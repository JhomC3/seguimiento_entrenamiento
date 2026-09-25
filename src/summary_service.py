"""Punto de entrada del resumen periodico + re-exports (spec 007)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from src.models import ValidationError
from src.summary_aggregate import (
    GRANULARITIES,
    _collapse_entity_rows,
    _period_key,
    _period_metrics,
    _period_rows_desc,
    aggregate_sets,
    db_window,
    flatten_muscle_categories,
    last_valid_training_date,
    mean_growth,
    totals_by_period,
)
from src.summary_history import (
    _dedupe_keep_order,
    _historical_rows_for_exercise,
    _historical_rows_for_global,
    _historical_rows_for_muscle,
)
from src.summary_models import (
    HistoricalPeriodRow,
    PeriodAggregate,
    PeriodSummary,
    SetDetail,
    SummaryFilter,
    SummaryTab,
    _PeriodTotals,
)
from src.summary_periods import (
    RowMetrics,
    Window,
    _week_bounds,
    calendar_window,
    day_intersects,
    day_label,
    day_sort_key,
    format_day_compact,
    format_month_compact,
    format_week_compact,
    historical_period_id,
    month_intersects,
    month_label,
    month_sort_key,
    period_intersects,
    round1,
    week_intersects,
    week_label,
    week_sort_key,
    week_start_date,
)
from src.training_service import parse_cycle_start

__all__ = [
    "HistoricalPeriodRow",
    "PeriodAggregate",
    "PeriodSummary",
    "RowMetrics",
    "SetDetail",
    "SummaryFilter",
    "SummaryTab",
    "Window",
    "_PeriodTotals",
    "_collapse_entity_rows",
    "_dedupe_keep_order",
    "_historical_rows_for_exercise",
    "_historical_rows_for_global",
    "_historical_rows_for_muscle",
    "_period_key",
    "_period_metrics",
    "_period_rows_desc",
    "_week_bounds",
    "aggregate_sets",
    "calendar_window",
    "day_intersects",
    "day_label",
    "day_sort_key",
    "db_window",
    "flatten_muscle_categories",
    "format_day_compact",
    "format_month_compact",
    "format_week_compact",
    "historical_period_id",
    "last_valid_training_date",
    "mean_growth",
    "month_intersects",
    "month_label",
    "month_sort_key",
    "period_intersects",
    "round1",
    "totals_by_period",
    "week_intersects",
    "week_label",
    "week_sort_key",
    "week_start_date",
]

logger = logging.getLogger(__name__)


def build_period_summary(
    db_path: str,
    musculos: Sequence[str],
    ejercicios: Sequence[str],
    granularidad: str,
    semanas: int,
) -> PeriodSummary:
    """Punto de entrada del panel derecho (server-authoritative).

    Reglas UX-3 revisada (sin pestaña genérica "Resumen", tablas siempre históricas desc):
    - global (sin selección): una sola tab Global, histórico por periodo.
    - uno o varios músculos: una tab por músculo seleccionado, cada una con su histórico.
    - uno o varios ejercicios: una tab por ejercicio seleccionado, cada una con su histórico.
      Las selecciones de ejercicio tienen prioridad sobre las de músculo.
    Ventana técnica fija de 8 semanas para la gráfica; el histórico muestra todo el ciclo.
    """
    if granularidad not in GRANULARITIES:
        raise ValidationError(f"Granularidad no soportada: {granularidad}")
    muscles = _dedupe_keep_order(musculos)
    exercises = _dedupe_keep_order(ejercicios)

    if not muscles and not exercises:
        nivel: Literal["global", "muscle", "exercise"] = "global"
    elif exercises:
        nivel = "exercise"
    else:
        nivel = "muscle"

    try:
        window = db_window(db_path, semanas)
        if window is None:
            return PeriodSummary("empty", nivel, granularidad, semanas, ())
        # Histórico completo: ignora ventana para no perder semanas (S1..S18 todas visibles)
        # Ventana sigue almacenada en PeriodSummary para selector, pero no filtra histórico
        aggs = aggregate_sets(db_path, tuple(muscles), tuple(exercises), granularidad, None, None)
    except Exception:
        logger.exception("build_period_summary falló para %s/%s", musculos, ejercicios)
        return PeriodSummary("error", nivel, granularidad, semanas, ())

    if not aggs:
        # Ventana global sin datos de la selección: mensaje informativo con el
        # último registro de ESA selección (la ventana sigue siendo la global).
        hint = ""
        try:
            ultimo = last_valid_training_date(db_path, muscles, exercises)
            if ultimo is not None:
                hint = (
                    f"Último registro de la selección: {day_label(ultimo)}. "
                    "Queda fuera de las ventanas disponibles. "
                    "Revisa el historial."
                )
        except Exception:
            logger.exception("hint de estado vacío falló")
        return PeriodSummary("empty", nivel, granularidad, semanas, (), hint)

    tabs: list[SummaryTab] = []

    # Preparar batch de detalles para Día (todas las entidades del histórico completo, sin filtrar kg/reps)
    ciclo_start_eff = parse_cycle_start()
    details_by_key: dict[tuple[str, str], tuple[SetDetail, ...]] | None = None
    if granularidad == "day":
        try:
            from src.database import get_sets_for_window

            # Batch sobre todas las entidades con datos en histórico completo
            batch_entities = list({pa.entidad for pa in aggs})
            if batch_entities:
                batch = get_sets_for_window(db_path, None, None, batch_entities)
                tmp: dict[tuple[str, str], list[SetDetail]] = {}
                for r in batch:
                    k = (str(r["fecha"]), str(r["ejercicio"]).casefold())
                    lst = tmp.setdefault(k, [])
                    lst.append(
                        SetDetail(
                            serie=int(r["set_orden"])
                            if r["set_orden"] is not None
                            else len(lst) + 1,
                            reps=float(r["reps"]) if r["reps"] is not None else None,
                            kg=float(r["kg"]) if r["kg"] is not None else None,
                            rir=float(r["rir"]) if r["rir"] is not None else None,
                            descanso_seg=float(r["descanso_seg"])
                            if r["descanso_seg"] is not None
                            else None,
                        )
                    )
                details_by_key = {
                    k: tuple(sorted(v, key=lambda s: s.serie)) for k, v in tmp.items()
                }
            else:
                details_by_key = {}
        except Exception:
            logger.exception("batch detalles Día falló")
            details_by_key = {}

    # UX-3 revisada: pestañas son nivel, filas siempre históricas por periodo.
    # Global -> [Global]
    # Músculo -> una tab por músculo seleccionado
    # Ejercicio -> una tab por ejercicio seleccionado
    # No existe pestaña genérica "Resumen". Tabla siempre histórica desc.
    if nivel == "global":
        # Rendimiento global agregado (histórico por periodo) + legacy filas por músculo para compat
        tabs.append(
            SummaryTab(
                "Global",
                "global",
                filas=_collapse_entity_rows_global(aggs, flatten_muscle_categories()),
                historical_rows=_historical_rows_for_global(aggs, granularidad, ciclo_start_eff),
            )
        )
    elif nivel == "exercise":
        # Tabs = cada ejercicio seleccionado (preservar orden selección) - histórico por periodo con legacy para compat
        for ex in exercises:
            ex_aggs = [a for a in aggs if a.entidad == ex]
            hist = _historical_rows_for_exercise(
                ex_aggs, granularidad, ex, ciclo_start_eff, details_by_key
            )
            legacy = _period_rows_desc(ex_aggs)
            tabs.append(SummaryTab(ex, "exercise", filas=legacy, historical_rows=hist))
        if not tabs:
            for ex in exercises:
                tabs.append(SummaryTab(ex, "exercise", historical_rows=()))

    else:
        # Uno o varios músculos: una tab por cada músculo seleccionado.
        for muscle in muscles:
            muscle_aggs = [a for a in aggs if a.grupo_muscular.lower() == muscle.lower()]
            hist = _historical_rows_for_muscle(muscle_aggs, granularidad, muscle, ciclo_start_eff)
            tabs.append(SummaryTab(muscle, "muscle", historical_rows=hist))

    return PeriodSummary("ready", nivel, granularidad, semanas, tuple(tabs))


def _collapse_entity_rows_global(
    aggs: list[PeriodAggregate], order: Sequence[str]
) -> tuple[RowMetrics, ...]:
    """Vista global: filas por MÚSCULO (agregando sus ejercicios), sin RM ni Peso."""
    by_group: dict[str, list[PeriodAggregate]] = {}
    for pa in aggs:
        by_group.setdefault(pa.grupo_muscular, []).append(pa)
    rows: list[RowMetrics] = []
    for muscle in order:
        periods = by_group.get(muscle, [])
        if not periods:
            rows.append(RowMetrics(muscle, None, None, None, None, None, None))
            continue
        series_total = sum(p.series for p in periods)
        rows.append(
            RowMetrics(
                etiqueta=muscle,
                delta_pct=round1(mean_growth([p.crecimiento for p in periods])),
                series=series_total,
                reps_media=round1(sum(p.reps_sum for p in periods) / series_total),
                peso_medio=None,
                rir_medio=round1(sum(p.rir_sum for p in periods) / series_total),
                # RM nunca se agrega entre ejercicios distintos.
                rm_max=None,
            )
        )
    return tuple(rows)


def _collapse_entity_rows_multi_muscle(
    aggs: list[PeriodAggregate], muscles: Sequence[str]
) -> tuple[RowMetrics, ...]:
    """Resumen multi-músculo: SOLO los músculos seleccionados, orden de selección."""
    by_group: dict[str, list[PeriodAggregate]] = {}
    for pa in aggs:
        by_group.setdefault(pa.grupo_muscular, []).append(pa)
    rows: list[RowMetrics] = []
    for muscle in muscles:
        periods = by_group.get(muscle, [])
        if not periods:
            rows.append(RowMetrics(muscle, None, None, None, None, None, None))
            continue
        series_total = sum(p.series for p in periods)
        rows.append(
            RowMetrics(
                etiqueta=muscle,
                delta_pct=round1(mean_growth([p.crecimiento for p in periods])),
                series=series_total,
                reps_media=round1(sum(p.reps_sum for p in periods) / series_total),
                peso_medio=None,
                rir_medio=round1(sum(p.rir_sum for p in periods) / series_total),
                rm_max=None,
            )
        )
    return tuple(rows)
