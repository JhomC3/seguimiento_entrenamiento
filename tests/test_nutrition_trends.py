"""Tendencia nutricional MA7: unificación de peso, media continua y gráfica dual."""

import json
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.analysis_data import daily_weight_manual, daily_weight_unified
from src.charts import chart_nutrition_trends
from src.dashboard_service import chart_shell_html
from src.database import init_db
from src.models import ValidationError
from src.nutrition_trends import build_nutrition_trends
from src.response_fragments import (
    nutrition_trend_data_oob,
    nutrition_trend_empty_oob,
    nutrition_trend_header_oob,
)
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
        CREATE TABLE diario_alimentacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL,
            orden INTEGER NOT NULL, alimento TEXT NOT NULL, cantidad_g REAL,
            kcal REAL NOT NULL, carbohidratos REAL NOT NULL, fibra REAL NOT NULL,
            proteina REAL NOT NULL, grasa REAL NOT NULL, hierro REAL NOT NULL,
            calcio REAL NOT NULL, vitamina_c REAL NOT NULL, vitamina_a REAL NOT NULL,
            origen TEXT NOT NULL DEFAULT 'google'
        );
        CREATE TABLE parametros_diarios (
            fecha TEXT PRIMARY KEY, peso_kg REAL NOT NULL DEFAULT 70,
            factor_proteina REAL NOT NULL DEFAULT 1.5,
            factor_grasa REAL NOT NULL DEFAULT 1.1,
            kcal_objetivo REAL NOT NULL DEFAULT 2300,
            fibra_objetivo REAL NOT NULL DEFAULT 0,
            hierro_objetivo REAL NOT NULL DEFAULT 0,
            calcio_objetivo REAL NOT NULL DEFAULT 0,
            vitamina_c_objetivo REAL NOT NULL DEFAULT 0,
            vitamina_a_objetivo REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _insert_weight_hc(db_path: str, kg: float, iso: str) -> None:
    conn = sqlite3.connect(db_path)
    payload = json.dumps({"value": {"kg": kg}})
    ts = _ts(iso)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES (?, 'WEIGHT', ?, ?, ?, 1, ?, ?, ?)",
        (f"w-{ts}-{kg}", ts, ts, ts, payload, TZ, TZ),
    )
    conn.commit()
    conn.close()


def _insert_kcal(db_path: str, fecha: str, kcal: float) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, kcal, carbohidratos, fibra, "
        "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES (?, 1, 'X', ?, 0, 0, 0, 0, 0, 0, 0, 0)",
        (fecha, kcal),
    )
    conn.commit()
    conn.close()


def _insert_peso_manual(db_path: str, fecha: str, peso: float) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO parametros_diarios (fecha, peso_kg) VALUES (?, ?)", (fecha, peso))
    conn.commit()
    conn.close()


def test_weight_manual_manda_sobre_hc(db):
    _insert_weight_hc(db, 90.0, "2026-08-10 07:00")
    _insert_peso_manual(db, "2026-08-10", 80.0)
    unified = daily_weight_unified(db)
    assert len(unified) == 1
    assert unified.iloc[0]["valor"] == pytest.approx(80.0)
    manual = daily_weight_manual(db)
    assert manual.iloc[0]["valor"] == pytest.approx(80.0)


def test_weight_unified_respaldo_hc(db):
    _insert_weight_hc(db, 83.0, "2026-08-10 07:00")
    unified = daily_weight_unified(db)
    assert unified.iloc[0]["valor"] == pytest.approx(83.0)


def test_weight_unified_vacio(db):
    assert daily_weight_unified(db).empty


def test_ma7_calendario_huecos_no_cero(db):
    # 8 días de kcal con un hueco en medio: el hueco no arrastra a 0.
    for i, kcal in enumerate([2000, 2000, 2000, 2000, 2000, 2000, 2000, 2400], start=1):
        if i == 4:
            continue  # hueco: sin fila
        _insert_kcal(db, f"2026-08-{i:02d}", kcal)
    df = build_nutrition_trends(db, "day")
    assert not df.empty
    last = df[df["fecha"] == "2026-08-08"].iloc[0]
    # Ventana 02..08 con un NaN: media de 6 valores (no divide entre 7 con 0).
    assert last["kcal_ma7"] == pytest.approx((2000 * 5 + 2400) / 6)
    assert last["kcal_ma7"] > 2000


def test_ma7_peso_min_periods(db):
    _insert_peso_manual(db, "2026-08-10", 80.0)
    # Un solo peso aislado queda en NaN (min_periods=2) → sin gráfica.
    assert build_nutrition_trends(db, "day").empty
    _insert_peso_manual(db, "2026-08-11", 82.0)
    df = build_nutrition_trends(db, "day")
    assert df["peso_ma7"].dropna().tolist() == [pytest.approx(81.0)]


