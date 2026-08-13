import os

import pandas as pd
import pytest

from src.charts import chart_pfr_timeline, get_exercise_raw_data, get_exercise_session_summary
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

    # Load training data (Lunes and Viernes), ISO dates
    df_ciclo = pd.DataFrame(
        [
            # Semana 1 - Lunes (2026-05-04)
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "2026-05-04",
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 1.0,
            },
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "2026-05-04",
                "set_orden": 2,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 0.0,
            },
            # Semana 1 - Viernes (2026-05-08)
            {
                "semana": 1,
                "dia": "VIERNES",
                "fecha": "2026-05-08",
                "set_orden": 64,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 85.0,
                "rir": 1.0,
            },
            # Semana 2 - Lunes (2026-05-11)
            {
                "semana": 2,
                "dia": "LUNES",
                "fecha": "2026-05-11",
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


def test_get_exercise_raw_data(setup_test_db):
    db = setup_test_db
    df = get_exercise_raw_data(db, "Press Convergente")
    assert not df.empty
    assert len(df) == 4
    assert {"semana", "sesion", "serie", "fecha", "kg", "reps", "rir", "rm", "rm_ajustado"} <= set(
        df.columns
    )
    # RM for 85kg x 6reps sin RIR: 85 * (1 + 0.0333 * 6) = 101.983 -> 102.0
    assert df.iloc[0]["rm"] == 102.0
    # RM ajustado para RIR 1.0: 85 * (1 + 0.0333 * (6 + 1 + 1)) = 107.644 -> 107.6
    assert df.iloc[0]["rm_ajustado"] == 107.6
    assert df.iloc[0]["fecha"] == "2026-05-04"


def test_get_exercise_session_summary(setup_test_db):
    db = setup_test_db
    df = get_exercise_session_summary(db, "Press Convergente")
    assert not df.empty
    assert len(df) == 3  # 3 sesiones únicas (Sem1-Lun, Sem1-Vie, Sem2-Lun)
    s1 = df[df["sesion"] == 1].iloc[0]
    assert s1["total_sets"] == 2
    assert s1["total_tonelaje"] == 1020.0  # 2 x 85kg x 6reps
    assert s1["avg_rm_ajustado"] == pytest.approx(106.2, abs=0.1)


def test_chart_pfr_timeline_hover_incluye_resumen(setup_test_db):
    db = setup_test_db
    fig = chart_pfr_timeline(db, "systemic", None, "")
    assert fig.data, "la figura debe tener datos"
    trace = fig.data[0]
    assert trace.customdata is not None
    # customdata por semana: [series, fallos, volumen, peso, sueño]
    assert len(trace.customdata[0]) == 5
    assert trace.customdata[0][0] >= 2  # series de la semana 1
    assert "customdata[1]" in trace.hovertemplate
    assert "Fallos" in trace.hovertemplate


def test_get_exercise_raw_data_incluye_descanso(setup_test_db):
    db = setup_test_db
    df = get_exercise_raw_data(db, "Press Convergente")
    assert "descanso_seg" in df.columns
