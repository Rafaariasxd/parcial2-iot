import os
import threading

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)


def url_base():
    url = os.environ.get("DATABASE_URL", "sqlite:///granja_iot.db")
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


URL = url_base()
ES_SQLITE = URL.startswith("sqlite")
motor = create_engine(
    URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30} if ES_SQLITE else {},
)
candado = threading.Lock()
meta = MetaData()

dispositivos = Table(
    "dispositivos",
    meta,
    Column("id", String(64), primary_key=True),
    Column("nombre", String(120), nullable=False),
    Column("categoria", String(30), nullable=False),
    Column("origen", String(120), nullable=False),
    Column("protocolo", String(60), nullable=False),
    Column("ubicacion", String(60), nullable=False),
    Column("descripcion", Text, nullable=False),
    Column("variables", Text, nullable=False),
    Column("acciones", Text, nullable=False),
    Column("en_linea", Boolean, nullable=False, default=False),
    Column("ultimo_contacto", DateTime(timezone=True)),
    Column("estado", Text),
)

lecturas = Table(
    "lecturas",
    meta,
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("dispositivo", String(64), nullable=False),
    Column("variable", String(40), nullable=False),
    Column("valor", Float, nullable=False),
    Column("via", String(20), nullable=False),
    Index("ix_lecturas_serie", "dispositivo", "variable", "ts"),
    Index("ix_lecturas_ts", "ts"),
)

conexiones = Table(
    "conexiones",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("dispositivo", String(64), nullable=False),
    Column("en_linea", Boolean, nullable=False),
)

comandos = Table(
    "comandos",
    meta,
    Column("id", String(36), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("dispositivo", String(64), nullable=False),
    Column("accion", String(40), nullable=False),
    Column("parametros", Text, nullable=False),
    Column("origen", String(40), nullable=False),
    Column("estado", String(20), nullable=False),
    Column("respuesta", Text),
    Column("ts_respuesta", DateTime(timezone=True)),
)

reglas = Table(
    "reglas",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dispositivo", String(64), nullable=False),
    Column("variable", String(40), nullable=False),
    Column("operador", String(2), nullable=False),
    Column("umbral", Float, nullable=False),
    Column("nivel", String(20), nullable=False),
    Column("mensaje", Text, nullable=False),
    Column("accion", Text),
    Column("activa", Boolean, nullable=False, default=True),
)

alertas = Table(
    "alertas",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("regla", Integer, nullable=False),
    Column("dispositivo", String(64), nullable=False),
    Column("variable", String(40), nullable=False),
    Column("nivel", String(20), nullable=False),
    Column("mensaje", Text, nullable=False),
    Column("valor", Float, nullable=False),
    Column("valor_extremo", Float, nullable=False),
    Column("inicio", DateTime(timezone=True), nullable=False),
    Column("fin", DateTime(timezone=True)),
)


def crear_tablas():
    meta.create_all(motor)
    if ES_SQLITE:
        with motor.begin() as c:
            c.execute(text("PRAGMA journal_mode=WAL"))
        return
    try:
        with motor.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            c.execute(text("SELECT create_hypertable('lecturas', 'ts', if_not_exists => TRUE, migrate_data => TRUE)"))
    except Exception:
        pass
