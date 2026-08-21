# Plan: Modularización de `app.py` en routers (`src/web/`)

**Ruta:** `docs/plans/app-router-modularization.md`
**Fecha:** 2026-08-18
**Tipo:** refactorización estructural, **sin cambios de comportamiento** (mismas URLs, mismo HTML, mismo contrato OOB).

## 1. Estado del plan

`pendiente` — documento de diseño para implementación por un agente. No se implementa código en este plan.

**Supuesto crítico:** el working tree de `feat/dashboard-ui-ux` tiene cambios sin commitear (rediseño del dashboard, Recuperación 1 parcial). Este plan exige partir de un **árbol limpio y suite verde** (F0); no se mezcla con funcionalidad nueva. Este plan se ejecuta **antes** de continuar con las Recuperaciones 2-5 del gap-doc: acumular dashboard sobre un `app.py` de ~1.400 líneas multiplica el riesgo de duplicar lógica, romper OOB y esconder errores.

## 2. Objetivo

Reducir `app.py` (1.426 líneas, 34 rutas + mount) a un módulo de composición (~150–250 líneas) moviendo las rutas a routers `APIRouter` por responsabilidad bajo `src/web/`, extrayendo los helpers de renderizado y la configuración de runtime a módulos compartidos, y emigrando el SQL inline a `src/database.py`. Cero cambios observables de comportamiento.

## 3. Contexto y problema

`app.py` mezcla diez responsabilidades: inicialización de FastAPI y middleware, rutas del dashboard, registro diario, alimentación, plantillas, splits, Health Connect, renderizado de fragmentos HTML, preparación de datos y manejo de errores. Además contiene **SQL inline** (violación directa de `docs/architecture/backend-standards.md`: "SQL fuera de `database.py`" está prohibido).

## 4. Evidencia del estado actual (working tree, 2026-08-18)

**E1 — Tamaño y mezcla.** `app.py` = 1.426 líneas: imports (1–105), `lifespan` (108–128), límites + `_check_lote` (131–140), `RequestIdMiddleware` (143–183), creación de app + middlewares + mount + `templates` (186–196), `static_cache_policy` (199–214), helpers de render (220–503), rutas (506–1426).

**E2 — SQL en `app.py` (prohibido por estándar).**
- `_cascade_items` ejecuta 5 consultas inline con `read_connection` (app.py:1199–1236).
- `export_health_connect_csv` monta el SELECT inline con `pd.read_sql_query` (app.py:1411–1420).
- `healthz` ejecuta `SELECT 1` (app.py:1180–1186) — aceptable como liveness, se deja como está.

**E3 — Huella de rutas (baseline a congelar).** 34 rutas + `MOUNT /static` = 35 entradas (volcado en §9.1). Un `git diff` de este plan no debe alterar esa lista.

**E4 — Acoplamiento de tests vía monkeypatch de módulo.**
- `monkeypatch.setattr(appmod, "DB_PATH", ...)`: **141 sitios** (`tests/test_app.py` 121, `tests/test_split_routes.py` 17, `test_security.py` / `test_logging_setup.py` / `test_static_assets.py` 1 c/u).
- `monkeypatch.setattr(appmod, "HC_SYNC_TOKEN", ...)`: **7 sitios** (`tests/test_app.py`).
- `from app import templates`: 3 sitios (`test_app.py:1611`, `test_security.py:543,558`).
- `TestClient(appmod.app)`: 8 sitios. `tests/e2e/conftest.py:16` usa `APP_MODULE = "app:app"`; `scripts/audit_ui.py:217` lanza `uvicorn app:app`.
- Consecuencia: `app.py` debe seguir exponiendo `app` y `templates`; la indirección de `DB_PATH`/`HC_SYNC_TOKEN` debe mantenerse **en un único módulo canónico leído en runtime** (ver D2).

**E5 — Gates que tocan `app.py`.** `pyproject.toml` per-file-ignores `"app.py" = ["B008", "BLE001", "S110", "DTZ005", "DTZ007", "DTZ011"]` (línea 37) — los routers heredan los mismos idioms (`Form(...)` en defaults, fechas locales ingenuas) y necesitan el mismo ignore bajo `src/web/*`. `mypy files = ["app.py", "src", "tests"]` y `--cov=src --cov=app` ya cubren `src/web/` sin cambios.

