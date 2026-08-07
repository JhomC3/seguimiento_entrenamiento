"""v005 — recompute `training_sets.semana` from `fecha` (Monday-Sunday cycle weeks).

The current cycle started 2026-05-04 (Monday). Sessions saved before this
migration used a stale cycle start and landed on wrong week numbers; this
migration recomputes every row's week from its date with the Monday-anchored
rule (week 1 = the Mon-Sun calendar week containing the cycle start).
Idempotent: running it twice yields the same result.
"""

from datetime import date, datetime, timedelta

VERSION = 5
NAME = "recompute_semana"

CYCLE_START = date(2026, 5, 4)

_FMT_LEGACY = "%d/%m/%y"
_FMT_LEGACY_4Y = "%d/%m/%Y"
_FMT_ISO = "%Y-%m-%d"


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (_FMT_LEGACY, _FMT_LEGACY_4Y, _FMT_ISO):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _cycle_week(fecha: date) -> int:
    monday = CYCLE_START - timedelta(days=CYCLE_START.weekday())
    return max(1, (fecha - monday).days // 7 + 1)


def migrate(conn) -> None:
    rows = conn.execute("SELECT id, fecha FROM training_sets").fetchall()
    for row_id, fecha in rows:
        parsed = _parse_date(fecha)
        if parsed is None:
            continue
        conn.execute(
            "UPDATE training_sets SET semana = ? WHERE id = ?", (_cycle_week(parsed), row_id)
        )
