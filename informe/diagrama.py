from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

MONTE, YEMA, TINTA, CAL = "#1E5B43", "#F4B23E", "#1C2520", "#F5F4EF"
COLORES = {"Gemelo digital": "#E3EFE8", "API": "#E2ECF7", "DataSet": "#EFE6F5", "Real": "#FDF1DA"}

fig, ax = plt.subplots(figsize=(17, 10.5))
ax.set_xlim(0, 170)
ax.set_ylim(0, 105)
ax.axis("off")


def caja(x, y, w, h, texto, fondo="#FFFFFF", borde=MONTE, tam=8.5, negrita=False, lw=1.3, radio=1.0, color=TINTA):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.25,rounding_size={radio}", fc=fondo, ec=borde, lw=lw))
    ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center", fontsize=tam,
            fontweight="bold" if negrita else "normal", color=color, linespacing=1.25)


def flecha(x1, y1, x2, y2, color=MONTE, estilo="-|>", lw=1.3, rad=0.0, punteada=False):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=estilo, mutation_scale=11, color=color, lw=lw,
                                 connectionstyle=f"arc3,rad={rad}", linestyle="--" if punteada else "-"))


def etiqueta(x, y, texto, color=MONTE, tam=7.5, rot=0):
    ax.text(x, y, texto, fontsize=tam, color=color, ha="center", va="center", rotation=rot,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))


ax.text(2, 102, "Galpón Conectado · Arquitectura de referencia IoT", fontsize=15, fontweight="bold", color=MONTE)

ax.add_patch(FancyBboxPatch((1, 4), 47, 93, boxstyle="round,pad=0.3,rounding_size=2", fc=CAL, ec=MONTE, lw=1.6))
ax.text(3, 94.5, "1. Dispositivos (finca, Santander)", fontsize=10.5, fontweight="bold", color=MONTE)

dispositivos = [
    ("Gemelo digital", "Ambiente galpón 1", "temperatura, humedad, THI", "MQTT"),
    ("Gemelo digital", "Gases galpón 1", "amoníaco, CO2", "MQTT"),
    ("Gemelo digital", "Ventiladores", "velocidad, modo, kW", "MQTT"),
    ("Gemelo digital", "Iluminación", "lux, luces, horas de luz", "MQTT/WS"),
    ("Gemelo digital", "Tanque de agua", "nivel, caudal, bomba", "MQTT/WS"),
    ("Gemelo digital", "Tablero eléctrico", "V, A, kW, red", "MQTT"),
    ("Gemelo digital", "Contador de huevos", "huevos/h, postura, peso", "HTTP"),
    ("Gemelo digital", "Silo de alimento", "kg, kg/h, bultos", "HTTP"),
    ("API", "Clima Open-Meteo", "T, HR, lluvia, viento, radiación", "MQTT"),
    ("API", "Clima Azure Maps", "T, sensación, HR, UV", "HTTP"),
    ("DataSet", "Histórico ERA5 2025", "CSV horario, 1.200 filas", "MQTT"),
    ("Real", "Pasarela de la finca", "latencia, CPU, memoria", "MQTT"),
    ("Real", "ESP32 galpón 2", "DHT22, LDR, LED", "MQTT"),
]
alto, paso = 5.6, 6.85
for i, (cat, nombre, vars_, proto) in enumerate(dispositivos):
    y = 88.5 - i * paso
    caja(3, y, 30, alto, f"{nombre}\n{vars_}", COLORES[cat], tam=7.6)
    etiqueta(40.5, y + alto / 2, proto, tam=7.2)
    flecha(33.4, y + alto / 2, 37, y + alto / 2, lw=1.0)

for j, (cat, color) in enumerate(COLORES.items()):
    ax.add_patch(FancyBboxPatch((3 + j * 13, 0.3), 2.2, 2.2, boxstyle="round,pad=0.1", fc=color, ec=MONTE, lw=0.8))
    ax.text(6 + j * 13, 1.4, cat, fontsize=7.5, va="center")

ax.add_patch(FancyBboxPatch((54, 4), 114, 93, boxstyle="round,pad=0.3,rounding_size=2", fc="#FBFBF8", ec=MONTE, lw=1.6))
ax.text(56, 94.5, "2. Nube: Azure VM Ubuntu 24.04 (Standard_B2s) con Docker Compose", fontsize=10.5, fontweight="bold",
        color=MONTE)

