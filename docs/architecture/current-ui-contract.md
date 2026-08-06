# Current Dashboard UI Contract

> **Purpose:** Frozen behavioural contract captured before the frontend atomization programme (2026-08-06). Any intentional change to IDs, `data-*` attributes, form field names, htmx targets or `hx-swap-oob` markers documented here requires its own browser test and a contract-change commit.

**Baseline suite:** `uv run pytest -q` → **93 passed, 1 warning** (StarletteDeprecationWarning: `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead).

---

## 1. Routes and their contract

### `GET /` (index, full HTML)

- Renders `index.html` extending `base.html`.
- Serves: category navigation, exercise list, date navigator, session editor, unified chart (systemic PFR), exercise-create form, plantillas (templates) list.
- Injects `categoria_map_json` (JSON string of exercise → category map) via `const CATEGORIA_MAP = {{ categoria_map_json | safe }};` into `base.html` (block after `{% block content %}`).
- Injects `app_config_json` (`categoria_map` + `csrf_token`) via `<script id="app-config" type="application/json">` (data, never executed).
- Page-level `<style>` blocks remain in `index.html` (htmx-indicator, chart fade-in). All page JS was moved to `static/js/dashboard-filters.js`.

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
| `#app-config` | `type="application/json"` block with `categoria_map` + `csrf_token`, parsed by `app.js` |
| `#plantilla-applied` | Hidden marker inside editor OOB response after applying a plantilla; removed client-side to trigger baseline reset |
| `body[data-app-ready]` | Set to `1` by `app.js` after bootstrap; e2e waits on it (no `window.*` bridge exists) |

## 3. Client event contract (data-action delegation)

There are **no inline event handlers** in templates. Every interactive element
carries inert `data-action` attributes; one delegated `click` listener per owning
module reads `event.target.closest('[data-action]')`, validates the action name,
and ignores anything else. No mutable state is exposed on `window`.

| `data-action` | Element | Owning module | Values |
|---|---|---|---|
| `select-category` | `.category-btn` | `dashboard-filters.js` | `data-category` |
| `select-exercise` | `.filter-btn` | `dashboard-filters.js` | `data-exercise` |
| `select-date` | `.date-num` | `date-navigation.js` | `data-iso` |
| `jump-date` | `.today-btn` | `date-navigation.js` | `data-iso` |
| `scroll-dates` | `.nav-arrow` | `date-navigation.js` | `data-dir` |
| `toggle-edit` | `.pencil-btn` | `editor.js` | — |
| `toggle-template-form` | `.save-template-btn` | `editor.js` | — |
| `cancel-template-form` | `.btn-x` (form wrap) | `editor.js` | — |
| `confirm-template-save` | `.btn-check` (form wrap) | `editor.js` | — |
| `delete-session` | `.delete-session-btn` | `editor.js` | — |
| `row-add` / `row-remove` | `.row-btn` | `editor.js` | — |
| `apply-template` | `.pt-btn-burgundy` | `templates.js` | `data-template-id` |
| `edit-template` | `.pt-btn` | `templates.js` | `data-template-id` |
| `delete-template` | `.pt-btn` | `templates.js` | `data-template-id`, `data-template-name` |
| `template-row-add` / `template-row-remove` | `.row-btn` (edit form) | `templates.js` | — |
| `refresh-templates` | `.btn-x` (edit form) | `templates.js` | — |

Delegated listeners are bound once at `document` (stable root) inside the module
`init*` functions called from `app.js` bootstrap; htmx fragment swaps never
re-register them. The `#confirm-modal` buttons keep direct listeners wired once
in `htmx-lifecycle.js`.

## 4. Client behaviour summary (ES modules)

- **State (`state.js`):** module-scoped shared state via getters/setters only:
  `pendingNav`, `confirmCbs`, `saveRequested`, `sortableRows`,
  `plantillaAppliedPending`, drag state, `csrfToken`, `categoriaMap`,
  `currentIso` (falls back to the selected `.date-num`). Plus pure helpers:
  `serializeForm`/`captureBaseline`/`isDirty`, `fmtNum`, `editorEditmode`,
  `currentFecha`, confirm-dialog helpers.
- **Notices (`notices.js`):** `scheduleNotices()` (auto-dismiss + fade),
  `flashEditorNotice(msg, type)`.
- **Editor (`editor.js`):** edit-mode machine (`syncEditorFromContent`,
  `setPanelReadonly`, `enterEditMode`, `exitEditMode`, `toggleEdit`,
  `updateEditActions`, `syncEditButtons`), rows (`addRowAfter`, `removeRow`,
  `renumberRows`, `fitRowsToPanel`), `recalcRM`, `submitSave`,
  `eliminarSesion`, `initEditorActions` (delegated listener).
- **Row sortable (`row-sortable.js`):** `initRowSortable(onEnd)` /
  `syncSortableState` on `#set-rows`; editor passes the renumber/dirty callback.
- **Templates (`templates.js`):** plantilla flow (`aplicarPlantilla` debounce,
  `eliminarPlantilla`, `editarPlantilla`, `refreshPlantillas`,
  `suggestedTemplateName` via `getCategoriaMap()`, `syncTemplateEjercicios`,
  `guardarPlantillaToggle`, `confirmEntrenoSave`, `ptAddRow`/`ptRemoveRow`,
  `initTemplateSortable`, `initEntrenoDnD`, `persistDragOrder` (fetch with
  `X-CSRF-Token`)), `initTemplateActions` (delegated listener).
- **Date navigation (`date-navigation.js`):** `doNav(iso, force)`,
  `requestNavigate(iso)`, `updateDateDot(fecha, has)`, `initDateNavigation`
  (delegated listener + initial scrollIntoView).
- **Dashboard filters (`dashboard-filters.js`):** category/exercise selection,
  highlighting, `resetToGlobal`, Esc handler, exercise-create refresh,
  `initDashboardFilters` (delegated listener).
- **htmx lifecycle (`htmx-lifecycle.js`):** `initLifecycle()` wires the
  confirm-modal buttons and the delegated `htmx:afterSwap`/`afterSettle`/
  `afterRequest`, `submit` (capture, `#session-form`), `input`/`change`,
  `keydown` (Ctrl/Cmd+Z undo, Enter in template-name input → `confirmEntrenoSave`).
- **Bootstrap (`app.js`):** reads `#app-config` (`categoria_map`,
  `csrf_token`), injects `X-CSRF-Token` on every htmx request via
  `htmx:configRequest`, then runs the module initializers once on
  `DOMContentLoaded`; sets `body[data-app-ready]`.

## 5. Server-side orchestration notes

- `app.py` is thin: request parsing, one mutation-service call, fragment
  rendering. `src/dashboard_service.py` builds view models and translates
  errors; `src/mutation_service.py` owns backup/snapshot/undo-stack sequences;
  `src/response_fragments.py` renders OOB fragments through Jinja partials
  (autoescaping is the only HTML boundary; chart fragments are nonced).
- The in-memory `UNDO_STACK` (deque, maxlen 10) lives in `src/mutation_service.py`.
- RM formula client + server: `kg * (1 + 0.0333 * (reps + 1 + rir))`, rounded to 1 decimal.
- OOB responses: notices and editor markers/wrappers render via
  `templates/partials/oob_*.html`; no request-derived value is concatenated
  into HTML.
