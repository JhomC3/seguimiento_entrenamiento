# Plan maestro: factorización de archivos en todo el proyecto

**Ruta:** `docs/plans/codebase-factorization-plan.md`
**Fecha:** 2026-08-18
**Tipo:** roadmap de refactorización estructural, **sin cambios de comportamiento** en ninguna fase. Cada fase es un plan atómico ejecutable (o remite a uno existente).

## 1. Estado del plan

`PAUSADA` — roadmap estructural subordinado al [`MASTER-PLAN.md`](MASTER-PLAN.md). No se ejecutan
sus fases mientras el dashboard tenga cambios funcionales sin consolidar. La Fase 1 tiene el plan
atómico `app-router-modularization.md`; las Fases 2–3 y las fases condicionales esperan sus
dependencias explícitas.

## 2. Objetivo

Factorizar los archivos que mezclan responsabilidades o que por tamaño comprometen la revisión y la evolución del código, con criterios explícitos de necesidad (no por conteo de líneas), conservando el comportamiento congelado por la suite existente (~560 tests unit/integración + 83 e2e) y sin tocar URLs, HTML ni contrato OOB.

## 3. Criterios de necesidad (vinculantes para veredictos)

- **C1 — Mezcla de responsabilidades:** un archivo agrupa dominios distintos (rutas de varios features, capas distintas, concerns no relacionados) → **factorizar**.
- **C2 — Masa cohesiva con dolor:** archivo >800 líneas de una sola responsabilidad → **candidato** si sufre churn previsto o sus diffs ya son difíciles de revisar.
- **C3 — Tests espejo:** un archivo de tests solo se divide cuando se divide su sujeto (movimiento mecánico, sin tocar aserciones).
- **C4 — Líneas solas no bastan:** un archivo cohesivo de <500 líneas con churn bajo → **no factorizar** (el split sería ruido).
- **C5 — Presupuestos intactos:** ningún split puede violar `tests/test_frontend_budget.py` (JS: 64 KB individual / 160 KB agregado) ni añadir dependencias.

## 4. Inventario exhaustivo del proyecto (archivos >250 líneas, veredicto)

### 4.1 Backend Python

| Archivo | Líneas | Veredicto |
|---|---|---|
| `app.py` | 1.426 | **Fase 1** — C1: mezcla 10 responsabilidades + SQL inline. Plan: `app-router-modularization.md`. |
| `src/database.py` | 849 | **Fase 2** — C1/C2: 4 dominios en un archivo (catálogos/entrenamiento, plantillas, nutrición, splits). |
| `src/charts.py` | 581 | **Fase 4 condicional** — cohesivo (figuras Plotly), pero Recuperaciones 1-3 lo tocarán; split solo después, si sigue doliendo. |
| `src/parser.py` | 448 | No (C4): parsers cohesivos por hoja CSV, churn bajo. |
| `src/dashboard_service.py` | 382 | No (C4): una sola capa (view models + shell). |
| `src/mutation_service.py` | 275 | No (C4): un solo patrón (snapshot→backup→write→undo). |
| `src/models.py` (236), `src/nutrition_service.py` (226), `src/health_sync_service.py` (224), `src/security.py` (202) | <250 c/u | No (C4). |

### 4.2 Frontend JS

| Archivo | Líneas | Veredicto |
|---|---|---|
| `static/js/splits.js` | 1.110 | **Fase 3** — C2: ~55 funciones en 6 concerns (estado, drag&drop, resúmenes, form-sync, bridge htmx, init de 177 l). Feature estable (`/splits`), sin churn previsto → seguro split. |
| `static/js/nutrition-editor.js` | 420 | No (C4): feature única, bajo el umbral. |
| `static/js/templates.js` (361), `editor.js` (306), `level-cascade.js` (271) | <400 c/u | No ahora (C4). `level-cascade.js` será tocado por Recuperación 1 — revisar tamaño tras ese churn. |
| `static/js/htmx-lifecycle.js` | 219 | No (C4). |

### 4.3 Tests

| Archivo | Líneas | Veredicto |
|---|---|---|
| `tests/test_app.py` | 1.935 | **Fase 1 (F8 de su plan)** — C3: espejo de `app.py`; split mecánico por router, 125 tests, 0 aserciones tocadas. |
| `tests/test_database.py` | 1.286 | **Fase 2** — C3: espejo de `database.py`; split mecánico junto al sujeto (56 tests). |
| `tests/e2e/test_dashboard_flow.py` | 1.280 | **Fase 5 condicional** — C3: espejo del dashboard; la cola de Recuperaciones lo reescribirá parcialmente. Split solo cuando el dashboard estabilice. |
| `tests/e2e/test_splits_flow.py` (948), `test_security.py` (849), `test_parser.py` (556), `test_training_service.py` (383), `test_split_routes.py` (349), `test_charts.py` (314) | <1.000 c/u | No (C3): sus sujetos no se dividen o ya se dividieron (`test_split_routes.py` se fusiona en Fase 1-F8). |

