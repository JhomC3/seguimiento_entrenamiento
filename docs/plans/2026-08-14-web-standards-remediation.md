# Web Standards Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve the confirmed web-standards failures of the 2026-08-14 forensic audit without abandoning FastAPI, Jinja2, htmx, or server-owned validation. Backend-only findings (observability, /docs, WAL, indexes, dead backend code, form limits, /healthz) are out of scope here and are covered by the companion plan `docs/plans/2026-08-14-backend-standards-remediation.md`, executed in coordination with this one.

**Architecture:** The process visible to the LAN exposes HealthSync only. The dashboard remains loopback-only. A canonical JSON token file supplies Tailwind, CSS variables, and Plotly. Accessibility relies on native semantic elements and small ES modules, never a client framework.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite migrations, htmx, Tailwind 3.4 static build, Plotly, pytest, Playwright, axe-core, Lighthouse CI.

---

## Baseline and decisions

- The forensic report is a static snapshot of commit 085659b. It remains materially correct.
- The baseline note from the original audit ("unrelated edits in app.py, src/charts.py, level-cascade.js...") is obsolete: those edits are integrated at HEAD 04d45ac. Pending worktree edits (session editor RIR steppers, AGENTS.md §5.5) were committed in Fase 0 (6ca934b, 70d9d44); execute directly on this tree.
- The backend plan reuses migration v014 for the `training_sets(fecha, set_orden)` index because this plan's Task 8 owns v013 (undo journal). "Task 8 is the only migration" means: the only migration in THIS plan.
- The legacy routes /select, /grupo/reset, and /ejercicio are still registered and tested, but unused by the current client.
- The date-strip size finding is valid. Its alleged refresh during cascade selection belongs only to the legacy flow; do not reintroduce it.

### Required decisions

1. **LAN is HealthSync-only.** CSRF does not authenticate users: a remote peer can load the app and read a valid token. Remote UI access must therefore be blocked, not merely protected by a new CSRF secret.
2. **No known CSRF fallback.** Loopback mode uses a cryptographically random process-local fallback. The supported LAN launcher persists a private secret and fails without it.
3. **Honest no-JS policy.** The server-rendered overview and export remain available without JS. Editing, popup, htmx navigation, undo, and charts require JS and a noscript notice says so. Update the standard instead of asserting functionality that does not exist.
4. **One token source.** static/design-tokens.json is the only hand-maintained palette. Generated output may contain literals; handwritten CSS/Python/templates may not duplicate them.
5. **Accessible density.** Primary controls are at least 44×44 px. Dense table controls are at least 24×24 px, spaced, and keyboard-accessible; document this precise exception.
6. **Undo persists.** Replace the in-memory deque with a SQLite journal retaining the newest ten actions.

| Audit area | Tasks |
|---|---|
| LAN/CSRF/rate limit/headers/CSV | 1–2 |
| Tokens, contrast, typography, loading | 3–4 |
| CWV: scripts, cache, navigator, CLS, favicon | 4–5 |
| A11y: status, dialog, labels, keyboard, motion | 6–7 |
| UX: silent errors, templates, durable undo | 7–8 |
| No-JS, dead routes, SEO | 9 |
| Docs, axe, Lighthouse, bundle budget | 10–11 |

## Task 1: Isolate dashboard access from LAN sync

**Files**

- Create: src/network_access.py
- Modify: src/security.py, app.py, scripts/start_server.sh, .gitignore
- Test: tests/test_security.py
- Docs: docs/architecture/security-model.md, docs/operations/local-development.md

**Step 1: Write the failing ASGI tests.**

Use raw ASGI scopes because TestClient peers are loopback by default.

~~~python
def test_lan_sync_only_blocks_remote_dashboard() -> None:
    result = run_asgi(app, client=("192.168.1.25", 50000), path="/")
    assert result.status == 403


def test_lan_sync_only_allows_only_sync_post() -> None:
    allowed = run_asgi(
        app, client=("192.168.1.25", 50000), path="/sync/health-connect", method="POST"
    )
    denied = run_asgi(app, client=("192.168.1.25", 50000), path="/exportar/csv")
    assert allowed.status != 403
    assert denied.status == 403
