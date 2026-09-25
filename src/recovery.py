"""Índice de recuperación derivado (calculado localmente, NO dato del fabricante).

Health Connect no expone scores de recuperación/resiliencia/estrés (son
cálculos propietarios de Samsung/Garmin/Fitbit). Este módulo deriva un índice
0–100/día como composite TRANSPARENTE de z-scores rodantes PERSONALES
(ventana de 7 muestras, nunca umbrales poblacionales):

- HRV RMSSD (mayor = mejor): ``50 + 12*z``
- FC en reposo (menor = mejor): ``50 - 12*z``
- Sueño (duración, triangular centrada en 8 h, 0 en <=4 h y >=12 h)
- Penalización de carga del día previo (cardio + volumen relativo)

Cada componente puntúa 0–100; los pesos se renormalizan sobre los componentes
disponibles. Se exige basal cardiaca (z-score válido de HRV o de RHR): el sueño
solo no puntúa. Sin basal suficiente (``min_periods``) el día NO puntúa: nunca se
inventa un score.
"""

from dataclasses import dataclass

import pandas as pd

from src.analysis_data import (
    daily_cardio_minutes,
    daily_hrv,
    daily_resting_hr,
    daily_sleep_hours,
    daily_volume,
)
from src.metrics_engine import calculate_pfr_timeline

_Z_SCALE = 12.0


@dataclass(frozen=True)
class RecoveryConfig:
    baseline_samples: int = 7
    min_periods: int = 3
    w_hrv: float = 0.35
    w_rhr: float = 0.25
    w_sleep: float = 0.25
    sleep_optimal_h: float = 8.0
    sleep_span_h: float = 4.0
    max_cardio_penalty: float = 20.0
    max_volume_penalty: float = 15.0


def _zscore(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    roll = s.rolling(window=window, min_periods=min_periods)
    std = roll.std(ddof=1).replace(0.0, float("nan"))
    return (s - roll.mean()) / std


def _clip(s: pd.Series) -> pd.Series:
    return s.clip(lower=0.0, upper=100.0)


def _sleep_score(hours: pd.Series, cfg: RecoveryConfig) -> pd.Series:
    return _clip(100.0 * (1.0 - (hours - cfg.sleep_optimal_h).abs() / cfg.sleep_span_h))


def daily_recovery(db_path: str, cfg: RecoveryConfig | None = None) -> pd.DataFrame:
    """Índice de recuperación 0–100 por día (columnas fecha/valor/fecha_dt)."""
    cfg = cfg or RecoveryConfig()
    hrv = daily_hrv(db_path)[["fecha_dt", "valor"]].rename(columns={"valor": "hrv"})
    rhr = daily_resting_hr(db_path)[["fecha_dt", "valor"]].rename(columns={"valor": "rhr"})
    sleep = daily_sleep_hours(db_path)[["fecha_dt", "valor"]].rename(columns={"valor": "sleep"})
    cardio = daily_cardio_minutes(db_path)[["fecha_dt", "valor"]].rename(
        columns={"valor": "cardio"}
    )
    volume = daily_volume(db_path)[["fecha_dt", "valor"]].rename(columns={"valor": "volume"})
    df = hrv.merge(rhr, on="fecha_dt", how="outer")
    for part in (sleep, cardio, volume):
        df = df.merge(part, on="fecha_dt", how="outer")
    if df.empty:
        return df
    df = df.sort_values("fecha_dt").reset_index(drop=True)

    z_hrv = _zscore(df["hrv"], cfg.baseline_samples, cfg.min_periods)
    z_rhr = _zscore(df["rhr"], cfg.baseline_samples, cfg.min_periods)
    s_hrv = _clip(50.0 + _Z_SCALE * z_hrv)
    s_rhr = _clip(50.0 - _Z_SCALE * z_rhr)
    s_sleep = _sleep_score(df["sleep"], cfg)

    prev_cardio = df["cardio"].shift(1).fillna(0.0)
    vol_base = df["volume"].rolling(window=cfg.baseline_samples, min_periods=1).mean()
    vol_ratio = (df["volume"].shift(1).fillna(0.0) / vol_base.replace(0.0, float("nan"))).fillna(
        0.0
    )
    penalty = (
        (prev_cardio / 3.0).clip(upper=cfg.max_cardio_penalty)
        + ((vol_ratio - 0.5).clip(lower=0.0) * 10.0).clip(upper=cfg.max_volume_penalty)
    ).fillna(0.0)

    weighted = s_hrv * 0.0  # serie base para el índice (evita SettingWithCopy)
    total_w = s_hrv * 0.0
    for score, weight in ((s_hrv, cfg.w_hrv), (s_rhr, cfg.w_rhr), (s_sleep, cfg.w_sleep)):
        valid = score.notna()
        weighted = weighted.add(score.where(valid, 0.0) * weight, fill_value=0.0)
        total_w = total_w.add(valid.astype(float) * weight, fill_value=0.0)
    score = (weighted / total_w.replace(0.0, float("nan")) - penalty).clip(0.0, 100.0)
    # Sin basal cardiaca (ni HRV ni RHR con z válido) el día no puntúa.
    score = score.where(s_hrv.notna() | s_rhr.notna())

    out = pd.DataFrame({"fecha_dt": df["fecha_dt"], "valor": score})
    out = out.dropna(subset=["valor"]).reset_index(drop=True)
    out["fecha"] = out["fecha_dt"].dt.strftime("%Y-%m-%d")
    return out[["fecha", "valor", "fecha_dt"]]


def recovery_vs_performance(db_path: str) -> pd.DataFrame:
    """Cruce recuperación→rendimiento por día de entreno.

    Une el índice con el `rendimiento` sistémico de `calculate_pfr_timeline`
    en días con series (`sets_totales > 0`). Columnas
    fecha/recuperacion/rendimiento: la correlación se lee con `df.corr()`.
    Es el edge del proyecto: ninguna app comercial cruza HC con tus marcas.
    """
    rec = daily_recovery(db_path)
    if rec.empty:
        return rec
    timeline = calculate_pfr_timeline(db_path, "systemic")
    if timeline.empty:
        return pd.DataFrame()
    perf = timeline[timeline["sets_totales"] > 0][["fecha_dt", "rendimiento"]]
    out = rec.merge(perf, on="fecha_dt", how="inner").rename(columns={"valor": "recuperacion"})
    return out[["fecha_dt", "recuperacion", "rendimiento"]].reset_index(drop=True)
