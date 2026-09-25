"""Daily analysis layers: aggregated per-day series from domain tables and
health_records (JSON1). Read-only; SQL parametrized; excludes logical deletes.

Multi-origin rule: Samsung Health, Fitbit, etc. can record the SAME facts.
Every health layer below aggregates per (fecha, origen) and keeps ONE winning
origin per day (most rows; alphabetical tie-break) so two apps never
double-count. See _pick_winning_origin.
"""

import pandas as pd

from src.db_connection import read_connection

_DATETIME_FMT = "%Y-%m-%d"


def _daily_agg(db_path: str, sql: str) -> pd.DataFrame:
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame({"fecha": [], "valor": [], "fecha_dt": []}).astype(
            {"fecha_dt": "datetime64[ns]"}
        )
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format=_DATETIME_FMT, errors="coerce")
    return df.dropna(subset=["fecha_dt"]).reset_index(drop=True)


def _daily_by_origin(db_path: str, sql: str) -> pd.DataFrame:
    """Runs a per-(fecha, origen) aggregation and keeps the winning origin/day."""
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)
    return _pick_winning_origin(df)


def _pick_winning_origin(df: pd.DataFrame) -> pd.DataFrame:
    """One winning origin per fecha: most rows (n); tie-break alphabetical.

    Expects columns fecha/origen/valor/n. Returns fecha/valor/fecha_dt sorted.
    """
    if df.empty:
        return pd.DataFrame({"fecha": [], "valor": [], "fecha_dt": []}).astype(
            {"fecha_dt": "datetime64[ns]"}
        )
    ranked = df.sort_values(
        ["fecha", "n", "origen"], ascending=[True, False, True], na_position="first"
    )
    winners = ranked.drop_duplicates(subset="fecha", keep="first")[["fecha", "valor"]]
    out = winners.reset_index(drop=True)
    out["fecha_dt"] = pd.to_datetime(out["fecha"], format=_DATETIME_FMT, errors="coerce")
    out = out.dropna(subset=["fecha_dt"]).sort_values("fecha").reset_index(drop=True)
    return out


def _local_date(epoch_ms_col: str) -> str:
    return f"date({epoch_ms_col} / 1000, 'unixepoch', 'localtime') AS fecha"


def daily_sleep_hours(db_path: str) -> pd.DataFrame:
    """Horas de sueño por día (fecha de fin de la sesión de sueño)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("end_epoch_ms")},
               data_origin_package AS origen,
               SUM(end_epoch_ms - start_epoch_ms) / 3600000.0 AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'SLEEP_SESSION' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_resting_hr(db_path: str) -> pd.DataFrame:
    """FC en reposo promedio diario (bpm)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.bpm')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'RESTING_HEART_RATE' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_avg_hr(db_path: str) -> pd.DataFrame:
    """FC media diaria a partir de buckets de 5 min (HEART_RATE_5MIN)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("h.start_epoch_ms")},
               h.data_origin_package AS origen,
               AVG(json_extract(s.value, '$.bpm')) AS valor,
               COUNT(*) AS n
        FROM health_records h, json_each(h.value_json, '$.value.samples') s
        WHERE h.record_type = 'HEART_RATE_5MIN' AND h.deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_hrv(db_path: str) -> pd.DataFrame:
    """HRV RMSSD promedio diario (ms): proxy de recuperación/estrés."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.rmssd_ms')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'HEART_RATE_VARIABILITY_RMSSD' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def _hourly_or_raw_sums(raw_type: str, h1_type: str, value_key: str, db_path: str) -> pd.DataFrame:
    """Suma diaria con corte hacia adelante por origen: si el día tiene filas
    agregadas por hora (`*_H1`), esas mandan y el crudo histórico se ignora
    (si se sumaran ambos, el solape contaría doble). Después, un solo origen
    ganador por día (ver _pick_winning_origin)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT fecha, origen, COALESCE(nuevo, crudo) AS valor, n FROM (
            SELECT date(start_epoch_ms / 1000, 'unixepoch', 'localtime') AS fecha,
                   data_origin_package AS origen,
                   SUM(CASE WHEN record_type = '{h1_type}'
                            THEN json_extract(value_json, '$.value.{value_key}') END) AS nuevo,
                   SUM(CASE WHEN record_type = '{raw_type}'
                            THEN json_extract(value_json, '$.value.{value_key}') END) AS crudo,
                   COUNT(*) AS n
            FROM health_records
            WHERE record_type IN ('{raw_type}', '{h1_type}') AND deleted_at IS NULL
            GROUP BY fecha, origen
        )
        """,
    )


def daily_steps(db_path: str) -> pd.DataFrame:
    """Pasos totales por día (corte H1 hacia adelante, un origen por día)."""
    return _hourly_or_raw_sums("STEPS", "STEPS_H1", "count", db_path)


