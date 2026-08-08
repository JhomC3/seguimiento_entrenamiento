# Panel de Alimentación — Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rehacer el panel de alimentación sobre la rama `feature/nutrition-dashboard`: integrado en la página principal (arriba del editor de entrenamiento), con tabla de día idéntica al esquema del usuario (fila Objetivo calculada desde peso/factores editables, fila Consumido = suma del día, 9 nutrientes por alimento recalculados desde el catálogo), eliminando la página standalone, corrigiendo los 126 bloques duplicados del 8/8/2026 y conservando filas placeholder.

**Architecture:** Migración SQLite `v008` (tabla `parametros_diarios` + `diario_alimentacion.cantidad_g` nullable vía recreación de tabla). El parser deduplica bloques idénticos por fecha y extrae los objetivos de la fila de la hoja. El servidor es la única autoridad de cálculo: objetivo = `round_half_up(peso × factor)` con carb residual de Atwater; consumido = catálogo per-100g × gramos. La UI vive en `index.html` (panel arriba del editor de sesión) con fragmentos htmx y OOB allow-listed ya existentes.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, SQLite (migraciones versionadas), pandas, Decimal/ROUND_HALF_UP, módulos ES, pytest/Playwright, ruff, mypy, uv, Tailwind estático (`build_css.sh`).

---

## 1. Contexto verificado (datos reales de la hoja, 2026-08-08)

| Hecho | Valor verificado |
|---|---|
| Bloques en la hoja `diario` | 283; **158 fechas únicas** tras dedup de bloques idénticos |
| 8/8/2026 | **126 bloques idénticos** (misma firma fecha+filas) → tras dedup: 1 día |
| Alimentos del diario vs catálogo | 47 nombres del diario ⊆ 62 del catálogo — **0 faltantes** (recálculo viable) |
| Fila de objetivo (hoja, por bloque) | kcal varía {2250, 2300, 2500, 2600, 2750}; **fibra=38, hierro=8, calcio=1000, vitC=90, vitA=900 constantes**; prot/grasa/carb NO se importan (se calculan) |
| Fórmulas dictadas por el usuario | prot = peso × factor_prot (1.5, editable); grasa = peso × factor_grasa (1.1, editable); kcal = editable; carb = `(kcal − 4·prot − 9·grasa) / 4`; Atwater 4/4/9 |
| Placeholders reales | Filas con alimento y sin cantidad (Nueces, Papa) → se muestran `—` en Cantidad, 0 en nutrientes (cantidad_g NULL) |
| Estado de la rama | 17 commits; página `/alimentacion`, 4 templates, JS, 12 tests de nutrición — se rehace lo que no encaja, se conserva lo que sí |

## 2. Scope

**In scope:**
- Migración `v008`: `parametros_diarios` (fecha PK, peso_kg, factor_proteina 1.5, factor_grasa 1.1, kcal_objetivo, fibra/hierro/calcio/vitC/vitA objetivo) + `diario_alimentacion` con `cantidad_g` nullable (recreación preservando datos e índices).
- `parse_diario`: dedup de bloques idénticos por firma `(fecha, filas)`; placeholders con cantidad `None`; nueva salida `DiarioParse(df, params_por_fecha)`.
- Importador: consumido recalculado desde el catálogo (`round_half_up(catálogo × g / 100)`); parámetros por fecha (kcal+extras de la hoja; peso/factores por defecto); fallback a valores de la hoja + log si un alimento no está en el catálogo.
- Servicio: `objetivos_diarios()` con las fórmulas dictadas; `save` con `peso_kg`, `factor_proteina`, `factor_grasa`, `kcal_objetivo`.
- UI: panel en `index.html` **arriba** del editor de sesión; bloque de parámetros encima de la tabla (peso/kcal prominentes; factores prot/grasa atenuados); tabla con el esquema exacto del usuario (filas Objetivo/Consumido fijas + 11 columnas, solo Alimento/Cantidad editables, +/−, Guardar/Eliminar día); "Nuevo alimento" en el sidebar; preview client de 9 nutrientes y Objetivo/Consumido en vivo.
- Eliminar la página `/alimentacion`, `alimentacion.html` y el enlace del header.
- Tests, docs, gates, re-importación de `data/gym.db`.

