"""Filtro de silencio del vigilante externo (GET /health → 404)."""

import logging

from src.logging_setup import SilenceHealthPollFilter, attach_silence_filters


def _record(name, msg, args=(), **attrs):
    record = logging.LogRecord(name, logging.INFO, __file__, 0, msg, args, None)
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


def test_silencia_health_404_uvicorn():
    f = SilenceHealthPollFilter()
    record = _record(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:57691", "GET", "/health", "1.1", 404),
    )
    assert f.filter(record) is False


def test_silencia_health_404_propio():
    f = SilenceHealthPollFilter()
    record = _record("access", "%s %s status=%s duration_ms=%.1f", ("GET", "/health", 404, 1.2))
    assert f.filter(record) is False


def test_conserva_otros_404_y_errores():
    f = SilenceHealthPollFilter()
    assert f.filter(_record("access", "%s %s status=%s", ("GET", "/otro", 404))) is True
    assert (
        f.filter(
            _record(
                "uvicorn.access",
                '%s - "%s %s HTTP/%s" %d',
                ("127.0.0.1:1", "GET", "/otro", "1.1", 404),
            )
        )
        is True
    )
    assert f.filter(_record("access", "%s %s status=%s", ("GET", "/health", 200))) is True


def test_attach_idempotente():
    attach_silence_filters()
    attach_silence_filters()
    count = sum(isinstance(f, SilenceHealthPollFilter) for f in logging.getLogger("access").filters)
    assert count == 1
