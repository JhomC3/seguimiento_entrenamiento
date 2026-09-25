"""Datos para graficas: raw, cohortes y PFR (spec 008)."""

import pandas as pd

from src.db_connection import read_connection
from src.metrics_engine import RM_FACTOR, calculate_pfr_timeline, rm_ajustado
from src.summary_service import (
    _PeriodTotals,
    aggregate_sets,
    day_label,
    month_label,
    totals_by_period,
    week_label,
)


def _hover_totals_for(
    db_path: str, filter_type: str, filter_value: str | None, granularity: str
) -> dict[int, _PeriodTotals]:
    """Totales por periodo desde el camino compartido (summary_service).

    Reutiliza aggregate_sets + totals_by_period: cero SQL ni agregación
    duplicada. Devuelve {sort_key: _PeriodTotals}.
    """
    if filter_type == "muscle_group" and filter_value:
        muscles: tuple[str, ...] = (filter_value,)
        exercises: tuple[str, ...] = ()
    elif filter_type == "exercise" and filter_value:
        muscles = ()
        exercises = (filter_value,)
    else:
        muscles = ()
        exercises = ()
    aggs = aggregate_sets(db_path, muscles, exercises, granularity, None, None)
    return totals_by_period(aggs)


def get_exercise_raw_data(db_path: str, ejercicio: str) -> pd.DataFrame:
    """Retorna datos del ejercicio con contexto de posición y serie.

    La posición se deriva del orden de la primera serie de cada ejercicio en
    la sesión, de modo que ejercicios hechos en distinto estado de fatiga no
    se mezclen en la misma cohorte comparativa.
    """
    with read_connection(db_path) as conn:
        df = pd.read_sql_query(
            """
            SELECT semana, dia, fecha, set_orden, ejercicio, kg, reps, rir, descanso_seg
            FROM training_sets
            WHERE kg IS NOT NULL AND reps IS NOT NULL
            ORDER BY semana, fecha, set_orden
        """,
            conn,
        )

    if df.empty:
        return df

    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    session_keys = ["semana", "fecha"]
    df["sesion"] = df.groupby("semana")["fecha_dt"].transform(
        lambda x: x.rank(method="dense").astype(int)
    )
    first_order = df.groupby(session_keys + ["ejercicio"], as_index=False)["set_orden"].min()
    first_order["posicion_ejercicio"] = (
        first_order.groupby(session_keys)["set_orden"]
        .rank(method="dense", ascending=True)
        .astype(int)
    )
    df = df.merge(
        first_order.drop(columns=["set_orden"]),
        on=session_keys + ["ejercicio"],
        how="left",
    )
    df["serie"] = df.groupby(["semana", "fecha", "ejercicio"]).cumcount() + 1
    df = df[df["ejercicio"].str.lower() == ejercicio.lower()].copy()
    if df.empty:
        return df

    rir_safe = df["rir"].fillna(0)
    df["rm"] = (df["kg"] * (1 + RM_FACTOR * df["reps"])).round(1)
    # RM ajustado centralizado (única fuente: metrics_engine.rm_ajustado);
    # RIR ausente cuenta como 0 (semántica vigente del dominio).
    df["rm_ajustado"] = df.apply(
        lambda r: round(
            rm_ajustado(float(r["kg"]), float(r["reps"]), float(rir_safe.loc[r.name])), 1
        ),
        axis=1,
    )

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
            "posicion_ejercicio",
            "kg",
            "reps",
            "rir",
            "descanso_seg",
            "rm",
            "rm_ajustado",
        ]
    ]


