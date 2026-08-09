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


@dataclass(frozen=True)
class NutritionEntryInput:
    """A food entry submitted from the nutrition form, before persistence."""

    alimento: str
    cantidad_g: float | str


@dataclass(frozen=True)
class AlimentoInput:
    """A catalog food submitted from the create-food form (per 100 g)."""

    nombre: str
    categoria: str = ""
    kcal: float = 0.0
    carbohidratos: float = 0.0
    fibra: float = 0.0
    proteina: float = 0.0
    grasa: float = 0.0
    hierro: float = 0.0
    calcio: float = 0.0
    vitamina_c: float = 0.0
    vitamina_a: float = 0.0


@dataclass(frozen=True)
class HealthRecordInput:
    """A single Health Connect operation from POST /sync/health-connect.

    Mirrors health-sync-contract.md §4: op (UPSERT|DELETE), stable record type,
    revision (lastModifiedTime epoch ms) for conditional updates, and a
    versioned raw value snapshot.
    """

    op: str
    hc_id: str
    record_type: str
    revision: int
    start_epoch_ms: int | None = None
    end_epoch_ms: int | None = None
    data_origin_package: str | None = None
    time_zone_offset_minutes: int | None = None
    payload_schema_version: int = 1
    value: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HealthSyncPayload:
    """Body of POST /sync/health-connect."""

    schema_version: int
    device_id: str
    operations: list[HealthRecordInput]


@dataclass(frozen=True)
class OperationAck:
    """Server-side acknowledgement for one accepted operation."""

    hc_id: str
    revision: int


@dataclass(frozen=True)
class RejectedOperation:
    """Server-side rejection detail for one operation."""

    hc_id: str
    revision: int
    reason: str


@dataclass(frozen=True)
class IngestResult:
    """Result of applying one batch: exact acks per hc_id + revision."""

    received: int
    accepted: list[OperationAck]
    rejected: list[RejectedOperation]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)
