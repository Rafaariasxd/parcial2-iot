import json
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, delete, func, insert, select, update

from . import db

CATALOGO = Path(os.environ.get("CATALOGO", Path(__file__).resolve().parents[2] / "comun" / "catalogo.json"))
OPERADORES = {
    ">": lambda v, u: v > u,
    "<": lambda v, u: v < u,
    ">=": lambda v, u: v >= u,
    "<=": lambda v, u: v <= u,
}


class ErrorDeDatos(ValueError):
    pass


class NoEncontrado(LookupError):
    pass


def ahora():
    return datetime.now(timezone.utc)


def utc(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def iso(ts):
    return utc(ts).isoformat(timespec="seconds") if ts else None


def via_de_comandos(protocolo):
    return "http" if protocolo.startswith("HTTP REST") else "mqtt"


def margen(umbral):
    return 0.0 if umbral in (0, 1) else abs(umbral) * 0.02


class Plataforma:
    def __init__(self, publicar=None):
        self.publicar = publicar or (lambda topico, carga, retener=False: None)
        self.catalogo = {}
        self.acciones_comunes = []
        self.granja = {}
        self.ultimos = {}
        self.reglas = []
        self.abiertas = {}

    def iniciar(self):
        db.crear_tablas()
        datos = json.loads(CATALOGO.read_text(encoding="utf-8"))
        self.granja = datos["granja"]
        self.acciones_comunes = datos["acciones_comunes"]
        self.catalogo = {d["id"]: d for d in datos["dispositivos"]}
        with db.candado, db.motor.begin() as c:
            existentes = set(c.scalars(select(db.dispositivos.c.id)))
            for d in datos["dispositivos"]:
                fila = {
                    "nombre": d["nombre"],
                    "categoria": d["categoria"],
                    "origen": d["origen"],
                    "protocolo": d["protocolo"],
                    "ubicacion": d["ubicacion"],
                    "descripcion": d["descripcion"],
                    "variables": json.dumps(d["variables"], ensure_ascii=False),
                    "acciones": json.dumps(d["acciones"], ensure_ascii=False),
                }
                if d["id"] in existentes:
                    c.execute(update(db.dispositivos).where(db.dispositivos.c.id == d["id"]).values(**fila))
                else:
                    c.execute(insert(db.dispositivos).values(id=d["id"], en_linea=False, **fila))
            if not c.scalar(select(func.count()).select_from(db.reglas)):
                for r in datos["reglas"]:
                    c.execute(
                        insert(db.reglas).values(
                            dispositivo=r["dispositivo"],
                            variable=r["variable"],
                            operador=r["operador"],
                            umbral=r["umbral"],
                            nivel=r["nivel"],
                            mensaje=r["mensaje"],
                            accion=json.dumps(r["accion"], ensure_ascii=False) if r.get("accion") else None,
                            activa=True,
                        )
                    )
        self._cargar_reglas()
        self._cargar_ultimos()

    def _cargar_reglas(self):
        with db.motor.connect() as c:
            self.reglas = [dict(r._mapping) for r in c.execute(select(db.reglas))]
            abiertas = c.execute(select(db.alertas).where(db.alertas.c.fin.is_(None)))
            self.abiertas = {a.regla: {"id": a.id, "extremo": a.valor_extremo} for a in abiertas}

    def _cargar_ultimos(self):
        desde = ahora() - timedelta(days=2)
        l = db.lecturas
        maximos = (
            select(l.c.dispositivo, l.c.variable, func.max(l.c.ts).label("ts"))
            .where(l.c.ts >= desde)
            .group_by(l.c.dispositivo, l.c.variable)
            .subquery()
        )
        consulta = select(l.c.dispositivo, l.c.variable, l.c.ts, l.c.valor).join(
            maximos,
            and_(l.c.dispositivo == maximos.c.dispositivo, l.c.variable == maximos.c.variable, l.c.ts == maximos.c.ts),
        )
        with db.motor.connect() as c:
            for fila in c.execute(consulta):
                self.ultimos.setdefault(fila.dispositivo, {})[fila.variable] = (utc(fila.ts), fila.valor)

    def dispositivo(self, dispositivo_id):
        try:
            return self.catalogo[dispositivo_id]
        except KeyError:
            raise NoEncontrado(f"No existe el dispositivo {dispositivo_id}") from None

    def registrar(self, dispositivo_id, valores, ts=None, via="mqtt"):
        d = self.dispositivo(dispositivo_id)
        if not isinstance(valores, dict) or not valores:
            raise ErrorDeDatos("Faltan valores")
        momento = ahora()
        if ts:
            try:
                propio = utc(ts)
                if momento - timedelta(days=7) < propio < momento + timedelta(minutes=5):
                    momento = propio
            except (TypeError, ValueError):
                pass
        limpios, ignorados = {}, []
        for nombre, valor in valores.items():
            if isinstance(valor, bool):
                valor = int(valor)
            if nombre in d["variables"] and isinstance(valor, (int, float)) and math.isfinite(valor):
                limpios[nombre] = float(valor)
            else:
                ignorados.append(nombre)
        if not limpios:
            raise ErrorDeDatos("Ninguna variable válida")
        with db.candado, db.motor.begin() as c:
            c.execute(
                insert(db.lecturas),
                [{"ts": momento, "dispositivo": dispositivo_id, "variable": k, "valor": v, "via": via} for k, v in limpios.items()],
            )
            self._marcar_conexion(c, dispositivo_id, True, momento)
        propios = self.ultimos.setdefault(dispositivo_id, {})
        for k, v in limpios.items():
            propios[k] = (momento, v)
        eventos = self._evaluar(dispositivo_id, limpios, momento)
        return {"guardadas": len(limpios), "ignoradas": ignorados, "alertas": eventos}

    def _marcar_conexion(self, c, dispositivo_id, en_linea, momento):
        actual = c.execute(select(db.dispositivos.c.en_linea).where(db.dispositivos.c.id == dispositivo_id)).scalar()
        valores = {"en_linea": en_linea}
        if en_linea:
            valores["ultimo_contacto"] = momento
        c.execute(update(db.dispositivos).where(db.dispositivos.c.id == dispositivo_id).values(**valores))
        if bool(actual) != en_linea:
            c.execute(insert(db.conexiones).values(ts=momento, dispositivo=dispositivo_id, en_linea=en_linea))

    def conexion(self, dispositivo_id, en_linea):
        self.dispositivo(dispositivo_id)
        with db.candado, db.motor.begin() as c:
            self._marcar_conexion(c, dispositivo_id, en_linea, ahora())

    def revisar_silencio(self):
        momento = ahora()
        with db.motor.connect() as c:
            filas = list(c.execute(select(db.dispositivos).where(db.dispositivos.c.en_linea.is_(True))))
        for fila in filas:
            estado = json.loads(fila.estado) if fila.estado else {}
            intervalo = estado.get("intervalo_s") or 60
            limite = max(3 * intervalo, 180)
            ultimo = utc(fila.ultimo_contacto)
            if estado.get("encendido") is False:
                continue
            if ultimo is None or (momento - ultimo).total_seconds() > limite:
                with db.candado, db.motor.begin() as c:
                    self._marcar_conexion(c, fila.id, False, momento)

    def _evaluar(self, dispositivo_id, valores, momento):
        eventos = []
        for r in self.reglas:
            if not r["activa"] or r["dispositivo"] != dispositivo_id or r["variable"] not in valores:
                continue
            v = valores[r["variable"]]
            cumple = OPERADORES[r["operador"]](v, r["umbral"])
            abierta = self.abiertas.get(r["id"])
            if cumple and not abierta:
                with db.candado, db.motor.begin() as c:
                    alerta_id = c.execute(
                        insert(db.alertas).values(
                            regla=r["id"],
                            dispositivo=dispositivo_id,
                            variable=r["variable"],
                            nivel=r["nivel"],
                            mensaje=r["mensaje"],
                            valor=v,
                            valor_extremo=v,
                            inicio=momento,
                        )
                    ).inserted_primary_key[0]
                self.abiertas[r["id"]] = {"id": alerta_id, "extremo": v}
                evento = {"tipo": "alerta", "id": alerta_id, "dispositivo": dispositivo_id, "variable": r["variable"],
                          "valor": v, "nivel": r["nivel"], "mensaje": r["mensaje"], "ts": iso(momento)}
                self.publicar("granja/alertas", evento)
                eventos.append(evento)
                if r["accion"]:
                    accion = json.loads(r["accion"])
                    try:
                        self.enviar_comando(accion["dispositivo"], accion["accion"], accion.get("parametros", {}),
                                            origen=f"regla {r['id']}")
                    except (ErrorDeDatos, NoEncontrado):
                        pass
            elif cumple and abierta:
                peor = max if r["operador"].startswith(">") else min
                extremo = peor(abierta["extremo"], v)
                if extremo != abierta["extremo"]:
                    abierta["extremo"] = extremo
                    with db.candado, db.motor.begin() as c:
                        c.execute(update(db.alertas).where(db.alertas.c.id == abierta["id"]).values(valor_extremo=extremo))
            elif abierta:
                m = margen(r["umbral"])
                salio = v <= r["umbral"] - m if r["operador"].startswith(">") else v >= r["umbral"] + m
                if salio:
                    with db.candado, db.motor.begin() as c:
                        c.execute(update(db.alertas).where(db.alertas.c.id == abierta["id"]).values(fin=momento))
                    del self.abiertas[r["id"]]
                    evento = {"tipo": "resuelta", "id": abierta["id"], "dispositivo": dispositivo_id,
                              "variable": r["variable"], "valor": v, "ts": iso(momento)}
                    self.publicar("granja/alertas", evento)
                    eventos.append(evento)
        return eventos

    def _validar_comando(self, d, accion, parametros):
        permitidas = self.acciones_comunes + d["acciones"]
        if accion not in permitidas:
            raise ErrorDeDatos(f"Acción no permitida. Opciones: {', '.join(permitidas)}")
        if not isinstance(parametros, dict):
            raise ErrorDeDatos("Los parámetros deben ser un objeto")
        if accion == "intervalo":
            s = parametros.get("segundos")
            if not isinstance(s, (int, float)) or not 5 <= s <= 3600:
                raise ErrorDeDatos("El intervalo va de 5 a 3600 segundos")
        if accion == "calibrar":
            if parametros.get("variable") not in d["variables"]:
                raise ErrorDeDatos("Variable a calibrar desconocida")
            for campo in ("offset", "factor"):
                valor = parametros.get(campo)
                if valor is not None and not isinstance(valor, (int, float)):
                    raise ErrorDeDatos(f"{campo} debe ser un número")
            if parametros.get("factor") == 0:
                raise ErrorDeDatos("El factor no puede ser 0")

    def enviar_comando(self, dispositivo_id, accion, parametros=None, origen="panel"):
        d = self.dispositivo(dispositivo_id)
        parametros = parametros or {}
        self._validar_comando(d, accion, parametros)
        comando = {"id": str(uuid.uuid4()), "accion": accion, "parametros": parametros, "ts": iso(ahora())}
        via = via_de_comandos(d["protocolo"])
        estado = "pendiente"
        if via == "mqtt":
            self.publicar(f"granja/{dispositivo_id}/cmd", comando)
            estado = "enviado"
        with db.candado, db.motor.begin() as c:
            c.execute(
                insert(db.comandos).values(
                    id=comando["id"],
                    ts=ahora(),
                    dispositivo=dispositivo_id,
                    accion=accion,
                    parametros=json.dumps(parametros, ensure_ascii=False),
                    origen=origen,
                    estado=estado,
                )
            )
        return {**comando, "dispositivo": dispositivo_id, "estado": estado, "via": via}

    def pendientes(self, dispositivo_id):
        self.dispositivo(dispositivo_id)
        with db.candado, db.motor.begin() as c:
            filas = list(
                c.execute(
                    select(db.comandos)
                    .where(db.comandos.c.dispositivo == dispositivo_id, db.comandos.c.estado == "pendiente")
                    .order_by(db.comandos.c.ts)
                )
            )
            if filas:
                c.execute(
                    update(db.comandos).where(db.comandos.c.id.in_([f.id for f in filas])).values(estado="enviado")
                )
        return [{"id": f.id, "accion": f.accion, "parametros": json.loads(f.parametros), "ts": iso(f.ts)} for f in filas]

    def respuesta(self, dispositivo_id, comando_id, ok, mensaje="", estado=None):
        self.dispositivo(dispositivo_id)
        with db.candado, db.motor.begin() as c:
            hecho = c.execute(
                update(db.comandos)
                .where(db.comandos.c.id == comando_id, db.comandos.c.dispositivo == dispositivo_id)
                .values(estado="confirmado" if ok else "fallido", respuesta=mensaje, ts_respuesta=ahora())
            ).rowcount
        if estado is not None:
            self.estado_reportado(dispositivo_id, estado)
        if not hecho:
            raise NoEncontrado("Comando desconocido")

    def estado_reportado(self, dispositivo_id, estado):
        self.dispositivo(dispositivo_id)
        if not isinstance(estado, dict):
            raise ErrorDeDatos("El estado debe ser un objeto")
        with db.candado, db.motor.begin() as c:
            c.execute(
                update(db.dispositivos)
                .where(db.dispositivos.c.id == dispositivo_id)
                .values(estado=json.dumps(estado, ensure_ascii=False))
            )

    def lista(self):
        with db.motor.connect() as c:
            filas = list(c.execute(select(db.dispositivos).order_by(db.dispositivos.c.id)))
        orden = list(self.catalogo)
        filas.sort(key=lambda f: orden.index(f.id) if f.id in orden else 99)
        return [self._dispositivo_json(f) for f in filas]

    def detalle(self, dispositivo_id):
        self.dispositivo(dispositivo_id)
        with db.motor.connect() as c:
            fila = c.execute(select(db.dispositivos).where(db.dispositivos.c.id == dispositivo_id)).one()
        return self._dispositivo_json(fila)

    def _dispositivo_json(self, f):
        return {
            "id": f.id,
            "nombre": f.nombre,
            "categoria": f.categoria,
            "origen": f.origen,
            "protocolo": f.protocolo,
            "ubicacion": f.ubicacion,
            "descripcion": f.descripcion,
            "variables": json.loads(f.variables),
            "acciones": self.acciones_comunes + json.loads(f.acciones),
            "en_linea": bool(f.en_linea),
            "ultimo_contacto": iso(f.ultimo_contacto),
            "estado": json.loads(f.estado) if f.estado else {},
            "ultimos": {k: {"ts": iso(ts), "valor": v} for k, (ts, v) in self.ultimos.get(f.id, {}).items()},
        }

    def serie(self, dispositivo_id, variable, desde, hasta, paso_s):
        d = self.dispositivo(dispositivo_id)
        if variable not in d["variables"]:
            raise NoEncontrado(f"{dispositivo_id} no mide {variable}")
        l = db.lecturas
        consulta = (
            select(l.c.ts, l.c.valor)
            .where(l.c.dispositivo == dispositivo_id, l.c.variable == variable, l.c.ts >= desde, l.c.ts <= hasta)
            .order_by(l.c.ts)
        )
        cubetas = {}
        with db.motor.connect() as c:
            for ts, valor in c.execute(consulta):
                clave = int(utc(ts).timestamp() // paso_s * paso_s)
                cubetas.setdefault(clave, []).append(valor)
        puntos = [
            {
                "ts": datetime.fromtimestamp(k, timezone.utc).isoformat(timespec="seconds"),
                "promedio": round(sum(vs) / len(vs), 3),
                "min": min(vs),
                "max": max(vs),
                "n": len(vs),
            }
            for k, vs in sorted(cubetas.items())
        ]
        resumen = None
        if puntos:
            n = sum(p["n"] for p in puntos)
            resumen = {
                "promedio": round(sum(p["promedio"] * p["n"] for p in puntos) / n, 3),
                "min": min(p["min"] for p in puntos),
                "max": max(p["max"] for p in puntos),
                "lecturas": n,
            }
        return {"dispositivo": dispositivo_id, "variable": variable, "unidad": d["variables"][variable]["unidad"],
                "paso_s": paso_s, "resumen": resumen, "puntos": puntos}

    def resumen(self, desde, hasta):
        l = db.lecturas
        consulta = (
            select(
                l.c.dispositivo,
                l.c.variable,
                func.avg(l.c.valor),
                func.min(l.c.valor),
                func.max(l.c.valor),
                func.count(),
            )
            .where(l.c.ts >= desde, l.c.ts <= hasta)
            .group_by(l.c.dispositivo, l.c.variable)
        )
        with db.motor.connect() as c:
            filas = list(c.execute(consulta))
        return [
            {
                "dispositivo": f[0],
                "variable": f[1],
                "unidad": self.catalogo.get(f[0], {}).get("variables", {}).get(f[1], {}).get("unidad", ""),
                "promedio": round(f[2], 3),
                "min": f[3],
                "max": f[4],
                "lecturas": f[5],
            }
            for f in filas
        ]

    def alertas(self, limite=100, abiertas=False):
        consulta = select(db.alertas).order_by(db.alertas.c.inicio.desc()).limit(limite)
        if abiertas:
            consulta = consulta.where(db.alertas.c.fin.is_(None))
        with db.motor.connect() as c:
            filas = list(c.execute(consulta))
        return [
            {**dict(f._mapping), "inicio": iso(f.inicio), "fin": iso(f.fin)}
            for f in filas
        ]

    def comandos(self, limite=100, dispositivo_id=None):
        consulta = select(db.comandos).order_by(db.comandos.c.ts.desc()).limit(limite)
        if dispositivo_id:
            consulta = consulta.where(db.comandos.c.dispositivo == dispositivo_id)
        with db.motor.connect() as c:
            filas = list(c.execute(consulta))
        return [
            {**dict(f._mapping), "parametros": json.loads(f.parametros), "ts": iso(f.ts), "ts_respuesta": iso(f.ts_respuesta)}
            for f in filas
        ]

    def conexiones(self, limite=200):
        consulta = select(db.conexiones).order_by(db.conexiones.c.ts.desc()).limit(limite)
        with db.motor.connect() as c:
            return [{**dict(f._mapping), "ts": iso(f.ts)} for f in c.execute(consulta)]

    def lista_reglas(self):
        return [{**r, "accion": json.loads(r["accion"]) if r["accion"] else None} for r in self.reglas]

    def guardar_regla(self, datos, regla_id=None):
        d = self.dispositivo(datos.get("dispositivo", ""))
        if datos.get("variable") not in d["variables"]:
            raise ErrorDeDatos("Variable desconocida")
        if datos.get("operador") not in OPERADORES:
            raise ErrorDeDatos("Operador inválido")
        if not isinstance(datos.get("umbral"), (int, float)):
            raise ErrorDeDatos("El umbral debe ser un número")
        fila = {
            "dispositivo": datos["dispositivo"],
            "variable": datos["variable"],
            "operador": datos["operador"],
            "umbral": float(datos["umbral"]),
            "nivel": datos.get("nivel") or "aviso",
            "mensaje": datos.get("mensaje") or f"{datos['variable']} {datos['operador']} {datos['umbral']}",
            "accion": json.dumps(datos["accion"], ensure_ascii=False) if datos.get("accion") else None,
            "activa": bool(datos.get("activa", True)),
        }
        with db.candado, db.motor.begin() as c:
            if regla_id is None:
                regla_id = c.execute(insert(db.reglas).values(**fila)).inserted_primary_key[0]
            elif not c.execute(update(db.reglas).where(db.reglas.c.id == regla_id).values(**fila)).rowcount:
                raise NoEncontrado("Regla desconocida")
            if not fila["activa"] or regla_id in self.abiertas:
                abierta = self.abiertas.pop(regla_id, None)
                if abierta:
                    c.execute(update(db.alertas).where(db.alertas.c.id == abierta["id"]).values(fin=ahora()))
        self._cargar_reglas()
        return next(r for r in self.lista_reglas() if r["id"] == regla_id)

    def borrar_regla(self, regla_id):
        with db.candado, db.motor.begin() as c:
            if not c.execute(delete(db.reglas).where(db.reglas.c.id == regla_id)).rowcount:
                raise NoEncontrado("Regla desconocida")
            c.execute(update(db.alertas).where(db.alertas.c.regla == regla_id, db.alertas.c.fin.is_(None)).values(fin=ahora()))
        self._cargar_reglas()
