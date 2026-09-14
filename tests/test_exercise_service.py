import pytest

from src.database import get_exercises_catalog, init_db, insert_exercise
from src.exercise_service import categoria_for_grupo, create_exercise
from src.models import ConflictError, ValidationError


def test_create_exercise_valid(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    create_exercise(db, "Press Banca", "Pectoral", "EMPUJE")
    assert "Press Banca" in get_exercises_catalog(db)


def test_create_exercise_duplicado_case_insensitive(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press Banca", "Pectoral", "EMPUJE")
    with pytest.raises(ConflictError):
        create_exercise(db, "press banca", "Pectoral", "EMPUJE")


def test_create_exercise_nombre_vacio(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        create_exercise(db, "   ", "Pectoral", "EMPUJE")


def test_create_exercise_grupo_vacio(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        create_exercise(db, "Press", "  ", "EMPUJE")


def test_create_exercise_categoria_se_deriva_del_grupo(tmp_path):
    """La categoría del cliente se ignora: Pectoral siempre es EMPUJE."""
    from src.database import get_ejercicio_categoria

    db = str(tmp_path / "gym.db")
    init_db(db)
    create_exercise(db, "Press", "Pectoral", "NO_EXISTE")
    assert get_ejercicio_categoria(db)["press"] == "EMPUJE"
    create_exercise(db, "Remo", "Espalda")
    assert get_ejercicio_categoria(db)["remo"] == "TIRON"


def test_create_exercise_grupo_desconocido(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        create_exercise(db, "Press", "Trapecio", "EMPUJE")


def test_categoria_for_grupo_mapea_todo_muscle_categories(tmp_path):
    assert categoria_for_grupo("Pectoral") == "EMPUJE"
    assert categoria_for_grupo("hombro") == "EMPUJE"
    assert categoria_for_grupo("Biceps") == "TIRON"
    assert categoria_for_grupo("Gemelos") == "PIERNA"
    assert categoria_for_grupo("abdomen") == "CORE"
    with pytest.raises(ValidationError):
        categoria_for_grupo("Trapecio")
