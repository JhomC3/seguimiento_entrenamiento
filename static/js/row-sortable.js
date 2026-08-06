// row-sortable.js — owns: Sortable setup/teardown for #set-rows.
// DOM owned: #set-rows (Sortable container).
// Public API: initRowSortable(onEnd), syncSortableState.

import { editorEditmode, getSortableRows, setSortableRows } from './state.js';

export function initRowSortable(onEnd) {
    const tbody = document.getElementById('set-rows');
    if (!tbody || typeof Sortable === 'undefined') return;
    const existing = getSortableRows();
    if (existing) existing.destroy();
    setSortableRows(Sortable.create(tbody, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        filter: 'input, select, button',
        preventOnFilter: false,
        group: { name: 'editor-rows', pull: false, put: false },
        onEnd: onEnd || function () {},
    }));
    syncSortableState();
}

export function syncSortableState() {
    const sortable = getSortableRows();
    if (sortable) sortable.option('disabled', editorEditmode() !== '1');
}
