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
    assert undo_stack_size(db) == 1


def test_delete_diary_pushes_undo_entry(tmp_path):
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    clear_undo_stack(db)
    delete_diary_with_undo_snapshot(db, "2025-04-24")
    assert undo_stack_size(db) == 1


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
    assert undo_stack_size(db) == 1


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
    assert undo_stack_size(db) == 0
    assert undo_last_action(db, "")["kind"] == "empty"


def test_failed_backup_blocks_write_and_skips_stack(tmp_path, monkeypatch):
    from src import mutation_service

    db = _setup_db(tmp_path)

    def boom(db_path):
        raise OSError("backup fail")

    monkeypatch.setattr(mutation_service, "backup_or_raise", boom)
    with pytest.raises(OSError):
        save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
    assert undo_stack_size(db) == 0
    assert get_diario_by_fecha(db, "2025-04-24") == []


def test_domain_error_does_not_push_stack(tmp_path):
    db = _setup_db(tmp_path)
    with pytest.raises(ValidationError):
        save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("", "")])
    assert undo_stack_size(db) == 0


def test_undo_alimentacion_restores_parametros(tmp_path):
    from src.database import get_parametros_diarios

    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(
        db,
        "2025-04-24",
        [NutritionEntryInput("Avena", "120")],
        parametros={"peso_kg": 69.0, "kcal_objetivo": 2750.0},
    )
    save_diary_with_undo_snapshot(
        db,
        "2025-04-24",
        [NutritionEntryInput("Avena", "150")],
        parametros={"peso_kg": 70.0, "kcal_objetivo": 2600.0},
    )
    undo_last_action(db, "2025-04-24")
    params = get_parametros_diarios(db, "2025-04-24")
    assert params["peso_kg"] == 69.0
    assert params["kcal_objetivo"] == 2750.0


def test_stack_keeps_max_10_mixed_actions(tmp_path):
    db = _setup_db(tmp_path)
    for i in range(12):
        save_diary_with_undo_snapshot(
            db, "2025-04-24", [NutritionEntryInput("Avena", f"{100 + i}")]
        )
    assert undo_stack_size(db) == 10


# ---------------------------------------------------------------------------
# Web plan Task 8: undo persistente en SQLite (v013)
# ---------------------------------------------------------------------------


def test_undo_entries_persisted_in_db_table(tmp_path):
    from src.db_connection import read_connection

    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "100")])
    with read_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM undo_entries").fetchone()[0]
        kind = conn.execute("SELECT kind FROM undo_entries").fetchone()[0]
    assert n == 1
    assert kind == "alimentacion"


def test_undo_survives_new_service_instance(tmp_path):
    """Sin estado de proceso: el journal vive en la DB, nada que resetear."""
    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "100")])
    result = undo_last_action(db, "2025-04-24")
    assert result["kind"] == "alimentacion"
    assert undo_stack_size(db) == 0


def test_undo_entry_only_before_snapshot_stored(tmp_path):
    import json

    from src.db_connection import read_connection

    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "100")])
    with read_connection(db) as conn:
        raw = conn.execute("SELECT snapshot FROM undo_entries").fetchone()[0]
    snapshot = json.loads(raw)
    assert "before" in snapshot
    assert "after" not in snapshot
    assert "params_after" not in snapshot


def test_failed_restore_keeps_entry(tmp_path, monkeypatch):
    import src.mutation_service as ms

    db = _setup_db(tmp_path)
    save_diary_with_undo_snapshot(db, "2025-04-24", [NutritionEntryInput("Avena", "100")])

    def broken_restore(*args, **kwargs):
        raise OSError("restore caído")

    monkeypatch.setattr(ms, "restore_diario_rows", broken_restore)
    with pytest.raises(OSError):
        undo_last_action(db, "2025-04-24")
    assert undo_stack_size(db) == 1


# ---------------------------------------------------------------------------
# Splits: backup + journal de undo
# ---------------------------------------------------------------------------


def _split_items():
    from src.models import SplitItemInput

    return [
        SplitItemInput(dia="LUNES", ejercicio="Press"),
        SplitItemInput(dia="LUNES", ejercicio="Press"),
    ]


def test_save_split_undo_restaura(tmp_path):
    from src.database import get_split, insert_exercise
    from src.models import SplitInput
    from src.mutation_service import save_split_with_undo_snapshot

    db = _setup_db(tmp_path)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    result = save_split_with_undo_snapshot(db, None, SplitInput(nombre="A", items=_split_items()))
    assert get_split(db, result.id) is not None
    undo = undo_last_action(db, "")
    assert undo["kind"] == "splits"
    assert get_split(db, result.id) is None


def test_delete_split_undo_restaura(tmp_path):
    from src.database import get_split, insert_exercise
    from src.models import SplitInput
    from src.mutation_service import delete_split_with_undo_snapshot, save_split_with_undo_snapshot

    db = _setup_db(tmp_path)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    result = save_split_with_undo_snapshot(db, None, SplitInput(nombre="A", items=_split_items()))
    delete_split_with_undo_snapshot(db, result.id)
    assert get_split(db, result.id) is None
    undo = undo_last_action(db, "")
    assert undo["kind"] == "splits"
    assert get_split(db, result.id) is not None
    assert len(get_split(db, result.id)["items"]) == 2


def test_undo_splits_limita_a_10_entradas(tmp_path):
    from src.database import insert_exercise
    from src.models import SplitInput
    from src.mutation_service import save_split_with_undo_snapshot

    db = _setup_db(tmp_path)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    for i in range(12):
        save_split_with_undo_snapshot(db, None, SplitInput(nombre=f"S{i}", items=_split_items()))
    assert undo_stack_size(db) == 10


def test_undo_splits_restore_fallido_conserva_entrada(tmp_path, monkeypatch):
    from src.database import insert_exercise
    from src.models import SplitInput
    from src.mutation_service import save_split_with_undo_snapshot

    db = _setup_db(tmp_path)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    save_split_with_undo_snapshot(db, None, SplitInput(nombre="A", items=_split_items()))

    import src.mutation_service as mut

    def boom(db_path, snapshot):
        raise RuntimeError("restore falló")

    monkeypatch.setattr(mut, "restore_splits", boom)
    with pytest.raises(RuntimeError):
        undo_last_action(db, "")
    monkeypatch.undo()
    assert undo_stack_size(db) == 1
