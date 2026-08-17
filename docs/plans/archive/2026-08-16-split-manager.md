# Gestor de Splits de Entrenamiento — Plan de Implementación

> **Estado: COMPLETADO (2026-08-16).** Gestor de splits, persistencia, métricas, catálogo y pruebas integrados.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Nueva página `GET /splits` para crear/editar/guardar/eliminar splits semanales con catálogo arrastrable (duplicados = series), métricas server-authoritative y multi-split persistente en SQLite.

**Architecture:** Patrón existente de `plantillas` aplicado a página standalone: migración versionada → `src/database.py` (SQL) → `src/split_service.py` (dominio tipado + métricas) → `src/mutation_service.py` (backup + journal undo, kind `"splits"`) → handlers delgados en `app.py` → fragmentos Jinja + htmx OOB → módulo ES `splits.js` con DnD nativo (patrón `initEntrenoDnD`, testeable con `_simulate_drag`).

**Tech Stack:** FastAPI + Jinja2 + htmx 1.9.10 + SQLite (WAL) + Tailwind compilado + SortableJS (solo reordenar filas dentro de un día, no para el DnD catálogo→día).

---

## Decisiones de diseño (contrato)

| Decisión | Detalle |
|---|---|
| Migración | `v015_splits.py`: tablas `training_splits` + `training_split_items`; índice UNIQUE en `LOWER(nombre)`; UNIQUE `(split_id, dia, orden)`; FK CASCADE; registrar en `_DOMAIN_TABLES` del runner |
| Día canónico | Reutilizar `DIA_MAP` de `src/training_service.py:14-21` (`LUNES..DOMINGO`, uppercase, sin acentos) — validación server contra esta lista |
| HIIT | Constantes en `split_service`: `HIIT_ITEM_TYPE="hiit"`, `HIIT_NAME="HIIT"`, `HIIT_GROUP="HIIT"`. Nunca se inserta en `ejercicios`. Fila: `item_type='hiit', ejercicio='HIIT', grupo_muscular='HIIT'` |
| `orden` | Server-computed: el cliente envía arrays alineados `dia[]/item_type[]/ejercicio[]` en orden visual (día a día, instancias en orden); el servidor agrupa por día, renumera `orden` desde 1 y **deriva `grupo_muscular` del catálogo** (nunca confía en el cliente) |
| Upsert por nombre | `POST /split/guardar` sigue el patrón `plantilla/guardar`: sin `split_id` → crear o actualizar por nombre (case-insensitive, `ConflictError` si choca con otro); con `split_id` → editar/renombrar ese split (`ConflictError` si el nombre pertenece a otro) |
| Límites | `MAX_SPLIT_ITEMS = 300` (nueva constante en `app.py`, junto a `MAX_REORDER_IDS`), `MAX_NAME_LEN = 200` reutilizado |
| Undo | `mutation_service.undo_last_action` nueva rama `kind == "splits"` → `restore_splits` + pop. `/undo` responde con OOB de `#splits-section`; `splits.js` refresca el board tras undo vía `htmx:afterRequest` |
| OOB targets nuevos | `"splits-section"`, `"split-board"` en `OOB_FRAGMENT_TARGETS` (`src/response_fragments.py:19-33`) |
| Form submit | `POST /split/guardar` con `split_id` (opcional), `nombre`, `dia[]`, `item_type[]`, `ejercicio[]` |

**Rutas finales** (adaptación de las sugeridas al patrón real del repo):

- `GET /splits` → página completa (catálogo + board + lista); `?abrir={id}` precarga un split
- `GET /split/{split_id}` → fragmento board (cargar/abrir/refrescar)
- `GET /split/lista` → fragmento lista
- `POST /split/guardar` → upsert; OOB `#notice-container` + `#splits-section` + `#split-board`
- `POST /split/eliminar/{split_id}` → OOB notice + lista + board vacío
- `POST /undo` (existente, modificada)

---

## Task 1: Migración `v015_splits`

