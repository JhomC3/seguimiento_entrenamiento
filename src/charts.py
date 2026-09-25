"""Entrada de graficas: chart_selection + re-exports (spec 008)."""

import pandas as pd
import plotly.graph_objects as go

from src.chart_axis import (
    _compact_day_labels,
    _day_tick_subset,
    _initial_x_range,
    _multi_year_flag,
    _range_for_axis,
    _x_key,
    _y_visible_in_window,
)
from src.chart_data import (
    _hover_totals_for,
    _pfr_df,
    _weekly_pfr_df,
    get_exercise_cohort_summary,
    get_exercise_raw_data,
)
from src.chart_format import (
    EXERCISE_PALETTE,
    RIR_LINE_ALPHA,
    RIR_TRACE_NAME,
    _fmt_delta,
    _fmt_num,
    _hex_to_rgba,
    _hover_rows,
    _month_tick_label,
    _pooled_rir_by_key,
    _rir_trace,
    _tooltip_day_label,
    _tooltip_month_label,
    _tooltip_week_label,
    chart_color,
    extract_point_values,
    format_day_short,
    format_month_short,
    format_week_short,
    point_comparison_id,
    tooltip_period_label,
)
from src.chart_metrics import (
    _tight_range,
    chart_metrics_index,
    get_exercise_session_summary,
)
from src.chart_timeline import (
    chart_pfr_timeline,
)
from src.db_connection import read_connection

__all__ = [
    "EXERCISE_PALETTE",
    "RIR_LINE_ALPHA",
    "RIR_TRACE_NAME",
    "_compact_day_labels",
    "_day_tick_subset",
    "_fmt_delta",
    "_fmt_num",
    "_hex_to_rgba",
    "_hover_rows",
    "_hover_totals_for",
    "_initial_x_range",
    "_month_tick_label",
    "_multi_year_flag",
    "_pfr_df",
    "_pooled_rir_by_key",
    "_range_for_axis",
    "_rir_trace",
    "_tight_range",
    "_tooltip_day_label",
    "_tooltip_month_label",
    "_tooltip_week_label",
    "_weekly_pfr_df",
    "_x_key",
    "_y_visible_in_window",
    "chart_color",
    "chart_metrics_index",
    "chart_pfr_timeline",
    "extract_point_values",
    "format_day_short",
    "format_month_short",
    "format_week_short",
    "get_exercise_cohort_summary",
    "get_exercise_raw_data",
    "get_exercise_session_summary",
    "point_comparison_id",
    "tooltip_period_label",
]


def _pfr_trace(
    df: pd.DataFrame,
    name: str,
    color: str,
    *,
    alpha: float = 1.0,
    width: float = 2.5,
    marker_size: int = 3,
    granularity: str = "week",
    multi_year: bool = False,
) -> go.Scatter:
    # Eje X y etiqueta de periodo según granularidad: la serie semanal conserva
    # `semana`; day y month usan `periodo` (fecha/label cronológico real).
    x_col = "semana" if granularity == "week" else "periodo"

    line_color = color if alpha >= 1.0 else _hex_to_rgba(color, alpha)
    customdata = _hover_rows(df, name, granularity=granularity, multi_year=multi_year)
    return go.Scatter(
        x=df[x_col],
        y=df["crecimiento"],
        mode="lines",
        name=name,
        line={"color": line_color, "width": width, "dash": "solid"},
        customdata=customdata,
    )


