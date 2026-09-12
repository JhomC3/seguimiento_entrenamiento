// editor.js — owns: #session-editor edit mode, rows, RM calculation, save.
// DOM owned: #session-editor, #session-form, #set-rows, #editor-state, #edit-actions.
// Public API: initEditorActions, syncEditButtons, updateEditActions,
// syncEditorFromContent, setPanelReadonly, handleEditorState, enterEditMode,
// exitEditMode, toggleEdit, addRowAfter, removeRow, renumberRows, fitRowsToPanel,
// recalcRM, submitSave, eliminarSesion, stepRir, isHiitRow, syncHiitRow,
// sessionMode, syncSessionHeaders, syncSessionRows.

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
import { confirmEntrenoSave, guardarPlantillaToggle } from './templates.js';

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
export function isHiitRow(row) {
    const sel = row && row.querySelector('.ej-select');
    return !!sel && sel.value.trim().toUpperCase() === 'HIIT';
}

/* Alterna kg/reps/rir ↔ velocidad/dificultad según el ejercicio.
   Los inputs ocultos se VACÍAN (siguen enviándose en los arrays paralelos:
   en blanco el servidor los ignora por rama). */
export function syncHiitRow(row) {
    if (!row) return;
    const hiit = isHiitRow(row);
    row.dataset.hiit = hiit ? '1' : '0';
    for (const name of ['kg', 'reps', 'rir']) {
        const cell = row.querySelector(`[data-col="${name}"]`);
        const input = row.querySelector(`input[name="${name}"]`);
        if (cell) cell.hidden = hiit;
        if (input && hiit) input.value = '';
    }
    for (const name of ['velocidad', 'dificultad']) {
        const cell = row.querySelector(`[data-col="${name}"]`);
        const input = row.querySelector(`input[name="${name}"]`);
        if (cell) cell.hidden = !hiit;
        if (input && !hiit) input.value = '';
    }
    if (hiit) {
        const rm = row.querySelector('.rm-cell');
        if (rm) rm.textContent = '—';
    }
}

/* Separación estricta HIIT: la sesión es HIIT pura, fuerza, mixta (legado
   inválido que el servidor rechaza) o vacía. Solo cuentan selects con valor. */
export function sessionMode() {
    const sels = Array.from(document.querySelectorAll('#set-rows .set-row .ej-select'));
    let hiit = 0, fuerza = 0;
    sels.forEach(function (sel) {
        const v = sel.value.trim();
        if (!v) return;
        if (v.toUpperCase() === 'HIIT') hiit++;
        else fuerza++;
    });
    if (hiit && fuerza) return 'mixto';
    if (hiit) return 'hiit';
    if (fuerza) return 'fuerza';
    return 'vacio';
}

/* Cabecera + filas vacías siguen al modo de sesión (el servidor renderiza
   el modo inicial; esto solo cubre cambios dinámicos sin recarga). */
export function syncSessionHeaders() {
    const form = document.getElementById('session-form');
    if (!form) return;
    const mode = sessionMode();
    const showStrength = mode !== 'hiit';
    const showHiit = mode === 'hiit' || mode === 'mixto';
    form.dataset.hiitSession = mode === 'hiit' ? '1' : '0';
    form.dataset.mixedSession = mode === 'mixto' ? '1' : '0';
    for (const name of ['kg', 'reps', 'rir', 'rm']) {
        form.querySelectorAll(`thead [data-col="${name}"]`).forEach(function (th) {
            th.hidden = !showStrength;
        });
    }
    for (const name of ['velocidad', 'dificultad']) {
        form.querySelectorAll(`thead [data-col="${name}"]`).forEach(function (th) {
            th.hidden = !showHiit;
        });
    }
}

export function syncSessionRows() {
    const mode = sessionMode();
    document.querySelectorAll('#set-rows .set-row').forEach(function (row) {
        const sel = row.querySelector('.ej-select');
        const empty = !sel || !sel.value.trim();
        if (empty && (mode === 'hiit' || mode === 'mixto')) {
            // Fila vacía en sesión con HIIT: ofrece inputs HIIT sin imponer valor.
            for (const name of ['kg', 'reps', 'rir']) {
                const cell = row.querySelector(`[data-col="${name}"]`);
                if (cell) cell.hidden = true;
            }
            for (const name of ['velocidad', 'dificultad']) {
                const cell = row.querySelector(`[data-col="${name}"]`);
                if (cell) cell.hidden = false;
            }
            return;
        }
        syncHiitRow(row);
    });
    syncSessionHeaders();
}

