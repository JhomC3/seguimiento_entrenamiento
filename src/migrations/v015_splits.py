"""v015 — training_splits y training_split_items (gestor de splits)."""

VERSION = 15
NAME = "splits"


def migrate(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_splits ("
        "id INTEGER PRIMARY KEY, "
        "nombre TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_splits_nombre ON training_splits (LOWER(nombre))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_split_items ("
        "id INTEGER PRIMARY KEY, "
        "split_id INTEGER NOT NULL REFERENCES training_splits(id) ON DELETE CASCADE, "
        "dia TEXT NOT NULL, "
        "orden INTEGER NOT NULL, "
        "item_type TEXT NOT NULL DEFAULT 'ejercicio', "
        "ejercicio TEXT NOT NULL, "
        "grupo_muscular TEXT NOT NULL, "
        "UNIQUE (split_id, dia, orden))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_split_items_split "
        "ON training_split_items (split_id, dia, orden)"
    )
