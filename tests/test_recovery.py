"""Índice de recuperación derivado: composite transparente de z-scores personales."""

import json
import sqlite3
from datetime import datetime

import pytest

from src.recovery import RecoveryConfig, daily_recovery, recovery_vs_performance

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
        CREATE TABLE ejercicios (id INTEGER PRIMARY KEY, grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE, categoria TEXT, origen TEXT NOT NULL DEFAULT 'google');
        CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER NOT NULL, dia TEXT NOT NULL,
            fecha TEXT, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, reps REAL, kg REAL,
            rir REAL, descanso_seg REAL, origen TEXT NOT NULL DEFAULT 'google');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _insert_hr(conn, record_type, value, start, end=None):
    payload = json.dumps({"value": value})
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (
            f"{record_type}-{start}-{conn.total_changes}",
            record_type,
            start,
            end or start,
            start,
            payload,
            TZ,
            TZ,
        ),
    )


def _stable_week(conn, hrv_base=50.0, rhr_base=60.0, sleep_h=8.0, start_day=10, days=8):
    """Semana estable CON varianza mínima (alterna ±1): sin varianza el z-score
    es NaN por std=0 y el día no puntúa (diseño: sin basal no hay score)."""
    for i, d in enumerate(range(start_day, start_day + days)):
        day = f"2026-08-{d:02d}"
        delta = 1.0 if i % 2 else -1.0
        _insert_hr(
            conn,
            "HEART_RATE_VARIABILITY_RMSSD",
            {"rmssd_ms": hrv_base + delta},
            _ts(f"{day} 06:00"),
        )
        _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": rhr_base - delta}, _ts(f"{day} 07:00"))
        _insert_hr(
            conn,
            "SLEEP_SESSION",
            {},
            _ts(f"2026-08-{d - 1:02d} 23:00"),
            end=_ts(f"{day} {int(sleep_h - 1):02d}:00"),
        )


def test_estable_puntua_en_rango_con_basal(db):
    conn = sqlite3.connect(db)
    _stable_week(conn)
    conn.commit()
    conn.close()
    df = daily_recovery(db).set_index("fecha")
    # Sin basal los 2 primeros días no puntúan (min_periods=3).
    assert len(df) == 6
    assert ((df["valor"] >= 0) & (df["valor"] <= 100)).all()
    # Paridad determinista: días impares (HRV alta + RHR baja) rinden más.
    assert df.loc["2026-08-17", "valor"] > df.loc["2026-08-16", "valor"]
    assert df.loc["2026-08-17", "valor"] == pytest.approx(71.5, abs=1.5)


def test_sueno_solo_no_puntua(db):
    conn = sqlite3.connect(db)
    for d in range(10, 18):
        _insert_hr(
            conn,
            "SLEEP_SESSION",
            {},
            _ts(f"2026-08-{d - 1:02d} 23:00"),
            end=_ts(f"2026-08-{d:02d} 07:00"),
        )
    conn.commit()
    conn.close()
    assert daily_recovery(db).empty


def test_sin_hrv_renormaliza_pesos(db):
    conn = sqlite3.connect(db)
    for i, d in enumerate(range(10, 18)):
        day = f"2026-08-{d:02d}"
        delta = 1.0 if i % 2 else -1.0
        _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": 60.0 - delta}, _ts(f"{day} 07:00"))
        _insert_hr(
            conn, "SLEEP_SESSION", {}, _ts(f"2026-08-{d - 1:02d} 23:00"), end=_ts(f"{day} 07:00")
        )
    conn.commit()
    conn.close()
    df = daily_recovery(db)
    assert len(df) == 6
    # Solo RHR+sueño: (0.25*s_rhr + 0.25*100)/0.5; último día RHR baja → ~79.8.
    assert df.iloc[-1]["valor"] == pytest.approx(79.8, abs=1.5)


