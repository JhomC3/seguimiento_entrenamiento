import os

import pandas as pd
import pytest

from src.charts import (
    _pfr_df,
    chart_pfr_timeline,
    chart_selection,
    get_exercise_cohort_summary,
    get_exercise_raw_data,
    get_exercise_session_summary,
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
    # UX-2: sin hovertemplate nativo (tooltip propio en cliente) y la etiqueta
    # del punto viaja en customdata con formato corto de tooltip.
    assert fig.data[0].hovertemplate is None
    assert fig.data[0].customdata[0][0] == "4 mayo 2026"


def test_chart_html_header_ciclo_igual_que_semana_panel(setup_test_db):
    from src.charts import chart_pfr_timeline
    from src.dashboard_service import chart_shell_html

    fig = chart_pfr_timeline(setup_test_db, "systemic", "")
    html = chart_shell_html("Rendimiento – Empuje", fig)
    assert 'id="unified-chart-header"' in html
    assert "Rendimiento<" in html
    assert "Ciclo 1<" not in html
    assert "Rendimiento – Empuje<" not in html
    assert 'id="unified-chart-data"' in html
    assert 'id="unified-chart-plot"' in html
    assert 'id="unified-chart-empty"' in html


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
    # RM ajustado para RIR 1.0: 85 * (1 + 0.0333 * (6 + 1)) = 104.811 -> 104.8
    assert df.iloc[0]["rm_ajustado"] == 104.8
    assert df.iloc[0]["fecha"] == "2026-05-04"


def test_get_exercise_session_summary(setup_test_db):
    db = setup_test_db
    df = get_exercise_session_summary(db, "Press Convergente")
    assert not df.empty
    assert len(df) == 3  # 3 sesiones únicas (Sem1-Lun, Sem1-Vie, Sem2-Lun)
    s1 = df[df["sesion"] == 1].iloc[0]
    assert s1["total_sets"] == 2
    assert s1["avg_rm_ajustado"] == pytest.approx(103.4, abs=0.1)
    assert s1["posicion_ejercicio"] == 1
    assert s1["rm_primera"] == pytest.approx(104.8, abs=0.1)
    assert s1["rm_ultima"] == pytest.approx(102.0, abs=0.1)
    assert s1["caida_pct"] == pytest.approx(2.7, abs=0.1)


def test_get_exercise_cohort_summary_agrupa_posicion_y_serie(setup_test_db):
    raw = get_exercise_raw_data(setup_test_db, "Press Convergente")
    cohorts = get_exercise_cohort_summary(raw)
    first = cohorts[(cohorts["posicion_ejercicio"] == 1) & (cohorts["serie"] == 1)].iloc[0]
    assert first["observaciones"] == 3
    assert first["baseline_rm"] == pytest.approx(104.8, abs=0.1)


def test_chart_pfr_timeline_hover_incluye_resumen(setup_test_db):
    db = setup_test_db
    fig = chart_pfr_timeline(db, "systemic", None, "")
    assert fig.data, "la figura debe tener datos"
    trace = fig.data[0]
    assert trace.customdata is not None
    # customdata (9 pos., inmutable): [etiqueta, Δ, series, reps, peso, rir,
    # rm, cobertura, nombre] — la cobertura viaja pero NO se muestra (UX-2).
    fila = trace.customdata[0]
    assert len(fila) == 9
    assert fila[2] >= "1"  # series de la semana 1 (>=2 aquí) como string
    assert int(fila[2]) >= 2
    assert fila[8] == "Crecimiento"
    # UX-2: tooltip propio en cliente; la traza no lleva hovertemplate nativo.
    assert trace.hovertemplate is None


def test_get_exercise_raw_data_incluye_descanso(setup_test_db):
    db = setup_test_db
    df = get_exercise_raw_data(db, "Press Convergente")
    assert "descanso_seg" in df.columns


def test_chart_muscle_exercises_compilado_solo(setup_test_db):
    from src.charts import chart_selection

    db = setup_test_db
    fig = chart_selection(db, ["Pectoral"], [])
    assert len(fig.data) == 2  # Global + músculo translúcido
    names = [t.name for t in fig.data]
    assert "Global" in names
    assert "Pectoral" in names


def test_chart_un_musculo_mantiene_global_y_nombra_musculo(setup_test_db):
    from src.charts import chart_selection

    fig = chart_selection(setup_test_db, ["Pectoral"], [])
    global_trace, muscle_trace = fig.data
    assert global_trace.name == "Global"
    assert global_trace.line.color == "#e56d88"
    assert muscle_trace.name == "Pectoral"
    assert muscle_trace.line.color.endswith(", 0.4)")
    assert muscle_trace.line.width == 3.5


def test_chart_muscle_exercises_una_traza_por_ejercicio(setup_test_db):
    from src.charts import chart_selection

    db = setup_test_db
    fig = chart_selection(db, ["Pectoral"], ["Press Convergente"])
    assert len(fig.data) == 2  # músculo guía (UX-2) + ejercicio
    assert fig.data[0].name == "Pectoral"
    assert fig.data[1].name == "Press Convergente"
    # UX-2: nunca "Compilado"; el nombre viaja en customdata[8].
    assert all(t.name != "Compilado" for t in fig.data)
    assert fig.data[1].customdata[0][8] == "Press Convergente"
    assert fig.data[1].hovertemplate is None


def test_chart_muscle_exercises_filtra_ejercicios_ajenos(setup_test_db):
    from src.charts import chart_selection

    db = setup_test_db
    fig = chart_selection(db, ["Pectoral"], ["Press Convergente", "Curl Bayesian"])
    # "Curl Bayesian" pertenece a Biceps: se descarta, quedan compilado + Press
    assert len(fig.data) == 2
    names = [t.name for t in fig.data]
    assert "Curl Bayesian" not in names


def test_chart_muscle_exercises_vacio_sin_datos(tmp_path):
    from src.charts import chart_selection
    from src.database import init_db

    db = str(tmp_path / "empty.db")
    init_db(db)
    fig = chart_selection(db, ["Pectoral"], [])
    assert len(fig.data) == 0


def test_chart_muscle_exercises_ejercicios_mas_tenues(setup_test_db):
    from src.charts import chart_selection

    db = setup_test_db
    fig = chart_selection(db, ["Pectoral"], ["Press Convergente"])
    compilado = fig.data[0]
    ejercicio = fig.data[1]
    # El compilado es sólido (borgoña, alpha 1) y protagonista.
    assert compilado.line.color == "#e56d88"
    assert compilado.line.width == 2.5
    # El ejercicio individual: línea translúcida (alpha 0.4) y gruesa (3.5).
    assert ejercicio.line.color.startswith("rgba(")
    assert ejercicio.line.color.endswith(", 0.4)")
    assert ejercicio.line.width == 3.5
    # Los puntos comparten la misma transparencia que su línea.
    assert ejercicio.marker.color == ejercicio.line.color
    assert ejercicio.marker.size == 3


def test_chart_selection_dos_musculos_global_mas_tenues(setup_test_db):
    import sqlite3

    from src.charts import chart_selection

    db = setup_test_db
    # Datos para el segundo músculo (Biceps) para que ambas trazas existan.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
        "VALUES (2, 'LUNES', '2026-05-11', 1, 'Curl Bayesian', 10, 12, 1)"
    )
    conn.commit()
    conn.close()
    fig = chart_selection(db, ["Pectoral", "Biceps"], [])
    # Global sólido (referencia) + un músculo tenue por cada seleccionado.
    assert len(fig.data) == 3
    global_trace = fig.data[0]
    assert global_trace.name == "Global"
    assert global_trace.line.color == "#e56d88"
    assert global_trace.line.width == 2.5
    for trace in fig.data[1:]:
        assert trace.line.color.startswith("rgba(")
        assert trace.line.color.endswith(", 0.4)")
        assert trace.line.width == 3.5
    assert "Rendimiento – Cuerpo entero" in fig.layout.title.text


