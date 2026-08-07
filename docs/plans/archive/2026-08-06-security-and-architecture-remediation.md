# Security and Architecture Remediation Implementation Plan

> **Status:** ✅ COMPLETED (movido a `docs/plans/archive/` el 2026-08-07)


> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the confirmed XSS vectors, make mutation failures truthful and safe, complete the client event-boundary refactor, and reduce remaining route orchestration without changing dashboard behaviour.

**Architecture:** Replace every inline event handler containing dynamic data with inert `data-*` attributes plus delegated event listeners in ES modules. Render OOB notices and fragments through Jinja templates so autoescaping is the only HTML boundary. Move session/template/undo use cases behind dashboard services; route handlers parse requests and choose HTTP responses only.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, htmx, JavaScript ES modules, SQLite, pytest, Playwright, ruff, mypy, uv.

---

## Preconditions and non-negotiable invariants

- Execute in a new worktree/branch. The current `codex` worktree is clean, but this work changes a security-sensitive rendering boundary.
- Work in priority order. Tasks 1–3 are release blockers: do not expose the dashboard beyond loopback until they pass.
- Preserve the existing UI behaviour and htmx targets. The refactor must retain IDs such as `#plantillas-section`, `#exercise-section`, `#session-editor-wrap`, `#editor-notice` and `#save-outcome`.
- Keep CSRF token injection, migrations, the 90% coverage floor, and browser workflows working throughout.
- Never solve XSS by adding more `|safe`, escaping only one quote type, or sanitizing with regex. Dynamic values must not become JavaScript source or concatenated HTML.

## Phase 1 — Close confirmed XSS vectors (P0 release blocker)

### Task 1: Add failing security regression tests for HTML/JavaScript context injection

**Files:**

- Modify: `tests/test_security.py`
- Modify: `tests/e2e/test_dashboard_flow.py`
- Modify: `tests/test_app.py`

**Step 1: Add a server-rendering regression test for hostile names.**

Use the payload `x');alert(1)//<img src=x onerror=alert(2)>` as both an exercise name and a template name. Create it through the real route/service, then load `/` and `/plantillas`.

Assert all of the following:

- the literal payload is visible as text where the name is displayed;
- no rendered attribute begins with `onclick=` / `onchange=` / `onsubmit=`;
- the payload is not present within a `<script>` element;
- no `alert(` token appears outside the escaped text node.

**Step 2: Add a browser execution regression test.**

In Playwright, register `page.on("dialog", ...)` and fail the test if any dialog appears. Create/load the hostile template, click its delete control, dismiss the dashboard confirmation, and prove no attacker dialog executed.

**Step 3: Add a dynamic notice test.**

POST `/ejercicio/nuevo` with the payload. Assert the response contains an escaped text representation, not an `<img>` element, and the browser does not create an image node in `#notice-container` after the htmx swap.

**Step 4: Run tests to prove they fail on current code.**

```bash
uv run pytest tests/test_security.py tests/test_app.py -k 'xss or hostile or notice' -v
uv run pytest tests/e2e/test_dashboard_flow.py -k xss -v
```

Expected: FAIL because `templates/plantillas_list.html`, `templates/exercise_list.html`, `templates/index.html`, and `app.py` currently interpolate data into inline handlers/HTML strings.

**Step 5: Commit tests only.**

```bash
git add tests/test_security.py tests/test_app.py tests/e2e/test_dashboard_flow.py
git commit -m "test: expose dashboard XSS rendering regressions"
```

### Task 2: Replace inline dynamic handlers with inert data attributes and delegated events

**Files:**

- Modify: `templates/plantillas_list.html`
- Modify: `templates/exercise_list.html`
- Modify: `templates/index.html`
- Modify: `templates/date_navigator.html`
- Modify: `templates/session_editor.html`
- Create: `static/js/dashboard-filters.js`
- Modify: `static/js/templates.js`
- Modify: `static/js/date-navigation.js`
- Modify: `static/js/editor.js`
- Modify: `static/js/htmx-lifecycle.js`
- Modify: `static/js/app.js`
- Modify: `tests/test_security.py`
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Define the inert DOM contract.**

Use semantic `data-action` and data values instead of executable attributes:

```html
<button type="button" data-action="delete-template" data-template-id="{{ p.id }}" data-template-name="{{ p.nombre }}">
  Eliminar
</button>
<button type="button" data-action="select-exercise" data-exercise="{{ ej }}">...</button>
```

Jinja escapes attributes correctly. JavaScript reads values through `element.dataset`; it never evaluates them as source code.