### 4.4 Scripts, Android, templates, migraciones

| Archivo | Líneas | Veredicto |
|---|---|---|
| `scripts/audit_ui.py` | 639 | No (C4): herramienta de una responsabilidad (barrido Playwright); `audit_routes` es larga pero secuencial y aislada. |
| `android/.../HealthRepository.kt` | 645 | No (C4): mayor archivo Kotlin, cohesivo (Changes API + outbox), con su suite de tests propia. |
| `templates/nutrition_editor.html` (262) y demás templates | <265 | No (C4): fragmentos por feature, tamaño sano. |
| `src/migrations/*`, `scripts/import_*` | <200 c/u | No (C4). |

**Observación (drift documentado, fuera de alcance):** el estándar dice "SQL solo en `database.py`", pero hay 38+ llamadas `conn.execute`/`read_sql` en servicios de dominio (`mutation_service` 7, `charts` 6, `cardio_service` 6, `dashboard_service` 5, `training_service` 4, `health_sync_service` 4…). Es un patrón estable y testeado; la consolidación masiva sería churn de alto riesgo y cero valor de comportamiento. Este plan **no** la incluye. Lo único que se corrige es el SQL de la capa web (`app.py`) en la Fase 1 (decisión D3 de su plan).

## 5. Fases

### Fase 1 — `app.py` → `src/web/` routers

**Especificación completa:** `docs/plans/app-router-modularization.md` (no se duplica aquí). Incluye el split de `tests/test_app.py`. **Condición de ejecución:** antes de continuar las Recuperaciones 2-5 del dashboard.

### Fase 2 — `src/database.py` → paquete `src/db/` con fachada

**Qué:** dividir por dominio usando las fronteras ya rotuladas en el archivo (separadores en las líneas 341, 522, 617), dejando `database.py` como fachada que re-exporta → **cero cambios** en los ~20 importadores (8 servicios, `app.py`/`src/web`, 3 scripts, tests).

```text
src/db/
├── __init__.py
├── core.py        (~90 l:  init_db, backup_db, _resync_sequence, load_ejercicios,
│                   load_training_data — carga/mantenimiento)
├── training.py    (~250 l: catálogos y series — get_categories, get_exercises_catalog,
│                   insert_exercise, get_sets_by_fecha, get_session_sets,
│                   delete_session_by_fecha, get_ejercicio_categoria,
│                   get_last_session_sets, snapshot/restore_entrenos)
├── templates.py   (~110 l: plantillas de entreno — get/insert/update/delete/reorder,
│                   find_plantilla_by_nombre, _plantilla_sets)
├── nutrition.py   (~280 l: alimentos, diario, parámetros y plantillas de comida)
└── splits.py      (~230 l: catálogos de splits/dashboard, CRUD de splits, snapshots)
```

`src/database.py` queda como fachada explícita (`from src.db.training import get_categories, ...` — sin `import *`), documentando en su cabecera que es la fachada histórica de compatibilidad.

**Tests (C3):** `tests/test_database.py` (1.286 l, 56 tests) → `tests/test_db_core.py`, `test_db_training.py`, `test_db_nutrition.py`, `test_db_splits.py` por movimiento mecánico. `from src.database import X` sigue siendo la vía canónica (los tests siguen usándola — verifica la fachada).

**Config:** añadir `"src/db/*" = ["DTZ005", "DTZ007", "DTZ011"]` a per-file-ignores de `pyproject.toml` (hereda la justificación naive-dates de `src/database.py`). mypy/cobertura ya cubren `src/`.

**Orden atómico:** F2.1 crear paquete + mover `core.py`+`training.py` + fachada → suite verde → F2.2 `nutrition.py` → F2.3 `templates.py`+`splits.py` → F2.4 split de tests espejo → F2.5 `AGENTS.md` §3 + gates completos.

**Aceptación:** `grep -c "def " src/database.py` → solo re-exports (0 defs propias salvo docstring); suite verde; diff sin cambios fuera de `src/db/`, `src/database.py`, `tests/test_db_*.py`, `pyproject.toml`, `AGENTS.md`; greps de imports intactos.

### Fase 3 — `static/js/splits.js` → módulos ES `static/js/splits/`

**Qué:** separar los 6 concerns observados (líneas y funciones verificadas):

```text
static/js/splits/
├── state.js         (estado por item, itemKey, ensureItemState, canEdit, límites,
│                    guardLimit, refreshCatalogDisabled — ~150 l)
├── dnd.js           (buildBoardSortable/buildCatalogSortable, onItemShift*, onDayHeader*,
│                    dayInsertionAnchor, insertCardsAt, bindDropGuards, paintDropTarget — ~300 l)
├── summaries.js     (finalizeCard, createCardFromChip, tally, rebuildDaySummary,
│                    updatePreview, rebuildStrip, toggleSummaryGroup — ~250 l)
├── form.js          (syncSplitForm, splitDelete, splitDayClear, addItemToDay,
│                    applyEditMode/setEditMode/markDirty — ~200 l)
├── htmx-bridge.js   (processHtmx, snapshotBeforeMutation, applyStateToElement,
│                    restoreAfterSectionSwap, reconcileState — ~200 l)
└── index.js         (initSplits + reinitAll + safeInitCatalog, re-exportado — ~230 l)
```

