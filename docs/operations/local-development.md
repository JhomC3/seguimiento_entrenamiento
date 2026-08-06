# Local Development

## Setup (one time)

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked        # creates .venv from the locked resolution (Python 3.11)
uv run playwright install chromium   # browser binaries for e2e tests (one time)
```

`uv sync --locked` fails if `uv.lock` is missing or stale — CI enforces the same.

## Run the dashboard

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

- **Default binding is loopback-only** (`127.0.0.1`). Do not expose the dashboard
  on a network without the security review in
  `docs/architecture/security-model.md` (no authentication exists).
- The app initializes the DB on startup: creates the file if missing and applies
  pending migrations (`src/migrations/`). Before any pending migration runs on a
  pre-existing database, a timestamped backup is written to `data/backups/`.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GYM_DB_PATH` | SQLite database path | `data/gym.db` |
| `GYM_CSRF_SECRET` | HMAC secret for CSRF tokens. **Must be set outside localhost.** | dev-only fallback |
| `SHEET_ID` / `GIDS` | Google Sheets source (config.py) | project defaults |

## Database: backup and recovery

- Automatic backups: written to `data/backups/` (a) before every mutation
  (`/entrenamiento/session/save`, delete, `/undo`) and (b) before pending schema
  migrations on an existing DB.
- Restore:
  ```bash
  cp data/backups/gym-YYYYMMDD-HHMMSS.db data/gym.db
  uv run uvicorn app:app --host 127.0.0.1 --port 8000
  ```
- Schema is versioned in `schema_migrations`; never hand-edit tables.

## Tests

```bash
uv run pytest                    # full suite: unit + integration + browser (Playwright)
uv run pytest --ignore=tests/e2e # unit/integration only, with coverage floor (90%)
uv run pytest tests/e2e -q --no-cov  # browser tests only (coverage gate belongs to unit runs)
```

Coverage (branch, floor 90%) is enforced via `pyproject.toml` `addopts`.

## Static analysis gates (CI-enforced)

```bash
uv run ruff format --check .   # formatting
uv run ruff check .            # lint
uv run mypy app.py src tests   # types
```

## Import from Google Sheets

The dashboard reads its historical data from a Google Sheet. Run the import script
(not an HTTP route):

```bash
uv run python scripts/import_google_sheets.py
```

## Verifying the editor UI contract

```bash
uv run python scripts/verify_editor.py
```
