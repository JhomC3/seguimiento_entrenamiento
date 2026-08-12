from src.database import (
    delete_plantilla,
    find_plantilla_by_nombre,
    get_ejercicio_categoria,
    get_last_session_sets,
    get_plantilla,
    insert_plantilla,
    update_plantilla,
)

__all__ = [
    "CLASSIFICATIONS",
    "apply_template_rows",
    "classify_template",
    "delete_plantilla",
    "edit_template",
    "save_template",
]
from src.models import (
    ConflictError,
    NotFoundError,
    Template,
    TemplateInput,
    TrainingSetInput,
    ValidationError,
)

CLASSIFICATIONS = ["EMPUJE", "JALON", "PIERNA", "TORSO", "FULL BODY", "CORE", "SIN CLASIFICAR"]


def classify_template(db_path: str, ejercicios: list[str]) -> str:
    cats = {
        get_ejercicio_categoria(db_path).get(str(ej).strip().lower())
        for ej in ejercicios
        if str(ej).strip()
    }
    cats.discard(None)
    if not cats:
        return "SIN CLASIFICAR"
    has_empuje = "EMPUJE" in cats
    has_tiron = "TIRON" in cats
    has_pierna = "PIERNA" in cats
    if has_pierna and (has_empuje or has_tiron):
        return "FULL BODY"
    if has_empuje and has_tiron:
        return "TORSO"
    if has_tiron:
        return "JALON"
    if has_empuje:
        return "EMPUJE"
    if has_pierna:
        return "PIERNA"
    return "CORE"


def _clean_ejercicios(ejercicios: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for ej in ejercicios:
        name = str(ej).strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        cleaned.append(name)
    return cleaned


def _to_template(row: dict) -> Template:
    return Template(
        id=row["id"],
        nombre=row["nombre"],
        clasificacion=row["clasificacion"],
        updated_at=row["updated_at"],
        ejercicios=list(row.get("ejercicios", [])),
        updated=bool(row.get("updated", False)),
    )


def save_template(db_path: str, template: TemplateInput) -> Template:
    nombre = str(template.nombre).strip()
    ejercicios = _clean_ejercicios(template.ejercicios)
    if not nombre:
        raise ValidationError("Debes ponerle nombre al entreno.")
    if not ejercicios:
        raise ValidationError("El entreno debe tener al menos un ejercicio.")
    clasificacion = classify_template(db_path, ejercicios)
    existing = find_plantilla_by_nombre(db_path, nombre)
    if existing is not None:
        update_plantilla(db_path, existing, nombre, clasificacion, ejercicios)
        return _to_template(
            {
                "id": existing,
                "nombre": nombre,
                "clasificacion": clasificacion,
                "updated_at": "",
                "ejercicios": ejercicios,
                "updated": True,
            }
        )
    pid = insert_plantilla(db_path, nombre, clasificacion, ejercicios)
    return _to_template(
        {
            "id": pid,
            "nombre": nombre,
            "clasificacion": clasificacion,
            "updated_at": "",
            "ejercicios": ejercicios,
        }
    )


def edit_template(db_path: str, plantilla_id: int, template: TemplateInput) -> Template:
    nombre = str(template.nombre).strip()
    ejercicios = _clean_ejercicios(template.ejercicios)
    if not nombre:
        raise ValidationError("El nombre del entreno no puede estar vacío.")
    if not ejercicios:
        raise ValidationError("El entreno debe tener al menos un ejercicio.")
    existing = find_plantilla_by_nombre(db_path, nombre)
    if existing is not None and existing != plantilla_id:
        raise ConflictError(f"Ya existe un entreno llamado '{nombre}'.")
    clasificacion = classify_template(db_path, ejercicios)
    update_plantilla(db_path, plantilla_id, nombre, clasificacion, ejercicios)
    return _to_template(
        {
            "id": plantilla_id,
            "nombre": nombre,
            "clasificacion": clasificacion,
            "updated_at": "",
            "ejercicios": ejercicios,
        }
    )


def apply_template_rows(db_path: str, plantilla_id: int) -> list[TrainingSetInput]:
    plantilla = get_plantilla(db_path, plantilla_id)
    if plantilla is None:
        raise NotFoundError("La plantilla no existe.")
    rows: list[TrainingSetInput] = []
    for ej in plantilla["ejercicios"]:
        sets = get_last_session_sets(db_path, ej)
        if sets:
            for s in sets:
                rows.append(
                    TrainingSetInput(
                        ejercicio=s["ejercicio"],
                        kg=s["kg"],
                        reps=s["reps"],
                        rir=s["rir"],
                        descanso_seg=s.get("descanso_seg", ""),
                    )
                )
        else:
            rows.append(TrainingSetInput(ejercicio=ej, kg="", reps="", rir=""))
    return rows
