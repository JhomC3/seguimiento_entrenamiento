# Dashboard Forensic Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remediación forense del dashboard: normalizar las fechas de sesión a ISO (elimina la clase de bugs de ordenamiento), centralizar la fórmula RMₐ, retener backups, eliminar código muerto, añadir historial de sesiones y endurecer seguridad/UX (Tailwind estático, CSRF configurable, focus-visible, navegación por teclado) sin cambiar la identidad visual ni el contrato htmx existente.

**Architecture:** Migración SQLite v004 que convierte `training_sets.fecha` de TEXT `d/m/yy` a `YYYY-MM-DD`, haciendo que `ORDER BY fecha` sea cronológico en SQL y permitiendo eliminar los parseos en Python. La fórmula `kg*(1+0.0333*(reps+1+rir))` vive solo en `metrics_engine` (constante `RM_FACTOR` + helper `rm_ajustado`). Backup con retención (30) vía `src/backup_utils.py` compartido por app y runner de migraciones. Nuevo caso de uso `exercise_service` y sección "Últimas Sesiones" que reutiliza `get_training_sessions`. Tailwind compilado estáticamente (fuera del CDN runtime) para reducir la superficie CSP.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, SQLite (migraciones versionadas), pandas, Plotly, Tailwind 3.4 (build estático con npx), pytest/Playwright, ruff, mypy, uv.

---

## Scope, non-goals, and success criteria

### In scope

- Migración v004 `d/m/yy` → ISO `YYYY-MM-DD` con conversión de datos legacy y saneamiento de filas no parseables (NULL).
- Centralizar la fórmula RMₐ en `metrics_engine.rm_ajustado` y reemplazar las 6 duplicaciones (backend + guard de regresión para el JS del editor).
- Retención de backups: mantener solo los últimos 30, tanto en `backup_db` como en el backup previo a migraciones.
- Limpieza técnica: `restore_session_rows` que preserva `origen` en el undo; borrado de ~12 funciones muertas en `charts.py` y `training_service.py`; validación de creación de ejercicio movida a `exercise_service`.
- Nueva sección "Últimas Sesiones" (`GET /sesiones`) con OOB refresh tras save/delete/undo y navegación con dirty-check.
- Tailwind estático (`scripts/build_css.sh` → `static/css/tailwind.css` commiteado), CDN retirado del CSP.
- Ventana CSRF configurable (env `GYM_CSRF_WINDOW_HOURS`, default 7 días), mensaje de rechazo claro, warning al arrancar si se usa el secreto de desarrollo.
- Anillo `:focus-visible` visible (a11y).
- UX de navegación: input de fecha, atajos de teclado (←/→ día, ⌘/Ctrl+←/→ semana), modal custom para eliminar entreno, hints de atajos, e2e responsive a 375px.

### Explicit non-goals

- No cambiar el diseño visual, el contrato htmx (`#session-editor-wrap`, `#set-rows`, `hx-swap-oob`), ni la identidad de la paleta.
- No introducir SPA, ORM, build framework (más allá de Tailwind CSS), cuentas de usuario ni librería de migraciones.
- No cambiar el comportamiento readonly de fechas pasadas sin datos (decisión confirmada: la hoja importada sigue siendo la fuente de verdad histórica).
- No eliminar `requirements.txt` (export de compatibilidad) ni tocar `AGENTS.md`.

### Definition of done

