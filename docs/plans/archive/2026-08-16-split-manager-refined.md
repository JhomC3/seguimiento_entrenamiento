# Plan: Split Manager v5 — board full-width, resumen semanal en cabecera, acciones como iconos, tarjetas más altas

Fecha: 2026-08-16 · Rama: `feat/split-manager` (continuación de v4)
**Estado: COMPLETADO (2026-08-16)** — Tasks 0-5 implementadas; gates verdes
(551 unit + 73 e2e, ruff, mypy, audit_consistency, cobertura 92.80%) y
verificación geométrica OK en 1440×900, 1920×1080 y 390×844 (sin overflow
global, board full-width sin hueco tras Domingo, columnas iguales 146/215px,
tarjetas 620/560px invariantes, strip sin fecha, iconos agrupados con Guardar
deshabilitado).
Referencia: boceto del cliente (§1-§10) + evaluación crítica (correcciones P0/P1 incorporadas).

## Decisiones de diseño

1. **Iconos en fila propia** (confirmado por el usuario): el `<summary>` queda solo con texto estático (chevron + nombre + resumen semanal); Editar/Guardar/Eliminar como iconos agrupados a la derecha en la fila superior del contenido (`.split-item-toolbar`), junto al input de nombre. Los controles dentro del `<summary>` disparan el toggle del acordeón (bug conocido).
2. **Cabecera de una sola zona visual**: `<summary>` (chevron, nombre truncado, strip con `overflow-x: auto`) **sin borde inferior** + `.split-item-toolbar` con `border-bottom` — las dos filas leen como un bloque; el board es un bloque diferenciado (fondo `matte-950` + `border-top`). No dependencia solo de color: borde + fondo + jerarquía tipográfica.
3. **Fecha eliminada de la UI**: se elimina `updated_short`/“actualizado” de template y app.py; `updated_at` se conserva en BD solo para ordenar (`get_splits_summary` sin cambios).
4. **Grid estirable**: `repeat(7, minmax(var(--split-day-min-width), 1fr))` con `width: 100%`; **`--split-day-min-width: 148px` FIJO** (7×148+6×8 = 1084 ≤ editor a 1440 ≈ 1096 → **sin scroll del board a 1440**; se verifica con assert). El scroll horizontal queda confinado a `.split-board-scroll`.
5. **Estructura del día corregida (P0-1)**: copy-handle y clear-btn se mueven del header del día a la fila de la etiqueta "Ejercicios" (el header queda solo día+count y cabe en 148px; el boceto §7 no muestra handles en el header). Selectores e2e zone-scoped intactos.
6. **Sin fila de total en el resumen del día (P0-2/§9)**: el total ya está en el header de la tarjeta (`[data-day-count]`); el resumen empieza por los grupos (como el boceto §7). Se elimina la fila `.split-summary-total` del summary (server y JS).
7. **Alturas por breakpoint (fijas dentro de cada breakpoint)**: `--split-day-height: 620/580/560px` (≥1024 / 640–1023 / <640); `--split-summary-h: 260/240/220px`; `--split-toolbar-h: 40px`; `--split-board-pad-y: 10px`; `--split-expanded-height: calc(day + toolbar + 2*pad + 3px)` (≈683 desktop; el ejemplo del cliente 680 es orientativo) aplicado como `min-height` de `.split-accordion-content` — coincide con la altura natural (solo crece si el contenido excede, p. ej. zoom de accesibilidad; nunca se recorta).
8. **Guardar deshabilitado sin cambios**: `saveBtn.disabled = !(dirty || esNuevo)` — en vista siempre deshabilitado ocupando su mismo box (28×28, sin salto de layout); se habilita con `markDirty` (mutaciones del board **y tecleo del nombre** — listener `input` scoped). El botón deja de ocultarse con CSS en vista.
9. **Zonas independientes** (requisito central): cabecera, resumen (strip), board y tarjetas no se empujan — alturas fijas, `min-width:0`, truncado, scrolls internos delgados.

## Tasks

