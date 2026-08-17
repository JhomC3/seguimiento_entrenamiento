# Rediseño del Gestor de Splits (v2) — Plan de Implementación

> **Estado: COMPLETADO (2026-08-17).** Sus objetivos quedaron implementados en las iteraciones v3–v6 del gestor de splits y documentados en `docs/architecture/current-ui-contract.md`.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reordenar la página (tablero → resumen → catálogo → lista), catálogo desplegable por grupo muscular, resumen de series rediseñado (Semana / Por ejercicio / Por día, sin "Días activos" ni "Ejercicios distintos"), DnD estandarizado con SortableJS con inserción en posición exacta, y duplicación mediante Shift (instancia y día completo).

**Architecture:** Cambios server-side mínimos (`SplitMetrics` en `src/models.py` + `compute_split_metrics` en `src/split_service.py`); frontend: reorden de `splits.html`, `<details>/<summary>` nativo para el catálogo, resumen con 3 sub-secciones server-rendered, y `splits.js` reescrito sobre SortableJS (mismo patrón que `row-sortable.js`/`templates.js`). Rutas, CSRF y undo no cambian.

**Tech Stack:** FastAPI + Jinja2 + htmx + SortableJS 1.15.6 (ya en `base.html:14`) + Tailwind compilado.

---

## Decisiones de diseño

| Decisión | Detalle |
|---|---|
| Orden de página | `splits.html`: header → `#split-board` (board + resumen) → catálogo → `#splits-section` |
| Catálogo desplegable | `<details class="split-catalog-group">` + `<summary>` nativo por grupo (aria-expanded/teclado/focus nativos); HIIT como `<details>` propio. Inicia cerrado. Search: abre grupos con resultados, oculta el resto, restaura cerrado al vaciar |
| Chips = tarjetas | Chips del catálogo: `div.split-item-card.split-catalog-chip[role=button][tabindex=0]` con solo `.split-item-name` (clon de Sortable válido); `data-grupo`/`data-item-type`/`data-ejercicio` solo como atributos. Tarjetas de día sin `.split-item-group` visible |
| Métricas (modelo) | `SplitMetrics`: eliminar `total_instances`, `active_days`, `distinct_exercises`; `days` = los 7 días (vacíos con 0). `database.get_splits_summary.active_days` se conserva (lista de splits, fuera de alcance) |
| Resumen | 3 sub-secciones server-rendered con ids estables: `#split-metrics-week` (total + por grupo), `#split-metrics-exercises` (por ejercicio), `#split-metrics-days` (7 filas: series + por grupo). Board sin split → `compute_split_metrics([])` |
| DnD items (SortableJS) | Catálogo: `group:{name:'split-days', pull:'clone', put:false}`, `sort:false`. Días: `group:{name:'split-days', pull:true, put:true}`, `draggable:'.split-item-card'`, `filter:'button'`, `preventOnFilter:false`, `animation:150`, `ghostClass:'sortable-ghost'`, `chosenClass:'sortable-chosen'` (idéntico a `row-sortable.js:14-23`) |
| Inserción exacta | Nativa de SortableJS (posición del puntero). Se elimina `getDragAfterElement`/append al final de `splits.js` |
| Shift + arrastre (instancia) | `onStart`: si `shiftKey` → `state.shiftCopies.set(uid, item.cloneNode(true))` + clase `copy-mode`. `onUpdate` (mismo día) / `onAdd` (otro día): swap — la copia recibe `finalizeCard` (uid nuevo + `data-dia` del destino) y se inserta en `newIndex`; el original vuelve a `oldIndex` de su lista. Sin Shift: movimiento normal de Sortable |
| Shift + arrastre (día completo) | Handle `button.split-day-copy-handle[draggable=true][data-action=split-day-copy][data-day][aria-label][title]` en cada header. `dragstart` sin Shift → `preventDefault` (sin arrastre); con Shift → payload `daycopy:<dia>`. Drop en zona destino: copia todas las tarjetas con `finalizeCard` (`dia` = destino) insertadas antes del anchor por Y (o al final). Shift+click copia al día seleccionado. Nunca se mueve/borra el origen |
| Límite | `data-max-items` (de `MAX_SPLIT_ITEMS`) en `#split-open-state`; guard client-side antes de cada mutación (catálogo, shift-copy, day-copy): si supera el límite → notice seguro y NO se toca el DOM |
| Re-init tras OOB | `initBoardSortables()` (destroy + recrear) y `bindDayCopyHandles()` (por elemento, flag `dataset.copyReady`) tras `htmx:afterSwap` de `#split-board`; re-lee `data-max-items` |
| Drop-target | `.split-day-zone.drop-target` (ya en CSS) vía `onMove` (add) / `onEnd` (remove); day-copy usa el mismo resaltado |
| syncSplitForm | Sin cambios: DOM por día = orden visual; servidor renumera y deriva grupo |

