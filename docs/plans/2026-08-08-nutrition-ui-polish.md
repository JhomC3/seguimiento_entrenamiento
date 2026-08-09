# Nutrition UI Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reordenar la cabecera del dashboard (título de fecha global debajo del navegador, títulos de panel estáticos, colapso arriba, editar/eliminar abajo en ambos paneles), añadir plantillas de alimentación con drag&drop (guardar/reordenar/aplicar como en entrenamiento) y precargar en cada día vacío los últimos datos guardados (alimentos y parámetros peso/factores/kcal).

**Architecture:** Título global renderizado por servidor (`day_from_date`/`fecha_display`/`calculate_cycle_week`) y actualizado en cliente con las mismas fórmulas (ciclo_start en `#app-config`). Los dos editores comparten estructura y CSS (`.panel-topbar`, `.panel-content`, `.panel-bottombar`) sobre `session-editor.css`. Plantillas de alimentación: migración v009 (`plantillas_alimentacion` + `plantilla_alimentos`), DnD HTML5 espejo de `templates.js` en un módulo nuevo (`nutrition-templates.js`), y aplicar = `GET /alimentacion/plantilla/aplicar/{id}` → editor `force_editable`. Prefill en `build_nutrition_editor`: día sin filas en DB → copia del día previo con datos (filas + parámetros), con `has_data` basado en DB.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, SQLite (migraciones), pandas, módulos ES, pytest/Playwright, ruff, mypy, uv, Tailwind estático.

---

## 1. Decisiones confirmadas con el usuario

| Decisión | Elección |
|---|---|
| Títulos de panel | Estáticos en ambos (`Entrenamiento` / `Alimentación`); la fecha vive en el título global |
| Botones editar/eliminar | Iconos (mismas clases, reubicados) en `.panel-bottombar` centrada |
| Botón colapsar | Fila integrada `.panel-topbar` en el borde superior del card (sin elementos externos) |
| Plantillas alimentación | Guarda alimento + cantidad; **drag&drop**: reordenar dentro de la lista y soltar sobre el panel para aplicar |

## 2. Dependencias verificadas (código existente)

- `src/training_service.py`: `calculate_cycle_week` (semana = `max(1, (fecha − lunes(ciclo_start)).days // 7 + 1)`), `day_from_date` (mapa español), `fecha_display` (`d/m/yy`) — se replican en JS.
- `verify_editor.py:439`: `allControlsVisible: controls.length === 4` — con el nuevo layout el header de sesión queda con **1** control (bookmark) → actualizar a `=== 1`.
- `tests/e2e/test_dashboard_flow.py:90`: `#session-editor-wrap` contiene "Semana" → pasa a `#session-date-title`.
- Clics por clase (`#session-editor .pencil-btn`, `.delete-session-btn`, `.save-template-btn`, `.row-actions`) siguen resolviendo al mover los botones (clases conservadas).
- `templates.js`: DnD HTML5 (dragstart/dragover/drop/dragend + ghost) — modelo a replicar en `nutrition-templates.js` sin tocar `templates.js`.

## 3. Scope / Non-goals / Definition of done

**In scope:** título global + títulos estáticos; reordenamiento de controles en ambos paneles; plantillas de alimentación (guardar desde el día, listar en sidebar, reordenar por drag, aplicar por drag o botón); prefill del día vacío; tests, verify, e2e, docs.

**Non-goals:** drag&drop de filas dentro de la tabla de alimentación; objetivos por plantilla (peso/kcal no se guardan en la plantilla); prefill en entrenamiento; multi-usuario.

**Definition of done:** título global cambia al navegar (cliente y servidor consistentes); ambos paneles con topbar/bottombar; verify 131/131 (con assert 1 control); plantilla guardada se aplica a un día vacío con filas + cantidades; día vacío muestra datos del día previo (filas + peso/factores/kcal) sin marcarlos como guardados; gates en verde.

## 4. Guardrails

1. TDD: test rojo → implementación mínima → verde → commit por tarea.
2. No tocar `templates.js`, `editor.js`, ni la lógica de entrenamiento (solo layout en `session_editor.html` y asserts del verify/e2e).
3. SQL parametrizado; `data-action` + delegación; targets OOB allow-listed; fechas ISO.
4. Verificar `git branch --show-current` antes de cada commit; sin `data/*.db` ni backups en git.
5. Probe de navegador efímero en `scripts/.probe_ui.py` (se elimina al final); salidas solo dentro del proyecto.

---

## Phase 0 — Plan materializado y baseline

### Task 0.1: Guardar el plan y baseline
- Guardar este documento en `docs/plans/2026-08-08-nutrition-ui-polish.md`.
- `uv run pytest -q` (335) · `uv run python scripts/verify_editor.py` (131/131) · ruff · mypy → registrar.
- Commit `docs: add nutrition ui polish plan`.

