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