**Step 2: Move dashboard filtering out of `index.html`.**

Create `static/js/dashboard-filters.js` exporting `initDashboardFilters()`. Move `currentCategory`, `currentExercise`, category/exercise highlighting, reset, and htmx refresh logic from the inline script in `templates/index.html` into this module.

**Step 3: Add exactly one delegated click listener per feature root.**

- `dashboard-filters.js` owns category and exercise selection.
- `templates.js` owns apply/edit/delete template actions and template row actions.
- `date-navigation.js` owns date-arrow/today/date selection actions.
- `editor.js` owns edit/save-template/delete-session/add/remove row actions.

Each listener uses `event.target.closest('[data-action]')`, validates its owning root, and returns if the action is unknown. Do not add a global switch with all dashboard behaviour.

**Step 4: Make initializers idempotent.**

Since htmx replaces feature fragments, bind delegated listeners once at `document`/stable roots. `initLifecycle()` must not register duplicate handlers after an OOB swap. Add a module-level boolean or use a `data-initialized` guard only on a stable element.

**Step 5: Remove legacy bridge assignments.**

Delete `registerInlineHandlers()` and all `window.*` operational function assignments from `static/js/app.js`. Keep only public module exports for tests, never as global browser APIs.

**Step 6: Remove every inline event handler.**

Run:

```bash
rg -n 'on(click|change|submit|input|keydown)=' templates -g '*.html'
```

Expected: no matches. This includes static handlers with no dynamic values, not only the vulnerable ones.

**Step 7: Re-run security and browser tests.**

```bash
uv run pytest tests/test_security.py tests/test_app.py -v
uv run pytest tests/e2e/test_dashboard_flow.py -v
```

Expected: XSS regression tests pass and all existing user flows continue to pass.

**Step 8: Commit.**

```bash
git add templates static/js tests
git commit -m "fix: remove inline handlers from dashboard fragments"
```

### Task 3: Stop constructing user-visible HTML with string interpolation

**Files:**

- Create: `templates/partials/oob_notice.html`
- Create: `templates/partials/oob_editor_state.html`
- Create: `templates/partials/oob_editor_wrap.html`
- Create: `src/response_fragments.py`
- Modify: `app.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_security.py`

**Step 1: Write a failing fragment-rendering test.**

Render `oob_notice.html` with the hostile payload in `message`. Assert Jinja renders it as text, preserves the OOB target, and does not produce descendant elements from the payload.

**Step 2: Create a tiny, typed rendering adapter.**

In `src/response_fragments.py`, introduce a function such as:

```python
def render_fragment(
    templates: Jinja2Templates, request: Request, name: str, **context: object
) -> str:
    return templates.TemplateResponse(request=request, name=name, context=context).body.decode()
```

The adapter may render a server-owned fragment, but it must not concatenate request-derived values into HTML.

**Step 3: Replace `_notice_oob`.**

Use `oob_notice.html` for success and error notices. Pass `target`, safe CSS kind, dismiss time, and plain message as Jinja context. Validate `target` against a module-level allow-list (`notice-container`, `editor-notice`) before rendering; do not let a caller choose arbitrary element IDs.

**Step 4: Replace OOB wrapper concatenation.**

Use `oob_editor_state.html` and `oob_editor_wrap.html` for the string-built editor markers/wrappers in `app.py`. Pass the pre-rendered `editor_html` only as a server-controlled fragment; do not mark user data safe in the wrapper.

**Step 5: Preserve chart handling explicitly.**

Plotly returns a server-generated HTML fragment. Keep it isolated to a named chart wrapper; document why it is trusted. Do not reuse this trusted-fragment mechanism for exercise/template names, errors, or request values.

**Step 6: Add the negative static guard.**

In `tests/test_security.py`, inspect `app.py` or route responses to assert user-controlled fields (`ejercicio`, `nombre`, `error`) are not inserted through f-string HTML construction. Prefer behavioural tests; the source assertion is only a regression tripwire.

**Step 7: Verify and commit.**

```bash
uv run pytest tests/test_security.py tests/test_app.py -v
uv run pytest -q
git add app.py src/response_fragments.py templates/partials tests
git commit -m "fix: render dashboard OOB fragments through Jinja"
```

## Phase 2 — Correct error semantics and complete the service boundary (P1)

### Task 4: Make deletion, template mutations and undo truthful on failure

**Files:**

- Create: `src/mutation_service.py`
- Modify: `app.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_training_service.py`
- Modify: `tests/test_template_service.py`

**Step 1: Write failing failure-path tests.**

For each mutating route, monkeypatch the final persistence operation to raise `sqlite3.OperationalError("database locked")`.

