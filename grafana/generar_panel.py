import json
from pathlib import Path

FUENTE = {"type": "grafana-postgresql-datasource", "uid": "granja-bd"}
VERDE, YEMA, ROJO, AZUL, GRIS, MORADO = "#1E5B43", "#F4B23E", "#B3261E", "#3A6EA5", "#8A8F8C", "#7A4FA0"
paneles = []
siguiente_id = [1]


def nuevo_id():
    siguiente_id[0] += 1
    return siguiente_id[0]


def sql_serie(dispositivo, variable, alias, funcion="avg"):
    return (
        f"SELECT $__timeGroupAlias(ts, $__interval), {funcion}(valor) AS \"{alias}\" FROM lecturas "
        f"WHERE dispositivo = '{dispositivo}' AND variable = '{variable}' AND $__timeFilter(ts) GROUP BY 1 ORDER BY 1"
    )


def objetivo(sql, ref, formato="time_series"):
    return {"datasource": FUENTE, "refId": ref, "rawQuery": True, "editorMode": "code", "format": formato, "rawSql": sql}


def fila(titulo, y):
    paneles.append({"type": "row", "title": titulo, "id": nuevo_id(), "collapsed": False,
                    "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []})


def umbrales(pasos):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in pasos]}


def serie(titulo, consultas, pos, unidad="", pasos=None, colores=None, descripcion="", min_max=None, apilar=False):
    objetivos = []
    sobre = []
    for i, (disp, var, alias) in enumerate(consultas):
        objetivos.append(objetivo(sql_serie(disp, var, alias), chr(65 + len(objetivos))))
        if colores and i < len(colores):
            sobre.append({"matcher": {"id": "byName", "options": alias},
                          "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": colores[i]}}]})
    if min_max:
        disp, var, alias = consultas[0]
        for funcion, nombre in (("min", f"Mínimo {alias.lower()}"), ("max", f"Máximo {alias.lower()}")):
            objetivos.append(objetivo(sql_serie(disp, var, nombre, funcion), chr(65 + len(objetivos))))
            sobre.append({"matcher": {"id": "byName", "options": nombre}, "properties": [
                {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [4, 4]}},
                {"id": "custom.lineWidth", "value": 1},
                {"id": "color", "value": {"mode": "fixed", "fixedColor": GRIS}},
            ]})
    defaults = {
        "unit": unidad,
        "custom": {"lineWidth": 2, "fillOpacity": 8, "spanNulls": 600000, "showPoints": "never",
                   "thresholdsStyle": {"mode": "dashed" if pasos else "off"},
                   "stacking": {"mode": "normal" if apilar else "none"}},
        "color": {"mode": "palette-classic"},
    }
    if pasos:
        defaults["thresholds"] = umbrales(pasos)
    paneles.append({
        "type": "timeseries", "title": titulo, "id": nuevo_id(), "datasource": FUENTE, "description": descripcion,
        "gridPos": pos, "targets": objetivos,
        "fieldConfig": {"defaults": defaults, "overrides": sobre},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "min", "max", "lastNotNull"]},
                    "tooltip": {"mode": "multi", "sort": "none"}},
    })


def estado(titulo, dispositivo, variable, pos, unidad="", pasos=None, decimales=1):
    sql = (f"SELECT ts AS time, valor FROM lecturas WHERE dispositivo = '{dispositivo}' AND variable = '{variable}' "
           f"AND ts > now() - interval '1 day' ORDER BY ts DESC LIMIT 1")
    paneles.append({
        "type": "stat", "title": titulo, "id": nuevo_id(), "datasource": FUENTE, "gridPos": pos,
        "targets": [objetivo(sql, "A", "table")],
        "fieldConfig": {"defaults": {"unit": unidad, "decimals": decimales,
                                     "thresholds": umbrales(pasos or [(None, VERDE)]), "color": {"mode": "thresholds"}},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^valor$/"}, "colorMode": "background",
                    "graphMode": "none", "textMode": "value"},
    })


def estado_sql(titulo, sql, pos, pasos=None, unidad=""):
    paneles.append({
        "type": "stat", "title": titulo, "id": nuevo_id(), "datasource": FUENTE, "gridPos": pos,
        "targets": [objetivo(sql, "A", "table")],
        "fieldConfig": {"defaults": {"unit": unidad, "thresholds": umbrales(pasos or [(None, VERDE)]),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}, "colorMode": "background",
                    "graphMode": "none", "textMode": "value"},
    })


def tabla(titulo, sql, pos, descripcion=""):
    paneles.append({
        "type": "table", "title": titulo, "id": nuevo_id(), "datasource": FUENTE, "gridPos": pos,
        "description": descripcion, "targets": [objetivo(sql, "A", "table")],
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True}}, "overrides": []},
        "options": {"showHeader": True, "cellHeight": "sm"},
    })


