import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.security import CSP

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from src.database import init_db, insert_exercise
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    monkeypatch.setattr(appmod, "DB_PATH", db)
    return TestClient(appmod.app)


def test_nosniff_header(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_referrer_policy_header(client):
    r = client.get("/")
    assert r.headers["referrer-policy"] == "same-origin"


def test_frame_options_header(client):
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"


def test_csp_header_present_and_restrictive(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert csp == CSP
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert "form-action 'self'" in csp


def test_csp_allows_required_cdn_sources(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    for src in (
        "https://cdn.tailwindcss.com",
        "https://unpkg.com",
        "https://cdn.jsdelivr.net",
        "https://cdn.plot.ly",
    ):
        assert src in csp


def test_headers_on_mutating_route(client):
    r = client.post("/entrenamiento/session/save", data={
        "fecha": "2099-01-01", "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["1"],
    })
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == CSP


def test_static_assets_have_headers(client):
    r = client.get("/static/css/app.css")
    assert r.headers["x-content-type-options"] == "nosniff"
