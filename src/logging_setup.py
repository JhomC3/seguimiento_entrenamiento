"""Logging setup: root handler + request_id context propagation.

request_id_var is a contextvars.ContextVar set by the request_id middleware
(app.py) and injected into every log record via RequestIdFilter.
"""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_ROOT_HANDLER_KIND = logging.StreamHandler


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent root handler with request_id in every record.

    El nivel se fija siempre (idempotencia solo evita duplicar handlers)."""
    root = logging.getLogger()
    if not any(isinstance(h, _ROOT_HANDLER_KIND) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
            )
        )
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
    root.setLevel(level)
