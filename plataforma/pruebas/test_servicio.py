from datetime import timedelta

import pytest
from sqlalchemy import delete

from granja_iot import db
from granja_iot.servicio import ErrorDeDatos, NoEncontrado, Plataforma, ahora


@pytest.fixture
def plataforma():
    db.crear_tablas()
    with db.motor.begin() as c:
        for tabla in (db.lecturas, db.alertas, db.comandos, db.reglas, db.conexiones, db.dispositivos):
            c.execute(delete(tabla))
    publicados = []
    p = Plataforma(lambda topico, carga, retener=False: publicados.append((topico, carga)))
    p.iniciar()
    p.publicados = publicados
    return p


def test_siembra_los_trece_dispositivos_y_las_reglas(plataforma):
    assert len(plataforma.lista()) == 13
    assert len(plataforma.lista_reglas()) >= 10


def test_registrar_guarda_solo_variables_declaradas(plataforma):
    r = plataforma.registrar("galpon1-ambiente", {"temperatura": 26.5, "humedad": 70, "inventada": 3, "texto": "x"})
    assert r["guardadas"] == 2
    assert set(r["ignoradas"]) == {"inventada", "texto"}
    d = plataforma.detalle("galpon1-ambiente")
    assert d["en_linea"] and d["ultimos"]["temperatura"]["valor"] == 26.5


def test_rechaza_dispositivo_desconocido_y_lecturas_vacias(plataforma):
    with pytest.raises(NoEncontrado):
        plataforma.registrar("intruso", {"temperatura": 20})
    with pytest.raises(ErrorDeDatos):
        plataforma.registrar("galpon1-ambiente", {"inventada": 1})


def test_fecha_del_dispositivo_fuera_de_rango_usa_la_hora_del_servidor(plataforma):
    plataforma.registrar("galpon1-ambiente", {"temperatura": 25}, ts="2001-01-01T00:00:00Z")
    ts = plataforma.detalle("galpon1-ambiente")["ultimos"]["temperatura"]["ts"]
    assert ts.startswith(str(ahora().year))


def test_regla_abre_una_sola_alerta_y_la_cierra_con_histeresis(plataforma):
    plataforma.registrar("galpon1-ambiente", {"temperatura": 31})
    plataforma.registrar("galpon1-ambiente", {"temperatura": 32})
    abiertas = plataforma.alertas(abiertas=True)
    assert len(abiertas) == 1 and abiertas[0]["valor_extremo"] == 32
    plataforma.registrar("galpon1-ambiente", {"temperatura": 29.8})
    assert len(plataforma.alertas(abiertas=True)) == 1
    plataforma.registrar("galpon1-ambiente", {"temperatura": 29.0})
    assert plataforma.alertas(abiertas=True) == []
    assert any(t == "granja/alertas" and c["tipo"] == "resuelta" for t, c in plataforma.publicados)


def test_regla_critica_manda_comando_a_otro_dispositivo(plataforma):
    plataforma.registrar("galpon1-gases", {"amoniaco": 30})
    comandos = plataforma.comandos(dispositivo_id="galpon1-ventilacion")
    assert comandos[0]["accion"] == "velocidad" and comandos[0]["parametros"] == {"valor": 100}
    assert comandos[0]["origen"].startswith("regla")
    assert ("granja/galpon1-ventilacion/cmd") in [t for t, _ in plataforma.publicados]


def test_corte_de_luz_dispara_con_valor_cero(plataforma):
    plataforma.registrar("tablero-energia", {"red": 0, "voltaje": 0})
    assert plataforma.alertas(abiertas=True)[0]["dispositivo"] == "tablero-energia"
    plataforma.registrar("tablero-energia", {"red": 1, "voltaje": 118})
    assert plataforma.alertas(abiertas=True) == []


def test_comando_mqtt_se_publica_y_se_confirma(plataforma):
    c = plataforma.enviar_comando("galpon1-iluminacion", "horario", {"encendido": 5, "apagado": 21})
    assert c["estado"] == "enviado" and c["via"] == "mqtt"
    plataforma.respuesta("galpon1-iluminacion", c["id"], True, "listo", {"encendido": True, "intervalo_s": 60})
    hecho = plataforma.comandos(dispositivo_id="galpon1-iluminacion")[0]
    assert hecho["estado"] == "confirmado" and hecho["respuesta"] == "listo"
    assert plataforma.detalle("galpon1-iluminacion")["estado"]["intervalo_s"] == 60


def test_comando_http_queda_pendiente_hasta_que_el_dispositivo_lo_pide(plataforma):
    c = plataforma.enviar_comando("silo-alimento", "llenado", {"kg": 400})
    assert c["estado"] == "pendiente"
    pendientes = plataforma.pendientes("silo-alimento")
    assert [p["id"] for p in pendientes] == [c["id"]]
    assert plataforma.pendientes("silo-alimento") == []


def test_valida_acciones_y_parametros(plataforma):
    with pytest.raises(ErrorDeDatos):
        plataforma.enviar_comando("galpon1-ambiente", "velocidad", {"valor": 3})
    with pytest.raises(ErrorDeDatos):
        plataforma.enviar_comando("galpon1-ambiente", "intervalo", {"segundos": 1})
    with pytest.raises(ErrorDeDatos):
        plataforma.enviar_comando("galpon1-ambiente", "calibrar", {"variable": "co2", "offset": 1})
    with pytest.raises(ErrorDeDatos):
        plataforma.enviar_comando("galpon1-ambiente", "calibrar", {"variable": "temperatura", "factor": 0})


def test_serie_agrupa_promedio_minimo_y_maximo(plataforma):
    base = ahora().replace(second=0, microsecond=0) - timedelta(minutes=30)
    for i, v in enumerate([20, 22, 24, 30]):
        plataforma.registrar("galpon1-ambiente", {"temperatura": v}, ts=(base + timedelta(seconds=10 * i)).isoformat())
    s = plataforma.serie("galpon1-ambiente", "temperatura", base - timedelta(minutes=1), ahora(), 3600)
    assert s["resumen"] == {"promedio": 24.0, "min": 20.0, "max": 30.0, "lecturas": 4}
    resumen = {(r["dispositivo"], r["variable"]): r for r in plataforma.resumen(base - timedelta(minutes=1), ahora())}
    assert resumen[("galpon1-ambiente", "temperatura")]["max"] == 30.0


def test_dispositivo_callado_queda_desconectado(plataforma):
    plataforma.registrar("silo-alimento", {"nivel": 4000}, ts=(ahora() - timedelta(minutes=10)).isoformat())
    plataforma.revisar_silencio()
    assert not plataforma.detalle("silo-alimento")["en_linea"]
    assert plataforma.conexiones()[0]["en_linea"] is False


def test_desactivar_regla_cierra_su_alerta(plataforma):
    plataforma.registrar("galpon1-ambiente", {"temperatura": 31})
    regla = next(r for r in plataforma.lista_reglas() if r["variable"] == "temperatura" and r["umbral"] == 30)
    plataforma.guardar_regla({**regla, "activa": False}, regla["id"])
    assert plataforma.alertas(abiertas=True) == []