~~~

Add loopback and IPv6-loopback allowance, exact-route enforcement, and rate-limit tests. Requests beyond GYM_SYNC_RATE_LIMIT_PER_MINUTE must return 429 and Retry-After.

**Step 2: Implement typed ASGI middleware.**

LanSyncOnlyMiddleware is enabled only by GYM_LAN_SYNC_ONLY=1. It must:

- classify scope client addresses through ipaddress.ip_address(...).is_loopback;
- trust no X-Forwarded-For headers;
- allow remote traffic only for POST /sync/health-connect;
- reject remote dashboard, static, export, and non-sync mutation requests before parsing;
- use a bounded per-peer fixed-window/token-bucket limiter, defaulting to 30 requests/minute;
- return 403 or 429 without exposing HTML.

Register it outside CSRF middleware. Keep the existing exact CSRF exemption, because HealthSync continues to authenticate via X-Sync-Token.

**Step 3: Fix the official launcher.**

Set umask 077. Create data/csrf_secret using openssl rand -hex 48 when missing, require non-empty contents, export it as GYM_CSRF_SECRET, and set GYM_LAN_SYNC_ONLY=1. Do not print this secret. Add the file to .gitignore. Lifespan raises RuntimeError if LAN-sync mode lacks a secret.

**Step 4: Verify and commit.**

Run: uv run pytest tests/test_security.py -q  
Expected: remote UI denied; loopback UI and valid HealthSync accepted; throttle works.

~~~bash
git add src/network_access.py src/security.py app.py scripts/start_server.sh .gitignore tests/test_security.py docs
git commit -m "fix: isolate dashboard UI from LAN sync endpoint"
~~~

## Task 2: Remove the public CSRF fallback and complete low-cost hardening

**Files**

- Modify: src/security.py, app.py
- Test: tests/test_security.py, tests/test_app.py

**Step 1: Write failing tests.**

~~~python
def test_missing_csrf_env_uses_nonpublic_random_secret(monkeypatch) -> None:
    monkeypatch.delenv("GYM_CSRF_SECRET", raising=False)
    assert get_csrf_secret() != "dev-only-secret-do-not-use-in-production"
    assert len(get_csrf_secret()) >= 32
~~~

Assert Permissions-Policy and Cross-Origin-Opener-Policy: same-origin. Assert all three CSV downloads start with codecs.BOM_UTF8 while content type and filename remain unchanged.

**Step 2: Implement.**

Replace the development literal with one module-private secrets.token_urlsafe(48) value. Add Permissions-Policy for camera, microphone, geolocation, payment, and USB (all disabled) plus COOP. Prefix training, nutrition, and Health Connect CSV content with UTF-8 BOM only; do not alter data order or escaping.

**Step 3: Verify and commit.**

Run: uv run pytest tests/test_security.py tests/test_app.py -q

~~~bash
git add src/security.py app.py tests/test_security.py tests/test_app.py
git commit -m "fix: harden security defaults and CSV exports"
~~~

## Task 3: Establish one generated token pipeline

**Files**

- Create: static/design-tokens.json, scripts/build_design_tokens.py, static/css/tokens.css, src/design_tokens.py, tests/test_design_tokens.py
- Modify: tailwind.config.js, scripts/build_css.sh, static/css/app.css, templates/base.html, src/charts.py, tests/test_charts.py
- Delete: static/css/palette.css

**Step 1: Write failing token tests.**

Test required JSON schema, deterministic CSS generation, Plotly color lookup, no handwritten hexadecimal color in src/charts.py, no palette.css link, and no inline style block in index.html.

~~~python
def test_chart_colours_use_canonical_tokens() -> None:
    assert chart_color("primary") == color("burgundy.400")
    assert EXERCISE_PALETTE == palette("chart.exercise")


def test_tokens_css_is_generator_output() -> None:
    assert render_css(read_tokens()) == Path("static/css/tokens.css").read_text()
~~~

**Step 2: Implement source and consumers.**