**E6 — `docs/architecture/current-ui-contract.md` no referencia `app.py`** (grep vacío): el contrato vive en rutas/IDs/OOB, no en ubicaciones de archivo. Solo `AGENTS.md` §3/§5 describe la estructura y debe actualizarse.

**E7 — Dead code candidato.** `_nutrition_fecha_display` (app.py:423–427) no tiene llamantes en `app.py` (`src/dashboard_service.py:306` tiene la versión usada). Verificar con grep en F8 y eliminar si sigue sin referencias.

**E8 — La suite existente es el congelado.** ~560 tests unit/integración + 83 e2e ya cubren las 34 rutas (contrato OOB, CSRF, tokens, undo). No se necesitan tests nuevos para congelar: se ejecutan como baseline y tras cada fase.

## 5. Estructura objetivo

```text
app.py                        (~170 l: lifespan, RequestIdMiddleware, middlewares, mount,
                               static_cache_policy, exception_handler, include_router ×8,
                               re-export de `templates`)
src/web/
├── __init__.py
├── dependencies.py           (~45 l: DB_PATH/HC_SYNC_TOKEN de runtime, CICLO_START_DATE,
│                               MAX_FORM_SETS/MAX_DIARY_ROWS/MAX_REORDER_IDS/MAX_NAME_LEN/
│                               MAX_SPLIT_ITEMS, check_lote)
├── render_helpers.py         (~300 l: instancia `templates` + todos los helpers *_html +
│                               NUTRIENT_FIELD_LABELS, _alimento_preview_map,
│                               _nutrition_app_config, _today_iso, _muscle_names,
│                               _chart_title, _render_body, _domain_error_response)
├── dashboard_routes.py       (~170 l: GET /, /nivel, /grafica, /semana/primer-entreno)
├── record_routes.py          (~240 l: GET /fecha/editor, /registro, /editor/popup, /cardio/day;
│                               POST /cardio/annotation, /entrenamiento/session/save,
│                               /entrenamiento/session/eliminar, /ejercicio/nuevo)
├── nutrition_routes.py       (~190 l: GET /alimentacion/editor, /alimentacion/plantilla/aplicar/{id};
│                               POST /alimentacion/save, /alimentacion/eliminar, /alimento/nuevo,
│                               /alimentacion/plantilla/guardar|eliminar/{id}|reordenar)
├── template_routes.py        (~110 l: GET /plantillas, /plantilla/aplicar/{id};
│                               POST /plantilla/guardar|editar/{id}|eliminar/{id}|reordenar)
├── split_routes.py           (~150 l: GET /splits, /split/nuevo;
│                               POST /split/guardar, /split/eliminar/{id})
├── sync_routes.py            (~100 l: POST /sync/health-connect, GET /exportar/health-connect.csv)
├── health_routes.py          (~25 l: GET /healthz)
└── undo_routes.py            (~75 l: POST /undo — cruza sesión/alimentación/splits/plantillas)
```

Distribución de las 34 rutas: dashboard 4, record 8, nutrition 7, template 6, split 4, sync 2, health 1, undo 1. (`/static` mount queda en `app.py`.)

## 6. Decisiones de diseño

