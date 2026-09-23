"""Dominio de respiración B5.0 (src/breathing_service.py).

Valida patrones de 4 fases, simulación de ciclos con rampa lineal y
validación de borde del payload móvil. El vector de rampa está congelado
en docs/architecture/breathing-vectors.json (misma fuente que Kotlin).
"""

import datetime
import json
import time
import uuid
from pathlib import Path

import pytest

from src.breathing_service import (
    BreathingPattern,
    cycle_seconds,
    derive_fecha,
    simulate,
    validate_pattern,
    validate_session_payload,
)
from src.models import ValidationError

VECTORS = json.loads(
    (Path(__file__).parent.parent / "docs" / "architecture" / "breathing-vectors.json").read_text()
)


def _ms(y: int, m: int, d: int, hh: int = 7, mm: int = 0) -> int:
    return int(datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.UTC).timestamp() * 1000)


def _payload(**over):
    base = {
        "client_session_id": str(uuid.uuid4()),
        "start_epoch_ms": _ms(2026, 9, 13),
        "end_epoch_ms": _ms(2026, 9, 13) + 120_000,
        "time_zone_offset_minutes": 0,
        "patron": {"inhale_s": 4.0, "hold_in_s": 0.0, "exhale_s": 6.0, "hold_out_s": 0.0},
    }
    base.update(over)
    return base


# --- Patrones -----------------------------------------------------------------


def test_validate_pattern_constante_ok():
    p = validate_pattern({"inhale_s": 4, "exhale_s": 6})
    assert (p.inhale_s, p.hold_in_s, p.exhale_s, p.hold_out_s) == (4.0, 0.0, 6.0, 0.0)
    assert p.ramp_sec is None
    assert not p.has_ramp


def test_validate_pattern_rampa_ok():
    raw = dict(VECTORS["rampa_lineal"]["patron"])
    p = validate_pattern(raw)
    assert p.has_ramp
    assert p.ramp_sec == 480
    assert p.end_exhale_s == 9.0


def test_validate_pattern_errores():
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": 0, "exhale_s": 6})
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": 4, "exhale_s": 61})
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": 4, "exhale_s": 6, "hold_in_s": -1})
    with pytest.raises(ValidationError):
        validate_pattern("no-dict")  # type: ignore[arg-type]
    # end_* sin ramp_sec
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": 4, "exhale_s": 6, "end_inhale_s": 6})
    # ramp fuera de rango
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": 4, "exhale_s": 6, "ramp_sec": 10})
    with pytest.raises(ValidationError):
        validate_pattern({"inhale_s": "lento", "exhale_s": 6})


# --- Simulación -----------------------------------------------------------------


def test_cycle_seconds_constante():
    p = BreathingPattern(inhale_s=4.0, hold_in_s=0.0, exhale_s=6.0, hold_out_s=0.0)
    assert cycle_seconds(p, 0) == 10.0
    assert cycle_seconds(p, 9999) == 10.0


def test_cycle_seconds_rampa_progresa():
    p = validate_pattern(dict(VECTORS["rampa_lineal"]["patron"]))
    assert cycle_seconds(p, 0) == VECTORS["rampa_lineal"]["ciclo_t0"]
    assert cycle_seconds(p, 480) == VECTORS["rampa_lineal"]["ciclo_t_ramp"]
    assert cycle_seconds(p, 10_000) == VECTORS["rampa_lineal"]["ciclo_t_ramp"]


def test_simulate_vector_rampa_congelado():
    p = validate_pattern(dict(VECTORS["rampa_lineal"]["patron"]))
    ciclos, bpm = simulate(p, VECTORS["rampa_lineal"]["duracion_real_sec"])
    assert ciclos == VECTORS["rampa_lineal"]["ciclos_completados"]
    assert bpm == VECTORS["rampa_lineal"]["bpm_medio"]


def test_simulate_vector_constante_congelado():
    p = validate_pattern(dict(VECTORS["constante"]["patron"]))
    ciclos, bpm = simulate(p, VECTORS["constante"]["duracion_real_sec"])
    assert ciclos == VECTORS["constante"]["ciclos_completados"]
    assert bpm == VECTORS["constante"]["bpm_medio"]