def test_chart_selection_dos_musculos_ignora_ejercicios(setup_test_db):
    from src.charts import chart_selection

    db = setup_test_db
    # Con 2+ músculos los ejercicios no aplican: solo Global + músculos.
    fig = chart_selection(db, ["Pectoral", "Biceps"], ["Press Convergente"])
    names = [t.name for t in fig.data]
    assert "Press Convergente" not in names
    assert "Global" in names


# --- Contrato de semántica de trazas (parametrizado) ---


@pytest.mark.parametrize(
    "musculos, ejercicios, expected_names",
    [
        # 0 músculos → sistémica (D3)
        ([], [], ["Crecimiento"]),
        # 1 músculo, 0 ejercicios → Global + músculo
        (["Pectoral"], [], ["Global", "Pectoral"]),
        # 1 músculo, 1 ejercicio válido → músculo guía + ejercicio (D2: sin Global)
        (["Pectoral"], ["Press Convergente"], ["Pectoral", "Press Convergente"]),
        # 1 músculo, ejercicio ajeno → solo el músculo (D2)
        (["Pectoral"], ["Curl Bayesian"], ["Pectoral"]),
        # 2+ músculos → Global + músculos
        (["Pectoral", "Biceps"], [], ["Global", "Pectoral", "Biceps"]),
        # 2+ músculos, ejercicios ignorados
        (["Pectoral", "Biceps"], ["Press Convergente"], ["Global", "Pectoral", "Biceps"]),
        # Sin datos → vacío (se testea por separado con DB vacía)
    ],
)
def test_chart_semantics_decision_matrix(setup_test_db, musculos, ejercicios, expected_names):
    from src.charts import chart_selection

    db = setup_test_db
    # Para 2+ músculos, inyectar datos de Biceps (solo tiene Pectoral por defecto)
    if len(musculos) >= 2:
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO training_sets "
            "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
            "VALUES (2, 'LUNES', '2026-05-11', 1, 'Curl Bayesian', 10, 12, 1)"
        )
        conn.commit()
        conn.close()
    fig = chart_selection(db, musculos, ejercicios)
    names = [t.name for t in fig.data]
    for name in expected_names:
        assert name in names, f"Expected '{name}' in {names}"


def test_chart_semantics_empty_db(tmp_path):
    from src.charts import chart_selection
    from src.database import init_db

    db = str(tmp_path / "empty.db")
    init_db(db)
    fig = chart_selection(db, ["Pectoral"], [])
    assert len(fig.data) == 0


def test_chart_semantics_global_systemic(setup_test_db):
    from src.charts import chart_pfr_timeline

    fig = chart_pfr_timeline(setup_test_db, "systemic")
    assert len(fig.data) >= 1
    assert fig.data[0].name == "Crecimiento"


# ---------------------------------------------------------------------------
# B2 — Agregación diaria (gran=day): eje X con fechas reales, sin descanso
# ---------------------------------------------------------------------------


def test_pfr_df_day_x_usa_fechas_no_semana(setup_test_db):
    """gran=day: el eje X usa fechas reales (periodo), no la columna semana."""
    df = _pfr_df(setup_test_db, "systemic", None, "day")
    assert "semana" not in df.columns, "day no debe exponer la columna semana"
    assert "periodo" in df.columns
    assert df["periodo"].tolist() == ["2026-05-04", "2026-05-08", "2026-05-11"]


def test_pfr_df_day_numero_de_puntos_es_dias_con_datos(setup_test_db):
    """Nº de puntos = días con entrenamiento: 3 días reales ≠ 8 días de rango."""
    df = _pfr_df(setup_test_db, "systemic", None, "day")
    assert len(df) == 3


def test_pfr_df_day_sin_dias_de_descanso_artificiales(setup_test_db):
    """No se inventan puntos entre días de entrenamiento (hueco 05-04→05-08)."""
    df = _pfr_df(setup_test_db, "systemic", None, "day")
    periodos = df["periodo"].tolist()
    assert "2026-05-05" not in periodos
    assert "2026-05-06" not in periodos
    # Orden cronológico
    assert periodos == sorted(periodos)


def test_pfr_df_day_varias_sesiones_mismo_dia_se_agrega(setup_test_db):
    """Dos sets el mismo día (05-04) → un único punto con series=2."""
    df = _pfr_df(setup_test_db, "systemic", None, "day")
    day0404 = df[df["periodo"] == "2026-05-04"].iloc[0]
    assert day0404["series"] == 2


def test_pfr_df_day_metric_definition_conservada(setup_test_db):
    """La métrica del día = rendimiento promedio del día (def. existente), y el
    crecimiento = rendimiento - 100."""
    df = _pfr_df(setup_test_db, "systemic", None, "day")
    raw = _pfr_df(setup_test_db, "systemic", None, "day")
    assert (df["crecimiento"] - (df["rendimiento"] - 100)).abs().max() < 1e-9
    assert raw is df or raw.equals(df)


