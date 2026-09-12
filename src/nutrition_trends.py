"""Tendencias de nutrición: medias móviles de 7 días sobre calendario continuo.

Capa pura (pandas, sin SQL): combina las capas diarias de ``analysis_data``
(``daily_kcal`` + ``daily_weight_unified``) y suaviza con ventana móvil de
7 días naturales. Los días sin registro son ``NaN`` (nunca 0): no se inventa
consumo ni peso. ``granularity`` solo reagrupa la serie diaria ya suavizada.
"""

import pandas as pd

from src.analysis_data import daily_kcal, daily_weight_unified
from src.models import ValidationError

GRANULARITIES = ("day", "week", "month")

KCAL_MIN_PERIODS = 1
PESO_MIN_PERIODS = 2


def _validate_granularity(granularity: str) -> str:
    if granularity not in GRANULARITIES:
        raise ValidationError(
            f"Granularidad inválida: {granularity!r}. Valores permitidos: day, week, month."
        )
    return granularity


def _daily_ma_frame(db_path: str) -> pd.DataFrame:
    """Serie diaria continua con MA7 de kcal y peso.

    Columnas: ``fecha`` (ISO), ``fecha_dt``, ``kcal_ma7``, ``peso_ma7``,
    ``kcal_raw``, ``peso_raw``. Vacía si no hay ningún dato.
    """
    kcal = daily_kcal(db_path)
    peso = daily_weight_unified(db_path)
    if kcal.empty and peso.empty:
        return pd.DataFrame()
    all_dates: set[str] = set()
    if not kcal.empty:
        all_dates.update(str(v) for v in kcal["fecha"].tolist())
    if not peso.empty:
        all_dates.update(str(v) for v in peso["fecha"].tolist())
    start = pd.Timestamp(min(all_dates))
    end = pd.Timestamp(max(all_dates))
    idx = pd.date_range(start=start, end=end, freq="D")
    frame = pd.DataFrame({"fecha_dt": idx})
    frame["fecha"] = frame["fecha_dt"].dt.strftime("%Y-%m-%d")
    if not kcal.empty:
        ks = kcal.set_index("fecha")["valor"]
        frame["kcal_raw"] = frame["fecha"].map(ks).astype(float)
    else:
        frame["kcal_raw"] = float("nan")
    if not peso.empty:
        ps = peso.set_index("fecha")["valor"]
        frame["peso_raw"] = frame["fecha"].map(ps).astype(float)
    else:
        frame["peso_raw"] = float("nan")
    frame["kcal_ma7"] = frame["kcal_raw"].rolling(7, min_periods=KCAL_MIN_PERIODS).mean()
    frame["peso_ma7"] = frame["peso_raw"].rolling(7, min_periods=PESO_MIN_PERIODS).mean()
    # Sin ningún punto suavizado no hay gráfica (p. ej. 1 solo peso aislado
    # queda en NaN con min_periods=2).
    if frame["kcal_ma7"].dropna().empty and frame["peso_ma7"].dropna().empty:
        return pd.DataFrame()
    return frame


def build_nutrition_trends(db_path: str, granularity: str = "day") -> pd.DataFrame:
    """DataFrame listo para graficar según granularidad.

    - ``day``: una fila por día natural (``fecha`` ISO).
    - ``week``: media de la MA7 diaria por semana (lunes ISO en ``periodo``).
    - ``month``: media de la MA7 diaria por mes (``periodo`` ``YYYY-MM``).
    """
    _validate_granularity(granularity)
    daily = _daily_ma_frame(db_path)
    if daily.empty:
        return daily
    if granularity == "day":
        return daily.sort_values("fecha").reset_index(drop=True)
    if granularity == "week":
        work = daily.copy()
        work["periodo"] = (
            work["fecha_dt"] - pd.to_timedelta(work["fecha_dt"].dt.weekday, unit="D")
        ).dt.strftime("%Y-%m-%d")
        grouped = (
            work.groupby("periodo", as_index=False)
            .agg(kcal_ma7=("kcal_ma7", "mean"), peso_ma7=("peso_ma7", "mean"))
            .sort_values("periodo")
        )
        return grouped.reset_index(drop=True)
    work = daily.copy()
    work["periodo"] = work["fecha_dt"].dt.strftime("%Y-%m")
    grouped = (
        work.groupby("periodo", as_index=False)
        .agg(kcal_ma7=("kcal_ma7", "mean"), peso_ma7=("peso_ma7", "mean"))
        .sort_values("periodo")
    )
    return grouped.reset_index(drop=True)
