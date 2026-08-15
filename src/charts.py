import pandas as pd
import plotly.graph_objects as go

from config import CICLO_NUMERO
from src.analysis_data import daily_sleep_hours, daily_volume, daily_weight
from src.db_connection import read_connection
from src.design_tokens import color, palette
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

# Paleta para trazas por ejercicio (canonical: static/design-tokens.json)
EXERCISE_PALETTE = palette("chart.exercise")


def chart_color(path: str) -> str:
    """Color de gráfica desde los tokens canónicos ("chart.axes", "primary", ...)."""
    if path == "primary":
        path = "chart.primary"
    elif not path.startswith("chart."):
        path = f"chart.{path}"
    return color(path)


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
        # Los puntos comparten la transparencia de su línea.
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


def chart_selection(db_path: str, musculos: list[str], ejercicios: list[str]) -> go.Figure:
    """Gráfica de la selección actual:

    - 1 músculo: línea del compilado (todos sus ejercicios) sólida como
      referencia + una línea tenue por cada ejercicio seleccionado.
    - 2+ músculos: línea del GLOBAL (cuerpo entero) sólida como referencia +
      una línea tenue por cada músculo seleccionado. Los ejercicios no aplican.

    Los ejercicios que no pertenecen al músculo se descartan.
    """
    traces: list[go.Scatter] = []
    title = "Rendimiento – Cuerpo entero"

    if len(musculos) == 1:
        musculo = musculos[0]
        title = f"Rendimiento – {musculo}"
        compiled = _weekly_pfr_df(db_path, "muscle_group", musculo)
        if not compiled.empty:
            # El compilado es la línea de referencia: sólida y protagonista.
            traces.append(_pfr_trace(compiled, "Compilado", chart_color("primary")))

        if ejercicios:
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
                # Ejercicios individuales: línea translúcida y gruesa (3.5);
                # los puntos llevan la misma transparencia que la línea.
                traces.append(_pfr_trace(df, ejercicio, color, alpha=0.4, width=3.5, marker_size=6))
    elif len(musculos) >= 2:
        global_df = _weekly_pfr_df(db_path, "systemic", None)
        if not global_df.empty:
            # El global (cuerpo entero) es la línea de referencia sólida.
            traces.append(_pfr_trace(global_df, "Global", chart_color("primary")))
        for idx, musculo in enumerate(musculos):
            df = _weekly_pfr_df(db_path, "muscle_group", musculo)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            # Músculos seleccionados: líneas tenues como los ejercicios.
            traces.append(_pfr_trace(df, musculo, color, alpha=0.4, width=3.5, marker_size=6))

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
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis={
            "title": "Semana",
            "tickmode": "array",
            "tickvals": sorted({int(v) for t in traces for v in t.x}),
            "tickfont": {"size": 10, "color": chart_color("axes")},
            "showgrid": False,
        },
        yaxis={
            "title": "Crecimiento (%)",
            "range": [y_bottom, y_max + y_padding],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        legend={
            "font": {"color": chart_color("axes"), "size": 11},
            "bgcolor": chart_color("background"),
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
            line={"color": chart_color("primary"), "width": 2.5},
            marker={"size": 8, "color": chart_color("primary")},
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
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis={
            "title": "Semana",
            "tickmode": "array",
            "tickvals": weekly["semana"],
            "ticktext": [str(n) for n in weekly["semana"]],
            "tickfont": {"size": 10, "color": chart_color("axes")},
            "showgrid": False,
        },
        yaxis={
            "title": "Crecimiento (%)",
            "range": [y_bottom, y_max + y_padding],
            "showgrid": False,
            "zerolinecolor": chart_color("grid"),
            "tickfont": {"color": chart_color("axes")},
        },
        plot_bgcolor=chart_color("background"),
        paper_bgcolor=chart_color("background"),
        font={"color": chart_color("axes")},
        margin={"l": 60, "r": 20, "t": 50, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
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