**Non-goals (v1):** porcentajes contra objetivo; historial de días; gráficas nutricionales; migración de datos de entrenamiento; multi-usuario; unidades distintas de gramos.

**Definition of done:**
- `/alimentacion` devuelve 404; no existe enlace en el header; el panel vive en `/`.
- `data/gym.db`: 8/8/2026 con 1 bloque (~13 filas, incl. placeholders); total ≈ 2.100 filas; `parametros_diarios` poblado por fecha (158).
- Objetivo 8/8/2026 (peso 69, prot 1.5, grasa 1.1, kcal 2750) = prot 104, grasa 76, carb 397 (verificado por test con ROUND_HALF_UP).
- Consumido de una fila Avena 160 g = 622 kcal (catálogo × 1.6) en BD y UI.
- Guardar el día persiste peso/factores/kcal + filas; undo restaura ambos.
- Gates: `uv run pytest -q`, `ruff format --check .`, `ruff check .`, `mypy app.py src tests`, `uv run python scripts/verify_editor.py`, `build_css.sh` con diff mínimo.

## 3. Guardrails

1. TDD: test estrecho rojo → implementación mínima → verde → commit.
2. Un commit lógico por tarea; rama `feature/nutrition-dashboard`; verificar `git branch --show-current` antes de cada commit (otra sesión comparte el árbol).
3. SQL parametrizado (`?`); sin handlers inline (solo `data-action` + delegación); targets OOB allow-listed; `#app-config` server-owned con escaping `\u003c/\u003e/\u0026`.
4. Fechas solo ISO `YYYY-MM-DD`; no editar migraciones aplicadas; v008 se registra tras v007.
5. No commits de `data/gym.db`, backups ni `.tmp/` (crear/limpiar dentro del proyecto).
6. El bloque de parámetros respeta la jerarquía visual pedida: peso y kcal primarios; factores atenuados.

---

## Phase 0 — Estado actual y limpieza de la página standalone

### Task 0.1: Materializar el plan y baseline
Guardar este documento en `docs/plans/2026-08-08-alimentacion-dashboard-rebuild.md`. Gates baseline: `uv run pytest -q` (312 passed), ruff, mypy. Commit `docs: add nutrition dashboard rebuild plan`.

### Task 0.2: Eliminar la página standalone y su enlace

**Files:** Modify `app.py`, `templates/index.html`, `tests/test_app.py`; Delete `templates/alimentacion.html`.

Tests (rojo → verde): `test_alimentacion_standalone_page_removed` (GET /alimentacion → 404) y `test_index_no_tiene_enlace_alimentacion` (`href="/alimentacion"` ausente en `/`). Implementación: borrar ruta `alimentacion_index`, helpers `_nutrition_app_config`/`_alimento_preview_map` (se mudan en Task 2.4), enlace del header, `templates/alimentacion.html`. Commit `feat: remove standalone nutrition page`.

## Phase 1 — Datos: migración, parser, importador

### Task 1.1: Migración `v008_nutrition_daily_params`

**Files:** Create `src/migrations/v008_nutrition_daily_params.py`; Modify `src/migrations/runner.py`, `tests/test_database.py`.

- `parametros_diarios` (fecha TEXT PK, peso_kg REAL NOT NULL DEFAULT 70, factor_proteina REAL NOT NULL DEFAULT 1.5, factor_grasa REAL NOT NULL DEFAULT 1.1, kcal_objetivo REAL NOT NULL DEFAULT 2300, fibra_objetivo, hierro_objetivo, calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo REAL NOT NULL DEFAULT 0).
- Recrear `diario_alimentacion` con `cantidad_g REAL` nullable (CREATE `_new` → INSERT SELECT → DROP → RENAME → recrear índice) preservando filas.
- Registrar tras `v007`; añadir `parametros_diarios` a `_DOMAIN_TABLES`.
- Tests: columnas nullable + tabla params + MAX(version)==8 + filas preservadas. Commit `feat: v008 nutrition daily params and nullable quantity`.

