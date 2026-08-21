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


def _pfr_df(
    db_path: str, filter_type: str, filter_value: str | None, granularity: str = "week"
) -> pd.DataFrame:
    """DataFrame de rendimiento por periodo con customdata de resumen (series,
    fallos, volumen, peso, sueño) para el hover enriquecido.

    granularity: 'day' | 'week' | 'month'
    """
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return pd.DataFrame()

    volume_all = _week_series(db_path, daily_volume)
    peso_all = _week_series(db_path, daily_weight)
    sueno_all = _week_series(db_path, daily_sleep_hours)

    if granularity == "day":
        # calculate_pfr_timeline devuelve una cronología continua con los días de
        # descanso rellenados (rendimiento ffill, sets_totales=0). Solo mostramos
        # días con entrenamiento real: sin inventar puntos de descanso (req. 2-3).
        result = df[df["sets_totales"] > 0][
            ["fecha_dt", "rendimiento", "sets_totales", "sets_fallo"]
        ].copy()
        result = result.rename(columns={"sets_totales": "series", "sets_fallo": "fallos"})
        result["periodo"] = result["fecha_dt"].dt.strftime("%Y-%m-%d")
        result = result.sort_values("periodo")
        result["crecimiento"] = result["rendimiento"] - 100

        # Volume/peso/sueño por semana de ciclo (fallback diario)
        from src.training_service import calculate_cycle_week, parse_cycle_start

        ciclo = parse_cycle_start()

        def _daily_customdata(row):
            sem = calculate_cycle_week(row["fecha_dt"].date(), ciclo)
            return [
                int(row["series"]),
                int(row["fallos"]),
                f"{volume_all.get(sem, 0):.0f} kg" if volume_all.get(sem) else "—",
                f"{peso_all[sem]:.1f} kg" if peso_all.get(sem) else "—",
                f"{sueno_all[sem]:.1f} h" if sueno_all.get(sem) else "—",
            ]

        result["customdata"] = result.apply(_daily_customdata, axis=1)
        return result

    if granularity == "month":
        df["periodo"] = df["fecha_dt"].dt.to_period("M").astype(str)
        grouped = (
            df.groupby("periodo")
            .agg(
                rendimiento=("rendimiento", "mean"),
                series=("sets_totales", "sum"),
                fallos=("sets_fallo", "sum"),
            )
            .reset_index()
            .sort_values("periodo")
        )
        grouped["crecimiento"] = grouped["rendimiento"] - 100
        grouped["customdata"] = grouped.apply(
            lambda r: [
                int(r["series"]),
                int(r["fallos"]),
                "—",
                "—",
                "—",
            ],
            axis=1,
        )
        return grouped

    # Default: week (comportamiento original)
    volume_w = volume_all
    peso_w = peso_all
    sueno_w = sueno_all
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
    weekly["periodo"] = weekly["semana"].astype(str)
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


# Legacy alias
def _weekly_pfr_df(db_path: str, filter_type: str, filter_value: str | None) -> pd.DataFrame:
    return _pfr_df(db_path, filter_type, filter_value, granularity="week")


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


def _iso_to_full(iso: str) -> str:
    """YYYY-MM-DD → DD/MM/YYYY."""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _compact_day_labels(periods: list[str]) -> list[str]:
    """Etiquetas compactas para gran=day.

    - Mismo mes: DD
    - Primer día de nuevo mes: DD/MM
    - Cambio de año: DD/MM/YY
    El valor interno sigue siendo YYYY-MM-DD; solo cambia ticktext.
    """
    labels: list[str] = []
    prev_y: str | None = None
    prev_m: str | None = None
    for p in periods:
        y, m, d = p.split("-")
        if prev_y is None:
            labels.append(d)
        elif y != prev_y:
            labels.append(f"{d}/{m}/{y[2:]}")
        elif m != prev_m:
            labels.append(f"{d}/{m}")
        else:
            labels.append(d)
        prev_y, prev_m = y, m
    return labels


def _day_tick_subset(periods: list[str], max_ticks: int = 8) -> tuple[list[str], list[str]]:
    """Subconjunto de ticks para no mostrar una etiqueta por punto.

    Usa tickmode array pero con un subconjunto espaciado; mantiene compactas.
    Si hay ≤ max_ticks puntos, muestra todos; si no, muestrea.
    """
    if len(periods) <= max_ticks:
        return periods, _compact_day_labels(periods)
    step = (len(periods) + max_ticks - 1) // max_ticks
    tickvals = periods[::step]
    # Asegurar que el último punto siempre esté etiquetado.
    if tickvals[-1] != periods[-1]:
        tickvals = [*tickvals[:-1], periods[-1]]
    ticktext = _compact_day_labels(tickvals)
    return tickvals, ticktext