def chart_selection(
    db_path: str,
    musculos: list[str],
    ejercicios: list[str],
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de la selección actual:

    - 0 músculos: línea sistémica global ("Global").
    - 1 músculo, 0 ejercicios: Global + nombre del músculo.
    - 1 músculo, N ejercicios válidos: músculo (guía, UX-2: sin "Compilado")
      + ejercicios. (Global se oculta en estado ejercicio — decisión D2.)
    - 2+ músculos: Global + músculos. Los ejercicios no aplican.

    Los ejercicios que no pertenecen al músculo se descartan.

    En todos los estados se añade la traza "RIR" (RIR medio pooled del ámbito
    seleccionado, eje Y derecho, blanco translúcido discontinuo): existe
    siempre que el ámbito tenga series.
    """
    traces: list[go.Scatter] = []
    title = "Rendimiento – Cuerpo entero"
    # The systemic series provides a stable vertical reference. Selection
    # changes may add traces outside this window, but must never resize or
    # vertically reposition the chart shell.
    reference_df = _pfr_df(db_path, "systemic", None, granularity)
    # Flag de figura (no de traza): todas las trazas etiquetan un mismo x con
    # el mismo formato (año completo en day solo si el dataset abarca >1 año).
    multi_year = _multi_year_flag(reference_df, granularity)
    # Ámbito del RIR: sigue a la selección como las trazas PFR.
    rir_scope: tuple[list[str], list[str]] = ([], [])

    if len(musculos) == 0:
        # Estado global: línea sistémica (D3).
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df,
                    "Global",
                    chart_color("primary"),
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )
    elif len(musculos) == 1:
        musculo = musculos[0]
        title = f"Rendimiento – {musculo}"

        if ejercicios:
            # Estado ejercicio: el músculo guía (UX-2) + ejercicios (sin global — D2).
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                traces.append(
                    _pfr_trace(
                        compiled,
                        musculo,
                        chart_color("primary"),
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )

            with read_connection(db_path) as conn:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                    (musculo,),
                ).fetchall()
            valid = {str(r[0]).lower() for r in rows}
            rir_scope = ([musculo], [e for e in ejercicios if e.lower() in valid])
            for idx, ejercicio in enumerate(ejercicios):
                if ejercicio.lower() not in valid:
                    continue
                df = _pfr_df(db_path, "exercise", ejercicio, granularity)
                if df.empty:
                    continue
                color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
                traces.append(
                    _pfr_trace(
                        df,
                        ejercicio,
                        color,
                        alpha=0.4,
                        width=3.5,
                        marker_size=3,
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
        else:
            # Estado muscular: misma jerarquía que 2+ músculos:
            # Global sólido + músculo identificado y translúcido.
            rir_scope = ([musculo], [])
            global_df = _pfr_df(db_path, "systemic", None, granularity)
            if not global_df.empty:
                traces.append(
                    _pfr_trace(
                        global_df,
                        "Global",
                        chart_color("primary"),
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                color = EXERCISE_PALETTE[0]
                traces.append(
                    _pfr_trace(
                        compiled,
                        musculo,
                        color,
                        alpha=0.4,
                        width=3.5,
                        marker_size=3,
                        granularity=granularity,
                        multi_year=multi_year,
                    )
                )
    elif len(musculos) >= 2:
        rir_scope = (list(musculos), [])
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df,
                    "Global",
                    chart_color("primary"),
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )
        for idx, musculo in enumerate(musculos):
            df = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            traces.append(
                _pfr_trace(
                    df,
                    musculo,
                    color,
                    alpha=0.4,
                    width=3.5,
                    marker_size=3,
                    granularity=granularity,
                    multi_year=multi_year,
                )
            )

    if not traces:
        return go.Figure()

    fig = go.Figure()
    for t in traces:
        fig.add_trace(t)

    # Eje X primero: la ventana temporal inicial determina qué puntos visibles
    # condicionan el rango Y (los históricos fuera de la ventana permanecen en
    # la traza para pan/zoom, pero no afectan la escala vertical inicial).
    all_x = [v for t in traces for v in t.x]
    initial_range = _initial_x_range(all_x, granularity)

    y_visible: list[float] = []
    for t in traces:
        y_visible.extend(_y_visible_in_window(list(t.x), list(t.y), initial_range, granularity))
    ref_x_col = "semana" if granularity == "week" else "periodo"
    reference_y = _y_visible_in_window(
        list(reference_df[ref_x_col]),
        list(reference_df["crecimiento"]),
        initial_range,
        granularity,
    )
    # El rango Y incluye todas las series visibles en la ventana (Global,
    # músculos y ejercicios) más la línea base 0: ningún punto visible queda cortado.
    scale_vals = y_visible + reference_y + [0.0]
    y_min = min(scale_vals)
    y_max = max(scale_vals)
    # Margen por lado, proporcional a la extensión de cada lado desde 0: así la
    # línea 0 queda visible con un margen pequeño sin inflar huecos (p. ej. un
    # baseline ~0 apenas añade margen superior aunque el mínimo sea muy negativo).
    flat = y_max == y_min
    extent_hi = max(0.0, y_max)
    extent_lo = max(0.0, -y_min)
    y_padding_hi = extent_hi * 0.15 if extent_hi > 0 else (5 if flat else 0)
    y_padding_lo = extent_lo * 0.15 if extent_lo > 0 else (5 if flat else 0)
    y_bottom = min(0.0, y_min) - y_padding_lo
    y_top = max(0.0, y_max) + y_padding_hi

    # RIR medio del ámbito seleccionado: traza única sobre el eje derecho.
    # Fuera de la escala Y principal a propósito (unidades distintas); existe
    # siempre que el ámbito tenga series (ausente = 0, como el hover).
    rir = _rir_trace(_pooled_rir_by_key(db_path, *rir_scope, granularity), granularity, multi_year)
    rir_range: list | None = None
    if rir is not None:
        fig.add_trace(rir)
        rir_range = _tight_range(
            [
                float(v)
                for v in _y_visible_in_window(list(rir.x), list(rir.y), initial_range, granularity)
                if v is not None and not pd.isna(v)
            ],
            0.15,
            0.5,
        )

    # Eje X: tickmode array con subconjunto para no apiñar (day: máx 8 etiquetas)
    if granularity == "day":
        all_periods = sorted({str(v) for v in all_x})
        tickvals, ticktext = _day_tick_subset(all_periods, max_ticks=8)
    elif all_x and isinstance(all_x[0], int):
        tickvals = sorted(set(all_x))
        ticktext = [_month_tick_label(v) for v in tickvals]
    else:
        tickvals = sorted({str(v) for v in all_x})
        ticktext = [str(v) for v in tickvals]

    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": tickvals,
        "ticktext": ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    # Tipo de eje explícito por granularidad: date para day, category para
    # week y month (las claves normalizadas se convierten a la representación
    # del eje con _range_for_axis; sin ambigüedad de tipo).
    xaxis_cfg["type"] = "date" if granularity == "day" else "category"
    if initial_range:
        xaxis_cfg["range"] = _range_for_axis(initial_range, granularity)

    fig.update_layout(
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
        yaxis={
            "range": [y_bottom, y_top],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        height=450,
        # Sin leyenda ni títulos: el tooltip cristal es el único identificador
        # de traza. La estabilidad del shell entre estados la dan los márgenes
        # y la altura idénticos (ver test_chart_layout_estable_entre_estados).
        # r44 reserva sitio a los ticks del eje RIR derecho.
        margin={"l": 48, "r": 44, "t": 20, "b": 28},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        showlegend=False,
        dragmode="pan",
        **(
            {
                "yaxis2": {
                    "overlaying": "y",
                    "side": "right",
                    "showgrid": False,
                    "zeroline": False,
                    "tickfont": {"color": chart_color("axes")},
                    **({"range": rir_range} if rir_range is not None else {}),
                }
            }
            if rir is not None
            else {}
        ),
    )
    return fig
