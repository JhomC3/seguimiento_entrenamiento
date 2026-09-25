"""Modelos inmutables del resumen periodico (spec 007)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from src.summary_periods import RowMetrics

logger = logging.getLogger(__name__)


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
class SetDetail:
    """Serie individual para acordeón Día+ejercicio."""

    serie: int
    reps: float | None
    kg: float | None
    rir: float | None
    descanso_seg: float | None


@dataclass(frozen=True)
class HistoricalPeriodRow:
    """Fila histórica por periodo para vista exercise (no modifica RowMetrics).

    periodo = visible S<n> · DD-MM-YY / S<n> · DD-MM-YY / MM-YY
    periodo_aria = lectura única AT
    periodo_id = gran|periodo_norm|entity_norm (nunca etiqueta visible)
    """

    periodo: str
    periodo_aria: str
    periodo_id: str
    sort_key: int
    metrics: RowMetrics
    fecha_iso: str | None
    semana: int | None
    detalles: tuple[SetDetail, ...] = ()


@dataclass(frozen=True)
class SummaryTab:
    """Pestaña prerenderizable del panel.

    filas = para global/muscle (RowMetrics)
    historical_rows = para exercise (HistoricalPeriodRow). Unión explícita
    para jinja: ramificar por nivel antes de acceder a métricas.
    """

    titulo: str
    nivel: str
    filas: tuple[RowMetrics, ...] = ()
    historical_rows: tuple[HistoricalPeriodRow, ...] = ()


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