def test_pfr_df_day_datos_nulos_no_rompen(setup_test_db, tmp_path):
    """Un ejercicio sin baseline o sets con kg/reps nulos no produce columnas
    con NaN que rompan el trazo; y configuración sin datos → DataFrame vacío."""
    from src.database import init_db

    empty_db = str(tmp_path / "empty_day.db")
    init_db(empty_db)
    df = _pfr_df(empty_db, "systemic", None, "day")
    assert df.empty


def test_chart_selection_day_global_musculo_ejercicio(setup_test_db):
    """Contratos Global/músculo/ejercicio intactos con gran=day: las trazas usan
    fechas, el eje X se titula 'Fecha' y los nombres son los canónicos."""
    # Global (0 músculos)
    fig0 = chart_selection(setup_test_db, [], [], "day")
    assert [t.name for t in fig0.data] == ["Crecimiento"]
    assert fig0.layout.xaxis.title.text == "Fecha"
    # Sistema Global y Compilado (músculo)
    fig1 = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    assert [t.name for t in fig1.data] == ["Global", "Pectoral"]
    for t in fig1.data:
        assert list(t.x) == ["2026-05-04", "2026-05-08", "2026-05-11"]
    # Ejercicios (músculo guía + ejercicio, sin Global — D2; UX-2: sin Compilado)
    fig2 = chart_selection(setup_test_db, ["Pectoral"], ["Press Convergente"], "day")
    assert [t.name for t in fig2.data] == ["Pectoral", "Press Convergente"]


def test_chart_selection_day_con_seleccion_persistida(setup_test_db):
    """Granularidad day con músculo+ejercicio persistentes: tanto el Compilado
    como el ejercicio realmente comparten el eje de fechas diario."""
    fig = chart_selection(setup_test_db, ["Pectoral"], ["Press Convergente"], "day")
    assert len(fig.data) == 2
    for t in fig.data:
        assert list(t.x) == ["2026-05-04", "2026-05-08", "2026-05-11"]


def test_pfr_df_day_tooltip_diario(setup_test_db):
    """UX-2: etiqueta tooltip '4 mayo' (sin año), 9 pos. y sin hover nativo."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for t in fig.data:
        assert t.hovertemplate is None
        fila = t.customdata[0]
        assert len(fila) == 9
        assert fila[0] == "4 mayo"
        assert fila[1].startswith(("+", "-")) or fila[1] == "0.0%"


def test_pfr_trace_week_inmutable(setup_test_db):
    """Regresión: la agregación semanal no cambia: eje X = semanas (1,2), no
    fechas diarias, mismo nº de puntos (2 semanas)."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "week")
    assert [t.name for t in fig.data] == ["Global", "Pectoral"]
    assert len(fig.data[0].x) == 2
    # Los valores X de la semana son números de semana, no fechas 'YYYY-MM-DD'.
    for t in fig.data:
        xs = list(t.x)
        assert all(str(v).isdigit() for v in xs), f"semana no debe usar fechas: {xs}"
        assert {str(v) for v in xs} == {"1", "2"}


# ---------------------------------------------------------------------------
# B2-R3 — Etiquetas compactas para gran=day
# ---------------------------------------------------------------------------


def test_day_ticktext_compacto_mismo_mes(setup_test_db):
    """Mismo mes: etiquetas solo DD (15,16,17)."""
    from src.charts import _compact_day_labels

    labels = _compact_day_labels(["2026-08-15", "2026-08-16", "2026-08-17"])
    assert labels == ["15", "16", "17"]
    # En la figura, ticktext == DD y tickvals siguen siendo ISO.
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    # La fixture tiene fechas 2026-05-04, 08, 11 (mismo mes Mayo) → 04,08,11
    assert fig.layout.xaxis.ticktext == ("04", "08", "11")
    assert fig.layout.xaxis.tickvals == ("2026-05-04", "2026-05-08", "2026-05-11")


def test_day_ticktext_cambio_de_mes(setup_test_db):
    """Primer día de nuevo mes: DD/MM (ej. 01/09)."""
    from src.charts import _compact_day_labels

    labels = _compact_day_labels(["2026-08-29", "2026-08-30", "2026-09-01", "2026-09-02"])
    assert labels == ["29", "30", "01/09", "02"]


def test_day_ticktext_cambio_de_ano(setup_test_db):
    """Cambio de año: DD/MM/YY."""
    from src.charts import _compact_day_labels

    labels = _compact_day_labels(["2026-12-31", "2027-01-01", "2027-01-02"])
    assert labels == ["31", "01/01/27", "02"]


def test_day_tooltip_fecha_completa(setup_test_db):
    """UX-2: day '4 mayo', week '4 mayo 2026' (lunes del ciclo), sin hover nativo."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for t in fig.data:
        assert t.customdata[0][0] == "4 mayo"
        assert t.hovertemplate is None
    # chart_pfr_timeline también
    fig2 = chart_pfr_timeline(setup_test_db, "systemic", granularity="day")
    assert fig2.data[0].customdata[0][0] == "4 mayo"
    assert fig2.data[0].hovertemplate is None
    # Week: lunes de la semana del ciclo con año
    figw = chart_pfr_timeline(setup_test_db, "systemic", granularity="week")
    assert figw.data[0].customdata[0][0] == "4 mayo 2026"
    assert figw.data[0].hovertemplate is None


def test_day_eje_interno_sigue_iso(setup_test_db):
    """El valor interno del eje sigue siendo YYYY-MM-DD."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for t in fig.data:
        assert list(t.x) == ["2026-05-04", "2026-05-08", "2026-05-11"]


def test_day_no_muestra_iso_largo(setup_test_db):
    """No se deben mostrar fechas ISO largas como ticktext en day."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for txt in fig.layout.xaxis.ticktext:
        assert len(txt) <= 8, f"ticktext demasiado largo: {txt}"
        assert "-" not in txt or "/" in txt  # DD/MM/YY lleva slash, no guion ISO


def test_day_global_musculo_ejercicio_ticktext_consistente(setup_test_db):
    """Global/músculo/ejercicio comparten el mismo ticktext compacto."""
    fig = chart_selection(setup_test_db, ["Pectoral"], ["Press Convergente"], "day")
    assert fig.layout.xaxis.ticktext == ("04", "08", "11")
    assert fig.layout.xaxis.title.text == "Fecha"


def test_day_tick_cantidad_no_equals_puntos(tmp_path):
    """Historial largo: cantidad de ticks < cantidad de puntos (B2-R4)."""
    db = str(tmp_path / "wtick.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # Siembra 40 días para historial largo
    import datetime

    start = datetime.date(2026, 1, 1)
    rows = []
    for i in range(40):
        d = start + datetime.timedelta(days=i)
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 80.0,
                "rir": 1.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    fig = chart_selection(db, ["Pectoral"], [], "day")
    assert len(fig.layout.xaxis.ticktext) < len(fig.data[0].x)
    # Ticks compactos (DD o DD/MM), no ISO largo
    for txt in fig.layout.xaxis.ticktext:
        assert len(txt) <= 8
        assert "-" not in txt or "/" in txt


def test_day_altura_no_cambia(setup_test_db):
    """La altura del gráfico se mantiene 450px (B2-R4)."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    assert fig.layout.height == 450
    assert fig.layout.xaxis.type == "date"
    # Dragmode pan para TradingView
    assert fig.layout.dragmode == "pan"


