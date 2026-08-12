import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import CICLO_NUMERO
from src.analysis_data import (
    daily_avg_hr,
    daily_cardio_minutes,
    daily_hrv,
    daily_kcal,
    daily_resting_hr,
    daily_sleep_hours,
    daily_steps,
    daily_volume,
    daily_weight,
)
from src.db_connection import read_connection
from src.metrics_engine import RM_FACTOR, calculate_pfr_timeline

LAYER_TITLES = {
    "pfr": "Rendimiento (%)",
    "volumen": "Volumen (kg)",
    "peso": "Peso (kg)",
    "kcal": "Kcal",
    "sueno": "Sueño (h)",
    "fc": "FC media",
    "fc_reposo": "FC reposo",
    "hrv": "HRV (ms)",
    "pasos": "Pasos",
    "cardio": "Cardio (min)",
    "fallos": "Sets al fallo",
}

LAYER_COLORS = {
    "pfr": "#e56d88",
    "volumen": "#7dd3fc",
    "peso": "#fbbf24",
    "kcal": "#a3e635",
    "sueno": "#c084fc",
    "fc": "#f87171",
    "fc_reposo": "#fb923c",
    "hrv": "#34d399",
    "pasos": "#60a5fa",
    "cardio": "#f472b6",
    "fallos": "#9b1b30",
}

NIVEL_FILTER_TYPE = {
    "global": "systemic",
    "grupo": "category",
    "musculo": "muscle_group",
    "ejercicio": "exercise",
}

_LAYER_FUNCS = {
    "volumen": daily_volume,
    "peso": daily_weight,
    "kcal": daily_kcal,
    "sueno": daily_sleep_hours,
    "fc": daily_avg_hr,
    "fc_reposo": daily_resting_hr,
    "hrv": daily_hrv,
    "pasos": daily_steps,
    "cardio": daily_cardio_minutes,
}


def _pfr_series(db_path: str, nivel: str, focus: str | None, layer: str) -> pd.DataFrame:
    timeline = calculate_pfr_timeline(db_path, NIVEL_FILTER_TYPE[nivel], focus)
    if timeline.empty:
        return pd.DataFrame()
    col = "rendimiento" if layer == "pfr" else "sets_fallo"
    return timeline[["fecha_dt", col]].rename(columns={col: "valor"})


