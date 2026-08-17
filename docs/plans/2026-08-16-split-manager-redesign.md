# Plan: Rediseño del Gestor de splits v4 — acordeón full-width + tarjetas de dimensiones invariantes

Fecha: 2026-08-16 · Rama: `feat/split-manager` (continuación de la v3)
**Estado: COMPLETADO (2026-08-16)** — Tasks 0-5 implementadas; gates verdes
(551 unit + 69 e2e, ruff, mypy, audit_consistency, cobertura 92.76%).

## Objetivo

Rediseñar la página de creación/edición de splits siguiendo el boceto del
cliente: dos zonas (catálogo fijo a la izquierda, splits a la derecha), cada
split como componente colapsable, y cada día como tarjeta de **dimensiones
invariantes** con dos scrolls internos (resumen jerárquico arriba, ejercicios
editables abajo). La página usa todo el ancho disponible, sin overflow
horizontal global.

## Decisiones confirmadas

1. **Formulario por split**: cada item del acordeón es autónomo (input de
   nombre + Editar/Guardar/Eliminar); se pueden editar varios splits
   independientes a la vez; el estado (open/edit/dirty/selección) es por split.
2. **Eliminar el panel ledger semanal** (`#split-summary-panel`): el total de
   series vive en la cabecera del split y cada tarjeta de día tiene su propio
   resumen jerárquico colapsable por grupo (server-rendered, recalculado al
   guardar).
3. **Eager server-rendered**: todos los boards se renderizan al cargar dentro
   de cada `<details>` (escala actual ≤ ~10 splits, límite 300 items/split).

## Correcciones incorporadas (evaluación crítica previa)

- **A1 — Pérdida de ediciones no guardadas**: los OOB de sección re-renderizan
  todos los items; un split con cambios locales no guardados que no sea el
  mutado perdería su DOM. Mitigación: snapshot de DOM de los items sucios en
  `htmx:beforeRequest` y restauración tras el swap de `#splits-section` (los
  items nuevos sin persistir se re-insertan al tope).
- **A2 — "Crear nuevo split" sin duplicar el template en JS**: nueva ruta
  `GET /split/nuevo` que devuelve el fragmento del item vacío en modo edición
  (GET puro, sin efectos); el JS lo inserta al tope de `#splits-list`.
- **A3 — Drops en boards no editables**: `disabled` de Sortable no garantiza
  rechazar drops con `group` compartido; guard `canEdit(item)` en
  `onMove`/`onAdd`/`onUpdate` de cada board (defensa doble).
- **B1 — Orden de eventos**: la captura de snapshot va en `htmx:beforeRequest`
  (en `afterSwap` el DOM ya fue reemplazado); el restore en
  `htmx:oobAfterSwap` (target `#splits-section`).
- **B2 — Item activo**: el chip del catálogo (click/Enter) agrega al día
  seleccionado del **último item interactuado**; si ningún item está en
  edición → notice "Pulsa Editar en un split…".
- **B3 — `updated_at` en local**: `CURRENT_TIMESTAMP` es UTC; la cabecera
  muestra `updated_short` formateado server-side con `astimezone()`.
- **B4 — Target size**: hit area ≥24×24 px en cabecera de día (day-select,
  copy-handle, clear-btn) sin cambiar el layout.
- **B5 — Borrar día explícito**: visible solo en modo edición (coherente con
  §8 "habilitar los botones de eliminar"); declarado en el contrato.
- **B6 — Perf**: cada OOB re-renderiza N boards; aceptable ≤ ~10 splits; nota
  de escala (lazy si N > 20).

## Arquitectura nueva

```
splits.html (full-width, sin max-w-7xl)
├── header: h1 + ← Dashboard + [Nuevo split]
├── .splits-layout
│   ├── .splits-catalog-col (280px, sticky, scroll propio; SIN título)
│   │   └── buscador + <details> por grupo (chips, HIIT)
│   └── .splits-editor-col
│       └── #splits-section
│           ├── estado vacío: "Todavía no hay splits guardados" + [Crear nuevo split]
│           └── #splits-list (items acordeón)
│               └── .split-accordion-item (id=split-item-{id}, data-split-id,
│                   data-editmode, data-nombre, data-max-items)
│                   ├── <details .split-accordion> (open solo si ?abrir)
│                   │   └── <summary>: chevron + nombre + N series ·
│                   │       actualizado dd/mm HH:mm (tamaño reducido)
│                   ├── .split-item-toolbar (fuera del summary, evita el bug
│                   │   de toggle del <summary>)
│                   │   └── form (hidden split_id + input nombre + [Editar]
│                   │       + hint "Modificado" + [Guardar]) + [Eliminar]
│                   └── .split-board-scroll (overflow-x: auto SOLO aquí)
│                       └── .split-columns (grid fija 7 × var(--split-card-w))
│                           └── 7 × .split-day-zone (altura FIJA)
│                               ├── .split-day-header (day-select aria-pressed
│                               │   + count + copy-handle + clear-btn)
│                               ├── .split-day-summary (altura FIJA, scroll
│                               │   interno): total día + por grupo:
│                               │   <button .split-summary-group-toggle
│                               │   aria-expanded aria-controls> + body
│                               │   .split-summary-group-body (hidden) con
│                               │   filas ejercicio — N series
│                               └── .split-day-items (flex:1, min-height:0,
│                                   scroll interno): .split-item-card + hint
```