- `data/gym.db` real migra a ISO sin pérdida y el dashboard funciona igual visualmente.
- `ORDER BY fecha` es cronológico en SQL (export CSV verificado por test).
- Una sola definición de la fórmula RMₐ en Python; el JS del editor queda cubierto por guard de regresión.
- Tras una mutación quedan ≤30 backups en `data/backups/`.
- `GET /sesiones` muestra las últimas 10 sesiones y navega al editor con confirmación de cambios no guardados.
- `base.html` no referencia `cdn.tailwindcss.com`; CSP sin runtime JS de terceros para estilos.
- Suite completa en verde: `uv run pytest -q`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy app.py src tests`, y `uv run python scripts/verify_editor.py`.

## Guardrails for every phase

1. Trabajar en la rama `forensic-remediation` creada desde el commit del estado actual.
2. TDD: antes de cada cambio, el test más estrecho falla; tras cada cambio lógico, test estrecho + `uv run pytest -q`.
3. Preservar IDs, `data-*`, nombres de campo de formulario, targets htmx y marcadores `hx-swap-oob` hasta que un test demuestre un cambio intencional.
4. Un commit lógico por tarea. Nunca incluir `data/*.db`, backups, `.venv`, caches ni cambios ajenos.
5. SQL parametrizado únicamente (`?`); no interpolar datos del cliente en SQL, HTML, JS ni URLs.

# Phase 0 — Baseline and safety rails (blocker for all code changes)

### Task 0.1: Commit del estado actual y crear rama

**Files:**
- Modify: ninguno (solo git)
- Test: ninguno

**Step 1: Verificar el árbol de trabajo.**

Run: `git status --short`

Expected: modificados `scripts/verify_editor.py`, `static/css/session-editor.css`, `static/js/htmx-lifecycle.js`, `templates/index.html`, `templates/session_editor.html` (trabajo de compactación/scrollbar previo).

**Step 2: Commit y rama.**

```bash
git add -A
git commit -m "style: compact session editor panel, aligned title, thin scrollbar"
git checkout -b forensic-remediation
```

**Step 3: Baseline de suite.**

Run: `uv run pytest -q`

Expected: PASS, registrar el contador (190 actual) como referencia de esta fase.

# Phase 1 — Normalizar fechas a ISO y centralizar la fórmula RMₐ (base arquitectónica)

### Task 1.1: Migración v004 `iso_dates`

**Files:**
- Create: `src/migrations/v004_iso_dates.py`
- Modify: `src/migrations/runner.py`
- Test: `tests/test_database.py`

**Step 1: Escribir el test que falla.**

```python
def test_v004_convierte_fechas_a_iso(tmp_path):
    from src.migrations import v004_iso_dates
    db = str(tmp_path / "legacy.db")
    with connect_db(db) as conn:
        conn.execute("CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER, dia TEXT, fecha TEXT, set_orden INTEGER, ejercicio TEXT, reps REAL, kg REAL, rir REAL)")
        conn.execute("INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (1, 'LUNES', '6/8/26', 1, 'Press', 90, 7, 1.2)")
        conn.execute("INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (2, 'MARTES', '10/02/2026', 1, 'Press', 90, 7, 1.2)")
        conn.execute("INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (3, 'MIERCOLES', 'basura', 1, 'Press', 90, 7, 1.2)")
    v004_iso_dates.migrate(connect_db(db))
    with read_connection(db) as conn:
        fechas = [r[0] for r in conn.execute("SELECT fecha FROM training_sets ORDER BY id")]
    assert fechas == ["2026-08-06", "2026-02-10", None]
```

**Step 2: Verificar que falla.**

Run: `uv run pytest tests/test_database.py::test_v004_convierte_fechas_a_iso -v`

Expected: FAIL (ModuleNotFoundError `v004_iso_dates`).

**Step 3: Implementación mínima.**

```python
# src/migrations/v004_iso_dates.py
"""v004 — normalize training_sets.fecha to ISO (YYYY-MM-DD)."""
from datetime import datetime

VERSION = 4
NAME = "iso_dates"

_LEGACY_COL = "fecha_legacy"


def _iso_or_null(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def migrate(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(training_sets)").fetchall()}
    if _LEGACY_COL in cols or "fecha" not in cols:
        return
    conn.execute(f"ALTER TABLE training_sets RENAME COLUMN fecha TO {_LEGACY_COL}")
    conn.execute("ALTER TABLE training_sets ADD COLUMN fecha TEXT")
    for row_id, legacy in conn.execute(f"SELECT id, {_LEGACY_COL} FROM training_sets").fetchall():
        conn.execute("UPDATE training_sets SET fecha = ? WHERE id = ?", (_iso_or_null(legacy), row_id))
    conn.execute(f"ALTER TABLE training_sets DROP COLUMN {_LEGACY_COL}")
```

Registrar en `src/migrations/runner.py`: importar `v004_iso_dates` y añadirlo a `MIGRATIONS` tras `v003_add_template_order`.

**Step 4: Verificar que pasa.**

Run: `uv run pytest tests/test_database.py -v`

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/migrations/v004_iso_dates.py src/migrations/runner.py tests/test_database.py
git commit -m "feat: v004 migration normalizes session dates to ISO"
```

### Task 1.2: `fecha_to_db` → ISO + helper `fecha_display`

**Files:**
- Modify: `src/training_service.py:33-38`
- Test: `tests/test_training_service.py`

**Step 1: Test rojo.**

```python
def test_fecha_to_db_devuelve_iso():
    assert fecha_to_db(date(2026, 8, 6)) == "2026-08-06"

def test_fecha_display():
    assert fecha_display("2026-08-06") == "6/8/26"
```

**Step 2:** Run: `uv run pytest tests/test_training_service.py -k "fecha" -v` → FAIL (sigue devolviendo `6/8/26`).

**Step 3: Implementación.**

```python
def fecha_to_db(fecha: date) -> str:
    return fecha.strftime("%Y-%m-%d")


def fecha_from_db(fecha: str) -> date:
    return datetime.strptime(fecha, "%Y-%m-%d").date()


def fecha_display(fecha_iso: str) -> str:
    d = fecha_from_db(fecha_iso)
    return f"{d.day}/{d.month}/{d.year % 100:02d}"
```

**Step 4:** Run: `uv run pytest tests/test_training_service.py -v` → PASS.

**Step 5: Commit.**

```bash
git add src/training_service.py tests/test_training_service.py
git commit -m "feat: session dates stored as ISO, display helper added"
```

### Task 1.3: Renombrar `fecha_db` → `fecha_display` en el view model

**Files:**
- Modify: `src/view_models.py:33`
- Modify: `src/dashboard_service.py:209` (usar `fecha_display(fecha_iso)`)
- Modify: `app.py:132` (clave del contexto)
- Modify: `templates/session_editor.html:4` (`{{ fecha_db }}` → `{{ fecha_display }}`)
- Test: `tests/test_app.py` (ajustar asserts que referencien `fecha_db`)

**Step 1:** `rg -n "fecha_db" tests` → ajustar referencias.

**Step 2:** Aplicar el rename en los 4 sitios.

**Step 3:** Run: `uv run pytest tests/test_app.py -v` → PASS (el título del editor sigue mostrando "JUEVES 6/8/26").

**Step 4: Commit.**

```bash
git add src app.py templates tests
git commit -m "refactor: rename editor fecha_db to fecha_display"
```

### Task 1.4: Orden cronológico nativo en SQL (eliminar parseos Python)

**Files:**
- Modify: `src/database.py` (`get_training_sessions`, `get_last_session_sets`, borrar `_parse_fecha`)
- Test: `tests/test_database.py`

**Step 1: Test rojo.**

```python
def test_get_training_sessions_ordena_por_fecha_iso(tmp_path):
    db = str(tmp_path / "g.db")
    init_db(db)
    for iso in ("2026-03-01", "2026-01-15", "2026-02-10"):
        with transaction(db) as conn:
            conn.execute(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
                "VALUES (?, 'LUNES', ?, 1, 'Press', 90, 7, 1.2)",
                (1, iso),
            )
    sessions = get_training_sessions(db)
    assert [s["fecha"] for s in sessions] == ["2026-03-01", "2026-02-10", "2026-01-15"]
```

**Step 2:** Run: `uv run pytest tests/test_database.py::test_get_training_sessions_ordena_por_fecha_iso -v` → FAIL (el parseo `d/m/yy` lanza ValueError y descarta filas).

**Step 3: Implementación.** Reemplazar el cuerpo de `get_training_sessions` por una sola consulta con `GROUP BY semana, dia, fecha` + `ORDER BY fecha DESC` sin parseo en Python; `get_last_session_sets` con `ORDER BY fecha DESC LIMIT 1` en SQL; borrar `_parse_fecha` (líneas 80-81).

**Step 4:** Run: `uv run pytest tests/test_database.py -v` → PASS (actualizar los tests existentes que insertaban fechas `d/m/yy` a ISO con el helper `fecha_to_db(date(...))`).

**Step 5: Commit.**

```bash
git add src/database.py tests/test_database.py
git commit -m "refactor: chronological ordering now native in SQL (ISO dates)"
```

### Task 1.5: Fórmula RMₐ centralizada en `metrics_engine`

**Files:**
- Modify: `src/metrics_engine.py` (constante + helper + usos)
- Modify: `src/dashboard_service.py:164` (`_editor_rows`)
- Modify: `src/charts.py` (`get_exercise_raw_data`, `get_exercise_session_summary`)
- Create: `tests/test_metrics_engine.py`
- Modify: `tests/test_coverage_edges.py` (guard JS)

**Step 1: Test rojo.**

```python
from src.metrics_engine import RM_FACTOR, rm_ajustado

def test_rm_ajustado_escalar():
    assert rm_ajustado(90, 7, 1.2) == 90 * (1 + 0.0333 * (7 + 1 + 1.2))

def test_factor_constante():
    assert RM_FACTOR == 0.0333

def test_editor_js_usa_misma_constante_rm():
    src = Path("static/js/editor.js").read_text()
    assert "0.0333" in src
```

**Step 2:** Run: `uv run pytest tests/test_metrics_engine.py tests/test_coverage_edges.py -v` → FAIL (no existe `rm_ajustado`/`RM_FACTOR`).

**Step 3: Implementación.**

```python
RM_FACTOR = 0.0333


def rm_ajustado(kg: float, reps: float, rir: float = 0.0) -> float:
    """RM ajustado: kg * (1 + 0.0333 * (reps + 1 + rir))."""
    return kg * (1 + RM_FACTOR * (reps + 1 + rir))
```

Sustituir en `get_exercises_baselines` y `calculate_pfr_timeline` las fórmulas inline por `RM_FACTOR` (manteniendo la vectorización: `df["rm_ajustado"] = df["kg"] * (1 + RM_FACTOR * (df["reps"] + 1 + rir_safe))`). En `dashboard_service._editor_rows`: `rm = round(rm_ajustado(kg, reps, rir or 0.0), 1)`. En `charts.get_exercise_raw_data`: `rm` y `rm_ajustado` con `RM_FACTOR`; igual en `get_exercise_session_summary`.

**Step 4:** Run: `uv run pytest -q` → PASS.

**Step 5: Commit.**

```bash
git add src tests
git commit -m "refactor: single RM-adjusted formula in metrics_engine"
```

### Task 1.6: Parser e import → fechas ISO

**Files:**
- Modify: `src/parser.py` (conversión en `parse_ciclo`)
- Test: `tests/test_parser.py`

**Step 1:** Actualizar los asserts de `test_parser.py` a fechas ISO (las fechas de fixture `d/m/yy` → `YYYY-MM-DD` con el mismo `_iso_or_null`).

**Step 2:** Run: `uv run pytest tests/test_parser.py -v` → FAIL.

**Step 3:** En `src/parser.py` añadir `_iso_or_null` (mismo código que v004) y en `parse_ciclo` cambiar `"fecha": dates_per_week.get(week_num)` → `"fecha": _iso_or_null(dates_per_week.get(week_num))`.

**Step 4:** Run: `uv run pytest tests/test_parser.py tests/test_integration.py -v` → PASS.

**Step 5: Commit.**

```bash
git add src/parser.py tests/test_parser.py
git commit -m "feat: sheet import converts dates to ISO"
```

### Task 1.7: Export CSV cronológico + test

**Files:**
- Test: `tests/test_app.py` (la lógica de `app.py:462-471` no cambia: con ISO, `ORDER BY fecha` ya ordena)

**Step 1: Test.**

```python
def test_export_csv_orden_cronologico(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    from src.training_service import save_session
    from src.models import TrainingSetInput
    for iso, sets in [
        ("2026-01-15", [TrainingSetInput("Press", 90, 7, 1)]),
        ("2026-02-03", [TrainingSetInput("Press", 92, 7, 1)]),
        ("2026-01-09", [TrainingSetInput("Press", 88, 7, 1)]),
    ]:
        save_session(str(tmp_path / "gym.db"), iso, sets)
    resp = client.get("/exportar/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    fechas = [ln.split(",")[3] for ln in resp.text.splitlines()[1:]]
    assert fechas == ["2026-01-09", "2026-01-15", "2026-02-03"]
```

**Step 2:** Run: `uv run pytest tests/test_app.py::test_export_csv_orden_cronologico -v` → FAIL antes de la migración de datos de test; con ISO → PASS.

**Step 3:** Sin cambio de código (comportamiento corregido por la migración).

**Step 4: Commit.**

```bash
git add tests/test_app.py
git commit -m "test: export CSV is chronologically ordered (ISO dates)"
```

### Task 1.8: Barrido de literales de fecha en tests

**Files:**
- Modify: `tests/test_charts.py`, `tests/test_database.py`, `tests/test_training_service.py`, `tests/test_models.py`, `tests/test_coverage_edges.py`

**Step 1:** `rg -n "[0-9]{1,2}/[0-9]{1,2}/[0-9]{2}" tests --glob "*.py"` → convertir cada literal `d/m/yy` a ISO (los tests que usan `fecha_to_db(date(...))` ya funcionan por identidad).

**Step 2:** Run: `uv run pytest -q` → PASS.

**Step 3:** Run: `uv run mypy app.py src tests` → PASS.

**Step 4: Commit.**

```bash
git add tests
git commit -m "test: migrate date literals to ISO"
```

# Phase 2 — Retención de backups

### Task 2.1: `src/backup_utils.py` + prune en `backup_db` y runner

**Files:**
- Create: `src/backup_utils.py`
- Modify: `src/database.py:17-24` (`backup_db(db_path, *, keep: int = 30)`)
- Modify: `src/migrations/runner.py:22-30` (`_backup_before_upgrade`)
- Test: `tests/test_database.py`

**Step 1: Test rojo.**

```python
def test_backup_prune_mantiene_ultimos_30(tmp_path):
    db = str(tmp_path / "g.db")
    init_db(db)
    for i in range(35):
        (tmp_path / "backups" / f"gym-20260804-{100000 + i:06d}.db").touch()
    backup_db(db)
    backups = sorted(p.name for p in (tmp_path / "backups").glob("gym-*.db"))
    assert len(backups) == 30
```

**Step 2:** Run: `uv run pytest tests/test_database.py::test_backup_prune_mantiene_ultimos_30 -v` → FAIL (quedan 36).

**Step 3: Implementación.**

```python
# src/backup_utils.py
"""Backup retention helpers shared by app backups and migration pre-upgrade backups."""
from pathlib import Path


def prune_backups(backups_dir: str, keep: int) -> None:
    files = sorted(Path(backups_dir).glob("gym-*.db"))
    if len(files) <= keep:
        return
    for stale in files[:-keep]:
        stale.unlink(missing_ok=True)
```

En `database.backup_db`: tras `shutil.copy2`, llamar `prune_backups(backups_dir, keep)`. En `runner._backup_before_upgrade`: tras el copy, `prune_backups(backups_dir, 30)`.

**Step 4:** Run: `uv run pytest tests/test_database.py -v` → PASS (ajustar `test_backup_only_when_pending_migrations` si cuenta archivos).

**Step 5: Commit.**

```bash
git add src/backup_utils.py src/database.py src/migrations/runner.py tests/test_database.py
git commit -m "feat: backup retention keeps last 30 snapshots"
```

# Phase 3 — Limpieza técnica

### Task 3.1: Undo preserva `origen`

**Files:**
- Modify: `src/training_service.py` (nueva `restore_session_rows`)
- Modify: `src/mutation_service.py:116` (usarla en `undo_last_action`)
- Test: `tests/test_app.py`

**Step 1: Test rojo.**

```python
def test_undo_restaura_origen_google(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with read_connection(str(tmp_path / "gym.db")) as conn:
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (1, 'LUNES', '2026-08-06', 1, 'Press', 90, 7, 1.2, 'google')"
        )
    fecha = "2026-08-06"
    client.post("/entrenamiento/session/save", data={"fecha": fecha, "ejercicio": ["Press"], "kg": ["95"], "reps": ["6"], "rir": ["1"]}, headers=_csrf_headers(client))
    client.post("/undo", data={"fecha": fecha}, headers=_csrf_headers(client))
    rows = get_sets_by_fecha(str(tmp_path / "gym.db"), "2026-08-06")
    assert rows[0]["kg"] == 90 and rows[0]["origen"] == "google"
```

(Reutilizar las fixtures existentes `_client` y `_csrf_headers` de `test_app.py`.)

**Step 2:** Run: `uv run pytest tests/test_app.py::test_undo_restaura_origen_google -v` → FAIL (origen vuelve como `manual`).

**Step 3: Implementación.**

```python
def restore_session_rows(db_path: str, fecha_iso: str, rows: list) -> None:
    """Undo restore: reinserts saved rows preserving each row's origen."""
    fecha = parse_form_date(fecha_iso)
    ciclo = parse_cycle_start()
    semana = calculate_cycle_week(fecha, ciclo)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    kept = []
    for raw in rows:
        if _is_empty_row(raw):
            continue
        origen = str(raw.get("origen") or "manual") if isinstance(raw, dict) else "manual"
        kept.append((_coerce_set(raw), origen))
    cleaned = validate_sets(db_path, [s for s, _ in kept])
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha_db,))
        for idx, (s, origen) in enumerate(zip(cleaned, [o for _, o in kept]), start=1):
            conn.execute(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (semana, dia, fecha_db, idx, s.ejercicio, s.reps, s.kg, s.rir, origen),
            )
```

En `mutation_service.py`: importar `restore_session_rows` y sustituir `save_session(db_path, fecha_iso, entry["before"])`.

**Step 4:** Run: `uv run pytest tests/test_app.py -k undo -v && uv run pytest -q` → PASS.

**Step 5: Commit.**

```bash
git add src/training_service.py src/mutation_service.py tests/test_app.py
git commit -m "fix: undo restores original set origin"
```

### Task 3.2: Eliminar código muerto

**Files:**
- Modify: `src/charts.py` — borrar `chart_rm_progression`, `chart_tonnage_per_session`, `get_exercise_detail`, `get_exercise_best_rm`, `chart_exercise_rm`, `pivot_exercise_table`, `get_muscle_group_volume`, `chart_muscle_group_volume` y el import `plotly.express as px`
- Modify: `src/training_service.py` — borrar `get_session_detail`, `insert_manual_session`, `update_session`, `_session_from_meta` y el import `get_session_sets`
- Modify: `src/dashboard_service.py` — subir el import local `from src.database import get_exercises_catalog, get_sets_by_fecha` a nivel de módulo
- Modify: `tests/test_charts.py` (reescribir para cubrir solo `chart_pfr_timeline`, `get_exercise_raw_data`, `get_exercise_session_summary`)
- Modify: `tests/test_training_service.py` (los 8 usos de `insert_manual_session` → `save_session`)

**Step 1:** Reescribir primero `tests/test_charts.py` con asserts sobre las funciones vivas (p.ej. `chart_pfr_timeline(db, "exercise", "Press")` no vacía) → run FAIL si el chart cambió de contrato, PASS en estado actual.

**Step 2:** Borrar funciones e imports; refactorizar el seeding de `test_training_service.py`.

**Step 3:** Run: `uv run pytest -q && uv run ruff check .` → PASS (sin imports sin usar).

**Step 4: Commit.**

```bash
git add src/charts.py src/training_service.py src/dashboard_service.py tests
git commit -m "refactor: remove dead chart and training code"
```

### Task 3.3: `exercise_service.create_exercise`

**Files:**
- Create: `src/exercise_service.py`
- Modify: `app.py:272-309` (`/ejercicio/nuevo` delgado: parseo → servicio → respuesta)
- Create: `tests/test_exercise_service.py`

**Step 1: Test rojo.**

```python
def test_create_exercise_valid(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    create_exercise(db, "Press Banca", "Pectoral", "EMPUJE")
    assert "Press Banca" in get_exercises_catalog(db)


def test_create_exercise_duplicado_case_insensitive(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press Banca", "Pectoral", "EMPUJE")
    with pytest.raises(ConflictError):
        create_exercise(db, "press banca", "Pectoral", "EMPUJE")
```

**Step 2:** Run: `uv run pytest tests/test_exercise_service.py -v` → FAIL (no existe el módulo).

**Step 3: Implementación.** Mover la validación del handler (nombre/grupo obligatorios, categoría en `MUSCLE_CATEGORIES`, duplicado case-insensitive → `ConflictError`) a `src/exercise_service.py`; `app.py` usa `create_exercise` dentro del try/except con `_domain_error_response`.

**Step 4:** Run: `uv run pytest tests/test_exercise_service.py tests/test_app.py -v` → PASS (ruta sigue cubierta).

**Step 5: Commit.**

```bash
git add src/exercise_service.py app.py tests
git commit -m "feat: exercise creation moved to typed service use case"
```

# Phase 4 — Historial de sesiones

### Task 4.1: Fragmento `session_history.html` + ruta `GET /sesiones`

**Files:**
- Create: `templates/session_history.html`
- Modify: `src/dashboard_service.py` (`get_recent_sessions(limit=10)` reutilizando `get_training_sessions`)
- Modify: `app.py` (`_sesiones_list_html` + ruta + contexto en `read_index`)
- Modify: `src/response_fragments.py` (añadir `"session-history"` a `OOB_FRAGMENT_TARGETS`)
- Modify: `templates/index.html` (contenedor `#session-history` en el aside, entre `#plantillas-section` y las categorías)
- Modify: `static/js/date-navigation.js` (acción `goto-session` → `requestNavigate`)
- Test: `tests/test_app.py`

**Step 1: Test rojo.**

```python
def test_sesiones_view_renders_ultimas(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    save_session(str(tmp_path / "gym.db"), "2026-08-06", [TrainingSetInput("Press", 90, 7, 1)])
    resp = client.get("/sesiones")
    assert resp.status_code == 200
    assert "2026-08-06" in resp.text and "series" in resp.text
```

**Step 2:** Run: `uv run pytest tests/test_app.py::test_sesiones_view_renders_ultimas -v` → FAIL (404).

**Step 3: Implementación.**

`src/dashboard_service.py`:

```python
def get_recent_sessions(db_path: str, limit: int = 10) -> list[dict]:
    sessions = get_training_sessions(db_path)[:limit]
    for s in sessions:
        try:
            s["fecha_display"] = fecha_display(s["fecha"])
        except ValueError:
            s["fecha_display"] = s["fecha"]
    return sessions
```

`app.py`:

```python
def _sesiones_list_html(request: Request) -> str:
    return _render_body(templates.TemplateResponse(
        request=request, name="session_history.html",
        context={"sessions": get_recent_sessions(DB_PATH)}))


@app.get("/sesiones", response_class=HTMLResponse)
def sesiones_view(request: Request):
    return HTMLResponse(content=_sesiones_list_html(request))
```

`templates/session_history.html` (raíz `<div id="session-history">` para el patrón OOB; `<details>` cerrado por defecto):

```html
<div id="session-history">
    <details class="bg-neutral-900 border border-transparent rounded-xl flex flex-col gap-2.5 neon-border metallic-border">
        <summary class="text-xs font-black tracking-[0.2em] text-burgundy-400 uppercase text-center pb-2 border-b border-neutral-800 neon-title cursor-pointer px-4 pt-4">Últimas Sesiones</summary>
        <div class="flex flex-col gap-0.5 px-2 pb-2">
        {% if not sessions %}
            <p class="text-[11px] text-neutral-500 text-center py-1">Aún no hay sesiones.</p>
        {% else %}
            {% for s in sessions %}
            <button type="button" data-action="goto-session" data-iso="{{ s.fecha }}"
                class="text-left text-[11px] text-neutral-400 hover:text-burgundy-400 hover:bg-white/[0.04] rounded px-1.5 py-1 transition-colors">
                <span class="font-bold text-neutral-200">{{ s.dia }}</span>
                {{ s.fecha_display }} · {{ s.n_series }} series · {{ s.n_ejercicios }} ej.
            </button>
            {% endfor %}
        {% endif %}
        </div>
    </details>
</div>
```

`index.html`: `<div id="session-history">{{ session_history_html | safe }}</div>` + contexto `session_history_html` en `read_index`. `date-navigation.js` (handler de click): `else if (el.dataset.action === 'goto-session') requestNavigate(el.dataset.iso);`.

**Step 4:** Run: `uv run pytest tests/test_app.py -v && uv run pytest -q` → PASS.

**Step 5: Commit.**

```bash
git add src app.py templates static/js tests
git commit -m "feat: recent sessions history section with navigation"
```

### Task 4.2: OOB refresh tras mutaciones

**Files:**
- Modify: `app.py` — en `entrenamiento_session_save` (respuesta con `saved_rows`), `entrenamiento_session_eliminar` y `undo` (rama `sesion`), añadir `+ fragment_oob(templates, request, "session-history", _sesiones_list_html(request))`
- Test: `tests/test_app.py`

**Step 1: Test rojo.**

```python
def test_save_incluye_oob_history(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/entrenamiento/session/save", data={"fecha": "2026-08-06", "ejercicio": ["Press"], "kg": ["90"], "reps": ["7"], "rir": ["1"]}, headers=_csrf_headers(client))
    assert 'id="session-history" hx-swap-oob="innerHTML"' in resp.text
```

**Step 2:** Run → FAIL (no está el fragmento).

**Step 3:** Añadir el append en los 3 handlers (save/eliminar/undo-sesion).

**Step 4:** Run: `uv run pytest tests/test_app.py -k "oob_history or undo or eliminar" -v` → PASS.

**Step 5: Commit.**

```bash
git add app.py tests/test_app.py
git commit -m "feat: history OOB refresh after save/delete/undo"
```

### Task 4.3: e2e navegación desde el historial

**Files:**
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Test.** Seed 2 sesiones en fechas distintas; abrir `/`; click en la sesión del historial; esperar el swap y assert de `#session-form input[name="fecha"]` con la fecha objetivo.

**Step 2:** Run: `uv run pytest tests/e2e/test_dashboard_flow.py -v` → FAIL si el handler no dispara.

**Step 3:** Depurar el data-action/swap (el JS ya está implementado en Task 4.1; solo si falla).

**Step 4:** PASS.

**Step 5: Commit.**

```bash
git add tests/e2e/test_dashboard_flow.py
git commit -m "test: e2e navigate from session history"
```

# Phase 5 — Seguridad y accesibilidad

### Task 5.1: Tailwind estático (fuera del CDN)

**Files:**
- Create: `static/css/input.css` (`@tailwind base; @tailwind components; @tailwind utilities;`)
- Create: `scripts/build_css.sh`
- Create: `static/css/tailwind.css` (generado, commiteado)
- Modify: `templates/base.html:9` (quitar `<script src="https://cdn.tailwindcss.com"></script>` → `<link rel="stylesheet" href="/static/css/tailwind.css">`)
- Modify: `src/security.py:14-25` (CSP sin `https://cdn.tailwindcss.com` en script-src ni style-src; mantener `'unsafe-inline'` en style-src — Plotly inyecta estilos; actualizar el comentario del módulo)
- Modify: `tests/test_app.py` (`test_base_template_cdn_scripts_pin_sri` → 3 CDNs; añadir `test_base_template_sin_cdn_tailwind` y `test_static_tailwind_css_served`)

**Step 1: Tests rojos.** Los asserts de SRI listando CDNs fallan con el cambio; escribirlos primero (esperar 3 CDNs con SRI + `<link ... tailwind.css>` + ausencia de `cdn.tailwindcss.com`).

**Step 2: Build.**

```bash
chmod +x scripts/build_css.sh
./scripts/build_css.sh
```

Con `scripts/build_css.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes tailwindcss@3.4.17 \
  --content "templates/**/*.html" "static/js/**/*.js" \
  -i static/css/input.css -o static/css/tailwind.css --minify
