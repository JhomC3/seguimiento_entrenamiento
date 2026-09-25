"""Métricas de salud del dashboard: catálogo e índice 0–100.

Capa pura (pandas, sin SQL): combina las capas de ``analysis_data`` (+ el
índice de ``recovery``) en el índice de la gráfica central y el catálogo de
la sección Salud del panel izquierdo. ``granularity`` reagrupa day/week/month
(semana = lunes ISO, mes = YYYY-MM); al reagrupar se usa la media uniforme
(el índice compara nivel típico diario). Los días sin registro son NaN
(nunca 0).
"""

import pandas as pd

from src.analysis_data import (
    daily_avg_hr,
    daily_body_temp,
    daily_calories_burned,
    daily_cardio_minutes,
    daily_distance,
    daily_hrv,
    daily_hydration_ml,
    daily_kcal,
    daily_respiratory_rate,
    daily_resting_hr,
    daily_sleep_hours,
    daily_spo2,
    daily_steps,
    daily_vo2max,
    daily_weight_unified,
)
from src.models import ValidationError
from src.recovery import daily_recovery

GRANULARITIES = ("day", "week", "month")

# key → (etiqueta, unidad, capa diaria, agregación week/month)
SERIES = {
    "recovery": ("Índice", "pts", daily_recovery, "mean"),
    "hrv": ("HRV", "ms", daily_hrv, "mean"),
    "rhr": ("FC reposo", "lpm", daily_resting_hr, "mean"),
    "sleep": ("Sueño", "h", daily_sleep_hours, "mean"),
    "steps": ("Pasos", "pasos", daily_steps, "sum"),
    "cardio": ("Cardio", "min", daily_cardio_minutes, "sum"),
    "distance": ("Distancia", "m", daily_distance, "sum"),
    "calories": ("Calorías", "kcal", daily_calories_burned, "sum"),
    "hydration": ("Hidratación", "ml", daily_hydration_ml, "sum"),
    "resp": ("Respiración", "rpm", daily_respiratory_rate, "mean"),
    "spo2": ("SpO₂", "%", daily_spo2, "mean"),
    "temp": ("Temperatura", "°C", daily_body_temp, "mean"),
    "weight": ("Peso", "kg", daily_weight_unified, "mean"),
    "vo2max": ("VO₂ máx", "ml/kg/min", daily_vo2max, "mean"),
    "avg_hr": ("FC media", "lpm", daily_avg_hr, "mean"),
    "kcal": ("Ingesta", "kcal", daily_kcal, "mean"),
}


def _validate_granularity(granularity: str) -> str:
    if granularity not in GRANULARITIES:
        raise ValidationError(
            f"Granularidad inválida: {granularity!r}. Valores permitidos: day, week, month."
        )
    return granularity


# key → (etiqueta de chip, unidad de tooltip). Por defecto etiqueta/unidad de
# SERIES; aquí solo los que necesitan desambiguación (quema vs ingesta).
METRIC_DISPLAY = {
    "calories": ("Quema", "kcal"),
    "kcal": ("Ingesta", "kcal"),
}

METRIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Recuperación", ("recovery", "hrv", "rhr", "sleep")),
    ("Actividad", ("steps", "cardio", "distance", "calories")),
    ("Vitales", ("resp", "spo2", "temp", "weight", "vo2max", "avg_hr", "hydration")),
    ("Nutrición", ("kcal",)),
)

METRIC_ORDER: tuple[str, ...] = tuple(k for _, ks in METRIC_GROUPS for k in ks)

DEFAULT_METRICS: tuple[str, ...] = (
    "recovery",
    "hrv",
    "rhr",
    "sleep",
    "steps",
    "weight",
    "kcal",
)


def parse_metrics_param(raw: str | None) -> tuple[str, ...]:
    """Lista ?metricas= (coma) validada contra el catálogo, en orden canónico.
    Ausente (None) o con valores desconocidos → DEFAULT_METRICS. Presente pero
    vacía ("") → tupla vacía (todo oculto: apagado explícito desde los chips)."""
    if raw is None:
        return DEFAULT_METRICS
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    picked = tuple(k for k in METRIC_ORDER if k in wanted)
    if picked:
        return picked
    return () if not raw.strip() else DEFAULT_METRICS


def normalize_01_100(values: pd.Series, already_01_100: bool = False) -> pd.Series:
    """Índice 0–100 por winsorización p1–p99 (robusto a outliers de sensor).

    ``already_01_100`` (índice de recuperación): solo clip, sin reescalar.
    Serie plana (p99 == p1) → 50. NaN se conserva (ausencia, nunca 0).
    """
    v = values.astype(float)
    if already_01_100:
        return v.clip(lower=0.0, upper=100.0)
    clean = v.dropna()
    if clean.empty:
        return v
    lo, hi = float(clean.quantile(0.01)), float(clean.quantile(0.99))
    if not hi > lo:
        return v.where(v.isna(), 50.0)
    return ((v - lo) / (hi - lo) * 100.0).clip(lower=0.0, upper=100.0)


def build_metrics_index(db_path: str, granularity: str = "day") -> pd.DataFrame:
    """Ancho con valores CRUDOS por métrica (col. x ``fecha``|``periodo`` + una
    columna por clave con datos). La normalización vive en la gráfica, no aquí.

    Reagrupación week/month: media uniforme de los valores diarios en TODAS
    las series (el índice compara nivel típico diario). Días sin registro → NaN.
    """
    _validate_granularity(granularity)
    frames = []
    for key in METRIC_ORDER:
        layer = SERIES[key][2](db_path)
        if layer.empty:
            continue
        frames.append(layer.set_index("fecha")["valor"].rename(key))
    if not frames:
        return pd.DataFrame()
    daily = pd.concat(frames, axis=1)
    daily["fecha_dt"] = pd.to_datetime(daily.index, format="%Y-%m-%d", errors="coerce")
    daily = daily.dropna(subset=["fecha_dt"]).sort_index()
    daily = daily.reset_index().rename(columns={"index": "fecha"})
    if "fecha" not in daily.columns:
        daily = daily.rename(columns={daily.columns[0]: "fecha"})
    if granularity == "day":
        return daily
    work = daily.copy()
    if granularity == "week":
        work["periodo"] = (
            work["fecha_dt"] - pd.to_timedelta(work["fecha_dt"].dt.weekday, unit="D")
        ).dt.strftime("%Y-%m-%d")
    else:
        work["periodo"] = work["fecha_dt"].dt.strftime("%Y-%m")
    cols = [k for k in METRIC_ORDER if k in work.columns]
    grouped = work.groupby("periodo", as_index=False)[cols].mean().sort_values("periodo")
    return grouped.reset_index(drop=True)


def build_metrics_catalog(db_path: str, selection: tuple[str, ...]) -> list[dict]:
    """Catálogo de métricas por grupo para el panel inferior: lista de
    {group, metrics: [{key, label, unit, pressed, disabled}]}. disabled = la
    serie no tiene datos (informa cobertura, no se oculta)."""
    df = build_metrics_index(db_path, "day")
    available = {k for k in METRIC_ORDER if k in df.columns and df[k].notna().any()}
    catalog = []
    for group, keys in METRIC_GROUPS:
        metrics = []
        for key in keys:
            label, unit = METRIC_DISPLAY.get(key, (SERIES[key][0], SERIES[key][1]))
            metrics.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "pressed": key in selection,
                    "disabled": key not in available,
                }
            )
        catalog.append({"group": group, "metrics": metrics})
    return catalog
