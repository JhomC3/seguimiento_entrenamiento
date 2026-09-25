"""Bloques de salud: construcción por bloque/granularidad, gráficas y ruta."""

import json
import sqlite3
from datetime import datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.charts import chart_metrics_index
from src.dashboard_service import chart_shell_html
from src.database import init_db
from src.health_panels import (
    DEFAULT_METRICS,
    METRIC_ORDER,
    build_metrics_catalog,
    build_metrics_index,
    normalize_01_100,
    parse_metrics_param,
)
from src.models import ValidationError
from src.security import get_csrf_secret, make_csrf_token

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
        CREATE TABLE parametros_diarios (
            fecha TEXT PRIMARY KEY, peso_kg REAL NOT NULL DEFAULT 70,
            factor_proteina REAL NOT NULL DEFAULT 1.5,
            factor_grasa REAL NOT NULL DEFAULT 1.1,
            kcal_objetivo REAL NOT NULL DEFAULT 2300
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


def _insert_hr(conn, record_type, value, start, end=None):
    payload = json.dumps({"value": json.loads(value) if isinstance(value, str) else value})
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


def _seed_basics(conn):
    _insert_hr(conn, "STEPS_H1", {"count": 5000}, _ts("2026-08-10 09:00"))
    _insert_hr(conn, "STEPS_H1", {"count": 6000}, _ts("2026-08-11 09:00"))
    _insert_hr(
        conn,
        "EXERCISE_SESSION",
        {"exercise_type": 17},
        _ts("2026-08-10 08:00"),
        end=_ts("2026-08-10 08:30"),
    )
    _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": 60}, _ts("2026-08-10 07:00"))
    _insert_hr(conn, "RESTING_HEART_RATE", {"bpm": 62}, _ts("2026-08-11 07:00"))
    _insert_hr(conn, "SLEEP_SESSION", {}, _ts("2026-08-09 23:00"), end=_ts("2026-08-10 07:00"))


def test_normalize_winsoriza_outliers():
    s = pd.Series([10.0] * 98 + [100000.0, -50000.0])
    n = normalize_01_100(s)
    assert ((n >= 0) & (n <= 100)).all()
    assert n.iloc[98] == 100.0 and n.iloc[99] == 0.0  # outliers a los extremos
    assert (n.iloc[:98] == n.iloc[0]).all()  # el grueso conserva su igualdad


def test_normalize_plana_y_vacia_y_passthrough():
    assert (normalize_01_100(pd.Series([7.0, 7.0, 7.0])) == 50.0).all()
    assert normalize_01_100(pd.Series([], dtype=float)).empty
    assert normalize_01_100(pd.Series([None, float("nan")])).isna().all()
    assert normalize_01_100(pd.Series([-5.0, 64.7, 250.0]), already_01_100=True).tolist() == [
        0.0,
        64.7,
        100.0,
    ]


def test_parse_metrics_param():
    assert parse_metrics_param(None) == DEFAULT_METRICS
    assert parse_metrics_param("zzz") == DEFAULT_METRICS
    assert parse_metrics_param("") == ()
    assert parse_metrics_param("sleep,steps,zzz") == ("sleep", "steps")
    # Orden canónico aunque el query venga desordenado.
    assert parse_metrics_param("steps,sleep") == ("sleep", "steps")
    assert set(DEFAULT_METRICS) <= set(METRIC_ORDER)


def test_build_metrics_index(db):
    conn = sqlite3.connect(db)
    _seed_basics(conn)
    _insert_hr(conn, "WEIGHT", '{"kg": 80.0}', _ts("2026-08-10 07:00"))
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, kcal, carbohidratos, fibra, "
        "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2026-08-10', 1, 'Avena', 350, 60, 10, 12, 6, 1, 1, 1, 1)"
    )
    conn.commit()
    conn.close()
    df = build_metrics_index(db, "day")
    assert list(df["fecha"]) == ["2026-08-10", "2026-08-11"]
    assert df["steps"].tolist() == [5000, 6000]
    assert df["kcal"].iloc[0] == 350
    assert df["weight"].iloc[0] == pytest.approx(80.0)
    week = build_metrics_index(db, "week")
    assert week["steps"].iloc[0] == pytest.approx(5500.0)  # media uniforme
    assert build_metrics_index(db, "month")["periodo"].tolist() == ["2026-08"]
    with pytest.raises(ValidationError):
        build_metrics_index(db, "quincena")


def test_build_metrics_catalog_disabled(db):
    conn = sqlite3.connect(db)
    _insert_hr(conn, "STEPS_H1", '{"count": 100}', _ts("2026-08-10 09:00"))
    conn.commit()
    conn.close()
    catalog = build_metrics_catalog(db, ("steps",))
    by_key = {m["key"]: m for g in catalog for m in g["metrics"]}
    assert by_key["steps"]["pressed"] and not by_key["steps"]["disabled"]
    assert not by_key["hrv"]["pressed"] and by_key["hrv"]["disabled"]
    assert by_key["kcal"]["label"] == "Ingesta"
    assert [g["group"] for g in catalog] == [
        "Recuperación",
        "Actividad",
        "Vitales",
        "Rendimiento",
        "Nutrición",
    ]


def test_chart_metrics_index_trazas():
    df = pd.DataFrame(
        {
            "fecha": ["2026-08-10", "2026-08-11"],
            "steps": [5000.0, 6000.0],
            "rhr": [60.0, 62.0],
        }
    )
    fig = chart_metrics_index(df, "day", ("steps",))
    assert len(fig.data) == 2
    by_meta = {t.meta: t for t in fig.data}
    assert by_meta["steps"].visible is True
    assert by_meta["rhr"].visible is False
    assert all(v <= 100 and v >= 0 for v in by_meta["steps"].y)
    assert len(by_meta["steps"].customdata[0]) == 2
    assert "pasos" in by_meta["steps"].customdata[0][1]
    assert not chart_metrics_index(pd.DataFrame(), "day", ("steps",)).data


def test_shell_metricas_slot():
    html = chart_shell_html(
        "Métricas", chart_metrics_index(pd.DataFrame(), "day", ("steps",)), prefix="nutrition-trend"
    )
    assert 'id="nutrition-trend-data"' in html
    assert 'id="nutrition-trend-plot"' in html
    assert ">Métricas<" in html


def test_index_metricas_seleccion(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gym.db")
    init_db(db_path)
    monkeypatch.setattr(appmod, "DB_PATH", db_path)
    client = TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})
    body = client.get("/").text
    # Una sola gráfica (slot nutricional) + sección Salud en el panel izquierdo.
    assert 'id="nutrition-trend-data"' in body
    assert ">Métricas<" in body
    assert 'id="metrics-catalog"' in body
    assert 'data-metric="hrv"' in body
    assert 'id="dashboard-metrics-row"' not in body
    body = client.get("/", params={"metricas": "sleep,steps"}).text
    assert 'data-metric="sleep"' in body
    # Desconocidas se ignoran (defaults).
    body = client.get("/", params={"metricas": "zzz"}).text
    assert 'aria-pressed="true"' in body


def test_grafica_emite_metricas(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gym.db")
    init_db(db_path)
    monkeypatch.setattr(appmod, "DB_PATH", db_path)
    client = TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})
    body = client.get("/grafica", params={"gran": "day"}).text
    assert 'id="nutrition-trend-data"' in body
    assert 'id="nutrition-trend-empty"' in body
    assert 'id="unified-chart-data"' in body
    assert ">Métricas<" in body