def linea_estado(titulo, consultas, pos):
    objetivos = [objetivo(sql_serie(d, v, a, "min"), chr(65 + i)) for i, (d, v, a) in enumerate(consultas)]
    paneles.append({
        "type": "state-timeline", "title": titulo, "id": nuevo_id(), "datasource": FUENTE, "gridPos": pos,
        "targets": objetivos,
        "fieldConfig": {"defaults": {"color": {"mode": "thresholds"},
                                     "thresholds": umbrales([(None, ROJO), (0.5, VERDE)]),
                                     "mappings": [{"type": "range", "options": {"from": 0.5, "to": 1.5, "result": {"text": "Sí"}}},
                                                  {"type": "range", "options": {"from": -0.5, "to": 0.5, "result": {"text": "No"}}}]},
                        "overrides": []},
        "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8},
    })


y = 0
fila("Ahora en el galpón", y)
y += 1
estado_sql("Dispositivos en línea", "SELECT count(*) FILTER (WHERE en_linea) AS en_linea FROM dispositivos",
           {"h": 4, "w": 4, "x": 0, "y": y}, [(None, ROJO), (10, YEMA), (12, VERDE)])
estado_sql("Alertas activas", "SELECT count(*) AS activas FROM alertas WHERE fin IS NULL",
           {"h": 4, "w": 4, "x": 4, "y": y}, [(None, VERDE), (1, YEMA), (3, ROJO)])
estado("Temperatura galpón", "galpon1-ambiente", "temperatura", {"h": 4, "w": 4, "x": 8, "y": y}, "celsius",
       [(None, AZUL), (20, VERDE), (30, YEMA), (33, ROJO)])
estado("Amoníaco", "galpon1-gases", "amoniaco", {"h": 4, "w": 4, "x": 12, "y": y}, "ppm",
       [(None, VERDE), (20, YEMA), (25, ROJO)])
estado("Postura hoy", "contador-huevos", "postura", {"h": 4, "w": 4, "x": 16, "y": y}, "percent",
       [(None, ROJO), (85, YEMA), (90, VERDE)])
estado("Silo", "silo-alimento", "bultos", {"h": 4, "w": 4, "x": 20, "y": y}, "none",
       [(None, ROJO), (30, YEMA), (50, VERDE)], 0)
y += 4

fila("Ambiente del galpón 1", y)
y += 1
serie("Temperatura dentro y fuera", [("galpon1-ambiente", "temperatura", "Galpón 1"),
                                    ("clima-openmeteo", "temperatura", "Exterior (Open-Meteo)"),
                                    ("galpon2-ambiente", "temperatura", "Galpón 2 (ESP32)")],
      {"h": 9, "w": 12, "x": 0, "y": y}, "celsius", [(None, VERDE), (30, YEMA), (33, ROJO)], [VERDE, AZUL, MORADO],
      "El galpón sigue al clima exterior con unos grados más por el calor de las aves.", min_max=True)
serie("Humedad relativa", [("galpon1-ambiente", "humedad", "Galpón 1"),
                          ("clima-openmeteo", "humedad", "Exterior")],
      {"h": 9, "w": 6, "x": 12, "y": y}, "percent", [(None, VERDE), (85, YEMA)], [VERDE, AZUL])
serie("Índice temperatura-humedad (THI)", [("galpon1-ambiente", "indice_thi", "THI")],
      {"h": 9, "w": 6, "x": 18, "y": y}, "none", [(None, VERDE), (72, YEMA), (79, ROJO)], [YEMA],
      "Bajo 72 sin estrés, 72-79 estrés leve, sobre 79 estrés fuerte.")
y += 9
serie("Amoníaco y CO2", [("galpon1-gases", "amoniaco", "Amoníaco (ppm)")],
      {"h": 8, "w": 8, "x": 0, "y": y}, "ppm", [(None, VERDE), (20, YEMA), (25, ROJO)], [MORADO], min_max=True)
serie("CO2", [("galpon1-gases", "co2", "CO2 (ppm)")],
      {"h": 8, "w": 8, "x": 8, "y": y}, "ppm", [(None, VERDE), (3000, YEMA)], [GRIS])
serie("Ventiladores", [("galpon1-ventilacion", "velocidad", "Velocidad (%)")],
      {"h": 8, "w": 8, "x": 16, "y": y}, "percent", None, [VERDE],
      "En automático suben con la temperatura y con el amoníaco. Bajan a 0 en los cortes de luz.")
y += 8

