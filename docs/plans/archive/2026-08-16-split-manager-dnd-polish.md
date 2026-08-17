# Plan: Split Manager v6 — DnD sin duplicados, header arrastrable, icono Editar iluminado, tarjetas de tamaño fijo

Fecha: 2026-08-16 · Rama: `feat/split-manager` (continuación de v5)
**Estado: COMPLETADO (2026-08-16)** — Tasks 0-5 implementadas; gates verdes
(551 unit + 76 e2e, ruff, mypy, audit_consistency, cobertura 92.80%).
**Hallazgo real durante la ejecución (sonda de diagnóstico P0-1)**: el
duplicado visual tiene DOS causas — (a) ghost sin estilo en DnD nativo y
(b) con `forceFallback`, el `draggable=true` hace que el drag nativo HTML5
secuestre el arrastre y el fallback quede en `chosen` sin arrancar. Solución:
quitar `draggable` de tarjetas/chips, `forceFallback` + `filter` FUNCIÓN
(`e.shiftKey || target.tagName === 'BUTTON'` — el `preventDefault` en captura
no basta porque Sortable escucha mousedown en el elemento) y ghost estilizado.
Referencia: prompt del cliente (§1-§11) + evaluación crítica (correcciones P0/P1 incorporadas).

## Regla central (explícita)
**Arrastre normal = mover. Shift + arrastre = copiar. Solo el catálogo clona automáticamente** (`pull:'clone'` únicamente en `buildCatalogSortable`; los días usan `pull:true`/`put:true` = movimiento real, sin `cloneNode` en movimientos normales).

## Diagnóstico (verificado en código v5)
El duplicado visual durante el drag viene de SortableJS en modo **DnD nativo**: la imagen de arrastre del navegador sigue al cursor mientras la tarjeta real es re-parentada como ghost en la lista, y `.sortable-ghost`/`.sortable-chosen` de splits **no tienen estilo** en `components.css` (solo session-editor los estiliza) → el ghost se ve como una tarjeta completa opaca. `pull:'clone'` ya vive solo en el catálogo (línea 321); `onItemShiftDown` está en fase burbuja (línea 987).

## Correcciones de la evaluación (incorporadas)
- **P0-1 (gate de diagnóstico)**: Task 0 empieza con una sonda de reproducción (mid-drag: 1 `.sortable-ghost` sin opacidad + drag image nativa) ANTES de tocar Sortable.
- **P0-2 (límite testeable)**: e2e muta `data-max-items` en página (p. ej. a 2) y copia un día de 3 con Shift → rechazo con notice, origen intacto, sin clones parciales.
- **P0-3 (día-drag sobre día ocupado)**: e2e explícito — inserción posicional si cae sobre la lista, append si cae sobre el header destino, **no reemplaza**.
- **P0-4 (a11y del botón 18px)**: `.split-item-remove` 18px **visual** + hit area ≥24px vía `::before { inset: -4px }` + `position: relative` (cumple WCAG 2.5.8 y la CSS del cliente).
- **P1-5**: e2e en dos fases: (a) convertir helpers a mouse-drag manteniendo la suite verde; (b) añadir tests nuevos.
- **P1-6 (accesibilidad del día-copia)**: el header-drag es solo puntero; se conserva un **icono de copia compacto** `.split-day-copy-btn` en `.split-day-section-actions` (click → copia al día seleccionado, como el viejo shift+click). Sin regresión silenciosa.
- **P1-7**: aserción de `pull:'clone'` acotada al cuerpo de `buildCatalogSortable`.
- **P1-8**: protocolo exacto del test de ghost (mid-drag con `mouse.down` → `mouse.move` en pasos → `evaluate` → `mouse.up`; 1 ghost opacidad<1, 1 card `.split-fallback` en `body`, listas N−1).
- **P1-9**: en el mouseup del día-drag la zona se detecta con `closest('.split-day-zone')` (el botón day-select está DENTRO de la zona); la exclusión de `button` solo aplica al mousedown de inicio.
- **P1-10**: contrato realista de scrollbars: `--split-scrollbar-size: 3px` donde el navegador lo permita (Firefox `thin` ≈ 6-8px; macOS overlay ignora WebKit custom) — el test valida la var CSS + `scrollbar-width: thin` computado.
- **P1-11**: `.is-active` como selector compuesto `.split-action-btn.is-active` (la regex de auditoría no captura la clase suelta).
- **P1-12**: inserción secuencial `insertBefore(anchor)` en orden (declarado para evitar orden invertido); `clearDragVisuals` limpia también `.dragging-day`.
- **P1-13**: el `preventDefault` en captura bloquea el arranque del fallback de Sortable con Shift (deseado) y NO bloquea el `click` del botón de eliminar.
- **P1-14**: límite touch documentado (día-drag es puntero/mouse; app de escritorio).

## Tasks

