import sqlite3

import pytest

from src.database import init_db
from src.db_connection import connect_db, read_connection, transaction


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "gym.db")
    init_db(path)
    return path


def test_connect_db_enables_foreign_keys(db):
    conn = connect_db(db)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_connect_db_sets_busy_timeout(db):
    conn = connect_db(db)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    finally:
        conn.close()


def test_connect_db_uses_row_factory(db):
    conn = connect_db(db)
    try:
        conn.execute("INSERT INTO plantillas (nombre) VALUES ('A')")
        conn.commit()
        row = conn.execute("SELECT id, nombre FROM plantillas").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["nombre"] == "A"
    finally:
        conn.close()


def test_read_connection_closes_on_exception(db):
    with pytest.raises(RuntimeError):
        with read_connection(db) as conn:
            conn.execute("SELECT 1")
            raise RuntimeError("boom")
    conn = connect_db(db)
    try:
        assert conn.execute("SELECT 1").fetchone() is not None
    finally:
        conn.close()


def test_transaction_rolls_back_on_exception(db):
    with pytest.raises(RuntimeError):
        with transaction(db) as conn:
            conn.execute("INSERT INTO plantillas (nombre) VALUES ('A')")
            raise RuntimeError("boom")
    conn = connect_db(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM plantillas").fetchone()[0] == 0
    finally:
        conn.close()


def test_transaction_commits_on_success(db):
    with transaction(db) as conn:
        conn.execute("INSERT INTO plantillas (nombre) VALUES ('A')")
    conn = connect_db(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM plantillas").fetchone()[0] == 1
    finally:
        conn.close()


def test_delete_plantilla_cascades_sets(db):
    from src.database import delete_plantilla, insert_plantilla

    pid = insert_plantilla(db, "Mi Empuje", "", ["Press", "Curl"])
    delete_plantilla(db, pid)
    conn = connect_db(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM plantilla_sets WHERE plantilla_id = ?", (pid,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_failed_session_save_leaves_no_partial_rows(db):
    from src.database import get_sets_by_fecha, insert_exercise
    from src.training_service import fecha_to_db, save_session
    import datetime

    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    fecha = datetime.date.today()
    save_session(db, fecha.strftime("%Y-%m-%d"), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    with pytest.raises(ValueError):
        save_session(db, fecha.strftime("%Y-%m-%d"), [
            {"ejercicio": "Press", "kg": 90, "reps": 8, "rir": 1},
            {"ejercicio": "Press", "kg": 70, "reps": "", "rir": 1},
        ])
    rows = get_sets_by_fecha(db, fecha_to_db(fecha))
    assert len(rows) == 1
    assert rows[0]["kg"] == 80
