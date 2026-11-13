import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

TABLAS = {
    "lecturas": ["ts", "dispositivo", "variable", "valor", "via"],
    "conexiones": ["id", "ts", "dispositivo", "en_linea"],
    "comandos": ["id", "ts", "dispositivo", "accion", "parametros", "origen", "estado", "respuesta", "ts_respuesta"],
    "reglas": ["id", "dispositivo", "variable", "operador", "umbral", "nivel", "mensaje", "accion", "activa"],
    "alertas": ["id", "regla", "dispositivo", "variable", "nivel", "mensaje", "valor", "valor_extremo", "inicio", "fin"],
}
FECHAS = {"ts", "ts_respuesta", "inicio", "fin", "ultimo_contacto"}
BOOLEANOS = {"en_linea", "activa"}


def normalizar(fila, columnas):
    salida = {}
    for c, v in zip(columnas, fila):
        if c in FECHAS and v is not None:
            v = datetime.fromisoformat(str(v))
            v = v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
        if c in BOOLEANOS and v is not None:
            v = bool(v)
        salida[c] = v
    return salida


def main(origen, destino):
    o = create_engine(f"sqlite:///{origen}")
    d = create_engine(destino.replace("postgresql://", "postgresql+psycopg://"))
    with o.connect() as co, d.begin() as cd:
        cd.execute(text("TRUNCATE lecturas, conexiones, comandos, reglas, alertas RESTART IDENTITY"))
        for tabla, columnas in TABLAS.items():
            filas = co.execute(text(f"SELECT {', '.join(columnas)} FROM {tabla}")).fetchall()
            sql = text(f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({', '.join(':' + c for c in columnas)})")
            for i in range(0, len(filas), 5000):
                cd.execute(sql, [normalizar(f, columnas) for f in filas[i:i + 5000]])
            print(f"{tabla}: {len(filas)} filas")
        for tabla in ("conexiones", "reglas", "alertas"):
            cd.execute(text(f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), coalesce(max(id), 0) + 1, false) FROM {tabla}"))
        for f in co.execute(text("SELECT id, en_linea, ultimo_contacto, estado FROM dispositivos")).fetchall():
            valores = normalizar(f, ["id", "en_linea", "ultimo_contacto", "estado"])
            cd.execute(text("UPDATE dispositivos SET en_linea = :en_linea, ultimo_contacto = :ultimo_contacto, "
                            "estado = :estado WHERE id = :id"), valores)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