def test_pico_hrv_sube_y_carga_previa_penaliza(db):
    conn = sqlite3.connect(db)
    # Tendencias suaves (z estable) + sueño óptimo, sin carga.
    for d in range(10, 20):
        day = f"2026-08-{d:02d}"
        _insert_hr(
            conn,
            "HEART_RATE_VARIABILITY_RMSSD",
            {"rmssd_ms": 50.0 + 0.1 * (d - 10)},
            _ts(f"{day} 06:00"),
        )
        _insert_hr(
            conn,
            "RESTING_HEART_RATE",
            {"bpm": 60.0 - 0.1 * (d - 10)},
            _ts(f"{day} 07:00"),
        )
        _insert_hr(
            conn, "SLEEP_SESSION", {}, _ts(f"2026-08-{d - 1:02d} 23:00"), end=_ts(f"{day} 07:00")
        )
    # 60 min de cardio el día 18 → penaliza solo al 19.
    _insert_hr(
        conn,
        "EXERCISE_SESSION",
        {"exercise_type": 17},
        _ts("2026-08-18 08:00"),
        end=_ts("2026-08-18 09:00"),
    )
    # Día 20: pico de HRV sin carga previa.
    _insert_hr(conn, "HEART_RATE_VARIABILITY_RMSSD", {"rmssd_ms": 90.0}, _ts("2026-08-20 06:00"))
    _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": 59.0}, _ts("2026-08-20 07:00"))
    _insert_hr(conn, "SLEEP_SESSION", {}, _ts("2026-08-19 23:00"), end=_ts("2026-08-20 07:00"))
    conn.commit()
    conn.close()
    df = daily_recovery(db).set_index("fecha")
    assert ((df["valor"] >= 0) & (df["valor"] <= 100)).all()
    diff_carga = df.loc["2026-08-18", "valor"] - df.loc["2026-08-19", "valor"]
    assert diff_carga == pytest.approx(20.0, abs=3.0)  # 60 min → −20 puntos
    assert df.loc["2026-08-20", "valor"] > df.loc["2026-08-19", "valor"]  # el pico domina


def test_vacio_sin_datos(db):
    assert daily_recovery(db).empty
    assert recovery_vs_performance(db).empty


def test_correlacion_recuperacion_rendimiento(db):
    conn = sqlite3.connect(db)
    _stable_week(conn, sleep_h=5.0, days=3)  # 10-12: poco sueño (con varianza)
    for i, d in enumerate(range(13, 20)):
        day = f"2026-08-{d:02d}"
        delta = 1.0 if i % 2 else -1.0
        _insert_hr(
            conn,
            "HEART_RATE_VARIABILITY_RMSSD",
            {"rmssd_ms": 50.0 + delta},
            _ts(f"{day} 06:00"),
        )
        _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": 60.0 - delta}, _ts(f"{day} 07:00"))
        _insert_hr(
            conn, "SLEEP_SESSION", {}, _ts(f"2026-08-{d - 1:02d} 23:00"), end=_ts(f"{day} 07:00")
        )
    conn.execute("INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press')")
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
        "VALUES (1, 'LUNES', '2026-08-12', 1, 'Press', 8, 80, 2),"
        "       (2, 'LUNES', '2026-08-19', 1, 'Press', 8, 100, 2)"
    )
    conn.commit()
    conn.close()
    df = recovery_vs_performance(db)
    assert len(df) == 2
    assert df.iloc[1]["recuperacion"] > df.iloc[0]["recuperacion"]  # 8 h > 5 h
    assert df.iloc[1]["rendimiento"] > df.iloc[0]["rendimiento"]  # 100 kg > 80 kg
    assert float(df[["recuperacion", "rendimiento"]].corr().iloc[0, 1]) > 0.9


def test_config_pesos_personalizados(db):
    conn = sqlite3.connect(db)
    _stable_week(conn)
    conn.commit()
    conn.close()
    cfg = RecoveryConfig(w_hrv=1.0, w_rhr=0.0, w_sleep=0.0)
    df = daily_recovery(db, cfg)
    # Último día: HRV alta → z≈+0.8 → ~59.6.
    assert df.iloc[-1]["valor"] == pytest.approx(59.6, abs=1.5)