**Files:**
- Create: `src/migrations/v015_splits.py`
- Modify: `src/migrations/runner.py` (import + lista + `_DOMAIN_TABLES`)
- Test: `tests/test_split_service.py` (fixture `db` usa `init_db` — valida migración)

**Step 1: escribir la migración**

```python
"""v015 — training_splits y training_split_items (gestor de splits)."""

VERSION = 15
NAME = "splits"


def migrate(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_splits ("
        "id INTEGER PRIMARY KEY, "
        "nombre TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_splits_nombre ON training_splits (LOWER(nombre))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_split_items ("
        "id INTEGER PRIMARY KEY, "
        "split_id INTEGER NOT NULL REFERENCES training_splits(id) ON DELETE CASCADE, "
        "dia TEXT NOT NULL, "
        "orden INTEGER NOT NULL, "
        "item_type TEXT NOT NULL DEFAULT 'ejercicio', "
        "ejercicio TEXT NOT NULL, "
        "grupo_muscular TEXT NOT NULL, "
        "UNIQUE (split_id, dia, orden))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_split_items_split ON training_split_items (split_id, dia, orden)"
    )
```

**Step 2: registrar** — import + `v015_splits` en `MIGRATIONS` (runner.py:7-37); añadir `"training_splits", "training_split_items"` a `_DOMAIN_TABLES` (runner.py:42-54).

**Step 3: verificar** — `uv run pytest tests/test_db_connection.py tests/test_database.py -q` (init_db en tmp aplica v015).

**Step 4: commit** — `feat: migración v015 splits`

---

## Task 2: Modelos tipados (`src/models.py`)

**Files:** Modify `src/models.py` (después de `Template`, ~línea 70)

```python
SPLIT_DAYS = ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO")


@dataclass(frozen=True)
class SplitItemInput:
    dia: str
    item_type: str = "ejercicio"
    ejercicio: str = ""


@dataclass(frozen=True)
class SplitInput:
    nombre: str
    items: list[SplitItemInput] = field(default_factory=list)


@dataclass(frozen=True)
class SplitItem:
    id: int
    dia: str
    orden: int
    item_type: str
    ejercicio: str
    grupo_muscular: str


@dataclass(frozen=True)
class Split:
    id: int
    nombre: str
    updated_at: str
    items: list[SplitItem] = field(default_factory=list)
    updated: bool = False


@dataclass(frozen=True)
class SplitDaySummary:
    dia: str
    series: int
    by_exercise: dict[str, int]
    by_group: dict[str, int]


@dataclass(frozen=True)
class SplitMetrics:
    total_instances: int
    total_series: int
    active_days: int
    distinct_exercises: int
    by_group: dict[str, int]
    by_exercise: dict[str, int]
    days: list[SplitDaySummary]
```

**Step:** `uv run mypy src/models.py` → commit `feat: modelos de dominio de splits`

---

## Task 3: Capa SQL (`src/database.py`)

**Files:** Modify `src/database.py` (tras las funciones de plantillas, ~línea 300)

Funciones (todas con `read_connection`/`transaction`, SQL parametrizado):

- `get_split_catalog(db_path) -> list[dict]` → `SELECT ejercicio, grupo_muscular, categoria FROM ejercicios ORDER BY grupo_muscular, ejercicio` (catálogo agrupado para el board)
- `get_splits_summary(db_path) -> list[dict]` → splits + conteos (join items: series por split, días activos, grupos usados `GROUP_CONCAT(DISTINCT grupo_muscular)`)
- `get_split(db_path, split_id) -> dict | None` → split + items `ORDER BY dia_idx, orden` (índice de `DIA_MAP`)
- `find_split_by_nombre(db_path, nombre) -> int | None` → `WHERE LOWER(nombre) = LOWER(?)` (mismo patrón que `find_plantilla_by_nombre`, database.py:192)
- `insert_split(db_path, nombre, items: list[tuple]) -> int` → transaction: insert split + items (dia, orden 1..n, item_type, ejercicio, grupo_muscular)
- `update_split(db_path, split_id, nombre, items) -> None` → transaction: update nombre/updated_at, `DELETE FROM training_split_items WHERE split_id=?`, re-insert
- `delete_split(db_path, split_id) -> None` → transaction (CASCADE borra items)
- `snapshot_splits(db_path) -> list` / `restore_splits(db_path, snapshot) -> None` → mismo patrón que `snapshot_entrenos`/`restore_entrenos` (database.py:250-298), con `_resync_sequence(conn, "training_splits")`

