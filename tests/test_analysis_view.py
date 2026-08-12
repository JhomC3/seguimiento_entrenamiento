"""Analysis view model: KPIs and chart JSON fragment."""

import sqlite3

import pytest

from src.dashboard_service import (
    analysis_chart_html,
    build_analysis_kpis,
    build_analysis_viewmodel,
)
from src.view_models import AnalysisKpis, AnalysisViewModel


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "t.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE ejercicios (id INTEGER PRIMARY KEY, grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE, categoria TEXT, origen TEXT NOT NULL DEFAULT 'google');
        CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER NOT NULL, dia TEXT NOT NULL,
            fecha TEXT, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, reps REAL, kg REAL,
            rir REAL, descanso_seg REAL, origen TEXT NOT NULL DEFAULT 'google');
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
        INSERT INTO ejercicios (grupo_muscular, ejercicio, categoria)
        VALUES ('Pectoral', 'Press', 'Empuje');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (14, 'LUNES', '2026-08-10', 1, 'Press', 8, 80, 2),
               (14, 'LUNES', '2026-08-10', 2, 'Press', 5, 80, 0),
               (14, 'LUNES', '2026-08-10', 3, 'Press', 4.5, 80, -1);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_build_analysis_kpis_calcula_fallo_y_pfr(db):
    kpis = build_analysis_kpis(db, "global", None)
    assert isinstance(kpis, AnalysisKpis)
    assert kpis.pfr_actual is not None
    assert kpis.sets_fallo_semana == 2  # rir=0 y reps decimal
    assert kpis.peso_actual is None  # sin registros WEIGHT
    assert kpis.sueno_anoche is None  # sin registros SLEEP


def test_build_analysis_kpis_peso_y_sueno_desde_health(db):
    conn = sqlite3.connect(db)
    ts = lambda iso: int(__import__("datetime").datetime.fromisoformat(iso).timestamp() * 1000)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('w1', 'WEIGHT', ?, ?, ?, 1, '{\"kg\": 82.4}', 'x', 'x')",
        (ts("2026-08-10 07:00"), ts("2026-08-10 07:00"), ts("2026-08-10 07:00")),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('s1', 'SLEEP_SESSION', ?, ?, ?, 1, '{}', 'x', 'x')",
        (ts("2026-08-09 23:00"), ts("2026-08-10 07:30"), ts("2026-08-10 07:30")),
    )
    conn.commit()
    conn.close()
    kpis = build_analysis_kpis(db, "global", None)
    assert kpis.peso_actual == 82.4
    assert kpis.sueno_anoche == 8.5


def test_build_analysis_viewmodel_serializa_figura(db):
    vm = build_analysis_viewmodel(db, "global", None, ["pfr", "volumen"], rango=4)
    assert isinstance(vm, AnalysisViewModel)
    assert vm.has_data
    assert vm.active_layers == ("pfr", "volumen")
    assert '"yaxis2"' in vm.chart_json  # dos subplots


def test_build_analysis_viewmodel_sin_datos(db):
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM training_sets")
    conn.commit()
    conn.close()
    vm = build_analysis_viewmodel(db, "global", None, ["pfr", "volumen"])
    assert not vm.has_data
    assert vm.chart_json == ""


def test_analysis_chart_html_sin_datos_devuelve_placeholder(db):
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM training_sets")
    conn.commit()
    conn.close()
    vm = build_analysis_viewmodel(db, "global", None, ["pfr"])
    html = analysis_chart_html(vm)
    assert "Sin datos" in html
    assert "application/json" not in html


def test_analysis_chart_html_con_datos_incluye_script_inerte(db):
    vm = build_analysis_viewmodel(db, "global", None, ["pfr"])
    html = analysis_chart_html(vm)
    assert 'id="analysis-chart-data" type="application/json"' in html
    assert 'id="analysis-chart-plot"' in html