- **D1 — Routers por responsabilidad, no por conteo.** Cada router agrupa un dominio de la UI. `undo_routes.py` se añade a la propuesta original porque `/undo` consume helpers de render de cuatro dominios (editor, nutrición, splits, plantillas) y no pertenece a ninguno.
- **D2 — Config de runtime en `dependencies.py`, leída como atributo de módulo.** Los routers hacen `from src.web import dependencies as deps` y referencian `deps.DB_PATH` / `deps.HC_SYNC_TOKEN` **dentro del cuerpo del handler** (nunca `from ... import DB_PATH`, que ligaría el valor en import y rompería el monkeypatch). Los 141+7 patches de tests cambian de target `appmod` → módulo `dependencies` (cambio mecánico, sin tocar aserciones). Alternativas descartadas: import perezoso de `app` dentro de los handlers (acoplamiento circular oculto); `dependency_overrides` de FastAPI (reescribe más tests y cambia el patrón del repo).
- **D3 — El SQL emigra a `src/database.py`.** Nuevas funciones con el mismo texto SQL: `get_cascade_items(db_path, nivel, foco)` (consolida las 5 consultas de `_cascade_items`) y `export_health_records(db_path, incluir_borrados) -> pd.DataFrame` (SELECT del CSV). `app.py`/routers quedan sin SQL (verificación por grep, §9.3).
- **D4 — Mover verbatim, sin renames.** Los helpers conservan sus nombres (incluido el prefijo `_`) en `render_helpers.py`. Un rename cosmético sería ruido de diff sin valor; si se desea, es un plan posterior.
- **D5 — `app.py` es solo composición.** Conserva: `lifespan`, `RequestIdMiddleware`, registro de middlewares (el orden no cambia), `app.mount("/static")`, `static_cache_policy`, `validation_error_handler` (usa `templates`), `include_router` ×8 y el re-export `from src.web.render_helpers import templates` (mantiene vivos los 3 `from app import templates` de tests — app.py lo usa legítimamente en el exception handler, sin F401).
- **D6 — `pyproject.toml`:** añadir `"src/web/*" = ["B008", "BLE001", "S110", "DTZ005", "DTZ007", "DTZ011"]` (mismos códigos y justificación que `app.py`). mypy/cobertura no requieren cambios (E5).
- **D7 — `render_helpers.py` único (~300 l, excepción al rango 100–250).** Funciones planas de render sin lógica de dominio; separarlo por dominio obligaría a imports cruzados entre routers (undo → nutrition/splits). Se documenta la excepción aquí.
- **D8 — Restricción de dependencias.** `src/web/*` puede importar `config`, `src/*` y entre sí (`dependencies`, `render_helpers`), pero **nunca `app`** (sin ciclos). Gate por grep (§9.3).

## 7. Alcance

`app.py`, nuevo paquete `src/web/`, `src/database.py` (solo las 2 funciones nuevas de D3), `pyproject.toml` (ignores), `tests/test_app.py` (target de monkeypatch + split mecánico en F8), `tests/test_split_routes.py` / `test_security.py` / `test_logging_setup.py` / `test_static_assets.py` (target de monkeypatch), `AGENTS.md` §3/§5 (estructura), este plan. **Prohibido tocar:** `templates/`, `static/`, URLs, nombres de handlers internos visibles en logs si aplica, orden de middlewares, `src/` de dominio salvo `database.py` (D3).

## 8. Fuera de alcance

Split de `src/database.py` (§11), split de `static/js/splits.js` (§11), cualquier cambio de comportamiento/HTML/OOB, nuevas rutas, migraciones, dependencias nuevas, mejoras al dashboard (Recuperaciones 2-5), renames cosméticos.

## 9. Fases atómicas ordenadas

Cada fase termina con suite completa verde (§10) y commit atómico revisable. Nada de commits automáticos (AGENTS.md §8): el usuario revisa el diff de cada fase.

