"""Agregacion de sets por periodo (spec 007)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date

from config import MUSCLE_CATEGORIES
from src.db_connection import read_connection
from src.metrics_engine import get_exercises_baselines, rm_ajustado
from src.models import ValidationError
from src.summary_models import PeriodAggregate, SummaryFilter, _PeriodTotals
from src.summary_periods import (
    RowMetrics,
    Window,
    calendar_window,
    day_label,
    month_label,
    month_sort_key,
    round1,
    week_label,
    week_sort_key,
)
from src.training_service import calculate_cycle_week, parse_cycle_start

logger = logging.getLogger(__name__)

GRANULARITIES: tuple[str, ...] = ("day", "week", "month")


def flatten_muscle_categories() -> tuple[str, ...]:
    """Orden FIJO de músculos derivado de config.MUSCLE_CATEGORIES.

    Nunca ordena por rendimiento, series ni fecha.
    """
    out: list[str] = []
    for group in MUSCLE_CATEGORIES:
        for muscle in group.get("muscles", []):
            if isinstance(muscle, str) and muscle not in out:
                out.append(muscle)
    return tuple(out)


def last_valid_training_date(
    db_path: str,
    muscles: Sequence[str] = (),
    exercises: Sequence[str] = (),
) -> date | None:
    """Última fecha con sets válidos (kg y reps NOT NULL).

    Sin filtros → fecha global del dashboard (ancla de la ventana compartida
    con la gráfica). Con músculos/ejercicios → fecha de la selección, usada
    SOLO para el mensaje informativo del estado vacío (nunca para anclar la
    ventana: gráfica y panel comparten el mismo "ahora").
    """
    clauses = ["t.kg IS NOT NULL", "t.reps IS NOT NULL"]
    params: list[object] = []
    join = ""
    muscles_clean = tuple(m.strip() for m in muscles if m.strip())
    exercises_clean = tuple(e.strip() for e in exercises if e.strip())
    if muscles_clean:
        join = "JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio)"
        clauses.append(f"LOWER(e.grupo_muscular) IN ({','.join('?' * len(muscles_clean))})")
        params.extend(m.lower() for m in muscles_clean)
    if exercises_clean:
        clauses.append(f"LOWER(t.ejercicio) IN ({','.join('?' * len(exercises_clean))})")
        params.extend(e.lower() for e in exercises_clean)
    with read_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT MAX(t.fecha) FROM training_sets t {join} WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
    if not row or row[0] is None:
        return None
    return date.fromisoformat(str(row[0]))


def db_window(db_path: str, weeks: int) -> Window | None:
    """Ventana calendario anclada a la última fecha con datos; None sin datos."""
    end = last_valid_training_date(db_path)
    if end is None:
        return None
    return calendar_window(end, weeks)


def _period_key(fecha: date, granularity: str, ciclo_start: date) -> tuple[int, str]:
    """Clave cronológica + etiqueta centralizada según granularidad."""
    if granularity == "day":
        return fecha.toordinal(), day_label(fecha)
    if granularity == "week":
        semana = calculate_cycle_week(fecha, ciclo_start)
        return week_sort_key(semana), week_label(semana)
    if granularity == "month":
        key = month_sort_key(fecha.year, fecha.month)
        return key, month_label(fecha.year, fecha.month)
    raise ValidationError(f"Granularidad no soportada: {granularity}")


def aggregate_sets(
    db_path: str,
    muscles: Sequence[str],
    exercises: Sequence[str],
    granularity: str,
    fecha_min_iso: str | None,
    fecha_max_iso: str | None,
) -> list[PeriodAggregate]:
    """Camino ÚNICO de agregación por (entidad, periodo).

    - SQL parametrizado con JOIN a ejercicios; solo sets con kg y reps válidos.
    - RIR NULL → 0 (sin reserva, pero no fallo).
    - RM por set vía metrics_engine.rm_ajustado; rm_max = máximo del periodo.
    - rendimiento = media simple de perf_rel de los sets del periodo
      (perf_rel = rm_ajustado / baseline × 100; sin baseline → 100.0 como el
      motor de metrics_engine).
    - Orden interno SIEMPRE ascendente cronológico; descendente solo al render.
    """
    if granularity not in GRANULARITIES:
        raise ValidationError(f"Granularidad no soportada: {granularity}")

    clauses = ["t.kg IS NOT NULL", "t.reps IS NOT NULL"]
    params: list[object] = []
    if fecha_min_iso is not None:
        clauses.append("t.fecha >= ?")
        params.append(fecha_min_iso)
    if fecha_max_iso is not None:
        clauses.append("t.fecha <= ?")
        params.append(fecha_max_iso)
    muscles_clean = tuple(dict.fromkeys(m.strip() for m in muscles if m.strip()))
    exercises_clean = tuple(dict.fromkeys(e.strip() for e in exercises if e.strip()))
    if muscles_clean:
        clauses.append(f"LOWER(e.grupo_muscular) IN ({','.join('?' * len(muscles_clean))})")
        params.extend(m.lower() for m in muscles_clean)
    if exercises_clean:
        clauses.append(f"LOWER(t.ejercicio) IN ({','.join('?' * len(exercises_clean))})")
        params.extend(e.lower() for e in exercises_clean)

    baselines = get_exercises_baselines(db_path)
    ciclo_start = parse_cycle_start()
    acc: dict[tuple[str, str, int], dict[str, float]] = {}
    labels: dict[int, str] = {}

    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT t.fecha, t.ejercicio, e.grupo_muscular, t.kg, t.reps, "
            "COALESCE(t.rir, 0) AS rir "
            "FROM training_sets t JOIN ejercicios e ON LOWER(t.ejercicio) = LOWER(e.ejercicio) "
            f"WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()

    for fecha_iso, ejercicio, grupo, kg, reps, rir in rows:
        d = date.fromisoformat(str(fecha_iso))
        key, label = _period_key(d, granularity, ciclo_start)
        labels[key] = label
        kg_f = float(kg)
        reps_f = float(reps)
        rir_f = float(rir)
        rm = rm_ajustado(kg_f, reps_f, rir_f)
        baseline = baselines.get(str(ejercicio))
        perf = rm / baseline * 100.0 if baseline else 100.0
        bucket_key = (str(grupo), str(ejercicio), key)
        bucket = acc.setdefault(
            bucket_key,
            {"series": 0.0, "reps": 0.0, "peso": 0.0, "rir": 0.0, "rm_max": 0.0, "perf": 0.0},
        )
        bucket["series"] += 1
        bucket["reps"] += reps_f
        bucket["peso"] += kg_f
        bucket["rir"] += rir_f
        bucket["rm_max"] = max(bucket["rm_max"], rm)
        bucket["perf"] += perf

    out: list[PeriodAggregate] = []
    for (grupo, entidad, key), b in sorted(acc.items(), key=lambda kv: (kv[0][2], kv[0][1])):
        series = int(b["series"])
        out.append(
            PeriodAggregate(
                grupo_muscular=grupo,
                entidad=entidad,
                granularity=granularity,
                sort_key=key,
                label=labels[key],
                series=series,
                reps_sum=b["reps"],
                peso_sum=b["peso"],
                rir_sum=b["rir"],
                rm_max=b["rm_max"],
                rendimiento=b["perf"] / series,
            )
        )
    return out


def _period_metrics(
    db_path: str,
    filtro: SummaryFilter,
    granularidad: str,
    ventana: Window,
) -> list[PeriodAggregate]:
    """Wrapper sobre aggregate_sets acotado a la ventana calendario.

    Todo set dentro de [ventana.start, ventana.end] pertenece a un periodo que
    intersecta la ventana; las semanas/meses parciales quedan cubiertas.
    """
    return aggregate_sets(
        db_path,
        filtro.muscles,
        filtro.exercises,
        granularidad,
        ventana.start.isoformat(),
        ventana.end.isoformat(),
    )


def totals_by_period(aggregates: Iterable[PeriodAggregate]) -> dict[int, _PeriodTotals]:
    """Colapsa entidades por periodo (para tooltips global/músculo)."""
    totals: dict[int, list[float]] = {}
    meta: dict[int, tuple[str, str, str]] = {}
    for pa in aggregates:
        slot = totals.setdefault(pa.sort_key, [0.0, 0.0, 0.0, 0.0, float("-inf")])
        slot[0] += pa.series
        slot[1] += pa.reps_sum
        slot[2] += pa.peso_sum
        slot[3] += pa.rir_sum
        slot[4] = max(slot[4], pa.rm_max)
        meta[pa.sort_key] = (pa.granularity, pa.label, pa.grupo_muscular + "|" + pa.entidad)
    out: dict[int, _PeriodTotals] = {}
    for key, slot in totals.items():
        gran, label, _ = meta[key]
        out[key] = _PeriodTotals(
            granularity=gran,
            sort_key=key,
            label=label,
            series=int(slot[0]),
            reps_sum=slot[1],
            peso_sum=slot[2],
            rir_sum=slot[3],
            rm_max=slot[4],
        )
    return out


def mean_growth(values: Sequence[float]) -> float | None:
    """Media aritmética de crecimientos; None si no hay valores."""
    if not values:
        return None
    return sum(values) / len(values)


def _collapse_entity_rows(
    aggs: list[PeriodAggregate], order: Sequence[str], *, include_rm: bool
) -> tuple[RowMetrics, ...]:
    """Una fila RowMetrics por entidad en ``order`` colapsando sus periodos.

    Δ = media de crecimiento de los periodos de la entidad en la ventana.
    Medias de reps/peso/RIR ponderadas por series (suma/cuenta). El RM entre
    ejercicios distintos NO es comparable: si la fila agrupa >1 ejercicio
    (nivel músculo/global) se fuerza rm_max=None salvo que include_rm=True y
    la entidad sea un único ejercicio.
    """
    by_entity: dict[str, list[PeriodAggregate]] = {}
    for pa in aggs:
        by_entity.setdefault(pa.entidad, []).append(pa)
    rows: list[RowMetrics] = []
    for name in order:
        periods = by_entity.get(name, [])
        if not periods:
            rows.append(RowMetrics(name, None, None, None, None, None, None))
            continue
        series_total = sum(p.series for p in periods)
        delta = round1(mean_growth([p.crecimiento for p in periods]))
        single_entity = len({p.entidad for p in periods}) == 1
        rm = round1(max(p.rm_max for p in periods)) if (include_rm and single_entity) else None
        rows.append(
            RowMetrics(
                etiqueta=name,
                delta_pct=delta,
                series=series_total,
                reps_media=round1(sum(p.reps_sum for p in periods) / series_total),
                # La columna Peso solo aplica a la vista por periodo de un
                # ejercicio; en filas colapsadas por entidad no se muestra.
                peso_medio=None,
                rir_medio=round1(sum(p.rir_sum for p in periods) / series_total),
                rm_max=rm,
            )
        )
    return tuple(rows)


def _period_rows_desc(pa_list: list[PeriodAggregate]) -> tuple[RowMetrics, ...]:
    """Filas por periodo, más reciente primero (presentación desc).

    Mantiene contrato legacy para tests que esperan RowMetrics con etiqueta canónica
    (Semana N / Agosto). UX-3 revisada usa HistoricalPeriodRow para exercise.
    """
    rows: list[RowMetrics] = []
    for pa in sorted(pa_list, key=lambda p: p.sort_key, reverse=True):
        rows.append(
            RowMetrics(
                etiqueta=pa.label,
                delta_pct=round1(pa.crecimiento),
                series=pa.series,
                reps_media=round1(pa.reps_media),
                peso_medio=round1(pa.peso_medio),
                rir_medio=round1(pa.rir_medio),
                rm_max=round1(pa.rm_max),
            )
        )
    return tuple(rows)