**Tests** (en `tests/test_database.py`, fixture `db` con `init_db`): insert/get/update/delete, orden por día conservado, snapshot→restore idempotente, CASCADE (borrar split borra items).

**Step:** `uv run pytest tests/test_database.py -q` → commit `feat: SQL de splits en database.py`

---

## Task 4: Servicio de dominio (`src/split_service.py`)

**Files:** Create `src/split_service.py`; Test: `tests/test_split_service.py`

Contrato público: `save_split(db_path, split_input: SplitInput, split_id: int | None = None) -> Split`, `delete_split(db_path, split_id) -> None`, `compute_split_metrics(items) -> SplitMetrics`, `get_split_board(db_path, split_id) -> dict` (split + metrics), constantes HIIT y `DIA_MAP` importado de `training_service`.

**Validación (borde, server-authoritative):**

```python
def _normalize_item(
    item: SplitItemInput, catalog_lower: dict[str, str]
) -> tuple[str, str, str, str]:
    dia = str(item.dia).strip().upper()
    if dia not in SPLIT_DAYS:
        raise ValidationError("Día inválido en el split.")
    if item.item_type == "hiit":
        if str(item.ejercicio).strip().upper() != HIIT_NAME:
            raise ValidationError("El elemento HIIT debe llamarse HIIT.")
        return dia, HIIT_ITEM_TYPE, HIIT_GROUP, HIIT_NAME
    nombre = str(item.ejercicio).strip()
    grupo = catalog_lower.get(nombre.lower())
    if not grupo:
        raise ValidationError("El ejercicio no existe en el catálogo.")
    return dia, "ejercicio", grupo, nombre
```

(no devolver valores del cliente en errores — mensaje seguro; `translate_error` ya lo maneja, dashboard_service.py:43.)

**save_split:** nombre vacío → `ValidationError("El nombre del split no puede estar vacío.")`; con `split_id` → `ConflictError` si nombre duplicado de otro split; sin `split_id` → `find_split_by_nombre`, si existe actualiza (`updated=True`), si no inserta. **Al menos 1 item** → `ValidationError` (un split sin ejercicios no tiene sentido; decisión alineada con `save_template`).

**compute_split_metrics:** 1 item = 1 serie. Por día: `series=len(items)` + `by_exercise` + `by_group` (dicts count). Semanales: `total_instances`/`total_series` (suma), `active_days` (días con ≥1), `distinct_exercises` (nombres únicos, incl. HIIT), `by_group`/`by_exercise` globales. `days` en orden `SPLIT_DAYS` solo con items.

**Tests (tests/test_split_service.py)** — cada uno TDD:

1. `test_save_split_crea`
2. `test_rechaza_nombre_vacio`
3. `test_nombre_duplicado_case_insensitive` (guardar "Push Pull Legs" y "push pull legs" → actualiza, no crea; con split_id ajeno → ConflictError)
4. `test_ejercicio_repetido_mismo_dia_se_conserva` (2× Curl Lunes → 2 items, órdenes 1,2)
5. `test_guarda_hiit`
6. `test_rechaza_ejercicio_inexistente`
7. `test_rechaza_dia_invalido`
8. `test_conserva_orden_por_dia`
9-12. métricas: por día / por ejercicio / por grupo / total semanal
13. `test_eliminar_split_cascade`

**Step:** `uv run pytest tests/test_split_service.py -q --cov=src.split_service --cov-branch --cov-fail-under=90` → commit `feat: split_service con métricas autoritativas`

---

## Task 5: Integración undo (`src/mutation_service.py`)

**Files:** Modify `src/mutation_service.py`

