"""Typed domain models and domain exceptions at service boundaries."""

from dataclasses import dataclass, field


class ValidationError(ValueError):
    """Domain validation failure. Subclasses ValueError for route compatibility."""


class NotFoundError(ValueError):
    """A requested domain object does not exist."""


class ConflictError(ValueError):
    """An operation conflicts with existing domain state (e.g. duplicate name)."""


@dataclass(frozen=True)
class TrainingSetInput:
    """A set submitted from a form, before persistence."""

    ejercicio: str
    kg: float | str
    reps: float | str
    rir: float | str


@dataclass(frozen=True)
class TrainingSet:
    """A persisted set row."""

    ejercicio: str
    set_orden: int
    reps: float | None = None
    kg: float | None = None
    rir: float | None = None
    origen: str = "google"


@dataclass(frozen=True)
class Session:
    """A training day: cycle week, weekday and its ordered sets."""

    semana: int
    dia: str
    fecha: str
    sets: list[TrainingSet] = field(default_factory=list)


@dataclass(frozen=True)
class TemplateInput:
    """A template submitted from a form."""

    nombre: str
    ejercicios: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Template:
    """A stored workout template."""

    id: int
    nombre: str
    clasificacion: str
    updated_at: str
    ejercicios: list[str] = field(default_factory=list)
    updated: bool = False
