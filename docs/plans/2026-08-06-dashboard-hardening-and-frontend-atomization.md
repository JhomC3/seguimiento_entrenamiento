# Dashboard Hardening and Frontend Atomization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the monolithic client layout into maintainable, tested assets while strengthening persistence, architecture, security, dependency management, and automated quality gates without changing the dashboard's user-visible behaviour.

**Architecture:** Keep FastAPI server-rendered HTML and htmx.  `base.html` becomes a small layout shell; page-specific CSS and JavaScript move to static, responsibility-based files while retaining the existing DOM contract during the migration.  Database access is consolidated behind a configured SQLite connection factory and versioned migrations; route handlers become thin orchestration layers over typed services.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, SQLite, pandas, Plotly, pytest, Playwright, ruff, mypy, uv, GitHub Actions (or the repository's CI provider).

---

## Scope, non-goals, and success criteria

### In scope

- Atomize the 1,282-line `templates/base.html` into a stable Jinja layout, partials, CSS and JavaScript modules.
- Preserve all current dashboard operations: date navigation, session editing/saving/deleting, undo, template CRUD/application/reordering, row ordering, notices, calculated RM, htmx out-of-band swaps, charts and CSV export.
- Establish a reliable SQLite boundary, versioned schema migrations and data-integrity checks.
- Separate HTTP/view rendering, application services and persistence enough to keep `app.py` thin.
- Add focused unit, integration, browser and security-regression tests; make them CI-enforced.
- Lock dependencies and add static analysis and formatting gates.

### Explicit non-goals

- Do not change visual design, routes, database semantics, or the Google Sheets import flow in this programme.
- Do not introduce a SPA, a frontend build framework, an ORM, user accounts, or a third-party migration library.  They add complexity without addressing the current bottleneck.
- Do not rewrite stored `fecha` values in this programme.  Existing `d/m/yy` values are part of the current data contract.  A future normalized-date migration needs its own backup and migration plan.

### Definition of done

- `base.html` contains only layout/configuration and includes; client behaviour lives outside it by responsibility.
- All current 93 tests still pass, and added unit/integration/browser tests cover critical paths and failure modes.
- A fresh database and each supported legacy schema migrate idempotently, transactionally and with foreign keys enabled.
- No route handler issues raw SQL or contains multi-step domain logic.
- `uv sync --locked`, formatting, linting, typing, unit tests and browser smoke tests run in CI.
- Security headers and request-origin protection match the deployment model, with regression tests.

## Guardrails for every phase

1. Work on a new `codex/` branch or isolated worktree; do not overwrite the existing uncommitted changes in `AGENTS.md`, `templates/base.html`, `templates/index.html`, `templates/session_editor.html`, `scripts/verify_editor.py`, or `tests/test_app.py`.
2. Before each change, run the narrowest relevant failing test; after each logical change run its narrow test plus `uv run pytest -q`.
3. Preserve existing IDs, `data-*` attributes, form field names, htmx targets and `hx-swap-oob` markers until their browser tests prove an intentional contract change.
4. One logical commit per task.  Never include generated databases, `.venv`, browser downloads, caches or unrelated user changes.
5. Use parameterized SQL only.  Do not interpolate client data into SQL, HTML, JavaScript or URLs.

# Phase 0 — Baseline and safety rails (blocker for all code changes)

### Task 0.1: Capture the current behavioural contract

**Files:**
- Create: `docs/architecture/current-ui-contract.md`
- Modify: none
- Test: existing `tests/test_app.py`, `tests/test_training_service.py`, `tests/test_template_service.py`

**Step 1: Record the current contract.**

Document the route, method, form inputs, target element, OOB markers and expected user outcome for `/`, `/fecha/editor`, `/entrenamiento/session/save`, `/entrenamiento/session/eliminar`, `/plantilla/*`, `/undo`, `/exportar/csv`, `/select`, `/grupo/reset` and `/ejercicio`.

**Step 2: Record frontend invariants.**

Include stable selectors such as `#session-editor-wrap`, `#session-editor`, `#session-form`, `#set-rows`, `#plantillas-section`, `#notice-container`, `#editor-state`, `#save-outcome` and `#undo-result`.

**Step 3: Run the baseline suite.**

Run: `uv run pytest -q`

Expected: the current suite passes; record the count and any warnings in the document.

**Step 4: Commit.**

```bash
git add docs/architecture/current-ui-contract.md
git commit -m "docs: capture dashboard UI contract"
```

### Task 0.2: Add a reproducible development toolchain

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Modify: `requirements.txt` (only if it remains as a compatibility export)
- Create: `.gitignore` (or modify it if present)
- Test: no source test file required

**Step 1: Write the failing reproducibility check.**

Create a CI shell step that runs `uv sync --locked` and fails if a lock file is absent or stale.

**Step 2: Define project metadata and tool configuration.**

Use Python `>=3.11` as stated by the project.  Define runtime dependencies, a `dev` dependency group for `pytest`, `pytest-cov`, `ruff`, `mypy`, Playwright and type stubs where needed.  Configure ruff and mypy with an initially realistic, explicit scope (`app.py`, `src`, `tests`).

**Step 3: Generate the lock file using uv.**

Run: `uv lock`

Expected: `uv.lock` is created and `uv sync --locked` succeeds from a clean environment.

**Step 4: Verify the interpreter mismatch is resolved.**

Run: `uv run python --version`

Expected: Python 3.11 or newer, rather than the current Python 3.10 virtual environment.

**Step 5: Commit.**

```bash
git add pyproject.toml uv.lock requirements.txt .gitignore
git commit -m "build: lock Python development environment"
```

# Phase 1 — Atomize the frontend without changing behaviour (highest maintainability impact)

### Task 1.1: Add static-file serving and a frontend asset contract test

**Files:**
- Modify: `app.py`
- Create: `static/css/.gitkeep`
- Create: `static/js/.gitkeep`
- Modify: `tests/test_app.py`

**Step 1: Write failing tests.**

Add tests asserting `GET /` returns references to `/static/css/app.css` and `/static/js/app.js`, and `GET /static/css/app.css` plus `GET /static/js/app.js` return `200` with the correct content type.

**Step 2: Run the focused tests.**

Run: `uv run pytest tests/test_app.py -k static -v`

Expected: FAIL because static assets are not mounted or referenced.

**Step 3: Implement the minimum FastAPI setup.**

Mount `StaticFiles(directory="static")` at `/static` in `app.py`.  Do not serve user-provided paths and do not expose project-root files.

**Step 4: Add empty, tracked asset entry points.**

Create `static/css/app.css` and `static/js/app.js`; replace `.gitkeep` with those real files.

**Step 5: Re-run focused tests and commit.**

```bash
uv run pytest tests/test_app.py -k static -v
git add app.py static tests/test_app.py
git commit -m "feat: serve dashboard static assets"
```

### Task 1.2: Extract global styling from the layout

**Files:**
- Modify: `templates/base.html`
- Create: `static/css/theme.css`
- Create: `static/css/components.css`
- Create: `static/css/date-navigator.css`
- Create: `static/css/session-editor.css`
- Create: `static/css/templates.css`
- Modify: `static/css/app.css`
- Modify: `tests/test_app.py`

**Step 1: Add a regression test before moving CSS.**

Assert that the rendered index includes the ordered CSS assets and no longer contains the large inline style block.  Retain the Tailwind configuration temporarily because it is runtime configuration, not component CSS.

**Step 2: Move only global design tokens and generic rules.**

Put `:root`, `body`, scrollbar, focus, neon and metallic definitions in `theme.css` or `components.css`.

**Step 3: Move feature styles by owning UI.**

Move date selector rules into `date-navigator.css`; row, editor and RM rules into `session-editor.css`; template-list rules into `templates.css`.  Preserve selector names exactly in this task.

**Step 4: Make `app.css` a deterministic import manifest.**

Use CSS `@import` statements in this order: theme, components, date navigator, session editor, templates.  This preserves cascade order and makes future ownership obvious.

**Step 5: Verify styles are actually served.**

Run: `uv run pytest tests/test_app.py -k 'static or index' -v`

Run: `uv run pytest -q`

Expected: both pass with no selector or template regressions.

**Step 6: Commit.**

```bash
git add templates/base.html static/css tests/test_app.py
git commit -m "refactor: extract dashboard styles from base layout"
```

### Task 1.3: Extract client code into responsibility-based modules

**Files:**
- Modify: `templates/base.html`
- Create: `static/js/state.js`
- Create: `static/js/notices.js`
- Create: `static/js/editor.js`
- Create: `static/js/row-sortable.js`
- Create: `static/js/templates.js`
- Create: `static/js/date-navigation.js`
- Create: `static/js/htmx-lifecycle.js`
- Modify: `static/js/app.js`
- Modify: `tests/test_app.py`

**Step 1: Specify the module boundary in a testable comment.**

At the top of each module, document the DOM elements it owns and the public API it exposes.  `state.js` owns shared ephemeral state; no other module may mutate it directly.

**Step 2: Write source-contract tests.**

Add tests that verify `base.html` loads only `app.js` (as an ES module) and contains no inline operational functions such as `submitSave`, `doNav`, `aplicarPlantilla`, or `recalcRM`.

**Step 3: Move state and small pure helpers.**

Move `pendingNav`, confirmation callbacks, dirty-state serialisation, `fmtNum`, and selector helpers to `state.js`.  Export explicit functions; do not leave mutable globals on `window`.

**Step 4: Move each coherent interaction.**

- `notices.js`: scheduling and display of notifications.
- `editor.js`: edit mode, row add/remove/re-numbering, form serialization, RM recalculation and save submission.
- `row-sortable.js`: Sortable setup/teardown for session rows.
- `templates.js`: template form, apply/delete/edit/reorder and template-row Sortable setup.
- `date-navigation.js`: selected-date changes, unsaved-change confirmation and date dots.
- `htmx-lifecycle.js`: delegated `htmx:*` handlers; it calls module initializers rather than duplicating their logic.

**Step 5: Add a single bootstrap.**

`app.js` imports modules, reads `#app-config` JSON generated by Jinja, listens once for `DOMContentLoaded`, and initializes the current DOM.  It must be safe if htmx replaces the editor or templates section multiple times.

**Step 6: Preserve security at the template-to-JS boundary.**

Replace `const CATEGORIA_MAP = {{ categoria_map_json | safe }}` with `<script id="app-config" type="application/json">{{ app_config_json }}</script>` and parse `textContent`.  Serialize JSON on the server; never interpolate untrusted strings into executable JavaScript.

**Step 7: Run unit, integration and browser tests.**

Run: `uv run pytest tests/test_app.py -v`

Run: `uv run pytest -q`

Browser tests introduced in Phase 2 must pass before merging this task.

**Step 8: Commit.**

```bash
git add templates/base.html static/js tests/test_app.py
git commit -m "refactor: modularize dashboard client behaviour"
```

### Task 1.4: Make `base.html` a real layout and extract reusable markup

**Files:**
- Modify: `templates/base.html`
- Create: `templates/partials/confirm_modal.html`
- Create: `templates/partials/notices.html`
- Create: `templates/partials/app_config.html`
- Modify: `templates/index.html`
- Modify: `tests/test_app.py`

**Step 1: Write rendering tests.**

Assert the index includes the confirm modal, notice container and application config exactly once.  Assert an htmx partial response does not accidentally include a second full HTML document.

**Step 2: Extract global markup.**

Move the confirmation modal, notification container and JSON configuration script to partials.  Include them from `base.html` once.

**Step 3: Keep page-owned markup in page/feature templates.**

Do not move `session_editor.html`, `date_navigator.html`, `plantillas_list.html` or their htmx OOB wrappers into `base.html`.  They are feature fragments and must remain independently renderable.

**Step 4: Reduce `base.html`.**

It should contain document metadata, third-party library tags, Tailwind runtime configuration, static CSS/JS references, global partial includes and `{% block content %}` only.

**Step 5: Verify and commit.**

```bash
uv run pytest tests/test_app.py -v
git add templates tests/test_app.py
git commit -m "refactor: reduce base template to application shell"
```

# Phase 2 — Make the UI refactor observable and safe

### Task 2.1: Establish browser-test infrastructure

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_dashboard_flow.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Step 1: Write the first failing end-to-end test.**

Start the app against a temporary DB with one known exercise.  Using Playwright, open `/`, select today's editor, fill an exercise, kg, reps and RIR, save, and assert the success notification and read-only state.

**Step 2: Install and pin browser requirements through uv.**

Use the existing `playwright` dependency from the locked dev group.  Add a documented one-time browser-install CI step; do not commit browser binaries.

**Step 3: Add fixture isolation.**

Use a temporary DB and monkeypatch/configure `DB_PATH`.  Start uvicorn on a random local port and always terminate it in fixture teardown.

**Step 4: Run the test.**

Run: `uv run pytest tests/e2e/test_dashboard_flow.py -v`

Expected: PASS without reaching external network resources except explicitly permitted CDN assets.  If offline tests are required, Phase 5 replaces CDN assets.

**Step 5: Commit.**

```bash
git add tests/e2e pyproject.toml .gitignore uv.lock
git commit -m "test: add isolated dashboard browser smoke test"
```

### Task 2.2: Cover high-risk htmx interactions

**Files:**
- Modify: `tests/e2e/test_dashboard_flow.py`
- Modify: `tests/test_app.py`

**Step 1: Add one test per supported workflow.**

Cover: unsaved-change confirmation when navigating date; add/remove/reorder a set; apply a template; create/edit/reorder/delete a template; delete and undo a session; invalid numeric input; and empty-state chart rendering.

**Step 2: Test the behaviour, not incidental markup.**

Prefer accessible roles, stable `data-testid` values and DOM state over long assertions on CSS class strings.  Add `data-testid` only where a stable semantic selector does not already exist.

**Step 3: Add server contract tests for OOB responses.**

For each mutating route, assert status code, OOB target and successful/error marker.  Continue testing validation error messages at service level.

**Step 4: Run the focused suites.**

```bash
uv run pytest tests/test_app.py tests/e2e -v
uv run pytest -q
```

**Step 5: Commit.**

```bash
git add tests/test_app.py tests/e2e
git commit -m "test: cover htmx editing and template workflows"
```

# Phase 3 — Harden persistence before widening the service layer

### Task 3.1: Introduce a single SQLite connection factory

**Files:**
- Create: `src/db_connection.py`
- Modify: `src/database.py`
- Modify: `src/training_service.py`
- Modify: `src/charts.py`
- Modify: `src/metrics_engine.py`
- Modify: `app.py`
- Create: `tests/test_db_connection.py`

**Step 1: Write failing connection tests.**

Test that a connection returned by `connect_db` has `PRAGMA foreign_keys = 1`, a nonzero `busy_timeout`, `sqlite3.Row` row factory, and that read/write context managers close even after an exception.

**Step 2: Implement `connect_db`.**

Create `connect_db(db_path: str) -> sqlite3.Connection`.  Enable `foreign_keys`, set `busy_timeout`, set `row_factory = sqlite3.Row`; use WAL only after a compatibility test confirms it works for the project's filesystem.  Keep one connection per request/operation; do not introduce a global connection.

**Step 3: Add context managers.**

Add `read_connection` and `transaction` context managers that guarantee closure and rollback.  The write context must use `BEGIN IMMEDIATE` only if the concurrency test proves ordinary deferred transactions are insufficient.

**Step 4: Migrate one module at a time.**

Replace direct `sqlite3.connect` use in the listed modules while preserving parameterized queries and return formats.  Start with `training_service.py`, then `database.py`, then read-only chart/metric code, then app helpers.

**Step 5: Add integrity regression tests.**

Test deleting a template deletes its `plantilla_sets` children.  Test a failed multi-row session save rolls back rather than leaving partial rows.

**Step 6: Run and commit.**

```bash
uv run pytest tests/test_db_connection.py tests/test_database.py tests/test_training_service.py -v
uv run pytest -q
git add src app.py tests
git commit -m "refactor: centralize configured SQLite connections"
```

### Task 3.2: Replace ad-hoc schema changes with versioned migrations

**Files:**
- Create: `src/migrations/__init__.py`
- Create: `src/migrations/v001_initial_schema.py`
- Create: `src/migrations/v002_add_origins_and_categories.py`
- Create: `src/migrations/v003_add_template_order.py`
- Create: `src/migrations/runner.py`
- Modify: `src/database.py`
- Modify: `tests/test_database.py`

**Step 1: Write migration tests first.**

Create databases representing each known prior state from current tests.  Assert migration reaches the latest version, preserves rows, backfills expected values, creates indexes, and is idempotent.

**Step 2: Create migration metadata.**

Create `schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`.  Record each migration only after its transaction succeeds.

**Step 3: Move schema creation into migration `v001`.**

The migration must define all current tables, indexes and foreign keys.  It must be safe only for a new database.

**Step 4: Encode historical upgrades explicitly.**

`v002` adds/backfills `origen` and `categoria`; `v003` adds/backfills `plantillas.orden`.  Each must inspect legacy columns defensively and run transactionally.

**Step 5: Reduce `init_db`.**

Leave it responsible only for directory creation, connecting and calling the migration runner.  Remove direct scattered `ALTER TABLE` conditions.

**Step 6: Add backup-before-upgrade behaviour.**

For an existing production DB, create a timestamped backup before applying a pending migration.  Test that the backup occurs only when versions are pending, not on every startup.

**Step 7: Verify and commit.**

```bash
uv run pytest tests/test_database.py -v
uv run pytest -q
git add src/migrations src/database.py tests/test_database.py
git commit -m "feat: add versioned SQLite migrations"
```

# Phase 4 — Clarify architecture and data validation

### Task 4.1: Introduce typed domain models at service boundaries

**Files:**
- Create: `src/models.py`
- Modify: `src/training_service.py`
- Modify: `src/template_service.py`
- Modify: `src/database.py`
- Modify: `tests/test_training_service.py`
- Modify: `tests/test_template_service.py`

**Step 1: Write failing validation tests.**

Test malformed dates, whitespace-only exercise names, non-finite numeric values, negative kg/reps/RIR, duplicate or invalid template rows, and valid zero RIR.  Assert domain exceptions, not raw `ValueError` messages from lower layers.

**Step 2: Add small typed models.**

Use dataclasses (or Pydantic only if already desired for request models): `TrainingSetInput`, `TrainingSet`, `Session`, `TemplateInput`, `Template`.  Keep persistence row mapping inside repositories/services.

**Step 3: Create explicit domain exceptions.**

Define `ValidationError`, `NotFoundError` and `ConflictError` in `src/models.py` or `src/errors.py`.  Do not expose SQLite exception messages to the browser.

**Step 4: Convert validation and service signatures.**

Replace public `list[dict]` / `dict` service interfaces with typed inputs and outputs.  Preserve internal adapter functions temporarily where routes still submit form arrays.

**Step 5: Verify types and tests.**

```bash
uv run mypy app.py src tests
uv run pytest tests/test_training_service.py tests/test_template_service.py -v
```

**Step 6: Commit.**

```bash
git add src tests
git commit -m "refactor: type training and template domain boundaries"
```

### Task 4.2: Extract route orchestration from `app.py`

**Files:**
- Create: `src/dashboard_service.py`
- Create: `src/view_models.py`
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Step 1: Write route-level tests before extraction.**

Freeze status codes, response fragments and user messages for a successful save, validation failure, template application, deletion and undo.

**Step 2: Move direct database helpers.**

Move `get_filters`, `get_ejercicios_por_grupo`, `_fechas_con_datos` and date/session orchestration out of `app.py`.  Keep app functions limited to request parsing, service calls and HTTP/HTML response selection.

**Step 3: Create explicit view models.**

`SessionEditorViewModel` and `DateNavigatorViewModel` should expose only values templates need.  Template rendering must not perform database access or calculate domain state.

**Step 4: Standardize error translation.**

Add a single helper/middleware that maps known domain errors to safe 4xx responses and a generic message.  Log unexpected exceptions with context server-side; never use broad `except Exception` to silently return empty data.

**Step 5: Make sync/blocking work explicit.**

Because SQLite, pandas and Plotly calls are synchronous, make the affected FastAPI handlers regular `def` functions or use `run_in_threadpool`.  Do not leave blocking work inside `async def` handlers.

**Step 6: Run all contract tests and commit.**

```bash
uv run pytest tests/test_app.py tests/test_integration.py -v
uv run pytest -q
git add app.py src tests
git commit -m "refactor: isolate dashboard route orchestration"
```

# Phase 5 — Security and deployment posture

### Task 5.1: Establish a proportionate threat model and security headers

**Files:**
- Create: `docs/architecture/security-model.md`
- Create: `src/security.py`
- Modify: `app.py`
- Create: `tests/test_security.py`

**Step 1: Define deployment assumptions.**

Document whether the dashboard is localhost-only, LAN-only or internet-facing.  If it is not authenticated, its default safe deployment must be loopback-only; internet exposure requires an authentication and authorization design before release.

**Step 2: Write failing header tests.**

Assert `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` (or CSP `frame-ancestors 'none'`), and a restrictive Content Security Policy appropriate to the current external CDN usage.

**Step 3: Implement security middleware.**

Add headers centrally.  Start CSP in report-compatible/enforced form only after all legitimate Tailwind, htmx, Sortable and Plotly resources have explicit allowed sources.  Prefer pinned CDN URLs with Subresource Integrity where supported.

**Step 4: Verify output encoding boundaries.**

Review every `| safe`, `HTMLResponse` string construction and client-supplied template/exercise name.  Replace executable inline interpolation with the JSON-data pattern from Task 1.3.  Keep Jinja autoescape enabled.

**Step 5: Run tests and commit.**

```bash
uv run pytest tests/test_security.py tests/test_app.py -v
git add docs/architecture/security-model.md src/security.py app.py tests/test_security.py
git commit -m "feat: add dashboard security baseline"
```

### Task 5.2: Protect state-changing browser requests appropriately

**Files:**
- Modify: `src/security.py`
- Modify: `app.py`
- Modify: `templates/base.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_security.py`
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Write a failing CSRF/origin test.**

For each unsafe method, verify a cross-origin `Origin` is rejected and a same-origin browser request succeeds.  Use a route exemption only for explicitly documented machine-to-machine endpoints, if any.

**Step 2: Choose the minimal protection matching deployment.**

For same-origin browser use, implement signed CSRF tokens embedded in `#app-config` and sent by htmx requests, plus Origin validation as defence in depth.  If the documented deployment remains strictly localhost-only, record why this is adequate but retain Origin checks.

**Step 3: Implement token validation centrally.**

Use a secret configured by environment variable in non-development deployments.  Never log tokens.  Return a safe `403` fragment/message on rejection.

**Step 4: Prove htmx and normal forms still work.**

Use Playwright to save, delete and reorder templates after token injection.

**Step 5: Commit.**

```bash
uv run pytest tests/test_security.py tests/e2e/test_dashboard_flow.py -v
git add src/security.py app.py templates/base.html static/js/app.js tests
git commit -m "feat: protect dashboard mutations from cross-origin requests"
```

# Phase 6 — Enforce quality continuously

### Task 6.1: Add linting, formatting, typing and coverage gates

**Files:**
- Modify: `pyproject.toml`
- Create: `.github/workflows/ci.yml` (or the configured CI equivalent)
- Create: `tests/test_quality_contract.py` only if a repository-local guard is needed

**Step 1: Make formatting/linting fail locally.**

Run: `uv run ruff format --check .`

Run: `uv run ruff check .`

Fix violations rather than adding blanket ignores.  Each exception needs a narrow code and written rationale.

**Step 2: Introduce typing incrementally.**

Run: `uv run mypy app.py src tests`

Use strictness appropriate to current code; raise it in small commits.  Do not use global `ignore_missing_imports` or blanket `Any` to silence failures.

**Step 3: Add coverage measurement.**

Set an initial line coverage floor based on the current measured baseline, then increase it after the new critical tests.  Add branch coverage for `src/training_service.py`, `src/database.py`, `src/template_service.py` and security code.

**Step 4: Add CI jobs.**

Order jobs: locked sync → ruff format/check → mypy → unit/integration tests with coverage → Playwright browser tests.  Cache uv and Playwright downloads only; never cache the database under test.

**Step 5: Verify CI commands locally.**

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest -q --cov=src --cov=app
uv run pytest tests/e2e -v
```

**Step 6: Commit.**

```bash
git add pyproject.toml uv.lock .github tests
git commit -m "ci: enforce dashboard quality gates"
```

### Task 6.2: Perform a release-candidate verification and document operation

**Files:**
- Create: `docs/operations/local-development.md`
- Create: `docs/operations/release-checklist.md`
- Modify: `AGENTS.md` only if its route or workflow information is now incorrect
- Test: all suites

**Step 1: Document local setup and safe operation.**

Include `uv sync --locked`, database backup/recovery, migration behaviour, test commands, Playwright setup, environment variables and the safe loopback binding command.

**Step 2: Write a release checklist.**

Require clean worktree review, backup before pending migrations, locked dependency check, static analysis, full tests, browser tests, security-header tests and manual smoke test of save/undo/template/export.

**Step 3: Run the release candidate matrix.**

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest -q --cov=src --cov=app
uv run pytest tests/e2e -v
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

Expected: all automated checks pass; manually verify the dashboard in a browser against a copied development DB, then stop the server.

**Step 4: Commit.**

```bash
git add docs AGENTS.md
git commit -m "docs: add dashboard operational runbook"
```

## Recommended execution order and checkpoints

1. Complete Phase 0 and review the frozen UI contract before touching templates.
2. Complete Phase 1, then run the browser tests of Phase 2 before accepting the client refactor.
3. Complete Phase 3 before Phase 4; typed services must rely on a known, reliable persistence boundary.
4. Complete Phase 5 before any non-local deployment or sharing the dashboard on a network.
5. Phase 6 is the merge/release gate, not optional cleanup.

## Acceptance review checklist

- [ ] `templates/base.html` is a small layout shell and no longer contains component CSS or operational JavaScript.
- [ ] Static modules have one owner each and do not rely on accidental global ordering.
- [ ] All critical htmx flows pass in a real browser.
- [ ] SQLite connections consistently enable foreign keys and close/rollback correctly.
- [ ] Schema changes are versioned, backed up and tested from legacy states.
- [ ] Route handlers are small; domain validation, persistence and rendering inputs are separated.
- [ ] Security controls are tested and match the documented deployment exposure.
- [ ] The locked, linted, typed, tested project is reproducible from a clean checkout.
