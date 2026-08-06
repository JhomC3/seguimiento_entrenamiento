// editor.js — owns: #session-editor edit mode, rows, RM calculation, save.
// DOM owned: #session-editor, #session-form, #set-rows, #editor-state, #edit-actions.
// Public API: syncEditButtons, updateEditActions, syncEditorFromContent,
// setPanelReadonly, handleEditorState, enterEditMode, exitEditMode, toggleEdit,
// addRowAfter, removeRow, renumberRows, fitRowsToPanel, recalcRM, submitSave,
// eliminarSesion.

import { flashEditorNotice } from './notices.js';
import { initRowSortable, syncSortableState } from './row-sortable.js';
import {
    captureBaseline,
    currentFecha,
    editorEditmode,
    fmtNum,
    isDirty,
    setSaveRequested,
    showConfirmDialog,
} from './state.js';
import { doNav } from './date-navigation.js';

export function syncEditButtons() {
    const st = document.getElementById('editor-state');
    const editor = document.getElementById('session-editor');
    if (!st || !editor) return;
    const editable = editor.dataset.editmode === '1';
    const pencil = editor.querySelector('.pencil-btn');
    if (pencil) {
        pencil.classList.toggle('on', editable);
        pencil.classList.toggle('off', !editable);
    }
    const bookmark = editor.querySelector('.save-template-btn');
    if (bookmark) bookmark.classList.toggle('on', editable);
    const trash = editor.querySelector('.delete-session-btn');
    if (trash) {
        trash.hidden = st.dataset.hasData !== '1';
        trash.classList.toggle('on', editable && st.dataset.hasData === '1');
    }
    const actions = document.getElementById('edit-actions');
    const saveBtn = actions && actions.querySelector('button[type="submit"]');
    if (saveBtn) saveBtn.disabled = !editable;
}

export function updateEditActions() {
    const actions = document.getElementById('edit-actions');
    if (!actions) return;
    const show = editorEditmode() === '1' && isDirty();
    actions.classList.toggle('invisible', !show);
}

export function syncEditorFromContent() {
    const editor = document.getElementById('session-editor');
    const st = document.getElementById('editor-state');
    if (!editor || !st) return;
    editor.dataset.editmode = st.dataset.readonly === '1' ? '0' : '1';
    captureBaseline();
    updateEditActions();
    syncEditButtons();
}

export function setPanelReadonly() {
    const form = document.getElementById('session-form');
    if (!form) return;
    form.querySelectorAll('input, select').forEach(el => { el.disabled = true; });
    form.querySelectorAll('.row-actions').forEach(el => { el.classList.add('hidden'); el.hidden = true; });
    const editor = document.getElementById('session-editor');
    if (editor) editor.dataset.editmode = '0';
    const actions = document.getElementById('edit-actions');
    if (actions) actions.classList.add('invisible');
    captureBaseline();
    syncSortableState();
    syncEditButtons();
}

export function handleEditorState() {
    const st = document.getElementById('editor-state');
    if (st && st.dataset.readonly === '1') setPanelReadonly();
}

export function enterEditMode() {
    if (editorEditmode() === '1') return;
    const form = document.getElementById('session-form');
    if (!form) return;
    form.querySelectorAll('input, select').forEach(el => { el.disabled = false; });
    form.querySelectorAll('.row-actions').forEach(el => { el.classList.remove('hidden'); el.hidden = false; });
    const editor = document.getElementById('session-editor');
    if (editor) editor.dataset.editmode = '1';
    const st = document.getElementById('editor-state');
    if (st) st.dataset.readonly = '0';
    captureBaseline();
    updateEditActions();
    syncSortableState();
    syncEditButtons();
}

export function exitEditMode() {
    const editor = document.getElementById('session-editor');
    const fecha = editor?.querySelector('#session-form input[name="fecha"]')?.value;
    if (isDirty()) {
        showConfirmDialog(
            function () { submitSave(); },
            function () { doNav(fecha || '', true); }
        );
    } else {
        doNav(fecha || '', true);
    }
}