```

Expected: `static/css/tailwind.css` generado (las utilidades dinámicas de `dashboard-filters.js` como `shadow-[0_0_10px_rgba(155,27,48,0.5)]` están en el scan de contenido).

**Step 3:** Aplicar cambios de `base.html` y CSP.

**Step 4:** Run: `uv run pytest tests/test_app.py -k "static or base" -v && uv run pytest -q` → PASS.

**Step 5: Verificación visual obligatoria.**

Run: `uv run uvicorn app:app --host 127.0.0.1 --port 8000`

Expected: estilos de editor, navegador, plantillas e historial intactos.

**Step 6: Commit.**

```bash
git add static/css templates/base.html src/security.py scripts tests
git commit -m "feat: static tailwind build, CDN runtime removed from CSP"
```

### Task 5.2: Ventana CSRF configurable + mensaje claro

**Files:**
- Modify: `src/security.py` (`CSRF_WINDOW_SECONDS` vía `GYM_CSRF_WINDOW_HOURS`, default `24*7`; `_forbidden` con mensaje de recarga)
- Modify: `tests/test_security.py` (usar la constante para offsets de expiración)

**Step 1: Test rojo.**

```python
def test_csrf_window_configurable(monkeypatch):
    monkeypatch.setenv("GYM_CSRF_WINDOW_HOURS", "1")
    import importlib
    import src.security as sec
    importlib.reload(sec)
    assert sec.CSRF_WINDOW_SECONDS == 3600