## Tasks

1. **Backend**: `src/models.py` `SplitMetrics` sin `total_instances/active_days/distinct_exercises`; `src/split_service.py` `compute_split_metrics` → 7 días. Tests: actualizar `test_metricas_*`, nuevo `test_metricas_incluye_dias_vacios`.
2. **Templates**: `splits.html` (catálogo tras board, `<details>` por grupo + HIIT); `split_board.html` (cards sin grupo, handle de copia de día con SVG, resumen 3 secciones, `data-max-items`); `app.py` `_split_board_html` pasa `max_items` y métricas vacías.
3. **CSS**: `components.css` — `.split-catalog-group/summary/body` (chevron, focus-visible, fade), `.split-catalog-chip` (grab), `.split-item-card.copy-mode` (dashed outline), `.split-day-copy-handle` (+`.dragging-day`), quitar `.split-item-group`; `audit_consistency.py` COMPONENT_CLASSES al día.
4. **JS**: `splits.js` reescrito: SortableJS (catálogo clone, días move), shift-copy (onStart/onUpdate/onAdd swap), day-copy (native DnD solo del handle), search+details, preview 3 secciones, límite client-side, re-init tras OOB. Sin `document.addEventListener('dragstart'...)`.
5. **Tailwind**: `./scripts/build_css.sh`.
6. **Tests rutas**: asserts de details, sin "Días activos"/"Ejercicios distintos", 7 días, chips sin texto de grupo; test estático: `splits.js` sin listeners nativos `dragstart/dragend` en document.
7. **E2E**: helpers con mouse real (`_drag_row_up` pattern) + Shift con `page.keyboard.down('Shift')`; casos: mover sin Shift, shift-copy intra-día (posición exacta), shift-copy entre días (dia correcto, original permanece), day-copy (jueves = lunes, lunes intacto, no reemplaza, orden), límite (con `data-max-items` bajo vía route monkeypatch o tarjetas suficientes), guardar/recargar.
8. **Docs**: `docs/architecture/current-ui-contract.md` (orden visual, catálogo details, resumen nuevo, SortableJS + shift-copy, límite).
9. **Gates**: `uv sync --locked`, `pytest --ignore=tests/e2e`, `pytest tests/e2e -q --no-cov`, `ruff format --check .`, `ruff check .`, `mypy app.py src tests`, `build_css.sh`, `audit_consistency.py`, `check_module_coverage.py --min 90`.

## Riesgos

- SortableJS + DragEvent sintéticos → e2e con mouse real (patrón probado `_drag_row_up`).
- Clon de `<button>` inválido → chips `div[role=button]`; el botón de eliminar lo añade `finalizeCard`.
- Duplicación de Sortables tras OOB → destroy + recrear.
- `audit_component_coverage` → sincronizar COMPONENT_CLASSES en Task 3.
- Precisión de posición en e2e → coordenadas `top+2` del anchor.