### Task 1.2: `parse_diario` — dedup, placeholders y parámetros

**Files:** Modify `src/parser.py`, `tests/test_parser.py`, `tests/test_import_nutrition.py`.

- `@dataclass DiarioParse(df: pd.DataFrame, params: list[dict])`.
- Dedup: firma por bloque `(fecha_iso, tuple((alimento, cantidad, *9 nutrientes)))`; skip si ya vista para esa fecha.
- Placeholder: alimento con cantidad vacía → `cantidad_g=None`, nutrientes 0.0.
- Parámetros: fila de objetivo (índice 3) con label-map del bloque: kcal/fibra/hierro/calcio/vitC/vitA objetivo (1 por fecha tras dedup).
- `parse_diario` devuelve `DiarioParse`; actualizar llamadas existentes a `.df`.
- Tests: dedup de bloques idénticos, placeholder conservado, params extraídos. Commit `feat: dedupe identical blocks, keep placeholders, extract targets`.

### Task 1.3: Importador — recálculo del consumido y parámetros

**Files:** Modify `scripts/import_nutrition.py`, `tests/test_import_nutrition.py`.

- Para cada fila con cantidad: nutrientes = `calculate_nutrients(catálogo[alimento], cantidad_g)`; fallback: valores del CSV + aviso.
- `INSERT OR REPLACE INTO parametros_diarios` (kcal+extras de la hoja; peso/factores por defecto).
- Tests: recálculo (Avena 120g → 467 kcal pese a 999 en hoja), params con defaults. Re-import real: total ≈ 2.100 filas, 8/8/2026 ≈ 13. Commit `feat: recompute consumed from catalog and import targets`.

## Phase 2 — Dominio y backend

### Task 2.1: `nutrition_service` — fórmulas de objetivo

`objetivos_diarios(peso_kg, factor_proteina, factor_grasa, kcal_objetivo, extras) -> dict[str, float]`:
prot = round_half_up(peso×factor_prot); grasa = round_half_up(peso×factor_grasa); kcal = round_half_up(kcal_objetivo); carb = round_half_up((kcal − 4prot − 9grasa)/4); extras (fibra/hierro/calcio/vitC/vitA). Test con 69/1.5/1.1/2750 → 104/76/397. Commit `feat: daily target formulas from weight and factors`.

### Task 2.2: `database.py` — parámetros y cantidad nula

`get_parametros_diarios(db, fecha) -> dict | None`; `save_parametros_diarios(db, fecha, params)` (UPSERT); `get_diario_by_fecha`/`replace_diario_by_fecha` con `cantidad_g` nullable. Commit `feat: persist daily params and nullable quantities`.

### Task 2.3: View model — objetivo, consumido y filas

`NutritionEditorViewModel` gana `objetivo: dict`, `consumido: dict` (gramos + 9 nutrientes), `parametros: dict`. `build_nutrition_editor` los compone. Tests: objetivo 104/397, consumido 467, placeholder con cantidad None. Commit `feat: editor view model with targets and consumed totals`.

### Task 2.4: Rutas — save con parámetros; app_config del index

- `POST /alimentacion/save` recibe `peso_kg`, `factor_proteina`, `factor_grasa`, `kcal_objetivo` y los persiste (undo restaura filas y parámetros).
- `app_config_json` del index gana `alimento_map` con los **9** nutrientes.
- Tests: save guarda params + filas; index contiene `"alimento_map"`. Commit `feat: save daily params and index alimento map`.

## Phase 3 — UI integrada

### Task 3.1: Panel en `index.html` + bloque de parámetros + tabla del esquema

**Files:** Modify `templates/index.html`, `templates/nutrition_editor.html`, `templates/nutrition_date_navigator.html`, `templates/alimento_create_form.html` (sidebar), `tests/test_app.py`.

