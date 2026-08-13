"""Cardio annotations: user-supplied speed/incline over Health Connect sessions.

Only EXERCISE_SESSION records (the mirrored hc_id must exist and not be
logically deleted). An annotation with all fields empty deletes the row.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from src.db_connection import transaction
from src.models import ValidationError


@dataclass(frozen=True)
class CardioAnnotationInput:
    hc_id: str
    velocidad_kmh: float | None
    inclinacion_pct: float | None
    notas: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def upsert_cardio_annotation(db_path: str, data: CardioAnnotationInput) -> None:
    """Valida que hc_id exista y sea EXERCISE_SESSION; upsert; vacío = delete."""
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT record_type FROM health_records WHERE hc_id = ? AND deleted_at IS NULL",
            (data.hc_id,),
        ).fetchone()
        if row is None:
            raise ValidationError("Sesión de cardio no encontrada.")
        if row[0] != "EXERCISE_SESSION":
            raise ValidationError("La anotación solo aplica a sesiones de ejercicio.")
        if data.velocidad_kmh is None and data.inclinacion_pct is None and not data.notas.strip():
            conn.execute("DELETE FROM cardio_annotations WHERE hc_id = ?", (data.hc_id,))
            return
        now = _now()
        conn.execute(
            """INSERT INTO cardio_annotations
                   (hc_id, velocidad_kmh, inclinacion_pct, notas, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(hc_id) DO UPDATE SET
                   velocidad_kmh = excluded.velocidad_kmh,
                   inclinacion_pct = excluded.inclinacion_pct,
                   notas = excluded.notas,
                   updated_at = excluded.updated_at""",
            (data.hc_id, data.velocidad_kmh, data.inclinacion_pct, data.notas.strip(), now, now),
        )


# ---------------------------------------------------------------------------
# Lecturas del día (para el popup de registro): cardio + recuperación
# ---------------------------------------------------------------------------

from src.db_connection import read_connection


def get_day_cardio(db_path: str, fecha_iso: str) -> list[dict]:
    """Sesiones EXERCISE_SESSION del día + anotación manual (si existe)."""
    with read_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT h.hc_id,
                   json_extract(h.value_json, '$.value.title') AS titulo,
                   (h.end_epoch_ms - h.start_epoch_ms) / 60000.0 AS duracion_min,
                   a.velocidad_kmh,
                   a.inclinacion_pct,
                   COALESCE(a.notas, '')
            FROM health_records h
            LEFT JOIN cardio_annotations a ON a.hc_id = h.hc_id
            WHERE h.record_type = 'EXERCISE_SESSION'
              AND date(h.start_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND h.deleted_at IS NULL
            ORDER BY h.start_epoch_ms
            """,
            (fecha_iso,),
        ).fetchall()
    return [
        {
            "hc_id": r[0],
            "titulo": r[1] or "Sesión de ejercicio",
            "duracion_min": round(float(r[2]), 1) if r[2] is not None else 0.0,
            "velocidad_kmh": float(r[3]) if r[3] is not None else None,
            "inclinacion_pct": float(r[4]) if r[4] is not None else None,
            "notas": str(r[5] or ""),
        }
        for r in rows
    ]


def get_day_fc_media(db_path: str, fecha_iso: str) -> float | None:
    """FC media diaria a partir de buckets de 5 min (HEART_RATE_5MIN)."""
    with read_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT AVG(json_extract(s.value, '$.bpm'))
            FROM health_records h, json_each(h.value_json, '$.value.samples') s
            WHERE h.record_type = 'HEART_RATE_5MIN'
              AND date(h.start_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND h.deleted_at IS NULL
            """,
            (fecha_iso,),
        ).fetchone()
    return round(float(row[0])) if row and row[0] is not None else None


def get_day_sleep_prev_night(db_path: str, fecha_iso: str) -> float | None:
    """Horas de sueño de la noche anterior (sesión que termina el día)."""
    with read_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT SUM(end_epoch_ms - start_epoch_ms) / 3600000.0
            FROM health_records
            WHERE record_type = 'SLEEP_SESSION'
              AND date(end_epoch_ms / 1000, 'unixepoch', 'localtime') = ?
              AND deleted_at IS NULL
            """,
            (fecha_iso,),
        ).fetchone()
    return round(float(row[0]), 1) if row and row[0] is not None else None
