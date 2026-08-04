import sqlite3
import pytest
import pandas as pd
from src.database import init_db, load_ejercicios, load_training_data

def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t[0] for t in tables]
    assert "ejercicios" in table_names
    assert "training_sets" in table_names
    conn.close()

def test_init_db_creates_new_columns(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    sets_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()]
    ej_cols = [r[1] for r in conn.execute("PRAGMA table_info(ejercicios)").fetchall()]
    conn.close()
    assert "origen" in sets_cols
    assert "categoria" in ej_cols
    assert "origen" in ej_cols

def test_init_db_preserves_existing_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) VALUES (1, 'LUNES', '4/5/26', 1, 'Press', 6, 85, 1, 'manual')")
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 1

def test_init_db_migrates_old_schema(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE
        );
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana INTEGER NOT NULL,
            dia TEXT NOT NULL,
            fecha TEXT,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            reps REAL,
            kg REAL,
            rir REAL
        );
        INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (1, 'LUNES', '4/5/26', 1, 'Press', 6, 85, 1);
    """)
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    sets_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()]
    ej_cols = [r[1] for r in conn.execute("PRAGMA table_info(ejercicios)").fetchall()]
    set_origen = conn.execute("SELECT origen FROM training_sets").fetchone()[0]
    cat = conn.execute("SELECT categoria FROM ejercicios").fetchone()[0]
    conn.close()
    assert "origen" in sets_cols
    assert "categoria" in ej_cols
    assert set_origen == "google"
    assert cat == "EMPUJE"

def test_init_db_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0

def test_load_ejercicios(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    df = pd.DataFrame({
        "grupo_muscular": ["Pectoral", "Triceps"],
        "ejercicio": ["Press Convergente", "Katana"],
    })
    load_ejercicios(db_path, df)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT grupo_muscular, ejercicio FROM ejercicios").fetchall()
    assert len(rows) == 2
    assert rows[0] == ("Pectoral", "Press Convergente")
    assert rows[1] == ("Triceps", "Katana")
    conn.close()

def test_load_training_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    df = pd.DataFrame({
        "semana": [1, 1],
        "dia": ["LUNES", "LUNES"],
        "fecha": ["4/5/26", "4/5/26"],
        "set_orden": [1, 2],
        "ejercicio": ["Press Convergente", "Press Convergente"],
        "reps": [6.0, 6.0],
        "kg": [85.0, 85.0],
        "rir": [1.0, 0.5]
    })
    load_training_data(db_path, df)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT semana, dia, reps, kg, rir FROM training_sets").fetchall()
    origens = conn.execute("SELECT DISTINCT origen FROM training_sets").fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, "LUNES", 6.0, 85.0, 1.0)
    assert origens == [("google",)]
    conn.close()
