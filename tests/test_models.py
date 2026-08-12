"""Domain validation tests: typed models and domain exceptions."""

import pytest

from src.database import init_db, insert_exercise
from src.models import (
    ConflictError,
    NotFoundError,
    TemplateInput,
    TrainingSetInput,
    ValidationError,
)
from src.template_service import apply_template_rows, edit_template, save_template
from src.training_service import parse_form_date, save_session, sets_from_form, validate_sets


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "gym.db")
    init_db(path)
    insert_exercise(path, "Press", "Pectoral", "EMPUJE")
    return path


def test_parse_form_date_malformed_raises_domain_error():
    with pytest.raises(ValidationError):
        parse_form_date("not-a-date")


def test_validate_whitespace_exercise_raises_domain_error(db):
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="   ", kg="80", reps="8", rir="1")])


def test_validate_non_finite_raises_domain_error(db):
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="Press", kg=float("nan"), reps="8", rir="1")])
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="Press", kg=float("inf"), reps="8", rir="1")])


def test_validate_negative_raises_domain_error(db):
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="Press", kg="-5", reps="8", rir="1")])
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="Press", kg="80", reps="-1", rir="1")])
    # RIR negativo es válido desde RIR_MIN (-5): representa series forzadas.
    cleaned = validate_sets(db, [TrainingSetInput(ejercicio="Press", kg="80", reps="8", rir="-1")])
    assert cleaned[0].rir == -1.0
    with pytest.raises(ValidationError):
        validate_sets(db, [TrainingSetInput(ejercicio="Press", kg="80", reps="8", rir="-6")])


def test_validate_zero_rir_is_valid(db):
    cleaned = validate_sets(db, [TrainingSetInput(ejercicio="Press", kg="80", reps="8", rir="0")])
    assert cleaned[0].rir == 0.0


def test_save_session_malformed_date_raises_domain_error(db):
    with pytest.raises(ValidationError):
        save_session(
            db, "01/13/2026", [TrainingSetInput(ejercicio="Press", kg="80", reps="8", rir="1")]
        )


def test_template_duplicate_name_raises_conflict(db):
    save_template(db, TemplateInput(nombre="A", ejercicios=["Press"]))
    pid = save_template(db, TemplateInput(nombre="B", ejercicios=["Press"])).id
    with pytest.raises(ConflictError):
        edit_template(db, pid, TemplateInput(nombre="A", ejercicios=["Press"]))


def test_template_invalid_rows_raise_domain_error(db):
    with pytest.raises(ValidationError):
        save_template(db, TemplateInput(nombre="   ", ejercicios=["Press"]))
    with pytest.raises(ValidationError):
        save_template(db, TemplateInput(nombre="Vacia", ejercicios=[]))


def test_apply_missing_template_raises_not_found(db):
    with pytest.raises(NotFoundError):
        apply_template_rows(db, 999)


def test_sets_from_form_adapter(db):
    sets = sets_from_form(["Press"], ["80"], ["8"], ["1"])
    assert sets == [TrainingSetInput(ejercicio="Press", kg="80", reps="8", rir="1", descanso_seg="")]
