"""Tests de las mutaciones nutricionales con backup y undo."""

import pytest

from src.database import get_diario_by_fecha, init_db, insert_alimento
from src.models import NutritionEntryInput, ValidationError
from src.mutation_service import (
    clear_undo_stack,
    delete_diary_with_undo_snapshot,
    save_diary_with_undo_snapshot,
    undo_last_action,
    undo_stack_size,
)


@pytest.fixture(autouse=True)
def _empty_undo_stack():
    clear_undo_stack()
    yield
    clear_undo_stack()


def _setup_db(tmp_path) -> str:
    db = str(tmp_path / "g.db")
    init_db(db)
    insert_alimento(
        db,
        {
            "nombre": "Avena",
            "categoria": "Cereal",
            "kcal": 389.0,
            "carbohidratos": 68.0,
            "fibra": 10.0,
            "proteina": 17.0,
            "grasa": 6.9,
            "hierro": 4.2,
            "calcio": 54.0,
            "vitamina_c": 0.0,
            "vitamina_a": 0.0,
        },
    )
    insert_alimento(
        db,
        {
            "nombre": "Huevo",
            "categoria": "Animal",
            "kcal": 143.0,
            "carbohidratos": 1.0,
            "fibra": 0.0,
            "proteina": 13.0,
            "grasa": 10.0,
            "hierro": 2.0,
            "calcio": 50.0,
            "vitamina_c": 0.0,
            "vitamina_a": 300.0,
        },
    )
    return db


def test_save_diary_pushes_undo_entry(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    assert undo_stack_size() == 1


def test_delete_diary_pushes_undo_entry(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    clear_undo_stack()
    delete_diary_with_undo_snapshot(db, "2025-04-24")
    assert undo_stack_size() == 1


def test_undo_restores_previous_snapshot(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Huevo", "100")])
    result = undo_last_action(db, "2025-04-24")
    assert result["kind"] == "alimentacion"
    assert result["fecha_iso"] == "2025-04-24"
    assert result["has_data"] == "1"
    rows = get_diario_by_fecha(db, "2025-04-24")
    assert len(rows) == 1
    assert rows[0]["alimento"] == "Avena"
    assert rows[0]["orden"] == 1
    assert rows[0]["origen"] == "manual"
    assert rows[0]["kcal"] == 467.0
    assert undo_stack_size() == 1


def test_undo_delete_restores_snapshot(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    delete_diary_with_undo_snapshot(db, "2025-04-24")
    result = undo_last_action(db, "2025-04-24")
    assert result["kind"] == "alimentacion"
    assert result["has_data"] == "1"
    rows = get_diario_by_fecha(db, "2025-04-24")
    assert len(rows) == 1
    assert rows[0]["kcal"] == 467.0


def test_undo_alimentacion_does_not_touch_plantillas(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    undo_last_action(db, "")
    undo_last_action(db, "")
    assert undo_stack_size() == 0
    assert undo_last_action(db, "")["kind"] == "empty"


def test_failed_backup_blocks_write_and_skips_stack(tmp_path, monkeypatch):
    from src import mutation_service

    db = _setup_db(tmp_path)

    def boom(db_path):
        raise OSError("backup fail")

    monkeypatch.setattr(mutation_service, "backup_or_raise", boom)
    with pytest.raises(OSError):
        save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    assert undo_stack_size() == 0
    assert get_diario_by_fecha(db, "2025-04-24") == []


def test_domain_error_does_not_push_stack(tmp_path):
    db = _setup_db(tmp_path)
    with pytest.raises(ValidationError):
        save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("", "")])
    assert undo_stack_size() == 0


def test_stack_keeps_max_10_mixed_actions(tmp_path):
    db = _setup_db(tmp_path)
    for i in range(12):
        save_diary_with_undo_snapshot(
            db, "2025-04-24", [NutritionEntryInput("Avena", f"{100 + i}")]
        )
    assert undo_stack_size() == 10
