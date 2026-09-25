"""Filas historicas por ejercicio, global y musculo (spec 007)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from src.summary_aggregate import mean_growth
from src.summary_models import HistoricalPeriodRow, PeriodAggregate, SetDetail
from src.summary_periods import (
    RowMetrics,
    format_day_compact,
    format_month_compact,
    format_week_compact,
    historical_period_id,
    round1,
)
from src.training_service import calculate_cycle_week

logger = logging.getLogger(__name__)


def _historical_rows_for_exercise(
    pa_list: list[PeriodAggregate],
    granularidad: str,
    ejercicio: str,
    ciclo_start: date,
    details_by_key: dict[tuple[str, str], tuple[SetDetail, ...]] | None = None,
) -> tuple[HistoricalPeriodRow, ...]:
    """Filas históricas por periodo para vista exercise con formato compacto UX-3.

    Solo exercise recibe detalles Día.
    No modifica customdata; periodo_norm = ISO/weekStr/YYYY-MM para id.
    """
    rows: list[HistoricalPeriodRow] = []
    for pa in sorted(pa_list, key=lambda p: p.sort_key, reverse=True):
        if granularidad == "day":
            d = date.fromordinal(pa.sort_key)
            visible, aria = format_day_compact(d, ciclo_start)
            periodo_norm = d.isoformat()
            fecha_iso = periodo_norm
            semana = calculate_cycle_week(d, ciclo_start)
        elif granularidad == "week":
            semana = int(pa.sort_key)
            visible, aria = format_week_compact(semana, ciclo_start)
            periodo_norm = str(semana)
            fecha_iso = None
        elif granularidad == "month":
            year = pa.sort_key // 100
            month = pa.sort_key % 100
            visible, aria = format_month_compact(year, month)
            periodo_norm = f"{year:04d}-{month:02d}"
            fecha_iso = None
            semana = None  # type: ignore[assignment]
        else:
            visible, aria = pa.label, pa.label
            periodo_norm = str(pa.sort_key)
            fecha_iso = None
        # semana variable for week/day
        if granularidad == "day":
            sem_val: int | None = semana  # type: ignore[assignment]
        elif granularidad == "week":
            sem_val = int(pa.sort_key)
        else:
            sem_val = None
        periodo_id = historical_period_id(granularidad, periodo_norm, ejercicio)
        metrics = RowMetrics(
            etiqueta=visible,
            delta_pct=round1(pa.crecimiento),
            series=pa.series,
            reps_media=round1(pa.reps_media),
            peso_medio=round1(pa.peso_medio),
            rir_medio=round1(pa.rir_medio),
            rm_max=round1(pa.rm_max),
        )
        detalles: tuple[SetDetail, ...] = ()
        if granularidad == "day" and details_by_key is not None and fecha_iso is not None:
            detalles = details_by_key.get((fecha_iso, ejercicio.casefold()), ())
        rows.append(
            HistoricalPeriodRow(
                periodo=visible,
                periodo_aria=aria,
                periodo_id=periodo_id,
                sort_key=pa.sort_key,
                metrics=metrics,
                fecha_iso=fecha_iso,
                semana=sem_val,
                detalles=detalles,
            )
        )
    return tuple(rows)


def _historical_rows_for_global(
    aggs: list[PeriodAggregate],
    granularidad: str,
    ciclo_start: date,
) -> tuple[HistoricalPeriodRow, ...]:
    """Histórico global: 1 fila por periodo agregado (todos los músculos)."""
    by_period: dict[int, list[PeriodAggregate]] = {}
    for pa in aggs:
        by_period.setdefault(pa.sort_key, []).append(pa)
    rows: list[HistoricalPeriodRow] = []
    for sort_key in sorted(by_period.keys(), reverse=True):
        pas = by_period[sort_key]
        if granularidad == "day":
            d = date.fromordinal(sort_key)
            visible, aria = format_day_compact(d, ciclo_start)
            periodo_norm = d.isoformat()
            fecha_iso = periodo_norm
            sem_val: int | None = calculate_cycle_week(d, ciclo_start)
        elif granularidad == "week":
            semana = int(sort_key)
            visible, aria = format_week_compact(semana, ciclo_start)
            periodo_norm = str(semana)
            fecha_iso = None
            sem_val = semana
        elif granularidad == "month":
            year = sort_key // 100
            month = sort_key % 100
            visible, aria = format_month_compact(year, month)
            periodo_norm = f"{year:04d}-{month:02d}"
            fecha_iso = None
            sem_val = None
        else:
            visible, aria = str(sort_key), str(sort_key)
            periodo_norm = str(sort_key)
            fecha_iso = None
            sem_val = None
        periodo_id = historical_period_id(granularidad, periodo_norm, "crecimiento")
        total_series = sum(p.series for p in pas)
        total_reps = sum(p.reps_sum for p in pas)
        total_peso = sum(p.peso_sum for p in pas)
        total_rir = sum(p.rir_sum for p in pas)
        rm_max = max(p.rm_max for p in pas)
        delta = mean_growth([p.crecimiento for p in pas])
        metrics = RowMetrics(
            etiqueta=visible,
            delta_pct=round1(delta),
            series=total_series,
            reps_media=round1(total_reps / total_series) if total_series else None,
            peso_medio=round1(total_peso / total_series) if total_series else None,
            rir_medio=round1(total_rir / total_series) if total_series else None,
            rm_max=round1(rm_max),
        )
        rows.append(
            HistoricalPeriodRow(
                visible, aria, periodo_id, sort_key, metrics, fecha_iso, sem_val, ()
            )
        )
    return tuple(rows)


def _historical_rows_for_muscle(
    aggs: list[PeriodAggregate],
    granularidad: str,
    musculo: str,
    ciclo_start: date,
) -> tuple[HistoricalPeriodRow, ...]:
    """Histórico de un músculo: 1 fila por periodo de ese músculo."""
    # aggs ya filtrado a ese músculo
    by_period: dict[int, list[PeriodAggregate]] = {}
    for pa in aggs:
        by_period.setdefault(pa.sort_key, []).append(pa)
    rows: list[HistoricalPeriodRow] = []
    for sort_key in sorted(by_period.keys(), reverse=True):
        pas = by_period[sort_key]
        if granularidad == "day":
            d = date.fromordinal(sort_key)
            visible, aria = format_day_compact(d, ciclo_start)
            periodo_norm = d.isoformat()
            fecha_iso = periodo_norm
            sem_val = calculate_cycle_week(d, ciclo_start)
        elif granularidad == "week":
            semana = int(sort_key)
            visible, aria = format_week_compact(semana, ciclo_start)
            periodo_norm = str(semana)
            fecha_iso = None
            sem_val = semana
        elif granularidad == "month":
            year = sort_key // 100
            month = sort_key % 100
            visible, aria = format_month_compact(year, month)
            periodo_norm = f"{year:04d}-{month:02d}"
            fecha_iso = None
            sem_val = None
        else:
            visible, aria = str(sort_key), str(sort_key)
            periodo_norm = str(sort_key)
            fecha_iso = None
            sem_val = None
        periodo_id = historical_period_id(granularidad, periodo_norm, musculo)
        total_series = sum(p.series for p in pas)
        total_reps = sum(p.reps_sum for p in pas)
        total_peso = sum(p.peso_sum for p in pas)
        total_rir = sum(p.rir_sum for p in pas)
        rm_max = max(p.rm_max for p in pas)
        delta = mean_growth([p.crecimiento for p in pas])
        metrics = RowMetrics(
            etiqueta=visible,
            delta_pct=round1(delta),
            series=total_series,
            reps_media=round1(total_reps / total_series) if total_series else None,
            peso_medio=round1(total_peso / total_series) if total_series else None,
            rir_medio=round1(total_rir / total_series) if total_series else None,
            rm_max=round1(rm_max),
        )
        rows.append(
            HistoricalPeriodRow(
                visible, aria, periodo_id, sort_key, metrics, fecha_iso, sem_val, ()
            )
        )
    return tuple(rows)


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))
