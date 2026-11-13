import json
import logging
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt

log = logging.getLogger("granja.dispositivos")


def ahora_utc():
    return datetime.now(timezone.utc)


def ruido(sigma):
    return random.gauss(0, sigma)


class Dispositivo:
    intervalo = 60
    variables = ()

    def __init__(self, dispositivo_id, carpeta_estado):
        self.id = dispositivo_id
        self.archivo = Path(carpeta_estado) / f"{dispositivo_id}.json"
        self.candado = threading.Lock()
        self.despertar = threading.Event()
        self.estado = {"encendido": True, "intervalo_s": self.intervalo, "calibracion": {}}
        if self.archivo.exists():
            try:
                self.estado.update(json.loads(self.archivo.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        self.restaurar(self.estado)

    def restaurar(self, estado):
        pass

    def medir(self, momento):
        raise NotImplementedError

    def extra_estado(self):
        return {}

    def guardar(self):
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")

    def estado_publico(self):
        return {**self.estado, **self.extra_estado()}

    def lectura(self, momento):
        crudos = self.medir(momento)
        salida = {}
        for nombre, valor in crudos.items():
            ajuste = self.estado["calibracion"].get(nombre)
            if ajuste and isinstance(valor, (int, float)):
                valor = valor * ajuste.get("factor", 1) + ajuste.get("offset", 0)
            salida[nombre] = round(valor, 3) if isinstance(valor, float) else valor
        return salida

    def ejecutar(self, accion, parametros):
        with self.candado:
            if accion == "apagar":
                self.estado["encendido"] = False
                mensaje = "Sensor apagado: deja de medir pero sigue escuchando comandos"
            elif accion == "encender":
                self.estado["encendido"] = True
                mensaje = "Sensor encendido"
            elif accion == "intervalo":
                self.estado["intervalo_s"] = int(parametros["segundos"])
                mensaje = f"Intervalo de envío: {self.estado['intervalo_s']} s"
            elif accion == "calibrar":
                variable = parametros["variable"]
                ajuste = {"offset": float(parametros.get("offset", 0)), "factor": float(parametros.get("factor", 1))}
                self.estado["calibracion"][variable] = ajuste
                mensaje = f"{variable} calibrada: valor × {ajuste['factor']} + {ajuste['offset']}"
            elif accion == "reiniciar_calibracion":
                self.estado["calibracion"] = {}
                mensaje = "Calibración de fábrica"
            else:
                manejador = getattr(self, f"accion_{accion}", None)
                if manejador is None:
                    raise ValueError(f"Acción desconocida: {accion}")
                mensaje = manejador(parametros)
            self.guardar()
        self.despertar.set()
        return mensaje


class Enlace:
    def __init__(self, dispositivo):
        self.dispositivo = dispositivo

    def iniciar(self):
        pass

    def enviar(self, valores, momento):
        raise NotImplementedError

    def sondear(self):
        pass

    def responder(self, comando):
        try:
            mensaje = self.dispositivo.ejecutar(comando["accion"], comando.get("parametros") or {})
            ok = True
        except (ValueError, KeyError, TypeError) as error:
            mensaje, ok = f"No se pudo: {error}", False
        log.info("%s ejecutó %s: %s", self.dispositivo.id, comando.get("accion"), mensaje)
        return {"comando_id": comando.get("id"), "ok": ok, "mensaje": mensaje,
                "estado": self.dispositivo.estado_publico()}


class EnlaceMqtt(Enlace):
    def __init__(self, dispositivo, host, puerto, websockets=False, ruta="/mqtt", usuario=None, clave=None, tls=False):
        super().__init__(dispositivo)
        self.base = f"granja/{dispositivo.id}"
        self.cliente = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=dispositivo.id,
            transport="websockets" if websockets else "tcp",
        )
        if websockets:
            self.cliente.ws_set_options(path=ruta)
        if tls:
            self.cliente.tls_set()
        if usuario:
            self.cliente.username_pw_set(usuario, clave)
        self.cliente.will_set(f"{self.base}/conexion", "desconectado", qos=1, retain=True)
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_message = self._al_recibir
        self.cliente.reconnect_delay_set(1, 60)
        self.cliente.max_queued_messages_set(5000)
        self.host, self.puerto = host, puerto

    def iniciar(self):
        self.cliente.connect_async(self.host, self.puerto, keepalive=30)
        self.cliente.loop_start()

    def _al_conectar(self, cliente, datos, banderas, codigo, propiedades=None):
        if codigo.is_failure:
            log.warning("%s: el bróker rechazó la conexión (%s)", self.dispositivo.id, codigo)
            return
        cliente.publish(f"{self.base}/conexion", "en_linea", qos=1, retain=True)
        cliente.subscribe(f"{self.base}/cmd", qos=1)
        self.publicar_estado()

    def publicar_estado(self):
        self.cliente.publish(f"{self.base}/estado", json.dumps(self.dispositivo.estado_publico(), ensure_ascii=False),
                             qos=1, retain=True)

    def _al_recibir(self, cliente, datos, mensaje):
        if mensaje.topic != f"{self.base}/cmd" or mensaje.retain:
            return
        try:
            comando = json.loads(mensaje.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(comando, dict) or not comando.get("accion"):
            return
        respuesta = self.responder(comando)
        cliente.publish(f"{self.base}/respuesta", json.dumps(respuesta, ensure_ascii=False), qos=1)
        self.publicar_estado()

    def enviar(self, valores, momento):
        carga = {"ts": momento.isoformat(timespec="seconds"), "valores": valores}
        self.cliente.publish(f"{self.base}/telemetria", json.dumps(carga), qos=1)


class EnlaceHttp(Enlace):
    def __init__(self, dispositivo, url_api, clave=""):
        super().__init__(dispositivo)
        self.url = url_api.rstrip("/")
        self.http = httpx.Client(timeout=15, headers={"X-Clave": clave} if clave else {})

    def iniciar(self):
        self._estado()

    def _estado(self):
        try:
            self.http.put(f"{self.url}/api/dispositivos/{self.dispositivo.id}/estado",
                          json=self.dispositivo.estado_publico())
        except httpx.HTTPError as error:
            log.warning("%s: sin conexión con la API (%s)", self.dispositivo.id, error)

    def _atender(self, comandos):
        for comando in comandos:
            respuesta = self.responder(comando)
            self.http.post(f"{self.url}/api/dispositivos/{self.dispositivo.id}/respuestas", json=respuesta)

    def enviar(self, valores, momento):
        try:
            r = self.http.post(f"{self.url}/api/telemetria/{self.dispositivo.id}",
                               json={"ts": momento.isoformat(timespec="seconds"), "valores": valores})
            r.raise_for_status()
            self._atender(r.json().get("comandos", []))
        except httpx.HTTPError as error:
            log.warning("%s: no se pudo enviar (%s)", self.dispositivo.id, error)

    def sondear(self):
        try:
            r = self.http.get(f"{self.url}/api/dispositivos/{self.dispositivo.id}/pendientes")
            r.raise_for_status()
            self._atender(r.json())
            self._estado()
        except httpx.HTTPError as error:
            log.warning("%s: no se pudo consultar comandos (%s)", self.dispositivo.id, error)


def correr(dispositivo, enlace, parar):
    enlace.iniciar()
    parar.wait(random.uniform(0, 5))
    while not parar.is_set():
        try:
            if dispositivo.estado["encendido"]:
                momento = ahora_utc()
                valores = dispositivo.lectura(momento)
                if valores:
                    enlace.enviar(valores, momento)
            else:
                enlace.sondear()
        except Exception:
            log.exception("%s: error en el ciclo", dispositivo.id)
        espera = dispositivo.estado["intervalo_s"]
        if isinstance(enlace, EnlaceHttp) and not dispositivo.estado["encendido"]:
            espera = min(espera, 30)
        dispositivo.despertar.wait(espera)
        dispositivo.despertar.clear()
        time.sleep(0.05)