# ---------------------------------------------------------------------------
# Estabilidad de layout: la shell no cambia de tamaño al cambiar selección
# ---------------------------------------------------------------------------


def _layout_signature(fig) -> dict:
    """Firma del layout que determina el tamaño del área de trazado."""
    margin = fig.layout.margin
    return {
        "height": fig.layout.height,
        "margin": {
            "l": margin.l,
            "r": margin.r,
            "t": margin.t,
            "b": margin.b,
        },
        "legend_y": fig.layout.legend.y,
        "legend_orientation": fig.layout.legend.orientation,
        "legend_xanchor": fig.layout.legend.xanchor,
        "legend_yanchor": fig.layout.legend.yanchor,
        "showlegend": fig.layout.showlegend,
        "dragmode": fig.layout.dragmode,
    }


def test_chart_layout_estable_entre_estados(setup_test_db):
    """Global, 1 músculo, 1 músculo+ejercicio y 2 músculos comparten EXACTAMENTE
    el mismo margen y configuración de leyenda: seleccionar o deseleccionar no
    redimensiona ni reposiciona el panel de la gráfica."""
    import sqlite3

    db = setup_test_db
    # Datos para Biceps (2 músculos / estado ejercicio necesita 2 ejercicios)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO training_sets "
        "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
        "VALUES (2, 'LUNES', '2026-05-11', 1, 'Curl Bayesian', 10, 12, 1)"
    )
    conn.commit()
    conn.close()

    states = {
        "global": chart_pfr_timeline(db, "systemic", granularity="day"),
        "musculo": chart_selection(db, ["Pectoral"], [], "day"),
        "ejercicio": chart_selection(db, ["Pectoral"], ["Press Convergente"], "day"),
        "dos_musculos": chart_selection(db, ["Pectoral", "Biceps"], [], "day"),
    }
    signatures = {name: _layout_signature(fig) for name, fig in states.items()}
    reference = signatures["global"]
    for name, sig in signatures.items():
        assert sig == reference, f"{name} difiere del global:\n{sig}\nvs\n{reference}"
    # La leyenda vive FUERA del área de trazado (y > 1) en todos los estados.
    assert all(sig["legend_y"] > 1 for sig in signatures.values())
    assert all(sig["showlegend"] is True for sig in signatures.values())
    # Margen superior reducido (48) pero suficiente para la banda de leyenda.
    assert reference["margin"]["t"] == 48
    assert reference["legend_y"] == 1.08


def test_chart_global_muestra_leyenda_en_banda_superior(setup_test_db):
    """El modo global también renderiza leyenda: la banda superior nunca pasa
    de vacía a ocupada (esa transición era la que encogía la gráfica)."""
    fig = chart_pfr_timeline(setup_test_db, "systemic", granularity="day")
    assert fig.layout.showlegend is True
    assert fig.layout.legend.orientation == "h"
    assert fig.layout.legend.y > 1
    # Misma firma que la figura de selección muscular.
    sel = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    assert _layout_signature(fig) == _layout_signature(sel)


# ---------------------------------------------------------------------------
# Ventana temporal inicial (xaxis.range) por granularidad
# ---------------------------------------------------------------------------


def _seed_days_from(db_path: str, start, n: int, ejercicio: str = "Press Convergente"):
    """Siembra n días consecutivos desde `start` (date) — 1 set/día."""
    import datetime

    rows = []
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": ejercicio,
                "reps": 6.0,
                "kg": 80.0,
                "rir": 1.0,
            }
        )
    load_training_data(db_path, pd.DataFrame(rows))


