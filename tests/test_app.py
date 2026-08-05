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
    assert 'transition-opacity duration-150" hidden' in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-editmode="0"' in r.text

def test_saved_future_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(1), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "edit-toggle off" in r.text
    assert 'data-readonly="1"' in r.text

def test_empty_future_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "edit-toggle on" in r.text
    assert 'transition-opacity duration-150"' in r.text
    assert 'transition-opacity duration-150" hidden' not in r.text
    assert 'data-readonly="0"' in r.text
    assert 'data-editmode="1"' in r.text

def test_empty_today_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "edit-toggle on" in r.text

def test_empty_past_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(-2)}")
    assert "edit-toggle off" in r.text

def test_index_uses_stable_wrapper(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get("/")
    assert "session-editor-wrap" in r.text
