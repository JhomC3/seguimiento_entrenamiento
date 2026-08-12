import pandas as pd

from src.db_connection import read_connection

RM_FACTOR = 0.0333


def rm_ajustado(kg: float, reps: float, rir: float = 0.0) -> float:
    """RM ajustado: kg * (1 + 0.0333 * (reps + 1 + rir))."""
    return kg * (1 + RM_FACTOR * (reps + 1 + rir))


def is_failure_set(reps: float, rir: float | None) -> bool:
    """True si la serie llegó al fallo (RIR <= 0) o tuvo rep parcial (reps decimal)."""
    return (rir is not None and rir <= 0) or (reps % 1 != 0)


# Palabras clave para identificar ejercicios compuestos (multiarticulares)
COMPOUND_KEYWORDS = {
    "hack",
    "jalon",
    "pm rigidas",
    "prensa",
    "convergente",
    "mancuernas",
    "militar",
    "remo",
    "sentadilla",
    "vertical",
}


def is_compound(exercise_name: str) -> bool:
    """Retorna True si el ejercicio es multiarticular/compuesto."""
    name_lower = exercise_name.lower()
    return any(kw in name_lower for kw in COMPOUND_KEYWORDS)


def get_exercises_baselines(db_path: str) -> dict[str, float]:
    """
    Calcula el RM_a base de cada ejercicio (promedio de la semana 1).
    Si un ejercicio no se realizó en la semana 1, se toma la primera semana disponible.
    """
    with read_connection(db_path) as conn:
        query = """
            SELECT ejercicio, semana, kg, reps, rir
            FROM training_sets
            WHERE kg IS NOT NULL AND reps IS NOT NULL
            ORDER BY semana
        """
        df = pd.read_sql_query(query, conn)

    baselines: dict[str, float] = {}
    if df.empty:
        return baselines

    # Calcular RM_a de cada set
    rir_safe = df["rir"].fillna(0)
    df["rm_ajustado"] = df["kg"] * (1 + RM_FACTOR * (df["reps"] + 1 + rir_safe))

    # Para cada ejercicio, encontrar su primera semana disponible y promediar
    for exercise, group in df.groupby("ejercicio"):
        first_week = group["semana"].min()
        first_week_sets = group[group["semana"] == first_week]
        baselines[str(exercise)] = round(first_week_sets["rm_ajustado"].mean(), 1)

    return baselines


def calculate_pfr_timeline(
    db_path: str, filter_type: str = "systemic", filter_value: str | None = None
) -> pd.DataFrame:
    """
    Calcula la serie temporal diaria de Rendimiento (PI), Fatiga Acumulada (FI) y Recuperación (RI).
    - filter_type: 'systemic' (todo el cuerpo), 'muscle_group', 'exercise'
    - filter_value: el nombre del grupo muscular o ejercicio correspondiente
    """
    with read_connection(db_path) as conn:
        # 1. Obtener todos los sets de entrenamiento con el grupo muscular correspondiente
        query = """
            SELECT t.semana, t.dia, t.fecha, t.set_orden, t.ejercicio, t.kg, t.reps, t.rir, e.grupo_muscular
            FROM training_sets t
            JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio)
            WHERE t.kg IS NOT NULL AND t.reps IS NOT NULL
        """
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return pd.DataFrame()

    # Obtener baselines para calcular rendimiento relativo %
    baselines = get_exercises_baselines(db_path)

    # Parsear fechas reales y ordenar de forma cronológica
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    df = df.dropna(subset=["fecha_dt"]).sort_values("fecha_dt").reset_index(drop=True)

    if df.empty:
        return pd.DataFrame()

    # Calcular RM_a individual de cada set
    rir_safe = df["rir"].fillna(0)
    df["rm_ajustado"] = df["kg"] * (1 + RM_FACTOR * (df["reps"] + 1 + rir_safe))

    # Calcular Rendimiento Relativo (%) respecto al baseline
    df["perf_rel"] = df.apply(
        lambda r: (
            (r["rm_ajustado"] / baselines[r["ejercicio"]] * 100)
            if r["ejercicio"] in baselines
            else 100.0
        ),
        axis=1,
    )
    df["es_fallo"] = df.apply(
        lambda r: int(is_failure_set(float(r["reps"]), r["rir"])), axis=1
    )

    # --- FILTRADO DE DATOS SEGÚN NIVEL ---
    if filter_type == "muscle_group" and filter_value:
        df_filtered = df[df["grupo_muscular"].str.lower() == filter_value.lower()].copy()
    elif filter_type == "exercise" and filter_value:
        df_filtered = df[df["ejercicio"].str.lower() == filter_value.lower()].copy()
    else:
        df_filtered = df.copy()  # systemic (todo el cuerpo)

    if df_filtered.empty:
        return pd.DataFrame()

    # --- AGRUPACIÓN DIARIA (SESIONES REALES) ---
    daily_sessions = (
        df_filtered.groupby("fecha_dt")
        .agg(
            semana=("semana", "first"),
            fecha=("fecha", "first"),
            dia=("dia", "first"),
            sets_totales=("set_orden", "count"),
            avg_rir=("rir", "mean"),
            sets_fallo=("es_fallo", "sum"),
            # Rendimiento promedio del día (fuerza relativa en %)
            rendimiento=("perf_rel", "mean"),
        )
        .reset_index()
    )

    # --- GENERAR CRONOLOGÍA DE DÍAS CONTINUOS (PARA EL DECAIMIENTO DE FATIGA) ---
    start_date = daily_sessions["fecha_dt"].min()
    end_date = daily_sessions["fecha_dt"].max()
    all_dates = pd.date_range(start=start_date, end=end_date, freq="D")

    timeline = pd.DataFrame({"fecha_dt": all_dates})
    timeline = timeline.merge(daily_sessions, on="fecha_dt", how="left")

    # Completar días de descanso (donde no se entrenó)
    timeline["sets_totales"] = timeline["sets_totales"].fillna(0)
    timeline["sets_fallo"] = timeline["sets_fallo"].fillna(0)
    timeline["dia"] = timeline["fecha_dt"].dt.strftime("%A")

    # Traducir días de la semana a español
    dias_es = {
        "Monday": "Lunes",
        "Tuesday": "Martes",
        "Wednesday": "Miércoles",
        "Thursday": "Jueves",
        "Friday": "Viernes",
        "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    timeline["dia_es"] = timeline["dia"].map(dias_es)
    timeline["fecha_str"] = timeline["fecha_dt"].dt.strftime("%d/%m/%y")

    # El rendimiento se mantiene (ffill) durante días de descanso
    timeline["rendimiento"] = timeline["rendimiento"].ffill().fillna(100.0)

    return timeline
