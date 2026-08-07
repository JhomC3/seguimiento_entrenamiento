import os

import pandas as pd
import pytest

from src.charts import (
    chart_pfr_timeline,
    get_exercise_best_rm,
    get_exercise_detail,
    pivot_exercise_table,
)
from src.database import init_db, load_ejercicios, load_training_data

TEST_DB = "data/test_charts.db"


@pytest.fixture
def setup_test_db():
    os.makedirs("data", exist_ok=True)
    init_db(TEST_DB)

    # Load exercises
    df_ej = pd.DataFrame(
        [
            {"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"},
            {"grupo_muscular": "Biceps", "ejercicio": "Curl Bayesian"},
        ]
    )
    load_ejercicios(TEST_DB, df_ej)

    # Load training data (Lunes and Viernes)
    df_ciclo = pd.DataFrame(
        [
            # Semana 1 - Lunes (4/5/26)
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "4/5/26",
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 1.0,
            },
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "4/5/26",
                "set_orden": 2,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 0.0,
            },
            # Semana 1 - Viernes (8/5/26)
            {
                "semana": 1,
                "dia": "VIERNES",
                "fecha": "8/5/26",
                "set_orden": 64,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 1.0,
            },
            # Semana 2 - Lunes (11/5/26)
            {
                "semana": 2,
                "dia": "LUNES",
                "fecha": "11/5/26",
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 5.0,
                "kg": 90.0,
                "rir": 2.0,
            },
        ]
    )
    load_training_data(TEST_DB, df_ciclo)

    yield TEST_DB

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def test_chart_pfr_timeline_crecimiento_base_0(setup_test_db):
    db = setup_test_db
    fig = chart_pfr_timeline(db, "systemic")
    assert fig.data, "la gráfica debe tener datos"
    assert list(fig.layout.xaxis.ticktext) == ["1", "2"]
    assert fig.layout.yaxis.range[0] == 0
    ys = list(fig.data[0].y)
    assert ys[0] == pytest.approx(0, abs=0.5)  # semana 1 = baseline
    assert ys[1] > 0  # semana 2 = crecimiento
    assert "Ciclo 1" in fig.layout.title.text
    assert "Crecimiento" in fig.data[0].hovertemplate


def test_chart_html_header_ciclo_igual_que_semana_panel(setup_test_db):
    from src.dashboard_service import chart_html

    html = chart_html(setup_test_db, "systemic", title="Rendimiento – Empuje")
    assert 'class="text-[11px] text-neutral-500 flex-none">Ciclo 1<' in html
    assert 'neon-title truncate">Rendimiento – Empuje<' in html


def test_get_exercise_detail(setup_test_db):
    db = setup_test_db
    df = get_exercise_detail(db, "Press Convergente")
    assert not df.empty
    assert len(df) == 4
    # Assert RM calculation is correct for 85kg x 6reps: 85 * (1 + 0.0333 * 6) = 101.983 -> 102.0
    assert df.iloc[0]["rm"] == 102.0
    # RIR should be retrieved
    assert df.iloc[0]["rir"] == 1.0
    # Session number: Lunes is 1, Viernes is 2
    assert df.iloc[0]["sesion"] == 1  # Lunes
    assert df.iloc[2]["sesion"] == 2  # Viernes
    assert df.iloc[3]["sesion"] == 1  # Semana 2 - Lunes


def test_get_exercise_best_rm(setup_test_db):
    db = setup_test_db
    df = get_exercise_best_rm(db, "Press Convergente")
    assert not df.empty
    assert len(df) == 3  # 3 unique sessions
    # Best RM of first session is 102.0
    assert df.iloc[0]["mejor_rm"] == 102.0


def test_pivot_exercise_table(setup_test_db):
    db = setup_test_db
    pivot = pivot_exercise_table(db, "Press Convergente")
    assert not pivot.empty
    # Index should contain Sem 1 - S1, Sem 1 - S2, Sem 2 - S1
    assert "Sem 1 - S1" in pivot.index
    assert "Sem 1 - S2" in pivot.index
    assert "Sem 2 - S1" in pivot.index
    # Columns should contain Fecha, Orden, and Series
    assert "Fecha" in pivot.columns
    assert "Orden" in pivot.columns
    assert "Serie 1" in pivot.columns