- Panel (`#nutrition-panel`, misma tarjeta que el editor de sesión) insertado **antes** de `#session-editor` en el main.
- Bloque `#target-params` encima de la tabla: peso (kg) y kcal prominentes; factores prot/grasa atenuados.
- Tabla: filas fijas `Objetivo` (Cantidad = peso kg; kcal/carb/prot/grasa calculados; 5 extras) y `Consumido` (Cantidad = "N g"; suma 9 nutrientes); 11 columnas en orden fijo; celdas `.nutrition-preview` con clases `kcal-cell, carb-cell, prot-cell, fat-cell, fibra-cell, hierro-cell, calcio-cell, vitc-cell, vita-cell`; placeholder → `—`/0.
- Tests render: panel antes que session-editor; 11 etiquetas; Objetivo/Consumido presentes. `build_css.sh` si diff. Commit `feat: nutrition panel on index with target table`.

### Task 3.2: `nutrition-editor.js` — preview 9 + objetivo en vivo + consumido

**Files:** Modify `static/js/nutrition-editor.js`, `tests/e2e/test_nutrition_flow.py`.

- `previewRow` con 9 campos; `updateObjetivo()` desde `#target-params` (fórmulas dictadas, roundHalfUp); `updateConsumido()` suma celdas (gramos incluidos); form envía `peso_kg/factor_proteina/factor_grasa/kcal_objetivo` ocultos; `refreshNutritionEditor()` recalcula tras swaps.
- e2e reescrito sobre `/`: crear alimento → fila Avena 120 → preview 467 → parámetros (69/2750) → Objetivo 104/76/397 en vivo → guardar → recargar → persisten → eliminar día (modal) → vacío.
- Commit `feat: live nutrition preview and target recalculation`.

## Phase 4 — Calidad

### Task 4.1: Gates completos
`uv run pytest -q` (~320 passed), ruff format/check, mypy, `verify_editor.py` 131/131, `build_css.sh` diff mínimo. Commit `chore: final gates and css`.

## Phase 5 — Documentación e integración

### Task 5.1: Docs
`docs/architecture/current-ui-contract.md` (sección nutrición reescrita), `docs/operations/local-development.md`, `AGENTS.md` (`parametros_diarios`, cantidad nullable, rutas), nota en plan anterior. Commit `docs: update nutrition contract after rebuild`.

### Task 5.2: Importación final y smoke
`GYM_DB_PATH=data/gym.db uv run python scripts/import_nutrition.py` + uvicorn + verificación manual de `/` (panel arriba, 8/8/2026 con ~13 filas, Objetivo/Consumido, guardar/eliminar/undo, entrenamiento intacto). Sin commit de BD.

### Task 5.3: Integración (solo con aprobación explícita del usuario)
`git merge main` (si pasó tiempo) → gates → merge a `main` → `git branch -d forensic-remediation`. Commit final + reporte.

---

**Riesgos:** cambio de firma de `parse_diario` rompe tests existentes (se actualizan en Task 1.2); hoja en edición viva (fixtures congelados); colisión con la otra sesión (verificar rama antes de cada commit); `build_css.sh` requiere npx (instalado).

## Notas de ejecución (2026-08-08)

1. **v008 en gym.db**: un arranque previo registró v008 con la condición invertida del rebuild (registrada sin aplicar); se reparó `data/gym.db` manualmente con el mismo SQL del rebuild y se re-importó (2444 filas / 158 fechas; 8/8/2026 con 29 filas tras dedup).
2. **verify_editor y el sticky**: el aside del sidebar era más alto que su contenedor (`3418px` vs `2450px`), lo que impedía el anclaje `position: sticky`; con el panel de alimentación, la tarjeta fuente del drag quedaba fuera del viewport y el drag HTML5 no arrancaba (4 checks FAIL). Fix: `lg:max-h-[calc(100vh-1.5rem)] lg:overflow-y-auto` en el aside → sticky real + scroll interno → 131/131 OK.
3. **carb objetivo del test**: con grasa 1.1 × 69 = 76, `carb = (2750 − 4·104 − 9·76)/4 = 413` (el 398 del esquema corresponde a grasa 83).
4. **Selector colisionante**: `input[name="fecha"]` sin scope en un e2e de entrenamiento → scoped a `#session-form`.
