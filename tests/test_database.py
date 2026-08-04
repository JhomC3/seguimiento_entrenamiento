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
    assert len(rows) == 2
    assert rows[0] == (1, "LUNES", 6.0, 85.0, 1.0)
    conn.close()