### Task 0 — CSS (`static/css/components.css` + `scripts/audit_consistency.py`)
- **Tokens**: eliminar `--split-card-w: 184px` y `--split-card-h: 480px`; añadir `--split-day-min-width: 148px`, `--split-day-height`/`--split-summary-h` con overrides `@media` (640–1023, <640) sobre `:root`, `--split-toolbar-h: 40px`, `--split-board-pad-y: 10px`, `--split-expanded-height: calc(var(--split-day-height) + var(--split-toolbar-h) + 2*var(--split-board-pad-y) + 3px)`, `--split-item-gap: 8px`.
- `.split-columns`: `grid-template-columns: repeat(7, minmax(var(--split-day-min-width), 1fr)); width: 100%;`.
- `.split-day-zone`: `height: var(--split-day-height)`; `.split-day-summary`: `flex: 0 0 var(--split-summary-h)`.
- `.split-accordion-content` (nuevo): `display:flex; flex-direction:column; min-height: var(--split-expanded-height);`. `.split-board-scroll`: `flex:1; min-height:0; padding: var(--split-board-pad-y) 12px; background: matte-950; border-top: 1px solid neutral-800;` (scrollbars finas existentes).
- `.split-item-toolbar`: altura fija `var(--split-toolbar-h)`, `padding: 0 14px`, `border-bottom`, sin wrap; `.split-item-actions { margin-left: auto; display:flex; gap:6px; }` (sin `space-between` artificial).
- **Nuevos componentes**: `.split-summary-strip` (flex:1, `min-width:0`, `overflow-x:auto`, `white-space:nowrap`, scrollbar 5px, fondo sutil + `border-left`, `focus-visible`, `strong` burdeos) + `.split-summary-strip-sep`; `.split-action-btn` (28×28, icono 14px, hover/active/focus-visible burdeos, `[disabled]` opacity .4 manteniendo tamaño); `.split-day-section-label` (12px/900/uppercase/tracking burdeos, `min-height:22px`) + `.split-day-section-actions`.
- Eliminar `.split-accordion-meta` y el borde del summary (`[open] > .summary` border-bottom ya no aplica). En vista: ocultar solo `.split-name-input` (Guardar visible deshabilitado); handles ocultos en vista (regla existente adaptada a la nueva posición).
- `COMPONENT_CLASSES`: añadir `split-accordion-content`, `split-summary-strip`, `split-summary-strip-sep`, `split-action-btn`, `split-day-section-label`, `split-day-section-actions`; retirar `split-accordion-meta`.

### Task 1 — Servidor (`app.py`)
- Eliminar `_split_updated_short()` y `updated_short` del contexto del item; limpiar el import de `datetime` si queda sin uso. Sin más cambios (el strip se calcula en el template desde `metrics.by_group` con `| sort(attribute='1', reverse=true)`).

### Task 2 — Templates
- `partials/split_accordion_item.html`:
  - `<summary>`: chevron + nombre + `<span class="split-summary-strip" role="region" aria-label="Resumen semanal del split" tabindex="0">` → `<strong>{{ total_series }}</strong> series` + por grupo `· Grupo <strong>n</strong>` (sort desc por series; empates en orden de inserción). Item nuevo: `0 series`.
  - `.split-accordion-content` envolviendo toolbar + board.
  - `.split-item-toolbar`: form (input nombre) + badge "Editando" + hint "Modificado" + `.split-item-actions` con 3 `.split-action-btn` (lápiz `split-edit` con `aria-pressed`; guardar `split-save` con `disabled` server-side si `split` existe y aria-label "Guardar el split"; papelera `split-delete` conservando `data-split-id` y **`data-split-nombre`** para el confirm) — SVGs stroke 14px con aria-label + title.
  - Eliminar `span.split-accordion-meta`.
- `partials/split_board.html`:
  - Header de tarjeta: solo day-select + `[data-day-count]` (count con `margin-left:auto`).
  - `.split-day-section-label` "Resumen" antes del summary; el summary **sin fila de total** (solo grupos).
  - `.split-day-section-label` "Ejercicios" con `.split-day-section-actions` (copy-handle + clear-btn movidos aquí) antes de `.split-day-items`.

### Task 3 — JS (`static/js/splits.js`)
- `updatePreview`: eliminar el update de `[data-split-total-series]`; añadir `rebuildStrip(itemEl, total)` (mismos totales y formato del server, grupos sort desc + `localeCompare`).
- `applyEditMode`: `saveBtn.disabled = !(st.dirty || !itemEl.dataset.splitId)` (sync en markDirty, restore y OOB de guardar).
- Nuevo listener delegado `input` (scoped al item) para `input[name="nombre"]` → `markDirty(itemEl)` (habilita Guardar al teclear; `fill()` de Playwright dispara `input`).
- `rebuildDaySummary`: eliminar la fila de total. Sin cambios en snapshot/restore, guards, `processHtmx`, sortables ni listeners.

