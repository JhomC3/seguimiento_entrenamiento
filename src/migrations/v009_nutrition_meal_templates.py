"""v009 — nutrition meal templates (plantillas de alimentación).

Stores named meal templates: a header (`plantillas_alimentacion`) and ordered
rows with alimento + cantidad_g (`plantilla_alimentos`), mirroring the
training templates.
"""

VERSION = 9
NAME = "nutrition_meal_templates"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plantillas_alimentacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plantilla_alimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plantilla_id INTEGER NOT NULL,
    orden INTEGER NOT NULL,
    alimento TEXT NOT NULL,
    cantidad_g REAL NOT NULL,
    FOREIGN KEY (plantilla_id) REFERENCES plantillas_alimentacion(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_plantilla_alimentos
    ON plantilla_alimentos(plantilla_id);
"""


def migrate(conn) -> None:
    for statement in SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            conn.execute(statement)
