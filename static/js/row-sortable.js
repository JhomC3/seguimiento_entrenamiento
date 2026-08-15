// row-sortable.js — owns: Sortable setup/teardown for the editable tables
// (#set-rows sesión, #nutrition-rows alimentación). Las filas se arrastran
// desde cualquier celda no-control (inputs/selects/buttons filtrados).
// El Sortable está SIEMPRE habilitado: al empezar un arrastre, el caller
// entra en modo edición (onStart) para que el reorden persista al guardar.
// Public API: initRowSortable(onEnd, onStart), syncSortableState,
// initNutritionRowSortable(onEnd, onStart), syncNutritionSortableState.

import { editorEditmode, getSortableRows, setSortableRows } from './state.js';

let nutritionSortable = null;

function buildSortable(tbody, onEnd, onStart) {
    return Sortable.create(tbody, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        filter: 'input, select, button',
        preventOnFilter: false,
        group: { name: 'editor-rows', pull: false, put: false },
        onEnd: onEnd || function () {},
        onStart: onStart || function () {},
    });
}

export function initRowSortable(onEnd, onStart) {
    const tbody = document.getElementById('set-rows');
    if (!tbody || typeof Sortable === 'undefined') return;
    const existing = getSortableRows();
    if (existing) existing.destroy();
    setSortableRows(buildSortable(tbody, onEnd, onStart));
    syncSortableState();
}

export function syncSortableState() {
    const sortable = getSortableRows();
    if (sortable) sortable.option('disabled', false);
}

export function initNutritionRowSortable(onEnd, onStart) {
    const tbody = document.getElementById('nutrition-rows');
    if (!tbody || typeof Sortable === 'undefined') return;
    if (nutritionSortable) nutritionSortable.destroy();
    nutritionSortable = buildSortable(tbody, onEnd, onStart);
    syncNutritionSortableState();
}

export function syncNutritionSortableState() {
    if (nutritionSortable) nutritionSortable.option('disabled', false);
}