def _pfr_trace(
    df: pd.DataFrame,
    name: str,
    color: str,
    *,
    alpha: float = 1.0,
    width: float = 2.5,
    marker_size: int = 3,
    granularity: str = "week",
) -> go.Scatter:
    # Eje X y etiqueta de periodo según granularidad: la serie semanal conserva
    # `semana`; day y month usan `periodo` (fecha/label cronológico real).
    x_col = "semana" if granularity == "week" else "periodo"
    period_label = {"week": "Semana", "day": "Fecha", "month": "Mes"}[granularity]

    line_color = color if alpha >= 1.0 else _hex_to_rgba(color, alpha)
    if granularity == "day":
        hover_vals = df[["series", "fallos"]].assign(
            volumen=df["customdata"].apply(lambda c: c[2]),
            peso=df["customdata"].apply(lambda c: c[3]),
            sueno=df["customdata"].apply(lambda c: c[4]),
            nombre=name,
            fecha_full=df["periodo"].apply(_iso_to_full),
        )
        customdata = hover_vals.values.tolist()
        hovertemplate = (
            "%{customdata[5]}<br>Fecha %{customdata[6]}<br>Crecimiento: %{y:.1f}%"
            "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
            "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
            "<extra></extra>"
        )
    else:
        customdata = (
            df[["series", "fallos"]]
            .assign(
                volumen=df["customdata"].apply(lambda c: c[2]),
                peso=df["customdata"].apply(lambda c: c[3]),
                sueno=df["customdata"].apply(lambda c: c[4]),
                nombre=name,
            )
            .values.tolist()
        )
        hovertemplate = (
            f"%{{customdata[5]}}<br>{period_label} %{{x}}<br>Crecimiento: %{{y:.1f}}%"
            "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
            "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
            "<extra></extra>"
        )
    return go.Scatter(
        x=df[x_col],
        y=df["crecimiento"],
        mode="lines+markers",
        name=name,
        line={"color": line_color, "width": width},
        # Los puntos comparten la transparencia de su línea.
        marker={"size": marker_size, "color": line_color},
        customdata=customdata,
        hovertemplate=hovertemplate,
    )