```

(limpia el env en teardown.)

**Step 2:** Run → FAIL (ventana fija de 24h).

**Step 3: Implementación.**

```python
def _window_seconds() -> int:
    try:
        return int(os.environ.get("GYM_CSRF_WINDOW_HOURS", str(24 * 7))) * 3600
    except ValueError:
        return 24 * 7 * 3600


CSRF_WINDOW_SECONDS = _window_seconds()
```

`_forbidden`: `b"<div class='notice notice-error'>Sesión de seguridad vencida. Recarga la página e intenta de nuevo.</div>"`.

**Step 4:** Run: `uv run pytest tests/test_security.py -v` → PASS (ajustar offsets de expiración a `CSRF_WINDOW_SECONDS`).

**Step 5: Commit.**

```bash
git add src/security.py tests/test_security.py
git commit -m "feat: configurable CSRF window and clear rejection message"
```

### Task 5.3: Warning al arrancar con secreto de desarrollo

**Files:**
- Modify: `app.py` (lifespan)
- Test: `tests/test_app.py`

**Step 1: Test rojo.**

```python
def test_lifespan_warns_sin_csrf_secret(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("GYM_CSRF_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as c:
            c.get("/")
    assert any("GYM_CSRF_SECRET" in r.message for r in caplog.records)
```

**Step 2:** Run → FAIL.

**Step 3:** En `lifespan`: `if os.environ.get("GYM_CSRF_SECRET") is None: logging.getLogger("security").warning("GYM_CSRF_SECRET no configurado: usando secreto de desarrollo.")`.

**Step 4:** PASS.

**Step 5: Commit.**

```bash
git add app.py tests/test_app.py
git commit -m "feat: warn when CSRF dev secret is active"
```

### Task 5.4: Anillo `:focus-visible` (a11y)

**Files:**
- Modify: `static/css/theme.css:24-29` (quitar `outline: none !important` global)
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Test rojo (e2e).**

```python
def test_keyboard_focus_ring_visible(page, server):
    page.goto(server)
    page.wait_for_selector("#app-config")
    page.keyboard.press("Tab")
    has_outline = page.evaluate(
        "() => { const e = document.activeElement; const cs = getComputedStyle(e);"
        " return cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px'; }"
    )
    assert has_outline
```

**Step 2:** Run → FAIL (outline suprimido).

**Step 3: Implementación.**

```css
button:focus { outline: none; }
button:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible {
    outline: 2px solid #e56d88 !important;
    outline-offset: 2px;
}
```

**Step 4:** Run: `uv run pytest tests/e2e/test_dashboard_flow.py -v` → PASS.

**Step 5: Commit.**

```bash
git add static/css/theme.css tests/e2e/test_dashboard_flow.py
git commit -m "fix: visible keyboard focus ring (a11y)"
```

# Phase 6 — UX de navegación

### Task 6.1: Input de fecha + atajos de teclado

**Files:**
- Modify: `templates/date_navigator.html` (input `type="date"` entre los botones de scroll)
- Modify: `static/js/date-navigation.js` (handler `jump-date-input` + atajos ←/→ y ⌘/Ctrl+←/→, con `getCurrentIso`)
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Test rojo (e2e).**

```python
def test_keyboard_day_shift_updates_editor(page, server):
    page.goto(server)
    fecha = page.input_value("#session-form input[name='fecha']")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(
        "document.querySelector('#session-form input[name=\\'fecha\\']').value !== arguments[0]", fecha
    )
```

**Step 2:** Run → FAIL (sin handler).

**Step 3: Implementación.**

`date_navigator.html`:

```html
<input type="date" id="date-jump" data-action="jump-date-input" value="{{ selected_iso }}"
    class="h-7 px-1.5 bg-matte-950 border border-neutral-800 rounded text-[11px] text-neutral-300 focus:outline-none"
    title="Ir a fecha">
```

`date-navigation.js`:

```js
document.addEventListener('change', function (e) {
    const el = e.target.closest('[data-action="jump-date-input"]');
    if (el && el.value) requestNavigate(el.value);
});

function shiftDay(days) {
    const iso = getCurrentIso();
    if (!iso) return;
    const d = new Date(iso + 'T00:00:00');
    d.setDate(d.getDate() + days);
    requestNavigate(d.toISOString().slice(0, 10));
}

document.addEventListener('keydown', function (e) {
    const inField = e.target.closest && e.target.closest('input, textarea, select');
    if (inField) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); shiftDay(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); shiftDay(1); }
    else if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowLeft') { e.preventDefault(); shiftDay(-7); }
    else if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowRight') { e.preventDefault(); shiftDay(7); }
});
```

(importar `getCurrentIso` desde `state.js`.)

**Step 4:** Run: `uv run pytest tests/e2e/test_dashboard_flow.py -v` → PASS.

**Step 5: Commit.**

```bash
git add templates/date_navigator.html static/js/date-navigation.js tests/e2e/test_dashboard_flow.py
git commit -m "feat: date input jump and keyboard day/week navigation"
```

### Task 6.2: Modal custom para eliminar entreno

**Files:**
- Modify: `static/js/templates.js:48-51` (reemplazar `confirm()` por `showConfirmDialog`)
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Test rojo (e2e):** crear plantilla → click "Eliminar" → `#confirm-modal` visible.

