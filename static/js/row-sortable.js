// row-sortable.js — owns: Sortable setup/teardown for the editable tables
// (#set-rows sesión, #nutrition-rows alimentación). Las filas se arrastran
// desde cualquier celda no-control (inputs/selects/buttons filtrados).
// Public API: initRowSortable(onEnd), syncSortableState,
// initNutritionRowSortable(onEnd), syncNutritionSortableState.

import { editorEditmode, getSortableRows, setSortableRows } from './state.js';

let nutritionSortable = null;

function buildSortable(tbody, onEnd) {
    return Sortable.create(tbody, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        filter: 'input, select, button',
        preventOnFilter: false,
        group: { name: 'editor-rows', pull: false, put: false },
        onEnd: onEnd || function () {},
    });
}

export function initRowSortable(onEnd) {
    const tbody = document.getElementById('set-rows');
    if (!tbody || typeof Sortable === 'undefined') return;
    const existing = getSortableRows();
    if (existing) existing.destroy();
    setSortableRows(buildSortable(tbody, onEnd));
    syncSortableState();
}

export function syncSortableState() {
    const sortable = getSortableRows();
    if (sortable) sortable.option('disabled', editorEditmode() !== '1');
}

export function initNutritionRowSortable(onEnd) {
    const tbody = document.getElementById('nutrition-rows');
    if (!tbody || typeof Sortable === 'undefined') return;
    if (nutritionSortable) nutritionSortable.destroy();
    nutritionSortable = buildSortable(tbody, onEnd);
    syncNutritionSortableState();
}

export function syncNutritionSortableState() {
    if (!nutritionSortable) return;
    const panel = document.getElementById('nutrition-panel');
    const editable = panel && panel.dataset.editmode === '1';
    nutritionSortable.option('disabled', !editable);
}
