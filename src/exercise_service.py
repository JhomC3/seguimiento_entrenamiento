"""Exercise creation use case: typed validation before persistence."""

from config import MUSCLE_CATEGORIES
from src.database import get_exercises_catalog, get_last_exercise_series, insert_exercise
from src.models import ConflictError, ValidationError, is_hiit_set
from src.training_service import parse_form_date


def categoria_for_grupo(grupo_muscular: str) -> str:
    """Categoría autoritativa del grupo (case-insensitive).

    Lanza ValidationError si el grupo no está en el catálogo.
    """
    return _categoria_for_grupo(grupo_muscular)


def _categoria_for_grupo(grupo_muscular: str) -> str:
    """Categoría autoritativa del grupo (case-insensitive)."""
    want = grupo_muscular.strip().lower()
    for cat in MUSCLE_CATEGORIES:
        muscles = cat.get("muscles")
        if isinstance(muscles, list) and any(str(m).strip().lower() == want for m in muscles):
            return str(cat["name"])
    raise ValidationError(f"El grupo muscular '{grupo_muscular.strip()}' no existe en el catálogo.")


def create_exercise(
    db_path: str, ejercicio: str, grupo_muscular: str, categoria: str | None = None
) -> None:
    """Alta con categoría derivada del grupo (el cliente no la decide).

    ``categoria`` se acepta por compatibilidad (form/API antiguos) pero se
    ignora: la fuente es ``MUSCLE_CATEGORIES``.
    """
    ejercicio = ejercicio.strip()
    grupo_muscular = grupo_muscular.strip()
    if not ejercicio:
        raise ValidationError("El nombre del ejercicio es obligatorio.")
    if not grupo_muscular:
        raise ValidationError("El grupo muscular es obligatorio.")
    categoria_derivada = categoria_for_grupo(grupo_muscular)
    if any(e.lower() == ejercicio.lower() for e in get_exercises_catalog(db_path)):
        raise ConflictError(f"El ejercicio '{ejercicio}' ya existe en el catálogo.")
    insert_exercise(db_path, ejercicio, grupo_muscular, categoria_derivada)


def last_exercise_payload(db_path: str, ejercicio: str, before_fecha: str | None = None) -> dict:
    """Últimas series de un ejercicio para autofill (misma fuente que la rueda).

    Valida nombre (catálogo o HIIT) y `before_fecha` opcional (solo mira
    fechas estrictamente anteriores: evita eco del propio día y futuro).
    Devuelve {"ejercicio", "fuente_fecha", "series": [{pos, kg, reps, rir,
    descanso_seg, velocidad_kmh, dificultad}]}.
    """
    name = str(ejercicio or "").strip()
    if not name:
        raise ValidationError("Ejercicio requerido.")
    if before_fecha is not None and str(before_fecha).strip():
        parse_form_date(str(before_fecha).strip())
        before = str(before_fecha).strip()
    else:
        before = None
    catalog = {e.lower() for e in get_exercises_catalog(db_path)}
    if not is_hiit_set(name) and name.lower() not in catalog:
        raise ValidationError(f"El ejercicio '{name}' no existe en el catálogo.")
    payload = get_last_exercise_series(db_path, name, before_fecha=before)
    series = [
        {
            "pos": s["pos"],
            "kg": s["kg"],
            "reps": s["reps"],
            "rir": s["rir"],
            "descanso_seg": s["descanso_seg"],
            "velocidad_kmh": s["velocidad_kmh"],
            "dificultad": s["dificultad"],
        }
        for s in payload["series"]
    ]
    return {"ejercicio": name, "fuente_fecha": payload["fuente_fecha"], "series": series}