fila("Agua, alimento y energía", y)
y += 1
serie("Tanque de agua", [("tanque-agua", "nivel", "Nivel (%)")], {"h": 8, "w": 8, "x": 0, "y": y}, "percent",
      [(None, ROJO), (20, YEMA), (35, VERDE)], [AZUL], "La bomba arranca bajo el umbral y para al 95 %.")
serie("Consumo de agua", [("tanque-agua", "caudal", "Caudal (L/min)")], {"h": 8, "w": 8, "x": 8, "y": y},
      "none", None, [AZUL])
serie("Silo de alimento", [("silo-alimento", "nivel", "Nivel (kg)")], {"h": 8, "w": 8, "x": 16, "y": y}, "masskg",
      [(None, ROJO), (1200, YEMA), (2000, VERDE)], [YEMA])
y += 8
serie("Potencia de la finca", [("tablero-energia", "potencia", "Potencia (kW)")], {"h": 8, "w": 12, "x": 0, "y": y},
      "kwatt", None, [YEMA], min_max=True)
serie("Voltaje", [("tablero-energia", "voltaje", "Voltaje (V)")], {"h": 8, "w": 6, "x": 12, "y": y}, "volt",
      [(None, ROJO), (100, VERDE)], [VERDE])
linea_estado("Red, luces y bomba", [("tablero-energia", "red", "Red eléctrica"),
                                    ("galpon1-iluminacion", "luces", "Luces"),
                                    ("tanque-agua", "bomba", "Bomba")], {"h": 8, "w": 6, "x": 18, "y": y})
y += 8

fila("Producción", y)
y += 1
serie("Huevos por hora", [("contador-huevos", "huevos_hora", "Huevos por hora")], {"h": 8, "w": 8, "x": 0, "y": y},
      "none", None, [YEMA], "Casi toda la postura ocurre en las primeras horas después de encender las luces.")
serie("Huevos acumulados del día", [("contador-huevos", "huevos_dia", "Huevos del día")],
      {"h": 8, "w": 8, "x": 8, "y": y}, "none", None, [YEMA])
serie("Postura estimada", [("contador-huevos", "postura", "Postura (%)")], {"h": 8, "w": 8, "x": 16, "y": y},
      "percent", [(None, ROJO), (85, VERDE)], [VERDE])
y += 8

fila("Clima: dos APIs y el dataset del año pasado", y)
y += 1
serie("Temperatura exterior por fuente", [("clima-openmeteo", "temperatura", "Open-Meteo"),
                                         ("clima-azure-maps", "temperatura", "Azure Maps"),
                                         ("historico-era5", "temperatura", "ERA5 mismo día de 2025")],
      {"h": 9, "w": 12, "x": 0, "y": y}, "celsius", None, [AZUL, VERDE, GRIS])
serie("Radiación solar", [("clima-openmeteo", "radiacion", "Open-Meteo"),
                         ("historico-era5", "radiacion", "ERA5 2025")],
      {"h": 9, "w": 6, "x": 12, "y": y}, "none", None, [YEMA, GRIS])
serie("Lluvia", [("clima-openmeteo", "lluvia", "Open-Meteo (mm)"), ("historico-era5", "lluvia", "ERA5 2025 (mm)")],
      {"h": 9, "w": 6, "x": 18, "y": y}, "none", None, [AZUL, GRIS])
y += 9

fila("Dispositivos reales", y)
y += 1
serie("Latencia de la pasarela a la nube", [("pasarela-finca", "latencia", "Latencia (ms)")],
      {"h": 8, "w": 8, "x": 0, "y": y}, "ms", [(None, VERDE), (800, YEMA)], [VERDE], min_max=True)
serie("CPU y memoria de la pasarela", [("pasarela-finca", "cpu", "CPU (%)"), ("pasarela-finca", "memoria", "Memoria (%)")],
      {"h": 8, "w": 8, "x": 8, "y": y}, "percent", None, [YEMA, AZUL])
serie("ESP32 galpón 2", [("galpon2-ambiente", "temperatura", "Temperatura (°C)"),
                         ("galpon2-ambiente", "humedad", "Humedad (%)")],
      {"h": 8, "w": 8, "x": 16, "y": y}, "none", None, [ROJO, AZUL])
y += 8