**Step 2:** Run → FAIL (usa `confirm()` nativo).

**Step 3: Implementación.**

```js
export function eliminarPlantilla(id, nombre) {
    document.getElementById('confirm-msg').textContent = `¿Eliminar el entreno "${nombre}"?`;
    showConfirmDialog(function () {
        htmx.ajax('POST', `/plantilla/eliminar/${id}`, { target: 'body', swap: 'none' });
    }, null);
}
```

**Step 4:** PASS.

**Step 5: Commit.**

```bash
git add static/js/templates.js tests/e2e/test_dashboard_flow.py
git commit -m "feat: custom confirm modal for template deletion"
```

### Task 6.3: Hints de atajos

**Files:**
- Modify: `templates/index.html` (línea de hints bajo `#session-editor`)

**Step 1:** Añadir tras el panel editor:

```html
<p class="text-[10px] text-neutral-600 text-center -mt-3">Ctrl+Z deshacer · Esc ver todo · ←/→ día · ⌘+←/→ semana</p>
```

**Step 2:** Verificación visual con uvicorn.

**Step 3: Commit.**

```bash
git add templates/index.html
git commit -m "style: keyboard shortcut hints under editor"
```

### Task 6.4: e2e responsive a 375px

**Files:**
- Modify: `tests/e2e/test_dashboard_flow.py`

