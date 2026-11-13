import json
import logging
import os
import signal
import threading
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from . import externos, gemelos
from .base import EnlaceHttp, EnlaceMqtt, correr
from .modelo import Galpon, motor

RAIZ = Path(__file__).resolve().parents[2]
log = logging.getLogger("granja.dispositivos")


def entorno(nombre, defecto=""):
    return os.environ.get(nombre, defecto)


def escuchar_clima(galpon, host, puerto, usuario, clave, tls):
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="motor-gemelo-galpon1")
    if usuario:
        cliente.username_pw_set(usuario, clave)
    if tls:
        cliente.tls_set()

    def al_conectar(c, datos, banderas, codigo, propiedades=None):
        if not codigo.is_failure:
            c.subscribe("granja/clima-openmeteo/telemetria", qos=1)

    def al_recibir(c, datos, mensaje):
        if mensaje.topic != "granja/clima-openmeteo/telemetria":
            return
        try:
            carga = json.loads(mensaje.payload)
            galpon.recibir_clima(carga["valores"], datetime.fromisoformat(carga["ts"]))
        except (ValueError, KeyError):
            pass

    cliente.on_connect, cliente.on_message = al_conectar, al_recibir
    cliente.connect_async(host, puerto, keepalive=30)
    cliente.loop_start()
    return cliente


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    catalogo = json.loads((RAIZ / "comun" / "catalogo.json").read_text(encoding="utf-8"))
    granja = catalogo["granja"]
    estado = Path(entorno("CARPETA_ESTADO", str(RAIZ / "estado")))
    host = entorno("MQTT_HOST", "localhost")
    puerto = int(entorno("MQTT_PUERTO", "1883"))
    puerto_ws = int(entorno("MQTT_WS_PUERTO", "9001"))
    ruta_ws = entorno("MQTT_WS_RUTA", "/mqtt")
    tls = entorno("MQTT_TLS") == "1"
    tls_ws = entorno("MQTT_WS_TLS", entorno("MQTT_TLS")) == "1"
    usuario, clave = entorno("MQTT_USUARIO") or None, entorno("MQTT_CLAVE") or None
    api = entorno("API_URL", "http://localhost:8000")
    clave_http = entorno("DISPOSITIVOS_CLAVE")
    solo = {x.strip() for x in entorno("SOLO").split(",") if x.strip()}

    galpon = Galpon(granja["aves"], estado / "galpon1.json")

    def mqtt_tcp(d):
        return EnlaceMqtt(d, host, puerto, usuario=usuario, clave=clave, tls=tls)

    def mqtt_ws(d):
        return EnlaceMqtt(d, host, puerto_ws, websockets=True, ruta=ruta_ws, usuario=usuario, clave=clave, tls=tls_ws)

    def http(d):
        return EnlaceHttp(d, api, clave_http)

    fabricas = {
        "galpon1-ambiente": lambda: (gemelos.Ambiente("galpon1-ambiente", estado, galpon), mqtt_tcp),
        "galpon1-gases": lambda: (gemelos.Gases("galpon1-gases", estado, galpon), mqtt_tcp),
        "galpon1-ventilacion": lambda: (gemelos.Ventilacion("galpon1-ventilacion", estado, galpon), mqtt_tcp),
        "galpon1-iluminacion": lambda: (gemelos.Iluminacion("galpon1-iluminacion", estado, galpon), mqtt_ws),
        "tanque-agua": lambda: (gemelos.Tanque("tanque-agua", estado, galpon), mqtt_ws),
        "tablero-energia": lambda: (gemelos.Energia("tablero-energia", estado, galpon), mqtt_tcp),
        "contador-huevos": lambda: (gemelos.ContadorHuevos("contador-huevos", estado, galpon), http),
        "silo-alimento": lambda: (gemelos.Silo("silo-alimento", estado, galpon), http),
        "clima-openmeteo": lambda: (
            externos.OpenMeteo("clima-openmeteo", estado, granja["latitud"], granja["longitud"]), mqtt_tcp),
        "clima-azure-maps": lambda: (
            externos.AzureMaps("clima-azure-maps", estado, granja["latitud"], granja["longitud"],
                               entorno("AZURE_MAPS_CLAVE")), http),
        "historico-era5": lambda: (
            externos.HistoricoEra5("historico-era5", estado, RAIZ / "datos" / "era5_2025.csv"), mqtt_tcp),
        "pasarela-finca": lambda: (externos.Pasarela("pasarela-finca", estado, host, puerto), mqtt_tcp),
    }
    elegidos = [n for n in fabricas if not solo or n in solo]
    parar = threading.Event()
    hilos = []
    usa_galpon = any(n not in ("clima-openmeteo", "clima-azure-maps", "historico-era5", "pasarela-finca")
                     for n in elegidos)
    if usa_galpon:
        escuchar_clima(galpon, host, puerto, usuario, clave, tls)
        hilos.append(threading.Thread(target=motor, args=(galpon, parar), name="motor", daemon=True))
    for nombre in elegidos:
        dispositivo, fabrica_enlace = fabricas[nombre]()
        enlace = fabrica_enlace(dispositivo)
        hilos.append(threading.Thread(target=correr, args=(dispositivo, enlace, parar), name=nombre, daemon=True))
    for hilo in hilos:
        hilo.start()
    log.info("Corriendo %d dispositivos: %s", len(elegidos), ", ".join(elegidos))

    signal.signal(signal.SIGINT, lambda *a: parar.set())
    signal.signal(signal.SIGTERM, lambda *a: parar.set())
    while not parar.wait(1):
        pass
    galpon.guardar()


if __name__ == "__main__":
    main()
