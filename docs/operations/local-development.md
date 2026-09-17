# Local Development

## Setup (one time)

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked        # creates .venv from the locked resolution (Python 3.11)
uv run playwright install chromium   # browser binaries for e2e tests (one time)
```

`uv sync --locked` fails if `uv.lock` is missing or stale — CI enforces the same.

## Run the dashboard

There is exactly one supported way to run the server for daily use
(dashboard on this Mac + mobile sync over the LAN):

```bash
./scripts/start_server.sh
```

It generates/persists `data/hc_sync_token` + `data/csrf_secret`, activates
the LAN sync-only gate and serves `0.0.0.0:8000`. Do not start uvicorn by
hand for daily use: without the script there is no sync token
(`POST /sync/health-connect` answers 503) and the phone cannot reach the
server. Direct `uvicorn` invocations exist only inside test/lighthouse
tooling (isolated ports/DBs), never as a second startup mode.

- The script activates the LAN sync-only gate: on the LAN
  the server serves **only** `POST /sync/health-connect` (HealthSync, autenticado
  con `X-Sync-Token`) **plus the training diary API v1** (entreno, nutrición,
  plantillas, altas y undo; mismo token; contrato en
  `docs/architecture/training-api-contract.md`); the dashboard UI, static assets,
  exports and htmx mutations
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
| `GYM_LAN_SYNC_ONLY` | `1` = LAN gate activo: remoto solo `POST /sync/health-connect` + API v1 del diario | desactivado |
| `GYM_SYNC_RATE_LIMIT_PER_MINUTE` | Rate limit del sync por peer remoto (429 + `Retry-After`) | 30 |
| `SHEET_ID` / `GIDS` | Google Sheets source (config.py) | project defaults |

## Database: backup and recovery

- Automatic backups: written to `data/backups/` (a) before every mutation
  (`/entrenamiento/session/save`, delete, `/undo`) and (b) before pending schema
  migrations on an existing DB.
- Restore:
  ```bash
  cp data/backups/lifestyle-YYYYMMDD-HHMMSS.db data/lifestyle.db
  ./scripts/start_server.sh
  ```
- Schema is versioned in `schema_migrations`; never hand-edit tables.
- Emergency server undo (no UI affordance by design): `HC_SYNC_TOKEN=$(cat data/hc_sync_token)`,
  then `curl -X POST -H "X-Sync-Token: $HC_SYNC_TOKEN" http://127.0.0.1:8000/api/v1/undo`
  (peek first with `GET /api/v1/undo/peek`). Pops one journal entry (max 10).

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

## Parallel work with git worktrees

Rule (binding, see `AGENTS.md` §0.5): **one task = one branch = one worktree.**
Never run two agents or two tasks in the same working directory.
Worktrees always live **inside** the project, under `.tmp/` (sandbox maxima
`AGENTS.md` §0: nothing outside the project tree — it prevails over any path
example). `.tmp/` is gitignored and excluded from the gates (`ruff`
`extend-exclude`, `pytest` `testpaths`, top-level globs in Tailwind/audits),
so sibling WIP never pollutes `git status`, lint, tests or CSS builds.

### Create

```bash
git status --short --branch   # must be clean first: commit or `git stash -u`
mkdir -p .tmp
git worktree add .tmp/entrenamiento-<tarea> -b <tipo>/<nombre> <base>
git worktree list             # verify (all paths must stay under $PWD/.tmp/)
```

- `<base>` is a stable commit or branch (e.g. `main`), never a half-done branch.
- Branch names follow repo style: `feat/...`, `fix/...`, `docs/...`.
- A new worktree starts from HEAD; uncommitted changes are NOT carried over.

### Isolate (per worktree)

`.venv/`, `data/*.db`, `data/backups/`, tokens (`data/hc_sync_token`,
`data/csrf_secret`), `android/.gradle` and `android/sdk/` are gitignored, so
each worktree sets up its own:

```bash
cd .tmp/entrenamiento-<tarea>
uv sync --locked                                   # own .venv
cp ../../data/lifestyle.db data/ 2>/dev/null || uv run python scripts/import_google_sheets.py
./scripts/start_server.sh                          # generates its own secrets
uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload   # own port, never 8000
```

Android (from that worktree's `android/`, sandbox paths are relative so they
resolve per worktree automatically):

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@21 GRADLE_USER_HOME=$PWD/.gradle ANDROID_HOME=$PWD/android/sdk ./gradlew assembleDebug test
```

Notes:

- e2e tests use an isolated server + temporary DB, so `pytest` is safe to run
  in several worktrees at once. Playwright browsers (`~/.cache/ms-playwright`)
  are shared machine-wide (one-time install).
- `android/sdk/` is per worktree and large (~GBs). If disk is tight, reusing
  another tree's SDK read-only is a conscious sandbox exception, not the default.
- Assign agents by directory and keep touched files disjoint where possible;
  worktrees don't remove merge conflicts, they only isolate work in progress.

### Integrate (constant git maintenance)

- Small commits per milestone, concise message in repo style.
- Before every commit: `git status`, `git diff`, `git log --oneline -10`;
  stage only intended files, never secrets. No automatic commits or pushes:
  branch and diff are always reviewed first.
- Sync with the base (rebase/merge) before integrating.

### Clean up

```bash
git worktree remove .tmp/entrenamiento-<tarea>   # after the merge (run from the main checkout)
git worktree prune
git branch -d <tipo>/<nombre>                  # delete branches already merged
```