```python
def save_split_with_undo_snapshot(db_path, split_id, split_input) -> Split:
    before = snapshot_splits(db_path)
    backup_or_raise(db_path)
    result = save_split(db_path, split_input, split_id)
    _journal(db_path, "splits", {"before": _rows_to_dicts(before)})
    return result


def delete_split_with_undo_snapshot(db_path, split_id) -> None:
    before = snapshot_splits(db_path)
    backup_or_raise(db_path)
    delete_split(db_path, split_id)
    _journal(db_path, "splits", {"before": _rows_to_dicts(before)})
```

En `undo_last_action` (antes del fallback `restore_entrenos`, línea 240):

```python
if entry["kind"] == "splits":
    restore_splits(db_path, entry["before"])
    _pop_top(db_path)
    return {"kind": "splits"}
```

**Tests** (en `tests/test_mutation_service.py`): save→undo restaura, delete→undo restaura, undo stack ≤10, pop solo tras restore exitoso.

**Step:** `uv run pytest tests/test_mutation_service.py -q` → commit `feat: undo de splits`

---

## Task 6: OOB targets (`src/response_fragments.py`)

**Files:** Modify `src/response_fragments.py:19-33` — añadir `"splits-section", "split-board"` a `OOB_FRAGMENT_TARGETS`. Test en `test_app.py` (o `test_contract_fixtures.py`): `fragment_oob` con los nuevos targets no lanza `ValueError`.

**Step:** commit `feat: OOB targets de splits`

---

## Task 7: Rutas y handlers (`app.py`)

**Files:** Modify `app.py` (imports línea 29-91, constantes ~118, helpers ~300, rutas tras `/plantillas` ~924)

1. `MAX_SPLIT_ITEMS = 300` junto a `MAX_REORDER_IDS`.
2. Helpers delgados de render (patrón `_plantillas_list_html`, app.py:300):
   - `_split_board_html(request, split_id | None)` → `split_board.html` (catálogo + board + métricas; con split cargado o vacío)
   - `_split_list_html(request, *, editing_id=None, error=None)` → `split_list.html`
   - `_split_page_html(request, abrir_id | None)` → `splits.html` completo
3. Rutas:

```python
@app.get("/splits", response_class=HTMLResponse)
def splits_view(request: Request, abrir: int | None = Query(None)):
    return HTMLResponse(content=_split_page_html(request, abrir))


@app.get("/split/{split_id}", response_class=HTMLResponse)
def split_get(request: Request, split_id: int):
    try:
        board = get_split_board(DB_PATH, split_id)   # NotFoundError si no existe
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content=fragment_oob(templates, request, "split-board", _board_html(request, board), swap="innerHTML"))


@app.post("/split/guardar", response_class=HTMLResponse)
def split_guardar(request: Request, split_id: int | None = Form(None), nombre: str = Form(...),
                  dia: list[str] = Form(default=[]), item_type: list[str] = Form(default=[]),
                  ejercicio: list[str] = Form(default=[])):
    try:
        _check_lote(dia, MAX_SPLIT_ITEMS, "elementos")
        if not (len(dia) == len(item_type) == len(ejercicio)):
            raise ValidationError("Datos incompletos del split.")
        result = save_split_with_undo_snapshot(
            DB_PATH, split_id,
            SplitInput(nombre=nombre, items=[
                SplitItemInput(dia=d, item_type=t, ejercicio=e)
                for d, t, e in zip(dia, item_type, ejercicio)
            ]),
        )
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    msg = "Split actualizado." if result.updated else "Split guardado."
    return HTMLResponse(content=notice_oob(...message=msg)
        + fragment_oob(templates, request, "splits-section", _split_list_html(request), swap="outerHTML")
        + fragment_oob(templates, request, "split-board",
                       _board_html(request, get_split_board(DB_PATH, result.id)), swap="innerHTML"))


@app.post("/split/eliminar/{split_id}", response_class=HTMLResponse)
def split_eliminar(request: Request, split_id: int):
    try:
        delete_split_with_undo_snapshot(DB_PATH, split_id)
    except Exception as e:
        return _domain_error_response(request, e, "notice-container")
    return HTMLResponse(content=notice_oob(... "Split eliminado.")
        + fragment_oob(templates, request, "splits-section", _split_list_html(request), swap="outerHTML")
        + fragment_oob(templates, request, "split-board", _split_board_html(request, None), swap="innerHTML"))
```

