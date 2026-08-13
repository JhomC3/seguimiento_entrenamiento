# Revertir el rediseño — Plan de Implementación

> **Para Claude:** REQUIRED SUB-SKILL: Usar superpowers:executing-plans para implementar este plan tarea por tarea.

**Goal:** Volver a la UI anterior (colores, gráfica unificada, sidebar de plantillas/alta) conservando las mejoras de datos aprobadas (RIR negativo, reps decimales, descanso_seg, sets al fallo, cardio annotations) y añadiendo: editores como ventana emergente, cascada grupo→músculo→ejercicios en barra superior, resumen en el hover de la gráfica.

**Architecture:** Restaurar desde `main` los archivos de frontend (app.py, templates, static/js, dashboard_service, response_fragments, charts, view_models, tests de UI) y conservar de la rama los archivos de datos (migrations, models, training_service, database, metrics_engine, template_service, analysis_data, cardio_service + sus tests). Re-aplicar deltas de datos sobre el UI restaurado y añadir: popup de editores (`/editor/popup`), cascada de niveles (`/nivel`), hover enriquecido.

**Tech Stack:** FastAPI + htmx + Jinja2, pandas, plotly, SQLite, pytest, Playwright, ruff, mypy.

**Estándares (AGENTS.md §6):** tipado estricto, sin `except:` genéricos, SQL parametrizado, migraciones versionadas, TDD, commits pequeños, `uv run` siempre, gates por tarea (ruff format/check, mypy, pytest).

---

## Fase 0 — Verificación previa

### Task 1: Mapa exacto de restauración

**Step 1:** Confirmar el estado del árbol y la lista exacta de archivos a restaurar:

```bash
git status --short
git diff --name-status main...HEAD | rg "^[MD]" | head -40
```

**Step 2:** Confirmar que `main` (8ecbbd8) contiene los archivos UI esperados:

```bash
git ls-tree main --name-only templates/ static/js/ | head -40
```

**Step 3:** Sin cambios. Verificación de contexto para el plan.

**Commit:** ninguno (solo lectura).

---

## Fase 1 — Restaurar base anterior

### Task 2: Restaurar archivos UI desde `main`

**Files:**
- Restore (git checkout main --): `app.py`, `templates/index.html`, `templates/exercise_list.html`, `templates/session_history.html`, `templates/exercise_create_form.html`, `templates/alimento_create_form.html`, `static/js/app.js`, `static/js/dashboard-filters.js`, `static/js/chart-interaction.js`, `src/dashboard_service.py`, `src/response_fragments.py`, `src/charts.py`, `src/view_models.py`, `static/css/app.css`, `docs/architecture/current-ui-contract.md`, `tests/test_app.py`, `tests/test_charts.py`, `tests/test_security.py`, `tests/e2e/test_dashboard_flow.py`, `tests/e2e/test_nutrition_flow.py`
- Delete (git rm): `templates/analysis_filters.html`, `templates/day_detail.html`, `templates/kpi_row.html`, `templates/register_editor.html`, `static/js/analysis-chart.js`, `static/js/layer-toggles.js`, `static/js/segmented-pill.js`, `static/js/register-modal.js`, `static/js/contextual-create.js`, `static/css/pills.css`, `tests/test_analysis_view.py`, `tests/e2e/test_analysis_flow.py`

**Step 1:** Ejecutar el checkout + rm:

```bash
git checkout main -- app.py templates/index.html templates/exercise_list.html templates/session_history.html templates/exercise_create_form.html templates/alimento_create_form.html static/js/app.js static/js/dashboard-filters.js static/js/chart-interaction.js src/dashboard_service.py src/response_fragments.py src/charts.py src/view_models.py static/css/app.css docs/architecture/current-ui-contract.md tests/test_app.py tests/test_charts.py tests/test_security.py tests/e2e/test_dashboard_flow.py tests/e2e/test_nutrition_flow.py
git rm templates/analysis_filters.html templates/day_detail.html templates/kpi_row.html templates/register_editor.html static/js/analysis-chart.js static/js/layer-toggles.js static/js/segmented-pill.js static/js/register-modal.js static/js/contextual-create.js static/css/pills.css tests/test_analysis_view.py tests/e2e/test_analysis_flow.py
```

**Step 2:** Verificar que la app importa (los archivos de datos de la rama son compatibles con el app.py de main):