caja(58, 72, 30, 16, "Mosquitto 2.0\nbróker MQTT\n:1883 TCP · :9001 WebSockets\nusuario + clave, ACL por\ndispositivo (granja/%c/#)",
     "#E3EFE8", tam=8.2)
caja(58, 46, 30, 18, "Plataforma FastAPI\n• puente MQTT → ingesta\n• API REST /api/telemetria\n• reglas y alertas\n"
     "• órdenes (retroceso)\n• panel web propio", "#FFFFFF", tam=8.2)
caja(58, 20, 30, 16, "TimescaleDB\n(PostgreSQL 16)\nlecturas (hypertable),\nalertas, reglas, comandos,\nconexiones", "#FFFFFF",
     tam=8.2)
caja(100, 72, 28, 16, "Caddy\nHTTPS automático\nhttps://galpon-conectado-…\n.cloudapp.azure.com", YEMA, borde=TINTA, tam=8.2)
caja(100, 46, 28, 18, "Grafana 11\n/grafana\npromedio, mín., máx.,\numbrales, alertas,\nrango de tiempo", "#FFFFFF", tam=8.2)
caja(100, 20, 28, 16, "Contenedor dispositivos\ngemelos + APIs + dataset\n(motor físico del galpón\nacoplado al clima real)",
     "#E3EFE8", tam=8.2)
caja(138, 72, 27, 16, "Usuarios\nnavegador o celular\npanel web + Grafana", "#FFFFFF", tam=8.5)
caja(138, 46, 27, 18, "Análisis con IA\nlee estadísticas y\ngráficas exportadas\ny describe el\ncomportamiento", "#FFFFFF", tam=8.2)
caja(138, 20, 27, 16, "Servicios externos\nOpen-Meteo (gratis)\nAzure Maps Weather\nArchivo ERA5", "#E2ECF7", tam=8.2)

flecha(44, 70, 57.6, 80, lw=1.6)
etiqueta(50.5, 76.5, "MQTT\nMQTT/WSS", tam=7.3)
flecha(44, 40, 57.6, 54, lw=1.6)
etiqueta(50.5, 47.5, "HTTP\nREST", tam=7.3)
flecha(73, 71.7, 73, 64.4, lw=1.6)
etiqueta(77.5, 68, "suscripción\ngranja/+/…", tam=7)
flecha(73, 45.7, 73, 36.4, lw=1.6)
etiqueta(77, 41, "SQL", tam=7)
flecha(114, 45.7, 88.4, 32, lw=1.2, rad=-0.15)
etiqueta(101, 38.5, "consultas SQL", tam=7)
flecha(99.6, 80, 88.4, 56, lw=1.2, rad=0.2)
flecha(114, 71.7, 114, 64.4, lw=1.2)
flecha(128.4, 80, 137.6, 80, lw=1.6, estilo="<|-|>")
etiqueta(133, 83.5, "HTTPS", tam=7)
flecha(99.6, 28, 88.4, 76, lw=1.2, rad=-0.25)
etiqueta(96, 60, "MQTT\ninterno", tam=7)
flecha(137.6, 28, 128.4, 28, lw=1.2)
flecha(151.5, 64.4, 151.5, 71.7, lw=1.0, punteada=True)
flecha(137.6, 55, 128.4, 55, lw=1.0, punteada=True)

flecha(57.6, 75, 46, 57, color="#B3261E", lw=1.6, rad=0.25)
etiqueta(51.5, 62, "retroceso\ngranja/<id>/cmd", color="#B3261E", tam=7.2)
caja(58, 6, 107, 8, "Retroceso: el panel o una regla publica una orden en granja/<id>/cmd (MQTT) o la deja en cola para HTTP.\n"
     "El dispositivo la ejecuta (apagar, encender, intervalo, calibrar, velocidad, horario, bomba, llenado…) y responde en "
     "granja/<id>/respuesta con su estado nuevo", "#FBE4E2", borde="#B3261E", tam=7.3)

salida = Path(__file__).with_name("diagrama.png")
fig.savefig(salida, dpi=170, bbox_inches="tight", facecolor="white")
print(salida)