## Tasks

### Task 1 — Servidor

- `src/models.py`: `SplitDaySummary` gana `by_group_exercises:
  dict[str, dict[str, int]]` (jerarquía por día).
- `src/split_service.py`: `compute_split_metrics` calcula `by_group_exercises`
  por día.
- `app.py`:
  - `_split_accordion_item_html(request, split_id | None, *, open_=False)`
    (contexto: days, split, metrics, editmode `"0" if split.id else "1"`,
    max_items, updated_short con `astimezone().strftime("%d/%m %H:%M")`).
  - `_split_section_html(request, abrir_id=None)`: estado vacío o items eager
    (orden `get_splits_summary`).
  - `_split_page_html` reescrita (contexto: catalog + splits_html + csrf).
  - `GET /splits?abrir=` (valida con `get_split_board`).
  - `GET /split/nuevo` → fragmento item vacío en edición (se define ANTES de
    cualquier `/{split_id}`; la ruta `/split/{split_id}` se RETIRA — sin
    callers tras el rework de JS y undo).
  - `POST /split/guardar` y `POST /split/eliminar/{id}`: OOB
    `#notice-container` + `#splits-section` (outerHTML).
  - `undo` kind `splits`: sin cambios (ya re-renderiza la sección).

### Task 2 — Templates

- `splits.html`: full-width, catálogo sin `panel-title` "Catálogo de
  ejercicios", header con botón "Nuevo split", `#splits-section`.
- Nuevo `partials/split_accordion.html` (contenido de la sección: vacío o
  lista) y `partials/split_accordion_item.html` (item completo).
- `partials/split_board.html` rework: solo los 7 `.split-day-zone` (incluido
  desde el item; parámetros: split, metrics, editmode, max_items).
- Eliminar `partials/split_list.html`.

### Task 0 — CSS (`static/css/components.css` + `scripts/audit_consistency.py`)

- Variables canónicas en `:root` (el JSON de design tokens valida solo
  colores; las CSS custom properties son la fuente de verdad permitida):
  `--split-catalog-w: 280px`, `--split-card-w: 184px`, `--split-card-h: 480px`,
  `--split-summary-h: 200px`, `--split-item-gap: 10px`.
- `.splits-page` full-width; `.split-board-scroll` (overflow-x auto + scrollbar
  fina); `.split-columns` grid fija (se elimina el breakpoint móvil `1fr`:
  las tarjetas conservan tamaño y el board scrollea).
- `.split-day-zone` altura fija; `.split-day-summary` y `.split-day-items` con
  `overflow-y: auto` + `scrollbar-width: thin` (barras delgadas/sutiles).
- Edit mode por item: `.split-accordion-item[data-editmode="0"] .row-btn,
  .split-day-clear-btn, .split-day-copy-handle { display: none }` (reemplaza el
  selector `#split-board-week[data-editmode="0"]`) + badge "Editando" +
  `aria-pressed` en el botón Editar.
- Acordeón: `.split-accordion-*`, `.split-item-toolbar`,
  `.split-summary-group-toggle` (+focus-visible, chevron), `.split-empty-state`.
- Target size ≥24×24 (B4) en los controles de la cabecera de día.
- `COMPONENT_CLASSES`: añadir las nuevas, retirar las ledger muertas.

### Task 3 — JS (`static/js/splits.js`)

- Estado por item: `state.items: Map<key, {editmode, dirty, selectedDay}>`
  (key = `data-split-id` o id DOM para items nuevos), `activeItemId`,
  `maxItems`, uidSeq/newSeq, snapshot map, `pendingMutation`.
