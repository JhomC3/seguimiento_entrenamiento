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


def _weekly_pfr_df(db_path: str, filter_type: str, filter_value: str | None) -> pd.DataFrame:
    """DataFrame semanal de rendimiento con customdata de resumen (series,
    fallos, volumen, peso, sueño) para el hover enriquecido."""
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return pd.DataFrame()

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
    return weekly


HOVER_TEMPLATE = (
    "%{customdata[5]}<br>Semana %{x}<br>Crecimiento: %{y:.1f}%"
    "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
    "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
    "<extra></extra>"
)

# Paleta para trazas por ejercicio (sobre el tema oscuro del proyecto)
EXERCISE_PALETTE = [
    "#7dd3fc",
    "#a3e635",
    "#c084fc",
    "#fbbf24",
    "#34d399",
    "#60a5fa",
    "#f472b6",
]


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _pfr_trace(
    weekly: pd.DataFrame,
    name: str,
    color: str,
    *,
    alpha: float = 1.0,
    width: float = 2.5,
    marker_size: int = 7,
) -> go.Scatter:
    line_color = color if alpha >= 1.0 else _hex_to_rgba(color, alpha)
    return go.Scatter(
        x=weekly["semana"],
        y=weekly["crecimiento"],
        mode="lines+markers",
        name=name,
        line={"color": line_color, "width": width},
        marker={"size": marker_size, "color": line_color},
        customdata=weekly[["series", "fallos"]]
        .assign(
            volumen=weekly["customdata"].apply(lambda c: c[2]),
            peso=weekly["customdata"].apply(lambda c: c[3]),
            sueno=weekly["customdata"].apply(lambda c: c[4]),
            nombre=name,
        )
        .values.tolist(),
        hovertemplate=HOVER_TEMPLATE,
    )


def chart_muscle_exercises(db_path: str, musculo: str, ejercicios: list[str]) -> go.Figure:
    """Gráfica del músculo: línea del compilado (todos sus ejercicios) siempre
    visible + una línea por cada ejercicio seleccionado.

    Los ejercicios que no pertenecen al músculo se descartan.
    """
    compiled = _weekly_pfr_df(db_path, "muscle_group", musculo)
    traces: list[go.Scatter] = []
    if not compiled.empty:
        # El compilado es la línea de referencia: sólida y protagonista.
        traces.append(_pfr_trace(compiled, "Compilado", "#e56d88"))

    if musculo and ejercicios:
        with read_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                (musculo,),
            ).fetchall()
        valid = {str(r[0]).lower() for r in rows}
        for idx, ejercicio in enumerate(ejercicios):
            if ejercicio.lower() not in valid:
                continue
            df = _weekly_pfr_df(db_path, "exercise", ejercicio)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            # Los ejercicios individuales van más tenues que el compilado.
            traces.append(_pfr_trace(df, ejercicio, color, alpha=0.55, width=1.5, marker_size=5))

    if not traces:
        return go.Figure()

    fig = go.Figure()
    for t in traces:
        fig.add_trace(t)

    all_y = [v for t in traces for v in t.y if v is not None]
    y_min = min(all_y) if all_y else 0
    y_max = max(all_y) if all_y else 0
    y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 5
    y_bottom = 0 if y_min >= 0 else y_min - y_padding

    fig.update_layout(
        title={"text": f"Rendimiento – {musculo}", "font": {"color": "white", "size": 14}},
        xaxis={
            "title": "Semana",
            "tickmode": "array",
            "tickvals": sorted({int(v) for t in traces for v in t.x}),
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
        legend={
            "font": {"color": "#a3a3a3", "size": 11},
            "bgcolor": "rgba(0,0,0,0)",
        },
    )
    return fig


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
    weekly = _weekly_pfr_df(db_path, filter_type, filter_value)
    if weekly.empty:
        return go.Figure()

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
