"""Exercise creation use case: typed validation before persistence."""

from config import MUSCLE_CATEGORIES
from src.database import get_exercises_catalog, insert_exercise
from src.models import ConflictError, ValidationError


def create_exercise(db_path: str, ejercicio: str, grupo_muscular: str, categoria: str) -> None:
    ejercicio = ejercicio.strip()
    grupo_muscular = grupo_muscular.strip()
    if not ejercicio:
        raise ValidationError("El nombre del ejercicio es obligatorio.")
    if not grupo_muscular:
        raise ValidationError("El grupo muscular es obligatorio.")
    if categoria not in {c["name"] for c in MUSCLE_CATEGORIES}:
        raise ValidationError("Categoría inválida.")
    if any(e.lower() == ejercicio.lower() for e in get_exercises_catalog(db_path)):
        raise ConflictError(f"El ejercicio '{ejercicio}' ya existe en el catálogo.")
    insert_exercise(db_path, ejercicio, grupo_muscular, categoria)