def chart_selection(
    db_path: str,
    musculos: list[str],
    ejercicios: list[str],
    granularity: str = "week",
) -> go.Figure:
    """Gráfica de la selección actual:

    - 0 músculos: línea sistémica global ("Crecimiento").
    - 1 músculo, 0 ejercicios: Global + nombre del músculo.
    - 1 músculo, N ejercicios válidos: Compilado (guía) + ejercicios.
      (Global se oculta en estado ejercicio — decisión D2.)
    - 2+ músculos: Global + músculos. Los ejercicios no aplican.

    Los ejercicios que no pertenecen al músculo se descartan.
    """
    traces: list[go.Scatter] = []
    title = "Rendimiento – Cuerpo entero"
    # The systemic series provides a stable vertical reference. Selection
    # changes may add traces outside this window, but must never resize or
    # vertically reposition the chart shell.
    reference_df = _pfr_df(db_path, "systemic", None, granularity)

    if len(musculos) == 0:
        # Estado global: línea sistémica (D3).
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(
                    global_df, "Crecimiento", chart_color("primary"), granularity=granularity
                )
            )
    elif len(musculos) == 1:
        musculo = musculos[0]
        title = f"Rendimiento – {musculo}"

        if ejercicios:
            # Estado ejercicio: Compilado guía + ejercicios (sin global — D2).
            compiled = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if not compiled.empty:
                traces.append(
                    _pfr_trace(
                        compiled, "Compilado", chart_color("primary"), granularity=granularity
                    )
                )

            with read_connection(db_path) as conn:
                rows = conn.execute(
                    "SELECT ejercicio FROM ejercicios WHERE LOWER(grupo_muscular) = LOWER(?)",
                    (musculo,),
                ).fetchall()
            valid = {str(r[0]).lower() for r in rows}
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
                    )
                )
        else:
            # Estado muscular: misma jerarquía que 2+ músculos:
            # Global sólido + músculo identificado y translúcido.
            global_df = _pfr_df(db_path, "systemic", None, granularity)
            if not global_df.empty:
                traces.append(
                    _pfr_trace(global_df, "Global", chart_color("primary"), granularity=granularity)
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
                    )
                )
    elif len(musculos) >= 2:
        global_df = _pfr_df(db_path, "systemic", None, granularity)
        if not global_df.empty:
            traces.append(
                _pfr_trace(global_df, "Global", chart_color("primary"), granularity=granularity)
            )
        for idx, musculo in enumerate(musculos):
            df = _pfr_df(db_path, "muscle_group", musculo, granularity)
            if df.empty:
                continue
            color = EXERCISE_PALETTE[idx % len(EXERCISE_PALETTE)]
            traces.append(
                _pfr_trace(
                    df, musculo, color, alpha=0.4, width=3.5, marker_size=3, granularity=granularity
                )
            )

    if not traces:
        return go.Figure()

    fig = go.Figure()
    for t in traces:
        fig.add_trace(t)

    all_y = [v for t in traces for v in t.y if v is not None]
    reference_y = [v for v in reference_df["crecimiento"] if v is not None]
    scale_y = reference_y or all_y
    y_min = min(scale_y) if scale_y else 0
    y_max = max(scale_y) if scale_y else 0
    y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 5
    y_bottom = 0 if y_min >= 0 else y_min - y_padding

    # Eje X: tickmode array con subconjunto para no apiñar (day: máx 8 etiquetas)
    all_x = [v for t in traces for v in t.x]
    x_title = {"week": "Semana", "day": "Fecha", "month": "Mes"}[granularity]
    if granularity == "day":
        all_periods = sorted({str(v) for v in all_x})
        tickvals, ticktext = _day_tick_subset(all_periods, max_ticks=8)
    elif all_x and isinstance(all_x[0], int):
        tickvals = sorted(set(all_x))
        ticktext = [str(v) for v in tickvals]
    else:
        tickvals = sorted({str(v) for v in all_x})
        ticktext = [str(v) for v in tickvals]

    xaxis_cfg: dict = {
        "title": x_title,
        "tickmode": "array",
        "tickvals": tickvals,
        "ticktext": ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    if granularity == "day":
        xaxis_cfg["type"] = "date"

    fig.update_layout(
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
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
        height=450,
        # Reserve a fixed top band for the horizontal legend so adding or
        # removing traces never changes the chart shell or plot width.
        margin={"l": 60, "r": 20, "t": 76, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        # La leyenda SIEMPRE visible (también con 1 traza): vive en la banda
        # superior reservada, así que el área de trazado no cambia de tamaño
        # al pasar de modo global a selección y viceversa.
        showlegend=True,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.22,
            "xanchor": "left",
            "yanchor": "bottom",
            "entrywidth": 100,
            "entrywidthmode": "pixels",
            "font": {"color": chart_color("axes"), "size": 11},
            "bgcolor": chart_color("background"),
        },
        dragmode="pan",
    )
    return fig


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

    y_min = periodic["crecimiento"].min()
    y_max = periodic["crecimiento"].max()
    y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 5
    y_bottom = 0 if y_min >= 0 else y_min - y_padding

    # Eje X
    x_col = "periodo" if "periodo" in periodic.columns else "semana"
    x_title = {"week": "Semana", "day": "Fecha", "month": "Mes"}[granularity]

    fig = go.Figure()

    if granularity == "day":
        periods = [str(v) for v in periodic[x_col].tolist()]
        tickvals, ticktext = _day_tick_subset(periods, max_ticks=8)
        # Tooltip con fecha completa DD/MM/YYYY
        cd_full = periodic.apply(
            lambda r: [*r["customdata"], _iso_to_full(str(r["periodo"]))], axis=1
        ).tolist()
        hover = (
            "Fecha %{customdata[5]}<br>Crecimiento: %{y:.1f}%"
            "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
            "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
            "<extra></extra>"
        )
        customdata_vals = cd_full
        x_tickvals = tickvals
        x_ticktext = ticktext
    else:
        ticktext = [str(v) for v in periodic[x_col]]
        hover = (
            f"{x_title} %{{x}}<br>Crecimiento: %{{y:.1f}}%"
            "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
            "<br>Volumen: %{customdata[2]} · Peso: %{customdata[3]} · Sueño: %{customdata[4]}"
            "<extra></extra>"
        )
        customdata_vals = periodic["customdata"].tolist()
        x_tickvals = periodic[x_col].tolist()
        x_ticktext = ticktext

    fig.add_trace(
        go.Scatter(
            x=periodic[x_col],
            y=periodic["crecimiento"],
            mode="lines+markers",
            name="Crecimiento",
            line={"color": chart_color("primary"), "width": 2.5},
            marker={"size": 8, "color": chart_color("primary")},
            customdata=customdata_vals,
            hovertemplate=hover,
        )
    )

    xaxis_cfg: dict = {
        "title": x_title,
        "tickmode": "array",
        "tickvals": x_tickvals,
        "ticktext": x_ticktext,
        "tickfont": {"size": 10, "color": chart_color("axes")},
        "showgrid": False,
    }
    if granularity == "day":
        xaxis_cfg["type"] = "date"

    fig.update_layout(
        title={"text": title, "font": {"color": chart_color("hover.text"), "size": 14}},
        xaxis=xaxis_cfg,
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
        height=450,
        margin={"l": 60, "r": 20, "t": 76, "b": 50},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": chart_color("hover.bg"),
            "font": {"color": chart_color("hover.text"), "size": 12},
            "bordercolor": chart_color("grid"),
        },
        # La leyenda SIEMPRE visible (también con 1 traza): vive en la banda
        # superior reservada, así que el área de trazado no cambia de tamaño
        # al pasar de modo global a selección y viceversa.
        showlegend=True,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.22,
            "xanchor": "left",
            "yanchor": "bottom",
            "entrywidth": 100,
            "entrywidthmode": "pixels",
            "font": {"color": chart_color("axes"), "size": 11},
            "bgcolor": chart_color("background"),
        },
        dragmode="pan",
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


