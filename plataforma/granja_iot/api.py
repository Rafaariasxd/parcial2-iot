import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .puente_mqtt import PuenteMqtt
from .servicio import ErrorDeDatos, NoEncontrado, Plataforma, ahora, utc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
WEB = Path(__file__).resolve().parents[1] / "web"
PANEL_CLAVE = os.environ.get("PANEL_CLAVE", "")
DISPOSITIVOS_CLAVE = os.environ.get("DISPOSITIVOS_CLAVE", "")

plataforma = Plataforma()
puente = PuenteMqtt(
    plataforma,
    os.environ.get("MQTT_HOST", "localhost"),
    int(os.environ.get("MQTT_PUERTO", "1883")),
    os.environ.get("MQTT_USUARIO") or None,
    os.environ.get("MQTT_CLAVE") or None,
)
plataforma.publicar = puente.publicar
parar = threading.Event()


def vigilar():
    while not parar.wait(60):
        try:
            plataforma.revisar_silencio()
        except Exception:
            logging.getLogger("granja").exception("Revisión de silencio")


@asynccontextmanager
async def ciclo(app):
    plataforma.iniciar()
    puente.iniciar()
    hilo = threading.Thread(target=vigilar, daemon=True)
    hilo.start()
    yield
    parar.set()
    puente.detener()


app = FastAPI(title="Granja IoT", version="1.0", lifespan=ciclo)


def es_admin(authorization: str = Header(default="")):
    if PANEL_CLAVE and not secrets.compare_digest(authorization, f"Bearer {PANEL_CLAVE}"):
        raise HTTPException(401, "Clave del panel incorrecta")


def es_dispositivo(x_clave: str = Header(default="")):
    if DISPOSITIVOS_CLAVE and not secrets.compare_digest(x_clave, DISPOSITIVOS_CLAVE):
        raise HTTPException(401, "Clave de dispositivo incorrecta")


def errores(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except NoEncontrado as error:
        raise HTTPException(404, str(error)) from None
    except ErrorDeDatos as error:
        raise HTTPException(422, str(error)) from None


def rango(desde, hasta, horas):
    fin = utc(hasta) if hasta else ahora()
    inicio = utc(desde) if desde else fin - timedelta(hours=horas)
    if inicio >= fin:
        raise HTTPException(422, "desde debe ser anterior a hasta")
    return inicio, fin


@app.get("/salud")
def salud():
    return {"ok": True, "mqtt": puente.conectado, "hora": ahora().isoformat(timespec="seconds")}


@app.get("/api/info")
def info():
    return {
        "granja": plataforma.granja,
        "grafana": os.environ.get("GRAFANA_URL", ""),
        "requiere_clave": bool(PANEL_CLAVE),
        "mqtt": puente.conectado,
    }


@app.get("/api/dispositivos")
def dispositivos():
    return plataforma.lista()


@app.get("/api/dispositivos/{dispositivo_id}")
def dispositivo(dispositivo_id: str):
    return errores(plataforma.detalle, dispositivo_id)


@app.get("/api/dispositivos/{dispositivo_id}/serie")
def serie(
    dispositivo_id: str,
    variable: str,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    horas: float = Query(24, gt=0, le=24 * 31),
    paso: int | None = Query(None, ge=10, le=86400),
):
    inicio, fin = rango(desde, hasta, horas)
    if paso is None:
        segundos = (fin - inicio).total_seconds()
        paso = max(60, int(segundos / 300) // 60 * 60)
    return errores(plataforma.serie, dispositivo_id, variable, inicio, fin, paso)


@app.get("/api/resumen")
def resumen(desde: datetime | None = None, hasta: datetime | None = None, horas: float = Query(24, gt=0)):
    inicio, fin = rango(desde, hasta, horas)
    return {"desde": inicio.isoformat(), "hasta": fin.isoformat(), "variables": plataforma.resumen(inicio, fin)}


@app.get("/api/alertas")
def alertas(limite: int = Query(100, ge=1, le=1000), abiertas: bool = False):
    return plataforma.alertas(limite, abiertas)


@app.get("/api/comandos")
def comandos(limite: int = Query(100, ge=1, le=1000), dispositivo: str | None = None):
    return plataforma.comandos(limite, dispositivo)


@app.get("/api/conexiones")
def conexiones(limite: int = Query(200, ge=1, le=2000)):
    return plataforma.conexiones(limite)


@app.post("/api/dispositivos/{dispositivo_id}/comandos", dependencies=[Depends(es_admin)], status_code=202)
def nuevo_comando(dispositivo_id: str, cuerpo: dict = Body(...)):
    return errores(plataforma.enviar_comando, dispositivo_id, cuerpo.get("accion"), cuerpo.get("parametros") or {})


@app.get("/api/reglas")
def reglas():
    return plataforma.lista_reglas()


@app.post("/api/reglas", dependencies=[Depends(es_admin)], status_code=201)
def nueva_regla(cuerpo: dict = Body(...)):
    return errores(plataforma.guardar_regla, cuerpo)


@app.put("/api/reglas/{regla_id}", dependencies=[Depends(es_admin)])
def cambiar_regla(regla_id: int, cuerpo: dict = Body(...)):
    return errores(plataforma.guardar_regla, cuerpo, regla_id)


@app.delete("/api/reglas/{regla_id}", dependencies=[Depends(es_admin)], status_code=204)
def borrar_regla(regla_id: int):
    errores(plataforma.borrar_regla, regla_id)


@app.post("/api/telemetria/{dispositivo_id}", dependencies=[Depends(es_dispositivo)])
def telemetria_http(dispositivo_id: str, cuerpo: dict = Body(...)):
    valores = cuerpo.get("valores")
    if valores is None:
        valores = {k: v for k, v in cuerpo.items() if k != "ts"}
    resultado = errores(plataforma.registrar, dispositivo_id, valores, cuerpo.get("ts"), "http")
    return {**resultado, "comandos": plataforma.pendientes(dispositivo_id)}


@app.get("/api/dispositivos/{dispositivo_id}/pendientes", dependencies=[Depends(es_dispositivo)])
def pendientes(dispositivo_id: str):
    return errores(plataforma.pendientes, dispositivo_id)


@app.post("/api/dispositivos/{dispositivo_id}/respuestas", dependencies=[Depends(es_dispositivo)])
def respuesta_http(dispositivo_id: str, cuerpo: dict = Body(...)):
    errores(
        plataforma.respuesta, dispositivo_id, cuerpo.get("comando_id"), bool(cuerpo.get("ok")),
        cuerpo.get("mensaje", ""), cuerpo.get("estado"),
    )
    return {"ok": True}


@app.put("/api/dispositivos/{dispositivo_id}/estado", dependencies=[Depends(es_dispositivo)])
def estado_http(dispositivo_id: str, cuerpo: dict = Body(...)):
    errores(plataforma.estado_reportado, dispositivo_id, cuerpo)
    return {"ok": True}


@app.get("/")
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/estatico", StaticFiles(directory=WEB), name="estatico")