### Task 0 — CSS (`static/css/components.css` + `scripts/audit_consistency.py`)
- **Sonda de diagnóstico** (P0-1): script Playwright que durante un drag nativo actual cuenta `.sortable-ghost` y comprueba opacidad → gate documentado en el plan de ejecución.
- **Ghost/placeholder estándar**: `.split-day-items .sortable-ghost { opacity: .35; background: var(--t-overlay-burgundy-020); border: 1px dashed var(--t-burgundy-600); border-radius: 8px; }`, `.sortable-chosen` sutil (border accent), `.split-fallback { cursor: grabbing; }`.
- **Tamaño fijo** (req 4): tokens `--split-item-height: 28px` y `--split-item-action-size: 18px`. `.split-item-card` (días): `height/min-height/max-height: var(--split-item-height)`, `box-sizing: border-box`; `.split-catalog-chip`: altura 28px. Nuevo `.split-item-remove` (en lugar de `row-btn` dentro de las tarjetas): tamaño 18px visual + `::before` hit-area 24px, `display: grid; place-items: center`, `font-size: 10px`, `line-height: 1`, `flex: 0 0 var(--split-item-action-size)`, `position: relative`. **Vista: `visibility: hidden`** (reserva el slot; la tarjeta nunca cambia de tamaño).
- **Scrollbars** (req 5): `--split-scrollbar-size: 3px`; regla compartida `.split-day-summary, .split-day-items, .split-board-scroll, .split-summary-strip, .splits-catalog-col { scrollbar-width: thin; scrollbar-color: var(--t-overlay-white-014) transparent; }` + WebKit `::-webkit-scrollbar { width/height: var(--split-scrollbar-size) }`, track transparente, thumb `var(--t-overlay-white-014)` con `border-radius: 999px`, hover `var(--t-overlay-white-035)`; sin animaciones (`prefers-reduced-motion`).
- **Editar iluminado** (req 3): `.split-action-btn.is-active { color: var(--t-burgundy-400); border-color: var(--t-burgundy-600); filter: drop-shadow(0 0 3px var(--t-burgundy-600)); }` (mismo box 28×28). Eliminar `.split-edit-badge` (CSS + vocabulario).
- **Header del día** (req 6): `[data-editmode="1"] .split-day-header { cursor: grab }`, `.split-day-header.dragging-day { cursor: grabbing; border-color: var(--t-burgundy-600); }`.
- Eliminar `.split-day-copy-handle`; añadir `.split-day-copy-btn` (icono compacto 24px en el label row, mismo patrón visual que `split-action-btn` pero pequeño). `COMPONENT_CLASSES`: +`split-fallback`, `split-item-remove`, `split-day-copy-btn`; −`split-day-copy-handle`, `split-edit-badge`.

### Task 1 — JS (`static/js/splits.js`)
- **Sortable sin duplicados** (req 1-2): `buildBoardSortable` y `buildCatalogSortable` → `forceFallback: true, fallbackOnBody: true, fallbackClass: 'split-fallback'`; catálogo + `removeCloneOnHide: true, revertClone: true`. `onItemShiftDown` registrado en **captura** (`document.addEventListener('mousedown', onItemShiftDown, true)`): el `preventDefault` corre antes que el fallback de Sortable → la tecla Shift decide el modo desde el inicio (nunca coexisten mover y copiar). El movimiento entre días sigue siendo real (criterio 10→10).
- **Header del día arrastrable** (req 6-9): eliminar `bindDayCopyHandles`, `onDayCopyMove/Up` y el flujo del handle; nuevo drag por puntero delegado sobre `.split-day-header`:
  - mousedown: skip si `e.target.closest('button')` (day-select clicable), si `!canEdit(item)` o si el día origen está vacío (notice breve "El día X no tiene ejercicios."); `state.dayDrag = { key, from, mode: e.shiftKey ? 'copy' : 'move' }` + clase `dragging-day`.
  - mousemove: `paintDropTarget` de la zona bajo el puntero (sin tocar el DOM; nada flota tras el cursor).
  - mouseup: zona vía `closest('.split-day-zone')` (P1-9); mismo día → no-op; posición: inserción por mitad de tarjeta destino si el puntero cae sobre la lista, **append si cae sobre el header destino**; **guardas ANTES de tocar el DOM** (req 9): mover → `canAdd(destino, N)` (rechazo → notice, origen intacto); copiar → `guardLimit(destino, N)`; mover: re-parentar las tarjetas en orden (insertBefore secuencial preserva orden, P1-12) con `dia` del destino + `updatePreview` + `markDirty`; copiar: `cloneNode` + `finalizeCard` por tarjeta (uid nuevo, `dia` destino) + notice "Día X copiado a Y".
  - `clearDragVisuals`: limpiar también `.dragging-day`.