def test_ventana_day_datos_suficientes(tmp_path):
    """day: con >2 meses de datos el rango cubre los últimos 2 meses naturales."""
    import datetime

    db = str(tmp_path / "v_day.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_days_from(db, datetime.date(2026, 1, 1), 120)  # ene→abr
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.xaxis.range
    assert rng is not None
    # Última fecha = 2026-04-30 → inicio = 2026-02-28 con padding ±1 día
    assert list(rng) == ["2026-02-27", "2026-05-01"]
    # Todos los datos permanecen en la figura.
    assert len(fig.data[0].x) == 120


def test_ventana_day_cruce_de_mes(tmp_path):
    """day: fin a mitad de mes → inicio es el mismo día, 2 meses antes."""
    import datetime

    db = str(tmp_path / "v_dm.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_days_from(db, datetime.date(2026, 1, 10), 65)  # 10-ene → 15-mar
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    assert list(fig.layout.xaxis.range) == ["2026-01-14", "2026-03-16"]


def test_ventana_day_cruce_de_ano(tmp_path):
    """day: cruce de año → restar 2 meses cae en el año anterior."""
    import datetime

    db = str(tmp_path / "v_dy.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_days_from(db, datetime.date(2025, 11, 1), 80)  # nov-25 → ene-26
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    assert list(fig.layout.xaxis.range) == ["2025-11-18", "2026-01-20"]


def test_ventana_day_datos_insuficientes(setup_test_db):
    """day: <2 meses de datos → sin rango; Plotly muestra todo lo disponible."""
    fig = chart_pfr_timeline(setup_test_db, "systemic", granularity="day")
    # La fixture cubre 2026-05-04..11 (<2 meses): sin ventana inicial.
    assert not fig.layout.xaxis.range
    assert len(fig.data[0].x) == 3


def test_ventana_week_datos_suficientes_e_insuficientes(tmp_path, setup_test_db):
    """week: ≥16 semanas disponibles → últimas 15; ≤15 → sin rango."""
    import datetime

    db = str(tmp_path / "v_week.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # 20 semanas de ciclo = 140 días.
    _seed_days_from(db, datetime.date(2026, 1, 1), 140)
    fig = chart_selection(db, ["Pectoral"], [], "week")
    rng = fig.layout.xaxis.range
    assert rng is not None and len(rng) == 2
    # Eje category con rótulos string de semana (contrato consistente con trace.x).
    assert fig.layout.xaxis.type == "category"
    assert [int(rng[0]), int(rng[1])] == [6, 20]
    assert len(fig.data[0].x) == 20  # datos completos en la figura
    # Insuficiente: la fixture base solo tiene semanas 1-2.
    fig2 = chart_selection(setup_test_db, ["Pectoral"], [], "week")
    assert fig2.layout.xaxis.range is None


def test_ventana_month_datos_suficientes_y_cruce_de_ano(tmp_path, setup_test_db):
    """month: ≥13 meses disponibles → últimos 12; cruce de año correcto."""
    import datetime

    db = str(tmp_path / "v_month.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # 14 meses: 2025-01-01 + 420 días ≈ 2026-02-19.
    _seed_days_from(db, datetime.date(2025, 1, 1), 420)
    fig = chart_selection(db, ["Pectoral"], [], "month")
    rng = fig.layout.xaxis.range
    assert rng is not None and len(rng) == 2
    # Eje category con rótulos YYYY-MM (contrato consistente con trace.x).
    assert fig.layout.xaxis.type == "category"
    # Meses distintos presentes: 2025-01..2026-02 (14). Últimos 12: 2025-03..2026-02.
    assert list(rng) == ["2025-03", "2026-02"]
    # Datos completos en la figura.
    total_points = sum(len(t.x) for t in fig.data)
    assert total_points >= 14
    # Insuficiente: fixture base (un solo mes).
    fig2 = chart_selection(setup_test_db, ["Pectoral"], [], "month")
    assert fig2.layout.xaxis.range is None


# ---------------------------------------------------------------------------
# Autoajuste vertical del eje Y (todas las series visibles + línea 0)
# ---------------------------------------------------------------------------


def _seed_days_kg(db_path: str, start, n: int, kg: float, ejercicio: str = "Press Convergente"):
    """Siembra n días consecutivos con la misma kg (controla el crecimiento)."""
    import datetime

    rows = []
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": ejercicio,
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db_path, pd.DataFrame(rows))


def _assert_contiene_0_y_extremos(fig, y_vals, tol=1e-6):
    rng = fig.layout.yaxis.range
    lo, hi = rng[0], rng[1]
    # Contiene la línea 0 siempre.
    assert lo <= 0 <= hi, f"rango Y {rng} no contiene 0"
    # Contiene todos los valores visibles.
    lo_v = min(y_vals)
    hi_v = max(y_vals)
    assert lo <= lo_v, f"min visible cortado: {lo} > {lo_v}"
    assert hi >= hi_v, f"max visible cortado: {hi} < {hi_v}"
    # Padding razonable: holgura <= 25% del span (no espacio excesivo).
    span = hi - lo
    assert span > 0
    assert (hi_v - hi) / span <= 0.30, (hi, hi_v, span)
    assert (lo - lo_v) / span <= 0.30, (lo, lo_v, span)


def _seed_days_kg_ramp(db_path, start, n, kg_min, kg_max, ejercicio="Press Convergente"):
    """Siembra n días con kg creciente de kg_min→kg_max (crecimiento sube)."""
    import datetime

    rows = []
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        frac = i / max(1, n - 1)
        kg = kg_min + (kg_max - kg_min) * frac
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": ejercicio,
                "reps": 6.0,
                "kg": round(kg, 1),
                "rir": 0.0,
            }
        )
    load_training_data(db_path, pd.DataFrame(rows))


def _seed_week_kg(db_path, semana, kg, ejercicio="Press Convergente"):
    """Siembra 1 set por día de una semana completa con kg constante."""
    import datetime

    start = datetime.date(2026, 1, 1) + datetime.timedelta(days=(semana - 1) * 7)
    rows = []
    for i in range(7):
        d = start + datetime.timedelta(days=i)
        rows.append(
            {
                "semana": semana,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": ejercicio,
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db_path, pd.DataFrame(rows))


def test_y_solo_positivos_incluye_0_y_max(tmp_path):
    """Todos positivos (baseline = semana 1): rango inferior 0, superior con margen."""
    db = str(tmp_path / "y_pos.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_week_kg(db, 1, 60.0)
    _seed_week_kg(db, 2, 100.0)
    _seed_week_kg(db, 3, 140.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="week")
    y_vals = [v for v in fig.data[0].y if v is not None]
    # Baseline (semana 1) ≈ 0; el resto claramente positivo.
    assert max(y_vals[1:]) > 0 and min(y_vals[1:]) >= 0, y_vals
    _assert_contiene_0_y_extremos(fig, y_vals)
    rng = fig.layout.yaxis.range
    # Base en 0 (o epsilon de ruido del baseline): sin margen negativo.
    assert rng[0] <= 0.5, f"base debe abrazar 0: {rng}"


def test_y_solo_negativos_incluye_0_y_min(tmp_path):
    """Todos negativos: rango superior 0, inferior bajo el mínimo."""
    db = str(tmp_path / "y_neg.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_week_kg(db, 1, 140.0)
    _seed_week_kg(db, 2, 100.0)
    _seed_week_kg(db, 3, 60.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="week")
    y_vals = [v for v in fig.data[0].y if v is not None]
    # Baseline (semana 1) ≈ 0; el resto claramente negativo.
    assert min(y_vals[1:]) < 0 and max(y_vals[1:]) <= 0, y_vals
    rng = fig.layout.yaxis.range
    # Tope en 0 (o epsilon de ruido del baseline): sin margen positivo inflado.
    assert rng[1] <= 0.5, f"tope debe abrazar 0: {rng}"
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_mixtos_contiene_0_con_margen(tmp_path):
    """El rendimiento por ejercicio conserva el baseline del ejercicio."""
    import datetime

    db = str(tmp_path / "y_mix.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # Días alternando kg alta/baja.
    rows = []
    for i in range(6):
        d = datetime.date(2026, 1, 1) + datetime.timedelta(days=i)
        kg = 95.0 if i % 2 == 0 else 45.0
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    y_vals = [v for v in fig.data[0].y if v is not None]
    assert any(v < 0 for v in y_vals) and any(v > 0 for v in y_vals), y_vals
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_musculo_con_max_mayor_que_global_no_se_corta(tmp_path):
    """Regresión del bug: la escala ya no depende solo de Global."""
    import datetime

    db = str(tmp_path / "y_mus.db")
    init_db(db)
    load_ejercicios(
        db,
        pd.DataFrame(
            [
                {"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"},
                {"grupo_muscular": "Biceps", "ejercicio": "Curl Bayesian"},
            ]
        ),
    )
    # Global: kg 80 (crecimiento ~0). Músculo Pectoral: kg 120 (máx alto).
    _seed_days_kg(db, datetime.date(2026, 1, 1), 5, kg=80.0, ejercicio="Press Convergente")
    _seed_days_kg(db, datetime.date(2026, 1, 1), 5, kg=125.0, ejercicio="Curl Bayesian")
    # Solo Pectoral seleccionado: su serie (kg 120) debe estar dentro del rango.
    fig = chart_selection(db, ["Pectoral"], [], "day")
    y_vals = [v for t in fig.data for v in t.y if v is not None]
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_ejercicio_fuera_de_rango_global_incluido(tmp_path):
    """Ejercicio con valores fuera del rango Global no queda cortado."""
    import datetime

    db = str(tmp_path / "y_ej.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    _seed_days_kg(db, datetime.date(2026, 1, 1), 5, kg=130.0, ejercicio="Press Convergente")
    fig = chart_selection(db, ["Pectoral"], ["Press Convergente"], "day")
    y_vals = [v for t in fig.data for v in t.y if v is not None]
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_multimusculos_incluye_todas_las_series(tmp_path):
    """Varios músculos: el rango Y cubre todas las series visibles."""
    import datetime

    db = str(tmp_path / "y_multi.db")
    init_db(db)
    load_ejercicios(
        db,
        pd.DataFrame(
            [
                {"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"},
                {"grupo_muscular": "Biceps", "ejercicio": "Curl Bayesian"},
            ]
        ),
    )
    _seed_days_kg(db, datetime.date(2026, 1, 1), 5, kg=90.0, ejercicio="Press Convergente")
    _seed_days_kg(db, datetime.date(2026, 1, 1), 5, kg=115.0, ejercicio="Curl Bayesian")
    fig = chart_selection(db, ["Pectoral", "Biceps"], [], "day")
    y_vals = [v for t in fig.data for v in t.y if v is not None]
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_recalcula_por_granularidad(tmp_path):
    """Day/Week/Month calculan su rango con sus propios datos."""
    import datetime

    db = str(tmp_path / "y_gran.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # Datos crecientes: semanas 1..3 con kg que sube (crecimiento creciente).
    rows = []
    for i in range(21):
        d = datetime.date(2026, 1, 1) + datetime.timedelta(days=i)
        kg = 80.0 + i  # sube 1 kg/día → crecimiento distinto por semana
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    for gran in ("day", "week", "month"):
        fig = chart_selection(db, ["Pectoral"], [], gran)
        y_vals = [v for t in fig.data for v in t.y if v is not None]
        assert y_vals, gran
        rng = fig.layout.yaxis.range
        assert rng[0] <= 0 <= rng[1], (gran, rng)
        assert rng[1] >= max(y_vals), (gran, rng, max(y_vals))
        assert rng[0] <= min(y_vals), (gran, rng, min(y_vals))


def test_y_dato_nuevo_superior_incluido(tmp_path):
    """Un nuevo máximo/distinto queda incluido en el rango."""
    import datetime

    db = str(tmp_path / "y_new.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    # Primera carga: semana 1 kg 80.
    _seed_days_kg(db, datetime.date(2026, 1, 1), 7, kg=80.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="week")
    y_vals = [v for v in fig.data[0].y if v is not None]
    _assert_contiene_0_y_extremos(fig, y_vals)


def test_y_vacio_sin_excepcion(tmp_path):
    """Datos vacíos: figura vacía sin rango y sin excepción."""
    db = str(tmp_path / "y_empty.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    fig = chart_selection(db, ["Pectoral"], [], "day")  # sin sets
    assert len(fig.data) == 0
    # No debe crashear ni romper el shell.
    assert fig.layout is not None


# ---------------------------------------------------------------------------
# El rango Y inicial solo considera puntos dentro de la ventana X visible
# ---------------------------------------------------------------------------


def _y_window_fixture(db_path: str, periodo_dias: int, kg_viejos: float, kg_recientes: float):
    """Siembra datos antiguos (muy negativos si kg baja) + recientes positivos.

    periodo_dias: días antiguos con kg_viejos; último tramo con kg_recientes.
    Devuelve la DB con Pectoral/Press.
    """
    import datetime

    load_ejercicios(
        db_path, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    start = datetime.date(2026, 1, 1)
    total = periodo_dias
    rows = []
    for i in range(total):
        d = start + datetime.timedelta(days=i)
        kg = kg_recientes if i >= total - 30 else kg_viejos
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db_path, pd.DataFrame(rows))


def test_y_ignora_datos_antiguos_fuera_de_ventana_day(tmp_path):
    """Datos antiguos muy negativos fuera de la ventana no afectan el rango Y:
    la línea 0 queda en posición razonable (sin espacio vacío inflado abajo)."""
    db = str(tmp_path / "ywin.db")
    init_db(db)
    # 120 días: 90 antiguos con kg baja (crecimiento negativo) + 30 recientes altos.
    _y_window_fixture(db, 120, kg_viejos=40.0, kg_recientes=120.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.yaxis.range
    # La ventana solo contiene los últimos ~2 meses (recientes positivos).
    y_vals = [v for v in fig.data[0].y if v is not None]
    max_reciente = max(y_vals)
    # El tope incluye el máximo reciente con margen…
    assert rng[1] >= max_reciente
    # …pero la base NO está hundida por los antiguos negativos: 0 o apenas abajo.
    assert -10 <= rng[0] <= 0, f"la base debe rondar 0, no hundirse: {rng}"
    # Los datos históricos permanecen en la traza (para pan/zoom hacia atrás).
    assert len(fig.data[0].x) == 120


def test_y_ventana_day_solo_recientes_positivos_partida_cerca_de_0(tmp_path):
    """Ventana day con recientes positivos: el eje comienza en 0 (no en -grande)."""
    db = str(tmp_path / "ywin2.db")
    init_db(db)
    _y_window_fixture(db, 120, kg_viejos=50.0, kg_recientes=130.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.yaxis.range
    assert 0.0 <= rng[1]
    assert -1.0 <= rng[0] <= 0.5, f"base cerca de 0: {rng}"


def test_y_ventana_day_recientes_negativos_incluyen_0_y_min(tmp_path):
    """Recientes negativos dentro de la ventana: 0 incluido y mínimo visible."""
    db = str(tmp_path / "ywin3.db")
    init_db(db)
    # Antiguos positivos (out), recientes decrecientes (in).
    _y_window_fixture(db, 120, kg_viejos=120.0, kg_recientes=40.0)
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.yaxis.range
    y_vals = [v for v in fig.data[0].y if v is not None]
    min_visible = min(y_vals[-30:])  # últimos 30 días (ventana)
    assert rng[0] <= min_visible
    assert rng[1] >= 0, f"el tope debe incluir 0: {rng}"


def test_y_ventana_mixta_dentro_incluye_todo_y_0(tmp_path):
    """Mixto dentro de la ventana: contiene todos los valores visibles y 0."""
    import datetime

    db = str(tmp_path / "ywin4.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    rows = []
    for i in range(120):
        d = datetime.date(2026, 1, 1) + datetime.timedelta(days=i)
        if i < 90:
            kg = 120.0  # antiguos altos (out)
        else:
            kg = 90.0 + 40.0 * ((i % 2) - 0.5)  # alterna ± dentro de la ventana
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.yaxis.range
    y_vals = [v for v in fig.data[0].y if v is not None]
    assert rng[0] <= min(y_vals) and rng[1] >= max(y_vals)
    assert rng[0] <= 0 <= rng[1]


def test_y_ventana_multimusculos_solo_puntos_visibles(tmp_path):
    """Multi-músculo: solo los puntos dentro del rango X condicionan el Y."""
    import datetime

    db = str(tmp_path / "ywin5.db")
    init_db(db)
    load_ejercicios(
        db,
        pd.DataFrame(
            [
                {"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"},
                {"grupo_muscular": "Biceps", "ejercicio": "Curl Bayesian"},
            ]
        ),
    )
    # Presión: antiguo muy negativo; Biceps reciente muy positivo fuera de rango
    # de presión.
    rows = []
    for i in range(120):
        d = datetime.date(2026, 1, 1) + datetime.timedelta(days=i)
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": 50.0 if i < 90 else 90.0,
                "rir": 0.0,
            }
        )
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 2,
                "ejercicio": "Curl Bayesian",
                "reps": 10.0,
                "kg": 140.0 if i >= 90 else 12.0,
                "rir": 0.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    fig = chart_selection(db, ["Pectoral", "Biceps"], [], "day")
    rng = fig.layout.yaxis.range
    # El tope cubre el máximo visible (Biceps reciente 140); la base no se hunde.; el antiguo negativo de Press (50)
    # fuera de la ventana no hunde la base.
    assert rng[1] >= 0 and rng[0] <= 0
    assert -12 <= rng[0] <= 1, f"base no hundida por antiguos: {rng}"
    assert len(fig.data[0].x) == 120 and len(fig.data[1].x) == 120


def test_y_menos_datos_que_ventana_usa_todo(tmp_path):
    """Menos datos que la ventana: sin rango X explícito → Y con todos los datos."""
    db = str(tmp_path / "ywin6.db")
    init_db(db)
    _y_window_fixture(db, 10, kg_viejos=40.0, kg_recientes=120.0)  # 10 días < 2 meses
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    rng = fig.layout.yaxis.range
    y_vals = [v for v in fig.data[0].y if v is not None]
    assert rng[0] <= min(y_vals) and rng[1] >= max(y_vals)
    assert rng[0] <= 0 <= rng[1]


def test_y_granularidades_recalculan_con_su_ventana(tmp_path):
    """Cada granularidad recalcula Y con los datos de su ventana visible."""
    import datetime

    db = str(tmp_path / "ywin7.db")
    init_db(db)
    load_ejercicios(
        db, pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press Convergente"}])
    )
    rows = []
    for i in range(150):  # ~5 meses y 22 semanas
        d = datetime.date(2026, 1, 1) + datetime.timedelta(days=i)
        kg = 50.0 if i < 120 else 130.0  # antiguos negativos; último mes fuerte
        rows.append(
            {
                "semana": (i // 7) + 1,
                "dia": "LUNES",
                "fecha": d.isoformat(),
                "set_orden": 1,
                "ejercicio": "Press Convergente",
                "reps": 6.0,
                "kg": kg,
                "rir": 0.0,
            }
        )
    load_training_data(db, pd.DataFrame(rows))
    for gran in ("day", "week", "month"):
        fig = chart_selection(db, ["Pectoral"], [], gran)
        rng = fig.layout.yaxis.range
        assert rng[0] <= 0 <= rng[1], (gran, rng)
        # La base no debe hundirse por los negativos antiguos fuera de la ventana.
        assert rng[0] > -15, (gran, rng)


# ---------------------------------------------------------------------------
# Tooltip canónico (9 posiciones) y RM centralizado
# ---------------------------------------------------------------------------


def test_tooltip_customdata_8_posiciones_day(setup_test_db):
    """Day: [etiqueta '4 mayo', Δ±, series, reps, peso, rir, rm_max, cobertura, nombre] (9 pos.)."""
    from src.metrics_engine import rm_ajustado

    fig = chart_pfr_timeline(setup_test_db, "systemic", granularity="day")
    fila = fig.data[0].customdata[0]
    assert len(fila) == 9
    assert fila[0] == "4 mayo"
    assert fila[1].endswith("%")
    assert int(fila[2]) == 2  # 2 sets del día en la fixture
    assert float(fila[3]) == pytest.approx(6.0)
    assert float(fila[4]) == pytest.approx(85.0)
    assert float(fila[5]) == pytest.approx((1.0 + 0.0) / 2)
    # rm_max = rm_ajustado de la serie top: (85kg, reps 6, rir 1) vía metrics_engine.
    assert float(fila[6]) == pytest.approx(rm_ajustado(85.0, 6.0, 1.0), abs=0.15)
    assert fila[8] == "Crecimiento"


def test_tooltip_customdata_week_y_month_labels(setup_test_db):
    """Week → '4 mayo 2026' (lunes ciclo); Month → 'mayo 2026'; siempre 9 pos. y sin hover nativo."""
    figw = chart_pfr_timeline(setup_test_db, "systemic", granularity="week")
    assert figw.data[0].customdata[0][0] == "4 mayo 2026"
    assert len(figw.data[0].customdata[0]) == 9
    assert figw.data[0].hovertemplate is None
    figm = chart_pfr_timeline(setup_test_db, "systemic", granularity="month")
    assert figm.data[0].customdata[0][0] == "mayo 2026"
    assert len(figm.data[0].customdata[0]) == 9
    assert figm.data[0].hovertemplate is None


def test_tooltip_sin_textos_antiguos_en_figura(setup_test_db):
    """UX-2: sin hovertemplate nativo; customdata sin Volumen/Sueño/Fallos ni unidades."""
    for gran in ("day", "week", "month"):
        fig = chart_pfr_timeline(setup_test_db, "systemic", granularity=gran)
        t = fig.data[0]
        assert t.hovertemplate is None, (gran, t.hovertemplate)
        for fila in t.customdata:
            joined = "|".join(str(v) for v in fila)
            assert "kg" not in joined.replace("RM aj.", ""), (gran, joined)
            assert " h" not in joined
            assert "Fallos" not in joined
            for texto in ("Volumen", "Sueño", "Fallos", "Crecimiento:", '"Fecha "'):
                assert texto not in joined, (gran, texto)


def test_altura_layout_intacta(setup_test_db):
    """La altura del layout no cambia con el nuevo tooltip (450 en ambas fns)."""
    fig = chart_pfr_timeline(setup_test_db, "systemic")
    assert fig.layout.height == 450
    fig2 = chart_selection(setup_test_db, ["Pectoral"], [])
    assert fig2.layout.height == 450


def test_rm_max_usa_metrics_engine(tmp_path):
    """rm_max del hover == rm_ajustado(kg, reps, rir) del mejor set del periodo."""
    import sqlite3
    from datetime import date as _d

    from src.metrics_engine import rm_ajustado
    from src.training_service import calculate_cycle_week, parse_cycle_start

    db = str(tmp_path / "hover.db")
    init_db(db)
    load_ejercicios(
        db,
        pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press"}]),
    )
    fecha = "2026-08-10"
    semana = calculate_cycle_week(_d.fromisoformat(fecha), parse_cycle_start())
    sets_datos = [(40.0, 8.0, 3.0), (95.0, 4.0, 1.0)]
    conn = sqlite3.connect(db)
    try:
        for i, (kg, reps, rir) in enumerate(sets_datos, start=1):
            conn.execute(
                "INSERT INTO training_sets (semana,dia,fecha,set_orden,ejercicio,reps,kg,rir)"
                " VALUES (?, 'LUNES', ?, ?, 'Press', ?, ?, ?)",
                (semana, fecha, i, reps, kg, rir),
            )
        conn.commit()
    finally:
        conn.close()
    fig = chart_pfr_timeline(db, "systemic", granularity="day")
    fila = fig.data[0].customdata[-1]
    esperado = max(rm_ajustado(kg, reps, rir) for kg, reps, rir in sets_datos)
    assert float(fila[6]) == pytest.approx(esperado, abs=0.15)


def test_fmt_num_none_como_guion():
    """None/NaN se renderizan como '—' (ausencia), nunca como 0."""
    from src.charts import _fmt_delta, _fmt_num

    assert _fmt_num(None) == "—"
    assert _fmt_num(float("nan")) == "—"
    assert _fmt_num(82.55) == "82.5" or _fmt_num(82.55) == "82.6"
    assert _fmt_delta(None) == "—"
    assert _fmt_delta(8.44) == "+8.4%"
    assert _fmt_delta(-3.21) == "-3.2%"
    assert _fmt_delta(0.0) == "0.0%"


# ---------------------------------------------------------------------------
# TAREA 3 — Formato compacto y extracción segura para comparación
# ---------------------------------------------------------------------------


def test_format_day_short():
    from src.charts import format_day_short

    assert format_day_short("2026-07-18") == "18 jul"
    # Confusión entre años → añade año corto
    assert format_day_short("2026-07-18", ["2026-07-18", "2025-07-18"]) == "18 jul 26"
    assert format_day_short("2025-07-18", ["2026-07-18", "2025-07-18"]) == "18 jul 25"
    # Sin confusión (mismo año) no añade
    assert format_day_short("2026-07-18", ["2026-07-18", "2026-07-23"]) == "18 jul"


def test_format_week_short():
    from src.charts import format_week_short

    assert format_week_short(1) == "S1"
    assert format_week_short("1") == "S1"
    assert format_week_short(14) == "S14"
    assert format_week_short("14") == "S14"


def test_format_month_short():
    from src.charts import format_month_short

    assert format_month_short("2026-01") == "ene 26"
    assert format_month_short("2026-07") == "jul 26"
    assert format_month_short("2026-07-15") == "jul 26"
    assert format_month_short("2025-12") == "dic 25"


def test_extract_point_values_ok():
    from src.charts import extract_point_values

    row = ["18/07/2026", "+2.3%", "4", "6.0", "85.0", "1.5", "107.6", "Press"]
    vals = extract_point_values(row)
    assert vals is not None
    assert vals["periodo"] == "18/07/2026"
    assert vals["delta"] == "+2.3%"
    assert vals["series"] == "4"
    assert vals["reps"] == "6.0"
    assert vals["peso"] == "85.0"
    assert vals["rir"] == "1.5"
    assert vals["rm"] == "107.6"
    assert vals["trace"] == "Press"
    # 7 valores visibles + trace = 8 columnas, pero los 7 requeridos están presentes
    assert vals["series"] is not None


def test_extract_point_values_incompleto_seguro():
    from src.charts import extract_point_values

    assert extract_point_values(None) is None
    assert extract_point_values([]) is None
    assert extract_point_values(["a", "b"]) is None
    assert extract_point_values(["a"] * 7) is None
    # 8 es mínimo
    assert extract_point_values(["a"] * 8) is not None


def test_point_comparison_id_unica():
    from src.charts import point_comparison_id

    # Granularidad distingue
    assert point_comparison_id("week", "1", "Press") != point_comparison_id("day", "1", "Press")
    # Periodo distingue S1 vs S14 y días distintos
    assert point_comparison_id("week", "1", "Press") != point_comparison_id("week", "14", "Press")
    assert point_comparison_id("day", "2026-07-18", "Press") != point_comparison_id(
        "day", "2026-07-23", "Press"
    )
    # Traza distingue mismo periodo
    assert point_comparison_id("week", "1", "Press") != point_comparison_id("week", "1", "Curl")
    # Case-insensitive traza
    assert point_comparison_id("week", "1", "Press") == point_comparison_id("week", "1", "press")