JSON contains matte surfaces, burgundy scale, readable neutral tiers, focus, semantic notice colors, transparent chart background, and trace palette. The Python generator validates keys and creates custom properties. src/design_tokens.py reads the same JSON relative to the repository, validates it at import, and returns typed color/palette helpers without writing at runtime.

Tailwind imports JSON via require rather than repeating values. CSS imports tokens.css first and uses variables. charts.py gets axes, hover, text, background, and trace colors from helpers. Delete palette.css only after static Tailwind build proves all burgundy/matte utilities remain.

**Step 3: Verify and commit.**

Run: uv run python scripts/build_design_tokens.py --check && ./scripts/build_css.sh && uv run pytest tests/test_design_tokens.py tests/test_charts.py -q

~~~bash
git add static/design-tokens.json scripts/build_design_tokens.py static/css src/design_tokens.py tests tailwind.config.js scripts/build_css.sh templates/base.html src/charts.py
git rm static/css/palette.css
git commit -m "refactor: centralize visual tokens"
~~~

## Task 4: Repair contrast, type scale, loading, and critical render path

**Files**

- Create: static/css/cascade.css, static/favicon.svg
- Modify: CSS component files, templates/index.html, templates/base.html, dashboard_service.py, app.py, static/js/chart-interaction.js
- Test: tests/test_design_tokens.py, tests/test_app.py, tests/e2e/test_dashboard_flow.py

**Step 1: Write failing tests.**

Implement the WCAG luminance formula from the forensic annex. Every semantic text token must score at least 4.5:1 over matte-950 and neutral-900. Add source checks against audited text-neutral-500, text-neutral-600, and placeholder-neutral-600 in visible templates. Browser checks validate HOY, empty chart, and placeholder computed contrast.

**Step 2: Tokenize all page-local styles and text.**

Move htmx indicator, chart fade, level buttons/chips, and detail links out of index.html into cascade.css. Connect the indicator to actual htmx requests.

Replace all visible 8–11 px text with a readable 12 px component/token style: notices, badges, RIR marker, metadata, template controls, cardio labels, empty states, and navigator labels. Replace low-contrast text and placeholders with semantic readable neutral. HOY must be readable before hover.

**Step 3: Defer dependencies and lazy-load Plotly.**

- Add defer to the pinned/SRI htmx and Sortable scripts.
- Add only the required preconnects for unpkg, jsdelivr, and plotly CDNs.
- Remove eager Plotly. loadPlotly() appends exactly one pinned/SRI script after valid non-empty chart JSON appears, caches the promise, and reports failure through a safe notice.
- Give the chart shell final plot height; empty and loaded states occupy the same shell.
- Add favicon link.

**Step 4: Verify and commit.**

Run: uv run pytest tests/test_design_tokens.py tests/test_app.py tests/e2e/test_dashboard_flow.py -q --no-cov && ./scripts/build_css.sh

Browser network assertions: no Plotly request for empty chart; exactly one for populated chart; chart shell changes by at most 1 px.

~~~bash
git add static/css static/js/chart-interaction.js static/favicon.svg templates src/dashboard_service.py app.py tests
git commit -m "perf: improve critical rendering and readable visual states"
~~~

## Task 5: Bound date navigation and cache fingerprinted assets

**Files**

- Create: src/static_assets.py, tests/test_static_assets.py
- Modify: src/dashboard_service.py, src/view_models.py, templates/date_navigator.html, static/js/date-navigation.js, app.py, templates/base.html
- Test: tests/test_dashboard_service.py, tests/e2e/test_dashboard_flow.py

**Step 1: Write failing tests.**

~~~python
def test_navigator_has_a_bounded_selected_window() -> None:
    vm = build_date_navigator(DB, "2026-08-14", CYCLE_START, TODAY)
    assert len(vm.dates) <= 31
    assert any(day.selected for day in vm.dates)


def test_versioned_static_asset_is_immutable(client) -> None:
    response = client.get(static_url("css/app.css"))
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
~~~

Assert unversioned and stale-digest URLs are no-cache.

**Step 2: Implement.**

