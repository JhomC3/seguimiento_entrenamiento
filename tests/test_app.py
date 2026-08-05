import datetime

import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.database import init_db, insert_exercise
from src.training_service import save_session

def _setup_db(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    return db

def _fecha(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")

def test_saved_today_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "edit-toggle off" in r.text
    assert 'duration-150 hidden"' in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text
    assert 'id="edit-actions" class="h-8 flex items-center gap-2 invisible"' in r.text
    assert ">Cancelar</button>" in r.text
    assert "rm-cell" in r.text

def test_saved_future_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(1), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "edit-toggle off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text

def test_empty_future_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "edit-toggle on" in r.text
    assert 'transition-opacity duration-150' in r.text
    assert 'duration-150 hidden"' not in r.text
    assert 'data-readonly="0"' in r.text
    assert 'data-has-data="0"' in r.text
    assert 'id="edit-actions" class="h-8 flex items-center gap-2 invisible"' in r.text
    assert ">Cancelar</button>" in r.text

def test_empty_today_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "edit-toggle on" in r.text

def test_empty_past_is_readonly_with_fallback_row(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(-2)}")
    assert "edit-toggle off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="0"' in r.text
    assert r.text.count('<tr class="set-row') == 1

def test_index_uses_stable_card(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get("/")
    assert 'id="session-editor" data-editmode="0"' in r.text
    assert 'id="session-editor-wrap"' in r.text
    assert "rm-cell" in r.text
    assert 'id="save-outcome" data-ok="0" hidden' in r.text
    assert '<div id="editor-notice"></div>' in r.text


def test_save_valid_returns_ok_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["1"],
    })
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="1"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "Entrenamiento guardado" in r.text


def test_save_invalid_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": [""], "kg": ["80"], "reps": ["8"], "rir": [""],
    })
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="0"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "notice-error" in r.text
    assert 'data-ok="1"' not in r.text


def test_save_empty_rir_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": [""],
    })
    assert 'data-ok="0"' in r.text
    assert "RIR" in r.text


def test_save_zero_rir_succeeds(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["0"],
    })
    assert 'data-ok="1"' in r.text
