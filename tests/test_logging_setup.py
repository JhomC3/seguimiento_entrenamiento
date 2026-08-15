"""Logging setup: root handler + request_id context propagation."""

import logging

import pytest

from src.logging_setup import RequestIdFilter, request_id_var, setup_logging


@pytest.fixture(autouse=True)
def _reset_handler():
    setup_logging(logging.INFO)
    yield


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
