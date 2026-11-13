import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAIZ = Path(__file__).resolve().parents[1]
AQUI = Path(__file__).resolve().parent
GRAFICAS = AQUI / "graficas"
EVIDENCIAS = RAIZ / "evidencias"
MONTE = RGBColor(0x1E, 0x5B, 0x43)
COLOMBIA = timezone(timedelta(hours=-5))
COLORES = ["#1E5B43", "#F4B23E", "#3A6EA5", "#B3261E", "#7A4FA0", "#8A8F8C"]

parser = argparse.ArgumentParser()
parser.add_argument("--api", default="http://127.0.0.1:8000")
parser.add_argument("--desde", help="inicio del periodo, ISO")
parser.add_argument("--hasta", help="fin del periodo, ISO")
parser.add_argument("--url-publica", default="")
parser.add_argument("--github", default="")
args = parser.parse_args()

http = httpx.Client(base_url=args.api, timeout=120)
analisis_archivo = AQUI / "analisis.json"
ANALISIS = json.loads(analisis_archivo.read_text(encoding="utf-8")) if analisis_archivo.exists() else {}


def obtener(ruta, **params):
    r = http.get(ruta, params=params)
    r.raise_for_status()
    return r.json()


dispositivos = obtener("/api/dispositivos")
info = obtener("/api/info")
hasta = datetime.fromisoformat(args.hasta) if args.hasta else datetime.now(timezone.utc)
if args.desde:
    desde = datetime.fromisoformat(args.desde)
else:
    primeras = [obtener(f"/api/dispositivos/{d['id']}/serie", variable=next(iter(d["variables"])), horas=24 * 30,
                        paso=86400)["puntos"] for d in dispositivos]
    desde = min(datetime.fromisoformat(p[0]["ts"]) for p in primeras if p)
horas = (hasta - desde).total_seconds() / 3600
paso = 900 if horas > 48 else 300
resumen = {(v["dispositivo"], v["variable"]): v for v in
           obtener("/api/resumen", desde=desde.isoformat(), hasta=hasta.isoformat())["variables"]}
alertas = [a for a in obtener("/api/alertas", limite=1000) if desde.isoformat() <= a["inicio"] <= hasta.isoformat()]
comandos = [c for c in obtener("/api/comandos", limite=1000) if desde.isoformat() <= c["ts"] <= hasta.isoformat()]
conexiones = [c for c in obtener("/api/conexiones", limite=2000) if desde.isoformat() <= c["ts"] <= hasta.isoformat()]
reglas = obtener("/api/reglas")


def serie(d, variable):
    return obtener(f"/api/dispositivos/{d}/serie", variable=variable, desde=desde.isoformat(), hasta=hasta.isoformat(),
                   paso=paso)


def graficar(d):
    variables = list(d["variables"].items())
    fig, ejes = plt.subplots(len(variables), 1, figsize=(10, 1.9 * len(variables) + 0.6), sharex=True, squeeze=False)
    for i, (nombre, meta) in enumerate(variables):
        eje = ejes[i][0]
        s = serie(d["id"], nombre)
        if s["puntos"]:
            x = [datetime.fromisoformat(p["ts"]).astimezone(COLOMBIA).replace(tzinfo=None) for p in s["puntos"]]
            color = COLORES[i % len(COLORES)]
            eje.fill_between(x, [p["min"] for p in s["puntos"]], [p["max"] for p in s["puntos"]], color=color, alpha=0.18,
                             lw=0)
            eje.plot(x, [p["promedio"] for p in s["puntos"]], color=color, lw=1.2)
            for r in reglas:
                if r["dispositivo"] == d["id"] and r["variable"] == nombre and r["activa"]:
                    eje.axhline(r["umbral"], color="#B3261E" if r["nivel"] == "crítica" else "#F4B23E", ls="--", lw=0.9)
        eje.set_ylabel(f"{nombre.replace('_', ' ')}\n({meta['unidad'] or '—'})", fontsize=8)
        eje.tick_params(labelsize=7.5)
        eje.grid(alpha=0.3)
    ejes[-1][0].xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%H:%M"))
    fig.suptitle(f"{d['nombre']} · {d['categoria']} · {d['protocolo']}", fontsize=10, color="#1E5B43", fontweight="bold")
    fig.tight_layout()
    GRAFICAS.mkdir(exist_ok=True)
    salida = GRAFICAS / f"{d['id']}.png"
    fig.savefig(salida, dpi=150)
    plt.close(fig)
    return salida


