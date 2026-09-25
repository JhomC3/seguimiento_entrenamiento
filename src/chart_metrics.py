"""Indice de metricas y resumen de sesion (spec 008)."""

import pandas as pd
import plotly.graph_objects as go

from src.chart_axis import _day_tick_subset, _initial_x_range, _range_for_axis
from src.chart_data import get_exercise_raw_data
from src.chart_format import EXERCISE_PALETTE, _month_tick_label, chart_color, tooltip_period_label


def _tight_range(values: list[float], rel_pad: float, abs_min_pad: float) -> list | None:
    """Rango Y ajustado a los datos visibles, sin forzar el 0.

    ``rel_pad``: fracción del span como margen por lado; ``abs_min_pad``:
    suelo del margen para rachas planas (span 0). Vacío → None (autoscala).
    """
    if not values:
        return None
    lo, hi = min(values), max(values)
    pad = max((hi - lo) * rel_pad, abs_min_pad)
    return [lo - pad, hi + pad]


def chart_metrics_index(
    df: pd.DataFrame,
    granularity: str = "day",
    selection: tuple[str, ...] = (),
) -> go.Figure:
    """Índice 0–100 de métricas (una traza por serie).

    ``df`` es la salida de ``build_metrics_index`` (valores CRUDOS). Cada serie
    se normaliza con ``normalize_01_100`` (recovery: clip); el tooltip lleva el
    valor real + unidad (customdata 2-pos). ``selection`` marca visibles (el
    resto viaja oculto para toggles instantáneos sin refetch).
    Sin series con datos → ``go.Figure()``.
    """
    from src.health_panels import METRIC_DISPLAY, METRIC_ORDER, SERIES, normalize_01_100

    if df.empty:
        return go.Figure()
    x_col = "fecha" if "fecha" in df.columns else "periodo"
    if x_col not in df.columns:
        return go.Figure()
    keys = [k for k in METRIC_ORDER if k in df.columns and df[k].notna().any()]
    if not keys:
        return go.Figure()
    work = df.dropna(subset=[x_col]).reset_index(drop=True)
    x_values = [str(v) for v in work[x_col].tolist()]
    years = {v[:4] for v in x_values}
    multi_year = len(years) > 1
    label_gran = "day" if granularity in ("day", "week") else "month"

    fig = go.Figure()
    for i, key in enumerate(keys):
        label, unit = METRIC_DISPLAY.get(key, (SERIES[key][0], SERIES[key][1]))
        color = EXERCISE_PALETTE[i % len(EXERCISE_PALETTE)]
        raw = work[key].tolist()
        norm = normalize_01_100(work[key], already_01_100=(key == "recovery"))
        customdata = [
            [
                tooltip_period_label(label_gran, x, multi_year),
                "—" if v is None or pd.isna(v) else f"{float(v):.1f} {unit}",
            ]
            for x, v in zip(x_values, raw)
        ]
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=[None if v is None or pd.isna(v) else float(v) for v in norm.tolist()],
                # Espejo de la gráfica de rendimiento (_pfr_trace): líneas
                # puras, sólidas 2.5, paleta en orden (sin marcadores).
                mode="lines",
                name=label,
                visible=key in selection,
                meta=key,
                line={"color": color, "width": 2.5, "dash": "solid"},
                customdata=customdata,
            )
        )
    axis_gran = "month" if granularity == "month" else "day"
    if granularity == "month":
        tickvals = sorted(set(x_values))
        ticktext = [_month_tick_label(v) for v in tickvals]
    else:
        tickvals, ticktext = _day_tick_subset(sorted(set(x_values)), max_ticks=8)
    initial_range = _initial_x_range(x_values, axis_gran)
    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": tickvals,
        "ticktext": ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    xaxis_cfg["type"] = "category" if granularity == "month" else "date"
    if initial_range:
        xaxis_cfg["range"] = _range_for_axis(initial_range, axis_gran)
    fig.update_layout(
        title={"text": "", "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
        yaxis={
            "range": [-5, 105],
            "tickmode": "array",
            "tickvals": [0, 25, 50, 75, 100],
            "showgrid": False,
            "zeroline": False,
            "tickfont": {"size": 10, "color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=250,
        margin={"l": 40, "r": 16, "t": 20, "b": 30},
        hovermode="closest",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        showlegend=False,
        dragmode="pan",
    )
    return fig


def get_exercise_session_summary(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Resumen por sesión con rendimiento y caída intraejercicio."""
    df = get_exercise_raw_data(db_path, ejercicio)
    if df.empty:
        return df

    df["tonelaje"] = df["kg"] * df["reps"]
    session_df = (
        df.groupby(["semana", "sesion", "fecha", "dia"])
        .agg(
            total_sets=("set_orden", "count"),
            total_tonelaje=("tonelaje", "sum"),
            posicion_ejercicio=("posicion_ejercicio", "first"),
            avg_kg=("kg", "mean"),
            avg_reps=("reps", "mean"),
            avg_rm_ajustado=("rm_ajustado", "mean"),
            rm_primera=("rm_ajustado", "first"),
            rm_ultima=("rm_ajustado", "last"),
        )
        .reset_index()
    )

    session_df["avg_kg"] = session_df["avg_kg"].round(1)
    session_df["avg_reps"] = session_df["avg_reps"].round(1)
    session_df["avg_rm_ajustado"] = session_df["avg_rm_ajustado"].round(1)
    session_df["total_tonelaje"] = session_df["total_tonelaje"].round(1)
    session_df["caida_pct"] = (
        (1 - session_df["rm_ultima"] / session_df["rm_primera"]) * 100
    ).round(1)
    session_df["rm_primera"] = session_df["rm_primera"].round(1)
    session_df["rm_ultima"] = session_df["rm_ultima"].round(1)
    session_df = session_df.sort_values(["semana", "sesion"]).reset_index(drop=True)
    return session_df