**Step 1: Test.**

```python
def test_mobile_viewport_renders(page, server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(server)
    assert page.is_visible("#session-editor")
    assert page.is_visible("#date-navigator")
    can_scroll = page.evaluate(
        "() => { const el = document.querySelector('#session-editor .table-scroll');"
        " return el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight; }"
    )
    assert can_scroll
```

**Step 2:** Run → verificar; si el panel rompe en móvil, ajustar solo clases del panel (nunca el layout desktop).

**Step 3:** PASS.

**Step 4: Commit.**

```bash
git add tests/e2e/test_dashboard_flow.py
git commit -m "test: e2e responsive smoke at 375px"
```

## Recommended execution order and checkpoints

1. Phase 1 completa y gate verde (suite + uvicorn + export manual) antes de tocar Fases 2-6: la migración ISO toca todos los consumidores.
2. Phase 2 y Phase 3 son independientes: ejecutar en paralelo y revisar juntas.
3. Phase 4 (historial) después de la limpieza de Phase 3, ya que reutiliza `get_training_sessions`.
4. Phase 5 antes de cualquier despliegue no local; verificación visual obligatoria tras el build de Tailwind.
5. Phase 6 es la puerta de UX: ejecutar la suite e2e completa al final.

## Gates globales de entrega

```bash
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run python scripts/verify_editor.py
./scripts/build_css.sh   # sin diff tras regenerar
uv run uvicorn app:app --host 127.0.0.1 --port 8000   # smoke manual
```