### Task 4 — Tests
- **Unit** (`tests/test_split_routes.py`):
  - `test_splits_page_resumen_por_tarjeta_v4`: sustituir asserts del total/meta por: `.split-summary-strip` presente con `>2</strong> series` y `Pectoral <strong>1</strong>`, 2 `.split-summary-strip-sep`; **sin** "actualizado" ni patrón `\d{2}/\d{2} \d{2}:\d{2}`; `.split-summary-total` ya no existe como fila de día; 3 `.split-action-btn` con aria-labels; Guardar con `disabled` en item guardado (`'data-action="split-save" class="split-action-btn" disabled'`); `.split-day-section-label` ×14; handles dentro de `.split-day-section-actions`.
  - `test_splits_page_layout_y_editmode`: `.split-item-actions` presente; Guardar disabled.
  - `test_split_nuevo_fragmento`: strip `>0</strong> series`; Guardar **sin** disabled.
- **E2E** (`tests/e2e/test_splits_flow.py`):
  - Ajustar `test_resumen_jerarquico_por_tarjeta` (total del día vía `[data-day-count]`, no `.split-summary-total`).
  - **Ajustar `test_edicion_simultanea_conserva_no_guardado` (P0-3)**: tras editar A, **mutar A** (clic chip Curl → LUNES) antes de Guardar; B referenciado por nombre (`_item_by_name("B")`) porque hay 2 items editables.
  - `_save`: assert `to_be_enabled()` en Guardar antes del clic.
  - Nuevos: `test_header_resumen_semanal_sin_fecha` (strip "3 series · Pectoral 2 · HIIT 1", `overflowX === 'auto'`, sin "actualizado"/fecha); `test_acciones_iconos_agrupados` (3 botones mismo `top`, orden x edit<save<delete, aria-labels, Guardar disabled en vista → mismo box al editar → enabled tras mutación con mismo box); `test_columnas_ancho_completo_sin_hueco` (1440 y 1920: 7 anchos iguales ±0.5, borde derecho de Domingo ≈ borde del board ≤2px, `board.scrollWidth <= clientWidth`, `scrollWidth <= clientWidth` global); `test_panel_mas_alto` (tarjeta ≥ 600px a 1280); en `test_tarjeta_dimensiones_invariantes` añadir estabilidad del panel (`.split-accordion-content` rect igual al togglear Editar/expandir grupo/agregar).
  - `test_desktop_1920_caben_7_dias` y `test_layout_movil_sin_overflow`: se mantienen (con min-width 148 la grid estira y el board scrollea solo en móvil).

### Task 5 — Docs + gates + verificación visual (req 10)
- `docs/architecture/current-ui-contract.md`: sección splits (strip en summary sin fecha, iconos agrupados con disabled, grid minmax, tokens de altura por breakpoint, labels Resumen/Ejercicios con handles, sin fila de total) + lista de vocabulario.
- Gates: `uv sync --locked`, pytest unit + e2e + cobertura, `ruff format/check`, `mypy`, `audit_consistency`, `./scripts/build_css.sh`.
- Verificación obligatoria con servidor local + Playwright en **1440×900, 1920×1080 y 390×844**: board ocupa el ancho útil, sin franja tras Domingo, columnas consistentes, panel alto e invariante, strip junto al nombre sin fecha, iconos agrupados con aria-label/title, scrolls internos finos, `document.documentElement.scrollWidth <= clientWidth`.

## Archivos afectados
`static/css/components.css`, `static/css/tailwind.css` (recompilado), `scripts/audit_consistency.py`, `app.py`, `templates/partials/split_accordion_item.html`, `templates/partials/split_board.html`, `static/js/splits.js`, `tests/test_split_routes.py`, `tests/e2e/test_splits_flow.py`, `docs/architecture/current-ui-contract.md`, `docs/plans/2026-08-16-split-manager-refined.md`.

## Riesgos controlados
- Ancho de cabecera del día a 148px: resuelto moviendo los handles al label "Ejercicios" (header = día + count ≈ 126px).
- `sort(attribute='1')` sobre `dict.items()` en Jinja: soportado (make_attrgetter); empates en orden de inserción (determinista).
- Guardar disabled: se enumeran los tests afectados y se arreglan (P0-3).
- min-height del panel = altura natural (no recorta; crece solo con zoom).
