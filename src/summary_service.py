"""Contrato mínimo de resumen periódico (Fase 2 — C1).

Define tipos inmutables Window y RowMetrics y funciones puras para:
- ventana calendario 4/8 semanas,
- intersección de periodos día/semana/mes con la ventana,
- etiquetas centralizadas y ordenables,
- redondeo a un decimal.

Sin acceso a DB, sin templates, sin JS. Toda función es pura y server-authoritative.
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from config import MUSCLE_CATEGORIES
from src.db_connection import read_connection
from src.metrics_engine import get_exercises_baselines, rm_ajustado
from src.models import ValidationError
from src.training_service import calculate_cycle_week, parse_cycle_start

logger = logging.getLogger(__name__)

WindowWeeks = Literal[4, 8]

MONTH_NAMES_ES: tuple[str, ...] = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)

ALLOWED_WINDOWS: tuple[int, ...] = (4, 8)


@dataclass(frozen=True)
class Window:
    """Ventana calendario cerrada [start, end] de N semanas NATURALES.

    Invariantes:
    - weeks ∈ {4, 8}
    - start <= end
    - (end - start).days == weeks*7 - 1  → exactamente weeks*7 días inclusivos
      (4 semanas = 28 días; 8 semanas = 56 días).
    """

    start: date
    end: date
    weeks: WindowWeeks


@dataclass(frozen=True)
class RowMetrics:
    """Métricas de un periodo ya agregado para presentación.

    Un campo en None significa ausencia de dato y debe renderizarse como "—",
    nunca como 0. RM es siempre máximo del periodo, Δ es media de crecimiento
    (rendimiento-100) de los periodos incluidos en la ventana.
    """

    etiqueta: str
    delta_pct: float | None
    series: int | None
    reps_media: float | None
    peso_medio: float | None
    rir_medio: float | None
    rm_max: float | None


def calendar_window(end: date, weeks: int) -> Window:
    """Calcula la ventana calendario de N semanas NATURALES terminada en ``end``.

    Fin = última fecha con datos.
    Inicio = fin - (N*7 - 1) días  → la ventana inclusiva mide exactamente
    N*7 días (4 semanas = 28 días; 8 semanas = 56 días).

    Solo N ∈ {4, 8}. Cualquier otro valor lanza ``ValidationError``.
    """
    if weeks not in ALLOWED_WINDOWS:
        raise ValidationError(f"La ventana debe ser 4 u 8 semanas, recibido: {weeks}")
    # N semanas naturales: N*7 días inclusivos → desplazamiento N*7 - 1.
    start = end - timedelta(days=weeks * 7 - 1)
    # Cast para mypy: weeks ya validado como 4|8.
    return Window(start=start, end=end, weeks=weeks)  # type: ignore[arg-type]


def day_intersects(window: Window, day: date) -> bool:
    """True si el día cae dentro de la ventana inclusive."""
    return window.start <= day <= window.end


def _week_bounds(semana: int, cycle_start: date | None = None) -> tuple[date, date]:
    """Rango [lunes, domingo] de la semana de ciclo N."""
    if semana < 1:
        raise ValidationError(f"Semana inválida: {semana}")
    base = cycle_start if cycle_start is not None else parse_cycle_start()
    monday = base - timedelta(days=base.weekday())
    start = monday + timedelta(days=(semana - 1) * 7)
    end = start + timedelta(days=6)
    return start, end


def week_intersects(
    window: Window,
    semana: int,
    cycle_start: date | None = None,
) -> bool:
    """True si la semana de ciclo intersecta la ventana (solape de rangos)."""
    w_start, w_end = _week_bounds(semana, cycle_start)
    return w_end >= window.start and w_start <= window.end


def month_intersects(window: Window, year: int, month: int) -> bool:
    """True si el mes [1º, último día] intersecta la ventana.

    Meses parciales al inicio o al final se incluyen si hay solape, aunque sea
    de un solo día.
    """
    if not 1 <= month <= 12:
        raise ValidationError(f"Mes inválido: {month}")
    m_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    m_end = date(year, month, last_day)
    return m_end >= window.start and m_start <= window.end


def period_intersects(
    window: Window,
    granularity: str,
    period: date | int | tuple[int, int],
    cycle_start: date | None = None,
) -> bool:
    """Dispatcher genérico para tests de intersección.

    - granularity == "day": period es date
    - "week": period es int (semana de ciclo)
    - "month": period es tuple (year, month)
    """
    if granularity == "day":
        if not isinstance(period, date):
            raise ValidationError("Para granularity day el periodo debe ser date")
        return day_intersects(window, period)
    if granularity == "week":
        if not isinstance(period, int):
            raise ValidationError("Para granularity week el periodo debe ser int")
        return week_intersects(window, period, cycle_start)
    if granularity == "month":
        if not isinstance(period, tuple) or len(period) != 2:
            raise ValidationError("Para granularity month el periodo debe ser (year, month)")
        y, m = period
        return month_intersects(window, y, m)
    raise ValidationError(f"Granularidad no soportada: {granularity}")


# --- Etiquetas centralizadas ---


def day_label(d: date) -> str:
    """Etiqueta DD/MM/YYYY con ceros a la izquierda."""
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def week_label(semana: int) -> str:
    """Etiqueta canónica de semana de ciclo."""
    return f"Semana {semana}"


def month_label(year: int, month: int) -> str:
    """Etiqueta canónica de mes (nombre español, sin año para evitar duplicar).

    El año se conserva en la clave de ordenación; la etiqueta es solo presentación.
    """
    if not 1 <= month <= 12:
        raise ValidationError(f"Mes inválido: {month}")
    # year validado implícitamente al construir date en month_intersects; aquí solo
    # rango de mes, pero mantenemos chequeo de año razonable (>1900) por claridad.
    if year < 1900 or year > 3000:
        raise ValidationError(f"Año inválido: {year}")
    return MONTH_NAMES_ES[month - 1]


# --- Claves de ordenación cronológica ---


def day_sort_key(d: date) -> date:
    """Clave cronológica para ordenar días (no lexicográfica)."""
    return d


def week_sort_key(semana: int) -> int:
    """Clave cronológica para ordenar semanas (número de ciclo)."""
    return semana


def month_sort_key(year: int, month: int) -> int:
    """Clave cronológica YYYYMM para ordenar meses sin ambigüedad lexicográfica."""
    if not 1 <= month <= 12:
        raise ValidationError(f"Mes inválido: {month}")
    return year * 100 + month


# --- Redondeo ---


def round1(value: float | None) -> float | None:
    """Redondea a un decimal para presentación; None permanece None.

    Usa round() Python (bankers) con un decimal, consistente con el resto del
    dominio donde también se aplica round(x,1).
    """
    if value is None:
        return None
    # mypy: value es float aquí
    return round(float(value), 1)


# --- C2: agregación periódica compartida (panel + tooltip) ---

GRANULARITIES: tuple[str, ...] = ("day", "week", "month")


@dataclass(frozen=True)
class SummaryFilter:
    """Filtro de agregación. Ambos vacíos = global (todo el cuerpo).

    Músculos comparan contra ``ejercicios.grupo_muscular`` (LOWER) y ejercicios
    contra ``training_sets.ejercicio`` (LOWER); SQL siempre parametrizado.
    """

    muscles: tuple[str, ...] = ()
    exercises: tuple[str, ...] = ()


@dataclass(frozen=True)
class PeriodAggregate:
    """Métricas de UN periodo para UNA entidad (ejercicio) ya agregadas.

    Acumuladores crudos + medias derivadas. RM es SIEMPRE el máximo del
    periodo (nunca promedio). RIR ausente cuenta como 0 (semántica vigente:
    metrics_engine hace ``fillna(0)`` — serie sin RIR no se marca como fallo).
    """

    grupo_muscular: str
    entidad: str
    granularity: str
    sort_key: int
    label: str
    series: int
    reps_sum: float
    peso_sum: float
    rir_sum: float
    rm_max: float
    rendimiento: float

    @property
    def crecimiento(self) -> float:
        """Δ del motor actual: rendimiento relativo − 100."""
        return self.rendimiento - 100.0

    @property
    def reps_media(self) -> float:
        return self.reps_sum / self.series

    @property
    def peso_medio(self) -> float:
        return self.peso_sum / self.series

    @property
    def rir_medio(self) -> float:
        return self.rir_sum / self.series


@dataclass(frozen=True)
class _PeriodTotals:
    """Colapso de varias entidades en un mismo periodo (tooltip global/músculo)."""

    granularity: str
    sort_key: int
    label: str
    series: int
    reps_sum: float
    peso_sum: float
    rir_sum: float
    rm_max: float

    @property
    def reps_media(self) -> float:
        return self.reps_sum / self.series

    @property
    def peso_medio(self) -> float:
        return self.peso_sum / self.series

    @property
    def rir_medio(self) -> float:
        return self.rir_sum / self.series


@dataclass(frozen=True)
class SummaryTab:
    """Pestaña prerenderizable del panel."""

    titulo: str
    nivel: str
    filas: tuple[RowMetrics, ...]


@dataclass(frozen=True)
class PeriodSummary:
    """Resultado completo del panel derecho.

    estado: ready (datos), empty (sin sets válidos), error (fallo registrado,
    nunca propagado a HTTP). nivel refleja la vista principal de la selección.
    """

    estado: Literal["ready", "empty", "error"]
    nivel: Literal["global", "muscle", "exercise"]
    granularidad: str
    semanas: int
    tabs: tuple[SummaryTab, ...]
    # Mensaje opcional del estado vacío (p. ej. último registro de la
    # selección cuando la ventana global no la cubre). Nunca se usa para
    # anclar la ventana: gráfica y panel comparten el mismo fin temporal.
    hint: str = ""


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
    """Filas por periodo, más reciente primero (presentación desc)."""
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


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


def build_period_summary(
    db_path: str,
    musculos: Sequence[str],
    ejercicios: Sequence[str],
    granularidad: str,
    semanas: int,
) -> PeriodSummary:
    """Punto de entrada del panel derecho (server-authoritative).

    Reglas de pestañas:
    - global (sin selección): una tab Resumen con TODOS los músculos en orden
      config.MUSCLE_CATEGORIES, sin RM (no comparable entre ejercicios).
    - 1 músculo: una tab con sus ejercicios (orden estable alfabético) con RM.
    - n>1 músculos: [Resumen (músculos seleccionados, orden de selección)] +
      una tab por músculo.
    - ejercicios seleccionados: nivel exercise; [Resumen] + una tab por
      ejercicio (orden de selección); el Resumen muestra filas por EJERCICIO
      del/de los músculo(s) implicados (o filas de músculo si hay ≥2 músculos).
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
        aggs = _period_metrics(
            db_path, SummaryFilter(tuple(muscles), tuple(exercises)), granularidad, window
        )
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
                    "Queda fuera de las ventanas disponibles (4 u 8 semanas). "
                    "Revisa el historial."
                )
        except Exception:
            logger.exception("hint de estado vacío falló")
        return PeriodSummary("empty", nivel, granularidad, semanas, (), hint)

    tabs: list[SummaryTab] = []

    if nivel == "global":
        fixed = flatten_muscle_categories()
        tabs.append(SummaryTab("Resumen", "global", _collapse_entity_rows_global(aggs, fixed)))

    elif nivel == "muscle" and len(muscles) == 1:
        muscle = muscles[0]
        catalog_order = sorted({pa.entidad for pa in aggs}, key=str.lower)
        tabs.append(
            SummaryTab(
                muscle, "muscle", _collapse_entity_rows(aggs, catalog_order, include_rm=True)
            )
        )

    elif nivel == "exercise" and len(exercises) == 1 and not muscles:
        # Un único ejercicio: tabla comparativa por periodo (sin tab Resumen).
        own = [pa for pa in aggs if pa.entidad == exercises[0]]
        tabs.append(SummaryTab(exercises[0], "exercise", _period_rows_desc(own)))

    else:
        # Multi-selección: Resumen primero, luego elementos en orden de selección.
        if len(muscles) >= 2:
            resumen_filas: tuple[RowMetrics, ...] = _collapse_entity_rows_multi_muscle(
                aggs, muscles
            )
        else:
            involved = [pa.entidad for pa in aggs]
            resumen_order = sorted(dict.fromkeys(involved), key=str.lower)
            resumen_filas = _collapse_entity_rows(aggs, resumen_order, include_rm=True)
        tabs.append(SummaryTab("Resumen", nivel, resumen_filas))

        for ejercicio in exercises:
            own = [pa for pa in aggs if pa.entidad == ejercicio]
            tabs.append(SummaryTab(ejercicio, "exercise", _period_rows_desc(own)))
        # Tabs por músculo SOLO en multi-músculos puro; en mixto el Resumen ya
        # muestra los músculos (contrato §5 de Fase 2).
        if not exercises:
            for muscle in muscles:
                own = [pa for pa in aggs if pa.grupo_muscular.lower() == muscle.lower()]
                ent_order = sorted({p.entidad for p in own}, key=str.lower)
                tabs.append(
                    SummaryTab(
                        muscle, "muscle", _collapse_entity_rows(own, ent_order, include_rm=True)
                    )
                )

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