Cerrar el ciclo actualizando `docs/architecture/security-model.md` (CSP sin tailwind CDN, ventana CSRF configurable) y `docs/architecture/current-ui-contract.md` (nuevas acciones `goto-session`, `jump-date-input` y atajos de teclado).

## Acceptance review checklist

- [ ] `training_sets.fecha` es ISO en `data/gym.db` real y `ORDER BY fecha` es cronológico (export CSV verificado por test).
- [ ] La fórmula RMₐ existe una sola vez en Python (`metrics_engine.rm_ajustado` + `RM_FACTOR`) y el JS del editor está protegido por guard de regresión.
- [ ] `data/backups/` nunca supera 30 archivos tras mutaciones.
- [ ] El undo restaura el `origen` original de cada fila.
- [ ] No quedan funciones muertas en `charts.py`/`training_service.py`; `ruff check` no reporta imports sin usar.
- [ ] `GET /sesiones` muestra las últimas sesiones y navega al editor con confirmación de cambios no guardados.
- [ ] `base.html` no carga `cdn.tailwindcss.com`; el CSP no permite el runtime de Tailwind.
- [ ] La ventana CSRF es configurable por env y el rechazo 403 explica cómo recuperarse.
- [ ] El anillo `:focus-visible` es visible para teclado en botones e inputs.
- [ ] ←/→ y ⌘/Ctrl+←/→ navegan días/semanas; el input de fecha salta; el modal custom elimina entrenos.
- [ ] El dashboard renderiza y opera en viewport móvil de 375px.
- [ ] Suite completa en verde (pytest, ruff, mypy, verify_editor) y docs actualizadas.