## Phase 1 — Título global y títulos estáticos

### Task 1.1: Fragmento `date_title` y helper de servidor
**Files:** Create `templates/date_title.html`; Modify `app.py`, `templates/index.html`, `tests/test_app.py`.
- Test rojo: `GET /` contiene `id="session-date-title"` con el día (ej. "SABADO") y "Semana N"; el índice de `session-date-title` está entre `date-navigator` y `nutrition-panel`.
- Implementar: partial con `{{ dia }} {{ fecha_display }}` + `Semana {{ semana }}` (mismas clases que el título actual); helper `_date_title_html(request, fecha_iso)`; insertar en `index.html` tras `#date-navigator`.
- Verdes + `uv run pytest tests/test_app.py -q`. Commit `feat: global date title below navigator`.

### Task 1.2: Títulos estáticos de panel
**Files:** Modify `templates/session_editor.html`, `templates/nutrition_editor.html`, `tests/test_app.py`.
- Test: editor de sesión contiene `<h3 …>Entrenamiento</h3>` sin la fecha; nutrición contiene `Alimentación` sin fecha.
- Implementar: reemplazar el `<h3>` (sesión: `{{ dia }} {{ fecha_display }}` → `Entrenamiento`; nutrición: `Alimentación {{ fecha_display }}` → `Alimentación`). El span "Semana N" del editor se elimina (vive en el título global).
- Verdes. Commit `feat: static panel titles`.

### Task 1.3: Actualización client-side del título
**Files:** Modify `app.py` (`app_config_json` + `ciclo_start`), `static/js/state.js`, `static/js/date-navigation.js`, `tests/test_app.py`, `tests/e2e/test_dashboard_flow.py`.
- Test app: `#app-config` del index contiene `ciclo_start`.
- Test e2e: `#session-date-title` contiene "Semana"; al navegar a otra fecha el texto del título cambia (reemplaza la línea 90 del e2e actual).
- Implementar: `setCicloStart`/`getCicloStart` en `state.js`; en `doNav` actualizar `#session-date-title` con mapa español (LUNES..DOMINGO), `d/m/yy` y `max(1, floor((fecha − lunes(ciclo_start))/7)+1)`.
- Verdes + e2e entrenamiento. Commit `feat: live date title on navigation`.

## Phase 2 — Layout de paneles (topbar / content / bottombar)

### Task 2.1: Estructura de `session_editor.html` y `nutrition_editor.html`
**Files:** Modify ambos templates, `static/css/session-editor.css`, `scripts/verify_editor.py`, `tests/test_app.py`.
- Tests: `.panel-topbar` con el chevron en ambos paneles; `.panel-bottombar` con `.pencil-btn`/`.delete-session-btn` (y `.nutrition-*`) que NO están dentro de `.editor-header-actions`; el header de sesión contiene solo el bookmark.
- Implementar en ambos templates: envolver header+form+bottom en `<div class="panel-content">`; mover el chevron a `.panel-topbar` (primero del card); mover lápiz/eliminar a `.panel-bottombar` (clases intactas).
- CSS: `.panel-topbar` (fila fina, border-bottom, chevron izquierdo), `.panel-bottombar` (border-top, centrado), colapso: `#session-editor.collapsed .panel-content, #nutrition-panel.collapsed .panel-content { display: none; }` (sustituye la regla de `#session-form`).
- `verify_editor.py:439`: `controls.length === 4` → `=== 1`.
- Verdes: `verify_editor` 131/131, e2e entrenamiento (18) y nutrición. Commit `feat: top collapse bar and bottom edit bar in both editors`.

## Phase 3a — Plantillas de alimentación con drag&drop

### Task 3a.1: Migración v009
**Files:** Create `src/migrations/v009_nutrition_meal_templates.py`; Modify `runner.py`, `tests/test_database.py`.
- Test: tablas `plantillas_alimentacion` (nombre UNIQUE, orden) y `plantilla_alimentos` (orden, alimento, cantidad_g, FK CASCADE); `MAX(version) == 9`.
- Implementar + registrar + `_DOMAIN_TABLES`. Commit `feat: v009 nutrition meal templates`.

### Task 3a.2: Persistencia y servicio
**Files:** Modify `src/database.py`, `src/nutrition_service.py`, `tests/test_database.py`, `tests/test_nutrition_service.py`.
- Tests: `get_plantillas_alimentacion` (lista con alimentos), `insert_plantilla_alimentacion`, `delete_plantilla_alimentacion`, `reorder_plantillas_alimentacion`; `save_meal_template` (valida nombre + filas; reemplaza si el nombre existe), `apply_meal_template` (devuelve filas alimento/cantidad_g con los 9 nutrientes recalculados del catálogo; alimento desconocido → nutrientes 0).
- Implementar (espejo de plantillas de entrenamiento). Commit `feat: persist and apply nutrition meal templates`.

