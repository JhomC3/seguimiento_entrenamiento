# Backend Standards Remediation — Plan de Implementación

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolver todos los hallazgos del informe `docs/analysis/2026-08-14-forensic-backend-standards.md` (observabilidad, inventario de API, operativa SQLite, hardening de input y drift documental) sin cambiar la arquitectura monolítica modular ni el contrato htmx/JSON existente.

**Architecture:** Se añade una capa ligera de observabilidad (config de logging + `request_id` vía contextvars + middleware + `/healthz`), se decide el inventario de API (docs de FastAPI deshabilitadas, código muerto eliminado), se endurece SQLite (WAL + backup online vía API del motor + índice en `training_sets(fecha, set_orden)` + `ON CONFLICT`) y se ponen límites a los inputs de formulario. Todo con TDD: test primero, implementación mínima, gates verdes y commit por tarea.

**Tech Stack:** Python 3.11, FastAPI (ASGI middleware), sqlite3 (WAL, backup API), pandas, pytest (TestClient/caplog/monkeypatch), ruff, mypy.

**Base:** commit `04d45ac` + working tree con cambios sin commitear del plan frontend (`docs/plans/2026-08-14-web-standards-remediation.md`).

---

## 0. Coordinación con el plan frontend (LEER ANTES DE EJECUTAR)

El plan `docs/plans/2026-08-14-web-standards-remediation.md` se está ejecutando en paralelo y **ya cubre parte de los hallazgos de este informe**:

| Hallazgo de este plan | Cobertura frontend | Acción aquí |
|---|---|---|
| P0: `GYM_CSRF_SECRET` en `start_server.sh` | Web Task 1–2 (`data/csrf_secret`, fallback eliminado, `GYM_LAN_SYNC_ONLY=1`) | **No duplicar.** Verificar antes de ejecutar; si no está aplicado, implementarlo igual que ese plan |
| P2: rate limiting `/sync/health-connect` | Web Task 1 (`GYM_SYNC_RATE_LIMIT_PER_MINUTE` → 429 + `Retry-After`) | **No duplicar.** Verificar; si no aplicado, hacerlo en `src/network_access.py` (mismo módulo) |
| Rutas legacy `/select`, `/grupo/reset`, `/ejercicio` | Web Task 9 (eliminación + tests) | **No tocar** esas rutas: las elimina el plan frontend. Este plan solo elimina el **código muerto de servicios/DB** |
| `AGENTS.md` / `current-ui-contract.md` (rutas) | Web Task 10 | Este plan actualiza **solo el drift backend** (migraciones, record types, `/healthz`, docs off) |
| CSV sin BOM (Task 13 de este plan) | Web Task 2 (BOM en los 3 exports, con tests) | **Omitida**: la implementa el plan frontend |

**Resolución de la colisión de migración v013:** el plan frontend Task 8 crea `v013_persistent_undo` (journal de undo). Este plan usa **v014** para el índice de `training_sets(fecha, set_orden)` (Task 7, renombrado `v014_training_fecha_index.py`, `VERSION = 14`).

**Reglas de ejecución:**
- No editar `src/security.py` ni `scripts/start_server.sh` (los posee el plan frontend).
- `app.py` se modifica en ambos planes: aplicar este plan **después** de integrar el frontend, o resolver conflictos manteniendo ambos cambios (los middlewares se componen; el `request_id` debe quedar **fuera** de todos los demás).
- Puertas por tarea: `uv run pytest` (módulo afectado), `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app.py src tests`.
- Cobertura: `--cov-fail-under=90` global — ninguna tarea debe bajarla.

---

## Task 1: Config de logging + `request_id` (módulo `src/logging_setup.py`)

**Files:**
- Create: `src/logging_setup.py`
- Modify: `app.py` (lifespan, ~línea 87-94)
- Test: `tests/test_logging_setup.py` (nuevo)

**Step 1: Write the failing tests**

```python
import logging

import pytest

from src.logging_setup import RequestIdFilter, setup_logging, request_id_var


def test_setup_logging_instala_handler_y_nivel():
    setup_logging(logging.INFO)
    root = logging.getLogger()
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert root.level <= logging.INFO


def test_setup_logging_idempotente():
    setup_logging(logging.INFO)
    before = len(logging.getLogger().handlers)
    setup_logging(logging.INFO)
    assert len(logging.getLogger().handlers) == before


def test_request_id_filter_inyecta_contexto(caplog):
    token = request_id_var.set("req-123")
    try:
        logger = logging.getLogger("dashboard")
        with caplog.at_level(logging.INFO, logger="dashboard"):
            logger.info("mensaje de prueba")
    finally:
        request_id_var.reset(token)
    assert "req-123" in caplog.text
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_logging_setup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.logging_setup'`