Assert for session delete, template delete, template reorder and undo:

- response status is `500` for an unexpected database error;
- it contains the generic safe error notice, not a success notice;
- `#save-outcome` is absent or has `data-ok="0"`;
- the in-memory undo stack is unchanged;
- persisted rows are unchanged where the transaction fails.

**Step 2: Run focused tests and verify they fail.**

```bash
uv run pytest tests/test_app.py -k 'delete and failure or undo and failure or reorder and failure' -v
```

Expected: FAIL because `/entrenamiento/session/eliminar` swallows all exceptions and reports success.

**Step 3: Implement session mutation use cases.**

Add `delete_session`, `save_session_with_undo_snapshot`, `delete_template_with_undo_snapshot`, `reorder_templates_with_undo_snapshot`, and `undo_last_action` to `src/mutation_service.py`. Each function performs its snapshot/write/undo-return sequence as one application operation and raises domain errors or allows unexpected persistence errors to propagate.

**Step 4: Decide backup semantics once.**

Run `backup_db` before a write only when backup failure should block the write. For this dashboard, it should block: a claimed backup that did not occur is worse than a visible error. Do not use “best effort” for destructive operations.

**Step 5: Make route handlers thin.**

`app.py` should parse FastAPI form/query inputs, call one mutation service function, render fragments, and use `_domain_error_response`. It must not call `snapshot_entrenos`, `restore_entrenos`, `backup_db`, or manipulate `UNDO_STACK` directly.

**Step 6: Remove silent broad catches.**

Replace [the current `except Exception: pass` at `app.py:283`] with safe error mapping. Catch domain errors only when a different user response is intended; let the central unexpected-error path log and return a generic 500 response.

**Step 7: Verify rollback behaviour and commit.**

```bash
uv run pytest tests/test_app.py tests/test_training_service.py tests/test_template_service.py -v
uv run pytest -q
git add app.py src/mutation_service.py tests
git commit -m "fix: make dashboard mutations fail safely"
```

### Task 5: Prevent internal exception leakage and formalize exception translation

**Files:**

- Modify: `src/dashboard_service.py`
- Modify: `src/models.py`
- Modify: `src/mutation_service.py`
- Modify: `app.py`
- Modify: `templates/plantillas_list.html`
- Modify: `tests/test_security.py`
- Modify: `tests/test_app.py`

**Step 1: Write failing leak tests.**

Make `edit_template` raise `sqlite3.OperationalError("SECRET_INTERNAL_DETAIL")`. POST `/plantilla/editar/{id}` and assert the response is status `500`, includes `Ocurrió un error inesperado`, and never includes `SECRET_INTERNAL_DETAIL`.

**Step 2: Define the route exception policy.**

`ValidationError`, `NotFoundError`, and `ConflictError` become safe 400 errors. Unexpected exceptions are logged with `logger.exception` and produce a generic 500. No route may use `str(e)` as template context unless `e` is already a known domain exception.

**Step 3: Implement a single renderer for domain errors.**

Make `_domain_error_response` accept `Exception` but rely only on `translate_error`. On a validation failure that must keep a template edit form visible, pass the safe translated message, never the original exception string.

**Step 4: Narrow safe read fallbacks.**

In `src/dashboard_service.py`, replace broad `except Exception` in `get_filters` and `get_ejercicios_por_grupo` with database-specific errors (`sqlite3.Error`, `OSError` where relevant), preserve logging, and retain the documented empty-result fallback.

**Step 5: Verify and commit.**

```bash
uv run pytest tests/test_security.py tests/test_app.py -v
uv run ruff check .
uv run mypy app.py src tests
git add app.py src templates tests
git commit -m "fix: keep internal errors out of dashboard responses"
```

## Phase 3 — Finish security hardening and test depth (P2)

### Task 6: Tighten CSP after the inline-handler removal

**Files:**

- Modify: `src/security.py`
- Modify: `templates/base.html`
- Modify: `src/dashboard_service.py` (only if chart rendering needs a nonce/data change)
- Modify: `tests/test_security.py`
- Modify: `docs/architecture/security-model.md`

**Step 1: Write failing CSP tests.**

Assert the final policy does not include `'unsafe-inline'` in `script-src`. Also assert a dynamically injected `<script>` does not execute in a Playwright test.

**Step 2: Remove inline executable JavaScript from templates.**

After Task 2, `templates/index.html` and feature fragments have no inline scripts or handlers. Keep `app.js` as the only first-party executable source.

**Step 3: Resolve the remaining Tailwind and Plotly constraint deliberately.**