def test_granularidad_week_month(db):
    for i in range(1, 15):
        _insert_kcal(db, f"2026-08-{i:02d}", 2000.0)
        _insert_peso_manual(db, f"2026-08-{i:02d}", 80.0)
    week = build_nutrition_trends(db, "week")
    assert "periodo" in week.columns
    assert week["kcal_ma7"].notna().all()
    month = build_nutrition_trends(db, "month")
    assert month.iloc[0]["periodo"] == "2026-08"
    assert month.iloc[0]["kcal_ma7"] == pytest.approx(2000.0)


def test_granularidad_invalida(db):
    with pytest.raises(ValidationError):
        build_nutrition_trends(db, "quincena")


def test_chart_vacio(db):
    fig = chart_nutrition_trends(build_nutrition_trends(db, "day"), "day")
    assert not fig.data


def test_chart_dual_axis(db):
    for i in range(1, 10):
        _insert_kcal(db, f"2026-08-{i:02d}", 2000.0 + i * 10)
        _insert_peso_manual(db, f"2026-08-{i:02d}", 80.0)
    df = build_nutrition_trends(db, "day")
    fig = chart_nutrition_trends(df, "day")
    assert len(fig.data) == 2
    assert fig.data[0].name == "kcal"
    assert fig.data[1].name == "peso"
    assert fig.data[1].yaxis == "y2"
    # Sin títulos de eje (la leyenda mapea color→serie); kcal en miles.
    assert not fig.layout.yaxis.title.text
    assert not fig.layout.yaxis2.title.text
    assert not fig.layout.xaxis.title.text
    assert fig.layout.yaxis.tickformat == ".3s"
    assert fig.layout.height == 230
    assert (fig.layout.margin.l, fig.layout.margin.r) == (40, 40)
    assert (fig.layout.margin.t, fig.layout.margin.b) == (20, 24)
    assert fig.layout.showlegend is False
    # Peso: guía translúcida que une puntos disponibles; kcal con cortes honestos.
    assert fig.data[1].line.color.startswith("rgba")
    assert fig.data[1].line.width == 3.5
    assert fig.data[1].connectgaps is True
    assert not fig.data[0].connectgaps
    # Tooltip cristal: customdata 4-pos, sin hover nativo (una sola fecha en cliente).
    for trace in fig.data:
        assert trace.hovertemplate is None
        assert len(trace.customdata[0]) == 4
    assert fig.data[0].customdata[0][3] == "kcal"
    assert fig.data[1].customdata[0][3] == "peso"


def test_eje_kcal_ajustado_a_datos_actuales(db):
    # Rango real 2800-3000: el eje no debe bajar al 0 ni regalar rango vacío.
    for i in range(1, 12):
        _insert_kcal(db, f"2026-08-{i:02d}", 2800.0 + (i % 3) * 100)
        _insert_peso_manual(db, f"2026-08-{i:02d}", 80.0)
    fig = chart_nutrition_trends(build_nutrition_trends(db, "day"), "day")
    lo, hi = fig.layout.yaxis.range
    assert lo > 2000
    assert hi - lo < 600


def test_eje_kcal_racha_plana_no_colapsa():
    import pandas as pd

    flat = pd.DataFrame(
        {
            "fecha": ["2026-08-01", "2026-08-02", "2026-08-03"],
            "kcal_ma7": [2850.0, 2850.0, 2850.0],
            "peso_ma7": [80.0, 80.0, 80.0],
        }
    )
    fig = chart_nutrition_trends(flat, "day")
    lo, hi = fig.layout.yaxis.range
    assert lo < 2850.0 < hi
    assert hi - lo >= 100


def test_chart_week_month_ticks(db):
    for i in range(1, 15):
        _insert_kcal(db, f"2026-08-{i:02d}", 2000.0)
        _insert_peso_manual(db, f"2026-08-{i:02d}", 80.0)
    week_fig = chart_nutrition_trends(build_nutrition_trends(db, "week"), "week")
    assert len(week_fig.data) == 2
    # Semana: etiquetas compactas de día, nunca ISO completo.
    assert week_fig.layout.xaxis.ticktext
    assert all("-" not in str(t) for t in week_fig.layout.xaxis.ticktext)
    assert len(week_fig.data[0].customdata[0]) == 4
    month_fig = chart_nutrition_trends(build_nutrition_trends(db, "month"), "month")
    assert len(month_fig.data) == 2
    assert not month_fig.layout.xaxis.title.text
    assert month_fig.layout.xaxis.type == "category"
    assert month_fig.data[0].customdata[0][0] == "agosto 2026"


def test_ticks_en_ventana_visible_con_historico_largo(db):
    """Con meses de registro, los ticks viven en la ventana inicial visible:
    el eje nunca queda vacío ni con auto-ticks de fecha completa."""
    import pandas as pd

    base = pd.Timestamp("2026-01-01")
    for i in range(120):
        day = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        _insert_kcal(db, day, 2800.0)
        _insert_peso_manual(db, day, 80.0)
    df = build_nutrition_trends(db, "day")
    fig = chart_nutrition_trends(df, "day")
    tickvals = [str(v) for v in fig.layout.xaxis.tickvals]
    axis_range = [str(v) for v in fig.layout.xaxis.range]
    assert len(tickvals) >= 4
    assert all(axis_range[0] <= v <= axis_range[1] for v in tickvals)
    assert all("-" not in str(t) or len(str(t)) <= 8 for t in fig.layout.xaxis.ticktext)