```bash
uv run python -c "import app; print('ok')"
```

**Step 3:** Correr la suite de datos de la rama (deben pasar: RIR, descanso, fallos, migraciones, cardio, análisis_data):

```bash
uv run pytest tests/test_training_service.py tests/test_models.py tests/test_database.py tests/test_metrics_engine.py tests/test_analysis_data.py tests/test_cardio_service.py
```

**Step 4:** Gates parciales (pueden fallar tests de UI aún rotos — se arreglan en Fase 2):

```bash
uv run ruff check app.py src tests
```

**Step 5: Commit**

```bash
git add -A
git commit -m "revert: restore previous UI from main (sidebar, unified chart, colors)"
```

---

## Fase 2 — Re-aplicar mejoras de datos al UI restaurado

### Task 3: `descanso[]` en el guardado de sesión

**Files:**
- Modify: `app.py` (`entrenamiento_session_save`)
- Modify: `templates/session_editor.html` (conservado de la rama — verificar), `static/js/editor.js` (conservado), `static/js/htmx-lifecycle.js` (conservado)

**Step 1:** Verificar que `session_editor.html`, `editor.js` y `htmx-lifecycle.js` siguen siendo los de la rama (columna Desc, RIR min −5, badges, recalcRM):

```bash
git log --oneline -3 -- templates/session_editor.html static/js/editor.js static/js/htmx-lifecycle.js
rg -n "descanso|rir-badge|min=\"-5\"" templates/session_editor.html | head
```

**Step 2:** En `app.py` (restaurado de main), añadir el campo paralelo al handler de guardado:

```python
@app.post("/entrenamiento/session/save", response_class=HTMLResponse)
def entrenamiento_session_save(
    request: Request,
    fecha: str = Form(...),
    ejercicio: list[str] = Form(default=[]),
    kg: list[str] = Form(default=[]),
    reps: list[str] = Form(default=[]),
    rir: list[str] = Form(default=[]),
    descanso: list[str] = Form(default=[]),
):
    sets = sets_from_form(ejercicio, kg, reps, rir, descansos=descanso)
```

**Step 3:** Test de integración en `tests/test_app.py` (añadir): guardar con `descanso=["90"]` persiste la columna.

**Step 4:** `uv run pytest tests/test_app.py tests/test_training_service.py` + gates.

**Step 5: Commit** `feat: persist rest seconds via the restored editor`

---

### Task 4: Cardio del día — mover helpers a `cardio_service.py`

**Files:**
- Modify: `src/cardio_service.py` — añadir `get_day_cardio(db_path, fecha_iso) -> list[dict]` (sesiones EXERCISE_SESSION + anotaciones, SQL de la rama), `get_day_fc_media(db_path, fecha_iso)`, `get_day_sleep_prev_night(db_path, fecha_iso)`
- Test: `tests/test_cardio_service.py`

**Step 1: Tests que fallan** — `get_day_cardio` devuelve sesiones del día con anotación (envelope `$.value.title`), `get_day_fc_media` promedio de `$.value.samples`, `get_day_sleep_prev_night` horas de la noche anterior.

**Step 2:** Falla (no existen). **Step 3:** Implementar moviendo el SQL desde `src/dashboard_service.py` (rama) — rutas JSON correctas: `$.value.title`, `$.value.samples`, `SUM(end-start)`. **Step 4:** Tests + gates. **Step 5: Commit** `feat: cardio day helpers in cardio_service`

---

### Task 5: `chart_pfr_timeline` — hover resumen enriquecido

**Files:**
- Modify: `src/charts.py` (restaurado de main)
- Modify: `src/charts.py` — `get_exercise_raw_data` vuelve a seleccionar `descanso_seg`
- Test: `tests/test_charts.py`

**Step 1: Test que falla** — `chart_pfr_timeline` devuelve figura cuyo JSON contiene `sets_fallo` en el hovertemplate; `get_exercise_raw_data` tiene columna `descanso_seg`.

**Step 2:** Falla (main no lo tiene). **Step 3: Implementar:**

- En `chart_pfr_timeline`: usar el timeline de la rama (`calculate_pfr_timeline` ya devuelve `sets_totales`, `sets_fallo`), agregar por semana; unir `volumen`/`peso`/`sueno` semanales desde `src/analysis_data.py` (promedios de la semana por fecha) y enriquecer:

