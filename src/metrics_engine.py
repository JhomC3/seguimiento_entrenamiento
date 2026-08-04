import sqlite3
import pandas as pd
import numpy as np

# Palabras clave para identificar ejercicios compuestos (multiarticulares)
COMPOUND_KEYWORDS = {
    'hack', 'jalon', 'pm rigidas', 'prensa', 'convergente', 
    'mancuernas', 'militar', 'remo', 'sentadilla', 'vertical'
}

def is_compound(exercise_name: str) -> bool:
    """Retorna True si el ejercicio es multiarticular/compuesto."""
    name_lower = exercise_name.lower()
    return any(kw in name_lower for kw in COMPOUND_KEYWORDS)

def get_exercises_baselines(db_path: str) -> dict:
    """
    Calcula el RM_a base de cada ejercicio (promedio de la semana 1).
    Si un ejercicio no se realizó en la semana 1, se toma la primera semana disponible.
    """
    conn = sqlite3.connect(db_path)
    query = """
        SELECT ejercicio, semana, kg, reps, rir
        FROM training_sets
        WHERE kg IS NOT NULL AND reps IS NOT NULL
        ORDER BY semana
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    baselines = {}
    if df.empty:
        return baselines
    
    # Calcular RM_a de cada set
    rir_safe = df["rir"].fillna(0)
    df["rm_ajustado"] = df["kg"] * (1 + 0.0333 * (df["reps"] + 1 + rir_safe))
    
    # Para cada ejercicio, encontrar su primera semana disponible y promediar
    for exercise, group in df.groupby("ejercicio"):
        first_week = group["semana"].min()
        first_week_sets = group[group["semana"] == first_week]
        baselines[exercise] = round(first_week_sets["rm_ajustado"].mean(), 1)
        
    return baselines

def calculate_pfr_timeline(db_path: str, filter_type: str = "systemic", filter_value: str = None) -> pd.DataFrame:
    """
    Calcula la serie temporal diaria de Rendimiento (PI), Fatiga Acumulada (FI) y Recuperación (RI).
    - filter_type: 'systemic' (todo el cuerpo), 'muscle_group', 'exercise'
    - filter_value: el nombre del grupo muscular o ejercicio correspondiente
    """
    conn = sqlite3.connect(db_path)
    
    # 1. Obtener todos los sets de entrenamiento con el grupo muscular correspondiente
    query = """
        SELECT t.semana, t.dia, t.fecha, t.set_orden, t.ejercicio, t.kg, t.reps, t.rir, e.grupo_muscular
        FROM training_sets t
        JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio)
        WHERE t.kg IS NOT NULL AND t.reps IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return pd.DataFrame()
        
    # Obtener baselines para calcular rendimiento relativo %
    baselines = get_exercises_baselines(db_path)
    
    # Parsear fechas reales y ordenar de forma cronológica
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%y", errors="coerce")
    df = df.dropna(subset=["fecha_dt"]).sort_values("fecha_dt").reset_index(drop=True)
    
    if df.empty:
        return pd.DataFrame()
        
    # Calcular RM_a individual de cada set
    rir_safe = df["rir"].fillna(0)
    df["rm_ajustado"] = df["kg"] * (1 + 0.0333 * (df["reps"] + 1 + rir_safe))
    
    # Calcular Rendimiento Relativo (%) respecto al baseline
    df["perf_rel"] = df.apply(
        lambda r: (r["rm_ajustado"] / baselines[r["ejercicio"]] * 100) if r["ejercicio"] in baselines else 100.0,
        axis=1
    )
    
    # Calcular Fatiga de cada set según la proximidad al fallo (RIR)
    # RIR 0 -> factor 2.0 (fatiga extrema), RIR 2 -> factor 1.0, RIR 4 -> factor 0.5
    df["fatiga_set"] = 10 * (2.0 * np.exp(-0.35 * rir_safe))
    
    # --- FILTRADO DE DATOS SEGÚN NIVEL ---
    if filter_type == "muscle_group" and filter_value:
        df_filtered = df[df["grupo_muscular"].str.lower() == filter_value.lower()].copy()
    elif filter_type == "exercise" and filter_value:
        df_filtered = df[df["ejercicio"].str.lower() == filter_value.lower()].copy()
    else:
        df_filtered = df.copy() # systemic (todo el cuerpo)
        
    if df_filtered.empty:
        return pd.DataFrame()
        
    # --- AGRUPACIÓN DIARIA (SESIONES REALES) ---
    daily_sessions = df_filtered.groupby("fecha_dt").agg(
        semana=("semana", "first"),
        fecha=("fecha", "first"),
        dia=("dia", "first"),
        sets_totales=("set_orden", "count"),
        avg_rir=("rir", "mean"),
        # Rendimiento promedio del día (fuerza relativa en %)
        rendimiento=("perf_rel", "mean"),
        # Fatiga agregada de la sesión (suma de la fatiga de cada set)
        fatiga_sesion=("fatiga_set", "sum")
    ).reset_index()
    
    # --- GENERAR CRONOLOGÍA DE DÍAS CONTINUOS (PARA EL DECAIMIENTO DE FATIGA) ---
    start_date = daily_sessions["fecha_dt"].min()
    end_date = daily_sessions["fecha_dt"].max()
    all_dates = pd.date_range(start=start_date, end=end_date, freq="D")
    
    timeline = pd.DataFrame({"fecha_dt": all_dates})
    timeline = timeline.merge(daily_sessions, on="fecha_dt", how="left")
    
    # Completar días de descanso (donde no se entrenó)
    timeline["sets_totales"] = timeline["sets_totales"].fillna(0)
    timeline["fatiga_sesion"] = timeline["fatiga_sesion"].fillna(0)
    timeline["dia"] = timeline["fecha_dt"].dt.strftime("%A")
    
    # Traducir días de la semana a español
    dias_es = {
        "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
        "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo"
    }
    timeline["dia_es"] = timeline["dia"].map(dias_es)
    timeline["fecha_str"] = timeline["fecha_dt"].dt.strftime("%d/%m/%y")
    
    # El rendimiento se mantiene (ffill) durante días de descanso
    timeline["rendimiento"] = timeline["rendimiento"].ffill().fillna(100.0)
    
    # --- CÁLCULO DE FATIGA ACUMULADA Y RECUPERACIÓN CON DECAIMIENTO DIARIO ---
    fatiga_acumulada = []
    current_fatigue = 0.0
    
    for _, row in timeline.iterrows():
        # Aplicar decaimiento exponencial diario del 35% de la fatiga acumulada anterior (vida media ~2 días)
        current_fatigue = current_fatigue * 0.65
        # Añadir la fatiga generada en la sesión de hoy
        current_fatigue += row["fatiga_sesion"]
        fatiga_acumulada.append(round(current_fatigue, 1))
        
    timeline["fatiga_acumulada"] = fatiga_acumulada
    
    # Calcular el Índice de Recuperación (RI) basado en la Fatiga Acumulada
    # RI va de 10% (agotado/dañado) a 100% (recuperado)
    timeline["recuperacion"] = timeline["fatiga_acumulada"].apply(
        lambda f: max(10.0, round(100.0 - f * 1.2, 1))
    )
    
    return timeline