def daily_distance(db_path: str) -> pd.DataFrame:
    """Distancia total por día en metros (corte H1 hacia adelante, un origen)."""
    return _hourly_or_raw_sums("DISTANCE", "DISTANCE_H1", "meters", db_path)


def daily_calories_burned(db_path: str) -> pd.DataFrame:
    """Calorías totales quemadas por día en kcal (corte H1, un origen)."""
    return _hourly_or_raw_sums("TOTAL_CALORIES_BURNED", "TOTAL_CALORIES_H1", "energy_kcal", db_path)


def daily_cardio_minutes(db_path: str) -> pd.DataFrame:
    """Minutos de sesiones de ejercicio (EXERCISE_SESSION) por día."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               SUM(end_epoch_ms - start_epoch_ms) / 60000.0 AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'EXERCISE_SESSION' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_weight(db_path: str) -> pd.DataFrame:
    """Peso promedio diario (kg) desde Health Connect."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.kg')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'WEIGHT' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_respiratory_rate(db_path: str) -> pd.DataFrame:
    """Frecuencia respiratoria promedio diaria (resp/min)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.breaths_per_minute')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'RESPIRATORY_RATE' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_spo2(db_path: str) -> pd.DataFrame:
    """Saturación de oxígeno promedio diaria (%)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.percentage')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'OXYGEN_SATURATION' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_body_temp(db_path: str) -> pd.DataFrame:
    """Temperatura corporal promedio diaria (°C, BODY_TEMPERATURE).

    BASAL_BODY_TEMPERATURE se excluye a propósito: es otra fisiología
    (relevante sobre todo para ciclo, fuera de alcance)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.temperature_c')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'BODY_TEMPERATURE' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_vo2max(db_path: str) -> pd.DataFrame:
    """VO2 máx promedio diario (ml/kg/min)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               AVG(json_extract(value_json, '$.value.vo2_max_ml_kg_min')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'VO2_MAX' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_hydration_ml(db_path: str) -> pd.DataFrame:
    """Hidratación registrada por día (ml)."""
    return _daily_by_origin(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               data_origin_package AS origen,
               SUM(json_extract(value_json, '$.value.volume_ml')) AS valor,
               COUNT(*) AS n
        FROM health_records
        WHERE record_type = 'HYDRATION' AND deleted_at IS NULL
        GROUP BY fecha, origen
        """,
    )


def daily_weight_manual(db_path: str) -> pd.DataFrame:
    """Peso manual diario (kg) desde ``parametros_diarios``.

    Solo días con fila guardada (el editor precarga valores por defecto en
    memoria, pero aquí solo cuenta lo persistido). Sin SQL fuera de este
    módulo de lectura: forma parte de las capas de análisis diario.
    """
    return _daily_agg(
        db_path,
        """
        SELECT fecha, peso_kg AS valor
        FROM parametros_diarios
        WHERE peso_kg IS NOT NULL AND peso_kg > 0
        GROUP BY fecha
        """,
    )


def daily_weight_unified(db_path: str) -> pd.DataFrame:
    """Peso diario unificado: manual manda, HC como respaldo por día.

    Une ``daily_weight_manual`` y ``daily_weight`` por fecha ISO. Si un día
    tiene ambas fuentes, prevalece el peso manual del editor de nutrición.
    Retorna columnas ``fecha`` / ``valor`` / ``fecha_dt`` ordenadas.
    """
    manual = daily_weight_manual(db_path)
    hc = daily_weight(db_path)
    if manual.empty and hc.empty:
        return manual
    if manual.empty:
        return hc.sort_values("fecha").reset_index(drop=True)
    if hc.empty:
        return manual.sort_values("fecha").reset_index(drop=True)
    m = manual.set_index("fecha")["valor"]
    h = hc.set_index("fecha")["valor"]
    combined = m.combine_first(h).reset_index()
    combined = combined.rename(columns={"index": "fecha"})
    if "fecha" not in combined.columns:
        combined = combined.rename(columns={combined.columns[0]: "fecha"})
    combined["fecha_dt"] = pd.to_datetime(combined["fecha"], format=_DATETIME_FMT, errors="coerce")
    return combined.dropna(subset=["fecha_dt"]).sort_values("fecha").reset_index(drop=True)


def daily_kcal(db_path: str) -> pd.DataFrame:
    """Kcal consumidas por día (diario_alimentacion)."""
    return _daily_agg(
        db_path,
        """
        SELECT fecha, SUM(kcal) AS valor
        FROM diario_alimentacion
        GROUP BY fecha
        """,
    )


def daily_volume(db_path: str) -> pd.DataFrame:
    """Tonelaje diario (kg * reps) desde training_sets."""
    return _daily_agg(
        db_path,
        """
        SELECT fecha, SUM(kg * reps) AS valor
        FROM training_sets
        WHERE kg IS NOT NULL AND reps IS NOT NULL
        GROUP BY fecha
        """,
    )