def test_tooltip_customdata_formato(db):
    for i, (kcal, peso) in enumerate([(2800.0, 80.0), (2850.0, 81.0), (2900.0, 82.0)], start=10):
        _insert_kcal(db, f"2026-08-{i:02d}", kcal)
        _insert_peso_manual(db, f"2026-08-{i:02d}", peso)
    fig = chart_nutrition_trends(build_nutrition_trends(db, "day"), "day")
    fila_kcal = fig.data[0].customdata[1]
    assert fila_kcal[0] == "11 agosto"
    assert fila_kcal[1] == "2825"
    assert fila_kcal[2] == "80.5"
    fila_peso = fig.data[1].customdata[2]
    assert fila_peso[0] == "12 agosto"
    assert fila_peso[2] == "81.0"
    # Hueco de peso: '—', nunca 0.
    assert fig.data[1].customdata[0][2] == "—"


def test_chart_solo_peso_y_solo_kcal():
    import pandas as pd

    solo_peso = pd.DataFrame(
        {
            "fecha": ["2026-08-01", "2026-08-02"],
            "kcal_ma7": [float("nan")] * 2,
            "peso_ma7": [80.0, 81.0],
        }
    )
    fig = chart_nutrition_trends(solo_peso, "day")
    assert len(fig.data) == 2
    assert fig.layout.yaxis.autorange or "range" not in str(fig.layout.yaxis.to_plotly_json())
    solo_kcal = pd.DataFrame(
        {
            "fecha": ["2026-08-01", "2026-08-02"],
            "kcal_ma7": [2000.0, 2100.0],
            "peso_ma7": [float("nan")] * 2,
        }
    )
    fig2 = chart_nutrition_trends(solo_kcal, "day")
    assert len(fig2.data) == 2


def test_chart_filas_sin_puntos_y_sin_eje():
    import pandas as pd

    all_nan = pd.DataFrame(
        {"fecha": ["2026-08-01"], "kcal_ma7": [float("nan")], "peso_ma7": [float("nan")]}
    )
    assert not chart_nutrition_trends(all_nan, "day").data
    sin_eje = pd.DataFrame({"kcal_ma7": [2000.0], "peso_ma7": [80.0]})
    assert not chart_nutrition_trends(sin_eje, "day").data


def test_chart_ventana_inicial_rango(db):
    import pandas as pd

    base = pd.Timestamp("2026-01-01")
    for i in range(80):
        day = (base + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        _insert_kcal(db, day, 2000.0)
        _insert_peso_manual(db, day, 80.0)
    df = build_nutrition_trends(db, "day")
    fig = chart_nutrition_trends(df, "day")
    assert len(fig.data) == 2
    assert fig.layout.xaxis.range is not None


def test_shell_prefix_nutricion(db):
    for i in range(1, 4):
        _insert_kcal(db, f"2026-08-{i:02d}", 2000.0)
    df = build_nutrition_trends(db, "day")
    html = chart_shell_html(
        "Nutrición",
        chart_nutrition_trends(df, "day"),
        empty_text="Sin datos de nutrición o peso",
        prefix="nutrition-trend",
    )
    assert 'id="nutrition-trend-header"' in html
    assert 'id="nutrition-trend-data"' in html
    assert 'id="nutrition-trend-plot"' in html
    assert ">Nutrición<" in html
    assert "media 7" not in html


def test_shell_prefix_unified_compat():
    from plotly import graph_objects as go

    html = chart_shell_html("Rendimiento", go.Figure())
    assert 'id="unified-chart-header"' in html
    assert ">Rendimiento<" in html


def test_oob_nutricion():
    assert 'id="nutrition-trend-data"' in nutrition_trend_data_oob("{}")
    assert 'id="nutrition-trend-empty"' in nutrition_trend_empty_oob(True, "Sin datos")
    assert "Nutrición" in nutrition_trend_header_oob()


def test_index_incluye_panel_nutricion(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gym.db")
    init_db(db_path)
    monkeypatch.setattr(appmod, "DB_PATH", db_path)
    client = TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})
    body = client.get("/").text
    assert 'id="nutrition-trend-container"' in body
    assert 'id="nutrition-trend-data"' in body
    assert 'id="nutrition-trend-empty"' in body


def test_grafica_emite_oob_nutricion(tmp_path, monkeypatch):
    db_path = str(tmp_path / "gym.db")
    init_db(db_path)
    monkeypatch.setattr(appmod, "DB_PATH", db_path)
    client = TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})
    body = client.get("/grafica", params={"gran": "day"}).text
    assert 'id="nutrition-trend-data"' in body
    assert 'id="nutrition-trend-empty"' in body
    assert 'id="unified-chart-data"' in body
