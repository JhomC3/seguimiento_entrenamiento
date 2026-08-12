"""View models: expose only the values templates need, never DB access."""

from dataclasses import dataclass, field


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
    rm: float | None


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


@dataclass(frozen=True)
class AnalysisKpis:
    """KPIs compactos de la cabecera de análisis."""

    pfr_actual: float | None = None
    pfr_variacion: float | None = None  # % vs baseline (100)
    volumen_semana: float | None = None
    sets_fallo_semana: int = 0
    peso_actual: float | None = None
    sueno_anoche: float | None = None


@dataclass(frozen=True)
class AnalysisViewModel:
    """Estado completo de la vista de análisis: KPIs + figura serializada."""

    kpis: AnalysisKpis
    chart_json: str
    nivel: str
    focus: str | None
    active_layers: tuple[str, ...]
    rango: int | None
    has_data: bool
