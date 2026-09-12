"""Daily analysis layers: aggregated per-day series from domain tables and
health_records (JSON1). Read-only; SQL parametrized; excludes logical deletes."""

import pandas as pd

from src.db_connection import read_connection

_DATETIME_FMT = "%Y-%m-%d"


def _daily_agg(db_path: str, sql: str) -> pd.DataFrame:
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(sql, conn)
    if df.empty:
        return df
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format=_DATETIME_FMT, errors="coerce")
    return df.dropna(subset=["fecha_dt"]).reset_index(drop=True)


def _local_date(epoch_ms_col: str) -> str:
    return f"date({epoch_ms_col} / 1000, 'unixepoch', 'localtime') AS fecha"


def daily_sleep_hours(db_path: str) -> pd.DataFrame:
    """Horas de sueño por día (fecha de fin de la sesión de sueño)."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("end_epoch_ms")},
               SUM(end_epoch_ms - start_epoch_ms) / 3600000.0 AS valor
        FROM health_records
        WHERE record_type = 'SLEEP_SESSION' AND deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_resting_hr(db_path: str) -> pd.DataFrame:
    """FC en reposo promedio diario (bpm)."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               AVG(json_extract(value_json, '$.value.bpm')) AS valor
        FROM health_records
        WHERE record_type = 'RESTING_HEART_RATE' AND deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_avg_hr(db_path: str) -> pd.DataFrame:
    """FC media diaria a partir de buckets de 5 min (HEART_RATE_5MIN)."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("h.start_epoch_ms")},
               AVG(json_extract(s.value, '$.bpm')) AS valor
        FROM health_records h, json_each(h.value_json, '$.value.samples') s
        WHERE h.record_type = 'HEART_RATE_5MIN' AND h.deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_hrv(db_path: str) -> pd.DataFrame:
    """HRV RMSSD promedio diario (ms): proxy de recuperación/estrés."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               AVG(json_extract(value_json, '$.value.rmssd_ms')) AS valor
        FROM health_records
        WHERE record_type = 'HEART_RATE_VARIABILITY_RMSSD' AND deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_steps(db_path: str) -> pd.DataFrame:
    """Pasos totales por día."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               SUM(json_extract(value_json, '$.value.count')) AS valor
        FROM health_records
        WHERE record_type = 'STEPS' AND deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_cardio_minutes(db_path: str) -> pd.DataFrame:
    """Minutos de sesiones de ejercicio (EXERCISE_SESSION) por día."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               SUM(end_epoch_ms - start_epoch_ms) / 60000.0 AS valor
        FROM health_records
        WHERE record_type = 'EXERCISE_SESSION' AND deleted_at IS NULL
        GROUP BY fecha
        """,
    )


def daily_weight(db_path: str) -> pd.DataFrame:
    """Peso promedio diario (kg) desde Health Connect."""
    return _daily_agg(
        db_path,
        f"""
        SELECT {_local_date("start_epoch_ms")},
               AVG(json_extract(value_json, '$.value.kg')) AS valor
        FROM health_records
        WHERE record_type = 'WEIGHT' AND deleted_at IS NULL
        GROUP BY fecha
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
