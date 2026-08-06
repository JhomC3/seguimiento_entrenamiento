import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.db_connection import read_connection
from src.metrics_engine import calculate_pfr_timeline


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

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%y", errors="coerce")
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    df["serie"] = df.groupby(["semana", "sesion"]).cumcount() + 1

    rir_safe = df["rir"].fillna(0)
    df["rm"] = (df["kg"] * (1 + 0.0333 * df["reps"])).round(1)
    df["rm_ajustado"] = (df["kg"] * (1 + 0.0333 * (df["reps"] + (1 + rir_safe)))).round(1)

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
    title: str = "Rendimiento Semanal",
) -> go.Figure:
    """Gráfica de rendimiento semanal promedio. 100% = Semana 1."""
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

    y_min = weekly["rendimiento"].min()
    y_max = weekly["rendimiento"].max()
    y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 5

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=weekly["semana"],
            y=weekly["rendimiento"],
            mode="lines+markers",
            name="Rendimiento",
            line={"color": "#e56d88", "width": 2.5},
            marker={"size": 8, "color": "#e56d88"},
            hovertemplate=(
                "Semana %{x}<br>Promedio: %{y:.1f}%<br>(Semana 1 = 100%)<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title={"text": title, "font": {"color": "white", "size": 14}},
        xaxis={
            "title": "Semana",
            "dtick": 1,
            "tickfont": {"size": 10, "color": "#a3a3a3"},
            "showgrid": False,
        },
        yaxis={
            "title": "Rendimiento (%)",
            "range": [y_min - y_padding, y_max + y_padding],
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


def chart_rm_progression(db_path: str, ejercicio: str) -> go.Figure:
    """Gráfico: progresión del ejercicio redirigido al nuevo modelo de timeline PFR."""
    return chart_pfr_timeline(db_path, "exercise", ejercicio, f"Progreso Fisiológico – {ejercicio}")


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

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%y", errors="coerce")
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    df["tonelaje"] = df["kg"] * df["reps"]
    df["rm_ajustado"] = (df["kg"] * (1 + 0.0333 * (df["reps"] + (1 + df["rir"].fillna(0))))).round(
        1
    )

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


def chart_tonnage_per_session(db_path: str, ejercicio: str) -> go.Figure:
    """Gráfico de barras: tonelaje total por sesión."""
    df = get_exercise_session_summary(db_path, ejercicio)
    if df.empty:
        return go.Figure()

    x_labels = [f"Sem {int(r['semana'])}-S{int(r['sesion'])}" for _, r in df.iterrows()]
    week_positions = [v[0] for _, v in sorted(df.groupby("semana").indices.items())]
    week_labels_at = [x_labels[p] for p in week_positions]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=list(range(len(df))),
            y=df["total_tonelaje"],
            name="Tonelaje (kg)",
            marker={"color": "#e56d88", "opacity": 0.85},
            hovertemplate=(
                "<b>%{customdata[0]} - %{customdata[1]}</b><br>"
                "Tonelaje: %{y:.1f} kg<br>"
                "Series: %{customdata[2]}<br>"
                "Kg prom: %{customdata[3]:.1f}<extra></extra>"
            ),
            customdata=df[["fecha", "dia", "total_sets", "avg_kg"]].values,
        )
    )

    fig.update_layout(
        title={
            "text": f"Tonelaje por Sesión – {ejercicio}",
            "font": {"color": "white", "size": 14},
        },
        xaxis={
            "tickvals": week_positions,
            "ticktext": week_labels_at,
            "tickfont": {"size": 10, "color": "#a3a3a3"},
            "gridcolor": "#222",
            "showgrid": False,
        },
        yaxis={
            "title": "Tonelaje (kg)",
            "gridcolor": "#222",
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


def get_exercise_detail(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna todas las series individuales con peso, reps, RM y RIR calculados."""
    with read_connection(db_path) as conn:
        # 1. Obtener todas las series individuales
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, kg, reps, rir,
                   ROUND(kg * (1 + 0.0333 * reps), 1) as rm
            FROM training_sets
            WHERE ejercicio = ? AND kg IS NOT NULL
            ORDER BY semana, fecha, set_orden
        """,
            conn,
            params=[ejercicio],
        )

        # 2. Obtener el orden del ejercicio en cada sesión
        df_orden = pd.read_sql_query(
            """
            WITH ejercicio_orden AS (
                SELECT semana, dia, fecha, ejercicio,
                       MIN(set_orden) as primer_set
                FROM training_sets
                WHERE kg IS NOT NULL
                GROUP BY semana, dia, fecha, ejercicio
            )
            SELECT semana, dia, fecha,
                   RANK() OVER (PARTITION BY semana, dia ORDER BY primer_set) as orden_en_sesion
            FROM ejercicio_orden
            WHERE ejercicio = ?
            ORDER BY semana, fecha
        """,
            conn,
            params=[ejercicio],
        )

    if df.empty:
        return df

    # Intentar parsear fechas reales
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%y", errors="coerce")

    # Si hay fechas nulas por error de formato, ordenamos por semana y dia
    # Pero asumimos formato d/m/yy estable.

    # Calcular el número de sesión dentro de la semana (1, 2, 3...)
    # Para la misma semana, agrupamos por fecha_dt y les asignamos rango denso
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )

    # Calcular serie local (1, 2, 3...) dentro de esa sesión para el ejercicio
    df["serie"] = df.groupby(["semana", "sesion"]).cumcount() + 1

    # Obtener el día de la semana traducido o nativo
    # Como la DB ya tiene "dia" (LUNES, MARTES, etc.), podemos usar ese campo
    # o calcularlo desde fecha_dt. Usemos el de la DB por consistencia o fecha_dt.dt.day_name()
    # Traducimos a español los nombres de días si los calculamos
    dias_es = {
        "Monday": "Lunes",
        "Tuesday": "Martes",
        "Wednesday": "Miércoles",
        "Thursday": "Jueves",
        "Friday": "Viernes",
        "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    df["dia_semana"] = df["fecha_dt"].dt.strftime("%A").map(dias_es).fillna(df["dia"])

    # Merge con orden_en_sesion
    df = df.merge(df_orden[["semana", "dia", "orden_en_sesion"]], on=["semana", "dia"], how="left")

    return df


def get_exercise_best_rm(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna el mejor RM por sesión para graficar la progresión real."""
    with read_connection(db_path) as conn:
        # Agrupamos por semana y fecha para tener sesiones únicas reales cronológicas
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha,
                   MAX(ROUND(kg * (1 + 0.0333 * reps), 1)) as mejor_rm,
                   COUNT(*) as total_series
            FROM training_sets
            WHERE ejercicio = ? AND kg IS NOT NULL
            GROUP BY semana, dia, fecha
            ORDER BY semana, fecha
        """,
            conn,
            params=[ejercicio],
        )

    if df.empty:
        return df

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%y", errors="coerce")
    df = df.sort_values("fecha_dt").reset_index(drop=True)
    return df


def chart_exercise_rm(db_path: str, ejercicio: str) -> go.Figure:
    """Gráfico de línea: progresión del mejor RM por sesión."""
    df = get_exercise_best_rm(db_path, ejercicio)
    if df.empty:
        # Retorna figura vacía
        return go.Figure()

    # Crear etiquetas del eje X combinando semana y sesión dentro de esa semana
    df["sesion"] = df.groupby("semana")["fecha_dt"].rank(method="dense").astype(int)
    df["label"] = df.apply(lambda r: f"Sem{int(r['semana'])}-S{int(r['sesion'])}", axis=1)

    dias_es = {
        "Monday": "Lun",
        "Tuesday": "Mar",
        "Wednesday": "Mie",
        "Thursday": "Jue",
        "Friday": "Vie",
        "Saturday": "Sab",
        "Sunday": "Dom",
    }
    df["dia_nom"] = df["fecha_dt"].dt.strftime("%A").map(dias_es).fillna(df["dia"])
    df["hover_info"] = df.apply(
        lambda r: (
            f"Fecha: {r['dia_nom']} {r['fecha']}<br>Series: {int(r['total_series'])}<br>Mejor RM: {r['mejor_rm']} kg"
        ),
        axis=1,
    )

    fig = px.line(
        df,
        x="label",
        y="mejor_rm",
        title=f"Progresión del Mejor RM: {ejercicio}",
        labels={"mejor_rm": "Mejor RM (Kg)", "label": "Sesión (Semana-Sesión)"},
        markers=True,
        hover_name="hover_info",
    )
    fig.update_traces(hovertemplate="%{hover_name}<extra></extra>")
    fig.update_layout(hovermode="x unified")
    return fig


def pivot_exercise_table(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Tabla vertical: Sesión (Fila) × Serie (Columna), con información detallada."""
    df = get_exercise_detail(db_path, ejercicio)
    if df.empty:
        return pd.DataFrame()

    # 1. Crear identificadores de sesión
    df["col_sesion"] = df.apply(lambda r: f"Sem {int(r['semana'])} - S{int(r['sesion'])}", axis=1)

    # 2. Formato de celda de serie: "85.0 kg × 6 | RM: 102.0 | RIR: 1"
    def format_celda(r):
        rir_str = f"{r['rir']:.1f}" if pd.notna(r["rir"]) else "—"
        return f"{r['kg']:.1f} kg × {int(r['reps'])} | RM: {r['rm']:.1f} | RIR: {rir_str}"

    df["celda"] = df.apply(format_celda, axis=1)

    # 3. Pivotar para tener las series como columnas (Serie 1, Serie 2, etc.)
    # El índice será la sesión (col_sesion)
    pivot_series = df.pivot(index="col_sesion", columns="serie", values="celda")

    # Renombrar columnas de series a "Serie 1", "Serie 2", etc.
    pivot_series.columns = [f"Serie {int(c)}" for c in pivot_series.columns]

    # 4. Obtener información de sesión única para combinar
    # Agrupamos para obtener fecha, fecha_dt, dia_semana, orden_en_sesion por sesión
    df_sessions = (
        df.groupby("col_sesion")
        .agg(
            {
                "semana": "first",
                "sesion": "first",
                "fecha": "first",
                "fecha_dt": "first",
                "dia_semana": "first",
                "orden_en_sesion": "first",
            }
        )
        .reset_index()
    )

    # Asegurar orden cronológico de las sesiones
    df_sessions = df_sessions.sort_values(["semana", "sesion"]).reset_index(drop=True)

    # Formatear campos para mostrar
    df_sessions["Fecha"] = df_sessions.apply(lambda r: f"{r['dia_semana']} {r['fecha']}", axis=1)
    df_sessions["Orden"] = df_sessions["orden_en_sesion"].apply(
        lambda o: f"#{int(o)}" if pd.notna(o) else "—"
    )
    df_sessions.rename(columns={"col_sesion": "Sesión"}, inplace=True)

    # Combinar metadatos de sesión con las columnas de series
    result = df_sessions[["Sesión", "Fecha", "Orden"]].merge(
        pivot_series, left_on="Sesión", right_index=True, how="left"
    )

    # Rellenar nulos en las series con "—" para una tabla limpia
    series_cols = [c for c in result.columns if c.startswith("Serie ")]
    result[series_cols] = result[series_cols].fillna("—")

    # Establecer la columna Sesión como índice para que se vea genial
    result.set_index("Sesión", inplace=True)

    return result


def get_muscle_group_volume(db_path: str, grupo: str) -> pd.DataFrame:
    """Retorna volumen total (series) por semana para un grupo muscular."""
    with read_connection(db_path) as conn:
        query = """
            SELECT t.semana, COUNT(*) as total_series, 
                   SUM(t.reps) as total_reps,
                   AVG(t.kg) as kg_promedio
            FROM training_sets t
            JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio)
            WHERE LOWER(e.grupo_muscular) = LOWER(?) AND t.kg IS NOT NULL
            GROUP BY t.semana
            ORDER BY t.semana
        """
        df = pd.read_sql_query(query, conn, params=[grupo])
    return df


def chart_muscle_group_volume(db_path: str, grupo: str) -> go.Figure:
    """Gráfico de barras: volumen semanal por grupo muscular."""
    df = get_muscle_group_volume(db_path, grupo)
    fig = px.bar(
        df,
        x="semana",
        y="total_series",
        title=f"Volumen semanal (Series): {grupo}",
        labels={"total_series": "Series totales", "semana": "Semana"},
    )
    return fig


def chart_muscle_group_kg(db_path: str, grupo: str) -> go.Figure:
    """Gráfico de línea: kg promedio por semana para un grupo muscular."""
    df = get_muscle_group_volume(db_path, grupo)
    fig = px.line(
        df,
        x="semana",
        y="kg_promedio",
        title=f"Progresión de carga promedio del grupo: {grupo}",
        labels={"kg_promedio": "Kg promedio", "semana": "Semana"},
        markers=True,
    )
    fig.update_layout(hovermode="x unified")
    return fig