```python
hovertemplate=(
    "Semana %{x}<br>Crecimiento: %{y:.1f}%"
    "<br>Series: %{customdata[0]} · Fallos: %{customdata[1]}"
    "<br>Volumen: %{customdata[2]:.0f} kg"
    "<br>Peso: %{customdata[3]} kg · Sueño: %{customdata[4]} h"
    "<extra></extra>"
)
```

- `customdata` por fila semanal; valores None → "—" (string) para no romper el formato.
- `get_exercise_raw_data`: `SELECT ... rir, descanso_seg ...` + columna en el return.

**Step 4:** Tests + gates. **Step 5: Commit** `feat: enriched hover summary on unified chart`

---

## Fase 3 — Editores como ventana emergente

### Task 6: `GET /editor/popup` + template del popup

**Files:**
- Create: `templates/editor_popup.html`
- Modify: `app.py` — ruta `GET /editor/popup?fecha=`
- Modify: `src/response_fragments.py` — allow-list: `"cardio-day"`, `"popup-body"`

**Step 1: Template** `editor_popup.html` — contenedores del contrato JS (idénticos a los del main anterior):

```
#popup-body
  #date-navigator (fragmento _navigator_html)
  #session-date-title (día + semana)
  #nutrition-panel[data-editmode] > #nutrition-editor-wrap
  #session-editor[data-editmode] > #editor-notice + #save-outcome + #session-editor-wrap
  #cardio-day (bloque de cardio del día — Task 7)
```

**Step 2: Ruta** (en `app.py`):

```python
@app.get("/editor/popup", response_class=HTMLResponse)
def editor_popup(request: Request, fecha: str = Query(...)):
    from datetime import date as _date
    fecha_date = _date.fromisoformat(fecha)
    return _render_body(
        templates.TemplateResponse(
            request=request,
            name="editor_popup.html",
            context={
                "navigator_html": _navigator_html(request, fecha),
                "nutrition_editor_html": _nutrition_editor_html(request, fecha),
                "editor_html": _editor_html(request, fecha),
                "cardio_html": _cardio_day_html(request, fecha),
                "dia": day_from_date(fecha_date),
                "fecha_display": fecha_display(fecha),
                "semana": calculate_cycle_week(fecha_date, CICLO_START_DATE),
            },
        )
    )
```

con `_cardio_day_html(request, fecha)` → fragmento `cardio_day.html` (bloque: sesiones EXERCISE_SESSION con formularios `data-action="cardio-annotation-save"`, hidden `fecha`, OOB target `cardio-day`).

**Step 3:** `POST /cardio/annotation` (de la rama, re-añadir a `app.py` de main) con OOB `#cardio-day` (outerHTML) cuando `fecha` viene.

**Step 4: Tests de integración** — `/editor/popup` 200 con los 4 bloques; `POST /cardio/annotation` re-renderiza `#cardio-day`.

**Step 5: Commit** `feat: editor popup route and cardio day block`

---

### Task 7: `editor-popup.js` — apertura/cierre del popup

**Files:**
- Create: `static/js/editor-popup.js`
- Modify: `static/js/app.js` (registro)
- Modify: `templates/index.html` — contenedor `#editor-popup` (hidden) + botón `[data-action="open-editor-popup"]` en el header
- Modify: `static/js/htmx-lifecycle.js` — sync del editor tras swap en `#popup-body` (sustituir el branch de `register-modal-body` si existe en la versión conservada)

**Step 1: JS** — patrón del proyecto (delegado, sin handlers inline):

```javascript
export function openEditorPopup(fechaIso) { ... htmx.ajax('GET', '/editor/popup?fecha=' + iso, { target: '#popup-body', swap: 'innerHTML' }); mostrar overlay; ... }
export function closeEditorPopup() { ... }
export function initEditorPopup() {
    document.addEventListener('click', ...);  // open-editor-popup / close-editor-popup
    document.addEventListener('keydown', ...); // Escape
    document.body.addEventListener('htmx:afterSwap', ...); // fecha título + sync editor
}
```

**Step 2:** `htmx-lifecycle.js`: `e.detail.target.id === 'popup-body'` → `syncEditorFromContent()` + `fitRowsToPanel()` (mismo patrón que el branch de modal en la rama).

