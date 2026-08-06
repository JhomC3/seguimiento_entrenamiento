# Current Dashboard UI Contract

> **Purpose:** Frozen behavioural contract captured before the frontend atomization programme (2026-08-06). Any intentional change to IDs, `data-*` attributes, form field names, htmx targets or `hx-swap-oob` markers documented here requires its own browser test and a contract-change commit.

**Baseline suite:** `uv run pytest -q` → **93 passed, 1 warning** (StarletteDeprecationWarning: `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead).

---

## 1. Routes and their contract

### `GET /` (index, full HTML)

- Renders `index.html` extending `base.html`.
- Serves: category navigation, exercise list, date navigator, session editor, unified chart (systemic PFR), exercise-create form, plantillas (templates) list.
- Injects `categoria_map_json` (JSON string of exercise → category map) via `const CATEGORIA_MAP = {{ categoria_map_json | safe }};` into `base.html` (block after `{% block content %}`).
- Includes inline `<style>` blocks (theme, htmx-indicator, chart fade-in) and page-level JS in `index.html` (`toggleCategory`, `toggleExercise`, `highlightExerciseBtn`, `resetToGlobal`, Esc handler, `htmx:afterRequest` for exercise-create refresh).

### `GET /fecha/editor?fecha=<YYYY-MM-DD>`

- Returns `session_editor.html` fragment (no full document) via `HTMLResponse`.
- Used by htmx with `target: '#session-editor-wrap'`, `swap: 'innerHTML'` (from `doNav` in `base.html` and the Cancelar button in `session_editor.html`).
- Editor state markers: `#editor-state[data-readonly][data-has-data]` (hidden).

### `POST /entrenamiento/session/save`

- Form fields: `fecha` (ISO), `ejercicio[]`, `kg[]`, `reps[]`, `rir[]` (parallel arrays; submit from `#session-form` with `hx-swap="none"`).
- OOB markers on success: `#editor-notice` (innerHTML, success notice, `data-dismiss="3000"`), `#save-outcome` (outerHTML, `data-ok="1"`, hidden), and either `#editor-state` (outerHTML, `data-readonly="1" data-has-data="1"`, hidden) when rows remain, or `#session-editor-wrap` (innerHTML, fresh editor) when empty.
- OOB markers on validation failure (`ValueError`): `#editor-notice` (innerHTML, error notice, `data-dismiss="4500"`), `#save-outcome` (outerHTML, `data-ok="0"`, hidden).
- Client-side gating: submit intercepted; if `#session-editor[data-editmode] !== '1'` the submit is prevented.
- Side effects: DB backup, undo-stack push (`sesion` kind, before/after rows).

### `POST /entrenamiento/session/eliminar`

- Form field: `fecha` (ISO). Triggered by `eliminarSesion()` after confirm dialog.
- OOB markers: `#editor-notice` (success "Entreno eliminado."), `#save-outcome` (`data-ok="1"`), `#session-editor-wrap` (innerHTML, fresh readonly editor).
- Side effects: DB backup, undo-stack push with empty `after`.

### `POST /ejercicio/nuevo`

- Form fields: `ejercicio`, `grupo_muscular`, `categoria` (from `#exercise-create-form`, `hx-swap="none"`).
- OOB markers: `#notice-container` (innerHTML success/error notice), and on success `#exercise-create` (outerHTML, refreshed form).
- Error messages: missing name / missing group / invalid category / duplicate exercise (case-insensitive).

### `GET /plantillas?editar=<id>` (also `/plantillas` bare)

- Returns `plantillas_list.html` fragment; used with `target: '#plantillas-section'`, `swap: 'innerHTML'`.
- `editar` activates the inline edit form for that plantilla card.

### `POST /plantilla/guardar`

- Form fields: `nombre`, `ejercicio[]` (hidden inputs synced by `syncTemplateEjercicios`). Form is `#save-template-form` with `hx-swap="none"`.
- OOB markers: `#notice-container` (success "Entreno guardado." / "Entreno actualizado." or error), `#plantillas-section` (outerHTML, refreshed list) via `_plantillas_oob`.
- Side effects: snapshot/undo-stack push (`entrenos` kind).

### `POST /plantilla/editar/{id}`

- Form fields: `nombre`, `ejercicio[]` (same sync pattern). Target `#plantillas-section` through `_plantillas_oob`.
- On `ValueError`: returns OOB list with `editing_id` kept and error text shown; success returns notice + refreshed list.
- Side effects: undo-stack push (`entrenos` kind).

### `POST /plantilla/eliminar/{id}`

- No form fields. Triggered by `eliminarPlantilla(id, nombre)` (JS `confirm()` first) with `target: 'body'`, `swap: 'none'`.
- OOB markers: `#notice-container` (success), `#plantillas-section` (outerHTML).
- Side effects: undo-stack push (`entrenos` kind).

### `POST /plantilla/reordenar`

- Form fields: `id[]` (order of plantilla ids). Sent via `fetch` with `Content-Type: application/x-www-form-urlencoded` from `persistDragOrder()`.
- Returns empty `HTMLResponse` (200). Side effects: reorders rows, undo-stack push.

### `GET /plantilla/aplicar/{id}?fecha=<YYYY-MM-DD>`

- No form fields; triggered by `aplicarPlantilla(id)` (button or drop on editor panel) with `target: '#session-editor-wrap'`, `swap: 'none'`.
- On success: OOB `#editor-notice` (success "Entreno aplicado."), `#session-editor-wrap` (innerHTML, editor in force-editable mode) which includes a hidden `<div id="plantilla-applied">` marker consumed by client to reset dirty baseline.
- On `ValueError`: OOB `#editor-notice` error only.
- Client gate: requires edit mode; if `#editor-state[data-has-data] == '1'`, shows confirm dialog "¿Reemplazar el entrenamiento del día?" before applying.

### `POST /undo`

- Form field: `fecha` (ISO, current editor date; may be empty).
- Success OOB: `#notice-container` ("Acción deshecha."), and for `sesion` entries also `#undo-result` (outerHTML, `data-fecha`, `data-has-data`, hidden) plus `#save-outcome` (`data-ok="1"`) and `#session-editor-wrap` (innerHTML) when undoing the current date.
- Empty-stack OOB: `#notice-container` error "Nada que deshacer.".
- `entrenos` entries: OOB `#plantillas-section` (outerHTML) refreshed.
- Side effects: DB backup; pops from in-memory `UNDO_STACK` (deque, maxlen 10).

### `GET /exportar/csv`

- Returns `text/csv` download of `training_sets` (`Content-Disposition: attachment; filename="entrenamientos.csv"`), ordered by `fecha, set_orden`.

### `GET /select?grupo=<name>` (and `/select` bare)

- Returns `exercise_list.html` fragment + OOB `#unified-chart` (innerHTML).
- `grupo` empty/None → global exercise list + systemic chart; otherwise filtered by muscle group + muscle-group chart.
- Used with `target: '#exercise-section'` (htmx.ajax from `toggleCategory`/`resetToGlobal`).

### `GET /grupo/reset?grupo=<name>`

- Returns `<div></div>` + OOB `#unified-chart` (innerHTML, muscle-group chart).
- Used with `target: '#history-section'` when an exercise is deselected.

### `GET /ejercicio?ejercicio=<name>`

- Returns `exercise_detail.html` (raw sets table + per-session summary table) + OOB `#unified-chart` (innerHTML, exercise chart).
- Used with `target: '#history-section'`.

---

## 2. Frontend invariants (stable selectors)

| Selector | Owner / purpose |
|---|---|
| `#session-editor` | Editor card root; carries `data-editmode` (`0`/`1`) and `data-baseline` (serialized rows JSON for dirty tracking) |
| `#session-editor-wrap` | Inner editor container; htmx swap target for editor replacements |
| `#session-form` | Editor form; `hx-post="/entrenamiento/session/save"`, `hx-swap="none"`; fields `fecha`, `ejercicio[]`, `kg[]`, `reps[]`, `rir[]` |
| `#set-rows` / `.set-row` | Rows table body / row; `#set-rows` is the Sortable container |
| `.ej-select`, `.rm-cell`, `.set-num`, `.row-actions`, `.row-btn` | Per-row exercise select, RM cell, row number, action cell/buttons |
| `#edit-actions` | Save/Cancel row; `.invisible` toggling |
| `#editor-state` | Hidden state carrier: `data-readonly`, `data-has-data` |
| `#editor-notice` | OOB notice target inside editor card |
| `#save-outcome` | OOB save result marker: `data-ok` (`0`/`1`), hidden |
| `#undo-result` | OOB undo marker: `data-fecha`, `data-has-data`, hidden |
| `#notice-container` | Global notice OOB target (top of body) |
| `#plantillas-section` | Plantillas list OOB/swap target (outerHTML) |
| `#plantillas-list`, `.pt-card` | List container / card (`data-pt-id`, `data-pt-nombre`); native HTML5 drag & drop reorder |
| `#plantilla-edit-rows`, `.pt-row`, `.pt-select` | Template edit rows (Sortable container) |
| `#save-template-form-wrap`, `#save-template-form`, `input[name="nombre"]` | Template save form wrapper/flow |
| `#confirm-modal`, `#confirm-cancel`, `#confirm-save`, `#confirm-msg` | Shared confirm dialog (unsaved changes, replace, delete) |
| `#exercise-create`, `#exercise-create-form` | New-exercise form container (OOB outerHTML target) |
| `#exercise-section`, `#history-section` | htmx.ajax targets for category/exercise navigation |
| `#unified-chart` | Single chart OOB target (innerHTML) |
| `#date-navigator`, `#date-strip`, `.date-num`, `.date-dot`, `.nav-arrow`, `.today-btn` | Date navigator; `.date-num` buttons carry `data-iso` and `.selected` |
| `#app-config` (future) | Planned replacement for inline `CATEGORIA_MAP` script |
| `#plantilla-applied` | Hidden marker inside editor OOB response after applying a plantilla; removed client-side to trigger baseline reset |
| `body[data-*]` globals | `currentIso` (page-scoped `let` from `date_navigator.html`), `currentCategory`/`currentExercise` (from `index.html`), `pendingNav`, `confirmCbs`, `saveRequested`, `sortableRows`, `plantillaAppliedPending`, `dragCard`, `dragOrderStart`, `dropHandled`, `droppedOnList`, `applyInFlight`, `dragGhost` (from `base.html`) |

## 3. Client behaviour summary (base.html script block)

- **Notices:** `scheduleNotices()` — schedules auto-dismiss (`data-dismiss`) and fade-out for `.notice` elements.
- **Confirm dialog:** `showConfirmDialog(onSave, onDiscard)` / `hideConfirmDialog()`; callbacks stored in `confirmCbs`.
- **Editor state machine:** `editorEditmode()`, `captureBaseline()`, `isDirty()`, `syncEditorFromContent()`, `setPanelReadonly()`, `enterEditMode()`, `exitEditMode()`, `toggleEdit()`, `updateEditActions()`, `syncEditButtons()`, `flashEditorNotice()`.
- **Rows:** `addRowAfter()`, `removeRow()`, `renumberRows()`, `fitRowsToPanel()` (single measured row height, `--table-h` CSS var, 17.5 visible rows + buffer).
- **Row sortable:** `initRowSortable()` / `syncSortableState()` (Sortable on `#set-rows`, disabled outside edit mode).
- **Entreno DnD (native HTML5):** `getDragAfterElement()`, `restoreDragOrder()`, `persistDragOrder()`, `initEntrenoDnD()` — reorder in list, drop on editor panel applies plantilla (with replace confirm when data exists).
- **Plantillas:** `editorHasData()`, `currentFecha()`, `aplicarPlantilla(id)` (debounce `applyInFlight`), `eliminarPlantilla(id, nombre)`, `editarPlantilla(id)`, `refreshPlantillas()`, `suggestedTemplateName()` (uses `CATEGORIA_MAP`), `syncTemplateEjercicios()`, `setEntrenoBtnVisible()`, `openEntrenoForm()`, `guardarPlantillaToggle(force)`, `confirmEntrenoSave()`, `ptAddRow()`, `ptRemoveRow()`, `initTemplateSortable()`, `entrenosOrder()`.
- **Undo:** `undoAction()` (Ctrl/Cmd+Z or button) → `POST /undo`.
- **Save:** `submitSave()` → `#session-form.requestSubmit()`.
- **Navigation:** `doNav(iso, force)` (pendingNav logic, `.selected` class, scrollIntoView), `requestNavigate(iso)` (dirty → confirm dialog).
- **Post-save sync:** `updateDateDot(fecha, has)`, `fmtNum()`, `recalcRM()`.
- **htmx lifecycle (delegated on document/body):**
  - `DOMContentLoaded` → scheduleNotices, syncEditorFromContent, initRowSortable, initTemplateSortable, initEntrenoDnD, fitRowsToPanel.
  - `htmx:afterSwap` → scheduleNotices, handleEditorState; on `#session-editor-wrap` → syncEditorFromContent + plantilla-applied handling + initRowSortable + fitRowsToPanel; on `#plantillas-section` → initTemplateSortable.
  - `htmx:afterSettle` → plantillaAppliedPending baseline reset.
  - `htmx:afterRequest` → scheduleNotices, handleEditorState, initTemplateSortable, initEntrenoDnD, template-form close, save/undo outcome handling (`saveRequested`, `#undo-result`, `#save-outcome`, pendingNav follow-through).
  - `submit` (capture, `#session-form`) → gate on edit mode, set `saveRequested`.
  - `input`/`change` (delegated, `#session-form`) → updateEditActions, syncTemplateEjercicios.
  - `keydown` (capture) → Ctrl/Cmd+Z undo (not inside fields), Enter in template-name input → `confirmEntrenoSave()`.

## 4. Server-side orchestration notes (for later extraction)

- `app.py` helpers performing DB access today: `get_filters`, `get_ejercicios_por_grupo`, `_fechas_con_datos`, `export_csv` (raw pandas read), plus view-builder helpers `_chart_html`, `_navigator_html`, `_editor_html`, `_exercise_form_html`, `_plantillas_list_html`, `_plantillas_oob`, `_build_sets_from_form`.
- In-memory `UNDO_STACK` (deque, maxlen 10) lives in `app.py`.
- RM formula client + server: `kg * (1 + 0.0333 * (reps + 1 + rir))`, rounded to 1 decimal.
- `categoria_map_json` is the only executable-JS interpolation today; it must be replaced by the `#app-config` JSON-data pattern (Task 1.3).