def sombrear(celda, color):
    tcpr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcpr.append(shd)


def titulo(doc, texto, nivel=1):
    h = doc.add_heading(texto, level=nivel)
    for run in h.runs:
        run.font.color.rgb = MONTE
        run.font.name = "Calibri"
    return h


def parrafo(doc, texto, tam=10.5, cursiva=False, centrado=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    if centrado:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(texto)
    run.font.size = Pt(tam)
    run.italic = cursiva
    return p


def viñetas(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        if isinstance(item, tuple):
            p.add_run(item[0]).bold = True
            p.add_run(item[1])
        else:
            p.add_run(item)


def tabla(doc, encabezados, filas, anchos=None, tam=8.5):
    t = doc.add_table(rows=1, cols=len(encabezados))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, texto in enumerate(encabezados):
        celda = t.rows[0].cells[i]
        celda.text = ""
        run = celda.paragraphs[0].add_run(texto)
        run.bold = True
        run.font.size = Pt(tam)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        sombrear(celda, "1E5B43")
    for fila in filas:
        celdas = t.add_row().cells
        for i, valor in enumerate(fila):
            celdas[i].text = ""
            celdas[i].paragraphs[0].add_run(str(valor)).font.size = Pt(tam)
    if anchos:
        for fila in t.rows:
            for i, ancho in enumerate(anchos):
                fila.cells[i].width = Cm(ancho)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def num(v, decimales=2):
    if v is None:
        return "—"
    return f"{v:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def local(iso):
    return datetime.fromisoformat(iso).astimezone(COLOMBIA).strftime("%d/%m %H:%M") if iso else "—"


def imagen(doc, ruta, ancho=16.5, pie=None):
    if Path(ruta).exists():
        doc.add_picture(str(ruta), width=Cm(ancho))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if pie:
            parrafo(doc, pie, 9, cursiva=True, centrado=True)


doc = Document()
doc.core_properties.author = "Rafael Antonio Arias Monsalve"
doc.core_properties.title = "Parcial 2 - Galpón Conectado"
estilo = doc.styles["Normal"]
estilo.font.name = "Calibri"
estilo.font.size = Pt(10.5)
for seccion in doc.sections:
    seccion.top_margin = seccion.bottom_margin = Cm(2)
    seccion.left_margin = seccion.right_margin = Cm(2.2)

for _ in range(5):
    doc.add_paragraph()
imagen(doc, RAIZ / "plataforma" / "web" / "logo.png", 3.5)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Galpón Conectado")
r.bold, r.font.size, r.font.color.rgb = True, Pt(30), MONTE
parrafo(doc, "Monitoreo y control IoT de un galpón de gallinas ponedoras", 15, centrado=True)
parrafo(doc, "Parcial 2 · Proyecto final · IoT a la medida", 12, centrado=True)
doc.add_paragraph()
parrafo(doc, "Rafael Antonio Arias Monsalve", 13, centrado=True)
parrafo(doc, "Internet de las Cosas · Profesor Javier Pinzón\nUniversidad Autónoma de Bucaramanga (UNAB)", 11, centrado=True)
parrafo(doc, datetime.now(COLOMBIA).strftime("%d de %B de %Y").replace("November", "noviembre"), 11, centrado=True)
doc.add_paragraph()
if args.url_publica:
    parrafo(doc, f"URL: {args.url_publica}\nGrafana: {args.url_publica.rstrip('/')}/grafana", 10.5, centrado=True)
if args.github:
    parrafo(doc, f"Repositorio: {args.github}", 10.5, centrado=True)
parrafo(doc, f"Periodo de datos: {desde.astimezone(COLOMBIA):%d/%m/%Y %H:%M} a {hasta.astimezone(COLOMBIA):%d/%m/%Y %H:%M} "
             f"({horas / 24:.1f} días)", 10.5, centrado=True)
doc.paragraphs[-1].runs[-1].add_break(WD_BREAK.PAGE)

titulo(doc, "1. Descripción y contexto")
parrafo(doc, ANALISIS.get("contexto", (
    "La granja de la familia, en Santander, tiene siete galpones de gallinas ponedoras. Hoy todo se anota en un cuaderno "
    "y nadie sabe qué pasa en el galpón de noche o cuando no hay nadie: si hizo calor, si se fue la luz, si el tanque "
    "se quedó sin agua o si el amoníaco subió. Esos problemas se notan días después, cuando baja la postura o mueren aves. "
    "Este proyecto conecta el galpón 1 (4.800 aves Hy-Line Brown de 40 semanas) y el galpón 2 a una plataforma en la nube "
    "que mide ambiente, gases, agua, energía, alimento y producción, compara con el clima exterior real, avisa cuando algo "
    "se sale de rango y deja controlar los equipos a distancia. Es la parte IoT de la Granja App que la familia ya usa "
    "para el registro diario y la bodega.")))

titulo(doc, "2. Arquitectura de referencia IoT")
imagen(doc, AQUI / "diagrama.png", 17, "Figura 1. Arquitectura de referencia del proyecto")
viñetas(doc, [
    ("Dispositivos: ", "13 dispositivos de cuatro tipos: 8 gemelos digitales del galpón, 2 APIs de clima, 1 dataset "
                       "histórico y 2 reales (la pasarela de la finca y un ESP32)."),
    ("Comunicación: ", "MQTT sobre TCP, MQTT sobre WebSockets y HTTP REST. Bróker Mosquitto con usuario, clave y ACL."),
    ("Nube: ", "una VM Ubuntu en Azure con Docker Compose: Mosquitto, la plataforma FastAPI, TimescaleDB, Grafana, el "
               "contenedor de gemelos y Caddy, que da HTTPS en el dominio propio."),
    ("Aplicación: ", "panel web propio con control de los dispositivos, Grafana para el análisis y un paso de análisis "
                     "con IA sobre las estadísticas y gráficas."),
    ("Retroceso: ", "las órdenes viajan por granja/<id>/cmd (MQTT) o se recogen por HTTP; el dispositivo responde con "
                    "su estado nuevo."),
])

titulo(doc, "3. Tecnologías seleccionadas")
titulo(doc, "3.1 Sensores y dispositivos", 2)
filas = []
for d in dispositivos:
    variables = "; ".join(f"{k.replace('_', ' ')} {v['min']}-{v['max']} {v['unidad']}".strip()
                          for k, v in d["variables"].items())
    filas.append([d["id"], d["categoria"], d["origen"], d["protocolo"], variables])
tabla(doc, ["Dispositivo", "Tipo", "Origen", "Protocolo", "Variables y rangos"], filas, [3.2, 2.0, 3.4, 2.4, 6.0], 7.5)
parrafo(doc, "Resumen de variables en el periodo:", 10.5)
filas = []
for d in dispositivos:
    for k, meta in d["variables"].items():
        v = resumen.get((d["id"], k))
        if v:
            filas.append([d["nombre"], k.replace("_", " "), meta["unidad"], num(v["promedio"]), num(v["min"]),
                          num(v["max"]), v["lecturas"]])
tabla(doc, ["Dispositivo", "Variable", "Unidad", "Promedio", "Mínimo", "Máximo", "Lecturas"], filas,
      [3.8, 2.8, 1.8, 2.1, 2.1, 2.1, 1.8], 7.5)

titulo(doc, "3.2 Comunicación: bróker y protocolos", 2)
parrafo(doc, "El bróker es Eclipse Mosquitto 2.0 en la VM. Escucha MQTT en el puerto 1883 y WebSockets en el 9001, que "
             "Caddy publica cifrado como wss://<dominio>/mqtt. No acepta conexiones anónimas: la plataforma y los "
             "dispositivos tienen usuario y clave, y la ACL «pattern readwrite granja/%c/#» deja que cada dispositivo "
             "escriba solo en los tópicos de su propio identificador. La telemetría va con QoS 1 y cada dispositivo deja "
             "un mensaje de último deseo «desconectado» retenido, así la plataforma sabe al instante cuándo uno se cae.")
tabla(doc, ["Tópico", "Sentido", "Contenido"], [
    ["granja/<id>/telemetria", "dispositivo → plataforma", '{"ts": "...", "valores": {"temperatura": 26.1}}'],
    ["granja/<id>/estado", "dispositivo → plataforma (retenido)", "encendido, intervalo, calibración y estado propio"],
    ["granja/<id>/conexion", "dispositivo → plataforma (retenido, LWT)", "en_linea / desconectado"],
    ["granja/<id>/cmd", "plataforma → dispositivo", '{"id": "...", "accion": "calibrar", "parametros": {...}}'],
    ["granja/<id>/respuesta", "dispositivo → plataforma", '{"comando_id": "...", "ok": true, "estado": {...}}'],
    ["granja/alertas", "plataforma → suscriptores", "alerta abierta o resuelta"],
], [4.2, 5.0, 7.8], 8)
parrafo(doc, "Los dispositivos que hablan HTTP (contador de huevos, silo y Azure Maps) envían a POST /api/telemetria/<id> "
             "con la cabecera X-Clave. La plataforma les responde con las órdenes pendientes; el dispositivo las ejecuta "
             "y contesta en POST /api/dispositivos/<id>/respuestas. Así el retroceso también llega a equipos que no "
             "mantienen una conexión abierta.")

titulo(doc, "3.3 Nube y servicios", 2)
tabla(doc, ["Servicio", "Tecnología", "Para qué"], [
    ["VM", "Azure Standard_B2s, Ubuntu 24.04, IP pública con dominio de Azure", "aloja todo con Docker Compose"],
    ["Bróker", "Eclipse Mosquitto 2.0.20", "MQTT y WebSockets con usuario, clave y ACL"],
    ["Plataforma", "Python 3.12, FastAPI, SQLAlchemy, paho-mqtt", "ingesta, reglas, alertas, órdenes, API y panel web"],
    ["Base de datos", "TimescaleDB 2.17 sobre PostgreSQL 16", "lecturas en hypertable, alertas, reglas, órdenes"],
    ["Visualización", "Grafana 11.3 en /grafana", "series, umbrales, estadísticas, alertas y rango de tiempo"],
    ["Proxy", "Caddy 2.8", "HTTPS automático con Let's Encrypt en la URL propia"],
    ["Gemelos y APIs", "contenedor Python con el modelo del galpón", "simula los equipos y consulta Open-Meteo y Azure Maps"],
    ["APIs externas", "Open-Meteo, Azure Maps Weather, archivo ERA5", "clima real actual y del año pasado"],
    ["Código", "GitHub", "repositorio con el código, el panel de Grafana y los scripts de despliegue"],
], [2.6, 6.4, 8.0], 8)

titulo(doc, "4. Escenario y comportamiento de cada dispositivo")
for d in dispositivos:
    titulo(doc, d["nombre"], 2)
    parrafo(doc, f"{d['descripcion']} Tipo: {d['categoria']}. Origen: {d['origen']}. Protocolo: {d['protocolo']}.")
    texto = ANALISIS.get("dispositivos", {}).get(d["id"])
    if texto:
        parrafo(doc, texto)
    hay = any(resumen.get((d["id"], k)) for k in d["variables"])
    if hay:
        imagen(doc, graficar(d), 16.5,
               f"Promedio cada {paso // 60} min (línea), mínimo-máximo (banda) y umbrales de las reglas (punteado)")
    else:
        parrafo(doc, "Sin datos en el periodo.", cursiva=True)

titulo(doc, "5. Visualización y procesamiento de los datos")
parrafo(doc, "El panel web y Grafana muestran lo mismo desde dos ángulos. El panel web sirve para operar: ver qué "
             "dispositivos están en línea, el último valor de cada variable y mandar órdenes. Grafana sirve para analizar: "
             "promedio, mínimo y máximo por intervalo, umbrales de las reglas, alertas como anotaciones y tablas que "
             "cambian con el selector de tiempo (última hora, 24 horas, 6 días o un rango a mano).")
for nombre, pie in (("panel.png", "Panel web propio"), ("grafana.png", "Grafana: tablero Galpón Conectado"),
                    ("grafana-tablas.png", "Grafana: estadísticas, alertas y órdenes del periodo"),
                    ("grafana-explorar.png", "Grafana: explorador con promedio, mínimo y máximo")):
    imagen(doc, EVIDENCIAS / nombre, 16.5, pie)
titulo(doc, "5.1 Reglas", 2)
tabla(doc, ["Dispositivo", "Condición", "Nivel", "Mensaje", "Acción automática"], [
    [r["dispositivo"], f"{r['variable']} {r['operador']} {num(r['umbral'], 1)}", r["nivel"], r["mensaje"],
     f"{r['accion']['dispositivo']}: {r['accion']['accion']} {json.dumps(r['accion'].get('parametros', {}))}" if r["accion"] else "—"]
    for r in reglas], [3.0, 3.0, 1.5, 5.5, 4.0], 7.5)
parrafo(doc, "Cada regla abre una sola alerta cuando se cumple y la cierra cuando el valor vuelve con un margen del 2 % "
             "(histéresis), guardando el valor más extremo del episodio. Las reglas se editan desde el panel web.")
titulo(doc, "5.2 Alertas del periodo", 2)
if alertas:
    tabla(doc, ["Inicio", "Fin", "Dispositivo", "Nivel", "Mensaje", "Extremo"],
          [[local(a["inicio"]), local(a["fin"]) if a["fin"] else "activa", a["dispositivo"], a["nivel"], a["mensaje"],
            num(a["valor_extremo"])] for a in alertas[:60]], [2.0, 2.0, 3.0, 1.4, 6.6, 1.8], 7.5)
    if len(alertas) > 60:
        parrafo(doc, f"Se muestran 60 de {len(alertas)} alertas.", 9, cursiva=True)
else:
    parrafo(doc, "No hubo alertas en el periodo.", cursiva=True)

titulo(doc, "6. Retroceso: órdenes a los dispositivos")
parrafo(doc, "Todos los dispositivos aceptan apagar, encender, cambiar el intervalo de envío, calibrar (valor × factor + "
             "offset por variable) y volver a la calibración de fábrica. Además cada equipo tiene órdenes propias: "
             "velocidad y modo de los ventiladores, horario de luces, bomba y umbral del tanque, simulación de corte de "
             "luz, aves del lote, llegada de alimento al silo, desfase del dataset y el LED de alarma del ESP32. "
             "«Apagar» deja el sensor sin medir pero conectado esperando órdenes; por eso se puede volver a encender a "
             "distancia. El estado se guarda en disco o en la memoria flash del ESP32 y sobrevive a reinicios.")
if comandos:
    tabla(doc, ["Hora", "Dispositivo", "Acción", "Parámetros", "Origen", "Estado", "Respuesta del dispositivo"],
          [[local(c["ts"]), c["dispositivo"], c["accion"], json.dumps(c["parametros"], ensure_ascii=False), c["origen"],
            c["estado"], c["respuesta"] or ""] for c in comandos[:50]], [1.8, 2.8, 1.8, 2.8, 1.4, 1.6, 4.8], 7)
imagen(doc, EVIDENCIAS / "retroceso.png", 16.5, "Orden enviada desde el panel y confirmada por el dispositivo")
caidas = [c for c in conexiones if not c["en_linea"]]
parrafo(doc, f"En el periodo hubo {len(caidas)} desconexiones registradas por el último deseo MQTT o por silencio "
             "de los dispositivos HTTP; todas quedan en la tabla de conexiones de la plataforma.")

titulo(doc, "7. Análisis de gráficas y comportamiento con IA")
analisis = ANALISIS.get("general")
if analisis:
    for bloque in analisis:
        parrafo(doc, bloque)
else:
    parrafo(doc, "Pendiente: análisis con IA sobre los datos completos.", cursiva=True)

titulo(doc, "8. Referencias")
for ref in [
    "Hy-Line International. Hy-Line Brown Commercial Layers Management Guide, 2024.",
    "Lohmann Breeders. Management Guide Lohmann Brown-Classic, 2023.",
    "OASIS. MQTT Version 3.1.1, 2014. https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/",
    "Eclipse Foundation. Mosquitto documentation. https://mosquitto.org/documentation/",
    "Open-Meteo. Weather Forecast API y Historical Weather API (ERA5). https://open-meteo.com/en/docs",
    "Hersbach, H. et al. The ERA5 global reanalysis. Q. J. R. Meteorol. Soc. 146, 1999-2049, 2020.",
    "Microsoft. Azure Maps Weather service REST API. https://learn.microsoft.com/rest/api/maps/weather",
    "Timescale. TimescaleDB documentation. https://docs.timescale.com/",
    "Grafana Labs. Grafana documentation: PostgreSQL data source. https://grafana.com/docs/grafana/latest/datasources/postgres/",
    "FastAPI. https://fastapi.tiangolo.com/",
    "Wokwi. ESP32 simulator documentation. https://docs.wokwi.com/",
    "Universidad Autónoma de Bucaramanga. Arquitectura de IoT - Capstone Final (material del curso), 2026.",
]:
    doc.add_paragraph(ref, style="List Number")

salida = AQUI / "Parcial2_Galpon_Conectado.docx"
doc.save(salida)
print(salida)
try:
    from docx2pdf import convert

    convert(str(salida), str(salida.with_suffix(".pdf")))
    print(salida.with_suffix(".pdf"))
except Exception as error:
    print(f"No se generó el PDF: {error}")