- **F0 — Baseline congelado.** Working tree limpio (commitear antes el trabajo del dashboard pendiente). Volcar la huella de rutas (§9.1) a `.tmp/route-snapshot-before.txt` y correr la suite completa registrando el resultado. **Gate:** árbol limpio + suite verde.
- **F1 — Esqueleto `src/web/`.** Crear `__init__.py`, `dependencies.py` (D2) y `render_helpers.py` (D7) moviendo verbatim helpers y constantes; `app.py` importa de ahí (las rutas NO se mueven todavía); `pyproject.toml` ignores (D6); actualizar los 141+7 targets de monkeypatch. **Gate:** suite verde, `from app import templates` funciona, sin rutas movidas.
- **F2 — `split_routes.py`.** Frontera más clara (4 rutas + helpers `_split_*` ya en `render_helpers`; tiene su archivo de tests propio). Gate: suite + `test_split_routes.py` verde.
- **F3 — `sync_routes.py` + `health_routes.py`.** Mover `health_sync_ingest`, `export_health_connect_csv` (con SQL → `database.export_health_records`, D3) y `healthz`.
- **F4 — `nutrition_routes.py`.** 7 rutas de alimentación; helpers de nutrición ya viven en `render_helpers`.
- **F5 — `template_routes.py`.** 6 rutas de plantillas de entreno.
- **F6 — `record_routes.py`.** Registro diario: `/registro`, `/fecha/editor`, `/editor/popup`, `/cardio/*`, session save/eliminar, `/ejercicio/nuevo`.
- **F7 — `dashboard_routes.py` + `undo_routes.py`.** `/`, `/nivel`, `/grafica`, `/semana/primer-entreno` (con SQL de `_cascade_items` → `database.get_cascade_items`, D3); `/undo` al final (depende de los helpers de todos los dominios). `app.py` queda solo composición (D5).
- **F8 — Limpieza y split de tests.** Verificar y eliminar `_nutrition_fecha_display` si sigue muerto (E7); imports finales; dividir `tests/test_app.py` (1.935 l, 125 tests) en `tests/test_{dashboard,record,nutrition,template,split,undo}_routes.py` por movimiento mecánico (sin tocar aserciones; los tests de sync/health ya viven en `test_app.py` → `test_sync_routes.py`). `test_split_routes.py` existente absorbe los suyos.
- **F9 — Docs y gates finales.** Actualizar `AGENTS.md` §3 (estructura: `src/web/`) y §5 (flujo); comparar `.tmp/route-snapshot-before.txt` vs after (deben ser idénticos); greps de verificación (§9.3); gates completos (§10).

### 9.1 Huella de rutas (congelar y comparar)

```bash
UV_CACHE_DIR=.tmp/uv-cache uv run python -c "
from app import app
for r in sorted(app.routes, key=lambda r: r.path):
    print(','.join(sorted(getattr(r, 'methods', ['MOUNT']))), r.path)" > .tmp/route-snapshot-after.txt
diff .tmp/route-snapshot-before.txt .tmp/route-snapshot-after.txt
```

### 9.2 Por qué este orden

Splits primero (frontera clara + tests aislados), luego sync/health (aislados del HTML), nutrition y templates (dominios puros), record (comparte helpers con dashboard), dashboard + undo al final (consumen todo lo demás). Cada fase deja `app.py` importando routers ya extraídos: el árbol siempre está verde y el diff por commit es revisable.

### 9.3 Greps de verificación (F9)

```bash
grep -rn "read_connection\|conn.execute\|read_sql" src/web/          # → vacío (sin SQL)
grep -rn "^from app\|^import app\|from app import" src/web/          # → vacío (sin ciclos)
grep -c "monkeypatch.setattr(appmod" tests/ -r                        # → 0 (todos migrados)
git diff --stat main... -- templates/ static/                         # → sin cambios de este plan
```

## 10. Plan de pruebas

No se escriben tests nuevos: la suite existente ES el congelado (E8). Tras **cada** fase:

```bash
UV_CACHE_DIR=.tmp/uv-cache uv sync --locked
UV_CACHE_DIR=.tmp/uv-cache uv run pytest --ignore=tests/e2e          # unidad + integración (+cobertura ≥90)
UV_CACHE_DIR=.tmp/uv-cache uv run pytest tests/e2e -q --no-cov       # browser (servidor real app:app)
```

Gates estáticos en F9 (y localmente por fase):

```bash
UV_CACHE_DIR=.tmp/uv-cache uv run ruff format --check .
UV_CACHE_DIR=.tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=.tmp/uv-cache uv run mypy app.py src tests
UV_CACHE_DIR=.tmp/uv-cache uv run python scripts/audit_consistency.py
```

Además: arranque manual `./scripts/start_server.sh` (LAN sync-only) y `uv run uvicorn app:app --reload` en F9 para verificar lifespan/middlewares en ambos modos.

## 11. Inventario de archivos largos restantes (veredictos)

> **Actualizado (2026-08-18):** el inventario exhaustivo del proyecto vive ahora en `docs/plans/codebase-factorization-plan.md` (plan maestro). Este plan es su **Fase 1**; `src/database.py` es su **Fase 2** y `static/js/splits.js` su **Fase 3**.

