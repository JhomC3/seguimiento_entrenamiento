"""v011 — descanso_seg: segundos de descanso opcionales por serie."""

VERSION = 11
NAME = "descanso_seg"

SCHEMA_SQL = """
ALTER TABLE training_sets ADD COLUMN descanso_seg REAL;
"""


def migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()}
    if "descanso_seg" in cols:
        return
    conn.execute("ALTER TABLE training_sets ADD COLUMN descanso_seg REAL;")
