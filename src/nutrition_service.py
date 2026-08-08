"""Nutrition domain service: validation, catalog-based calculation, diary writes.

The catalog (`alimentos`, per 100 g) is the authoritative source for new
entries: `ROUND_HALF_UP(valor_100g * gramos / 100)` per nutrient, matching the
observed behavior of the source spreadsheet (never kcal from macros).
Imported rows keep the values delivered by the sheet; the service never edits
them on save.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from src.database import (
    delete_diario_by_fecha,
    find_alimento,
    insert_alimento,
    replace_diario_by_fecha,
)
from src.models import (
    AlimentoInput,
    ConflictError,
    NotFoundError,
    NutritionEntryInput,
    ValidationError,
)

NUTRIENT_FIELDS: tuple[str, ...] = (
    "kcal",
    "carbohidratos",
    "fibra",
    "proteina",
    "grasa",
    "hierro",
    "calcio",
    "vitamina_c",
    "vitamina_a",
)


def _sheet_round(value) -> float:
    """Redondeo a entero con half-up (equivalente a ROUND de Google Sheets)."""
    return float(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _validate_fecha_iso(fecha_iso: str) -> None:
    try:
        date.fromisoformat(fecha_iso)
    except (TypeError, ValueError):
        raise ValidationError(f"Fecha no válida: {fecha_iso!r}") from None


def _positive_float(value: float | str, field: str) -> float:
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValidationError(f"{field} no es un número válido: {value!r}") from None
    if parsed <= 0:
        raise ValidationError(f"{field} debe ser mayor que 0")
    return parsed


def _non_negative_float(value: float | str, field: str) -> float:
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValidationError(f"{field} no es un número válido: {value!r}") from None
    if parsed < 0:
        raise ValidationError(f"{field} no puede ser negativo")
    return parsed


def calculate_nutrients(food: dict, cantidad_g: float) -> dict[str, float]:
    """Calcula los nueve nutrientes para `cantidad_g` gramos desde el catálogo."""
    factor = Decimal(str(cantidad_g)) / Decimal(100)
    return {field: _sheet_round(Decimal(str(food[field])) * factor) for field in NUTRIENT_FIELDS}


_TARGET_EXTRA_FIELDS: tuple[tuple[str, str], ...] = (
    ("fibra_objetivo", "fibra"),
    ("hierro_objetivo", "hierro"),
    ("calcio_objetivo", "calcio"),
    ("vitamina_c_objetivo", "vitamina_c"),
    ("vitamina_a_objetivo", "vitamina_a"),
)


def objetivos_diarios(
    *,
    peso_kg: float,
    factor_proteina: float,
    factor_grasa: float,
    kcal_objetivo: float,
    extras: dict,
) -> dict[str, float]:
    """Objetivos del día con las fórmulas del documento (Atwater 4/4/9).

    proteina = round(peso x factor_proteina)
    grasa    = round(peso x factor_grasa)
    kcal     = round(kcal_objetivo)               (editable)
    carb     = round((kcal - 4*prot - 9*grasa) / 4)
    fibra/hierro/calcio/vitC/vitA: importados de la hoja (extras).
    """
    proteina = _sheet_round(Decimal(str(peso_kg)) * Decimal(str(factor_proteina)))
    grasa = _sheet_round(Decimal(str(peso_kg)) * Decimal(str(factor_grasa)))
    kcal = _sheet_round(Decimal(str(kcal_objetivo)))
    carbohidratos = _sheet_round(
        (
            Decimal(str(kcal_objetivo))
            - Decimal(4) * Decimal(str(proteina))
            - Decimal(9) * Decimal(str(grasa))
        )
        / Decimal(4)
    )
    target = {
        "kcal": kcal,
        "carbohidratos": carbohidratos,
        "proteina": proteina,
        "grasa": grasa,
    }
    for extra_key, field in _TARGET_EXTRA_FIELDS:
        target[field] = _sheet_round(Decimal(str(extras.get(extra_key, 0.0))))
    return target


def entries_from_form(alimentos: list[str], cantidades: list[str]) -> list[NutritionEntryInput]:
    """Une las listas paralelas del formulario; filas vacías se omiten, filas
    parcialmente rellenadas fallan."""
    entries: list[NutritionEntryInput] = []
    for alimento, cantidad in zip(alimentos, cantidades):
        name = str(alimento or "").strip()
        qty = str(cantidad or "").strip()
        if not name and not qty:
            continue
        if not name:
            raise ValidationError("Fila con cantidad pero sin alimento")
        if not qty:
            raise ValidationError(f"Fila '{name}' sin cantidad")
        _positive_float(qty, "Cantidad")
        entries.append(NutritionEntryInput(alimento=name, cantidad_g=qty))
    return entries


def save_diary(db_path: str, fecha_iso: str, entries: list[NutritionEntryInput]) -> None:
    """Reemplaza el día completo; los nutrientes se recalculan desde el catálogo."""
    _validate_fecha_iso(fecha_iso)
    rows: list[dict] = []
    for entry in entries:
        cantidad_g = _positive_float(entry.cantidad_g, "Cantidad")
        food = find_alimento(db_path, entry.alimento)
        if food is None:
            raise NotFoundError(f"Alimento no encontrado en el catálogo: {entry.alimento}")
        row = {"alimento": food["nombre"], "cantidad_g": cantidad_g}
        row.update(calculate_nutrients(food, cantidad_g))
        rows.append(row)
    replace_diario_by_fecha(db_path, fecha_iso, rows)


def delete_diary(db_path: str, fecha_iso: str) -> None:
    _validate_fecha_iso(fecha_iso)
    delete_diario_by_fecha(db_path, fecha_iso)


def create_alimento(db_path: str, alimento: AlimentoInput) -> None:
    nombre = alimento.nombre.strip()
    if not nombre:
        raise ValidationError("El nombre del alimento no puede estar vacío")
    if find_alimento(db_path, nombre) is not None:
        raise ConflictError(f"El alimento '{nombre}' ya existe en el catálogo")
    food: dict[str, float | str] = {"nombre": nombre, "categoria": alimento.categoria.strip()}
    for field in NUTRIENT_FIELDS:
        food[field] = _non_negative_float(getattr(alimento, field), field)
    insert_alimento(db_path, food)


def diary_totals(rows: list[dict]) -> dict[str, float]:
    """Totales del día sumando los nueve nutrientes almacenados."""
    return {
        field: round(sum(float(r.get(field) or 0.0) for r in rows), 2) for field in NUTRIENT_FIELDS
    }
