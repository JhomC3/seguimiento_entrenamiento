"""v006 — normalize `training_sets.fecha` to ISO (YYYY-MM-DD).

Legacy rows stored dates as `d/m/yy` (or `d/m/YYYY`); SQLite string ordering
then diverges from chronological order. After this migration every row holds a
zero-padded ISO date, so `ORDER BY fecha` is chronological in SQL.
Rows that don't parse are sanitized to NULL (safe for consumers).
Idempotent: running it twice leaves ISO values untouched.
"""

from datetime import datetime

VERSION = 6
NAME = "iso_dates"

_LEGACY_COL = "fecha_legacy"

_FMT_LEGACY = "%d/%m/%y"
_FMT_LEGACY_4Y = "%d/%m/%Y"
_FMT_ISO = "%Y-%m-%d"


def _iso_or_null(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (_FMT_LEGACY, _FMT_LEGACY_4Y):
        try:
            return datetime.strptime(text, fmt).date().strftime(_FMT_ISO)
        except ValueError:
            continue
    return None


def migrate(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(training_sets)").fetchall()}
    if _LEGACY_COL in cols or "fecha" not in cols:
        return
    # Los índices sobre `fecha` (p. ej. v014) siguen el rename de columna y
    # bloquearían el DROP de la columna legacy: se recrean al final.
    indexes = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name='training_sets' AND sql IS NOT NULL"
    ).fetchall()
    with conn:
        for name, _ in indexes:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.execute(f"ALTER TABLE training_sets RENAME COLUMN fecha TO {_LEGACY_COL}")
        conn.execute("ALTER TABLE training_sets ADD COLUMN fecha TEXT")
        for row_id, legacy in conn.execute(
            f"SELECT id, {_LEGACY_COL} FROM training_sets"
        ).fetchall():
            conn.execute(
                "UPDATE training_sets SET fecha = ? WHERE id = ?", (_iso_or_null(legacy), row_id)
            )
        conn.execute(f"ALTER TABLE training_sets DROP COLUMN {_LEGACY_COL}")
        for name, sql in indexes:
            conn.execute(sql.replace(_LEGACY_COL, "fecha"))
