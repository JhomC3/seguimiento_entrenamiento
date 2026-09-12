"""v016 — split actual (columna training_splits.activo, único)."""

VERSION = 16
NAME = "split_activo"


def migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(training_splits)").fetchall()}
    if "activo" not in cols:
        conn.execute("ALTER TABLE training_splits ADD COLUMN activo INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_splits_activo "
        "ON training_splits (activo) WHERE activo = 1"
    )