4. `/undo` (app.py:931): rama `if result["kind"] == "splits":` → notice_ok + `fragment_oob("splits-section", _split_list_html(request), swap="outerHTML")` (patrón exacto de `test_undo_entrenos_oob_plantillas`).

**Tests (tests/test_split_routes.py, nuevo; fixture `_client`/`_setup_db` copiados de test_app.py:11-20):**

- `GET /splits` 200, contiene catálogo (con `insert_exercise`), botón HIIT, 7 zonas `[data-day="LUNES"]`, `#splits-section`
- `GET /splits?abrir={id}` renderiza items del split
- `POST /split/guardar` crea + OOB `splits-section` y `split-board`; mismo nombre → actualiza; sin token → 403 (CSRF); con Origin cruzado → 403; `dia` inválido → 400 notice-error; ejercicio inexistente → 400; HIIT ok
- `POST /split/eliminar/{id}` + confirmación en cliente; ids inválidos (negativos) → 400
- Aislamiento: 2 splits con ítems distintos no se contaminan
- Undo: guardar → `/undo` → `splits-section` OOB con estado anterior
- `GET /split/999` → 400 "no existe"

**Step:** `uv run pytest tests/test_split_routes.py -q` → commit `feat: rutas de splits con CSRF y undo`

---

## Task 8: Templates

**Files:**
- Create `templates/splits.html` (extiende `base.html`)
- Create `templates/partials/split_board.html` (catálogo + 7 zonas + métricas)
- Create `templates/partials/split_list.html`
- Modify `templates/index.html:8-11` — link nav "Splits" (`<a href="/splits" class="btn btn-outline">Splits</a>` junto a Exportar CSV)

**`splits.html`** (estructura, layout de página con `max-w-7xl mx-auto px-4 py-8 flex flex-col gap-8`):

- Header: título + link "← Dashboard" + botón "Nuevo split" (`data-action="split-new"`) + form nombre (`field-input`) + "Guardar" (`data-action="split-save"`, `btn btn-primary`) — form único `id="split-save-form"` con `hx-post="/split/guardar" hx-swap="none"` y hidden `name="split_id"` + inputs hidden arrays (JS los sincroniza; mismo patrón que `syncTemplateEjercicios` en templates.js:84-100)
- `#splits-catalog`: partial catálogo — botones `draggable="true"` con `data-action="split-add-item"` (alternativa accesible: añade al día seleccionado), `data-ejercicio`, `data-grupo`, `data-item-type`; el botón HIIT exacto con `data-item-type="hiit"`; input `data-action="split-catalog-search"` (filtro client-side por nombre, `aria-label="Buscar ejercicio"`); agrupado por grupo muscular
- `#split-board` (OOB): 7 columnas `.split-day-zone` con `data-day="LUNES"`…`data-day="DOMINGO"`, header de día seleccionable (`data-action="split-day-select"`, `aria-pressed`), contador de series server-rendered, placeholder vacío "Suelta ejercicios aquí", items `.split-item-card` con `data-split-item-id`, nombre, chip de grupo, botón − (`data-action="split-item-remove"`, `aria-label`); panel métricas semanales (totales + por grupo + por ejercicio) — todo server-rendered
- `#splits-section` (OOB): lista de splits guardados `.split-card` con nombre, `updated_at`, series totales, días activos, grupos usados, botones Abrir (`data-action="split-open"`), Eliminar (`data-action="split-delete"` con `data-split-nombre` → confirm modal existente `#confirm-modal`); estado vacío "Aún no hay splits guardados"
- Estados: `htmx-indicator` en board; `<noscript>` heredado de base; errores vía `notice-container` (ya en base.html)

Reglas de oro: solo componentes canónicos (`panel`, `panel-title`, `btn*`, `card`, `field-input`, `cell-*`), cero utilidades de color inline, cero hex, atributos ARIA (`aria-pressed`, `aria-label`, `role="list"` en zonas).

