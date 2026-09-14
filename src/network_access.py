"""Network isolation: remote (LAN) traffic is allowed only for HealthSync
and the training diary JSON API (v1).

The dashboard UI (HTML, static assets, exports, htmx mutations) is served to
loopback clients only. Remote peers can use exactly:
- POST /sync/health-connect (Health Connect ingest, X-Sync-Token), and
- the training API: GET /api/v1/sesion, GET /api/v1/ejercicios,
  POST /api/v1/sesion, DELETE /api/v1/sesion (same X-Sync-Token);
every other remote request is rejected with a bare 403 before the body is
parsed. A bounded per-peer rate limiter protects all allowed remote paths.

The gate is active only when GYM_LAN_SYNC_ONLY=1 (set by scripts/start_server.sh);
otherwise the middleware is inert, preserving loopback-only development.
Only the ASGI scope['client'] address is trusted: X-Forwarded-For headers are
ignored by construction (uvicorn fills 'client' from the TCP peer).
"""

import ipaddress
import logging
import os
import time

logger = logging.getLogger("network")

SYNC_PATH = "/sync/health-connect"

# Training diary JSON API (v1, mismo X-Sync-Token). Rutas exactas, nunca
# prefijo: /api/v1/sesion/extra sigue bloqueado. Ver training-api-contract.md.
API_SESSION_PATH = "/api/v1/sesion"
API_EXERCISES_PATH = "/api/v1/ejercicios"

# (método, path) remotos permitidos bajo el gate. Todo lo demás → 403.
ALLOWED_REMOTE_ROUTES: frozenset = frozenset(
    {
        ("POST", SYNC_PATH),
        ("GET", API_SESSION_PATH),
        ("POST", API_SESSION_PATH),
        ("DELETE", API_SESSION_PATH),
        ("GET", API_EXERCISES_PATH),
        ("GET", "/api/v1/plantillas"),
        ("POST", "/api/v1/plantilla/guardar"),
        ("POST", "/api/v1/plantilla/aplicar"),
        ("POST", "/api/v1/ejercicio"),
        ("GET", "/api/v1/undo/peek"),
        ("POST", "/api/v1/undo"),
        ("GET", "/api/v1/diario"),
        ("POST", "/api/v1/diario"),
        ("DELETE", "/api/v1/diario"),
        ("GET", "/api/v1/alimentos"),
        ("POST", "/api/v1/alimento"),
        ("GET", "/api/v1/plantillas-comida"),
        ("POST", "/api/v1/plantilla-comida/guardar"),
        ("POST", "/api/v1/plantilla-comida/aplicar"),
        ("GET", "/api/v1/sugerencia"),
        ("GET", "/api/v1/ejercicio/ultimo"),
        ("GET", "/api/v1/cardio"),
        ("POST", "/api/v1/cardio/anotacion"),
        ("GET", "/api/v1/fechas"),
    }
)

_DEFAULT_RATE_LIMIT_PER_MINUTE = 30
_MAX_TRACKED_PEERS = 1024


def lan_sync_only_enabled() -> bool:
    """The LAN gate is active only when GYM_LAN_SYNC_ONLY=1."""
    return os.environ.get("GYM_LAN_SYNC_ONLY") == "1"


def sync_rate_limit_per_minute() -> int:
    """Per-peer sync POSTs per minute; invalid or zero values fall back."""
    try:
        return max(1, int(os.environ.get("GYM_SYNC_RATE_LIMIT_PER_MINUTE", "30")))
    except ValueError:
        return _DEFAULT_RATE_LIMIT_PER_MINUTE


def _is_loopback(client: tuple[str, int | None] | None) -> bool:
    if not client:
        return False
    host, _port = client
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _FixedWindowLimiter:
    """Bounded per-peer fixed-window counter (requests per 60 s window)."""

    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}

    def allow(self, peer: str) -> bool:
        now = time.monotonic()
        buckets = self._buckets
        if len(buckets) >= _MAX_TRACKED_PEERS and peer not in buckets:
            self._evict_expired(now)
        if len(buckets) >= _MAX_TRACKED_PEERS and peer not in buckets:
            return False
        start, count = buckets.get(peer, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0
        if count >= self.limit:
            return False
        buckets[peer] = (start, count + 1)
        return True

    def retry_after_seconds(self, peer: str) -> int:
        now = time.monotonic()
        start, _count = self._buckets.get(peer, (now, 0))
        remaining = self.window_seconds - (now - start)
        return max(1, int(remaining) + 1)

    def _evict_expired(self, now: float) -> None:
        for peer in [
            p for p, (start, _c) in self._buckets.items() if now - start >= self.window_seconds
        ]:
            del self._buckets[peer]


class LanSyncOnlyMiddleware:
    """Rejects non-loopback dashboard traffic; allows only the sync + API routes.

    Registered in app.py so it runs before the CSRF middleware: remote
    dashboard requests get a bare 403/429 without any HTML surface.
    """

    def __init__(self, app):
        self.app = app
        self.limiter = _FixedWindowLimiter(sync_rate_limit_per_minute())

    async def __call__(self, scope, receive, send):
        if not lan_sync_only_enabled() or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        if _is_loopback(client):
            await self.app(scope, receive, send)
            return
        if (scope["method"], scope.get("path", "")) in ALLOWED_REMOTE_ROUTES:
            peer = client[0] if client else "unknown"
            if not self.limiter.allow(peer):
                logger.warning("LAN sync rate limit exceeded: peer=%s", peer)
                await self._reject(
                    scope,
                    receive,
                    send,
                    status=429,
                    retry_after=self.limiter.retry_after_seconds(peer),
                )
                return
            await self.app(scope, receive, send)
            return
        logger.warning(
            "LAN sync-only reject: client=%s method=%s path=%s",
            client,
            scope.get("method"),
            scope.get("path", ""),
        )
        await self._reject(scope, receive, send, status=403)

    @staticmethod
    async def _reject(scope, receive, send, *, status: int, retry_after: int | None = None):
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", b"0"),
        ]
        if retry_after is not None:
            headers.append((b"retry-after", str(retry_after).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b""})
