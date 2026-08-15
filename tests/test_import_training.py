"""Importación de entrenamiento: backup previo + fábrica de conexión compartida."""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.db_connection import read_connection
from src.database import init_db

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_google_sheets.py"


@pytest.fixture()
def training_module():
    spec = importlib.util.spec_from_file_location("import_google_sheets", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_google_sheets"] = mod
    spec.loader.exec_module(mod)
    return mod


def _df_ejercicios() -> pd.DataFrame:
    return pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press"}])


def _df_ciclo() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "2026-08-10",
                "set_orden": 1,
                "ejercicio": "Press",
                "reps": 10,
                "kg": 80.0,
                "rir": 2,
            },
        ]
    )


def test_import_reemplaza_google_y_hace_backup(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    training_module.import_training_tables(db_path, _df_ejercicios(), _df_ciclo())
    backup_dir = Path(db_path).parent / "backups"
    assert list(backup_dir.glob("lifestyle-*.db"))
    with read_connection(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    assert n == 1


def test_import_idempotente(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    training_module.import_training_tables(db_path, _df_ejercicios(), _df_ciclo())
    training_module.import_training_tables(db_path, _df_ejercicios(), _df_ciclo())
    with read_connection(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    assert n == 1


def test_import_no_toca_origen_manual(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    from src.database import insert_exercise
    from src.models import TrainingSetInput
    from src.training_service import save_session

    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    save_session(db_path, "2026-08-12", [TrainingSetInput("Press", 90, 6, 1)])
    training_module.import_training_tables(db_path, _df_ejercicios(), _df_ciclo())
    with read_connection(db_path) as conn:
        rows = conn.execute("SELECT origen, COUNT(*) FROM training_sets GROUP BY origen").fetchall()
    assert dict(rows) == {"google": 1, "manual": 1}


def test_import_datos_vacios_rechaza(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    with pytest.raises(ValueError):
        training_module.import_training_tables(db_path, pd.DataFrame(), pd.DataFrame())
