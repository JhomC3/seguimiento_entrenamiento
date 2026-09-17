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
    find_plantilla_alimentacion_by_nombre,
    insert_alimento,
    insert_plantilla_alimentacion,
    replace_diario_by_fecha,
    update_plantilla_alimentacion_rows,
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
    "magnesio",
    "zinc",
    "potasio",
    "sodio",
    "vitamina_d",
    "vitamina_e",
    "vitamina_k",
    "folato",
    "vitamina_b12",
    "vitamina_b6",
    "yodo",
    "selenio",
)

# Unidad canónica por nutriente en `alimentos` (por 100 g) y en
# `diario_alimentacion` (por fila). `vitamina_a` son mcg RAE: la hoja y la
# API hablan siempre en mcg, nunca en IU (1 mcg RAE = 3.33 IU de retinol).
NUTRIENT_UNITS: dict[str, str] = {
    "kcal": "kcal",
    "carbohidratos": "g",
    "fibra": "g",
    "proteina": "g",
    "grasa": "g",
    "hierro": "mg",
    "calcio": "mg",
    "vitamina_c": "mg",
    "vitamina_a": "mcg",
    "magnesio": "mg",
    "zinc": "mg",
    "potasio": "mg",
    "sodio": "mg",
    "vitamina_d": "mcg",
    "vitamina_e": "mg",
    "vitamina_k": "mcg",
    "folato": "mcg",
    "vitamina_b12": "mcg",
    "vitamina_b6": "mg",
    "yodo": "mcg",
    "selenio": "mcg",
}

# Objetivos diarios de micronutrientes para hombre de 31-50 años (DRI del
# Food and Nutrition Board; fichas NIH Office of Dietary Supplements):
# fibra 38 g AI 19-50 · hierro 8 mg RDA hombres 19-50 · calcio 1000 mg RDA
# 19-50 · vitamina C 90 mg RDA hombres (+35 mg fumadores) · vitamina A
# 900 mcg RAE RDA hombres · magnesio 420 mg RDA hombres 31-50 (400 mg en
# 19-30) · zinc 11 mg RDA hombres · potasio 3400 mg AI hombres 19+
# (NASEM 2019, antes 4700) · sodio 1500 mg AI 19-50 (NASEM 2019; CDRR 2300) ·
# vitamina D 15 mcg RDA 19-70 · vitamina E 15 mg RDA alfa-tocoferol ·
# vitamina K 120 mcg AI hombres 19+ · folato 400 mcg DFE RDA adultos ·
# vitamina B12 2.4 mcg RDA adultos · vitamina B6 1.3 mg RDA 19-50 ·
# yodo 150 mcg RDA adultos · selenio 55 mcg RDA adultos.
# Claves de `parametros_diarios` (`*_objetivo`). Carbohidratos, proteína y
# grasa NO están aquí: se calculan por Atwater desde peso/factores/kcal.
MICRO_DRI_TARGETS: dict[str, float] = {
    "fibra_objetivo": 38.0,
    "hierro_objetivo": 8.0,
    "calcio_objetivo": 1000.0,
    "vitamina_c_objetivo": 90.0,
    "vitamina_a_objetivo": 900.0,
    "magnesio_objetivo": 420.0,
    "zinc_objetivo": 11.0,
    "potasio_objetivo": 3400.0,
    "sodio_objetivo": 1500.0,
    "vitamina_d_objetivo": 15.0,
    "vitamina_e_objetivo": 15.0,
    "vitamina_k_objetivo": 120.0,
    "folato_objetivo": 400.0,
    "vitamina_b12_objetivo": 2.4,
    "vitamina_b6_objetivo": 1.3,
    "yodo_objetivo": 150.0,
    "selenio_objetivo": 55.0,
}

# Límites superiores tolerables (UL, NIH ODS). `fibra` no tiene UL
# establecido; `sodio` 2300 es el CDRR 2019 (no hay UL). Solo informativo
# para la UI: nunca bloquean el guardado.
MICRO_UL: dict[str, float | None] = {
    "fibra": None,
    "hierro": 45.0,
    "calcio": 2500.0,
    "vitamina_c": 2000.0,
    "vitamina_a": 3000.0,
    "magnesio": 350.0,
    "zinc": 40.0,
    "potasio": None,
    "sodio": 2300.0,
    "vitamina_d": 100.0,
    "vitamina_e": 1000.0,
    "vitamina_k": None,
    "folato": 1000.0,
    "vitamina_b12": None,
    "vitamina_b6": 100.0,
    "yodo": 1100.0,
    "selenio": 400.0,
}

# Techo de plausibilidad para un alimento por 100 g: ni el aceite puro
# supera ~900 kcal. Por encima es un error de escala de la hoja (p. ej.
# valores por unidad o por lote), no un alimento real.
MAX_KCAL_PER_100G = 900.0


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
    """Calcula los nutrientes para `cantidad_g` gramos desde el catálogo."""
    factor = Decimal(str(cantidad_g)) / Decimal(100)
    return {field: _sheet_round(Decimal(str(food[field])) * factor) for field in NUTRIENT_FIELDS}


