"""Logging setup: root handler + request_id context propagation.

request_id_var is a contextvars.ContextVar set by the request_id middleware
(app.py) and injected into every log record via RequestIdFilter.
"""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_ROOT_HANDLER_KIND = logging.StreamHandler

_installed = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class SilenceHealthPollFilter(logging.Filter):
    """Suelta el ruido del vigilante externo (GET /health → 404).

    Un proceso local con User-Agent opencode/* sondea GET /health cada 30 s
    y esa ruta no existe (la nuestra es /healthz). Se excluye SOLO ese caso,
    en los dos formatos de access log (el propio y el de uvicorn); el resto
    de 404 siguen visibles (sondas y typos sí interesan en seguridad).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn 0.52 registra el access log como mensaje plano SIN extra:
        # args=(client, método, path, versión_http, status). El nuestro
        # (RequestIdMiddleware) usa args=(método, path, status, ...).
        args = record.args
        if isinstance(args, tuple):
            if len(args) >= 5 and args[1] == "GET" and args[2] == "/health" and args[4] == 404:
                return False
            if len(args) >= 3 and args[0] == "GET" and args[1] == "/health" and args[2] == 404:
                return False
        return True


def attach_silence_filters() -> None:
    """El filtro una sola vez por logger (lifespan puede reejecutarse en tests)."""
    for name in ("access", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, SilenceHealthPollFilter) for f in logger.filters):
            logger.addFilter(SilenceHealthPollFilter())


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent root handler with request_id in every record.

    El nivel se fija siempre; la instalación del handler es una sola vez
    (flag de módulo: pytest instala sus propios StreamHandler y no deben
    confundirse con el nuestro)."""
    global _installed
    root = logging.getLogger()
    if not _installed:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        )
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
        _installed = True
    root.setLevel(level)
