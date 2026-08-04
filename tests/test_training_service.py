import sqlite3
from datetime import date

import pytest

from src.database import delete_session, init_db
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    insert_manual_session,
    update_session,
    get_sessions_page,
    get_session_detail,
    validate_sets,
    parse_cycle_start,
)

CYCLE = parse_cycle_start()

def _seed_catalog(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press')")
    conn.commit()
    conn.close()

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_catalog(db_path)
    return db_path

def test_calculate_cycle_week():
    assert calculate_cycle_week(date(2026, 2, 10), CYCLE) == 1
    assert calculate_cycle_week(date(2026, 2, 16), CYCLE) == 1
    assert calculate_cycle_week(date(2026, 2, 17), CYCLE) == 2
    assert calculate_cycle_week(date(2026, 2, 18), CYCLE) == 2
    assert calculate_cycle_week(date(2026, 3, 1), CYCLE) == 3
    assert calculate_cycle_week(date(2026, 1, 1), CYCLE) == 1

def test_day_from_date():
    assert day_from_date(date(2026, 2, 10)) == "MARTES"
    assert day_from_date(date(2026, 2, 16)) == "LUNES"
    assert day_from_date(date(2026, 2, 22)) == "DOMINGO"

def test_insert_manual_session_basic(db):
    result = insert_manual_session(db, "2026-02-10", [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 2},
    ])
    assert result["semana"] == 1
    assert result["dia"] == "MARTES"
    assert result["fecha"] == "10/2/26"
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen FROM training_sets").fetchone()
    conn.close()
    assert row == (1, "MARTES", "10/2/26", 1, "Press", 8.0, 80.0, 2.0, "manual")

def test_insert_manual_session_multiple_sets(db):
    insert_manual_session(db, "2026-02-18", [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 2},
        {"ejercicio": "Press", "kg": 75, "reps": 10, "rir": None},
    ])
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT semana, set_orden, reps, rir FROM training_sets ORDER BY set_orden").fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == (2, 1, 8.0, 2.0)
    assert rows[1] == (2, 2, 10.0, None)

def test_insert_invalid_kg_rejected(db):
    with pytest.raises(ValueError):
        insert_manual_session(db, "2026-02-10", [{"ejercicio": "Press", "kg": 0, "reps": 8, "rir": None}])

def test_insert_invalid_reps_rejected(db):
    with pytest.raises(ValueError):
        insert_manual_session(db, "2026-02-10", [{"ejercicio": "Press", "kg": 80, "reps": -1, "rir": None}])

def test_insert_unknown_exercise_rejected(db):
    with pytest.raises(ValueError):
        insert_manual_session(db, "2026-02-10", [{"ejercicio": "No Existe", "kg": 80, "reps": 8, "rir": None}])

def test_insert_negative_rir_rejected(db):
    with pytest.raises(ValueError):
        insert_manual_session(db, "2026-02-10", [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": -1}])

def test_transaction_rolls_back_on_failure(db):
    with pytest.raises(ValueError):
        insert_manual_session(db, "2026-02-10", [
            {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
            {"ejercicio": "No Existe", "kg": 80, "reps": 8, "rir": None},
        ])
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0

def test_validate_sets_empty(db):
    with pytest.raises(ValueError):
        validate_sets(db, [])

def test_get_sessions_page_and_detail(db):
    insert_manual_session(db, "2026-02-18", [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 2},
        {"ejercicio": "Press", "kg": 75, "reps": 10, "rir": None},
    ])
    sessions, total, page = get_sessions_page(db, 1, 20)
    assert total == 1
    assert page == 1
    s = sessions[0]
    assert s["semana"] == 2
    assert s["n_series"] == 2
    assert s["n_ejercicios"] == 1
    assert s["manual_sets"] == 2
    assert s["google_sets"] == 0
    detail = get_session_detail(db, 2, "MIERCOLES", "18/2/26")
    assert len(detail) == 2
    assert detail[0]["rm_ajustado"] == round(80 * (1 + 0.0333 * (8 + 1 + 2)), 1)

def test_update_session(db):
    insert_manual_session(db, "2026-02-10", [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
    ])
    update_session(db, 1, "MARTES", "10/2/26", "2026-02-11", [
        {"ejercicio": "Press", "kg": 85, "reps": 6, "rir": 2},
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": None},
    ])
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT semana, dia, fecha, kg FROM training_sets ORDER BY set_orden").fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == (1, "MIERCOLES", "11/2/26", 85.0)
    assert rows[1][2] == "11/2/26"

def test_delete_session(db):
    insert_manual_session(db, "2026-02-10", [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
    ])
    deleted = delete_session(db, 1, "MARTES", "10/2/26")
    assert deleted == 1
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0
