# Release Checklist

Run every step before releasing or merging the `codex` branch. Any failure blocks
the release.

## 1. Repository state

- [ ] `git status` clean except intended files; no `.venv`, `data/*.db`,
      browser downloads or caches staged.
- [ ] `docs/architecture/current-ui-contract.md` reviewed: any DOM/htmx contract
      change since last release is intentional and has its own browser test.

## 2. Automated gates

```bash
npm ci
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest -q --ignore=tests/e2e        # coverage floor 90% enforced
uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py --min 90
uv run pytest tests/test_frontend_budget.py -q --no-cov
uv run pytest tests/e2e -q --no-cov --ignore=tests/e2e/test_accessibility.py
uv run pytest tests/e2e/test_accessibility.py -q --no-cov
./scripts/run_lighthouse.sh                # P/A/BP/SEO >= 90
```

- [ ] Generated assets up to date: `uv run python scripts/build_design_tokens.py --check && ./scripts/build_css.sh && git diff --exit-code -- static/css/tokens.css static/css/tailwind.css`
- [ ] All green on a clean checkout (CI `quality`, `unit`, `browser`, `lighthouse` jobs pass).

## 3. Database

- [ ] `data/backups/` contains a recent backup (or the DB is disposable/regenerable).
- [ ] No pending migrations on a production DB without a fresh backup (the runner
      creates one automatically, but verify it exists).
- [ ] Migration smoke test: `uv run python -c "from src.migrations.runner import run_migrations, current_version; import config; print(run_migrations(config.DB_PATH), current_version(config.DB_PATH))"`

## 4. Security

- [ ] `GYM_CSRF_SECRET` set in the deployment environment (non-localhost only).
- [ ] `uv run pytest tests/test_security.py -v` passes.
- [ ] Deployment stays loopback-only (`--host 127.0.0.1`) unless the auth design in
      `docs/architecture/security-model.md` is implemented.
- [ ] Smoke con la app levantada: `curl -i http://127.0.0.1:8000/healthz` → 200
      `{"status":"ok","db":"ok"}`; `curl -i http://127.0.0.1:8000/docs` → 404.
- [ ] Surface assertions: `rg -n 'get_sessions_page|get_training_sessions' src app.py` → 0.

## 4b. Android app (HealthSync) — si el release toca `android/`

```bash
cd android
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
export GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk
./gradlew test assembleDebug
```

- [ ] Suite Android en verde (debug + release).
- [ ] `assembleDebug` genera `app/build/outputs/apk/debug/app-debug.apk`.
- [ ] El APK debug embebe URL/token actuales de `data/hc_sync_token` (recompilar
      si el token del servidor cambió; el release NO lleva secreto).
- [ ] Smoke en dispositivo: "Permisos esenciales" → "Sincronizar AHORA" →
      `sqlite3 data/lifestyle.db "SELECT record_type, COUNT(*) FROM health_records WHERE deleted_at IS NULL GROUP BY record_type;"`.

## 5. Manual smoke test

With a copied development DB and `uv run uvicorn app:app --host 127.0.0.1 --port 8000`:

- [ ] Dashboard loads with charts and date navigator.
- [ ] Save a session (editor becomes read-only, dot appears on the date).
- [ ] Undo (Ctrl/Cmd+Z) restores the session.
- [ ] Create, apply, edit, reorder and delete a template (entreno).
- [ ] CSV export downloads.
- [ ] Date navigation with unsaved-change confirmation.

## 6. Security surface assertions

These commands must return zero matches; review any future match manually. The
second command is a security alarm, not an automatic proof of safety.

```bash
rg -n 'on(click|change|submit|input|keydown)=' templates -g '*.html'
rg -n 'innerHTML\s*=.*(message|nombre|ejercicio|error)' static app.py src -g '*.{js,py}'
```

- [ ] No inline event attributes remain in templates.
- [ ] No client module writes user fields into `innerHTML`.
- [ ] Hostile-payload regression tests pass:
      `uv run pytest tests/test_security.py -k 'hostile or oob or leak or nonce' -v`

## 7. Post-release

- [ ] Tag and/or merge with a conventional message.
- [ ] Update `docs/architecture/current-ui-contract.md` if the contract changed.