**Step:** `uv run python scripts/audit_consistency.py` pasa (tras Task 9) → commit `feat: templates de splits`

---

## Task 9: CSS canónico (`static/css/components.css`)

**Files:** Modify `static/css/components.css`; Modify `scripts/audit_consistency.py:39-83` (`COMPONENT_CLASSES`)

Nuevas clases (solo tokens `var(--t-*)`, `border-radius 8px`, fonts heredadas):

- `.split-columns` — grid 7 columnas desktop / 1 columna mobile (`@media (max-width: 1024px)`)
- `.split-day-zone` — fondo `var(--t-overlay-white-004)`, borde `var(--t-surfaces-neutral-800)`, `min-height`, estado `.drop-target` (borde `var(--t-burgundy-600)` + glow — estado visual del destino durante arrastre)
- `.split-day-header` — título uppercase 12px `var(--t-burgundy-400)`
- `.split-catalog-chip` — botón catálogo (`var(--t-overlay-white-004)` bg, hover `var(--t-burgundy-600)` border)
- `.split-item-card` — item con drag handle visual (cursor grab), borde neutral, hover
- `.split-metric` — celdas métricas con `var(--t-surfaces-neutral-400)`
- `.split-empty` — placeholder zona vacía

Añadir las 7 clases a `COMPONENT_CLASSES` (si no, `audit_component_coverage` falla por "sin uso ni alias"). Orden: añadir clases Y usarlas en templates, luego correr el gate.

**Step:** `uv run pytest tests/test_ui_consistency.py tests/test_static_assets.py -q` → commit

---

## Task 10: Módulo JS `static/js/splits.js`

**Files:** Create `static/js/splits.js`; Modify `static/js/app.js` (import + `initSplits()` en DOMContentLoaded, línea 47-67)

**Public API:** `initSplits()` — listeners delegados `data-action` (sin handlers inline, contrato v3):

- `split-day-select` → marca día activo (clase visual + `aria-pressed`), persiste en estado módulo
- `split-add-item` → clona tarjeta de instancia al día activo (alternativa accesible al drag; en catálogo tarjeta no-drag)
- `split-item-remove` → elimina instancia + refresh de preview métricas
- `split-open` → `htmx.ajax('GET', /split/{id}')` (board) + `split/lista` (ya OOB)
- `split-delete` → `showConfirmDialog` (`#confirm-msg` "¿Eliminar el split "X"?") → `htmx.ajax('POST', /split/eliminar/{id})`
- `split-new` → limpia board (hidden split_id vacío, nombre limpio, focus en nombre)
- `split-save` → valida nombre no vacío → `syncSplitItems()` (hidden inputs) → `form.requestSubmit()`
- `split-catalog-search` → filtra `.split-catalog-chip` por texto (input event)

**DnD nativo (patrón `initEntrenoDnD`, templates.js:259-360):**

- Catálogo: `dragstart` → `dataTransfer.setData('text/plain', 'cat:' + ejercicio + '|' + item_type)` + `effectAllowed='copy'` + ghost; el original permanece
- Zonas día: `dragover` → `preventDefault` + `.drop-target` class; `drop` → crea instancia (clon JS) al final del día + preview métricas + dirty flag
- Reorden dentro del día: patrón `getDragAfterElement` (templates.js:223-231) con items `[data-split-item-id]`; `dragend` limpia estado
- Métricas preview client-side: recomputa counts por día/ejercicio/grupo en un `#split-metrics-preview` (NUNCA enviadas al servidor; el board real se re-renderiza tras guardar)
- `htmx:afterRequest` para `/undo` → si `#split-board` existe, refetch `GET /split/{current}` (split abierto) — recupera estado tras undo
- `htmx:afterSwap` (board) → re-engancha DnD y `dragend` cleanup; `prefers-reduced-motion`: la clase `.drop-target` es estática (sin animación), no requiere media query adicional
- UIDs de instancia: contador módulo `splitItemUid` (`data-split-item-id="ui-1"`…) — instancias distintas aunque el nombre se repita

