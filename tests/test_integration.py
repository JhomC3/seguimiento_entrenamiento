import sqlite3

from src.database import init_db, load_ejercicios, load_training_data
from src.fetcher import fetch_sheet_csv
from src.parser import parse_ciclo, parse_ejercicios


def test_full_pipeline_integration(tmp_path):
    """Descarga datos reales -> parsea -> carga en DB -> consulta para validar."""
    db_path = str(tmp_path / "integration_test.db")

    # 1. Fetch live sheets
    csv_ejercicios = fetch_sheet_csv("ejercicios")
    csv_ciclo = fetch_sheet_csv("ciclo_16")

    assert len(csv_ejercicios) > 0
    assert len(csv_ciclo) > 0

    # 2. Parse
    df_ej = parse_ejercicios(csv_ejercicios)
    df_ciclo = parse_ciclo(csv_ciclo)

    assert len(df_ej) > 0
    assert len(df_ciclo) > 0

    # Verificar columnas esperadas
    assert list(df_ej.columns) == ["grupo_muscular", "ejercicio"]
    assert list(df_ciclo.columns) == [
        "semana",
        "dia",
        "fecha",
        "set_orden",
        "ejercicio",
        "reps",
        "kg",
        "rir",
    ]

    # 3. DB load
    init_db(db_path)
    load_ejercicios(db_path, df_ej)
    load_training_data(db_path, df_ciclo)

    # 4. Verification
    conn = sqlite3.connect(db_path)
    sets_count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    exercises_count = conn.execute("SELECT COUNT(*) FROM ejercicios").fetchone()[0]
    conn.close()

    assert sets_count == len(df_ciclo)
    assert exercises_count > 0
    print(f"Integration Test Success: Loaded {sets_count} sets and {exercises_count} exercises.")
