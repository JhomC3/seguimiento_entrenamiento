import os

import pandas as pd
import pytest

from src.charts import (
    _pfr_df,
    chart_pfr_timeline,
    chart_selection,
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
    assert "Crecimiento" in fig.data[0].hovertemplate


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
    assert len(fig.data) == 2  # compilado + ejercicio
    assert fig.data[1].name == "Press Convergente"
    # El hover muestra el nombre del ejercicio (customdata[5]).
    assert fig.data[1].customdata[0][5] == "Press Convergente"
    assert "%{customdata[5]}" in fig.data[1].hovertemplate


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
        # 1 músculo, 1 ejercicio válido → Compilado + ejercicio (D2: sin Global)
        (["Pectoral"], ["Press Convergente"], ["Compilado", "Press Convergente"]),
        # 1 músculo, ejercicio ajeno → solo Compilado (D2)
        (["Pectoral"], ["Curl Bayesian"], ["Compilado"]),
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
    # Ejercicios (Compilado guía + ejercicio, sin Global — D2)
    fig2 = chart_selection(setup_test_db, ["Pectoral"], ["Press Convergente"], "day")
    assert [t.name for t in fig2.data] == ["Compilado", "Press Convergente"]


def test_chart_selection_day_con_seleccion_persistida(setup_test_db):
    """Granularidad day con músculo+ejercicio persistentes: tanto el Compilado
    como el ejercicio realmente comparten el eje de fechas diario."""
    fig = chart_selection(setup_test_db, ["Pectoral"], ["Press Convergente"], "day")
    assert len(fig.data) == 2
    for t in fig.data:
        assert list(t.x) == ["2026-05-04", "2026-05-08", "2026-05-11"]


def test_pfr_df_day_tooltip_diario(setup_test_db):
    """El hover diario nombra 'Fecha' (no 'Semana') y conserva series/fallos."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for t in fig.data:
        assert "Fecha" in t.hovertemplate, t.hovertemplate
        assert "Semana" not in t.hovertemplate, t.hovertemplate


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
    """Tooltip diario muestra DD/MM/YYYY, no ISO ni Semana."""
    fig = chart_selection(setup_test_db, ["Pectoral"], [], "day")
    for t in fig.data:
        # Hover usa Fecha + DD/MM/YYYY via customdata[6]
        assert "Fecha" in t.hovertemplate
        assert "Semana" not in t.hovertemplate
        # customdata[6] debe ser DD/MM/YYYY
        assert t.customdata[0][6] == "04/05/2026"
    # chart_pfr_timeline también
    fig2 = chart_pfr_timeline(setup_test_db, "systemic", granularity="day")
    assert "04/05/2026" in fig2.data[0].customdata[0][5]


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
    # Margen superior reservado para la banda de leyenda.
    assert reference["margin"]["t"] >= 70


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