**Step 3: Write minimal implementation**

```python
"""Logging setup: root handler + request_id context propagation.

request_id_var is a contextvars.ContextVar set by the request_id middleware
(app.py) and injected into every log record via RequestIdFilter.
"""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_ROOT_HANDLER_KIND = logging.StreamHandler


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(h, _ROOT_HANDLER_KIND) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
```

**Step 4: Wire in `app.py` lifespan** (import + llamada antes de `init_db`):

```python
from src.logging_setup import setup_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    init_db(DB_PATH)
    ...
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_logging_setup.py -v && uv run pytest tests/test_app.py -q`
Expected: PASS (ambos)

**Step 6: Commit**

```bash
git add src/logging_setup.py app.py tests/test_logging_setup.py
git commit -m "feat: logging setup with root handler and request_id context"
```

---

## Task 2: Middleware `request_id` + log de peticiones

**Files:**
- Modify: `app.py` (middleware nuevo; registrar con `app.add_middleware` como **último** `add_middleware` para quedar más externo)
- Test: `tests/test_logging_setup.py` (extender)

**Step 1: Write the failing tests**

```python
def test_request_id_header_presente(client):
    resp = client.get("/")
    assert resp.headers.get("x-request-id")


def test_request_id_log_de_peticion(caplog):
    with caplog.at_level(logging.INFO, logger="access"):
        client.get("/fecha/editor?fecha=2026-08-14")
    assert any("GET /fecha/editor" in r.getMessage() for r in caplog.records)
```

(`client` = fixture TestClient existente de `tests/conftest.py` o `tests/test_app.py`; reutilizar el patrón de fixture del repo.)

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_logging_setup.py -v`
Expected: FAIL — no hay header `x-request-id` ni log de acceso

**Step 3: Write minimal implementation** (en `app.py`, junto a los otros middleware):

```python
import time
import uuid
from src.logging_setup import request_id_var


