"""Daily analysis layers: aggregation over health_records and domain tables."""

import json
import sqlite3
from datetime import datetime

import pytest

from src.analysis_data import (
    daily_avg_hr,
    daily_cardio_minutes,
    daily_hrv,
    daily_kcal,
    daily_resting_hr,
    daily_sleep_hours,
    daily_steps,
    daily_volume,
    daily_weight,
)

TZ = "2026-08-10 12:00:00"


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


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
        CREATE TABLE diario_alimentacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL,
            orden INTEGER NOT NULL, alimento TEXT NOT NULL, cantidad_g REAL,
            kcal REAL NOT NULL, carbohidratos REAL NOT NULL, fibra REAL NOT NULL,
            proteina REAL NOT NULL, grasa REAL NOT NULL, hierro REAL NOT NULL,
            calcio REAL NOT NULL, vitamina_c REAL NOT NULL, vitamina_a REAL NOT NULL,
            origen TEXT NOT NULL DEFAULT 'google'
        );
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY, semana INTEGER NOT NULL, dia TEXT NOT NULL,
            fecha TEXT, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL,
            reps REAL, kg REAL, rir REAL, descanso_seg REAL,
            origen TEXT NOT NULL DEFAULT 'google'
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _insert_hr(conn, record_type, value_json, start, end=None, deleted=None):
    value_json = json.dumps({"value": json.loads(value_json)})
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (
            f"{record_type}-{start}-{conn.total_changes}",
            record_type,
            start,
            end or start,
            start,
            value_json,
            TZ,
            TZ,
            deleted,
        ),
    )


def test_sleep_hours_por_fecha_de_fin(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "SLEEP_SESSION", "{}", _ts("2026-08-09 23:00"), end=_ts("2026-08-10 07:30"))
    conn.commit()
    conn.close()
    df = daily_sleep_hours(db)
    assert len(df) == 1
    assert str(df.iloc[0]["fecha_dt"].date()) == "2026-08-10"
    assert df.iloc[0]["valor"] == pytest.approx(8.5)


def test_resting_hr_promedio_diario(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "RESTING_HEART_RATE", '{"bpm": 58}', _ts("2026-08-10 07:00"))
    _insert_hr(conn, "RESTING_HEART_RATE", '{"bpm": 62}', _ts("2026-08-10 08:00"))
    conn.commit()
    conn.close()
    df = daily_resting_hr(db)
    assert df.iloc[0]["valor"] == pytest.approx(60.0)


def test_avg_hr_desde_buckets_5min(db):
    conn = sqlite3.connect(db)
    _insert_hr(
        conn,
        "HEART_RATE_5MIN",
        '{"samples": [{"time": 1, "bpm": 120}, {"time": 2, "bpm": 140}]}',
        _ts("2026-08-10 12:00"),
        end=_ts("2026-08-10 12:05"),
    )
    conn.commit()
    conn.close()
    df = daily_avg_hr(db)
    assert df.iloc[0]["valor"] == pytest.approx(130.0)


def test_hrv_promedio_diario(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "HEART_RATE_VARIABILITY_RMSSD", '{"rmssd_ms": 45}', _ts("2026-08-10 06:00"))
    _insert_hr(conn, "HEART_RATE_VARIABILITY_RMSSD", '{"rmssd_ms": 55}', _ts("2026-08-10 07:00"))
    conn.commit()
    conn.close()
    df = daily_hrv(db)
    assert df.iloc[0]["valor"] == pytest.approx(50.0)


def test_steps_suma_diaria(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "STEPS", '{"count": 4000}', _ts("2026-08-10 09:00"))
    _insert_hr(conn, "STEPS", '{"count": 3000}', _ts("2026-08-10 15:00"))
    conn.commit()
    conn.close()
    df = daily_steps(db)
    assert df.iloc[0]["valor"] == 7000


def test_cardio_minutes_suma_diaria(db):
    conn = sqlite3.connect(db)
    _insert_hr(
        conn,
        "EXERCISE_SESSION",
        '{"exercise_type": 17}',
        _ts("2026-08-10 08:00"),
        end=_ts("2026-08-10 08:30"),
    )
    _insert_hr(
        conn,
        "EXERCISE_SESSION",
        '{"exercise_type": 17}',
        _ts("2026-08-10 18:00"),
        end=_ts("2026-08-10 18:20"),
    )
    conn.commit()
    conn.close()
    df = daily_cardio_minutes(db)
    assert df.iloc[0]["valor"] == pytest.approx(50.0)


def test_weight_promedio_diario(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "WEIGHT", '{"kg": 82.5}', _ts("2026-08-10 07:00"))
    _insert_hr(conn, "WEIGHT", '{"kg": 83.5}', _ts("2026-08-10 19:00"))
    conn.commit()
    conn.close()
    df = daily_weight(db)
    assert df.iloc[0]["valor"] == pytest.approx(83.0)


def test_deleted_records_excluidas(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "STEPS", '{"count": 5000}', _ts("2026-08-10 09:00"))
    _insert_hr(conn, "STEPS", '{"count": 9000}', _ts("2026-08-09 09:00"), deleted="2026-08-11")
    conn.commit()
    conn.close()
    df = daily_steps(db)
    assert len(df) == 1
    assert df.iloc[0]["valor"] == 5000


def test_kcal_suma_diaria(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, kcal, carbohidratos, fibra, "
        "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2026-08-10', 1, 'Avena', 350, 60, 10, 12, 6, 1, 1, 1, 1),"
        "       ('2026-08-10', 2, 'Pollo', 200, 0, 0, 40, 5, 0, 0, 0, 0)"
    )
    conn.commit()
    conn.close()
    df = daily_kcal(db)
    assert df.iloc[0]["valor"] == 550


def test_volume_suma_diaria(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg) "
        "VALUES (14, 'LUNES', '2026-08-10', 1, 'Press', 8, 80),"
        "       (14, 'LUNES', '2026-08-10', 2, 'Press', 6, 90)"
    )
    conn.commit()
    conn.close()
    df = daily_volume(db)
    assert df.iloc[0]["valor"] == 1180