- Acciones delegadas re-scoped por `el.closest('.split-accordion-item')`:
  split-edit, split-save (nombre obligatorio + `syncSplitForm(itemEl)` +
  requestSubmit), split-delete (confirm), split-item-remove, split-day-clear,
  split-day-copy (shift+click → día seleccionado del item), split-day-select
  (aria-pressed por item), split-add-item (item activo; guard editmode),
  split-new.
- **Snapshot (A1/B1)**: `htmx:beforeRequest` en /split/guardar|/eliminar/*|/undo
  → captura {open, editmode, dirty, selectedDay, nombre} de TODOS los items y
  outerHTML de los sucios/nuevos. Restore en `htmx:oobAfterSwap` con target
  `#splits-section`: restaurar open (todos), DOM de sucios (salvo el guardado),
  re-insertar nuevos (salvo si la mutación fue la creación del propio item).
  Tras restore: re-init sortables + handles + estados.
- **Guard A3**: `onMove` devuelve `false` (sin drop-target) si el destino no
  está en un item editable; `onAdd`/`onUpdate` validan `canEdit(item)`.
- Catálogo `disabled` según item activo; notice (throttled) al intentar
  arrastrar/agregar sin item editable. Fallback Sortable caído: notice visible
  "El arrastre no está disponible; agrega ejercicios con clic." (además del
  console.warn actual).
- `updatePreview(itemEl)`: counts + hints + rebuild del resumen por día
  preservando los grupos expandidos (`data-summary-group`).
- `splitNew()`: `htmx.ajax('GET','/split/nuevo')` → inserta el item al tope
  (creando `#splits-list` si el estado era vacío), renombra id a
  `split-item-nuevo-N`, registra estado, focus en el input nombre, notice.
- Init resiliente (guard + try/catch por sub-init + retry en `load`).

### Task 4 — Tests

- Unit (`tests/test_split_routes.py` + `test_split_service.py`):
  - servicio: `test_metricas_by_group_exercises_por_dia`.
  - rutas: página con items colapsados y toolbar; estado vacío; `?abrir` abre
    en view; `GET /split/nuevo` (fragmento editable, 7 zonas); guardar OOB
    sección con item actualizado; eliminar; undo; **retirar el test de
    `GET /split/{id}`** (ruta eliminada); reescribir los asserts de ledger →
    toggles de grupo por tarjeta.
- E2E (`tests/e2e/test_splits_flow.py`, reescritura): helpers item/expand;
  invariantes de tamaño (rect de tarjeta idéntico al: entrar/salir de edición,
  expandir grupo, agregar item, cerrar/reabrir item, guardar);
  `document.documentElement.scrollWidth <= clientWidth` en desktop y móvil;
  acordeón (colapsados al cargar, independencia); estado vacío → "Crear nuevo
  split"; resumen jerárquico expandible + recálculo tras guardar/recargar;
  DnD (catálogo→día, reorden, mover entre días, shift duplica, day-copy);
  **drag a board no-editable no muta (A3)**; **dos items en edición: guardar
  uno conserva el otro (A1)**; clic-add; borrar día; eliminar split; undo;
  móvil apilado con scroll solo en board; item guardado sube al tope.

### Task 5 — Docs + gates + verificación

- `docs/architecture/current-ui-contract.md`: reescribir la sección Gestor de
  splits (layout full-width, acordeón con toolbar, tarjeta invariante con dos
  scrolls internos, resumen jerárquico colapsable, rutas nuevas/retiradas,
  snapshot/restore, guards A3).
- `AGENTS.md`: actualizar el inventario de partials y el bullet de rutas.
- Gates: `uv sync --locked`, pytest unit + e2e + cobertura, ruff, mypy,
  `scripts/audit_consistency.py`, `./scripts/build_css.sh`.
- Verificación visual local: 1440×900, 1920×1080, móvil (390×844): ancho usado,
  sin overflow global, catálogo izquierda / splits derecha, tarjetas
  invariantes, scrolls internos finos, DnD y clic operativos, estado vacío.

## Archivos afectados

- `src/models.py`, `src/split_service.py`, `app.py`
- `templates/splits.html`, `templates/partials/split_board.html`,
  `templates/partials/split_accordion.html` (nuevo),
  `templates/partials/split_accordion_item.html` (nuevo),
  `templates/partials/split_list.html` (eliminado)
- `static/js/splits.js`, `static/css/components.css`, `static/css/tailwind.css`
- `scripts/audit_consistency.py`, `docs/architecture/current-ui-contract.md`,
  `AGENTS.md`, `docs/plans/2026-08-16-split-manager-redesign.md`
- `tests/test_split_routes.py`, `tests/test_split_service.py`,
  `tests/e2e/test_splits_flow.py`