export function addRowAfter(btn) {
    if (editorEditmode() !== '1') return;
    const row = btn.closest('.set-row');
    const clone = row.cloneNode(true);
    clone.querySelector('.ej-select').value = '';
    clone.querySelectorAll('input').forEach(input => { input.value = ''; });
    const badge = clone.querySelector('.rir-badge');
    if (badge) badge.classList.add('hidden');
    row.after(clone);
    // La fila nueva hereda el modo de sesión: en sesión HIIT ofrece HIIT.
    if (sessionMode() === 'hiit') {
        clone.querySelector('.ej-select').value = 'HIIT';
    }
    syncSessionRows();
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

/* Sortable de filas con el re-numbering y dirty-state del editor.
   El arrastre está siempre activo: si el editor está en solo lectura, el
   onStart entra en modo edición para que el reorden persista al guardar. */
export function initEditorRowSortable() {
    initRowSortable(
        function () {
            renumberRows();
            updateEditActions();
        },
        function () {
            if (editorEditmode() !== '1') enterEditMode();
        }
    );
}

function updateRirBadge(row) {
    const input = row.querySelector('input[name="rir"]');
    const badge = row.querySelector('.rir-badge');
    if (!input || !badge) return;
    const raw = input.value.trim();
    const num = raw !== '' ? parseFloat(raw) : NaN;
    if (!isNaN(num) && num <= 0) {
        badge.textContent = num < 0 ? 'FORZADA' : 'FALLO';
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

export function recalcRM() {
    document.querySelectorAll('#set-rows .set-row').forEach(function (row) {
        const cell = row.querySelector('.rm-cell');
        if (!cell) return;
        if (isHiitRow(row)) {
            cell.textContent = '—';
            updateRirBadge(row);
            return;
        }
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
            const effectiveReps = reps + (rir >= 0 ? rir : 1 + rir);
            cell.textContent = fmtNum(kg * (1 + 0.0333 * effectiveReps));
        } else {
            cell.textContent = '—';
        }
        updateRirBadge(row);
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

/* ---------- RIR: cualquier decimal, flechas ±0,1 ---------- */
const RIR_STEP = 0.1;
const RIR_MIN = -5;

function cleanStepVal(v) {
    return parseFloat(v.toFixed(10));
}

export function stepRir(input, delta) {
    if (input.disabled || input.readOnly) return;
    const raw = input.value.trim();
    const current = raw === '' ? 0 : parseFloat(raw);
    if (isNaN(current)) return;
    const next = Math.max(RIR_MIN, cleanStepVal(current + delta));
    input.value = String(next);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

/* ---------- Acciones delegadas del editor ---------- */
export function initEditorActions() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        switch (el.dataset.action) {
            case 'toggle-edit':
                toggleEdit();
                break;
            case 'toggle-template-form':
                guardarPlantillaToggle();
                break;
            case 'cancel-template-form':
                guardarPlantillaToggle(false);
                break;
            case 'confirm-template-save':
                confirmEntrenoSave();
                break;
            case 'delete-session':
                eliminarSesion();
                break;
            case 'row-add':
                addRowAfter(el);
                break;
            case 'row-remove':
                removeRow(el);
                break;
            case 'rir-step': {
                const row = el.closest('.set-row');
                const input = row && row.querySelector('input[name="rir"]');
                if (input) stepRir(input, parseFloat(el.dataset.delta) || RIR_STEP);
                break;
            }
        }
    });


    document.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        const input = e.target.closest && e.target.closest('#session-form input[name="rir"]');
        if (!input) return;
        e.preventDefault();
        stepRir(input, e.key === 'ArrowUp' ? RIR_STEP : -RIR_STEP);
    });

    document.addEventListener('focusin', function (e) {
        const sel = e.target.closest ? e.target.closest('#session-form .ej-select') : null;
        if (!sel) return;
        sel.dataset.prev = sel.value;
    });

    document.addEventListener('change', function (e) {
        const sel = e.target.closest ? e.target.closest('#session-form .ej-select') : null;
        if (!sel) return;
        if (sessionMode() === 'mixto') {
            sel.value = sel.dataset.prev || '';
            const row = sel.closest('.set-row');
            if (row) syncHiitRow(row);
            syncSessionRows();
            flashEditorNotice(
                'HIIT no se puede combinar con otros ejercicios. Regístralo en un día separado.',
                'error'
            );
            return;
        }
        syncSessionRows();
        sel.dataset.prev = sel.value;
    });
}
