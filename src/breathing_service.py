"""Breathing domain (B5.0): paced-breathing patterns and session math.

Pure domain: no SQL, no I/O. The server always recomputes
`ciclos_completados`, `bpm_medio` and `fecha` — values sent by the client
are validated inputs, never stored truths (same rule as nutrition/RM).

Ramp (linear per cycle): the cycle `k` starting at second `t_k` uses
`factor = min(1, t_k / ramp_sec)` (`0` without ramp) and each phase lasts
`start + (end - start) * factor`, rounded to 0.1 s half-up. The same
formula is ported to Android (`BreathingEngine`); the frozen vector in
`docs/architecture/breathing-vectors.json` pins both implementations.
"""

import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from src.models import ValidationError

MIN_ACTIVE_PHASE_S = 0.5
MAX_PHASE_S = 60.0
MIN_PLANNED_SEC = 30
MAX_PLANNED_SEC = 7200
MIN_REAL_SEC = 5
MAX_REAL_SEC = 14400
MAX_TZ_OFFSET_MIN = 840
FUTURE_SKEW_MS = 5 * 60 * 1000


@dataclass(frozen=True)
class BreathingPattern:
    """Start phases (s) plus optional linear ramp to end phases."""

    inhale_s: float
    hold_in_s: float
    exhale_s: float
    hold_out_s: float
    ramp_sec: int | None = None
    end_inhale_s: float | None = None
    end_hold_in_s: float | None = None
    end_exhale_s: float | None = None
    end_hold_out_s: float | None = None

    @property
    def has_ramp(self) -> bool:
        return self.ramp_sec is not None and any(
            v is not None
            for v in (
                self.end_inhale_s,
                self.end_hold_in_s,
                self.end_exhale_s,
                self.end_hold_out_s,
            )
        )


@dataclass(frozen=True)
class BreathingSessionInput:
    """A validated breathing session submission, before persistence."""

    client_session_id: str
    start_epoch_ms: int
    end_epoch_ms: int
    time_zone_offset_minutes: int
    pattern: BreathingPattern
    duracion_planeada_sec: int | None = None
    completada: bool = True


@dataclass(frozen=True)
class BreathingSession:
    """A persisted breathing session with server-computed metrics."""

    client_session_id: str
    fecha: str
    start_epoch_ms: int
    end_epoch_ms: int
    time_zone_offset_minutes: int
    duracion_planeada_sec: int | None
    duracion_real_sec: int
    pattern: BreathingPattern
    ciclos_completados: int
    bpm_medio: float
    completada: bool