Render a selected-centered 31-day window constrained by cycle limits. Date input remains precise jump; arrows explicitly navigate date/window. Keep unsaved-change behavior and dots.

Create validated, memoized SHA-256 static_url(path) and register it as Jinja global. Use it for all rendered assets. Immutable cache is sent only when v equals current digest; direct/unversioned requests remain no-cache. This avoids asset copies and avoids stale deploys.

**Step 3: Verify and commit.**

Run: uv run pytest tests/test_dashboard_service.py tests/test_static_assets.py tests/test_security.py -q

~~~bash
git add src/static_assets.py src/dashboard_service.py src/view_models.py templates/date_navigator.html static/js/date-navigation.js app.py templates/base.html tests
git commit -m "perf: bound date navigation and fingerprint static assets"
~~~

## Task 6: Repair status announcements, labels, table semantics, headings, and dialogs

**Files**

- Create: static/js/modal-dialog.js
- Modify: partial notice/confirm templates; index, popup, session, nutrition, creation, and navigator templates
- Modify: static/js/notices.js, state.js, editor-popup.js, htmx-lifecycle.js, components.css
- Test: tests/test_app.py, tests/e2e/test_dashboard_flow.py

**Step 1: Write failing semantic tests.**

Require role=status, aria-live=polite, aria-atomic=true on global/editor regions and role=alert on errors. Use axe or accessibility snapshots to require an accessible name for every input/select, caption/scope on each data table, and h1 → h2 outline. Browser tests cover popup/confirmation initial focus, focus containment, Escape, and focus restoration, including confirmation inside popup.

**Step 2: Implement status and labels.**

Success notices inherit polite region; errors become alerts. Client-generated notices set equivalent roles using textContent. Table controls get labels such as Peso, serie 3. External fields get visible or visually-hidden labels. Convert title-only RIR/rest/date help to aria-describedby. Add table captions/scopes; move nutrition Objetivo and Consumido from thead to tfoot with scope=row. Chart heading becomes h2, popup title h2, panel titles h3.

**Step 3: Use native dialogs.**

Replace fixed custom overlays with native dialog elements. Popup is labelled by popup-fecha-title; confirmation uses labelledby plus describedby confirm-msg. modal-dialog.js owns showModal, close, origin focus, and nested dialog restoration. Preserve ?registro history without recursive popstate behavior. Do not build a parallel hand-rolled focus trap.

**Step 4: Verify and commit.**

Run: uv run pytest tests/test_app.py tests/e2e/test_dashboard_flow.py -q --no-cov

~~~bash
git add templates static/js static/css/components.css tests
git commit -m "fix: expose status forms and dialogs to assistive tech"
~~~

## Task 7: Make reordering, apply, shortcuts, focus, and motion accessible

**Files**

- Modify: session/nutrition/template/index templates
- Modify: editor, nutrition-editor, templates, nutrition-templates, row-sortable, date-navigation, lifecycle, notices JS
- Modify: theme, component, session-editor, template, navigator CSS
- Modify: app.py
- Test: browser dashboard/nutrition tests and test_app.py

**Step 1: Write failure and keyboard tests.**

Keyboard users must move session rows, nutrition rows, editable template rows, training cards, and nutrition cards up/down; persisted template order survives reload. Intercept reorder and first-training fetches: error notice appears and false local order is restored. Both template types require edit mode and confirm replacement. Arrow keys act only inside date navigator. Visible undo performs same action as Ctrl/Cmd+Z.

**Step 2: Implement explicit controls and truthful failures.**

Add Mover arriba/abajo buttons, disabled at boundaries. Pointer DnD remains enhancement. Shared reorder helper sends complete order using protected htmx, refreshes OOB list on success, restores original DOM and announces on error. Consolidate duplicated DnD state only after parity tests.

Replace nutrition apply anchor with a semantic button/data action. Shared policy: active edit mode, current date, confirmation if rows exist, one htmx request, OOB notice. firstTrainingOfWeek checks response.ok, announces network/parse failure, retries at most once for transient GET.

**Step 3: Implement sizing, focus, motion, and scoped shortcuts.**

