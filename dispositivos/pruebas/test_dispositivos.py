from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from granja_dispositivos import gemelos, modelo
from granja_dispositivos.externos import HistoricoEra5

RAIZ = Path(__file__).resolve().parents[2]


class Reloj:
    def __init__(self, inicio):
        self.ahora = inicio

    def now(self, tz=None):
        return self.ahora if tz is None else self.ahora.astimezone(tz)

    def fromisoformat(self, texto):
        return datetime.fromisoformat(texto)


@pytest.fixture
def galpon(tmp_path):
    return modelo.Galpon(4800, tmp_path / "galpon.json")


def simular(galpon, horas, paso=60):
    reloj = Reloj(datetime(2026, 11, 13, 5, 0, tzinfo=timezone.utc))
    muestras = []
    with mock.patch.object(modelo, "datetime", reloj):
        galpon.avanzar(0)
        for _ in range(int(horas * 3600 / paso)):
            reloj.ahora += timedelta(seconds=paso)
            galpon.avanzar(paso)
            muestras.append(dict(galpon.lectura()))
    return muestras


def test_dos_dias_del_galpon_quedan_en_rangos_realistas(galpon):
    with mock.patch.object(modelo.random, "random", return_value=1.0):
        muestras = simular(galpon, 48)
    temperaturas = [m["t_int"] for m in muestras]
    assert 18 < min(temperaturas) < max(temperaturas) < 36
    assert all(0 < m["nh3"] < 50 for m in muestras)
    assert all(0 <= m["tanque"] <= modelo.Galpon.CAPACIDAD_TANQUE for m in muestras)
    posturas = [m["postura_ayer"] for m in muestras]
    assert 85 < posturas[-1] < 96


def test_corte_de_luz_apaga_ventiladores_y_bomba(galpon):
    galpon.s["bomba_modo"] = "encendida"
    galpon.cortar_luz(30)
    galpon.avanzar(600)
    lectura = galpon.lectura()
    assert not lectura["red"] and not lectura["luces"]
    assert lectura["vent"] < 40
    energia = gemelos.Energia("tablero-energia", galpon.archivo.parent, galpon)
    assert energia.medir(None)["red"] == 0


def test_calibracion_y_apagado_se_guardan(tmp_path, galpon):
    sensor = gemelos.Ambiente("galpon1-ambiente", tmp_path, galpon)
    sensor.ejecutar("calibrar", {"variable": "temperatura", "offset": -1.5, "factor": 1})
    sensor.ejecutar("apagar", {})
    otra_vez = gemelos.Ambiente("galpon1-ambiente", tmp_path, galpon)
    assert otra_vez.estado["encendido"] is False
    with mock.patch.object(gemelos, "ruido", return_value=0):
        assert otra_vez.lectura(None)["temperatura"] == pytest.approx(galpon.s["t_int"] - 1.5, abs=0.01)


def test_acciones_propias_validan_rangos(tmp_path, galpon):
    vent = gemelos.Ventilacion("galpon1-ventilacion", tmp_path, galpon)
    assert "manual" in vent.ejecutar("velocidad", {"valor": 70})
    assert galpon.s["vent_auto"] is False
    with pytest.raises(ValueError):
        vent.ejecutar("velocidad", {"valor": 150})
    luces = gemelos.Iluminacion("galpon1-iluminacion", tmp_path, galpon)
    with pytest.raises(ValueError):
        luces.ejecutar("horario", {"encendido": 20, "apagado": 4})


def test_dataset_era5_interpola_entre_horas(tmp_path):
    era5 = HistoricoEra5("historico-era5", tmp_path, RAIZ / "datos" / "era5_2025.csv")
    momento = datetime(2026, 11, 2, 9, 30, tzinfo=modelo.COLOMBIA)
    valores = era5.medir(momento)
    i = era5.horas.index(datetime(2025, 11, 2, 9, 0, tzinfo=modelo.COLOMBIA))
    a, b = float(era5.filas[i]["temperature_2m"]), float(era5.filas[i + 1]["temperature_2m"])
    assert valores["temperatura"] == pytest.approx((a + b) / 2)