| Archivo | Líneas | Veredicto |
|---|---|---|
| `tests/test_app.py` | 1.935 | **En este plan** (F8: split mecánico por router, 125 tests). |
| `src/database.py` | 849 | **Fase 2 del plan maestro** (`codebase-factorization-plan.md`): split a paquete `src/db/` con `database.py` como fachada (cero churn de imports en los ~20 importadores); ejecutable independiente de este plan. |
| `static/js/splits.js` | 1.110 | **Fase 3 del plan maestro**: split a módulos ES `static/js/splits/` (state/dnd/summaries/form/htmx-bridge). Feature estable de `/splits`, sin conflicto con la cola del dashboard. |
| `scripts/audit_ui.py` | 639 | No. Herramienta de una responsabilidad (barrido Playwright). |
| `src/charts.py` | 581 | No ahora. Cohesivo (figuras Plotly); las Recuperaciones 2-3 lo tocarán — refactorizar después de ese churn. |
| `src/parser.py` | 448 | No. Parsers cohesivos por hoja CSV. |
| `src/dashboard_service.py` | 382 | No. Ya es una sola capa (view models + shell). |
| `tests/test_database.py` (1.286), `tests/e2e/test_dashboard_flow.py` (1.280), `tests/test_security.py` (849) | — | No. Espejan features; solo `test_app.py` se justifica (es el que acopla `app.py`). |

Regla aplicada: dividir por responsabilidad cuando un archivo mezcla dominios (`app.py`); no dividir por líneas cuando el archivo ya tiene una sola responsabilidad.

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Import circular `src/web → app` | Prohibido por diseño (D8) + gate grep §9.3 en cada fase |
| Patch de test pasado por alto | Conteo exacto pre/post (141 DB_PATH + 7 token → 0 en `appmod`); la suite lo detecta igual (fallback a DB real fallaría) |
| `B008`/`DTZ`/`BLE001` rompen ruff en `src/web/` | `pyproject.toml` se actualiza en F1, antes del primer router |
| Pérdida del orden de middlewares/seguridad | Ningún middleware se mueve; quedan en `app.py` (D5); e2e de seguridad (`test_security.py`, 52 tests) lo congela |
| Mezcla con trabajo del dashboard | F0 exige árbol limpio; PR/commits atómicos por fase; diff sin `templates/` ni `static/` (§9.3) |
| Rutas duplicadas/perdidas al mover | Snapshot de rutas pre/post idéntico (§9.1) en F9; también en F7 |
| `from app import templates` roto | Re-export explícito en `app.py` (D5); 3 tests existentes lo verifican |
| Cobertura cae por código nuevo | `--cov=src` ya cubre `src/web/`; los handlers se ejercitan vía TestClient/e2e existentes |

## 13. Criterios de aceptación verificables

1. Snapshot de rutas pre/post **idéntico** (§9.1, diff vacío).
2. `app.py` entre 150–250 líneas, **cero decoradores de ruta** (`grep -E "@app\.(get|post|put|delete)" app.py` → vacío; el exception handler y middlewares no son rutas).
3. Cada router ≤250 líneas; `render_helpers.py` ≤320 (excepción D7 documentada).
4. Greps §9.3 en verde (sin SQL en `src/web/`, sin imports de `app` en `src/web/`, 0 patches sobre `appmod`).
5. `git diff` del plan completo sin cambios en `templates/` ni `static/`; sin URLs nuevas ni renombradas.
6. Suite completa verde (`pytest` + e2e), `ruff format --check`/`ruff check` limpios, `mypy app.py src tests` limpio, cobertura ≥90 % (gate `addopts`), `audit_consistency.py` verde.
7. Tests: **0 aserciones modificadas** — solo targets de monkeypatch (F1) y reubicación mecánica de funciones de test entre archivos (F8).
8. `AGENTS.md` §3/§5 refleja la nueva estructura; `current-ui-contract.md` no requiere cambios (E6).
9. Arranque verificado en ambos modos (`start_server.sh` y `uvicorn app:app --reload`).

## 14. Próximo plan posterior

Con `app.py` modularizado y el árbol verde, retomar la cola del gap-doc: **Recuperación 2 — catálogo izquierdo definitivo** (`docs/plans/dashboard-recovery-2-3-catalog-granularity-summary.md`), ahora con la ventaja de que las fases del dashboard tocan `src/web/dashboard_routes.py` (~170 l) en lugar de un monolito de 1.400.