Primary controls reach 44 px. Dense controls reach 24 px plus spacing; row actions show on focus-within. Provide visible :focus fallback and suppress it only inside supports(:focus-visible); never globally remove focus. Add reduced-motion CSS and make smooth scrolling conditional. Visible Deshacer última acción includes shortcut hint. Ctrl/Cmd+Z never captures text editing. Date arrows require navigator focus.

**Step 4: Verify and commit.**

Run: uv run pytest tests/test_app.py tests/e2e/test_dashboard_flow.py tests/e2e/test_nutrition_flow.py -q --no-cov

~~~bash
git add templates static/js static/css app.py tests
git commit -m "fix: make dashboard interactions keyboard accessible"
~~~

## Task 8: Persist undo in SQLite

**Files**

- Create: src/migrations/v013_persistent_undo.py
- Modify: migration runner, mutation_service.py, app.py
- Test: tests/test_mutation_service.py, tests/test_migrations.py, tests/test_app.py
- Docs: web-standards.md

**Step 1: Write failing tests.**

~~~python
def test_undo_survives_new_service_instance(db_path: str) -> None:
    save_session_with_undo_snapshot(db_path, fecha, rows)
    assert undo_last_action(db_path, fecha)["kind"] == "sesion"
~~~

No process-local state exists in the DB-journal design (the old in-memory deque is gone), so there is nothing to reset between instances; the same `db_path` fixture covers the "new service instance" case. Also test cap of ten, atomic pop/restore, failed mutation produces no entry, and migration runner backup behavior.

**Step 2: Implement.**

v013 creates undo_entries with ordered id, kind, JSON snapshot, timestamp, and newest index. Refactor mutation service so snapshot, write, journal insert, trim, undo pop, and restore use the existing transaction. Remove deque once all callers use DB. Persist only the server-owned `before`-side snapshot (fecha_iso, before, params_before when tracked): `undo_last_action` never reads the `after` snapshots (verified in src/mutation_service.py:162-192), so they are not stored.

**Step 3: Verify and commit.**

Run: uv run pytest tests/test_mutation_service.py tests/test_migrations.py tests/test_app.py -q

~~~bash
git add src/migrations src/mutation_service.py app.py tests docs/architecture/web-standards.md
git commit -m "fix: persist bounded undo history"
~~~

## Task 9: Remove dead routes and make fallback/SEO claims true

**Files**

- Modify: app.py, templates/base.html, templates/index.html, level-cascade.js, chart-interaction.js
- Modify: tests/test_app.py, e2e dashboard tests, web-standards.md

**Step 1: Write tests.**

Legacy URLs must return 404; /nivel and /grafica retain live behavior. Index response must contain noscript notice, initial muscle row, descriptive title, meta description, and favicon.

**Step 2: Implement.**

Render initial muscles server-side; level-cascade loads only if absent. Add concise noscript message and export link. Delete only /select, /grupo/reset, and /ejercicio plus stale comments/tests; never remove /ejercicio/nuevo. Add title Gym Tracker — Progreso de entrenamiento and concise description. Do not introduce public SEO features.

**Step 3: Verify and commit.**

Run: uv run pytest tests/test_app.py tests/e2e/test_dashboard_flow.py -q --no-cov

~~~bash
git add app.py templates static/js tests docs/architecture/web-standards.md
git commit -m "refactor: retire obsolete routes and clarify fallback"
~~~

## Task 10: Synchronize contracts and repository documentation

**Files**

- Rewrite: docs/architecture/current-ui-contract.md
- Modify: AGENTS.md, security-model.md, release-checklist.md, forensic report
- Move: db_explorer.ipynb to docs/notebooks/db_explorer.ipynb
- Create: docs/notebooks/README.md

**Steps**

1. Rewrite UI contract from live source. Cover /, /nivel, /grafica, /editor/popup, /cardio/annotation, active session/nutrition/template routes, undo, exports, and LAN sync. Remove legacy routes, obsolete test count, old non-popup UI, and stale module ownership.
2. Update AGENTS: migrations v001..v013, SQLite undo journal, real JS modules. Clarify Android collects 17 types while server accepts its documented 41-type ingestion allow-list; they are compatible scopes, not an asserted mirror.
3. Preserve forensic evidence. Add only a short status/link to this plan; do not edit its historical finding evidence.
4. Move notebook rather than deleting it and explain it is exploratory only.

