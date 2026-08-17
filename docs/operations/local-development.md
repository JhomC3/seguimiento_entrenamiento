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
- Binding `--host 0.0.0.0` is **only** sanctioned through
  `scripts/start_server.sh`, which activates the LAN sync-only gate: on the LAN
  the server serves **only** `POST /sync/health-connect` (HealthSync, autenticado
  con `X-Sync-Token`); the dashboard UI, static assets, exports and mutations
  return bare 403/429 to non-loopback peers. `GYM_LAN_SYNC_ONLY=1` requires
  `GYM_CSRF_SECRET` (persisted in `data/csrf_secret`) and vice versa: the app
  refuses to start with an inconsistent pair (manual `uvicorn --host 0.0.0.0`
  without the gate is an **accepted risk** — do not use it).
- The app initializes the DB on startup: creates the file if missing and applies
  pending migrations (`src/migrations/`). Before any pending migration runs on a
  pre-existing database, a timestamped backup is written to `data/backups/`.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LIFESTYLE_DB_PATH` | SQLite database path | `data/lifestyle.db` (`GYM_DB_PATH` es alias) |
| `GYM_CSRF_SECRET` | HMAC secret for CSRF tokens (persisted in `data/csrf_secret` by `start_server.sh`) | random per-process fallback (loopback only; tokens invalidan al reiniciar) |
| `GYM_LAN_SYNC_ONLY` | `1` = LAN gate activo: remoto solo `POST /sync/health-connect` | desactivado |
| `GYM_SYNC_RATE_LIMIT_PER_MINUTE` | Rate limit del sync por peer remoto (429 + `Retry-After`) | 30 |
| `SHEET_ID` / `GIDS` | Google Sheets source (config.py) | project defaults |

## Database: backup and recovery

- Automatic backups: written to `data/backups/` (a) before every mutation
  (`/entrenamiento/session/save`, delete, `/undo`) and (b) before pending schema
  migrations on an existing DB.
- Restore:
  ```bash
  cp data/backups/lifestyle-YYYYMMDD-HHMMSS.db data/lifestyle.db
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

Both scripts honor `LIFESTYLE_DB_PATH` (o el alias `GYM_DB_PATH`) and abort without touching the DB on fetch/parse
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
  export JAVA_HOME=/opt/homebrew/opt/openjdk@21
  export GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk
  cd android && ./gradlew assembleDebug test
  ```
- **Servidor**: el arranque recomendado es `scripts/start_server.sh` (genera el
  token persistente en `data/hc_sync_token` — gitignored — y arranca uvicorn en
  `0.0.0.0:8000`). Alternativa manual:
  ```bash
  HC_SYNC_TOKEN=$(cat data/hc_sync_token) uv run uvicorn app:app --host 0.0.0.0 --port 8000
  ```
  Sin token configurado, `POST /sync/health-connect` responde 503.
- **App sin configuración (desde 2026-08-12)**: la app NO tiene formulario de
  URL/token. El build **debug** embebe el destino en build-time
  (`BuildConfig.DEFAULT_SYNC_URL` / `DEFAULT_SYNC_TOKEN` en
  `android/app/build.gradle.kts`; el token se lee de `data/hc_sync_token`, la
  URL apunta por defecto a la IP LAN del Mac). El build **release** no lleva
  secreto (vacío). Para cambiar el destino: editar `build.gradle.kts` +
  `data/hc_sync_token`, recompilar e instalar (ver
  `docs/operations/health-sync-migration.md` §5).
- **Backend endpoint**: `POST /sync/health-connect` (JSON, autenticado con
  `X-Sync-Token` = `HC_SYNC_TOKEN`).
- **Export**: `GET /exportar/health-connect.csv` (activos; `?incluir_borrados=1`
  para auditoría de bajas).
- **Forzar el worker desde ADB** (sin esperar la hora):
  `adb shell cmd jobscheduler run -f com.jhomc.healthsync <job_id>`.
- **Migración a host persistente**: `docs/operations/health-sync-migration.md`.