**Step 3: CSS** — estilos del popup en `static/css/components.css` o bloque `<style>` en index (colores anteriores: `bg-matte-950`, bordes `neutral-800`, overlay `bg-black/70`; `max-w-4xl`, centrado, `overflow-y-auto`, no full-screen).

**Step 4:** Verificación manual con servidor + e2e básico (abrir popup → editor visible; Esc cierra).

**Step 5: Commit** `feat: editors open in a floating popup`

---

## Fase 4 — Cascada grupo → músculo → ejercicios (barra superior)

### Task 8: `GET /nivel` — opciones de cascada + gráfica por foco

**Files:**
- Modify: `app.py` — ruta nueva `GET /nivel`
- Create: `templates/cascade_row.html` (fragmento de chips de una fila)
- Modify: `src/response_fragments.py` — allow-list: `"cascade-row"`

**Step 1: Contrato de la ruta:**

```
GET /nivel?tipo=grupo|musculo|ejercicio&foco=<valor>&padre=<valor>
```

- `tipo=grupo` sin foco → chips de categorías (Empuje/Tirón/Pierna/Core desde `get_categories`).
- `tipo=grupo` con `foco=<categoria>` → chips de músculos de esa categoría (JOIN `ejercicios.categoria`) + OOB gráfica `category`.
- `tipo=musculo` con `foco=<musculo>` → chips de ejercicios del músculo (lista compacta) + OOB gráfica `muscle_group`.
- `tipo=ejercicio` con `foco=<ejercicio>` → sin chips; body = `exercise_detail.html` (rutas restauradas) + OOB gráfica `exercise`.
- Respuesta: main content (siguiente fila de chips o detalle) + `chart_oob_wrapper(chart_html(...), target="unified-chart")`.

Reutiliza los builders de main (`chart_html`, `get_ejercicios_por_grupo`, `get_filters`, `get_exercise_raw_data`, `get_exercise_session_summary`).

**Step 2: Template `cascade_row.html`** — div `#cascade-row` con chips `.level-chip[data-action="set-focus"][data-tipo][data-foco][data-padre]` (estilos discretos del tema anterior, sin píldoras del rediseño).

**Step 3: Tests de integración** — `/nivel?tipo=grupo` devuelve chips de categorías; `foco=EMPUJE` devuelve chips de músculos + OOB `unified-chart`; `tipo=ejercicio&foco=Press` devuelve `exercise_detail` + OOB chart; foco desconocido → 200 con chips vacíos (sin 500).

**Step 4: Commit** `feat: progressive cascade endpoint for group->muscle->exercise`

---

### Task 9: Barra superior + `level-cascade.js` en `index.html`

**Files:**
- Modify: `templates/index.html` — header con píldoras de nivel (`data-action="set-level" data-tipo="global|grupo|musculo|ejercicio"`, colores anteriores), contenedor `#cascade-row`, botón "+ Registrar" (`data-action="open-editor-popup"`)
- Modify: `templates/index.html` — **quitar** del sidebar la sección de categorías musculares (la navegación vive arriba); conservar plantillas, alta contextual, últimas sesiones
- Create: `static/js/level-cascade.js`
- Modify: `static/js/app.js` (registro)

**Step 1: `level-cascade.js`** — patrón delegado:

- `set-level`: marca el nivel activo (`.level-btn.active`), limpia `#cascade-row` y pide `/nivel?tipo=grupo` (fila 1) o `/nivel?tipo=musculo` / `tipo=ejercicio` según nivel; `global` → `/select` (gráfica sistémica, lista global).
- `set-focus`: navega la cascada — `htmx.ajax('GET', '/nivel?tipo=...&foco=...&padre=...', { target: '#cascade-row', swap: 'outerHTML' })`; el OOB de la gráfica viaja en la misma respuesta.
- El detalle del ejercicio se muestra en `#history-section` (main content de la respuesta).

**Step 2: Ajustar `index.html`** — estructura del header (colores anteriores: texto `text-neutral-400`, borde `border-neutral-800`, activo `text-burgundy-400`):

```
[Gym Tracker] [Exportar CSV]      [+ Registrar] 
[Cuerpo entero | Grupo | Músculo | Ejercicio]   ← nivel
[#cascade-row]                                  ← chips progresivos
```

**Step 3:** Ajustar `dashboard-filters.js` (de main): mantener su API `getActiveFilter` para `chart-interaction.js`; los `cat-btn` del sidebar desaparecen — verificar que `chart-interaction.js` sigue funcionando con el clic de semana (usa `getActiveFilter`).

