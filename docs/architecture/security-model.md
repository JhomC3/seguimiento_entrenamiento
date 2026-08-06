# Security Model

> **Deployment assumption (default):** this dashboard is a **personal, loopback-only**
> application. It has no authentication or authorization layer. The only safe default
> deployment is binding to `127.0.0.1` (`uvicorn app:app --host 127.0.0.1`).
> Any LAN or internet exposure requires an authentication and authorization design
> before release (see "Before exposing on a network" below).

## 1. Assets and trust boundaries

| Asset | Notes |
|---|---|
| Browser clients | Same-origin htmx; CDN resources loaded with pinned versions |
| `GET` routes | Read-only data + charts |
| `POST` mutating routes | Session save/delete, template CRUD/reorder, undo, exercise create |
| SQLite DB (`data/gym.db`) | Local file; backups in `data/backups/` before pending migrations and mutations |
| Google Sheets import | `/sync`-style import path is separate (`src/fetcher.py`, `src/parser.py`); not part of the HTTP surface |

All data originates from the owner's own training log; the primary threats are
accidental data loss and drive-by browser attacks, not a motivated adversary.

## 2. Controls in place

### 2.1 Security headers (all responses, via `src/security.py`)

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`
- `X-Frame-Options: DENY` (no framing; equivalent CSP `frame-ancestors 'none'`)
- `Content-Security-Policy` — restrictive `default-src 'self'`, explicit pinned CDN
  origins for script/style, `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `connect-src 'self'`, `img-src 'self' data:`.

**Why `'unsafe-inline'` in script-src/style-src:** Plotly charts are rendered
server-side as inline `<script>` payloads, and the Tailwind CDN runtime requires
an inline config script plus runtime-injected styles. No client-supplied value is
ever interpolated into those inline blocks (see §2.3). Removing `'unsafe-inline'`
requires moving chart payloads to nonced external scripts — tracked as future work.

### 2.2 Output encoding

- Jinja autoescape stays enabled (default for `Jinja2Templates`).
- Client-configurable data (exercise names, template names, dates) is rendered
  through Jinja escaping only. The one former executable-JS interpolation
  (`const CATEGORIA_MAP = {{ ... | safe }}`) was replaced by the `#app-config`
  `type="application/json"` pattern parsed via `textContent` (Task 1.3).
- Review checklist before any new template: no `| safe` on user-supplied values;
  never build HTML/JS/URLs by string-interpolating request data (use parameterized
  SQL and form encoding).

### 2.3 SQL safety

- All SQL is parameterized (`?` placeholders); no client data is interpolated
  into statements.

### 2.4 Server-side error handling

- Domain errors (`ValidationError`, `NotFoundError`, `ConflictError`) are mapped
  to safe 400 responses with user-facing Spanish messages.
- Unexpected exceptions are logged server-side with context; clients receive a
  generic "Ocurrió un error inesperado." (500). No SQLite exception text reaches
  the browser.

### 2.5 CSRF / cross-origin protection

- **Same-origin browser flows** carry a signed CSRF token injected into
  `#app-config` and validated for mutating requests, plus `Origin` validation as
  defence in depth (Task 5.2). For loopback-only deployments this is documented
  as adequate: a cross-site attacker cannot read the token (CSP `connect-src 'self'`
  blocks token exfiltration) and cannot reach the loopback server from a browser
  without the token.
- **Before any non-loopback deployment:** Origin/token checks must stay enabled,
  the CSRF secret must come from the environment (`GYM_CSRF_SECRET`), and this
  document must be updated with the exposure model.

## 3. Before exposing on a network

1. Add authentication (login + session cookies) and authorization (owner-only).
2. Move CSRF secret to a managed environment variable; disable fallback secrets.
3. Switch server binding away from `127.0.0.1` only after 1–2 are done.
4. Re-run the full security test suite and the browser suite against the new
   deployment origin.
5. Remove `'unsafe-inline'` from the CSP (nonced chart payloads) before any
   untrusted content model is introduced.

## 4. Runbook

- Safe local run: `uv run uvicorn app:app --host 127.0.0.1 --port 8000`
- Verify headers: `curl -sI http://127.0.0.1:8000/ | grep -iE 'content-security|x-frame|x-content'`
- Security tests: `uv run pytest tests/test_security.py -v`
