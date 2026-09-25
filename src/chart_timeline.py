"""Linea temporal PFR (spec 008)."""

import pandas as pd
import plotly.graph_objects as go

from config import CICLO_NUMERO
from src.chart_axis import (
    _day_tick_subset,
    _initial_x_range,
    _multi_year_flag,
    _range_for_axis,
    _y_visible_in_window,
)
from src.chart_data import _pfr_df
from src.chart_format import (
    _hover_rows,
    _month_tick_label,
    _pooled_rir_by_key,
    _rir_trace,
    chart_color,
)
from src.chart_metrics import _tight_range


def chart_pfr_timeline(
    db_path: str,
    filter_type: str,
    filter_value: str | None = None,
    title: str = f"Rendimiento – Ciclo {CICLO_NUMERO}",
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de crecimiento vs baseline (semana 1 = 0).

    El hover resume el periodo: series, sets al fallo, volumen, peso y sueño.
    """
    periodic = _pfr_df(db_path, filter_type, filter_value, granularity)
    if periodic.empty:
        return go.Figure()

    # Eje X (sin título: la granularidad la indica el selector visible)
    x_col = "periodo" if "periodo" in periodic.columns else "semana"

    # Ventana temporal inicial antes del rango Y: solo los puntos dentro de la
    # ventana visible condicionan la escala vertical (los históricos permanecen
    # en la traza para pan/zoom, pero no afectan el rango Y inicial).
    initial_range = _initial_x_range(periodic[x_col].tolist(), granularity)
    y_visible = _y_visible_in_window(
        list(periodic[x_col]),
        list(periodic["crecimiento"]),
        initial_range,
        granularity,
    )
    scale_vals = y_visible + [0.0]
    y_min = min(scale_vals)
    y_max = max(scale_vals)
    # Margen por lado proporcional a la extensión desde 0 (línea base siempre
    # visible con un margen pequeño, sin inflar huecos; fallback 5 solo si plano).
    flat = y_max == y_min
    extent_hi = max(0.0, y_max)
    extent_lo = max(0.0, -y_min)
    y_padding_hi = extent_hi * 0.15 if extent_hi > 0 else (5 if flat else 0)
    y_padding_lo = extent_lo * 0.15 if extent_lo > 0 else (5 if flat else 0)
    y_bottom = min(0.0, y_min) - y_padding_lo
    y_top = max(0.0, y_max) + y_padding_hi

    fig = go.Figure()

    multi_year = _multi_year_flag(periodic, granularity)
    if granularity == "day":
        periods = [str(v) for v in periodic[x_col].tolist()]
        tickvals, ticktext = _day_tick_subset(periods, max_ticks=8)
        customdata_vals = _hover_rows(
            periodic, "Global", granularity=granularity, multi_year=multi_year
        )
        x_tickvals = tickvals
        x_ticktext = ticktext
    else:
        x_tickvals = periodic[x_col].tolist()
        x_ticktext = (
            [_month_tick_label(v) for v in periodic[x_col]]
            if granularity == "month"
            else [str(v) for v in periodic[x_col]]
        )
        customdata_vals = _hover_rows(periodic, "Global", granularity=granularity)

    fig.add_trace(
        go.Scatter(
            x=periodic[x_col],
            y=periodic["crecimiento"],
            mode="lines",
            name="Global",
            line={"color": chart_color("primary"), "width": 2.5, "dash": "solid"},
            customdata=customdata_vals,
        )
    )

    # RIR medio del filtro en el eje derecho (mismo criterio que chart_selection).
    if filter_type == "muscle_group" and filter_value:
        _rir_scope: tuple[list[str], list[str]] = ([filter_value], [])
    elif filter_type == "exercise" and filter_value:
        _rir_scope = ([], [filter_value])
    else:
        _rir_scope = ([], [])
    rir = _rir_trace(_pooled_rir_by_key(db_path, *_rir_scope, granularity), granularity, multi_year)
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

    xaxis_cfg: dict = {
        "tickmode": "array",
        "tickvals": x_tickvals,
        "ticktext": x_ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    # Tipo de eje explícito por granularidad (date/category).
    xaxis_cfg["type"] = "date" if granularity == "day" else "category"
    # Ventana temporal inicial (solo presentación; todos los datos quedan en la
    # figura y el usuario puede navegar hacia atrás con pan/zoom).
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
        # de traza; la unidad % vive en tooltip e Historial. Estabilidad entre
        # estados por márgenes/altura idénticos (ver test de layout estable).
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
