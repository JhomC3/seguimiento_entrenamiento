import pandas as pd
import plotly.graph_objects as go

from config import CICLO_NUMERO
from src.analysis_data import daily_sleep_hours, daily_volume, daily_weight
from src.db_connection import read_connection
from src.metrics_engine import RM_FACTOR, calculate_pfr_timeline
from src.training_service import calculate_cycle_week, parse_cycle_start


def _week_series(db_path: str, daily_fn) -> dict[int, float]:
    """Promedio por semana de ciclo de una serie diaria (analysis_data)."""
    df = daily_fn(db_path)
    if df.empty:
        return {}
    ciclo = parse_cycle_start()
    out: dict[int, list[float]] = {}
    for _, r in df.iterrows():
        semana = calculate_cycle_week(r["fecha_dt"].date(), ciclo)
        out.setdefault(semana, []).append(float(r["valor"]))
    return {w: sum(v) / len(v) for w, v in out.items()}


def get_exercise_raw_data(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna datos crudos con RM y RM ajustado calculados."""
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, kg, reps, rir, descanso_seg
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
            "descanso_seg",
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
    """Gráfica de crecimiento semanal vs baseline (semana 1 = 0).

    El hover resume la semana: series, sets al fallo, volumen, peso y sueño
    (los tres últimos desde health_records / diario, vía src.analysis_data).
    """
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return go.Figure()

    volume_w = _week_series(db_path, daily_volume)
    peso_w = _week_series(db_path, daily_weight)
    sueno_w = _week_series(db_path, daily_sleep_hours)

    weekly = (
        df.groupby("semana")
        .agg(
            rendimiento=("rendimiento", "mean"),
            series=("sets_totales", "sum"),
            fallos=("sets_fallo", "sum"),
        )
        .reset_index()
        .dropna(subset=["semana"])
    )
    weekly["semana"] = weekly["semana"].astype(int)
    weekly = weekly.sort_values("semana")
    weekly["crecimiento"] = weekly["rendimiento"] - 100
    weekly["customdata"] = weekly["semana"].apply(
        lambda sem: [
            int(weekly.loc[weekly["semana"] == sem, "series"].iloc[0]),
            int(weekly.loc[weekly["semana"] == sem, "fallos"].iloc[0]),
            f"{volume_w.get(sem, 0):.0f} kg" if volume_w.get(sem) else "—",
            f"{peso_w[sem]:.1f} kg" if peso_w.get(sem) else "—",
            f"{sueno_w[sem]:.1f} h" if sueno_w.get(sem) else "—",
        ]
    )

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
            customdata=weekly["customdata"].tolist(),
            hovertemplate=(
                "Semana %{x}<br>Crecimiento: %{y:.1f}%"
                "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
                "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
                "<extra></extra>"
            ),
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
