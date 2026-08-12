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
        CREATE TABLE cardio_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hc_id TEXT NOT NULL UNIQUE REFERENCES health_records(hc_id) ON DELETE CASCADE,
            velocidad_kmh REAL, inclinacion_pct REAL, notas TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE parametros_diarios (
            fecha TEXT PRIMARY KEY, peso_kg REAL, factor_proteina REAL,
            factor_grasa REAL, kcal_objetivo REAL, fibra_objetivo REAL,
            hierro_objetivo REAL, calcio_objetivo REAL, vitamina_c_objetivo REAL,
            vitamina_a_objetivo REAL
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
        "VALUES ('w1', 'WEIGHT', ?, ?, ?, 1, '{\"value\": {\"kg\": 82.4}}', 'x', 'x')",
        (ts("2026-08-10 07:00"), ts("2026-08-10 07:00"), ts("2026-08-10 07:00")),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('s1', 'SLEEP_SESSION', ?, ?, ?, 1, '{\"value\": {}}', 'x', 'x')",
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


def test_build_day_detail_entreno_nutricion_recuperacion(db):
    conn = sqlite3.connect(db)
    ts = lambda iso: int(__import__("datetime").datetime.fromisoformat(iso).timestamp() * 1000)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('s1', 'SLEEP_SESSION', ?, ?, ?, 1, '{\"value\": {}}', 'x', 'x')",
        (ts("2026-08-09 23:00"), ts("2026-08-10 07:30"), ts("2026-08-10 07:30")),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('c1', 'EXERCISE_SESSION', ?, ?, ?, 1, '{\"title\": \"Cinta\"}', 'x', 'x')",
        (ts("2026-08-10 08:00"), ts("2026-08-10 08:30"), ts("2026-08-10 08:30")),
    )
    conn.execute(
        "INSERT INTO cardio_annotations (hc_id, velocidad_kmh, inclinacion_pct, notas, created_at, updated_at) "
        "VALUES ('c1', 5.5, 2.0, 'caminata', 'x', 'x')"
    )
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, kcal, carbohidratos, fibra, "
        "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2026-08-10', 1, 'Avena', 350, 60, 10, 12, 6, 1, 1, 1, 1)"
    )
    conn.commit()
    conn.close()

    from src.dashboard_service import build_day_detail

    vm = build_day_detail(db, "2026-08-10", "global", None)
    assert vm.has_entreno
    assert len(vm.sets) == 3
    assert [s.fallo for s in vm.sets] == [False, True, True]
    assert [s.forzada for s in vm.sets] == [False, False, True]
    assert vm.sets[0].descanso_seg is None
    assert vm.sets_fallo == 2
    assert vm.sueno == 8.5
    assert vm.nutrientes["kcal_consumido"] == 350.0
    assert vm.nutrientes["kcal_objetivo"] == 2300.0
    assert len(vm.cardio) == 1
    assert vm.cardio[0].hc_id == "c1"
    assert vm.cardio[0].velocidad_kmh == 5.5
    assert vm.cardio[0].inclinacion_pct == 2.0


def test_build_day_detail_filtra_por_nivel(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO ejercicios (grupo_muscular, ejercicio, categoria) VALUES ('Espalda', 'Remo', 'Tiron')"
    )
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
        "VALUES (14, 'LUNES', '2026-08-10', 1, 'Remo', 8, 70, 2)"
    )
    conn.commit()
    conn.close()

    from src.dashboard_service import build_day_detail

    vm = build_day_detail(db, "2026-08-10", "grupo", "Empuje")
    assert vm.has_entreno
    assert {s.ejercicio for s in vm.sets} == {"Press"}
    vm2 = build_day_detail(db, "2026-08-10", "musculo", "Espalda")
    assert {s.ejercicio for s in vm2.sets} == {"Remo"}


def test_kpis_no_rompen_con_health_records_nulos(db):
    """Regresión real (2026-08-12): los WEIGHT de Samsung llegaban sin `$.kg`
    válido (json_extract NULL) y la home reventaba con TypeError."""
    conn = sqlite3.connect(db)
    ts = lambda iso: int(__import__("datetime").datetime.fromisoformat(iso).timestamp() * 1000)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('w-bad', 'WEIGHT', ?, ?, ?, 1, '{\"value\": {\"kg\": null}}', 'x', 'x')",
        (ts("2026-08-10 07:00"), ts("2026-08-10 07:00"), ts("2026-08-10 07:00")),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('w-ok', 'WEIGHT', ?, ?, ?, 1, '{\"value\": {\"kg\": 82.4}}', 'x', 'x')",
        (ts("2026-08-09 07:00"), ts("2026-08-09 07:00"), ts("2026-08-09 07:00")),
    )
    conn.commit()
    conn.close()
    kpis = build_analysis_kpis(db, "global", None)
    assert kpis.peso_actual == 82.4  # toma el último valor no nulo
    vm = build_analysis_viewmodel(db, "global", None, ["pfr", "peso"])
    assert vm is not None