fila("Explorar cualquier variable", y)
y += 1
paneles.append({
    "type": "timeseries", "title": "$dispositivo · $variable", "id": nuevo_id(), "datasource": FUENTE,
    "gridPos": {"h": 9, "w": 24, "x": 0, "y": y},
    "targets": [
        objetivo("SELECT $__timeGroupAlias(ts, $__interval), avg(valor) AS \"Promedio\", min(valor) AS \"Mínimo\", "
                 "max(valor) AS \"Máximo\" FROM lecturas WHERE dispositivo = '$dispositivo' AND variable = '$variable' "
                 "AND $__timeFilter(ts) GROUP BY 1 ORDER BY 1", "A"),
    ],
    "fieldConfig": {"defaults": {"custom": {"lineWidth": 2, "fillOpacity": 5, "showPoints": "never"}}, "overrides": [
        {"matcher": {"id": "byName", "options": "Mínimo"}, "properties": [{"id": "custom.fillBelowTo", "value": "Máximo"},
                                                                         {"id": "color", "value": {"mode": "fixed", "fixedColor": GRIS}}]},
        {"matcher": {"id": "byName", "options": "Máximo"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": GRIS}}]},
        {"matcher": {"id": "byName", "options": "Promedio"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": VERDE}}]},
    ]},
    "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "min", "max"]},
                "tooltip": {"mode": "multi"}},
})
y += 9

fila("Estadísticas, alertas y órdenes", y)
y += 1
tabla("Promedio, mínimo y máximo del periodo",
      "SELECT d.nombre AS \"Dispositivo\", l.variable AS \"Variable\", round(avg(l.valor)::numeric, 2) AS \"Promedio\", "
      "round(min(l.valor)::numeric, 2) AS \"Mínimo\", round(max(l.valor)::numeric, 2) AS \"Máximo\", count(*) AS \"Lecturas\" "
      "FROM lecturas l JOIN dispositivos d ON d.id = l.dispositivo WHERE $__timeFilter(l.ts) GROUP BY 1, 2 ORDER BY 1, 2",
      {"h": 12, "w": 12, "x": 0, "y": y}, "Cambia con el rango de tiempo de arriba.")
tabla("Alertas",
      "SELECT inicio AS \"Inicio\", fin AS \"Fin\", dispositivo AS \"Dispositivo\", nivel AS \"Nivel\", mensaje AS \"Mensaje\", "
      "round(valor_extremo::numeric, 2) AS \"Valor extremo\" FROM alertas WHERE $__timeFilter(inicio) ORDER BY inicio DESC",
      {"h": 12, "w": 12, "x": 12, "y": y})
y += 12
tabla("Dispositivos",
      "SELECT nombre AS \"Dispositivo\", categoria AS \"Tipo\", protocolo AS \"Protocolo\", "
      "CASE WHEN en_linea THEN 'En línea' ELSE 'Desconectado' END AS \"Estado\", ultimo_contacto AS \"Último dato\" "
      "FROM dispositivos ORDER BY categoria, nombre",
      {"h": 10, "w": 12, "x": 0, "y": y})
tabla("Órdenes enviadas a los dispositivos (retroceso)",
      "SELECT ts AS \"Hora\", dispositivo AS \"Dispositivo\", accion AS \"Acción\", parametros AS \"Parámetros\", "
      "origen AS \"Origen\", estado AS \"Estado\", respuesta AS \"Respuesta\" FROM comandos WHERE $__timeFilter(ts) "
      "ORDER BY ts DESC", {"h": 10, "w": 12, "x": 12, "y": y})

panel = {
    "uid": "galpon",
    "title": "Galpón Conectado",
    "tags": ["iot", "granja"],
    "timezone": "America/Bogota",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "timepicker": {"refresh_intervals": ["30s", "1m", "5m", "15m"]},
    "editable": True,
    "graphTooltip": 1,
    "annotations": {"list": [{
        "name": "Alertas", "enable": True, "iconColor": ROJO, "datasource": FUENTE,
        "target": {"rawQuery": True, "format": "table", "refId": "Anno", "editorMode": "code",
                   "rawSql": "SELECT inicio AS time, coalesce(fin, now()) AS timeend, mensaje AS text, nivel AS tags "
                             "FROM alertas WHERE $__timeFilter(inicio)"},
    }]},
    "templating": {"list": [
        {"name": "dispositivo", "label": "Dispositivo", "type": "query", "datasource": FUENTE,
         "query": "SELECT id FROM dispositivos ORDER BY id", "definition": "SELECT id FROM dispositivos ORDER BY id",
         "refresh": 1, "current": {"text": "galpon1-ambiente", "value": "galpon1-ambiente"}},
        {"name": "variable", "label": "Variable", "type": "query", "datasource": FUENTE,
         "query": "SELECT DISTINCT variable FROM lecturas WHERE dispositivo = '$dispositivo' AND ts > now() - interval '2 days'",
         "definition": "SELECT DISTINCT variable FROM lecturas WHERE dispositivo = '$dispositivo' AND ts > now() - interval '2 days'",
         "refresh": 2},
    ]},
    "panels": paneles,
}

salida = Path(__file__).with_name("paneles") / "galpon.json"
salida.write_text(json.dumps(panel, ensure_ascii=False, indent=1), encoding="utf-8")
print(salida, len(paneles), "paneles")