**Step:** `uv run pytest tests/test_frontend_budget.py -q` (JS agregado ≤64 KiB individual, 160 KiB agregado) → commit

---

## Task 11: Recompilar Tailwind

**Step:** `./scripts/build_css.sh` (si se tocaron clases Tailwind utilitarias en templates — las nuevas clases son propias de components.css, pero el header/nav y grid reutilizan utilitarios ya compilados; recompilar igualmente por seguridad). Verificar `git diff --stat static/css/tailwind.css`.

---

## Task 12: Tests de integración E2E (Playwright)

**Files:** Create `tests/e2e/test_splits_flow.py` (reutiliza fixture `server`/`page` de conftest.py:39-82, que ya siembra "Press" y "Curl"; para fidelidad al ejemplo añadir en conftest `insert_exercise(db, "Curl de bíceps", "Biceps", "TIRON")`)

Reutilizar `_simulate_drag` (test_dashboard_flow.py:50-63) — el DnD nativo responde a DragEvent sintéticos:

1. `test_splits_page_loads` — `page.goto(server + "/splits")`, espera `body.dataset.appReady === '1'`, catálogo visible, botón HIIT, 7 zonas
2. `test_drag_repetido_cuenta_series` — drag "Curl de bíceps" → LUNES; repetir; `#split-board [data-day="LUNES"] .split-item-card` count == 2; preview muestra "2 series"; drag HIIT → MARTES
3. `test_reordenar_y_eliminar` — drag 2 items, reordenar (drag item a posición), eliminar 1, counts actualizan
4. `test_guardar_recargar_abrir_conserva_estado` — armar LUNES [Curl, Curl], MARTES [HIIT]; guardar (nombre "Push Pull Legs"); `page.reload()`; abrir desde lista; verificar exactamente 2 items Curl en LUNES en orden, 1 HIIT en MARTES, resumen "5 series"
5. Accesibilidad: `page.get_by_role('button', name='Agregar')` (alternativa no-drag) añade instancia al día seleccionado

**Step:** `uv run pytest tests/e2e/test_splits_flow.py -q --no-cov` → commit

---

## Task 13: Documentación

**Files:** Modify `docs/architecture/current-ui-contract.md` (nuevo contrato splits: rutas, OOB targets, data-actions, formato de submit), Modify `AGENTS.md` (§4 tablas nuevas, §5 rutas nuevas — corrige drift señalado en forense), opcional: `scripts/audit_ui.py` marcadores de `/splits`.

---

## Task 14: Puertas finales (orden exacto)

```bash
uv sync --locked
uv run pytest --ignore=tests/e2e                      # gate cobertura 90% branch global
uv run pytest tests/e2e -q --no-cov
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
uv run python scripts/check_module_coverage.py src/split_service.py src/database.py src/mutation_service.py --min 90
./scripts/build_css.sh
uv run python scripts/audit_consistency.py
uv run python scripts/audit_ui.py --db .tmp/audit/lifestyle.db  # opcional, verifica la página nueva
```

**Criterio de aceptación #16 (no romper lo existente):** los tests completos de app/plantillas/nutrición/cardio/sync corren verdes.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `audit_component_coverage` falla con clases nuevas sin usar | Registrar en `COMPONENT_CLASSES` al mismo tiempo que se crean; correr gate en Task 9 |
| DnD nativo no dispara en e2e | Mismo patrón `_simulate_drag` ya probado en `test_dashboard_flow.py` (funciona con DragEvent sintéticos) |
| Undo global refresca board equivocado | JS refetch condicionado a presencia de `#split-board` y a `htmx:afterRequest` de `/undo` |
| Cobertura de `database.py` cae por funciones nuevas | Tests unitarios por función en `test_database.py` (Task 3) |
| UNIQUE `(split_id, dia, orden)` en guardado | Server renumera siempre desde 1 → nunca choca; test de orden lo verifica |
| Frontend budget JS | `splits.js` objetivo <15 KiB (presupuesto: 64 KiB/160 KiB actuales ~132 KiB) |
