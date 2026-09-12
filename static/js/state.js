// state.js — owns shared ephemeral client state and pure helpers.
// No other module may mutate state directly: always through the getters/setters.
// DOM owned: none (reads #session-editor, #session-form, #set-rows defensively).
// Public API: get*/set* for shared state, serializeForm, captureBaseline, isDirty,
// fmtNum, editorEditmode, currentFecha, showConfirmDialog, hideConfirmDialog,
// noteFormFocus, noteFieldEdit, clearFieldHistory, popFieldEdit.

let pendingNav = null;
let confirmCbs = null;
let saveRequested = false;
let sortableRows = null;
let plantillaAppliedPending = false;
let dragCard = null;
let dragOrderStart = null;
let dropHandled = false;
let droppedOnList = false;
let applyInFlight = null;
let dragGhost = null;
let categoriaMap = {};
let alimentoMap = {};
let cicloStart = "";
let csrfToken = "";
let currentIso = null;

export function getPendingNav() { return pendingNav; }
export function setPendingNav(v) { pendingNav = v; }
export function getConfirmCbs() { return confirmCbs; }
export function setConfirmCbs(v) { confirmCbs = v; }
export function getSaveRequested() { return saveRequested; }
export function setSaveRequested(v) { saveRequested = v; }
export function getSortableRows() { return sortableRows; }
export function setSortableRows(v) { sortableRows = v; }
export function getPlantillaAppliedPending() { return plantillaAppliedPending; }
export function setPlantillaAppliedPending(v) { plantillaAppliedPending = v; }
export function getDragCard() { return dragCard; }
export function setDragCard(v) { dragCard = v; }
export function getDragOrderStart() { return dragOrderStart; }
export function setDragOrderStart(v) { dragOrderStart = v; }
export function getDropHandled() { return dropHandled; }
export function setDropHandled(v) { dropHandled = v; }
export function getDroppedOnList() { return droppedOnList; }
export function setDroppedOnList(v) { droppedOnList = v; }
export function getApplyInFlight() { return applyInFlight; }
export function setApplyInFlight(v) { applyInFlight = v; }
export function getDragGhost() { return dragGhost; }
export function setDragGhost(v) { dragGhost = v; }
export function setCategoriaMap(m) { categoriaMap = m || {}; }
export function getCategoriaMap() { return categoriaMap; }
export function setAlimentoMap(m) { alimentoMap = m || {}; }
export function getAlimentoMap() { return alimentoMap; }
export function setCicloStart(v) { cicloStart = v || ""; }
export function getCicloStart() { return cicloStart; }
export function setCsrfToken(t) { csrfToken = t || ""; }
export function getCsrfToken() { return csrfToken; }

export function getCurrentIso() {
    if (currentIso) return currentIso;
    const sel = document.querySelector('.date-num.selected');
    return sel ? sel.dataset.iso : null;
}

export function setCurrentIso(v) {
    currentIso = v || null;
}

export function fmtNum(v) {
    const rounded = Math.round(v * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

/* ---------- Modal de confirmación (dialog nativo) ---------- */
export function showConfirmDialog(onSave, onDiscard) {
    confirmCbs = { onSave, onDiscard };
    const dialog = document.getElementById('confirm-modal');
    if (dialog && typeof dialog.showModal === 'function') {
        dialog.showModal();
        // Foco inicial en la acción primaria.
        const primary = dialog.querySelector('#confirm-save');
        if (primary) primary.focus();
    }
}

export function hideConfirmDialog() {
    const dialog = document.getElementById('confirm-modal');
    if (dialog && dialog.open) dialog.close();
    confirmCbs = null;
}

/* ---------- Estado del editor ---------- */
export function editorEditmode() {
    return document.getElementById('session-editor')?.dataset.editmode;
}

export function currentFecha() {
    const iso = getCurrentIso();
    if (iso) return iso;
    const form = document.getElementById('session-form') || document.getElementById('nutrition-form');
    const input = form && form.querySelector('input[name="fecha"]');
    return input ? input.value : '';
}

export function serializeForm() {
    const form = document.getElementById('session-form');
    if (!form) return '[]';
    const rows = Array.from(form.querySelectorAll('#set-rows .set-row')).map(row => {
        const sel = row.querySelector('.ej-select');
        const inputs = Array.from(row.querySelectorAll('input')).map(i => i.value);
        return [sel ? sel.value : '', ...inputs];
    });
    return JSON.stringify(rows);
}

export function captureBaseline() {
    const editor = document.getElementById('session-editor');
    if (editor) editor.dataset.baseline = serializeForm();
    const form = document.getElementById('session-form');
    if (form) clearFieldHistory(form);
}

export function isDirty() {
    const editor = document.getElementById('session-editor');
    if (!editor || editor.dataset.baseline === undefined) return false;
    return editor.dataset.baseline !== serializeForm();
}

/* Ctrl+Z local (R1+R2): restaura el último campo en edición, sin servidor.
   Se vacía al re-baselinear (guardar/navegar). */
const fieldPrev = new WeakMap();
const fieldHist = new Map();
const FIELD_HIST_MAX = 50;

function histKey(form) {
    return (form && form.id) || 'form';
}

export function noteFormFocus(form) {
    if (!form || !form.querySelectorAll) return;
    form.querySelectorAll('input, select').forEach(function (el) {
        if (!el.disabled && el.type !== 'hidden' && !fieldPrev.has(el)) {
            fieldPrev.set(el, el.value);
        }
    });
}

export function noteFieldEdit(el) {
    const form = el && el.form;
    if (!form || el.disabled || el.type === 'hidden') return;
    const prev = fieldPrev.has(el) ? fieldPrev.get(el) : el.value;
    fieldPrev.set(el, el.value);
    if (prev === el.value) return;
    const key = histKey(form);
    let stack = fieldHist.get(key);
    if (!stack) {
        stack = [];
        fieldHist.set(key, stack);
    }
    const top = stack[stack.length - 1];
    if (top && top.el === el) return;
    stack.push({ el: el, prev: prev });
    if (stack.length > FIELD_HIST_MAX) stack.shift();
}

export function clearFieldHistory(form) {
    if (form) fieldHist.delete(histKey(form));
    else fieldHist.clear();
}

export function popFieldEdit(form) {
    const stack = form ? fieldHist.get(histKey(form)) : null;
    const item = stack ? stack.pop() : null;
    if (!item) return false;
    if (!item.el.isConnected || item.el.disabled) return popFieldEdit(form);
    item.el.value = item.prev;
    fieldPrev.set(item.el, item.prev);
    item.el.dispatchEvent(
        new Event(item.el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })
    );
    return true;
}
