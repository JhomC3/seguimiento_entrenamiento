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

The nutrition panel imports its own public spreadsheet (`diario` and `alimentos`
sheets) with an idempotent script that backs up first and only replaces rows with
`origen='google'`:

```bash
uv run python scripts/import_nutrition.py
```

Both scripts honor `GYM_DB_PATH` and abort without touching the DB on fetch/parse
errors.

## Verifying the editor UI contract

```bash
uv run python scripts/verify_editor.py
```

## Health Connect sync (HealthSync)

- **Android app** lives in `android/`. Everything Gradle runs from `android/`
  with the sandbox rule: `GRADLE_USER_HOME=$PWD/.gradle` and
  `ANDROID_HOME=$PWD/android/sdk` (SDK instalado dentro del proyecto, no se
  commitea). Build + tests:
  ```bash
  export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
  export GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk
  cd android && ./gradlew assembleDebug test
  ```
- **Backend endpoint**: `POST /sync/health-connect` (JSON, autenticado con
  `X-Sync-Token` = `HC_SYNC_TOKEN`). Sin el env configurado responde 503.
  Ejemplo local:
  ```bash
  HC_SYNC_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))") \
  GYM_DB_PATH=data/gym.db uv run uvicorn app:app --host 127.0.0.1 --port 8000
  ```
- **Export**: `GET /exportar/health-connect.csv` (activos; `?incluir_borrados=1`
  para auditoría de bajas).
- **Forzar el worker desde ADB** (sin esperar la hora):
  `adb shell cmd jobscheduler run -f com.jhomc.healthsync <job_id>`.
- **Migración a host persistente**: `docs/operations/health-sync-migration.md`.