export function toggleEdit() {
    if (editorEditmode() === '1') {
        exitEditMode();
    } else {
        enterEditMode();
    }
}

/* ---------- Filas ---------- */
export function addRowAfter(btn) {
    if (editorEditmode() !== '1') return;
    const row = btn.closest('.set-row');
    const clone = row.cloneNode(true);
    clone.querySelector('.ej-select').value = '';
    clone.querySelectorAll('input').forEach(input => { input.value = ''; });
    row.after(clone);
    renumberRows();
    updateEditActions();
    fitRowsToPanel();
}

export function removeRow(btn) {
    if (editorEditmode() !== '1') return;
    btn.closest('.set-row').remove();
    renumberRows();
    updateEditActions();
    fitRowsToPanel();
}

export function renumberRows() {
    document.querySelectorAll('#set-rows .set-row').forEach((row, i) => {
        row.querySelector('.set-num').textContent = i + 1;
    });
}

/* ---------- Altura del panel: UNA medición estandarizada, constante en todo estado ---------- */
const ROWS_VISIBLE = 17.5;
const PANEL_BUFFER = 2;
const ROW_BORDER_PX = 1;
let rowHMeasured = null;
export function fitRowsToPanel() {
    const editor = document.getElementById('session-editor');
    const tbody = document.getElementById('set-rows');
    if (!editor || !tbody) return;
    const thead = editor.querySelector('.table-scroll thead');
    const theadH = thead ? thead.getBoundingClientRect().height : 20;
    if (rowHMeasured === null) {
        const row = tbody.querySelector('.set-row');
        if (row) {
            const actions = row.querySelector('.row-actions');
            const wasHidden = actions && actions.classList.contains('hidden');
            if (wasHidden) actions.classList.remove('hidden');
            rowHMeasured = row.getBoundingClientRect().height || 28;
            if (wasHidden) actions.classList.add('hidden');
        } else {
            rowHMeasured = 28;
        }
    }
    // Fórmula única: 18 filas + 17 bordes divide-y (1px c/u, solo filas 2..18) + margen único.
    const full = theadH + ROWS_VISIBLE * rowHMeasured + (ROWS_VISIBLE - 1) * ROW_BORDER_PX + PANEL_BUFFER;
    editor.style.setProperty('--table-h', full + 'px');
}

/* Sortable de filas con el re-numbering y dirty-state del editor */
export function initEditorRowSortable() {
    initRowSortable(function () {
        renumberRows();
        updateEditActions();
    });
}

export function recalcRM() {
    document.querySelectorAll('#set-rows .set-row').forEach(function (row) {
        const kgEl = row.querySelector('input[name="kg"]');
        const repsEl = row.querySelector('input[name="reps"]');
        const rirEl = row.querySelector('input[name="rir"]');
        const cell = row.querySelector('.rm-cell');
        if (!cell || !kgEl || !repsEl) return;
        const kg = parseFloat(kgEl.value);
        const reps = parseFloat(repsEl.value);
        const rirRaw = rirEl ? rirEl.value : '';
        const rir = rirRaw ? parseFloat(rirRaw) : 0;
        if (!isNaN(kg) && !isNaN(reps)) {
            cell.textContent = fmtNum(kg * (1 + 0.0333 * (reps + 1 + rir)));
        } else {
            cell.textContent = '—';
        }
    });
}

/* ---------- Guardar ---------- */
export function submitSave() {
    const form = document.getElementById('session-form');
    if (form) form.requestSubmit();
}

/* ---------- Sesión: eliminar ---------- */
export function eliminarSesion() {
    if (editorEditmode() !== '1') {
        flashEditorNotice('Activa el modo editable primero.', 'error');
        return;
    }
    const fecha = currentFecha();
    if (!fecha) return;
    document.getElementById('confirm-msg').textContent = '¿Eliminar el entreno de esta fecha?';
    showConfirmDialog(function () {
        setSaveRequested(true);
        htmx.ajax('POST', '/entrenamiento/session/eliminar', { values: { fecha: fecha }, target: 'body', swap: 'none' });
    }, null);
}
