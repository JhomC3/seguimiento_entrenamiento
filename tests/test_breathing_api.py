"""API v1 de respiración B5.0 (contrato training-api-contract.md §B5).

Append-only idempotente por client_session_id, métricas recalculadas en
servidor y DELETE idempotente. El cliente de estos tests NO envía cabecera
CSRF: cada POST/DELETE que pasa demuestra la exención exacta.
"""

import datetime
import sqlite3
import uuid

from fastapi.testclient import TestClient

import app as appmod
from src import http_shared, web_context
from src.database import init_db

SYNC_TOKEN = "secret-breathing-api"


def _client():
    return TestClient(appmod.app)


def _ms(y: int, m: int, d: int, hh: int = 7, mm: int = 0) -> int:
    return int(datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.UTC).timestamp() * 1000)


def _auth(monkeypatch, tmp_path, token=SYNC_TOKEN):
    db = str(tmp_path / "breathing_api.db")
    init_db(db)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    monkeypatch.setattr(http_shared, "HC_SYNC_TOKEN", token)
    return db


def _h(token=SYNC_TOKEN):
    return {"X-Sync-Token": token}


def _body(**over):
    base = {
        "client_session_id": str(uuid.uuid4()),
        "start_epoch_ms": _ms(2026, 9, 13),
        "end_epoch_ms": _ms(2026, 9, 13) + 120_000,
        "time_zone_offset_minutes": 0,
        "patron": {"inhale_s": 4.0, "hold_in_s": 0.0, "exhale_s": 6.0, "hold_out_s": 0.0},
    }
    base.update(over)
    return base


# --- Migración -------------------------------------------------------------------


