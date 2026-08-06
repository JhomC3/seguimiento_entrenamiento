"""Security baseline: header injection and CSP policy for the dashboard."""

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
