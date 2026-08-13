"""Cardio annotations: upsert/delete over health_records EXERCISE_SESSION."""

import sqlite3

import pytest

from src.cardio_service import CardioAnnotationInput, upsert_cardio_annotation
from src.models import ValidationError


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "t.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE health_records (
            hc_id TEXT PRIMARY KEY, record_type TEXT NOT NULL,
            start_epoch_ms INTEGER NOT NULL, end_epoch_ms INTEGER,
            last_modified_epoch_ms INTEGER NOT NULL, data_origin_package TEXT,
            payload_schema_version INTEGER NOT NULL, value_json TEXT NOT NULL,
            device_id TEXT NOT NULL DEFAULT '', received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, deleted_at TEXT
        );
        CREATE TABLE cardio_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hc_id TEXT NOT NULL UNIQUE REFERENCES health_records(hc_id) ON DELETE CASCADE,
            velocidad_kmh REAL, inclinacion_pct REAL, notas TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('c1', 'EXERCISE_SESSION', 1, 2, 1, 1, '{}', 'x', 'x'),"
        "       ('s1', 'SLEEP_SESSION', 1, 2, 1, 1, '{}', 'x', 'x')"
    )
    conn.commit()
    conn.close()
    return db_path


def _fetch(db, hc_id):
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT velocidad_kmh, inclinacion_pct, notas FROM cardio_annotations WHERE hc_id = ?",
        (hc_id,),
    ).fetchone()
    conn.close()
    return row


def test_upsert_crea_anotacion(db):
    upsert_cardio_annotation(
        db,
        CardioAnnotationInput(hc_id="c1", velocidad_kmh=5.5, inclinacion_pct=2.0, notas="caminata"),
    )
    assert _fetch(db, "c1") == (5.5, 2.0, "caminata")


def test_upsert_actualiza_existente(db):
    upsert_cardio_annotation(
        db, CardioAnnotationInput(hc_id="c1", velocidad_kmh=5.5, inclinacion_pct=2.0, notas="")
    )
    upsert_cardio_annotation(
        db, CardioAnnotationInput(hc_id="c1", velocidad_kmh=6.0, inclinacion_pct=1.0, notas="trote")
    )
    assert _fetch(db, "c1") == (6.0, 1.0, "trote")


def test_vacio_elimina_anotacion(db):
    upsert_cardio_annotation(
        db, CardioAnnotationInput(hc_id="c1", velocidad_kmh=5.5, inclinacion_pct=2.0, notas="x")
    )
    upsert_cardio_annotation(
        db, CardioAnnotationInput(hc_id="c1", velocidad_kmh=None, inclinacion_pct=None, notas="")
    )
    assert _fetch(db, "c1") is None


def test_rechaza_hc_inexistente(db):
    with pytest.raises(ValidationError):
        upsert_cardio_annotation(
            db,
            CardioAnnotationInput(hc_id="nope", velocidad_kmh=5.0, inclinacion_pct=None, notas=""),
        )


def test_rechaza_tipo_no_exercise(db):
    with pytest.raises(ValidationError):
        upsert_cardio_annotation(
            db, CardioAnnotationInput(hc_id="s1", velocidad_kmh=5.0, inclinacion_pct=None, notas="")
        )


def test_get_day_cardio_con_anotacion(db):
    import json

    from src.cardio_service import get_day_cardio

    ts = lambda iso: int(__import__("datetime").datetime.fromisoformat(iso).timestamp() * 1000)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE health_records SET start_epoch_ms = ?, end_epoch_ms = ?, value_json = ? "
        "WHERE hc_id = 'c1'",
        (ts("2026-08-10 08:00"), ts("2026-08-10 08:30"), json.dumps({"value": {"title": "Cinta"}})),
    )
    conn.execute(
        "INSERT INTO cardio_annotations (hc_id, velocidad_kmh, inclinacion_pct, notas, created_at, updated_at) "
        "VALUES ('c1', 5.5, 2.0, 'caminata', 'x', 'x')"
    )
    conn.commit()
    conn.close()
    rows = get_day_cardio(db, "2026-08-10")
    assert len(rows) == 1
    assert rows[0]["hc_id"] == "c1"
    assert rows[0]["titulo"] == "Cinta"
    assert rows[0]["duracion_min"] == 30.0
    assert rows[0]["velocidad_kmh"] == 5.5
    assert rows[0]["inclinacion_pct"] == 2.0


def test_get_day_fc_media_y_sueno(db):
    from src.cardio_service import get_day_fc_media, get_day_sleep_prev_night

    ts = lambda iso: int(__import__("datetime").datetime.fromisoformat(iso).timestamp() * 1000)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('h1', 'HEART_RATE_5MIN', ?, ?, ?, 1, "
        "'{\"value\": {\"samples\": [{\"time\": 1, \"bpm\": 120}, {\"time\": 2, \"bpm\": 140}]}}', 'x', 'x')",
        (ts("2026-08-10 12:00"), ts("2026-08-10 12:05"), ts("2026-08-10 12:05")),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('s1b', 'SLEEP_SESSION', ?, ?, ?, 1, '{\"value\": {}}', 'x', 'x')",
        (ts("2026-08-09 23:00"), ts("2026-08-10 07:30"), ts("2026-08-10 07:30")),
    )
    conn.commit()
    conn.close()
    assert get_day_fc_media(db, "2026-08-10") == 130
    assert get_day_sleep_prev_night(db, "2026-08-10") == 8.5
