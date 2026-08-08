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
