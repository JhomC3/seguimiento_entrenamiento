"""v012 — cardio_annotations: anotaciones manuales (velocidad/inclinación)
sobre sesiones EXERCISE_SESSION espejadas de Health Connect."""

VERSION = 12
NAME = "cardio_annotations"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cardio_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hc_id TEXT NOT NULL UNIQUE REFERENCES health_records(hc_id) ON DELETE CASCADE,
    velocidad_kmh REAL,
    inclinacion_pct REAL,
    notas TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
