"""v007 — nutrition: catalog (alimentos) and daily log (diario_alimentacion).

Values are stored per entry as a snapshot; no FK to `alimentos` so historical
imported rows survive catalog changes (mirrors how training_sets stores values).
"""

VERSION = 7
NAME = "nutrition"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    categoria TEXT NOT NULL DEFAULT '',
    kcal REAL NOT NULL,
    carbohidratos REAL NOT NULL,
    fibra REAL NOT NULL,
    proteina REAL NOT NULL,
    grasa REAL NOT NULL,
    hierro REAL NOT NULL,
    calcio REAL NOT NULL,
    vitamina_c REAL NOT NULL,
    vitamina_a REAL NOT NULL,
    origen TEXT NOT NULL DEFAULT 'google'
);
CREATE TABLE IF NOT EXISTS diario_alimentacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    orden INTEGER NOT NULL,
    alimento TEXT NOT NULL,
    cantidad_g REAL NOT NULL,
    kcal REAL NOT NULL,
    carbohidratos REAL NOT NULL,
    fibra REAL NOT NULL,
    proteina REAL NOT NULL,
    grasa REAL NOT NULL,
    hierro REAL NOT NULL,
    calcio REAL NOT NULL,
    vitamina_c REAL NOT NULL,
    vitamina_a REAL NOT NULL,
    origen TEXT NOT NULL DEFAULT 'google'
);
CREATE INDEX IF NOT EXISTS idx_diario_alimentacion_fecha_orden
    ON diario_alimentacion(fecha, orden);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
