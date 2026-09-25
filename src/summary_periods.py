"""Ventana calendario, intersecciones, etiquetas y formatos (spec 007)."""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from src.models import ValidationError
from src.training_service import calculate_cycle_week, parse_cycle_start

logger = logging.getLogger(__name__)

WindowWeeks = Literal[1, 2, 3, 4, 5, 6, 7, 8]

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

MESES_CORTO: tuple[str, ...] = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

ALLOWED_WINDOWS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)


@dataclass(frozen=True)
class Window:
    """Ventana calendario cerrada [start, end] de N semanas NATURALES.

    Invariantes:
    - weeks ∈ {1..8}
    - start <= end
    - (end - start).days == weeks*7 - 1  → exactamente weeks*7 días inclusivos
      (1 semana = 7 días; 8 semanas = 56 días).
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
    N*7 días (1 semana = 7 días; 8 semanas = 56 días).

    Solo N ∈ {1..8}. Cualquier otro valor lanza ``ValidationError``.
    """
    if weeks not in ALLOWED_WINDOWS:
        raise ValidationError(f"La ventana debe ser 1–8 semanas, recibido: {weeks}")
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


def week_start_date(semana: int, cycle_start: date | None = None) -> date:
    """Lunes de la semana N del ciclo (etiqueta de tooltip UX-2).

    Semana 1 = lunes de la semana que contiene ``cycle_start``; si el ciclo
    empieza a mitad de semana, la semana 1 arranca el lunes anterior.
    ``cycle_start=None`` usa la configuración del ciclo (``parse_cycle_start()``).
    Solo presentación: no altera las etiquetas del resumen periódico.
    """
    start, _ = _week_bounds(semana, cycle_start)
    return start


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


# --- Formatos compactos UX-3 revisada (no modifican etiquetas canónicas) ---


def historical_period_id(granularidad: str, periodo_norm: str, entity_norm: str) -> str:
    """ID canónico gráfica→fila: gran|periodo_norm|entity_norm.

    periodo_norm: day=YYYY-MM-DD, week=str(semana), month=YYYY-MM.
    entity_norm: strip().casefold(). No usar etiqueta visible.
    """
    return f"{granularidad}|{periodo_norm}|{entity_norm.strip().casefold()}"


def format_day_compact(d: date, ciclo_start: date | None = None) -> tuple[str, str]:
    """Visible S<n> · DD-MM-YY, aria Semana N · DD de mes de YYYY."""
    semana = calculate_cycle_week(
        d, ciclo_start if ciclo_start is not None else parse_cycle_start()
    )
    visible = f"S{semana} · {d.day:02d}-{d.month:02d}-{str(d.year)[2:]}"
    aria = f"Semana {semana} · {d.day} de {MONTH_NAMES_ES[d.month - 1].lower()} de {d.year}"
    return visible, aria


def format_week_compact(semana: int, ciclo_start: date | None = None) -> tuple[str, str]:
    """Visible S<n> · DD-MM-YY, aria Semana N · DD de mes de YYYY.

    Reutiliza week_start_date (no ISO week).
    """
    start = week_start_date(semana, ciclo_start)
    visible = f"S{semana} · {start.day:02d}-{start.month:02d}-{str(start.year)[2:]}"
    aria = f"Semana {semana} · {start.day} de {MONTH_NAMES_ES[start.month - 1].lower()} de {start.year}"
    return visible, aria


def format_month_compact(year: int, month: int) -> tuple[str, str]:
    """Visible MM-YY, aria mes de YYYY."""
    if not 1 <= month <= 12:
        raise ValidationError(f"Mes inválido: {month}")
    if year < 1900 or year > 3000:
        raise ValidationError(f"Año inválido: {year}")
    visible = f"{month:02d}-{str(year)[2:]}"
    aria = f"{MONTH_NAMES_ES[month - 1].lower()} de {year}"
    return visible, aria


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