def test_simulate_vector_exacto_6_6_congelado():
    p = validate_pattern(dict(VECTORS["exacto_6_6"]["patron"]))
    ciclos, bpm = simulate(p, VECTORS["exacto_6_6"]["duracion_real_sec"])
    assert ciclos == VECTORS["exacto_6_6"]["ciclos_completados"]
    assert bpm == VECTORS["exacto_6_6"]["bpm_medio"]


def test_simulate_vector_exacto_5_5_congelado():
    p = validate_pattern(dict(VECTORS["exacto_5_5"]["patron"]))
    ciclos, bpm = simulate(p, VECTORS["exacto_5_5"]["duracion_real_sec"])
    assert ciclos == VECTORS["exacto_5_5"]["ciclos_completados"]
    assert bpm == VECTORS["exacto_5_5"]["bpm_medio"]


def test_simulate_solo_ciclos_completos():
    p = BreathingPattern(inhale_s=4.0, hold_in_s=0.0, exhale_s=6.0, hold_out_s=0.0)
    ciclos, _bpm = simulate(p, 15)
    assert ciclos == 1


# --- Fechas ---------------------------------------------------------------------


def test_derive_fecha_dia_de_inicio():
    assert derive_fecha(_ms(2026, 9, 13), 0) == "2026-09-13"


def test_derive_fecha_offset_negativo_cruza_medianoche():
    # 02:00 UTC con offset -300 → 21:00 del día anterior en local.
    assert derive_fecha(_ms(2026, 9, 13, hh=2), -300) == "2026-09-12"


# --- Payload --------------------------------------------------------------------


def test_payload_ok_timer_off():
    out = validate_session_payload(_payload())
    assert out.duracion_planeada_sec is None
    assert out.completada is True
    assert out.pattern.inhale_s == 4.0


def test_payload_ok_con_planeada_y_rampa():
    patron = dict(VECTORS["rampa_lineal"]["patron"])
    out = validate_session_payload(
        _payload(
            end_epoch_ms=_ms(2026, 9, 13) + 600_000,
            duracion_planeada_sec=600,
            patron=patron,
            completada=False,
        )
    )
    assert out.duracion_planeada_sec == 600
    assert out.completada is False


def test_payload_errores():
    base_bad_uuid = _payload(client_session_id="no-uuid")
    with pytest.raises(ValidationError):
        validate_session_payload(base_bad_uuid)
    with pytest.raises(ValidationError):
        validate_session_payload("no-dict")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        validate_session_payload(
            _payload(start_epoch_ms=_ms(2026, 9, 13) + 5_000, end_epoch_ms=_ms(2026, 9, 13))
        )
    future = int(time.time() * 1000) + 3_600_000
    with pytest.raises(ValidationError):
        validate_session_payload(_payload(start_epoch_ms=future, end_epoch_ms=future + 120_000))
    with pytest.raises(ValidationError):
        validate_session_payload(_payload(time_zone_offset_minutes=9999))
    with pytest.raises(ValidationError):
        validate_session_payload(_payload(duracion_planeada_sec=10))
    with pytest.raises(ValidationError):
        validate_session_payload(_payload(completada="si"))
    # Menos de un ciclo (15 s por ciclo, 5 s reales).
    with pytest.raises(ValidationError):
        validate_session_payload(
            _payload(
                end_epoch_ms=_ms(2026, 9, 13) + 5_000,
                patron={"inhale_s": 4, "hold_in_s": 2, "exhale_s": 6, "hold_out_s": 3},
            )
        )
    # Rampa mayor que la sesión.
    with pytest.raises(ValidationError):
        validate_session_payload(
            _payload(
                patron={
                    "inhale_s": 4,
                    "exhale_s": 6,
                    "ramp_sec": 300,
                    "end_inhale_s": 6,
                    "end_exhale_s": 8,
                }
            )
        )