def period_summary(
    db_path: str,
    filter_type: str,
    filter_value: str | None,
    granularity: str = "week",
) -> dict:
    """Resumen de métricas del periodo: series, reps, peso, RM, rendimiento,
    delta RM vs último rendimiento. Todo server-side."""
    pfr = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if pfr.empty:
        return {"empty": True}

    # Agregar por periodo según granularidad
    if granularity == "day":
        pfr["periodo"] = pfr["fecha_dt"].dt.strftime("%Y-%m-%d")
    elif granularity == "month":
        pfr["periodo"] = pfr["fecha_dt"].dt.to_period("M").astype(str)
    else:
        pfr["periodo"] = pfr["semana"].astype(int).astype(str)

    grouped = (
        pfr.groupby("periodo")
        .agg(
            rendimiento=("rendimiento", "mean"),
            series=("sets_totales", "sum"),
        )
        .reset_index()
        .sort_values("periodo")
    )

    # RM promedio por periodo desde training_sets
    with read_connection(db_path) as conn:
        if filter_type == "muscle_group" and filter_value:
            rm_df = pd.read_sql_query(
                "SELECT fecha, reps, kg, rir, ejercicio FROM training_sets "
                "WHERE ejercicio IN (SELECT ejercicio FROM ejercicios "
                "WHERE LOWER(grupo_muscular) = LOWER(?))",
                conn,
                params=(filter_value,),
            )
        elif filter_type == "exercise" and filter_value:
            rm_df = pd.read_sql_query(
                "SELECT fecha, reps, kg, rir FROM training_sets WHERE LOWER(ejercicio) = LOWER(?)",
                conn,
                params=(filter_value,),
            )
        else:
            rm_df = pd.read_sql_query("SELECT fecha, reps, kg, rir FROM training_sets", conn)

    if not rm_df.empty:
        rm_df["fecha_dt"] = pd.to_datetime(rm_df["fecha"], errors="coerce")
        rm_df = rm_df.dropna(subset=["fecha_dt"])
        rir_safe = rm_df["rir"].fillna(0.0)
        rm_df["rm_ajustado"] = rm_df["kg"] * (1 + RM_FACTOR * (rm_df["reps"] + 1 + rir_safe))
        rm_df["reps_sum"] = rm_df["reps"]

        if granularity == "day":
            rm_df["periodo"] = rm_df["fecha_dt"].dt.strftime("%Y-%m-%d")
        elif granularity == "month":
            rm_df["periodo"] = rm_df["fecha_dt"].dt.to_period("M").astype(str)
        else:
            ciclo = parse_cycle_start()
            rm_df["periodo"] = rm_df["fecha_dt"].apply(
                lambda d: str(calculate_cycle_week(d.date(), ciclo))
            )

        rm_grouped = (
            rm_df.groupby("periodo")
            .agg(
                rm_avg=("rm_ajustado", "mean"),
                reps_total=("reps_sum", "sum"),
                peso_avg=("kg", "mean"),
            )
            .reset_index()
        )
    else:
        rm_grouped = pd.DataFrame(columns=["periodo", "rm_avg", "reps_total", "peso_avg"])

    merged = grouped.merge(rm_grouped, on="periodo", how="left")

    # Delta RM: comparar con el periodo anterior con datos
    rm_values = merged["rm_avg"].dropna().tolist()
    current_rm = rm_values[-1] if rm_values else None
    prev_rm = rm_values[-2] if len(rm_values) >= 2 else None
    delta_rm = (
        round(current_rm - prev_rm, 1) if (current_rm is not None and prev_rm is not None) else None
    )

    last = merged.iloc[-1] if not merged.empty else None

    return {
        "empty": False,
        "periodo": str(last["periodo"]) if last is not None else "—",
        "series": int(last["series"]) if last is not None else 0,
        "reps": int(last["reps_total"])
        if last is not None and pd.notna(last.get("reps_total"))
        else 0,
        "peso": round(float(last["peso_avg"]), 1)
        if last is not None and pd.notna(last.get("peso_avg"))
        else None,
        "rm": round(float(last["rm_avg"]), 1)
        if last is not None and pd.notna(last.get("rm_avg"))
        else None,
        "rendimiento": round(float(last["rendimiento"]), 1) if last is not None else None,
        "delta_rm": delta_rm,
    }