**Step 4:** e2e nuevo `tests/e2e/test_cascade_flow.py`: elegir Grupo → aparecen categorías; elegir Empuje → aparecen sus músculos; elegir músculo → aparecen ejercicios; elegir ejercicio → detalle + gráfica.

**Step 5: Commit** `feat: top-bar level cascade and register popup trigger`

---

## Fase 5 — Cierre

### Task 10: Restaurar/ajustar tests de UI

**Files:**
- Modify: `tests/test_app.py`, `tests/test_charts.py`, `tests/test_security.py` (restaurados de main)
- Modify: `tests/e2e/test_dashboard_flow.py`, `tests/e2e/test_nutrition_flow.py` (restaurados de main)

**Step 1:** Suite completa — los tests de main deben pasar (UI restaurado) salvo los que dependen de deltas nuevos.

**Step 2:** Ajustes esperados:
- `test_app.py`: + casos `/editor/popup`, `/nivel`, save con `descanso`.
- `test_charts.py`: hover enriquecido (aserciones nuevas de la rama se mantienen: sets_fallo, descanso_seg en raw).
- `test_security.py`: el payload hostil viaja por `/select` y `/` — igual que main (verificar `_assert_inert_fragment` sigue siendo la de main).
- e2e: los flujos de main usan el editor en la home — ahora el editor vive en el popup → helper `_open_popup(page)` antes de editar; el resto del flujo (fill/save/plantillas) intacto.

**Step 3: Commit** `test: adapt UI tests to popup editor and cascade`

---

### Task 11: Docs y archivo del plan del rediseño

**Files:**
- Modify: `docs/architecture/current-ui-contract.md` — apéndice "v3"
- Move: `docs/plans/2026-08-12-analysis-dashboard.md` → `docs/plans/archive/` con nota de rechazo en el header
- Modify: `AGENTS.md` — verificar §3 sigue correcto (no requiere cambio)

**Step 1:** Apéndice v3 en el contrato: popup (`#editor-popup`, `#popup-body`, `open-editor-popup`), cascada (`/nivel`, `#cascade-row`, `set-level`/`set-focus`), cardio (`/cardio/annotation`, `#cardio-day`), editor (descanso, RIR −5, badges).

**Step 2:** Mover el plan del rediseño al archivo con nota: `> RECHAZADO por el usuario (2026-08-12): UI preferida = anterior + popups + cascada.` al inicio.

**Step 3: Commit** `docs: UI contract v3 (popup + cascade) and archive rejected redesign plan`

---

### Task 12: Gates finales + verificación con BD real

**Step 1:**

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy app.py src tests
```

**Step 2:** Verificación con la BD real (sin crashes — el fix del envelope se conserva en `analysis_data.py`):

```bash
LIFESTYLE_DB_PATH=data/lifestyle.db uv run python -c "
from fastapi.testclient import TestClient
from app import app
with TestClient(app) as c:
    for p in ('/', '/nivel?tipo=grupo', '/editor/popup?fecha=2026-08-12'):
        r = c.get(p); print(p, r.status_code); assert r.status_code == 200
"
```

**Step 3:** Arranque manual `./scripts/start_server.sh` → verificación visual (popup, cascada, hover).

**Step 4: Commit final** si hay ajustes.

---

## Orden de ejecución y checkpoints

| Hito | Tasks | Validación |
|---|---|---|
| Restauración | 1-2 | Suite de datos verde; app importa |
| Datos en UI | 3-5 | descanso persiste; hover enriquecido; cardio helpers |
| Popup | 6-7 | `/editor/popup` 200; Esc cierra; e2e |
| Cascada | 8-9 | `/nivel` 200; grupo→músculo→ejercicio e2e |
| Cierre | 10-12 | Suite completa + e2e + gates + BD real |

## Riesgos

- Los tests de main asumen el editor en la home → se adaptan al popup en Task 10 (misma tarea que restaura los e2e).
- `dashboard-filters.js` de main está acoplado a `cat-btn` del sidebar → se elimina la sección de categorías del sidebar en Task 9; verificar `chart-interaction.js` (getActiveFilter) no rompe.
- Los datos de la rama (RIR/descanso/fallos/cardio) dependen de `database.py`/`models.py` de la rama — NO restaurarlos desde main.
