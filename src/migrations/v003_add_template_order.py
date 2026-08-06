"""v003 — add `plantillas.orden` for drag-and-drop reordering."""

VERSION = 3
NAME = "add_template_order"


def migrate(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(plantillas)").fetchall()}
    if "orden" not in cols:
        conn.execute("ALTER TABLE plantillas ADD COLUMN orden INTEGER NOT NULL DEFAULT 0")
