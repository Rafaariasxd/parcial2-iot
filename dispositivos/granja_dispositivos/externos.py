import csv
import logging
import socket
import time
from bisect import bisect_right
from datetime import datetime, timedelta

import httpx
import psutil

from .base import Dispositivo
from .modelo import COLOMBIA

log = logging.getLogger("granja.dispositivos")


class OpenMeteo(Dispositivo):
    intervalo = 600
    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, dispositivo_id, carpeta_estado, latitud, longitud, galpon=None):
        self.latitud, self.longitud, self.galpon = latitud, longitud, galpon
        self.http = httpx.Client(timeout=20)
        super().__init__(dispositivo_id, carpeta_estado)

    def medir(self, momento):
        r = self.http.get(self.URL, params={
            "latitude": self.latitud,
            "longitude": self.longitud,
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,shortwave_radiation,cloud_cover",
            "timezone": "America/Bogota",
        })
        r.raise_for_status()
        actual = r.json()["current"]
        valores = {
            "temperatura": float(actual["temperature_2m"]),
            "humedad": float(actual["relative_humidity_2m"]),
            "lluvia": float(actual["precipitation"]),
            "viento": float(actual["wind_speed_10m"]),
            "radiacion": float(actual["shortwave_radiation"]),
            "nubosidad": float(actual["cloud_cover"]),
        }
        if self.galpon is not None:
            self.galpon.recibir_clima(valores, momento)
        return valores


class AzureMaps(Dispositivo):
    intervalo = 900
    URL = "https://atlas.microsoft.com/weather/currentConditions/json"

    def __init__(self, dispositivo_id, carpeta_estado, latitud, longitud, clave):
        self.consulta, self.clave = f"{latitud},{longitud}", clave
        self.http = httpx.Client(timeout=20)
        super().__init__(dispositivo_id, carpeta_estado)

    def medir(self, momento):
        if not self.clave:
            log.warning("%s: falta AZURE_MAPS_CLAVE", self.id)
            return {}
        r = self.http.get(self.URL, params={
            "api-version": "1.1",
            "query": self.consulta,
            "language": "es-419",
            "subscription-key": self.clave,
        })
        r.raise_for_status()
        a = r.json()["results"][0]
        return {
            "temperatura": float(a["temperature"]["value"]),
            "sensacion": float(a["realFeelTemperature"]["value"]),
            "humedad": float(a["relativeHumidity"]),
            "punto_rocio": float(a["dewPoint"]["value"]),
            "indice_uv": float(a["uvIndex"]),
            "nubosidad": float(a["cloudCover"]),
        }


class HistoricoEra5(Dispositivo):
    intervalo = 300
    COLUMNAS = {"temperatura": "temperature_2m", "humedad": "relative_humidity_2m", "lluvia": "precipitation",
                "radiacion": "shortwave_radiation"}

    def __init__(self, dispositivo_id, carpeta_estado, archivo_csv):
        with open(archivo_csv, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        self.horas = [datetime.fromisoformat(f["time"]).replace(tzinfo=COLOMBIA) for f in filas]
        self.filas = filas
        super().__init__(dispositivo_id, carpeta_estado)
        self.estado.setdefault("desfase_dias", 365)

    def extra_estado(self):
        return {"archivo": "datos/era5_2025.csv", "filas": len(self.filas)}

    def medir(self, momento):
        objetivo = momento.astimezone(COLOMBIA) - timedelta(days=self.estado["desfase_dias"])
        i = bisect_right(self.horas, objetivo) - 1
        if i < 0 or i + 1 >= len(self.horas):
            log.warning("%s: %s está fuera del dataset", self.id, objetivo.isoformat())
            return {}
        fraccion = (objetivo - self.horas[i]).total_seconds() / 3600
        valores = {}
        for nombre, columna in self.COLUMNAS.items():
            a, b = float(self.filas[i][columna]), float(self.filas[i + 1][columna])
            valores[nombre] = a if nombre == "lluvia" else a + (b - a) * fraccion
        return valores

    def accion_desfase(self, p):
        dias = int(p["dias"])
        if not 0 <= dias <= 400:
            raise ValueError("El desfase va de 0 a 400 días")
        self.estado["desfase_dias"] = dias
        return f"Reproduce el clima de hace {dias} días"


class Pasarela(Dispositivo):
    intervalo = 60

    def __init__(self, dispositivo_id, carpeta_estado, host, puerto):
        self.destino = (host, puerto)
        super().__init__(dispositivo_id, carpeta_estado)
        psutil.cpu_percent(interval=None)

    def latencia(self):
        muestras = []
        for _ in range(3):
            inicio = time.perf_counter()
            try:
                with socket.create_connection(self.destino, timeout=5):
                    muestras.append((time.perf_counter() - inicio) * 1000)
            except OSError:
                muestras.append(5000.0)
        return sorted(muestras)[1]

    def medir(self, momento):
        return {
            "latencia": self.latencia(),
            "cpu": psutil.cpu_percent(interval=None),
            "memoria": psutil.virtual_memory().percent,
            "encendido_horas": (time.time() - psutil.boot_time()) / 3600,
        }
