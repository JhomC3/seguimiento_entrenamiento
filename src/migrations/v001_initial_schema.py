"""v001 — initial schema: all current tables, indexes and foreign keys.

Safe only for new databases; uses IF NOT EXISTS so it is harmless on legacy DBs.
"""

VERSION = 1
NAME = "initial_schema"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ejercicios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_muscular TEXT NOT NULL,
    ejercicio TEXT NOT NULL UNIQUE,
    categoria TEXT,
    origen TEXT NOT NULL DEFAULT 'google'
);
CREATE TABLE IF NOT EXISTS training_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    semana INTEGER NOT NULL,
    dia TEXT NOT NULL,
    fecha TEXT,
    set_orden INTEGER NOT NULL,
    ejercicio TEXT NOT NULL,
    reps REAL,
    kg REAL,
    rir REAL,
    origen TEXT NOT NULL DEFAULT 'google'
);
CREATE INDEX IF NOT EXISTS idx_training_semana ON training_sets(semana);
CREATE INDEX IF NOT EXISTS idx_training_ejercicio ON training_sets(ejercicio);
CREATE TABLE IF NOT EXISTS plantillas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    clasificacion TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plantilla_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plantilla_id INTEGER NOT NULL,
    set_orden INTEGER NOT NULL,
    ejercicio TEXT NOT NULL,
    FOREIGN KEY (plantilla_id) REFERENCES plantillas(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_plantilla_sets ON plantilla_sets(plantilla_id);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
