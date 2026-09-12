"""v017 — velocidad_kmh/dificultad: series HIIT sin kg/reps/rir."""

VERSION = 17
NAME = "hiit_velocidad_dificultad"

SCHEMA_SQL = """
ALTER TABLE training_sets ADD COLUMN velocidad_kmh REAL;
ALTER TABLE training_sets ADD COLUMN dificultad REAL;
"""


def migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()}
    if "velocidad_kmh" not in cols:
        conn.execute("ALTER TABLE training_sets ADD COLUMN velocidad_kmh REAL;")
    if "dificultad" not in cols:
        conn.execute("ALTER TABLE training_sets ADD COLUMN dificultad REAL;")