def get_exercise_cohort_summary(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Resume cohortes homogéneas: posición del ejercicio y serie ordinal.

    El baseline de cada cohorte es su primera observación cronológica. La
    mediana describe el nivel típico y reduce el efecto de una sesión atípica.
    """
    if raw_df.empty:
        return raw_df
    work = raw_df.sort_values(["fecha_dt", "serie"]).copy()
    rows: list[dict[str, object]] = []
    for (position, series), group in work.groupby(["posicion_ejercicio", "serie"], sort=True):
        group = group.sort_values("fecha_dt")
        baseline = float(group.iloc[0]["rm_ajustado"])
        current = float(group.iloc[-1]["rm_ajustado"])
        median = float(group["rm_ajustado"].median())
        rows.append(
            {
                "posicion_ejercicio": int(position),  # type: ignore[call-overload]
                "serie": int(series),  # type: ignore[call-overload]
                "observaciones": len(group),
                "baseline_rm": round(baseline, 1),
                "rm_mediana": round(median, 1),
                "rm_ultima": round(current, 1),
                "crecimiento_pct": round((current / baseline - 1) * 100, 1) if baseline else None,
                "ultima_fecha": group.iloc[-1]["fecha"],
            }
        )
    return pd.DataFrame(rows)


def _pfr_df(
    db_path: str, filter_type: str, filter_value: str | None, granularity: str = "week"
) -> pd.DataFrame:
    """DataFrame de rendimiento por periodo con columnas de hover.

    X/Y provienen de calculate_pfr_timeline (intacto). Las métricas del hover
    (series, reps/peso/RIR medios y RM máximo del periodo) vienen del camino
    ÚNICO de agregación en summary_service (aggregate_sets → totals_by_period).

    Columnas de hover: hlabel (etiqueta centralizada), h_series (int|None),
    h_reps/h_peso/h_rir/h_rm (float|None). None → '—' al renderizar.

    granularity: 'day' | 'week' | 'month'
    """
    df = calculate_pfr_timeline(db_path, filter_type, filter_value)
    if df.empty:
        return pd.DataFrame()

    totals = _hover_totals_for(db_path, filter_type, filter_value, granularity)

    def _key_for(row) -> int:
        if granularity == "day":
            return row["fecha_dt"].date().toordinal()
        if granularity == "month":
            return int(str(row["periodo"]).replace("-", "")[:6])
        return int(row["semana"])

    def _label_for(row) -> str:
        if granularity == "day":
            return day_label(row["fecha_dt"].date())
        if granularity == "month":
            iso = str(row["periodo"])
            return month_label(int(iso[:4]), int(iso[5:7]))
        return week_label(int(row["semana"]))

    def _totals_cols(row):
        t = totals.get(_key_for(row))
        if t is None or getattr(t, "series", 0) == 0:
            return pd.Series(
                {
                    "hlabel": _label_for(row),
                    "h_series": None,
                    "h_reps": None,
                    "h_peso": None,
                    "h_rir": None,
                    "h_rm": None,
                    "h_cobertura": None,
                }
            )
        return pd.Series(
            {
                "hlabel": t.label,
                "h_series": float(t.series),
                "h_reps": t.reps_media,
                "h_peso": t.peso_medio,
                "h_rir": t.rir_medio,
                "h_rm": t.rm_max,
                "h_cobertura": row.get("cobertura"),
            }
        )

    if granularity == "day":
        # calculate_pfr_timeline devuelve una cronología continua con los días de
        # descanso rellenados (rendimiento ffill, sets_totales=0). Solo mostramos
        # días con entrenamiento real: sin inventar puntos de descanso (req. 2-3).
        result = df[df["sets_totales"] > 0][
            ["fecha_dt", "rendimiento", "sets_totales", "cobertura"]
        ].copy()
        result = result.rename(columns={"sets_totales": "series"})
        result["periodo"] = result["fecha_dt"].dt.strftime("%Y-%m-%d")
        result = result.sort_values("periodo")
        result["crecimiento"] = result["rendimiento"] - 100
        result = pd.concat([result, result.apply(_totals_cols, axis=1)], axis=1)
        return result

    if granularity == "month":
        df["periodo"] = df["fecha_dt"].dt.to_period("M").astype(str)
        grouped = (
            df.groupby("periodo")
            .agg(
                rendimiento=("rendimiento", "mean"),
                series=("sets_totales", "sum"),
                cobertura=("cobertura", "mean"),
            )
            .reset_index()
            .sort_values("periodo")
        )
        grouped["crecimiento"] = grouped["rendimiento"] - 100
        grouped = pd.concat([grouped, grouped.apply(_totals_cols, axis=1)], axis=1)
        return grouped

    # Default: week (comportamiento original)
    weekly = (
        df.groupby("semana")
        .agg(
            rendimiento=("rendimiento", "mean"),
            series=("sets_totales", "sum"),
            cobertura=("cobertura", "mean"),
        )
        .reset_index()
        .dropna(subset=["semana"])
    )
    weekly["semana"] = weekly["semana"].astype(int)
    weekly = weekly.sort_values("semana")
    weekly["crecimiento"] = weekly["rendimiento"] - 100
    weekly["periodo"] = weekly["semana"].astype(str)
    weekly = pd.concat([weekly, weekly.apply(_totals_cols, axis=1)], axis=1)
    return weekly


# Legacy alias
def _weekly_pfr_df(db_path: str, filter_type: str, filter_value: str | None) -> pd.DataFrame:
    return _pfr_df(db_path, filter_type, filter_value, granularity="week")
