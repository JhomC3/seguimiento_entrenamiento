"""v002 — add/backfill `origen` and `categoria` columns.

Inspects legacy columns defensively; every step is idempotent.
"""

from config import MUSCLE_CATEGORIES

VERSION = 2
NAME = "add_origins_and_categories"


def _table_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _backfill_categories(conn) -> None:
    rows = conn.execute("SELECT id, grupo_muscular FROM ejercicios WHERE categoria IS NULL").fetchall()
    if not rows:
        return
    muscle_to_cat = {}
    for cat in MUSCLE_CATEGORIES:
        for muscle in cat["muscles"]:
            muscle_to_cat[muscle.strip().lower()] = cat["name"]
    for row_id, grupo in rows:
        cat = muscle_to_cat.get(str(grupo).strip().lower())
        if cat:
            conn.execute("UPDATE ejercicios SET categoria = ? WHERE id = ?", (cat, row_id))


def migrate(conn) -> None:
    sets_cols = _table_columns(conn, "training_sets")
    if "origen" not in sets_cols:
        conn.execute("ALTER TABLE training_sets ADD COLUMN origen TEXT NOT NULL DEFAULT 'google'")
    ej_cols = _table_columns(conn, "ejercicios")
    if "categoria" not in ej_cols:
        conn.execute("ALTER TABLE ejercicios ADD COLUMN categoria TEXT")
    if "origen" not in ej_cols:
        conn.execute("ALTER TABLE ejercicios ADD COLUMN origen TEXT NOT NULL DEFAULT 'google'")
    _backfill_categories(conn)
