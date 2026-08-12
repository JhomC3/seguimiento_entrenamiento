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
    upsert_cardio_annotation(db, CardioAnnotationInput(hc_id="c1", velocidad_kmh=None, inclinacion_pct=None, notas=""))
    assert _fetch(db, "c1") is None


def test_rechaza_hc_inexistente(db):
    with pytest.raises(ValidationError):
        upsert_cardio_annotation(
            db, CardioAnnotationInput(hc_id="nope", velocidad_kmh=5.0, inclinacion_pct=None, notas="")
        )


def test_rechaza_tipo_no_exercise(db):
    with pytest.raises(ValidationError):
        upsert_cardio_annotation(
            db, CardioAnnotationInput(hc_id="s1", velocidad_kmh=5.0, inclinacion_pct=None, notas="")
        )