Choose one of these narrowly scoped options and document the decision:

1. Keep Tailwind CDN only if it can run without inline configuration; replace runtime config with static CSS tokens.
2. Build/pin local Tailwind CSS and remove the CDN runtime.
3. Keep Plotly’s server-generated inline script only behind a per-response nonce, and add the nonce to `script-src`.

Recommendation: local static Tailwind output or existing CSS for layout, plus a nonce for the Plotly fragment. Do not pretend the CSP is strict while retaining a global `'unsafe-inline'` script source.

**Step 4: Add SRI where third-party tags remain.**

Use version-pinned URLs and `integrity`/`crossorigin` attributes where the CDN supplies stable hashes. If a provider does not support a practical SRI flow, document that and prefer a local asset for production.

**Step 5: Verify browser behaviour and commit.**

```bash
uv run pytest tests/test_security.py tests/e2e -v
git add src/security.py templates/base.html docs tests
git commit -m "security: tighten dashboard content security policy"
```

### Task 7: Improve analytical test depth without gaming the global threshold

**Files:**

- Modify: `tests/test_charts.py`
- Modify: `tests/test_integration.py`
- Modify: `tests/test_coverage_edges.py`
- Modify: `pyproject.toml`

**Step 1: Add branch tests for charts.**

Cover empty data, all chart filter modes (`systemic`, muscle group, exercise), invalid/missing dates, chart title rendering, best-RM aggregation and the no-data HTML branch.

**Step 2: Add metric edge tests.**

Cover zero/NULL kg/reps/RIR, one-session baseline, multiple exercises with independent baselines, unknown exercises, and non-compound classification. Assert numerical outputs with explicit tolerances.

**Step 3: Set per-module quality floors.**

Keep the global 90% floor and add a small coverage-report validation or CI command requiring `src/charts.py` and `src/metrics_engine.py` to meet an agreed threshold (initially 85%, then raise to 90%). Do not lower the global threshold to accommodate them.

**Step 4: Run all quality gates and commit.**

```bash
uv run pytest tests/test_charts.py tests/test_integration.py tests/test_coverage_edges.py -v
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
git add pyproject.toml tests
git commit -m "test: strengthen chart and metric edge coverage"
```

## Phase 4 — Release validation

### Task 8: Update documentation and perform the release-candidate matrix

**Files:**

- Modify: `docs/architecture/security-model.md`
- Modify: `docs/architecture/current-ui-contract.md`
- Modify: `docs/operations/release-checklist.md`
- Modify: `AGENTS.md` only if implementation paths or rules change

**Step 1: Document the event contract.**

Record `data-action` names, owning JavaScript module, stable root selector, and htmx fragment that can replace the element. Remove references to `window` bridges and inline handlers.

**Step 2: Document the corrected security model.**

State that user values are data attributes/text nodes only, OOB messages render via Jinja, and unexpected errors are never exposed. Update CSP documentation to match the actual final policy.

**Step 3: Add release checklist assertions.**

Add commands that must return zero matches:

```bash
rg -n 'on(click|change|submit|input|keydown)=' templates -g '*.html'
rg -n 'innerHTML\s*=.*(message|nombre|ejercicio|error)' static app.py src -g '*.{js,py}'
```

Review any future matches manually; the second command is a security alarm, not an automatic proof of safety.

**Step 4: Run the final matrix.**

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest -q
uv run pytest tests/e2e -q
```

Expected: all pass, overall coverage remains at least 90%, hostile-payload tests pass, and no inline event attributes remain.

**Step 5: Verify CI and commit.**

Ensure `.github/workflows/ci.yml` runs the same quality, unit, and browser commands. Then commit:

```bash
git add docs AGENTS.md .github
git commit -m "docs: record dashboard security remediation"
```

## Acceptance criteria

- [ ] A hostile exercise, muscle or template name renders as inert text and never opens a JavaScript dialog or creates an HTML node.
- [ ] No inline event attributes and no operational `window.*` bridge remain in templates/client bootstrap.
- [ ] User-visible OOB content is rendered by Jinja with autoescaping; request values are not concatenated into HTML.
- [ ] Failed destructive mutations return a safe failure response and never claim success or push a false undo entry.
- [ ] Unexpected exception messages never reach the browser.
- [ ] Route handlers invoke one application service and no longer coordinate snapshots, backup and undo directly.
- [ ] CSP accurately reflects the runtime and has no global inline-script allowance after the selected Tailwind/Plotly approach is implemented.
- [ ] Full locked/lint/type/unit/browser suite passes in CI and locally.
