"""Security baseline: header injection, CSP policy and CSRF protection."""

import hashlib
import hmac
import logging
import os
import secrets
import time

logger = logging.getLogger("security")

# Every executable script is external ('self' or pinned CDNs): the CSP allows
# no inline scripts (no nonce, no 'unsafe-inline'). Data-only elements like
# <script type="application/json"> (app-config, chart figure) are inert and
# unaffected by script-src. style-src keeps 'unsafe-inline' because Plotly
# injects <style> elements at runtime (CSS injection is not script
# execution). See docs/architecture/security-model.md.
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com "
    "https://cdn.jsdelivr.net https://cdn.plot.ly; "
    "style-src 'self' 'unsafe-inline'; "
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
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

CSRF_HEADER = "X-CSRF-Token"

# API endpoints with their own credential are exempted from the form-CSRF
# checks. The exemption is an EXACT path match, never a prefix: a path like
# /sync/other keeps full CSRF protection. See health-sync-contract.md and
# training-api-contract.md. Only mutating API paths need exemption (GET is a
# safe method and never checked).
CSRF_EXEMPT_PATHS: frozenset = frozenset(
    {
        "/sync/health-connect",
        "/api/v1/sesion",
        "/api/v1/plantilla/guardar",
        "/api/v1/plantilla/aplicar",
        "/api/v1/ejercicio",
        "/api/v1/undo",
        "/api/v1/diario",
        "/api/v1/alimento",
        "/api/v1/plantilla-comida/guardar",
        "/api/v1/plantilla-comida/aplicar",
        "/api/v1/cardio/anotacion",
    }
)


# Loopback-only fallback: cryptographically random per process, never public.
# Tokens signed with it become invalid on restart (acceptable: loopback dev,
# reload re-embeds a fresh token). GYM_CSRF_SECRET (LAN launcher) overrides it.
_FALLBACK_SECRET = secrets.token_urlsafe(48)


class SecurityHeadersMiddleware:
    """Adds security headers (incl. the static CSP) to every response."""

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
                headers[b"content-security-policy"] = CSP.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


def get_csrf_secret() -> str:
    """CSRF signing secret: environment for the LAN launcher, random otherwise."""
    return os.environ.get("GYM_CSRF_SECRET", _FALLBACK_SECRET)


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
    expected = _sign(secret, ts)
    return hmac.compare_digest(sig, expected)


def _same_origin(
    origin: str, scheme: str, host_header: str | None, server: tuple[str, int | None] | None
) -> bool:
    """True si Origin == scheme://<Host header> (sin Host, contra scheme://<server>).

    El Host header refleja la autoridad que el cliente usó realmente: el navegador
    lo fija desde la URL y XHR/fetch no pueden alterarlo (mismo nivel de confianza
    que Origin; patrón OWASP/Django). scope['server'] en uvicorn es la dirección de
    bind del socket: con --host 0.0.0.0 sería '0.0.0.0' y jamás coincidiría con el
    Origin del navegador (127.0.0.1, localhost, IP LAN).
    """
    if origin == "null":
        return False
    try:
        if host_header:
            return origin == f"{scheme}://{host_header}"
        if not server:
            return False
        host, port = server
        expected = f"{scheme}://{host}"
        default_port = "80" if scheme == "http" else "443"
        if port and str(port) != default_port:
            expected += f":{port}"
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
        body = (
            "<div class='notice notice-error'>Solicitud no autorizada. "
            "Recarga la página e intenta de nuevo.</div>"
        )
        return body.encode(), 403

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in self.UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") in CSRF_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {k.lower().decode(): v.decode() for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        token = headers.get(CSRF_HEADER.lower())
        if origin and not _same_origin(
            origin, scope["scheme"], headers.get("host"), scope.get("server")
        ):
            logger.warning(
                "CSRF reject (origin): origin=%r host=%r path=%s",
                origin,
                headers.get("host"),
                scope.get("path", ""),
            )
            body, status = self._forbidden()
        elif not token or not valid_csrf_token(token, get_csrf_secret()):
            logger.warning(
                "CSRF reject (token): present=%s origin=%r host=%r path=%s",
                bool(token),
                origin,
                headers.get("host"),
                scope.get("path", ""),
            )
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