def test_migracion_v021_crea_tabla(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "breathing_sessions" in tables
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        assert version >= 21
    finally:
        conn.close()


def test_migracion_v021_idempotente(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    init_db(db)
    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 21"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


# --- Auth ------------------------------------------------------------------------


def test_breathing_503_sin_token(tmp_path, monkeypatch):
    db = str(tmp_path / "b.db")
    init_db(db)
    monkeypatch.setattr(web_context, "DB_PATH", db)
    monkeypatch.setattr(http_shared, "HC_SYNC_TOKEN", "")
    c = _client()
    assert c.post("/api/v1/respiracion/sesion", json={}, headers=_h("x")).status_code == 503
    assert (
        c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h("x")).status_code == 503
    )
    assert (
        c.delete("/api/v1/respiracion/sesion?client_session_id=x", headers=_h("x")).status_code
        == 503
    )


def test_breathing_401_token_invalido(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.post("/api/v1/respiracion/sesion", json={}).status_code == 401
    assert c.post("/api/v1/respiracion/sesion", json={}, headers=_h("otro")).status_code == 401
    assert c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13").status_code == 401
    assert c.delete("/api/v1/respiracion/sesion?client_session_id=x").status_code == 401


# --- POST --------------------------------------------------------------------------


def test_breathing_post_roundtrip(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    body = _body()
    r = c.post("/api/v1/respiracion/sesion", json=body, headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["client_session_id"] == body["client_session_id"]
    assert data["fecha"] == "2026-09-13"
    assert data["ciclos_completados"] == 12
    assert data["bpm_medio"] == 6.0
    assert data["duracion_real_sec"] == 120
    assert data["saved"] is True


def test_breathing_post_servidor_recalcula(tmp_path, monkeypatch):
    """Campos extra del cliente (p. ej. ciclos falsos) se ignoran."""
    _auth(monkeypatch, tmp_path)
    c = _client()
    body = _body(ciclos_completados=999, bpm_medio=99.9, fecha="2030-01-01")
    r = c.post("/api/v1/respiracion/sesion", json=body, headers=_h())
    assert r.status_code == 200
    assert r.json()["ciclos_completados"] == 12
    assert r.json()["fecha"] == "2026-09-13"


def test_breathing_post_replay_idempotente(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    body = _body()
    first = c.post("/api/v1/respiracion/sesion", json=body, headers=_h()).json()
    second = c.post("/api/v1/respiracion/sesion", json=body, headers=_h()).json()
    assert first["saved"] is True
    assert second["saved"] is False
    assert second["ciclos_completados"] == first["ciclos_completados"]
    day = c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h()).json()
    assert day["count"] == 1


def test_breathing_post_validacion(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.post("/api/v1/respiracion/sesion", json={}, headers=_h()).status_code == 400
    assert (
        c.post(
            "/api/v1/respiracion/sesion", json=_body(client_session_id="x"), headers=_h()
        ).status_code
        == 400
    )
    # Sin ni un ciclo completo.
    bad = _body(
        end_epoch_ms=_ms(2026, 9, 13) + 5_000,
        patron={"inhale_s": 4, "hold_in_s": 2, "exhale_s": 6, "hold_out_s": 3},
    )
    assert c.post("/api/v1/respiracion/sesion", json=bad, headers=_h()).status_code == 400
    # JSON inválido.
    r = c.post(
        "/api/v1/respiracion/sesion",
        content=b"{no-json",
        headers={**_h(), "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    # Nada escrito tras los 400.
    day = c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h()).json()
    assert day["count"] == 0


def test_breathing_post_rampa(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    body = _body(
        end_epoch_ms=_ms(2026, 9, 13) + 600_000,
        duracion_planeada_sec=600,
        patron={
            "inhale_s": 4.0,
            "hold_in_s": 2.0,
            "exhale_s": 6.0,
            "hold_out_s": 3.0,
            "ramp_sec": 480,
            "end_inhale_s": 6.0,
            "end_hold_in_s": 2.0,
            "end_exhale_s": 9.0,
            "end_hold_out_s": 3.0,
        },
    )
    r = c.post("/api/v1/respiracion/sesion", json=body, headers=_h())
    assert r.status_code == 200
    assert r.json()["ciclos_completados"] == 33
    assert r.json()["bpm_medio"] == 3.4


def test_breathing_post_exacto_6_6(tmp_path, monkeypatch):
    """5 rpm exactas: 6/0/6/0 × 120 s → 10 ciclos, BPM 5.0 (vector exacto_6_6)."""
    _auth(monkeypatch, tmp_path)
    c = _client()
    body = _body(
        patron={"inhale_s": 6.0, "hold_in_s": 0.0, "exhale_s": 6.0, "hold_out_s": 0.0},
    )
    r = c.post("/api/v1/respiracion/sesion", json=body, headers=_h())
    assert r.status_code == 200
    assert r.json()["ciclos_completados"] == 10
    assert r.json()["bpm_medio"] == 5.0


# --- GET día -----------------------------------------------------------------------


def test_breathing_get_dia_vacio(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    r = _client().get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["count"] == 0
    assert data["sesiones"] == []
    assert data["minutos_totales"] == 0
    assert data["ciclos_totales"] == 0


def test_breathing_get_dia_con_datos_y_totales(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    c.post("/api/v1/respiracion/sesion", json=_body(), headers=_h())
    c.post("/api/v1/respiracion/sesion", json=_body(completada=False), headers=_h())
    r = c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["minutos_totales"] == 4.0
    assert data["ciclos_totales"] == 24
    first = data["sesiones"][0]
    assert first["patron"]["inhale_s"] == 4.0
    assert first["bpm_medio"] == 6.0
    assert first["completada"] is True
    assert data["sesiones"][1]["completada"] is False


def test_breathing_get_fecha_requerida_e_invalida(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.get("/api/v1/respiracion/sesiones", headers=_h()).status_code == 400
    assert c.get("/api/v1/respiracion/sesiones?fecha=no-fecha", headers=_h()).status_code == 400
    assert c.get("/api/v1/respiracion/sesiones?fecha=13/09/2026", headers=_h()).status_code == 400


# --- DELETE --------------------------------------------------------------------------


def test_breathing_delete_idempotente(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    sid = str(uuid.uuid4())
    c.post("/api/v1/respiracion/sesion", json=_body(client_session_id=sid), headers=_h())
    first = c.delete(f"/api/v1/respiracion/sesion?client_session_id={sid}", headers=_h())
    assert first.status_code == 200
    assert first.json()["deleted"] is True
    second = c.delete(f"/api/v1/respiracion/sesion?client_session_id={sid}", headers=_h())
    assert second.status_code == 200
    assert second.json()["deleted"] is False
    day = c.get("/api/v1/respiracion/sesiones?fecha=2026-09-13", headers=_h()).json()
    assert day["count"] == 0


def test_breathing_delete_uuid_requerido(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.delete("/api/v1/respiracion/sesion", headers=_h()).status_code == 400
    assert (
        c.delete("/api/v1/respiracion/sesion?client_session_id=x", headers=_h()).status_code == 400
    )
