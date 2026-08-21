"""View models: expose only the values templates need, never DB access."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogExercise:
    name: str
    category: str


@dataclass(frozen=True)
class CatalogGroup:
    name: str
    exercises: list["CatalogExercise"]


@dataclass(frozen=True)
class DateDay:
    iso: str
    label: str
    has_data: bool
    selected: bool


@dataclass(frozen=True)
class DateNavigatorViewModel:
    dates: list[DateDay]
    selected_iso: str
    today_iso: str


@dataclass(frozen=True)
class EditorRow:
    ejercicio: str
    kg: float | None
    reps: float | None
    rir: float | None
    descanso_seg: float | None = None
    rm: float | None = None


@dataclass(frozen=True)
class SessionEditorViewModel:
    fecha_iso: str
    fecha_display: str
    semana: int
    dia: str
    rows: list[EditorRow]
    readonly: bool
    has_data: bool
    error: str | None
    success: str | None
    catalog: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NutritionEntryRow:
    orden: int
    alimento: str
    cantidad_g: float
    kcal: float
    carbohidratos: float
    fibra: float
    proteina: float
    grasa: float
    hierro: float
    calcio: float
    vitamina_c: float
    vitamina_a: float


@dataclass(frozen=True)
class NutritionEditorViewModel:
    fecha_iso: str
    fecha_display: str
    rows: list[NutritionEntryRow]
    totals: dict[str, float]
    catalog: list[str] = field(default_factory=list)
    has_data: bool = False
    readonly: bool = False
    error: str | None = None
    success: str | None = None
    objetivo: dict[str, float] = field(default_factory=dict)
    consumido: dict[str, float] = field(default_factory=dict)
    parametros: dict[str, float] = field(default_factory=dict)
    prefilled: bool = False
    prefill_source: str | None = None