class RequestIdMiddleware:
    """Asigna request_id por petición, lo propaga a los logs y emite un
    access log propio (método, path, status, duración)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = dict(message.get("headers", []))
                headers[b"x-request-id"] = request_id.encode()
                message["headers"] = list(headers.items())
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logging.getLogger("access").info(
                "%s %s status=%s duration_ms=%.1f",
                scope["method"],
                scope.get("path", ""),
                status_holder["status"],
                duration_ms,
            )
            request_id_var.reset(token)


# Tras los add_middleware existentes (SecurityHeaders, CSRF) y ANTES de mount:
app.add_middleware(RequestIdMiddleware)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_logging_setup.py tests/test_security.py -v`
Expected: PASS (CSRF y headers siguen OK; el 403 del CSRF también lleva `x-request-id`)

**Step 5: Commit**

```bash
git add app.py tests/test_logging_setup.py
git commit -m "feat: request_id middleware with per-request access log"
```

---

## Task 3: Endpoint de salud `GET /healthz`

**Files:**
- Modify: `app.py` (nueva ruta)
- Test: `tests/test_app.py` (extender)

**Step 1: Write the failing tests**

```python
def test_healthz_ok(client, tmp_path, monkeypatch):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_healthz_db_caida_devuelve_503(monkeypatch):
    import src.db_connection as dbc

    def broken(_):
        raise OSError("db caída")

    monkeypatch.setattr(dbc, "connect_db", broken)
    resp = client.get("/healthz")
    assert resp.status_code == 503
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k healthz -v`
Expected: FAIL — 404

**Step 3: Write minimal implementation**

```python
@app.get("/healthz", response_class=JSONResponse)
def healthz():
    try:
        with read_connection(DB_PATH) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        logging.getLogger("dashboard").exception("healthz: la DB no responde")
        return JSONResponse({"status": "error", "db": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k healthz -v && uv run pytest tests/test_security.py -q`
Expected: PASS (GET no requiere CSRF; headers de seguridad aplican igual)

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: healthz liveness endpoint"
```

---

## Task 4: Deshabilitar `/docs`, `/redoc` y `/openapi.json`

Decisión (OWASP API9): la app no tiene consumidores externos de API; el contrato real es `current-ui-contract.md` + `health-sync-contract.md`. Se deshabilitan las tres rutas y se documenta.

**Files:**
- Modify: `app.py:97` (`FastAPI(title="Gym Tracker")` → `FastAPI(title="Gym Tracker", docs_url=None, redoc_url=None, openapi_url=None)`)
- Test: `tests/test_security.py` (extender)

**Step 1: Write the failing tests**

```python
def test_docs_y_openapi_deshabilitados(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_security.py -k docs -v`
Expected: FAIL — 200

**Step 3: Implement (la línea de `app = FastAPI(...)`)**

```python
app = FastAPI(
    title="Gym Tracker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_security.py tests/test_app.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_security.py
git commit -m "chore: disable FastAPI docs and OpenAPI inventory endpoints"
```

---

## Task 5: Eliminar código muerto de servicios y DB

Se eliminan las funciones sin callers en producción. **Se conservan** `load_ejercicios` y `load_training_data` porque los tests las usan como helpers de seed (test_charts, test_database, test_integration, test_coverage_edges) — se documentan como API de soporte de tests.

**Files:**
- Modify: `src/database.py` — borrar `get_training_sessions` (114-140) y `delete_session(semana, dia, fecha)` (168-174); añadir docstring a `load_ejercicios`/`load_training_data` indicando "test-support API"
- Modify: `src/training_service.py` — borrar `get_sessions_page` (209-213) y su import de `get_training_sessions` (línea 5)
- Modify: `tests/test_database.py` — borrar `test_get_training_sessions_ordena_por_fecha_iso` (631+)
- Modify: `tests/test_training_service.py` — borrar `test_get_sessions_page` (248+) y `test_delete_session` (298+); quitar imports muertos

**Step 1: Write the failing test (guarda que no queden callers)**

```bash
rg -n "get_sessions_page|get_training_sessions|delete_session\(" app.py src/ scripts/ -g '*.py' | grep -v "def \|_by_fecha\|with_undo_snapshot"
```

Run: `uv run pytest tests/test_database.py tests/test_training_service.py tests/test_integration.py tests/test_charts.py tests/test_coverage_edges.py -q`
Expected: primero COMPROBAR que pasan antes del cambio (baseline verde)

**Step 2: Apply the deletions** (según líneas arriba; eliminar también los tests que ejercitan las funciones borradas y sus imports)

**Step 3: Verify**

Run: `rg -n "get_sessions_page|get_training_sessions" src/ app.py` → **0 resultados**
Run: `uv run pytest tests/test_database.py tests/test_training_service.py tests/test_integration.py tests/test_charts.py tests/test_coverage_edges.py -q`
Expected: PASS

**Step 4: Commit**

```bash
git add src/database.py src/training_service.py tests/
git commit -m "refactor: remove dead backend code (legacy sessions helpers)"
```

---

## Task 6: WAL + backup online (API del motor)

**Cuidado (acoplamiento):** con WAL activo, `shutil.copy2` del archivo `.db` puede copiar sin los frames sin checkpointear → backup inconsistente. Se convierte `backup_db` y el backup del runner a la **API de backup online de SQLite** (`source.backup(dest)`).

**Files:**
- Modify: `src/db_connection.py:10-15` (WAL)
- Create: `src/backup_utils.py` — añadir `copy_db(source_path, dest_path)` con API backup
- Modify: `src/database.py:17-27` (`backup_db` usa `copy_db`)
- Modify: `src/migrations/runner.py:59-70` (backup pre-upgrade usa `copy_db`)
- Test: `tests/test_db_connection.py`, `tests/test_database.py:217` (ajustar/extender)

**Step 1: Write the failing tests**

```python
def test_connect_activa_wal(tmp_path):
    db = tmp_path / "wal.db"
    conn = connect_db(str(db))
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    finally:
        conn.close()
    assert row[0] == "wal"


def test_backup_db_via_api_conserva_datos(tmp_path):
    db = tmp_path / "orig.db"
    conn = connect_db(str(db))
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    dest = backup_db(str(db), keep=1)
    check = connect_db(dest)
    try:
        assert check.execute("SELECT v FROM t").fetchone()[0] == 42
    finally:
        check.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db_connection.py tests/test_database.py -k "wal or backup" -v`
Expected: FAIL — `journal_mode` devuelve el default y `backup_db` falla o no existe la nueva semántica

**Step 3: Write minimal implementation**

`src/backup_utils.py` (añadir):

```python
import sqlite3


def copy_db(source_path: str, dest_path: str) -> None:
    """Copia consistente de una base SQLite usando la API de backup online
    (incluye frames WAL sin checkpointear)."""
    source = sqlite3.connect(source_path)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
```

`src/db_connection.py` (en `connect_db`, tras `busy_timeout`):

```python
    conn.execute("PRAGMA journal_mode = WAL")
```

`src/database.py` (`backup_db`): sustituir `shutil.copy2(db_path, dest)` por:

```python
from src.backup_utils import copy_db, prune_backups

...
copy_db(db_path, dest)
```

`src/migrations/runner.py` (`_backup_before_upgrade`): sustituir `shutil.copy2(db_path, dest)` por `copy_db(db_path, dest)` (import del mismo helper).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_connection.py tests/test_database.py tests/test_mutation_service.py tests/test_integration.py -q`
Expected: PASS (incluye el backup pre-mutación y el runner con DBs con datos)

**Step 5: Commit**

```bash
git add src/backup_utils.py src/db_connection.py src/database.py src/migrations/runner.py tests/
git commit -m "feat: SQLite WAL mode and engine-level online backups"
```

---

## Task 7: Migración v014 — índice `training_sets(fecha, set_orden)`

**Files:**
- Create: `src/migrations/v014_training_fecha_index.py`
- Modify: `src/migrations/runner.py` (registrar `v014_...`)
- Test: `tests/test_db_connection.py` o `tests/test_database.py` (extender)

**Step 1: Write the failing tests**

```python
def test_v014_index_training_fecha(tmp_path):
    db_path = str(tmp_path / "mig.db")
    init_db(db_path)
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_training_fecha_set_orden",),
        ).fetchall()
    assert len(rows) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db_connection.py -k v014 -v`
Expected: FAIL — índice ausente

**Step 3: Write minimal implementation**

```python
"""v014 — índice para lectura/escritura de sesión por fecha."""

VERSION = 14
NAME = "training_fecha_index"


def migrate(conn) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_fecha_set_orden ON training_sets(fecha, set_orden)"
    )
```

`src/migrations/runner.py`: importar `v014_training_fecha_index` y añadirlo a `MIGRATIONS` (v14, por encima del v013 del journal de undo del plan frontend).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_connection.py -k v014 -v && uv run pytest tests/ -q --ignore=tests/e2e`
Expected: PASS (todo unit/integration; el runner aplica v014 sobre DBs existentes)

**Step 5: Commit**

```bash
git add src/migrations/v014_training_fecha_index.py src/migrations/runner.py tests/
git commit -m "feat: v014 index on training_sets(fecha, set_orden)"
```

---

## Task 8: Backup previo + fábrica de conexión en `import_google_sheets.py`

**Files:**
- Modify: `scripts/import_google_sheets.py`
- Test: `tests/test_import_training.py` (nuevo; patrón de `tests/test_import_nutrition.py`)

**Step 1: Write the failing tests**

```python
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_google_sheets.py"


@pytest.fixture
def training_module():
    spec = importlib.util.spec_from_file_location("import_google_sheets", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_google_sheets"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_import_reemplaza_google_y_hace_backup(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    df_ej = pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press"}])
    df_ciclo = pd.DataFrame(
        [
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "2026-08-10",
                "set_orden": 1,
                "ejercicio": "Press",
                "reps": 10,
                "kg": 80.0,
                "rir": 2,
            },
        ]
    )
    training_module.import_training_tables(db_path, df_ej, df_ciclo)
    backup_dir = Path(db_path).parent / "backups"
    assert list(backup_dir.glob("lifestyle-*.db"))
    with read_connection(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    assert n == 1


def test_import_idempotente(tmp_path, training_module):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    df_ej = pd.DataFrame([{"grupo_muscular": "Pectoral", "ejercicio": "Press"}])
    df_ciclo = pd.DataFrame(
        [
            {
                "semana": 1,
                "dia": "LUNES",
                "fecha": "2026-08-10",
                "set_orden": 1,
                "ejercicio": "Press",
                "reps": 10,
                "kg": 80.0,
                "rir": 2,
            },
        ]
    )
    training_module.import_training_tables(db_path, df_ej, df_ciclo)
    training_module.import_training_tables(db_path, df_ej, df_ciclo)
    with read_connection(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    assert n == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_import_training.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'import_training_tables'`

**Step 3: Write minimal implementation** (refactor del script: extraer la lógica de tablas, usar `connect_db` y backup)

```python
from src.db_connection import connect_db
from src.database import backup_db, init_db


def import_training_tables(
    db_path: str, df_ejercicios: pd.DataFrame, df_ciclo: pd.DataFrame
) -> dict:
    """Reemplazo atómico de las filas origen='google' con backup previo."""
    if df_ejercicios.empty or df_ciclo.empty:
        raise ValueError("no se descargaron datos válidos")
    backup_db(db_path)
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM training_sets WHERE origen = 'google'")
            conn.executemany(
                "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
                [(r.grupo_muscular, r.ejercicio) for r in df_ejercicios.itertuples()],
            )
            conn.executemany(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [
                    (r.semana, r.dia, r.fecha, r.set_orden, r.ejercicio, r.reps, r.kg, r.rir)
                    for r in df_ciclo.itertuples()
                ],
            )
    finally:
        conn.close()
    with read_connection(db_path) as conn:
        return {
            "total": conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0],
            "ejercicios": conn.execute("SELECT COUNT(*) FROM ejercicios").fetchone()[0],
        }
```

`main()` queda: fetch → `parse_*` → `init_db` → `import_training_tables(DB_PATH, df_ejercicios, df_ciclo)` → print.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_import_training.py -v && uv run pytest tests/test_import_nutrition.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/import_google_sheets.py tests/test_import_training.py
git commit -m "feat: backup before training import and shared connection factory"
```

---

## Task 9: `ON CONFLICT` en `save_parametros_diarios` e import de nutrición

**Files:**
- Modify: `src/database.py:496-510` (`save_parametros_diarios`)
- Modify: `scripts/import_nutrition.py:126-143` (INSERT OR REPLACE → UPSERT)
- Test: `tests/test_database.py` (extender)

**Step 1: Write the failing tests**

```python
def test_save_parametros_preserva_rowid(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    save_parametros_diarios(db_path, "2026-08-14", {"peso_kg": 80.0})
    with read_connection(db_path) as conn:
        rowid_1 = conn.execute(
            "SELECT rowid FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
    save_parametros_diarios(db_path, "2026-08-14", {"kcal_objetivo": 2400.0})
    with read_connection(db_path) as conn:
        rowid_2 = conn.execute(
            "SELECT rowid FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
        peso = conn.execute(
            "SELECT peso_kg FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
    assert rowid_1 == rowid_2
    assert peso == 80.0  # campo no enviado se conserva
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_database.py -k parametros -v`
Expected: FAIL — el rowid cambia (INSERT OR REPLACE)

**Step 3: Write minimal implementation**

```python
def save_parametros_diarios(db_path: str, fecha: str, params: dict) -> None:
    """UPSERT de los parámetros del día; solo se actualizan los campos presentes."""
    current = get_parametros_diarios(db_path, fecha) or {}
    merged = {**current, **params}
    with transaction(db_path) as conn:
        conn.execute(
            """INSERT INTO parametros_diarios (fecha, peso_kg, factor_proteina,
                   factor_grasa, kcal_objetivo, fibra_objetivo, hierro_objetivo,
                   calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fecha) DO UPDATE SET
                   peso_kg = excluded.peso_kg,
                   factor_proteina = excluded.factor_proteina,
                   factor_grasa = excluded.factor_grasa,
                   kcal_objetivo = excluded.kcal_objetivo,
                   fibra_objetivo = excluded.fibra_objetivo,
                   hierro_objetivo = excluded.hierro_objetivo,
                   calcio_objetivo = excluded.calcio_objetivo,
                   vitamina_c_objetivo = excluded.vitamina_c_objetivo,
                   vitamina_a_objetivo = excluded.vitamina_a_objetivo""",
            (fecha, *[float(merged.get(col, 0.0)) for col in _PARAMETROS_COLUMNS]),
        )
```

`scripts/import_nutrition.py`: mismo patrón `INSERT ... ON CONFLICT(fecha) DO UPDATE` con `VALUES (?, 70, 1.5, 1.1, ?...)`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_database.py -k parametros -v && uv run pytest tests/test_import_nutrition.py tests/test_nutrition_service.py tests/test_nutrition_dashboard.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/database.py scripts/import_nutrition.py tests/test_database.py
git commit -m "feat: upsert parametros_diarios with ON CONFLICT (stable rowid)"
```

---

## Task 10: Eliminar el N+1 de plantillas (1+N → 1)

**Files:**
- Modify: `src/database.py` — `get_plantillas` (187-203) y `get_plantillas_alimentacion` (523-541)
- Test: `tests/test_database.py` (extender con conteo de queries)

**Step 1: Write the failing test (baseline: 1 + N consultas)**

```python
class CountingConnection:
    def __init__(self, conn):
        self._conn = conn
        self.executions = 0

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, *args, **kwargs):
        self.executions += 1
        return self._conn.execute(*args, **kwargs)


def test_get_plantillas_una_sola_consulta(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_plantilla(db_path, "A", "EMPUJE", ["Press", "Press Militar"])
    insert_plantilla(db_path, "B", "JALON", ["Remo"])
    with read_connection(db_path) as conn:
        counting = CountingConnection(conn)
        get_plantillas_conn(counting)  # versión inyectable o uso de contador por monkeypatch
    assert counting.executions <= 2
```

> Nota de implementación: si prefieres no introducir una variante con `conn` inyectable, el test puede contar con un wrapper sobre `read_connection` vía `monkeypatch` de `src.database.read_connection`; el criterio es **≤ 2 ejecuciones** (1 plantillas + 1 sets) para 2 plantillas.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_database.py -k una_sola_consulta -v`
Expected: FAIL — 1 + N ejecuciones (N=2 → 3+)

**Step 3: Write minimal implementation**

```python
def get_plantillas(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, nombre, clasificacion, updated_at FROM plantillas ORDER BY orden, nombre"
        ).fetchall()
        sets_rows = conn.execute(
            "SELECT plantilla_id, set_orden, ejercicio FROM plantilla_sets ORDER BY plantilla_id, set_orden"
        ).fetchall()
    by_id: dict[int, dict] = {}
    for r in rows:
        by_id[r[0]] = {
            "id": r[0],
            "nombre": r[1],
            "clasificacion": r[2],
            "updated_at": r[3],
            "ejercicios": [],
        }
    for pid, _ord, ej in sets_rows:
        if pid in by_id:
            by_id[pid]["ejercicios"].append(ej)
    return list(by_id.values())
```

Mismo patrón para `get_plantillas_alimentacion` (1 query de plantillas + 1 de `plantilla_alimentos`).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_database.py -k plantilla -v && uv run pytest tests/test_app.py tests/test_nutrition_dashboard.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "perf: single-query plantilla lists (remove 1+N)"
```

---

## Task 11: Helper de resecuenciación en `restore_entrenos`

**Files:**
- Modify: `src/database.py:292-309` (`restore_entrenos`)
- Test: `tests/test_database.py` (extender)

**Step 1: Write the failing tests**

```python
def test_restore_entrenos_resecuencia_ids(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_plantilla(db_path, "A", "EMPUJE", ["Press"])
    snapshot = snapshot_entrenos(db_path)
    delete_plantilla(db_path, pid)
    restore_entrenos(db_path, snapshot)
    pid2 = insert_plantilla(db_path, "B", "JALON", ["Remo"])
    assert pid2 > pid
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_database.py -k resecuenci -v`
Expected: FAIL o PASS según el estado (si pasa, el test queda como guarda de regresión; la refactorización no cambia comportamiento)

**Step 3: Write minimal implementation** (extraer el bloque inline a helper privado, mismo comportamiento):

```python
def _resync_sequence(conn, table: str) -> None:
    row = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
    conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (row[0], table))
```

> `table` proviene únicamente de constantes del módulo (`"plantillas"`), nunca de input; el f-string es seguro.

Sustituir en `restore_entrenos` las líneas 308-309 por `_resync_sequence(conn, "plantillas")`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_database.py tests/test_mutation_service.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "refactor: extract sqlite_sequence resync helper in restore_entrenos"
```

---

## Task 12: Límites en formularios (arrays y longitudes)

**Files:**
- Modify: `app.py` — handlers `entrenamiento_session_save`, `alimentacion_save`, `plantilla_reordenar`, `plantilla_alimentacion_reordenar`, `plantilla_guardar/editar`
- Test: `tests/test_app.py` (extender)

**Step 1: Write the failing tests**

```python
def test_session_save_lote_excesivo_devuelve_400(client, csrf_headers):
    ejercicios = ["Press"] * 150
    resp = client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2026-08-14",
            "ejercicio": ejercicios,
            "kg": ["80"] * 150,
            "reps": ["10"] * 150,
            "rir": ["2"] * 150,
        },
        headers=csrf_headers,
    )
    assert resp.status_code == 400


def test_alimentacion_save_lote_excesivo_devuelve_400(client, csrf_headers):
    resp = client.post(
        "/alimentacion/save",
        data={"fecha": "2026-08-14", "alimento": ["Pollo"] * 150, "cantidad": ["150"] * 150},
        headers=csrf_headers,
    )
    assert resp.status_code == 400
```

(Reutilizar las fixtures `client`/`csrf_headers` existentes de `tests/test_app.py` o `conftest`.)

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k lote_excesivo -v`
Expected: FAIL — 200 (se guarda sin límite)

**Step 3: Write minimal implementation** (constantes + chequeo al inicio de cada handler mutante de listas)

```python
MAX_FORM_SETS = 100  # series por sesión
MAX_DIARY_ROWS = 100  # filas del diario
MAX_REORDER_IDS = 500  # ids de reordenamiento
MAX_NAME_LEN = 200  # nombres (ejercicio, alimento, plantilla)


def _check_lote(rows: list, max_rows: int, campo: str) -> None:
    if len(rows) > max_rows:
        raise ValidationError(f"Demasiadas filas de {campo} (máx. {max_rows}).")
```

En `entrenamiento_session_save` (antes de `sets_from_form`): `_check_lote(ejercicio, MAX_FORM_SETS, "series")`; en `alimentacion_save`: `_check_lote(alimento, MAX_DIARY_ROWS, "alimentos")`; en los reordenamientos: `_check_lote(id, MAX_REORDER_IDS, "orden")`. Además `Form(max_length=MAX_NAME_LEN)` en `nombre`, `ejercicio`, `alimento`, `categoria` de los handlers que los reciben como `str`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k "lote_excesivo or session_save or alimentacion" -v && uv run pytest tests/test_security.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: form batch and field length limits"
```

---

## Task 13: CSV exports con BOM UTF-8 (OMITIDA)

**Omitida por coordinación:** la implementa el plan frontend (Web Task 2, que además testea los tres exports con BOM). No duplicar en `app.py`.

**Files:**
- Modify: `app.py` — `export_csv` (~900-909), `export_nutrition_csv` (~710-724), `export_health_connect_csv` (~1217-1238)
- Test: `tests/test_app.py` (extender)

**Step 1: Write the failing tests**

```python
def test_export_csv_con_bom(client):
    resp = client.get("/exportar/csv")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k export_csv_con_bom -v`
Expected: FAIL — no empieza con BOM

**Step 3: Write minimal implementation**

```python
    csv = df.to_csv(index=False, encoding="utf-8-sig")
```

(aplicado a los tres exports; el resto del handler no cambia.)

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k export -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "fix: UTF-8 BOM on CSV exports for Excel compatibility"
```

---

## Task 14: Sincronizar documentación (drift backend)

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/architecture/current-ui-contract.md` (solo añadir `/healthz` si el plan frontend no lo hizo)
- Modify: `docs/architecture/backend-standards.md`
- Modify: `docs/architecture/security-model.md`
- Modify: `docs/operations/release-checklist.md`

**Step 1: Apply the edits**

1. `AGENTS.md` §4: "migraciones versionadas (`v001`..`v003`)" → "(`v001`..`v014`)". Corregir el drift de record types: "catálogo canónico ESENCIAL de 17 tipos" → "catálogo Android de 17 tipos núcleo; la allow-list del servidor (`health_sync_service.py`) es un superset de 41".
2. `AGENTS.md` §5: verificar tras el Task 9 del plan frontend; añadir `GET /healthz` → liveness; reflejar que `/docs`, `/redoc`, `/openapi.json` están deshabilitados.
3. `backend-standards.md`: §3 (OpenAPI: "rutas de documentación deshabilitadas por decisión; el contrato vive en `current-ui-contract.md`"), §7 (request_id implementado vía middleware + `/healthz` existente), §4 (nota del límite operativo de `pandas.read_sql_query` ya presente — verificar), §11 checklist (marcar ítems ya implementados si corresponde).
4. `security-model.md`: añadir al inventario que las rutas de documentación están deshabilitadas y que el rate limit del sync se controla con `GYM_SYNC_RATE_LIMIT_PER_MINUTE` (si el plan frontend lo implementa).
5. `release-checklist.md`: añadir a §5 manual smoke: `curl -i http://127.0.0.1:8000/healthz` → 200; `curl -i http://127.0.0.1:8000/docs` → 404; y a §6 surface assertions: `rg -n 'get_sessions_page|get_training_sessions' src app.py` → 0.

**Step 2: Verify no queda drift**

Run:
```bash
rg -n "v001..v003|v001\.\.v003" AGENTS.md
rg -n "get_sessions_page|get_training_sessions" src/ app.py
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/healthz   # con la app levantada: 200
```
Expected: sin coincidencias; healthz 200.

**Step 3: Commit**

```bash
git add AGENTS.md docs/
git commit -m "docs: sync backend drift (migrations, record types, healthz, docs inventory)"
```

---

## Task 15: Verificación final completa

**Step 1: Run all gates**

```bash
uv run pytest                      # unidad + integración + e2e, cobertura >= 90%
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run python scripts/check_module_coverage.py src/charts.py src/metrics_engine.py --min 90
```

Expected: todo en verde.

**Step 2: Smoke manual (app local)**

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8000
# 1. GET /healthz -> 200 {"status":"ok","db":"ok"}
# 2. GET /docs -> 404
# 3. Abrir / y guardar una sesión: notice de éxito (logging con [request_id])
# 4. Re-importar entrenamiento: scripts/import_google_sheets.py (backup en data/backups/)
```

**Step 3: Update the forensic report**

Añadir al final de `docs/analysis/2026-08-14-forensic-backend-standards.md` una sección "Estado tras remediación" con la tabla de hallazgos resueltos/pendientes (P0 CSRF y rutas legacy → plan frontend).

**Step 4: Commit**

```bash
git add docs/analysis/2026-08-14-forensic-backend-standards.md
git commit -m "docs: mark backend remediation status in forensic report"
```

---

## Resumen de hallazgos → tareas

| Hallazgo (forense) | Tarea |
|---|---|
| 3.1 Alto: CSRF dev + 0.0.0.0 | Plan frontend Tasks 1–2 (verificar) |
| 3.1 Medio: rate limiting sync | Plan frontend Task 1 (verificar) |
| 3.1 Medio: form parsing sin límites | Task 12 |
| 3.2 Alto: sin request_id / telemetría | Tasks 1–2 |
| 3.2 Alto: sin config de logging | Task 1 |
| 3.2 Medio: sin /healthz | Task 3 |
| 3.2 Medio: sin métricas | Tasks 2 (access log con duración) |
| 3.3 Alto: /docs·/redoc·/openapi.json | Task 4 |
| 3.3 Medio: código muerto backend | Task 5 (rutas legacy → plan frontend Task 9) |
| 3.4 Medio: SQLite sin WAL | Task 6 (incluye backup online) |
| 3.4 Medio: índices incompletos | Task 7 |
| 3.4 Medio: import sin backup | Task 8 |
| 3.4 Bajo: INSERT OR REPLACE | Task 9 |
| 3.4 Bajo: sqlite_sequence manual | Task 11 |
| 3.4 Bajo: backup por copy2 | Task 6 |
| 3.4 Bajo: N+1 plantillas | Task 10 |
| 3.4 Bajo: pandas en memoria | Task 14 (documentar) |
| 3.5 Medio: undo en memoria | Documentado en estándar §1/§8; sin código (UI → plan frontend) |
| 3.5 Bajo: constantes hardcodeadas | Task 14 (decisión documentada) |
| 3.5 Bajo: scripts sin fábrica de conexión | Task 8 |
| 3.7 Medio: drift AGENTS.md/contracts | Task 14 |
| 3.7 Bajo: CSV sin BOM | Task 13 |