- **Copy accesible** (P1-6): mantener `data-action="split-day-copy"` en `.split-day-copy-btn` (click → copia el día al día seleccionado con append, límites y notice — mismo helper que el header-drag).
- **"Editando" eliminado** (req 3): quitar `[data-split-edit-badge]` de `applyEditMode`; `editBtn.classList.toggle('is-active', editmode === '1')` + `aria-pressed` (ya existe).
- El shift-copy de items (custom pointer drag) se conserva intacto (solo cambia la fase del mousedown).

### Task 2 — Templates
- `split_board.html`: tarjetas con `class="split-item-remove"` (mantiene `data-action="split-item-remove"` + aria-label); label "Ejercicios" con `.split-day-section-actions` = `.split-day-copy-btn` (aria-label "Copiar el día {X} al día seleccionado", title) + clear-day; header sin cambios.
- `split_accordion_item.html`: eliminar `<span data-split-edit-badge>`.

### Task 3 — Tests unit (`tests/test_split_routes.py`)
- Quitar asserts de `split-day-copy-handle`/`aria-label="Copiar todo el día…"`; añadir `.split-item-remove` y el aria-label del copy-btn; `test_splits_js_sin_dnd_nativo_paralelo`: `"forceFallback: true" in src` + `pull:'clone'` acotado al cuerpo de `buildCatalogSortable` (P1-7) + ausencia de dragstart/dragend a nivel document (existente).

### Task 4 — Tests e2e (`tests/e2e/test_splits_flow.py`)
- **4a (conversión)**: `_mouse_drag` sin Shift (patrón de `_mouse_drag_shift`); `_drag_to_element`, `_drag_from_catalog`, `_drag_to_position`, `_drag_to_day_at` pasan a mouse-drag (forceFallback no usa DnD nativo); adaptar `intenta` de A3 (mouse-drag + try/except). Suite existente verde.
- **4b (nuevos, req 10)**:
  1. Mover LUNES→VIERNES sin Shift: total constante (10→10), origen sin duplicado, `data-dia` correcto.
  2. **Ghost único mid-drag** (P1-8): 1 `.sortable-ghost` (opacidad<1), 1 `.split-item-card.split-fallback` en `body`, listas con N−1.
  3. Shift duplica item (+1, posición exacta — existente, adaptado).
  4. Editar: sin "Editando"; lápiz `.is-active` + `aria-pressed=true` + mismo `bounding_box`.
  5. Tamaño de tarjeta idéntico en vista/edición/agregar/eliminar/mover/duplicar (invariantes + `bounding_box` del `.split-item-remove` con `visibility:hidden`).
  6. Día-drag sin Shift: bloque LUNES→VIERNES (origen vacío, orden, `dia=VIERNES`, total constante, dirty, persiste tras guardar/recargar).
  7. Día-drag con Shift: origen intacto, destino con copias, `dia` correcto, +N, dirty.
  8. Día-drag sobre día ocupado (P0-3): inserción posicional y append-en-header; no reemplaza.
  9. Día vacío: no inicia + notice breve.
  10. Límite (P0-2): `data-max-items=2` → copia día de 3 rechazada, origen intacto, notice.
  11. Scrollbars: `--split-scrollbar-size` = 3px y `scrollbar-width: thin` en `.split-day-summary`.
  12. Sin listeners duplicados tras OOB (req 10.20): guardar → día-drag → se mueve UNA vez.
- Mantener: overflow global, acordeón, strip, iconos, columnas, móvil.

### Task 5 — Docs + gates + verificación visual
- `docs/architecture/current-ui-contract.md`: sección splits (forceFallback + regla central, header-drag día mover/copiar con límites, `.split-item-remove` con hit-area, scrollbars 3px realistas, `.is-active`, copy-btn accesible) + vocabulario.
- Gates: `uv sync --locked`, pytest unit + e2e + cobertura, ruff, mypy, `audit_consistency`, `./scripts/build_css.sh`.
- Verificación geométrica en 1440×900 / 1920×1080 / 390×844 (mismo script que v5): una sola tarjeta mid-drag, cero duplicados tras drop, lápiz iluminado, tamaños idénticos, scrollbars, header grab, normal=mover/Shift=copiar, sin overflow global.

## Archivos afectados
`static/js/splits.js`, `static/css/components.css` (+`tailwind.css`), `scripts/audit_consistency.py`, `templates/partials/split_board.html`, `templates/partials/split_accordion_item.html`, `tests/test_split_routes.py`, `tests/e2e/test_splits_flow.py`, `docs/architecture/current-ui-contract.md`, `docs/plans/2026-08-16-split-manager-dnd-polish.md`.

## Riesgos controlados
- forceFallback rompe `drag_to` CDP → conversión mecánica de helpers (fase 4a aislada).
- Exclusión de Shift vía capture-phase (independiente del soporte de `filter` función en Sortable 1.15.6).
- Firefox/overlay: scrollbar "3px" es best-effort (P1-10).
- Límite de día-copia testeable vía mutación de `data-max-items` (P0-2).