_TARGET_EXTRA_FIELDS: tuple[tuple[str, str], ...] = (
    ("fibra_objetivo", "fibra"),
    ("hierro_objetivo", "hierro"),
    ("calcio_objetivo", "calcio"),
    ("vitamina_c_objetivo", "vitamina_c"),
    ("vitamina_a_objetivo", "vitamina_a"),
    ("magnesio_objetivo", "magnesio"),
    ("zinc_objetivo", "zinc"),
    ("potasio_objetivo", "potasio"),
    ("sodio_objetivo", "sodio"),
    ("vitamina_d_objetivo", "vitamina_d"),
    ("vitamina_e_objetivo", "vitamina_e"),
    ("vitamina_k_objetivo", "vitamina_k"),
    ("folato_objetivo", "folato"),
    ("vitamina_b12_objetivo", "vitamina_b12"),
    ("vitamina_b6_objetivo", "vitamina_b6"),
    ("yodo_objetivo", "yodo"),
    ("selenio_objetivo", "selenio"),
)


def objetivos_diarios(parametros: dict[str, float]) -> dict[str, float]:
    """Objetivos del día con las fórmulas del documento (Atwater 4/4/9).

    proteina = round(peso x factor_proteina)
    grasa    = round(peso x factor_grasa)
    kcal     = round(kcal_objetivo)               (editable)
    carb     = round((kcal - 4*prot - 9*grasa) / 4)
    fibra/hierro/calcio/vitC/vitA: importados de la hoja (extras).
    """
    peso_kg = parametros["peso_kg"]
    factor_proteina = parametros["factor_proteina"]
    factor_grasa = parametros["factor_grasa"]
    kcal_objetivo = parametros["kcal_objetivo"]
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
        # Un decimal: a entero se perderían B12 (2.4) y B6 (1.3).
        target[field] = float(
            Decimal(str(parametros.get(extra_key, 0.0))).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
        )
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
    validate_catalog_row(food)
    insert_alimento(db_path, food)


def validate_catalog_row(food: dict) -> None:
    """Rechaza filas de catálogo físicamente implausibles (error de escala).

    `food` lleva los nutrientes por 100 g. Lanza `ValidationError` si
    `kcal` supera `MAX_KCAL_PER_100G`.
    """
    try:
        kcal = float(food.get("kcal", 0.0))
    except (TypeError, ValueError):
        raise ValidationError("kcal no es un número válido") from None
    if kcal < 0 or kcal > MAX_KCAL_PER_100G:
        raise ValidationError(
            f"kcal fuera de rango plausible por 100 g (0-{MAX_KCAL_PER_100G:g}): {kcal:g}"
        )


def diary_totals(rows: list[dict]) -> dict[str, float]:
    """Totales del día sumando los nutrientes almacenados."""
    return {
        field: round(sum(float(r.get(field) or 0.0) for r in rows), 2) for field in NUTRIENT_FIELDS
    }


def save_meal_template(db_path: str, nombre: str, rows: list[dict]) -> None:
    """Guarda (o reemplaza por nombre) una plantilla de alimentación."""
    nombre = nombre.strip()
    if not nombre:
        raise ValidationError("El nombre de la plantilla no puede estar vacío")
    clean: list[dict] = []
    for r in rows:
        alimento = str(r.get("alimento") or "").strip()
        if not alimento:
            raise ValidationError("Plantilla con alimento vacío")
        cantidad = _positive_float(str(r.get("cantidad_g") or 0), "Cantidad")
        clean.append({"alimento": alimento, "cantidad_g": cantidad})
    if not clean:
        raise ValidationError("La plantilla debe tener al menos un alimento")
    existing = find_plantilla_alimentacion_by_nombre(db_path, nombre)
    if existing is not None:
        update_plantilla_alimentacion_rows(db_path, existing, clean)
    else:
        insert_plantilla_alimentacion(db_path, nombre, clean)


def apply_meal_template(db_path: str, plantilla_id: int) -> list[dict]:
    """Filas de la plantilla con los nutrientes recalculados del catálogo."""
    from src.database import get_plantillas_alimentacion

    template = next(
        (p for p in get_plantillas_alimentacion(db_path) if p["id"] == plantilla_id),
        None,
    )
    if template is None:
        raise NotFoundError(f"Plantilla de alimentación no encontrada: {plantilla_id}")
    rows: list[dict] = []
    for idx, r in enumerate(template["alimentos"], start=1):
        food = find_alimento(db_path, r["alimento"])
        row: dict = {
            "orden": idx,
            "alimento": r["alimento"],
            "cantidad_g": r["cantidad_g"],
        }
        if food is not None:
            row.update(calculate_nutrients(food, r["cantidad_g"]))
        else:
            row.update({field: 0.0 for field in NUTRIENT_FIELDS})
        rows.append(row)
    return rows
