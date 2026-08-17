"""Dominio de splits de entrenamiento.

Un split distribuye ejercicios de LUNES a DOMINGO; cada item colocado cuenta
como una serie. Las métricas se calculan SIEMPRE aquí (server-authoritative),
nunca se confía en datos del navegador.
"""

from src.database import (
    delete_split as _delete_split,
)
from src.database import (
    find_split_by_nombre,
    get_split,
    get_split_catalog,
    insert_split,
    update_split,
)
from src.models import (
    SPLIT_DAYS,
    ConflictError,
    NotFoundError,
    Split,
    SplitDaySummary,
    SplitInput,
    SplitItem,
    SplitItemInput,
    SplitMetrics,
    ValidationError,
)

__all__ = [
    "HIIT_GROUP",
    "HIIT_ITEM_TYPE",
    "HIIT_NAME",
    "compute_split_metrics",
    "delete_split",
    "get_split_board",
    "save_split",
    "split_items_from_form",
]

HIIT_ITEM_TYPE = "hiit"
HIIT_NAME = "HIIT"
HIIT_GROUP = "HIIT"

# Orden canónico de días para métricas y render (mismo vocabulario que
# training_service.DIA_MAP; SPLIT_DAYS es la única fuente de validación).
_DAY_INDEX = {day: idx for idx, day in enumerate(SPLIT_DAYS)}


def _catalog_groups(db_path: str) -> dict[str, str]:
    """Mapa lower(nombre) -> grupo_muscular autoritativo del catálogo."""
    return {c["ejercicio"].strip().lower(): c["grupo_muscular"] for c in get_split_catalog(db_path)}


def _normalize_item(
    item: SplitItemInput, catalog_lower: dict[str, str]
) -> tuple[str, str, str, str]:
    """Valida un item y devuelve (dia, item_type, ejercicio, grupo_muscular).

    El grupo muscular del cliente NUNCA se acepta: se deriva del catálogo o
    del tipo especial HIIT. Los mensajes de error no reflejan valores del
    cliente (mensaje seguro).
    """
    dia = str(item.dia).strip().upper()
    if dia not in SPLIT_DAYS:
        raise ValidationError("Día inválido en el split.")
    if item.item_type == HIIT_ITEM_TYPE:
        if str(item.ejercicio).strip().upper() != HIIT_NAME:
            raise ValidationError("El elemento HIIT debe llamarse HIIT.")
        return dia, HIIT_ITEM_TYPE, HIIT_NAME, HIIT_GROUP
    nombre = str(item.ejercicio).strip()
    grupo = catalog_lower.get(nombre.lower())
    if not grupo:
        raise ValidationError("El ejercicio no existe en el catálogo.")
    return dia, "ejercicio", nombre, grupo


def split_items_from_form(
    dias: list[str], item_types: list[str], ejercicios: list[str]
) -> list[SplitItemInput]:
    """Construye items validando la alineación de los arrays del formulario."""
    if not (len(dias) == len(item_types) == len(ejercicios)):
        raise ValidationError("Datos incompletos del split.")
    return [
        SplitItemInput(dia=d, item_type=t, ejercicio=e)
        for d, t, e in zip(dias, item_types, ejercicios)
    ]


def save_split(db_path: str, split_input: SplitInput, split_id: int | None = None) -> Split:
    """Upsert por nombre (patrón plantilla/guardar); con split_id edita/renombra."""
    nombre = str(split_input.nombre).strip()
    if not nombre:
        raise ValidationError("El nombre del split no puede estar vacío.")
    catalog_lower = _catalog_groups(db_path)
    items = [_normalize_item(i, catalog_lower) for i in split_input.items]
    if not items:
        raise ValidationError("El split debe tener al menos un ejercicio.")

    def _to_split(sid: int, updated: bool) -> Split:
        row = get_split(db_path, sid)
        return Split(
            id=sid,
            nombre=nombre,
            updated_at=(row or {}).get("updated_at", ""),
            updated=updated,
        )

    if split_id is not None:
        existing = find_split_by_nombre(db_path, nombre)
        if existing is not None and existing != split_id:
            raise ConflictError(f"Ya existe un split llamado '{nombre}'.")
        update_split(db_path, split_id, nombre, items)
        return _to_split(split_id, True)

    existing = find_split_by_nombre(db_path, nombre)
    if existing is not None:
        update_split(db_path, existing, nombre, items)
        return _to_split(existing, True)
    pid = insert_split(db_path, nombre, items)
    return _to_split(pid, False)


def delete_split(db_path: str, split_id: int) -> None:
    if get_split(db_path, split_id) is None:
        raise NotFoundError("El split no existe.")
    _delete_split(db_path, split_id)


def _items_from_rows(split: dict) -> list[SplitItem]:
    return [
        SplitItem(
            id=i["id"],
            dia=i["dia"],
            orden=i["orden"],
            item_type=i["item_type"],
            ejercicio=i["ejercicio"],
            grupo_muscular=i["grupo_muscular"],
        )
        for i in split["items"]
    ]


def compute_split_metrics(items: list[SplitItem]) -> SplitMetrics:
    """1 item = 1 serie. Métricas por día, ejercicio, grupo y totales semanales.

    `days` incluye SIEMPRE los 7 días canónicos (los vacíos con series 0) para
    que el resumen muestre la semana completa.
    """
    total = len(items)
    by_exercise: dict[str, int] = {}
    by_group: dict[str, int] = {}
    by_group_exercises: dict[str, dict[str, int]] = {}
    per_day: dict[str, list[SplitItem]] = {}
    for it in items:
        by_exercise[it.ejercicio] = by_exercise.get(it.ejercicio, 0) + 1
        by_group[it.grupo_muscular] = by_group.get(it.grupo_muscular, 0) + 1
        group_ex = by_group_exercises.setdefault(it.grupo_muscular, {})
        group_ex[it.ejercicio] = group_ex.get(it.ejercicio, 0) + 1
        per_day.setdefault(it.dia, []).append(it)

    days: list[SplitDaySummary] = []
    for dia in SPLIT_DAYS:
        day_items = per_day.get(dia, [])
        d_ex: dict[str, int] = {}
        d_g: dict[str, int] = {}
        d_g_ex: dict[str, dict[str, int]] = {}
        for it in day_items:
            d_ex[it.ejercicio] = d_ex.get(it.ejercicio, 0) + 1
            d_g[it.grupo_muscular] = d_g.get(it.grupo_muscular, 0) + 1
            group_ex = d_g_ex.setdefault(it.grupo_muscular, {})
            group_ex[it.ejercicio] = group_ex.get(it.ejercicio, 0) + 1
        days.append(
            SplitDaySummary(
                dia=dia,
                series=len(day_items),
                by_exercise=d_ex,
                by_group=d_g,
                by_group_exercises=d_g_ex,
            )
        )

    return SplitMetrics(
        total_series=total,
        by_group=by_group,
        by_exercise=by_exercise,
        by_group_exercises=by_group_exercises,
        days=days,
    )


def get_split_board(db_path: str, split_id: int) -> dict:
    """Split + métricas para render del board. NotFound si no existe."""
    split = get_split(db_path, split_id)
    if split is None:
        raise NotFoundError("El split no existe.")
    items = _items_from_rows(split)
    return {
        "split": Split(
            id=split["id"], nombre=split["nombre"], updated_at=split["updated_at"], items=items
        ),
        "metrics": compute_split_metrics(items),
    }