### Task 3a.3: Rutas y UI
**Files:** Modify `app.py`, `src/response_fragments.py`, `templates/index.html`; Create `templates/plantillas_alimentacion_list.html`; Modify `templates/nutrition_editor.html`; `tests/test_app.py`.
- Tests: `POST /alimentacion/plantilla/guardar` (OOB `#nutrition-templates-section`), `POST /alimentacion/plantilla/eliminar/{id}`, `POST /alimentacion/plantilla/reordenar`, `GET /alimentacion/plantilla/aplicar/{id}?fecha=` (editor con filas y `force_editable`), index con la sección de plantillas en el sidebar.
- Implementar: bookmark en el header de nutrición (`data-action="nutrition-toggle-template-form"`) + mini-form inline (nombre + btn-x/btn-check) — guarda `alimento[]`+`cantidad[]` del día; lista de tarjetas `draggable` con botón "Aplicar"; target OOB `nutrition-templates-section`.
- Commit `feat: nutrition meal template routes and sidebar`.

### Task 3a.4: Drag&drop
**Files:** Create `static/js/nutrition-templates.js`; Modify `static/js/app.js`, `static/css/session-editor.css` (selector `#nutrition-panel.drop-target`), `tests/e2e/test_nutrition_flow.py`.
- e2e: guardar plantilla desde el header → aparece en el sidebar; **arrastrar una tarjeta sobre otra** reordena y persiste tras refrescar; **soltar la tarjeta sobre `#nutrition-panel`** aplica las filas al editor (XHR a aplicar, filas presentes); botón "Aplicar" también funciona.
- Implementar: `initNutritionTemplatesDnD()` (dragstart con id + ghost local, dragover del list reordena, drop en list no-op, dragend persiste orden si cambió, drop en `#nutrition-panel` dispara el GET aplicar), import en `app.js`.
- Verdes: e2e nutrición + entrenamiento; `verify_editor` 131/131 (el DnD nuevo no interfiere: selectores distintos). Commit `feat: drag and drop nutrition templates`.

## Phase 3b — Prefill del día vacío con los últimos datos

### Task 3b.1: Prefill en `build_nutrition_editor`
**Files:** Modify `src/dashboard_service.py`, `src/view_models.py`, `tests/test_nutrition_dashboard.py`.
- Tests: día vacío tras un día con datos → `rows` = filas del previo (alimento/cantidad/snapshot) y `parametros` = del previo (peso/factores/kcal), `has_data=False`, `prefilled=True`, `prefill_source` = fecha previa; sin día previo → defaults y `prefilled=False`; día con datos guardados → sin prefill.
- Implementar: `build_nutrition_editor` con `rows` override y `force_editable`; consulta `MAX(fecha) < fecha` con filas; `readonly = (has_data or fecha < today) and not force_editable`.
- Commit `feat: prefill empty days with last saved data`.

### Task 3b.2: Hint visual y e2e
**Files:** Modify `templates/nutrition_editor.html`, `tests/e2e/test_nutrition_flow.py`.
- e2e: guardar día A → navegar a día B vacío → filas y peso/kcal precargados; el botón Eliminar NO aparece (sin datos guardados); guardar B → tiene datos.
- Implementar: hint discreto en el header/params cuando `prefilled` («Datos del {prefill_source}»).
- Verdes. Commit `feat: prefill hint in nutrition editor`.

## Phase 4 — Verificación final y cierre

### Task 4.1: Probe final y gates
- Probe (`scripts/.probe_ui.py`): título cambia al navegar; colapso oculta `.panel-content`; bottom bar con Editar/Eliminar; guardar→reordenar→aplicar plantilla por drag; prefill visible; consola limpia.
- `uv run pytest -q` (~345) · `verify_editor` 131/131 · e2e ambos · ruff · mypy · `./scripts/build_css.sh` (si diff) · `git diff --check`.
- Eliminar el probe. Commit `chore: final gates and polish`.

### Task 4.2: Docs
- `docs/architecture/current-ui-contract.md`: título global, topbar/bottombar, plantillas de alimentación, prefill.
- Notas en `docs/plans/2026-08-08-alimentacion-dashboard-rebuild.md` + el plan nuevo.
- Commit `docs: nutrition ui polish contract`.

## Riesgos y mitigaciones
- **verify/e2e sensibles al header**: solo se tocan los asserts identificados (`controls.length 4→1`, "Semana" → `#session-date-title`); los clics por clase se conservan (clases intactas en la reubicación).
- **DnD nuevo**: espejo de `templates.js` con estado local (sin `state.js` compartido) para no interferir con el DnD de entrenamiento; verify 131 checks + e2e como red.
- **Prefill vs guardado**: `has_data` y `data-has-data` siguen basados en DB (nada se marca como guardado hasta pulsar Guardar); el lápiz desbloquea el día pasado precargado como en entrenamiento.
