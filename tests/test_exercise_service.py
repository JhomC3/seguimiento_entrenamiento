import pytest

from src.database import get_exercises_catalog, init_db, insert_exercise
from src.exercise_service import create_exercise
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


def test_create_exercise_categoria_invalida(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        create_exercise(db, "Press", "Pectoral", "NO_EXISTE")
