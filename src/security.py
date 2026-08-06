"""Security baseline: header injection, CSP policy and CSRF protection."""

import hashlib
import hmac
import os
import time

# The dashboard renders Plotly charts and a Tailwind runtime config as inline
# <script> elements (server-generated, no client input reaches them). That is
# why script-src/style-src keep 'unsafe-inline'; every external origin is
# pinned explicitly. See docs/architecture/security-model.md.
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com https://unpkg.com "
    "https://cdn.jsdelivr.net https://cdn.plot.ly 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

DEFAULT_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
}

CSRF_HEADER = "X-CSRF-Token"
CSRF_WINDOW_SECONDS = 24 * 3600

# Development fallback only. Set GYM_CSRF_SECRET for any non-local deployment.
_DEV_SECRET = "dev-only-secret-do-not-use-in-production"


class SecurityHeadersMiddleware:
    """Adds security headers to every response (including static assets)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for name, value in DEFAULT_HEADERS.items():
                    headers[name.lower().encode()] = value.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


def get_csrf_secret() -> str:
    """CSRF signing secret: environment in non-development deployments."""
    return os.environ.get("GYM_CSRF_SECRET", _DEV_SECRET)


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_csrf_token(secret: str) -> str:
    """Signed timestamp token: <epoch>.<hmac(secret, epoch)>."""
    ts = str(int(time.time()))
    return f"{ts}.{_sign(secret, ts)}"


def valid_csrf_token(token: str, secret: str) -> bool:
    try:
        ts, sig = token.split(".", 1)
        int(ts)
    except (ValueError, TypeError):
        return False
    if abs(int(time.time()) - int(ts)) > CSRF_WINDOW_SECONDS:
        return False
    expected = _sign(secret, ts)
    return hmac.compare_digest(sig, expected)


def _same_origin(origin: str, scope) -> bool:
    if origin == "null":
        return False
    try:
        scheme = scope["scheme"]
        server = scope.get("server") or ("", 0)
        server_host = server[0]
        server_port = server[1] if len(server) > 1 else 0
        expected = f"{scheme}://{server_host}"
        default_port = "80" if scheme == "http" else "443"
        if server_port and str(server_port) != default_port:
            expected += f":{server_port}"
        return origin == expected
    except (TypeError, ValueError):
        return False


class CSRFProtectionMiddleware:
    """Rejects cross-origin and token-less state-changing requests with 403."""

    UNSAFE_METHODS: frozenset = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _forbidden():
        return b"<div class='notice notice-error'>Solicitud rechazada.</div>", 403

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in self.UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.lower().decode(): v.decode() for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        if origin and not _same_origin(origin, scope):
            body, status = self._forbidden()
        else:
            token = headers.get(CSRF_HEADER.lower())
            if not token or not valid_csrf_token(token, get_csrf_secret()):
                body, status = self._forbidden()
            else:
                await self.app(scope, receive, send)
                return
        await self._send_response(scope, receive, send, body, status)

    @staticmethod
    async def _send_response(scope, receive, send, body: bytes, status: int):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
