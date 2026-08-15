"""Logging setup: root handler + request_id context propagation."""

import logging

import pytest

from src.logging_setup import RequestIdFilter, request_id_var, setup_logging


@pytest.fixture(autouse=True)
def _reset_handler():
    setup_logging(logging.INFO)
    yield


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app as appmod
    from fastapi.testclient import TestClient
    from src.database import init_db

    db = str(tmp_path / "gym.db")
    init_db(db)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    return TestClient(appmod.app)


def test_setup_logging_instala_handler_y_nivel():
    setup_logging(logging.INFO)
    root = logging.getLogger()
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert root.level <= logging.INFO


def test_setup_logging_idempotente():
    setup_logging(logging.INFO)
    before = len(logging.getLogger().handlers)
    setup_logging(logging.INFO)
    assert len(logging.getLogger().handlers) == before


def test_request_id_filter_inyecta_contexto(caplog):
    token = request_id_var.set("req-123")
    try:
        logger = logging.getLogger("dashboard")
        with caplog.at_level(logging.INFO, logger="dashboard"):
            logger.info("mensaje de prueba")
    finally:
        request_id_var.reset(token)
    assert caplog.records and caplog.records[0].request_id == "req-123"


def test_request_id_default_guion(caplog):
    logger = logging.getLogger("dashboard")
    with caplog.at_level(logging.INFO, logger="dashboard"):
        logger.info("sin id")
    assert caplog.records and caplog.records[0].request_id == "-"


def test_setup_logging_respects_level_param():
    setup_logging(logging.WARNING)
    assert logging.getLogger().level <= logging.WARNING


# ---------------------------------------------------------------------------
# Backend plan Task 2: request_id middleware + access log
# ---------------------------------------------------------------------------


def test_request_id_header_presente(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")


def test_request_id_header_en_rechazo_csrf(client):
    resp = client.post("/entrenamiento/session/save", data={})
    assert resp.status_code == 403
    assert resp.headers.get("x-request-id")


def test_request_id_log_de_peticion(caplog, client):
    import logging

    with caplog.at_level(logging.INFO, logger="access"):
        client.get("/fecha/editor?fecha=2026-08-14")
    assert any("GET /fecha/editor" in r.getMessage() for r in caplog.records)
    assert any(getattr(r, "request_id", None) for r in caplog.records)


def test_request_ids_unicos_por_peticion(client):
    r1 = client.get("/").headers.get("x-request-id")
    r2 = client.get("/").headers.get("x-request-id")
    assert r1 and r2 and r1 != r2
