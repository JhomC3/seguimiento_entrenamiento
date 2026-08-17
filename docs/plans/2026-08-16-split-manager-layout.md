# Gestor de Splits v3 — Layout compacto, Editar/Borrar día y corrección del DnD

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Nuevo layout de dos columnas (catálogo sticky 300px a la izquierda, editor a la derecha; móvil: editor → resumen → catálogo), resumen jerárquico tipo ledger (semana → grupos → ejercicios; diario denso), botones "Editar" y "Borrar día" con estado view/edit + dirty tracking, y corrección del problema real de agregar/mover ejercicios.

**Architecture:** Layout por CSS puro (`.splits-layout` flex, sticky en escritorio). Resumen jerárquico: nuevo campo `by_group_exercises` en `SplitMetrics` (server-authoritative) + render ledger en `split_board.html` + preview JS equivalente. Estado view/edit: `data-editmode` en el board (server lo define al abrir un split guardado), Sortables `disabled` en view, botón "Editar" los activa. "Borrar día": `data-action="split-day-clear"` + confirm modal + dirty. Diagnóstico y blindaje de `initSplits` (guard `typeof Sortable` + sub-inits a prueba de fallos).

**Tech Stack:** FastAPI + Jinja2 + htmx + SortableJS 1.15.6 + Tailwind compilado (sin cambios de dependencias).

**Decisiones confirmadas:** view/edit mode (abrir guardado = visualización; "Editar" habilita) y regla de mínimo 1 ejercicio al guardar (un split totalmente vacío → error seguro).

---

## Task 0 — Diagnóstico y corrección del bug (§7) *(primera, bloqueante)*

**Causa raíz hipótesis principal:** `initSplits()` ejecuta `initCatalogSortables(); initBoardSortables(); bindDayCopyHandles();` **sin guards**. Si `Sortable` no está (CDN caído/lento), `initCatalogSortables()` lanza y nunca se crean los Sortables de los días: click-agregar funciona (listeners ya registrados) pero arrastrar/clonar/mover quedan muertos.

**Blindaje:**
- Guard `typeof Sortable === 'undefined'` en las sub-inits (patrón `row-sortable.js:28`).
- Sub-inits individuales con try/catch (log sin romper listeners).
- Reintento en `window load` si Sortable no estaba al DOMContentLoaded.
- Verificar `syncSplitForm` (envía DOM en orden visual) y ausencia de listeners duplicados (`splitsReady`).

**Gate:** los 9 pasos del requerimiento en e2e (nuevo `test_flujo_completo_navegador`).

## Task 1 — Layout de dos columnas (§1)

- `splits.html`: `.splits-layout` con `.splits-editor-col` (`#split-board`) primero y `.splits-catalog-col` (catálogo) después.
- CSS: flex column (móvil); `@media (min-width:1024px)` → row, catálogo `order:-1`, `flex:0 0 300px`, `position:sticky; top:16px; max-height:calc(100vh - 32px); overflow-y:auto`.
- Registrar clases en `COMPONENT_CLASSES`. Tests: route (clases) + e2e (sticky en desktop, apilado en móvil).

## Task 2 — Catálogo compacto (§2)

- Densidad CSS: summary padding 4px, body gap 6px, chips `3px 8px`. Comportamiento (details/search/HIIT) ya implementado.

## Task 3 — Resumen jerárquico compacto (§3, §4)

- Backend: `SplitMetrics.by_group_exercises: dict[str, dict[str, int]]` en `models.py` + `compute_split_metrics` (test nuevo).
- Template: `#split-summary-week` (Semana — N una vez; por grupo: fila grupo + total derecha, ejercicios indentados con total derecha, separador sutil entre grupos) + `#split-summary-days` (7 filas densas: día — N series — G n · G n). Reemplaza `#split-metrics-week/exercises/days`.
- CSS ledger: `.split-summary-row`, `.split-summary-name`, `.split-summary-total`, `.split-summary-exercise`, `.split-summary-group`, `.split-summary-day` (registrar).
- JS `updatePreview` reescrito para los dos bloques (DOM APIs, agrupa por `data-grupo` → `data-ejercicio`).

## Task 4 — Botón "Editar" y estado view/edit + dirty (§5)

- Servidor: `_split_board_html` pasa `editmode = "0" if split else "1"`; `#split-open-state[data-editmode]`.
- Template board: `data-editmode`; CSS `[data-editmode="0"]` oculta `.row-btn` y `split-day-clear`.
- Header: botón `data-action="split-edit"` (hidden si no hay split abierto) + `#split-dirty-hint` ("Modificado").
- Lista: "Abrir" → "Editar" (`split-edit-open` → `splitOpen` + `pendingEdit`).
- JS: `setEditMode(on)` (data-editmode, `sortable.option('disabled')`, visibilidad del botón), guards en add/remove/shift/day-copy/day-clear, `markDirty()` en toda mutación, limpieza en save/open/new/undo.

## Task 5 — Botón "Borrar día" (§6)

- Botón por día `data-action="split-day-clear"` + `aria-label="Borrar todos los ejercicios del {day}"`.
- Confirm modal → elimina solo ese día, `updatePreview()`, `markDirty()`. Servidor aplica al Guardar.

## Task 6 — DnD estándar (§8) — verificación

- Mecanismo ya SortableJS + drags por puntero Shift (documentado). Sortables `disabled` por editmode. Test estático sin `document.addEventListener('dragstart'` se mantiene. e2e regresión (9 pasos + abrir/editar dos splits seguidos).

## Task 7 — Persistencia y servidor (§9) — verificación con tests

- Ya cumplido (orden, dia real, duplicados, renumera, deriva grupo, HIIT, límite, backup+undo, OOB). Tests explícitos: arrays vacíos → 400, duplicados, cambios de día.

## Task 8 — Tests de layout/resumen/edición (§10)

- Layout (sticky/apilado), resumen (grupo una vez, anidados, total una vez, sin días activos/distintos, diario solo total+grupos), edición (Editar, click-add, drag, mover, shift, day-copy, borrar día con confirmación, guardar persiste), DnD (posición exacta, sin listeners duplicados, orden tras recargar), estático (guard Sortable + sin dragstart nativo).

## Task 9 — Docs y gates

- `docs/architecture/current-ui-contract.md` (layout, ledger, Editar/view/edit+dirty, Borrar día, robustez init).
- Gates: `uv sync --locked`, `pytest --ignore=tests/e2e`, `pytest tests/e2e -q --no-cov`, `ruff format --check .`, `ruff check .`, `mypy app.py src tests`, `./scripts/build_css.sh`, `audit_consistency.py`, `check_module_coverage.py --min 90`.

## Riesgos

- Bug §7 con otra causa → Task 0 diagnóstica antes de tocar nada.
- View/edit rompe e2e existentes → actualizar tests (cambio de contrato intencional).
- Chromium headless + Shift → mecanismo actual (puntero) se conserva.
