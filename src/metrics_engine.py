import pandas as pd

from src.db_connection import read_connection

RM_FACTOR = 0.0333
MISSING_PERFORMANCE_FULL_WEIGHT_DAYS = 7
MISSING_PERFORMANCE_MAX_DAYS = 14


def rm_ajustado(kg: float, reps: float, rir: float = 0.0) -> float:
    """Estima el 1RM con las repeticiones efectivas hasta el fallo.

    Para RIR normal, las repeticiones efectivas son ``reps + RIR``. Un RIR
    negativo representa una fracción de la siguiente repetición fallida:
    ``-0.5`` equivale a media repetición adicional y ``-1`` a ninguna.
    """
    effective_reps = reps + (rir if rir >= 0 else 1 + rir)
    return kg * (1 + RM_FACTOR * effective_reps)


def is_failure_set(reps: float, rir: float | None) -> bool:
    """True si hubo fallo negativo o una repetición parcial."""
    return (rir is not None and rir < 0) or (reps % 1 != 0)


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


def _weighted_group_timeline(
    df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp, group_column: str
) -> pd.DataFrame:
    """Calcula grupos con roster fijo, pesos por series y cobertura observada."""
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    rows: list[pd.DataFrame] = []
    for group_name, group in df.groupby(group_column):
        roster = group.groupby("ejercicio").size().astype(float)
        weights = roster / roster.sum()
        exercise_daily = group.groupby(["fecha_dt", "ejercicio"])["perf_rel"].mean()
        pivot = exercise_daily.unstack("ejercicio").reindex(dates)
        observed = pivot.notna()
        carried = pivot.ffill(limit=MISSING_PERFORMANCE_MAX_DAYS)

        # No asumimos que un ejercicio omitido sea un cero. Conservamos su
        # último rendimiento, pero reducimos gradualmente su peso después de
        # una semana para evitar saltos cuando cambia la selección de ejercicios.
        freshness = pd.DataFrame(index=dates, columns=pivot.columns, dtype=float)
        for exercise in pivot.columns:
            last_observed = pd.Series(dates, index=dates).where(observed[exercise]).ffill()
            age_days = (pd.Series(dates, index=dates) - last_observed).dt.days
            freshness[exercise] = (
                1.0
                - (age_days - MISSING_PERFORMANCE_FULL_WEIGHT_DAYS).clip(lower=0)
                / (MISSING_PERFORMANCE_MAX_DAYS - MISSING_PERFORMANCE_FULL_WEIGHT_DAYS)
            ).clip(lower=0, upper=1)
        effective_weights = freshness.where(carried.notna()).mul(weights, axis=1)
        available_weight = effective_weights.sum(axis=1)
        score = carried.mul(effective_weights).sum(axis=1).div(available_weight.replace(0, pd.NA))
        score = pd.to_numeric(score, errors="coerce")
        observed_weight = observed.mul(weights, axis=1).sum(axis=1)
        rows.append(
            pd.DataFrame(
                {
                    "fecha_dt": dates,
                    "grupo_calculo": str(group_name),
                    "rendimiento_grupo": score.astype(float),
                    "cobertura_grupo": pd.to_numeric(
                        observed_weight / weights.sum() * 100, errors="coerce"
                    ),
                }
            )
        )
    if not rows:
        return pd.DataFrame(
            columns=["fecha_dt", "grupo_calculo", "rendimiento_grupo", "cobertura_grupo"]
        )
    return pd.concat(rows, ignore_index=True)


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
    effective_reps = df["reps"] + rir_safe.where(rir_safe >= 0, 1 + rir_safe)
    df["rm_ajustado"] = df["kg"] * (1 + RM_FACTOR * effective_reps)

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
            SELECT t.semana, t.dia, t.fecha, t.set_orden, t.ejercicio, t.kg, t.reps, t.rir, e.grupo_muscular, e.categoria
            FROM training_sets t
            JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio)
            WHERE t.kg IS NOT NULL AND t.reps IS NOT NULL
        """
        df = pd.read_sql_query(query, conn)

    if df.empty:
        return pd.DataFrame()

    # Parsear fechas reales y ordenar de forma cronológica
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    df = df.dropna(subset=["fecha_dt"]).sort_values("fecha_dt").reset_index(drop=True)

    if df.empty:
        return pd.DataFrame()

    # Calcular RM_a individual de cada set
    rir_safe = df["rir"].fillna(0)
    effective_reps = df["reps"] + rir_safe.where(rir_safe >= 0, 1 + rir_safe)
    df["rm_ajustado"] = df["kg"] * (1 + RM_FACTOR * effective_reps)

    # La gráfica de progreso compara el ejercicio consigo mismo. La posición
    # y el número de serie se reservan para el análisis contextual del detalle,
    # no para redefinir el progreso global cuando cambia el orden de la sesión.
    baselines = get_exercises_baselines(db_path)
    df["perf_rel"] = df.apply(
        lambda r: (
            (r["rm_ajustado"] / baselines[r["ejercicio"]] * 100)
            if r["ejercicio"] in baselines
            else 100.0
        ),
        axis=1,
    )
    df["es_fallo"] = df.apply(lambda r: int(is_failure_set(float(r["reps"]), r["rir"])), axis=1)

    # --- FILTRADO DE DATOS SEGÚN NIVEL ---
    if filter_type == "muscle_group" and filter_value:
        df_filtered = df[df["grupo_muscular"].str.lower() == filter_value.lower()].copy()
    elif filter_type == "category" and filter_value:
        df_filtered = df[df["categoria"].str.lower() == filter_value.lower()].copy()
    elif filter_type == "exercise" and filter_value:
        df_filtered = df[df["ejercicio"].str.lower() == filter_value.lower()].copy()
    else:
        df_filtered = df.copy()  # systemic (todo el cuerpo)

    if df_filtered.empty:
        return pd.DataFrame()

    # --- AGRUPACIÓN DIARIA (SESIONES REALES) ---
    daily_base = (
        df_filtered.groupby("fecha_dt")
        .agg(
            semana=("semana", "first"),
            fecha=("fecha", "first"),
            dia=("dia", "first"),
            sets_totales=("set_orden", "count"),
            avg_rir=("rir", "mean"),
            sets_fallo=("es_fallo", "sum"),
        )
        .reset_index()
    )
    if filter_type == "systemic":
        # Un peso igual por grupo muscular evita que un grupo con más
        # ejercicios/series domine la métrica global. El roster de cada grupo
        # permanece fijo y los ausentes se arrastran temporalmente.
        group_daily = _weighted_group_timeline(
            df_filtered,
            daily_base["fecha_dt"].min(),
            daily_base["fecha_dt"].max(),
            "grupo_muscular",
        )
        daily_sessions = daily_base.copy()
        group_mean = group_daily.groupby("fecha_dt")["rendimiento_grupo"].mean()
        coverage_mean = group_daily.groupby("fecha_dt")["cobertura_grupo"].mean()
        daily_sessions["rendimiento"] = daily_sessions["fecha_dt"].map(group_mean)
        daily_sessions["cobertura"] = daily_sessions["fecha_dt"].map(coverage_mean)
    elif filter_type == "muscle_group":
        group_daily = _weighted_group_timeline(
            df_filtered,
            daily_base["fecha_dt"].min(),
            daily_base["fecha_dt"].max(),
            "grupo_muscular",
        )
        daily_sessions = daily_base.copy()
        group_score = group_daily.groupby("fecha_dt")["rendimiento_grupo"].mean()
        group_coverage = group_daily.groupby("fecha_dt")["cobertura_grupo"].mean()
        daily_sessions["rendimiento"] = daily_sessions["fecha_dt"].map(group_score)
        daily_sessions["cobertura"] = daily_sessions["fecha_dt"].map(group_coverage)
    else:
        daily_sessions = daily_base.copy()
        exercise_mean = df_filtered.groupby("fecha_dt")["perf_rel"].mean()
        daily_sessions["rendimiento"] = daily_sessions["fecha_dt"].map(exercise_mean)
        daily_sessions["cobertura"] = 100.0

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
