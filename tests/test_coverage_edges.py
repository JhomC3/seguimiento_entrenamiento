"""Analytical edge coverage: charts and metrics with explicit tolerances."""

import pandas as pd
import pytest

from src.charts import (
    chart_pfr_timeline,
    get_exercise_raw_data,
    get_exercise_session_summary,
)
from src.database import init_db, insert_exercise, load_ejercicios
from src.metrics_engine import (
    calculate_pfr_timeline,
    get_exercises_baselines,
    is_compound,
)
from src.models import TrainingSetInput
from src.training_service import save_session


@pytest.fixture()
def chart_db(tmp_path):
    db = str(tmp_path / "charts.db")
    init_db(db)
    load_ejercicios(
        db,
        pd.DataFrame(
            [
                {"grupo_muscular": "Pectoral", "ejercicio": "Press"},
                {"grupo_muscular": "Espalda", "ejercicio": "Remo"},
            ]
        ),
    )
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
            TrainingSetInput(ejercicio="Press", kg=82, reps=6, rir=2),
        ],
    )
    save_session(
        db,
        "2026-02-11",
        [
            TrainingSetInput(ejercicio="Remo", kg=60, reps=10, rir=0),
        ],
    )
    return db


def _rm_ajustado(kg, reps, rir=0.0):
    effective_reps = reps + (rir if rir >= 0 else 1 + rir)
    return kg * (1 + 0.0333 * effective_reps)


# ---------------------------------------------------------------------------
# Chart filter modes and titles
# ---------------------------------------------------------------------------


def test_chart_pfr_systemic_has_data_and_continuous_timeline(chart_db):
    fig = chart_pfr_timeline(chart_db, "systemic", title="Rendimiento Global – Todo el Cuerpo")
    assert len(fig.data) == 2  # Global + RIR
    assert [t.name for t in fig.data] == ["Global", "RIR"]
    assert fig.layout.title.text == "Rendimiento Global – Todo el Cuerpo"
    df = calculate_pfr_timeline(chart_db, "systemic")
    assert not df.empty
    assert df["sets_totales"].sum() == 3
    assert "dia_es" in df.columns and "fecha_str" in df.columns


def test_chart_pfr_muscle_group_filters(chart_db):
    df = calculate_pfr_timeline(chart_db, "muscle_group", "Pectoral")
    assert df["sets_totales"].sum() == 2
    fig = chart_pfr_timeline(chart_db, "muscle_group", "Pectoral", "Rendimiento – Pectoral")
    assert fig.layout.title.text == "Rendimiento – Pectoral"
    df_empty = calculate_pfr_timeline(chart_db, "muscle_group", "Core")
    assert df_empty.empty


def test_chart_pfr_exercise_filters(chart_db):
    df = calculate_pfr_timeline(chart_db, "exercise", "Press")
    assert df["sets_totales"].sum() == 2
    fig = chart_pfr_timeline(chart_db, "exercise", "Press", "Rendimiento – Press")
    assert fig.layout.title.text == "Rendimiento – Press"
    assert calculate_pfr_timeline(chart_db, "exercise", "Ghost").empty


def test_chart_pfr_empty_db(tmp_path):
    db = str(tmp_path / "empty.db")
    init_db(db)
    assert calculate_pfr_timeline(db, "systemic").empty
    fig = chart_pfr_timeline(db, "systemic")
    assert not fig.data


def test_chart_pfr_drops_invalid_dates(tmp_path):
    db = str(tmp_path / "bad_dates.db")
    init_db(db)
    load_ejercicios(db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press"}]))
    conn = __import__("src.db_connection", fromlist=["connect_db"]).connect_db(db)
    with conn:
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (1, 'LUNES', 'no-es-fecha', 1, 'Press', 8, 80, 1, 'manual')"
        )
    assert calculate_pfr_timeline(db, "systemic").empty


def test_chart_exercise_rm_and_summary(chart_db):
    summary = get_exercise_session_summary(chart_db, "Press")
    assert len(summary) == 1
    assert summary.iloc[0]["total_sets"] == 2
    assert abs(summary.iloc[0]["total_tonelaje"] - (80 * 8 + 82 * 6)) < 0.01


def test_chart_raw_data_rm_calculation(chart_db):
    df = get_exercise_raw_data(chart_db, "Press")
    assert len(df) == 2
    expected = round(_rm_ajustado(80, 8, 1), 1)
    assert abs(df.iloc[0]["rm_ajustado"] - expected) < 0.05
    assert get_exercise_raw_data(chart_db, "Ghost").empty


# ---------------------------------------------------------------------------
# Metrics edges
# ---------------------------------------------------------------------------


def test_baselines_ignore_null_kg_reps(chart_db):
    conn = __import__("src.db_connection", fromlist=["connect_db"]).connect_db(chart_db)
    with conn:
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (1, 'LUNES', '2026-05-04', 9, 'Press', NULL, NULL, 1, 'manual')"
        )
    baselines = get_exercises_baselines(chart_db)
    expected_press = round((_rm_ajustado(80, 8, 1) + _rm_ajustado(82, 6, 2)) / 2, 1)
    assert abs(baselines["Press"] - expected_press) < 0.05
    assert "Ghost" not in baselines


def test_one_session_baseline(tmp_path):
    db = str(tmp_path / "one.db")
    init_db(db)
    insert_exercise(db, "Curl", "Biceps", "TIRON")
    save_session(db, "2026-02-10", [TrainingSetInput(ejercicio="Curl", kg=20, reps=10, rir=0)])
    baselines = get_exercises_baselines(db)
    assert abs(baselines["Curl"] - round(_rm_ajustado(20, 10, 0), 1)) < 0.05


def test_independent_baselines_per_exercise(chart_db):
    baselines = get_exercises_baselines(chart_db)
    assert set(baselines) == {"Press", "Remo"}
    assert abs(baselines["Remo"] - round(_rm_ajustado(60, 10, 0), 1)) < 0.05
    assert baselines["Press"] != baselines["Remo"]


def test_unknown_exercise_falls_back_to_100_percent(chart_db, monkeypatch):

    monkeypatch.setattr("src.metrics_engine.get_exercises_baselines", lambda db: {})
    df = calculate_pfr_timeline(chart_db, "systemic")
    assert not df.empty
    assert (df["rendimiento"].dropna() == 100.0).all()


def test_zero_rir_handling(tmp_path):
    db = str(tmp_path / "zero.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    save_session(db, "2026-02-10", [TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=0)])
    df = calculate_pfr_timeline(db, "exercise", "Press")
    assert not df.empty
    assert df["rendimiento"].dropna().iloc[0] == pytest.approx(100.0, abs=0.1)


def test_is_compound_classification():
    assert is_compound("Sentadilla") is True
    assert is_compound("press convergente") is True
    assert is_compound("Curl Bayesian") is False
    assert is_compound("crunch") is False
