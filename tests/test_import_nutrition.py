"""Tests del importador de las hojas de alimentación."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import config
from src.database import init_db

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_nutrition.py"

ALIMENTOS_CSV = """Alimento,Categoría,cantidad,Calorías (kcal),Carbohidratos (g),Fibra (g),Proteína (g),Grasa (g),Hierro (mg),Calcio (mg),Vitamina C (mg),Vitamina A
Avena,Cereal,100,389,68,"10,0",17,"6,9","4,2",54,0,0
Huevo,Animal,100,143,1,0,13,10,2,50,0,300
"""

_DIARIO_HEADER = [
    "",
    "24/4/2025",
    "Cantidad",
    "Calorías (kcal)",
    "Carbohidratos (g)",
    "Fibra (g)",
    "Proteína (g)",
    "Grasa (g)",
    "Hierro (mg)",
    "Calcio (mg)",
    "Vitamina C (mg)",
    "Vitamina A",
    "",
]
_DIARIO_ROWS = [
    [""] * 13,
    _DIARIO_HEADER,
    [""] * 13,
    ["", "", "", "2300", "375", "38", "90", "72", "8", "1000", "90", "900", ""],
    ["", "", "", "1326", "210", "31", "44", "88", "18", "593", "60", "894", ""],
    ["", "Avena", "120 g", "467", "82", "12", "20", "8", "5", "65", "0", "0", ""],
    ["", "Huevo", "100 g", "143", "1", "0", "13", "10", "2", "50", "0", "300", ""],
]
DIARIO_CSV = "\n".join([",".join(r) for r in _DIARIO_ROWS]) + "\n"


def _load_script():
    spec = importlib.util.spec_from_file_location("import_nutrition", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_nutrition"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_import(tmp_path, monkeypatch, *, fetch_impl=None) -> int:
    mod = _load_script()
    db = str(tmp_path / "gym.db")
    monkeypatch.setattr(config, "DB_PATH", db)

    def default_fetch(name, **kwargs):
        return {"alimentos": ALIMENTOS_CSV, "diario": DIARIO_CSV}[name]

    monkeypatch.setattr(mod, "fetch_sheet_csv", fetch_impl or default_fetch)
    return mod.main()


def test_import_populates_tables(tmp_path, monkeypatch):
    assert _run_import(tmp_path, monkeypatch) == 0
    db = str(tmp_path / "gym.db")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM alimentos").fetchone()[0] == 2
    rows = conn.execute(
        "SELECT nombre, kcal, fibra, grasa FROM alimentos ORDER BY nombre"
    ).fetchall()
    assert rows[0] == ("Avena", 389.0, 10.0, 6.9)
    diario = conn.execute(
        "SELECT fecha, orden, alimento, cantidad_g, kcal, proteina, grasa, origen "
        "FROM diario_alimentacion ORDER BY orden"
    ).fetchall()
    assert diario[0] == ("2025-04-24", 1, "Avena", 120.0, 467.0, 20.0, 8.0, "google")
    assert diario[1][2] == "Huevo"
    conn.close()


def test_import_is_idempotent(tmp_path, monkeypatch):
    assert _run_import(tmp_path, monkeypatch) == 0
    assert _run_import(tmp_path, monkeypatch) == 0
    db = str(tmp_path / "gym.db")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM alimentos").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM diario_alimentacion").fetchone()[0] == 2
    conn.close()


def test_import_preserves_manual_rows(tmp_path, monkeypatch):
    db = str(tmp_path / "gym.db")
    init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO alimentos (nombre, categoria, kcal, carbohidratos, fibra, proteina, "
        "grasa, hierro, calcio, vitamina_c, vitamina_a, origen) "
        "VALUES ('Avena', 'Manual', 1, 1, 1, 1, 1, 1, 1, 1, 1, 'manual')"
    )
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
        "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, "
        "origen) VALUES ('2025-01-01', 1, 'Huevo', 100, 143, 1, 0, 13, 10, 2, 50, 0, 300, 'manual')"
    )
    conn.commit()
    conn.close()

    assert _run_import(tmp_path, monkeypatch) == 0

    conn = sqlite3.connect(db)
    avena = conn.execute("SELECT kcal, origen FROM alimentos WHERE nombre = 'Avena'").fetchone()
    assert avena == (1.0, "manual")
    manual = conn.execute(
        "SELECT fecha, origen FROM diario_alimentacion WHERE fecha = '2025-01-01'"
    ).fetchone()
    assert manual == ("2025-01-01", "manual")
    conn.close()


def test_import_aborts_on_fetch_error(tmp_path, monkeypatch):
    db = str(tmp_path / "gym.db")
    init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO alimentos (nombre, kcal, carbohidratos, fibra, proteina, grasa, "
        "hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('Manual', 1, 1, 1, 1, 1, 1, 1, 1, 1)"
    )
    conn.commit()
    conn.close()

    def boom(name, **kwargs):
        raise RuntimeError("network down")

    assert _run_import(tmp_path, monkeypatch, fetch_impl=boom) == 1
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM alimentos").fetchone()[0] == 1
    conn.close()


def test_import_creates_backup(tmp_path, monkeypatch):
    db = str(tmp_path / "gym.db")
    init_db(db)
    _run_import(tmp_path, monkeypatch)
    backups_dir = tmp_path / "backups"
    assert backups_dir.exists()
    assert len(list(backups_dir.glob("*.db"))) >= 1