Run: rg -n '/select|/grupo/reset|GET /ejercicio' AGENTS.md docs/architecture docs/operations -g '*.md'  
Expected: no active references outside archived plans.

~~~bash
git add AGENTS.md docs
git mv db_explorer.ipynb docs/notebooks/db_explorer.ipynb
git commit -m "docs: synchronize UI contracts and operations"
~~~

## Task 11: Add reproducible axe, Lighthouse, and budget gates

**Files**

- Create: package.json, package-lock.json, lighthouserc.cjs, scripts/run_lighthouse.sh, tests/e2e/test_accessibility.py, tests/test_frontend_budget.py
- Modify: .gitignore, scripts/build_css.sh, CI workflow, release checklist, nutrition e2e test

**Step 1: Lock tooling.**

Commit npm lockfile and local binaries for Tailwind 3.4.17, axe-core, Lighthouse CI. Ignore node_modules. Stop unbounded npx --yes in CI; build script checks tokens then runs local locked Tailwind. This is build tooling, not runtime dependency.

**Step 2: Add automated checks.**

Axe injects local axe.min.js and tests empty dashboard, populated chart, editor dialog, confirmation, nutrition, and templates. Explicit tests retain labels, status, table semantics, focus, and dialog coverage. No blanket suppression; each third-party false positive needs documented review.

Budget test enforces first-party CSS/JS individual+aggregate limits, fingerprint use, no eager Plotly, and no new synchronous external scripts. Set figures from post-remediation measurement as committed test constants.

**Step 3: Add deterministic Lighthouse runner.**

Run script uses .tmp/lighthouse inside repository, disposable DB, loopback Uvicorn, three locked Lighthouse samples, reports under .tmp, and trap cleanup. Config requires 90 in Performance, Accessibility, Best Practices, and SEO.

**Step 4: CI and flaky tests.**

CI sets up Node, runs npm ci, fails if generated assets differ, runs budget and axe checks, adds Lighthouse job/report artifact. Replace nutrition sleep/wait_for_timeout with selector/response state waits.

**Step 5: Verify and commit.**

~~~bash
npm ci
./scripts/build_css.sh
uv run pytest tests/test_frontend_budget.py -q
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
./scripts/run_lighthouse.sh
git add package.json package-lock.json lighthouserc.cjs scripts tests .github .gitignore docs
git commit -m "test: enforce web accessibility and performance budgets"
~~~

## Task 12: Final release verification

**Step 1: Regenerate deterministic artifacts.**

~~~bash
uv run python scripts/build_design_tokens.py --check
./scripts/build_css.sh
git diff --check
git diff --exit-code -- static/css/tokens.css static/css/tailwind.css
~~~

**Step 2: Run full quality gates.**

~~~bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest
uv run pytest tests/e2e -q --no-cov
./scripts/run_lighthouse.sh
~~~

**Step 3: Manual validation.**

At keyboard-only and 200% zoom validate popup/confirm dialogs, error/loading/success, session/nutrition/cardio, move controls, undo after restart, reduced motion, date navigation, empty/populated chart, and CSV exports. From a second LAN peer, validate dashboard/static/export denial and authenticated HealthSync success.

**Step 4: Commit only real final fixes.**

~~~bash
git add <files-that-fixed-a-real-verification-defect>
git commit -m "fix: resolve web standards verification findings"
~~~

## Order and non-goals

- Tasks 1–2 are P0 and precede all UI work.
- Tasks 3–5 establish visual/performance foundations.
- Tasks 6–7 are accessibility and interaction work.
- Task 8 is the only migration; verify backup before applying personal data.
- Tasks 9–11 settle the contract and make it continuously enforceable.
- Task 12 is mandatory.

No SPA, hydration, public authentication product, broad proxy trust, public SEO program, data/notebook deletion, or blanket axe/Lighthouse waiver is in scope.