def load_layer_series(
    db_path: str,
    nivel: str,
    focus: str | None,
    layers: list[str],
    rango_semanas: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Series diarias por capa alineadas a un rango de fechas continuo.

    Devuelve {layer: DataFrame(fecha_dt, valor)} solo con días con datos.
    El rango se deriva de la unión de fechas de las capas activas; si
    rango_semanas se indica, recorta al final del rango de datos.
    """
    if nivel not in NIVEL_FILTER_TYPE:
        raise ValueError(f"Nivel desconocido: {nivel}")
    series = {}
    for layer in layers:
        if layer in ("pfr", "fallos"):
            df = _pfr_series(db_path, nivel, focus, layer)
        elif layer in _LAYER_FUNCS:
            df = _LAYER_FUNCS[layer](db_path)
        else:
            continue
        if not df.empty:
            series[layer] = df
    if not series:
        return {}
    index = pd.DatetimeIndex(
        sorted(set().union(*(set(s["fecha_dt"]) for s in series.values())))
    )
    if rango_semanas:
        cutoff = index.max() - pd.Timedelta(weeks=rango_semanas)
        index = index[index >= cutoff]
    if len(index) == 0:
        return {}
    out = {}
    for layer, df in series.items():
        reindexed = (
            df.set_index("fecha_dt")["valor"]
            .reindex(index)
            .dropna()
            .reset_index()
            .rename(columns={"index": "fecha_dt", "valor": "valor"})
        )
        if not reindexed.empty:
            out[layer] = reindexed
    return out


def build_analysis_chart(
    db_path: str,
    nivel: str,
    focus: str | None,
    layers: list[str],
    rango_semanas: int | None = 8,
) -> go.Figure:
    """Paneles apilados con eje X de fechas compartido; un subplot por capa activa."""
    series = load_layer_series(db_path, nivel, focus, layers, rango_semanas)
    active = [l for l in layers if l in series]
    if not active:
        return go.Figure()
    fig = make_subplots(
        rows=len(active),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=[LAYER_TITLES[l] for l in active],
    )
    for i, layer in enumerate(active, start=1):
        df = series[layer]
        color = LAYER_COLORS[layer]
        if layer == "volumen":
            fig.add_trace(
                go.Bar(
                    x=df["fecha_dt"],
                    y=df["valor"],
                    name=LAYER_TITLES[layer],
                    marker_color=color,
                    hovertemplate="%{y:.0f} kg<extra></extra>",
                ),
                row=i,
                col=1,
            )
        elif layer == "pasos":
            fig.add_trace(
                go.Bar(
                    x=df["fecha_dt"],
                    y=df["valor"],
                    name=LAYER_TITLES[layer],
                    marker_color=color,
                    hovertemplate="%{y:,.0f}<extra></extra>",
                ),
                row=i,
                col=1,
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=df["fecha_dt"],
                    y=df["valor"],
                    mode="lines+markers",
                    name=LAYER_TITLES[layer],
                    line={"color": color, "width": 2},
                    marker={"color": color, "size": 5},
                    hovertemplate="%{y:.1f}<extra></extra>",
                ),
                row=i,
                col=1,
            )
    fig.update_layout(
        height=140 + 160 * len(active),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#a3a3a3"},
        hovermode="x unified",
        hoverlabel={"bgcolor": "#1a1a1a", "font": {"color": "white", "size": 12}, "bordercolor": "#333"},
        margin={"l": 50, "r": 16, "t": 40, "b": 30},
        showlegend=False,
    )
    fig.update_annotations(font={"color": "#a3a3a3", "size": 11})
    fig.update_xaxes(showgrid=False, tickfont={"color": "#a3a3a3", "size": 9})
    fig.update_yaxes(showgrid=False, zerolinecolor="#333", tickfont={"color": "#a3a3a3", "size": 9}, title=None)
    return fig


def get_exercise_raw_data(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna datos crudos con RM y RM ajustado calculados."""
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, kg, reps, rir
            FROM training_sets
            WHERE ejercicio = ? AND kg IS NOT NULL AND reps IS NOT NULL
            ORDER BY semana, fecha, set_orden
        """,
            conn,
            params=[ejercicio],
        )

    if df.empty:
        return df

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    df["serie"] = df.groupby(["semana", "sesion"]).cumcount() + 1

    rir_safe = df["rir"].fillna(0)
    df["rm"] = (df["kg"] * (1 + RM_FACTOR * df["reps"])).round(1)
    df["rm_ajustado"] = (df["kg"] * (1 + RM_FACTOR * (df["reps"] + (1 + rir_safe)))).round(1)

    df = df.sort_values(["semana", "fecha_dt", "serie"]).reset_index(drop=True)
    return df[
        [
            "semana",
            "sesion",
            "serie",
            "fecha",
            "fecha_dt",
            "dia",
            "set_orden",
            "kg",
            "reps",
            "rir",
            "rm",
            "rm_ajustado",
        ]
    ]


def chart_pfr_timeline(
    db_path: str,
    filter_type: str,
    filter_value: str | None = None,
    title: str = f"Rendimiento – Ciclo {CICLO_NUMERO}",
) -> go.Figure:
    """Gráfica de crecimiento semanal vs baseline (semana 1 = 0)."""
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return go.Figure()

    weekly = (
        df.groupby("semana")
        .agg(rendimiento=("rendimiento", "mean"))
        .reset_index()
        .dropna(subset=["semana"])
    )
    weekly["semana"] = weekly["semana"].astype(int)
    weekly = weekly.sort_values("semana")
    weekly["crecimiento"] = weekly["rendimiento"] - 100

    y_min = weekly["crecimiento"].min()
    y_max = weekly["crecimiento"].max()
    y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 5
    y_bottom = 0 if y_min >= 0 else y_min - y_padding

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=weekly["semana"],
            y=weekly["crecimiento"],
            mode="lines+markers",
            name="Crecimiento",
            line={"color": "#e56d88", "width": 2.5},
            marker={"size": 8, "color": "#e56d88"},
            hovertemplate=("Semana %{x}<br>Crecimiento: %{y:.1f}%<extra></extra>"),
        )
    )

    fig.update_layout(
        title={"text": title, "font": {"color": "white", "size": 14}},
        xaxis={
            "title": "Semana",
            "tickmode": "array",
            "tickvals": weekly["semana"],
            "ticktext": [str(n) for n in weekly["semana"]],
            "tickfont": {"size": 10, "color": "#a3a3a3"},
            "showgrid": False,
        },
        yaxis={
            "title": "Crecimiento (%)",
            "range": [y_bottom, y_max + y_padding],
            "showgrid": False,
            "zerolinecolor": "#333",
            "tickfont": {"color": "#a3a3a3"},
        },
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "#a3a3a3"},
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "#1a1a1a",
            "font": {"color": "white", "size": 12},
            "bordercolor": "#333",
        },
    )

    return fig


def get_exercise_session_summary(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Resumen por sesión: total sets, tonelaje, kg y reps promedio."""
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, kg, reps, rir
            FROM training_sets
            WHERE ejercicio = ? AND kg IS NOT NULL AND reps IS NOT NULL
            ORDER BY semana, fecha, set_orden
        """,
            conn,
            params=[ejercicio],
        )

    if df.empty:
        return df

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    df["tonelaje"] = df["kg"] * df["reps"]
    df["rm_ajustado"] = (
        df["kg"] * (1 + RM_FACTOR * (df["reps"] + (1 + df["rir"].fillna(0))))
    ).round(1)

    session_df = (
        df.groupby(["semana", "sesion", "fecha", "dia"])
        .agg(
            total_sets=("set_orden", "count"),
            total_tonelaje=("tonelaje", "sum"),
            avg_kg=("kg", "mean"),
            avg_reps=("reps", "mean"),
            avg_rm_ajustado=("rm_ajustado", "mean"),
        )
        .reset_index()
    )

    session_df["avg_kg"] = session_df["avg_kg"].round(1)
    session_df["avg_reps"] = session_df["avg_reps"].round(1)
    session_df["avg_rm_ajustado"] = session_df["avg_rm_ajustado"].round(1)
    session_df["total_tonelaje"] = session_df["total_tonelaje"].round(1)
    session_df = session_df.sort_values(["semana", "sesion"]).reset_index(drop=True)
    return session_df
