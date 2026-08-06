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
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run pytest -q --ignore=tests/e2e        # coverage floor 90% enforced
uv run pytest tests/e2e -q                  # browser tests
```

- [ ] All green on a clean checkout (CI `quality`, `unit`, `browser` jobs pass).

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

## 5. Manual smoke test

With a copied development DB and `uv run uvicorn app:app --host 127.0.0.1 --port 8000`:

- [ ] Dashboard loads with charts and date navigator.
- [ ] Save a session (editor becomes read-only, dot appears on the date).
- [ ] Undo (Ctrl/Cmd+Z) restores the session.
- [ ] Create, apply, edit, reorder and delete a template (entreno).
- [ ] CSV export downloads.
- [ ] Date navigation with unsaved-change confirmation.

## 6. Post-release

- [ ] Tag and/or merge with a conventional message.
- [ ] Update `docs/architecture/current-ui-contract.md` if the contract changed.