def _round_1(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _phase_number(value, field: str, *, minimum: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    if math.isnan(num) or math.isinf(num) or not minimum <= num <= MAX_PHASE_S:
        raise ValidationError(f"El campo {field} debe estar entre {minimum} y 60 s.")
    return num


def _opt_phase_number(value, field: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return _phase_number(value, field, minimum=MIN_ACTIVE_PHASE_S if "hold" not in field else 0.0)


def validate_pattern(raw: dict) -> BreathingPattern:
    """Validate a 4-phase pattern dict (start + optional ramp end)."""
    if not isinstance(raw, dict):
        raise ValidationError("Patrón de respiración inválido.")
    inhale = _phase_number(raw.get("inhale_s"), "inhale_s", minimum=MIN_ACTIVE_PHASE_S)
    hold_in = _phase_number(raw.get("hold_in_s", 0), "hold_in_s", minimum=0.0)
    exhale = _phase_number(raw.get("exhale_s"), "exhale_s", minimum=MIN_ACTIVE_PHASE_S)
    hold_out = _phase_number(raw.get("hold_out_s", 0), "hold_out_s", minimum=0.0)
    ramp_raw = raw.get("ramp_sec", None)
    ramp_sec: int | None = None
    if ramp_raw is not None and str(ramp_raw).strip() != "":
        try:
            ramp_sec = int(float(ramp_raw))
        except (TypeError, ValueError):
            raise ValidationError("El campo ramp_sec debe ser numérico.")
        if not MIN_PLANNED_SEC <= ramp_sec <= MAX_PLANNED_SEC:
            raise ValidationError(
                f"El campo ramp_sec debe estar entre {MIN_PLANNED_SEC} y {MAX_PLANNED_SEC} s."
            )
    ends = {
        name: _opt_phase_number(raw.get(name), name)
        for name in ("end_inhale_s", "end_hold_in_s", "end_exhale_s", "end_hold_out_s")
    }
    if any(v is not None for v in ends.values()) and ramp_sec is None:
        raise ValidationError("La rampa (end_*) requiere ramp_sec.")
    return BreathingPattern(
        inhale_s=inhale,
        hold_in_s=hold_in,
        exhale_s=exhale,
        hold_out_s=hold_out,
        ramp_sec=ramp_sec,
        **ends,  # type: ignore[arg-type]
    )


def _epoch_ms(value, field: str) -> int:
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    if num < 0:
        raise ValidationError(f"El campo {field} debe ser ≥ 0.")
    return num


def validate_session_payload(body: dict) -> BreathingSessionInput:
    """Validate the POST /api/v1/respiracion/sesion body (border validation)."""
    if not isinstance(body, dict):
        raise ValidationError("Cuerpo JSON inválido.")
    raw_id = body.get("client_session_id", "")
    try:
        session_id = str(uuid.UUID(str(raw_id)))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("El campo client_session_id debe ser un UUID.")
    start_ms = _epoch_ms(body.get("start_epoch_ms"), "start_epoch_ms")
    end_ms = _epoch_ms(body.get("end_epoch_ms"), "end_epoch_ms")
    if end_ms < start_ms:
        raise ValidationError("El fin de la sesión es anterior a su inicio.")
    now_ms = int(time.time() * 1000)
    if start_ms > now_ms + FUTURE_SKEW_MS or end_ms > now_ms + FUTURE_SKEW_MS:
        raise ValidationError("La sesión está en el futuro.")
    try:
        tz_offset = int(float(body.get("time_zone_offset_minutes", 0) or 0))
    except (TypeError, ValueError):
        raise ValidationError("El campo time_zone_offset_minutes debe ser numérico.")
    if not -MAX_TZ_OFFSET_MIN <= tz_offset <= MAX_TZ_OFFSET_MIN:
        raise ValidationError("Zona horaria fuera de rango.")
    pattern = validate_pattern(body.get("patron", {}))
    planned_raw = body.get("duracion_planeada_sec", None)
    planned: int | None = None
    if planned_raw is not None and str(planned_raw).strip() != "":
        try:
            planned = int(float(planned_raw))
        except (TypeError, ValueError):
            raise ValidationError("El campo duracion_planeada_sec debe ser numérico.")
        if not MIN_PLANNED_SEC <= planned <= MAX_PLANNED_SEC:
            raise ValidationError(
                f"El campo duracion_planeada_sec debe estar entre "
                f"{MIN_PLANNED_SEC} y {MAX_PLANNED_SEC} s."
            )
    real_sec = round((end_ms - start_ms) / 1000)
    if not MIN_REAL_SEC <= real_sec <= MAX_REAL_SEC:
        raise ValidationError(
            f"La duración real debe estar entre {MIN_REAL_SEC} y {MAX_REAL_SEC} s."
        )
    effective_total = planned if planned is not None else real_sec
    if pattern.ramp_sec is not None and pattern.ramp_sec > effective_total:
        raise ValidationError("La rampa no puede superar la duración de la sesión.")
    raw_done = body.get("completada", True)
    if isinstance(raw_done, bool):
        completada = raw_done
    elif raw_done in (0, 1):
        completada = bool(raw_done)
    else:
        raise ValidationError("El campo completada debe ser verdadero o falso.")
    ciclos, _bpm = simulate(pattern, real_sec)
    if ciclos < 1:
        raise ValidationError("La sesión no completa ni un ciclo de respiración.")
    return BreathingSessionInput(
        client_session_id=session_id,
        start_epoch_ms=start_ms,
        end_epoch_ms=end_ms,
        time_zone_offset_minutes=tz_offset,
        pattern=pattern,
        duracion_planeada_sec=planned,
        completada=completada,
    )


def cycle_seconds(pattern: BreathingPattern, t_start_sec: float) -> float:
    """Duration (s) of the cycle starting at `t_start_sec` (ramp-aware)."""
    if pattern.has_ramp and pattern.ramp_sec:
        factor = min(1.0, t_start_sec / pattern.ramp_sec)
    else:
        factor = 0.0

    def phase(start: float, end: float | None) -> float:
        target = start if end is None else end
        return _round_1(start + (target - start) * factor)

    return (
        phase(pattern.inhale_s, pattern.end_inhale_s)
        + phase(pattern.hold_in_s, pattern.end_hold_in_s)
        + phase(pattern.exhale_s, pattern.end_exhale_s)
        + phase(pattern.hold_out_s, pattern.end_hold_out_s)
    )


def simulate(pattern: BreathingPattern, duracion_real_sec: int) -> tuple[int, float]:
    """Count full cycles fitting in `duracion_real_sec`; mean breaths/minute."""
    ciclos = 0
    elapsed = 0.0
    while True:
        current = cycle_seconds(pattern, elapsed)
        if current <= 0 or elapsed + current > duracion_real_sec + 1e-9:
            break
        elapsed += current
        ciclos += 1
    bpm = round(60.0 * ciclos / elapsed, 1) if ciclos else 0.0
    return ciclos, bpm


def derive_fecha(start_epoch_ms: int, tz_offset_min: int) -> str:
    """Session day (ISO) from start instant + device offset. Start day wins."""
    local = datetime.fromtimestamp(start_epoch_ms / 1000, tz=UTC) + timedelta(minutes=tz_offset_min)
    return local.strftime("%Y-%m-%d")
