from .base import Dispositivo, ruido
from .modelo import limitar


class Gemelo(Dispositivo):
    def __init__(self, dispositivo_id, carpeta_estado, galpon):
        self.galpon = galpon
        super().__init__(dispositivo_id, carpeta_estado)


class Ambiente(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        t = g["t_int"] + ruido(0.15)
        h = limitar(g["h_int"] + ruido(0.8), 0, 100)
        thi = 0.8 * t + (h / 100) * (t - 14.4) + 46.4
        return {"temperatura": t, "humedad": h, "indice_thi": thi}


class Gases(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        return {"amoniaco": max(0.0, g["nh3"] + ruido(0.6)), "co2": max(400.0, g["co2"] + ruido(35))}


class Ventilacion(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        v = g["vent"]
        return {"velocidad": v, "modo_auto": int(g["vent_auto"]), "potencia": 1.6 * (v / 100) ** 1.5}

    def extra_estado(self):
        g = self.galpon.lectura()
        return {"modo": "auto" if g["vent_auto"] else "manual", "velocidad_manual": g["vent_manual"]}

    def accion_velocidad(self, p):
        valor = float(p["valor"])
        if not 0 <= valor <= 100:
            raise ValueError("La velocidad va de 0 a 100")
        with self.galpon.candado:
            self.galpon.s["vent_auto"] = False
            self.galpon.s["vent_manual"] = valor
        self.galpon.guardar()
        return f"Modo manual a {valor:.0f} %"

    def accion_modo(self, p):
        auto = bool(p.get("auto", True))
        with self.galpon.candado:
            self.galpon.s["vent_auto"] = auto
        self.galpon.guardar()
        return "Modo automático por temperatura" if auto else "Modo manual"


class Iluminacion(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        lux = (38.0 if g["luces"] else 0.0) + g["radiacion"] * 0.11
        return {
            "luz": max(0.0, lux + ruido(1.5)),
            "luces": int(g["luces"]),
            "horas_luz": g["luz_apagado"] - g["luz_encendido"],
        }

    def extra_estado(self):
        g = self.galpon.lectura()
        return {"encendido_h": g["luz_encendido"], "apagado_h": g["luz_apagado"], "forzada": g["luz_forzada"]}

    def accion_horario(self, p):
        inicio, fin = float(p["encendido"]), float(p["apagado"])
        if not 0 <= inicio < fin <= 24:
            raise ValueError("El horario debe estar entre 0 y 24 y empezar antes de terminar")
        with self.galpon.candado:
            self.galpon.s["luz_encendido"], self.galpon.s["luz_apagado"] = inicio, fin
        self.galpon.guardar()
        return f"Luces de {inicio:g} a {fin:g} h ({fin - inicio:g} h de luz)"

    def accion_forzar(self, p):
        valor = p.get("valor")
        if valor not in (None, 0, 1, True, False):
            raise ValueError("valor debe ser 1, 0 o null para volver al horario")
        with self.galpon.candado:
            self.galpon.s["luz_forzada"] = None if valor is None else int(valor)
        self.galpon.guardar()
        return "Luces según horario" if valor is None else ("Luces forzadas encendidas" if valor else "Luces forzadas apagadas")


class Tanque(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        nivel = 100 * g["tanque"] / self.galpon.CAPACIDAD_TANQUE
        return {
            "nivel": limitar(nivel + ruido(0.2), 0, 100),
            "caudal": max(0.0, g["caudal"] + ruido(0.03)),
            "bomba": int(g["bomba"] and g["red"]),
            "consumo_dia": g["consumo_agua_dia"],
        }

    def extra_estado(self):
        g = self.galpon.lectura()
        return {"bomba_modo": g["bomba_modo"], "umbral_bajo": g["umbral_bajo"]}

    def accion_bomba(self, p):
        valor = p.get("valor", "auto")
        modos = {1: "encendida", 0: "apagada", True: "encendida", False: "apagada", "auto": "auto"}
        if valor not in modos:
            raise ValueError("valor debe ser 1, 0 o auto")
        with self.galpon.candado:
            self.galpon.s["bomba_modo"] = modos[valor]
        self.galpon.guardar()
        return f"Bomba {modos[valor]}"

    def accion_umbral(self, p):
        bajo = float(p["bajo"])
        if not 5 <= bajo <= 80:
            raise ValueError("El umbral va de 5 a 80 %")
        with self.galpon.candado:
            self.galpon.s["umbral_bajo"] = bajo
        self.galpon.guardar()
        return f"La bomba arranca bajo {bajo:g} %"


class Energia(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        if not g["red"]:
            return {"voltaje": 0.0, "corriente": 0.0, "potencia": 0.0, "red": 0}
        potencia = 0.35 + 1.6 * (g["vent"] / 100) ** 1.5 + (0.9 if g["luces"] else 0) + (1.1 if g["bomba"] else 0)
        potencia += abs(ruido(0.03))
        voltaje = 119 + ruido(1.6) - potencia * 0.8
        return {"voltaje": voltaje, "corriente": potencia * 1000 / voltaje, "potencia": potencia, "red": 1}

    def accion_simular_corte(self, p):
        minutos = float(p.get("minutos", 10))
        if not 1 <= minutos <= 120:
            raise ValueError("El corte va de 1 a 120 minutos")
        self.galpon.cortar_luz(minutos)
        self.galpon.guardar()
        return f"Corte de luz simulado por {minutos:g} min"


class ContadorHuevos(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        if g["avance_postura"] > 0.35 and g["aves"]:
            postura = 100 * g["huevos_dia"] / (g["aves"] * g["avance_postura"])
        else:
            postura = g["postura_ayer"]
        return {
            "huevos_hora": max(0.0, g["huevos_hora"]),
            "huevos_dia": float(round(g["huevos_dia"])),
            "postura": limitar(postura, 0, 100),
            "peso_promedio": 62.4 - 0.25 * max(0.0, g["t_prom"] - 26) + ruido(0.35),
            "rotos_dia": float(round(g["rotos_dia"])),
        }

    def accion_aves(self, p):
        aves = int(p["valor"])
        if not 0 <= aves <= 6000:
            raise ValueError("El galpón tiene capacidad para 6.000 aves")
        with self.galpon.candado:
            self.galpon.s["aves"] = aves
        self.galpon.guardar()
        return f"Lote con {aves} aves"


class Silo(Gemelo):
    def medir(self, momento):
        g = self.galpon.lectura()
        nivel = max(0.0, g["silo"] + ruido(4))
        return {"nivel": nivel, "consumo_hora": max(0.0, g["consumo_silo_h"] + ruido(0.4)), "bultos": nivel / 40}

    def accion_llenado(self, p):
        kg = float(p["kg"])
        if not 0 < kg <= self.galpon.CAPACIDAD_SILO:
            raise ValueError("Cantidad inválida")
        with self.galpon.candado:
            self.galpon.s["silo"] = min(self.galpon.CAPACIDAD_SILO, self.galpon.s["silo"] + kg)
        self.galpon.guardar()
        return f"Llegaron {kg:g} kg ({kg / 40:g} bultos)"
