import json
import math
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

COLOMBIA = timezone(timedelta(hours=-5))


def limitar(valor, minimo, maximo):
    return max(minimo, min(maximo, valor))


def acercar(actual, objetivo, dt, tau):
    return actual + (objetivo - actual) * (1 - math.exp(-dt / tau))


class Galpon:
    """Estado físico del galpón 1 que leen todos los gemelos."""

    CAPACIDAD_TANQUE = 5000.0
    CAPACIDAD_SILO = 8000.0

    def __init__(self, aves, archivo):
        self.candado = threading.RLock()
        self.archivo = Path(archivo)
        self.clima = None
        self.s = {
            "aves": aves,
            "t_int": 26.0,
            "h_int": 72.0,
            "nh3": 9.0,
            "co2": 1100.0,
            "vent": 40.0,
            "vent_auto": True,
            "vent_manual": 60.0,
            "luz_encendido": 4.0,
            "luz_apagado": 20.0,
            "luz_forzada": None,
            "tanque": 3800.0,
            "bomba_modo": "auto",
            "bomba": False,
            "umbral_bajo": 35.0,
            "consumo_agua_dia": 0.0,
            "silo": 5200.0,
            "pedido_silo": None,
            "huevos_dia": 0.0,
            "rotos_dia": 0.0,
            "postura_ayer": 93.5,
            "dia": None,
            "corte_hasta": None,
            "t_prom": 26.0,
        }
        self.caudal = 0.0
        self.consumo_silo_h = 0.0
        self.huevos_hora = 0.0
        if self.archivo.exists():
            try:
                self.s.update(json.loads(self.archivo.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    def guardar(self):
        with self.candado:
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            self.archivo.write_text(json.dumps(self.s, ensure_ascii=False, indent=1), encoding="utf-8")

    def recibir_clima(self, valores, momento):
        with self.candado:
            self.clima = {"momento": momento, **valores}

    def exterior(self, local):
        hora = local.hour + local.minute / 60
        if self.clima and (datetime.now(timezone.utc) - self.clima["momento"]).total_seconds() < 3600:
            return self.clima.get("temperatura", 24.0), self.clima.get("humedad", 75.0), self.clima.get("radiacion", 0.0)
        temperatura = 24.5 + 5.0 * math.sin(2 * math.pi * (hora - 9) / 24)
        humedad = 74 - 16 * math.sin(2 * math.pi * (hora - 9) / 24)
        radiacion = max(0.0, 850 * math.sin(math.pi * (hora - 6) / 12)) if 6 <= hora <= 18 else 0.0
        return temperatura, humedad, radiacion

    def hay_red(self, ahora):
        hasta = self.s["corte_hasta"]
        return not (hasta and ahora < datetime.fromisoformat(hasta))

    def luces_encendidas(self, local, red):
        if not red:
            return False
        if self.s["luz_forzada"] is not None:
            return bool(self.s["luz_forzada"])
        hora = local.hour + local.minute / 60
        return self.s["luz_encendido"] <= hora < self.s["luz_apagado"]

    def cortar_luz(self, minutos):
        with self.candado:
            fin = datetime.now(timezone.utc) + timedelta(minutes=minutos)
            self.s["corte_hasta"] = fin.isoformat()

    def avanzar(self, dt):
        with self.candado:
            ahora = datetime.now(timezone.utc)
            local = ahora.astimezone(COLOMBIA)
            s = self.s
            dia = local.date().isoformat()
            if s["dia"] != dia:
                primera_vez = s["dia"] is None
                if not primera_vez and s["aves"]:
                    s["postura_ayer"] = round(100 * s["huevos_dia"] / s["aves"], 1)
                s["dia"], s["huevos_dia"], s["rotos_dia"], s["consumo_agua_dia"] = dia, 0.0, 0.0, 0.0
                if primera_vez:
                    avance = self.avance_postura(local)
                    s["huevos_dia"] = s["aves"] * s["postura_ayer"] / 100 * avance
                    s["rotos_dia"] = s["huevos_dia"] * 0.008

            if self.hay_red(ahora) and random.random() < dt / (2.2 * 86400):
                self.cortar_luz(random.uniform(6, 45))
            red = self.hay_red(ahora)
            t_ext, h_ext, rad = self.exterior(local)

            if not red:
                objetivo_vent = 0.0
            elif s["vent_auto"]:
                objetivo_vent = limitar(20 + (s["t_int"] - 24) * 14 + max(0, s["nh3"] - 18) * 4, 20, 100)
            else:
                objetivo_vent = s["vent_manual"]
            s["vent"] = acercar(s["vent"], objetivo_vent, dt, 60)
            v = s["vent"] / 100

            calor_aves = 4.2 * s["aves"] / 4800
            objetivo_t = t_ext + calor_aves * (1 - 0.65 * v) + rad / 1000 * 1.4
            s["t_int"] = acercar(s["t_int"], objetivo_t, dt, 1200)
            objetivo_h = limitar(h_ext + 7 - 13 * v, 35, 98)
            s["h_int"] = acercar(s["h_int"], objetivo_h, dt, 1500)
            s["t_prom"] = acercar(s["t_prom"], s["t_int"], dt, 86400)

            dia_cama = local.timetuple().tm_yday
            cama = 1 + 0.18 * math.sin(dia_cama * 0.9)
            objetivo_nh3 = (3.5 + 31 * (1 - v) ** 1.6) * (1 + 0.03 * (s["t_int"] - 24)) * cama
            s["nh3"] = acercar(s["nh3"], max(1.0, objetivo_nh3), dt, 1800)
            luces = self.luces_encendidas(local, red)
            actividad = 1.0 if luces or rad > 50 else 0.75
            objetivo_co2 = 520 + 2700 * (1 - v) ** 1.4 * actividad
            s["co2"] = acercar(s["co2"], objetivo_co2, dt, 900)

            despiertas = luces or rad > 80
            litros_dia = s["aves"] * 0.22 * (1 + 0.035 * max(0.0, s["t_int"] - 22))
            self.caudal = litros_dia / (16 * 60) * (1.0 if despiertas else 0.08)
            s["tanque"] = max(0.0, s["tanque"] - self.caudal * dt / 60)
            s["consumo_agua_dia"] += self.caudal * dt / 60
            nivel = 100 * s["tanque"] / self.CAPACIDAD_TANQUE
            if s["bomba_modo"] == "auto":
                if nivel < s["umbral_bajo"]:
                    s["bomba"] = True
                elif nivel > 95:
                    s["bomba"] = False
            else:
                s["bomba"] = s["bomba_modo"] == "encendida"
            if s["bomba"] and red:
                s["tanque"] = min(self.CAPACIDAD_TANQUE, s["tanque"] + 55 * dt / 60)

            kg_dia = s["aves"] * 0.112 * (1 - 0.025 * max(0.0, s["t_int"] - 28))
            self.consumo_silo_h = kg_dia / 16 if despiertas else 0.0
            s["silo"] = max(0.0, s["silo"] - self.consumo_silo_h * dt / 3600)
            if s["silo"] < 1500 and not s["pedido_silo"]:
                s["pedido_silo"] = (local + timedelta(days=1)).date().isoformat()
            if s["pedido_silo"] and dia >= s["pedido_silo"] and local.hour >= 9:
                s["silo"] = min(self.CAPACIDAD_SILO, s["silo"] + 6000)
                s["pedido_silo"] = None

            postura = 0.935 - 0.012 * max(0.0, s["t_prom"] - 26) - 0.004 * max(0.0, s["nh3"] - 25)
            pico = s["luz_encendido"] + 4.5
            hora = local.hour + local.minute / 60
            fraccion_hora = math.exp(-((hora - pico) ** 2) / (2 * 1.8 ** 2)) / (1.8 * math.sqrt(2 * math.pi))
            self.huevos_hora = s["aves"] * postura * fraccion_hora * random.uniform(0.9, 1.1)
            nuevos = self.huevos_hora * dt / 3600
            s["huevos_dia"] += nuevos
            s["rotos_dia"] += nuevos * random.uniform(0.004, 0.012)

    def avance_postura(self, local):
        hora = local.hour + local.minute / 60
        pico = self.s["luz_encendido"] + 4.5
        return 0.5 * (1 + math.erf((hora - pico) / (1.8 * math.sqrt(2))))

    def lectura(self):
        with self.candado:
            ahora = datetime.now(timezone.utc)
            local = ahora.astimezone(COLOMBIA)
            red = self.hay_red(ahora)
            luces = self.luces_encendidas(local, red)
            _, _, rad = self.exterior(local)
            avance = self.avance_postura(local)
            return {**self.s, "red": red, "luces": luces, "radiacion": rad, "avance_postura": avance,
                    "caudal": self.caudal, "consumo_silo_h": self.consumo_silo_h, "huevos_hora": self.huevos_hora}


def motor(galpon, parar, paso=10):
    galpon.avanzar(0)
    contador = 0
    while not parar.wait(paso):
        galpon.avanzar(paso)
        contador += 1
        if contador % 30 == 0:
            galpon.guardar()
