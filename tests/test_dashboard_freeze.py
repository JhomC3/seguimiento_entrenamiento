"""Pins del Dashboard congelado (armonización Diario/Splits → Dashboard).

El Dashboard es la referencia visual y NO debe cambiar: si alguno de estos
tests falla tras un lote de armonización, el lote ha tocado el Dashboard y
debe revertirse o consultarse antes de seguir.
"""

from fastapi.testclient import TestClient

import app as appmod
from src import web_context
from src.database import init_db, insert_exercise
from src.security import get_csrf_secret, make_csrf_token


def _client() -> TestClient:
    return TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})


def _setup_db(tmp_path) -> str:
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    return db


def test_freeze_dashboard_header(tmp_path, monkeypatch) -> None:
    db = _setup_db(tmp_path)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    body = _client().get("/").text
    assert '<header class="dashboard-header">' in body
    assert (
        '<h1 class="text-xl font-black tracking-[0.2em] text-white uppercase">Gym Tracker</h1>'
    ) in body
    assert 'class="workspace-nav"' in body
    assert 'id="catalog-toggle-mobile"' in body


def test_freeze_dashboard_layout_tres_columnas(tmp_path, monkeypatch) -> None:
    db = _setup_db(tmp_path)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    body = _client().get("/").text
    assert 'class="dashboard-layout"' in body
    assert 'id="dashboard-catalog"' in body
    assert '<h2 class="panel-title">Catálogo</h2>' in body
    assert 'id="unified-chart-container"' in body
    assert "panel panel-spacious" in body
    assert 'id="granularity-selector"' in body
    assert body.count('data-action="set-granularity"') == 3
    assert 'id="unified-chart-empty"' in body


def test_freeze_dashboard_catalogo_db(tmp_path, monkeypatch) -> None:
    db = _setup_db(tmp_path)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    body = _client().get("/").text
    assert 'id="dashboard-catalog-list"' in body
    assert "db-group" in body
    assert "db-exercise-row" in body
    assert "db-exercise-name" in body


def test_freeze_popup_variante_dashboard(tmp_path, monkeypatch) -> None:
    """El popup del Dashboard comparte fragmentos con el Diario: su variante
    no puede cambiar (formato con semana, dots solo de entreno)."""
    db = _setup_db(tmp_path)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    body = _client().get("/editor/popup?fecha=2099-01-01").text
    assert 'id="date-navigator"' in body
    assert "Semana" in body
    assert 'id="session-date-title"' in body
    assert 'id="session-editor-wrap"' in body
    assert 'id="nutrition-editor-wrap"' in body
    assert 'id="cardio-day"' in body