`static/js/app.js` cambia `import { initSplits } from './splits.js'` → `'./splits/index.js'`. El estado mutable compartido (`state`) vive en `state.js` y se importa donde se usa (mismo objeto en memoria — sin cambio semántico).

**Congelado:** `tests/e2e/test_splits_flow.py` (29 tests) + `scripts/audit_ui.py` (barre `/splits`) sin modificación.

**Presupuesto (C5):** el agregado sube ≤2 KB (sintaxis de `import`/`export`); cada archivo muy por debajo de 64 KB. `test_frontend_budget.py` debe seguir verde sin ajustar constantes.

**Aceptación:** `static/js/splits.js` eliminado; sin `window.*` nuevo (sin puente global); e2e de splits + auditoría UI verdes; presupuesto intacto.

### Fase 4 (condicional) — `src/charts.py`

**Condición:** tras completar Recuperación 2-3 del dashboard (granularidad + periodos tocarán `chart_selection` y `period_summary`). Si al terminar el archivo sigue >500 l o mezcla agregación de datos con construcción de figuras, separar `charts/data.py` (DataFrames/agregaciones) de `charts/figures.py` (Plotly go.Figure/estilos), con `charts.py` como fachada. No antes: sería churn sobre churn.

### Fase 5 (condicional) — `tests/e2e/test_dashboard_flow.py`

**Condición:** dashboard estabilizado (cola del gap-doc cerrada). Split mecánico por feature (cascada, gráfica, detalle, popup/registro, accesibilidad-móvil ya vive aparte). No antes: la Recuperación 1 reescribe buena parte de estos tests.

## 6. Secuenciación respecto a la cola del dashboard

```text
[Fase 1 app.py] → [Recuperación 1 (dashboard vertical)] → [Fase 2 database.py] →
[Recuperación 2-3 (catálogo/granularidad)] → [Fase 3 splits.js] →
[Recuperación 4-5 (registro/popup)] → [Fase 4 charts.py?] → [Fase 5 e2e dashboard?]
```

Regla: las Fases 2 y 3 no tocan archivos de la cola del dashboard (`dashboard_routes.py`, `charts.py`, `level-cascade.js`, `chart-interaction.js`, templates del dashboard) — pueden adelantarse o retrasarse sin conflicto. Fases 1, 4 y 5 sí tienen dependencia explícita con la cola.

## 7. Riesgos transversales y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Mezclar factorización con funcionalidad | Cada fase exige working tree limpio y commits atómicos por sub-paso; diff limitado a los archivos de la fase |
| Split de JS rompe identidad de estado compartido | `state` como módulo único importado (misma referencia); e2e de splits congelado |
| Fachada incompleta rompe importadores | La suite cubre los ~20 importadores; grep de imports rotos en cada sub-paso |
| Presupuesto frontend excedido | C5: `test_frontend_budget.py` en cada commit de Fase 3 |
| Drift documental | `AGENTS.md` §3 se actualiza en cada fase (obligación del estándar) |
| Refactor sobre código a punto de churn | Regla de §6: fases con dependencia explícita esperan su condición |

## 8. Gates comunes a cada fase

```bash
UV_CACHE_DIR=.tmp/uv-cache uv sync --locked
UV_CACHE_DIR=.tmp/uv-cache uv run pytest --ignore=tests/e2e       # cobertura ≥90 (gate addopts)
UV_CACHE_DIR=.tmp/uv-cache uv run pytest tests/e2e -q --no-cov
UV_CACHE_DIR=.tmp/uv-cache uv run ruff format --check .
UV_CACHE_DIR=.tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=.tmp/uv-cache uv run mypy app.py src tests
```

Fase 3 añade: `uv run python scripts/audit_ui.py` (copia de la DB real). Fases con CSS: `./scripts/build_css.sh` (no previsto en ninguna fase).

## 9. Criterios de aceptación globales

1. Ninguna fase cambia URLs, HTML servido, contrato OOB ni comportamiento observable (los tests existentes pasan sin tocar aserciones).
2. Los archivos "No" del inventario §4 permanecen intactos (verificable por ruta en el diff de cada fase).
3. Tras cada fase: suite completa + gates estáticos verdes (§8).
4. `AGENTS.md` §3 refleja la estructura vigente al cierre de cada fase.
5. Sin dependencias nuevas, sin migraciones, sin `window.*` nuevo, sin `import *`.
