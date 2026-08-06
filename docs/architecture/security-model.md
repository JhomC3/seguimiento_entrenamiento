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
  origins for script/style, **no `'unsafe-inline'` in `script-src`**, per-response
  `nonce` for the Plotly inline payload, `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`, `connect-src 'self'`, `img-src 'self' data:`.

**Inline script policy (decided in the remediation programme):**

- All inline event handlers and the Tailwind runtime config were removed
  (Tasks 2/6); `app.js` is the only first-party executable source.
- **Tailwind CDN runs without inline configuration.** The custom
  burgundy/matte utilities previously defined in `tailwind.config` are now
  static tokens in `static/css/palette.css`. The CDN runtime injects `<style>`
  elements, so `style-src` keeps `'unsafe-inline'` (CSS injection is not script
  execution) — documented as the only remaining global inline allowance.
- **Plotly chart payloads** are the only inline `<script>`; each response CSP
  carries a fresh nonce (`request.state.csp_nonce`) and the chart fragment's
  `<script>` tag gets the same nonce. plotly JSON-escapes `</` sequences in its
  payload (regression-tested); a runtime tripwire fails loudly if that ever
  regresses.
- The `#app-config` block is `type="application/json"` (data, never executed;
  not subject to `script-src`).

### 2.2 Output encoding and event boundary

- Jinja autoescape stays enabled (default for `Jinja2Templates`).
- **User values are data attributes and text nodes only.** No inline event
  handlers exist in templates; interactions go through `data-action` attributes
  read via `element.dataset` by delegated ES-module listeners (see
  `current-ui-contract.md` §3). Dynamic values never become JavaScript source.
- **OOB messages and fragments render through Jinja partials**
  (`templates/partials/oob_*.html` via `src/response_fragments.py`); request
  values are never concatenated into HTML. The only `| safe` content is a
  server-rendered Jinja fragment or the nonced Plotly payload.
- Client-configurable data (exercise names, template names, dates) is rendered
  through Jinja escaping only. The former executable-JS interpolation
  (`const CATEGORIA_MAP = {{ ... | safe }}`) was replaced by the `#app-config`
  `type="application/json"` pattern parsed via `textContent` (Task 1.3).
- Review checklist before any new template: no `| safe` on user-supplied values;
  never build HTML/JS/URLs by string-interpolating request data (use parameterized
  SQL and form encoding); no inline `on*=` attributes.

### 2.3 SQL safety

- All SQL is parameterized (`?` placeholders); no client data is interpolated
  into statements.

### 2.4 Server-side error handling

- Domain errors (`ValidationError`, `NotFoundError`, `ConflictError`) are mapped
  to safe 400 responses with user-facing Spanish messages.
- **Unexpected exceptions are never exposed.** They are logged with
  `logger.exception` and translated to a generic "Ocurrió un error inesperado."
  (500) by `translate_error`; no SQLite/internal message reaches the browser.
- Read fallbacks in `dashboard_service` catch only `sqlite3.Error`/`OSError`
  (documented empty-result behaviour), never `Exception`.

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
5. Re-evaluate the Tailwind CDN runtime: for production, prefer a locally built
   Tailwind stylesheet so the CDN script and the `style-src 'unsafe-inline'`
   allowance can also be removed.

## 4. Runbook

- Safe local run: `uv run uvicorn app:app --host 127.0.0.1 --port 8000`
- Verify headers: `curl -sI http://127.0.0.1:8000/ | grep -iE 'content-security|x-frame|x-content'`
- Security tests: `uv run pytest tests/test_security.py -v`
