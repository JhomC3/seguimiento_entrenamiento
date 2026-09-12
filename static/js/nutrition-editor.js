// nutrition-editor.js — editor del día de alimentación.
// Copia fiel del mecanismo del editor de sesión (editor.js) con ids nutrition-*:
// modo edición con lápiz, altura fija, filas +/− solo en edición, dirty-check.
// Extras de nutrición: preview de 9 nutrientes, filas Objetivo/Consumido en
// vivo, parámetros (peso/factores/kcal) y eliminación del día.

import { clearFieldHistory, getAlimentoMap, hideConfirmDialog, showConfirmDialog } from './state.js';
import { syncNutritionSortableState } from './row-sortable.js';
import { doNav } from './date-navigation.js';

const PREVIEW_CELLS = [
    ['kcal', 'kcal-cell'],
    ['carbohidratos', 'carb-cell'],
    ['proteina', 'prot-cell'],
    ['grasa', 'fat-cell'],
    ['fibra', 'fibra-cell'],
    ['hierro', 'hierro-cell'],
    ['calcio', 'calcio-cell'],
    ['vitamina_c', 'vitc-cell'],
    ['vitamina_a', 'vita-cell'],
];
const CONSUMED_TARGETS = [
    ['kcal', 'consumed-kcal'],
    ['carbohidratos', 'consumed-carb'],
    ['proteina', 'consumed-prot'],
    ['grasa', 'consumed-fat'],
];
const TARGET_CELLS = [
    ['kcal', 'target-kcal'],
    ['carbohidratos', 'target-carb'],
    ['proteina', 'target-prot'],
    ['grasa', 'target-fat'],
];

const ROWS_VISIBLE = 17.5;
const PANEL_BUFFER = 2;
const ROW_BORDER_PX = 1;

let bound = false;
let rowHMeasured = null;
let pendingNavIso = null;

function roundHalfUp(v) {
    return Math.floor(v + 0.5);
}

/* ---------- Estado del editor ---------- */
function panel() {
    return document.getElementById('nutrition-panel');
}

function panelEditmode() {
    return panel()?.dataset.editmode;
}

function serializeNutrition() {
    const form = document.getElementById('nutrition-form');
    if (!form) return '';
    const rows = Array.from(form.querySelectorAll('#nutrition-rows .nutrition-row')).map(row =>
        Array.from(row.querySelectorAll('input')).map(i => i.value)
    );
    const params = Array.from(
        form.querySelectorAll('input[type="hidden"][name="peso_kg"], '
            + 'input[type="hidden"][name="factor_proteina"], '
            + 'input[type="hidden"][name="factor_grasa"], '
            + 'input[type="hidden"][name="kcal_objetivo"]')
    ).map(i => i.value);
    return JSON.stringify([rows, params]);
}

function captureBaseline() {
    const form = document.getElementById('nutrition-form');
    if (!form) return;
    form.dataset.baseline = serializeNutrition();
    clearFieldHistory(form);
}

export function nutritionIsDirty() {
    const form = document.getElementById('nutrition-form');
    if (!form || form.dataset.baseline === undefined) return false;
    return form.dataset.baseline !== serializeNutrition();
}

export function nutritionSubmitSave() {
    const form = document.getElementById('nutrition-form');
    if (form) form.requestSubmit();
}

function syncNutritionButtons() {
    const p = panel();
    const st = document.getElementById('nutrition-editor-state');
    if (!p || !st) return;
    const editable = p.dataset.editmode === '1';
    const pencil = p.querySelector('.nutrition-pencil-btn');
    if (pencil) {
        pencil.classList.toggle('on', editable);
        pencil.classList.toggle('off', !editable);
    }
    const trash = p.querySelector('.nutrition-delete-btn');
    if (trash) {
        trash.hidden = st.dataset.hasData !== '1';
        trash.classList.toggle('on', editable && st.dataset.hasData === '1');
    }
    const bookmark = p.querySelector('.nutrition-template-btn');
    if (bookmark) bookmark.classList.toggle('on', editable);
    const actions = document.getElementById('nutrition-edit-actions');
    const saveBtn = actions && actions.querySelector('button[type="submit"]');
    if (saveBtn) saveBtn.disabled = !editable;
}

function setNutritionReadonly() {
    const form = document.getElementById('nutrition-form');
    if (!form) return;
    form.querySelectorAll('input').forEach(el => { el.disabled = true; });
    form.querySelectorAll('.row-actions').forEach(el => { el.classList.add('hidden'); el.hidden = true; });
    const p = panel();
    if (p) p.dataset.editmode = '0';
    const actions = document.getElementById('nutrition-edit-actions');
    if (actions) actions.classList.add('invisible');
    captureBaseline();
    syncNutritionButtons();
}

function enterNutritionEditMode() {
    if (panelEditmode() === '1') return;
    const form = document.getElementById('nutrition-form');
    if (!form) return;
    form.querySelectorAll('input').forEach(el => { el.disabled = false; });
    form.querySelectorAll('.row-actions').forEach(el => { el.classList.remove('hidden'); el.hidden = false; });
    const p = panel();
    if (p) p.dataset.editmode = '1';
    syncNutritionSortableState();
    const st = document.getElementById('nutrition-editor-state');
    if (st) st.dataset.readonly = '0';
    captureBaseline();
    updateEditActionsVisibility();
    syncNutritionButtons();
}

export function ensureNutritionEditable() {
    if (panelEditmode() !== '1') enterNutritionEditMode();
}

function exitNutritionEditMode() {
    // Igual que el editor de sesión: re-render del servidor para salir de edición.
    const p = panel();
    const fecha = p?.querySelector('#nutrition-form input[name="fecha"]')?.value;
    if (nutritionIsDirty()) {
        showConfirmDialog(
            function () {
                pendingNavIso = fecha || '';
                nutritionSubmitSave();
            },
            function () { doNav(fecha || '', true); }
        );
    } else {
        doNav(fecha || '', true);
    }
}

function toggleNutritionEdit() {
    if (panelEditmode() === '1') {
        exitNutritionEditMode();
    } else {
        enterNutritionEditMode();
    }
}

function handleNutritionState() {
    const st = document.getElementById('nutrition-editor-state');
    if (st && st.dataset.readonly === '1') setNutritionReadonly();
}

function updateEditActionsVisibility() {
    const actions = document.getElementById('nutrition-edit-actions');
    if (!actions) return;
    const show = panelEditmode() === '1' && nutritionIsDirty();
    actions.classList.toggle('invisible', !show);
}

/* ---------- Altura fija: misma fórmula que el editor de sesión ---------- */
export function fitNutritionRowsToPanel() {
    const p = panel();
    const tbody = document.getElementById('nutrition-rows');
    if (!p || !tbody) return;
    const thead = p.querySelector('.table-scroll thead');
    const theadH = thead ? thead.getBoundingClientRect().height : 20;
    if (rowHMeasured === null) {
        const row = tbody.querySelector('.nutrition-row');
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
    const full = theadH + ROWS_VISIBLE * rowHMeasured + (ROWS_VISIBLE - 1) * ROW_BORDER_PX + PANEL_BUFFER;
    p.style.setProperty('--table-h', full + 'px');
}

/* ---------- Filas ---------- */
function renumber() {
    document.querySelectorAll('#nutrition-rows .nutrition-row').forEach((row, i) => {
        const num = row.querySelector('.nutrition-num');
        if (num) num.textContent = String(i + 1);
    });
}

export function refreshNutritionRowsOrder() {
    renumber();
    updateConsumido();
}

function nutritionAddRow() {
    if (panelEditmode() !== '1') return;
    const tbody = document.getElementById('nutrition-rows');
    const src = tbody && tbody.querySelector('.nutrition-row');
    if (!src) return;
    const clone = src.cloneNode(true);
    clone.querySelectorAll('input').forEach(i => { i.value = ''; });
    clone.querySelectorAll('.nutrition-preview').forEach(c => { c.textContent = '—'; });
    tbody.appendChild(clone);
    const first = clone.querySelector('input');
    if (first) first.focus();
    updateConsumido();
    updateEditActionsVisibility();
}

function nutritionRemoveRow(btn) {
    if (panelEditmode() !== '1') return;
    const row = btn.closest('.nutrition-row');
    const tbody = document.getElementById('nutrition-rows');
    if (!row || !tbody) return;
    if (tbody.querySelectorAll('.nutrition-row').length > 1) {
        row.remove();
    } else {
        row.querySelectorAll('input').forEach(i => { i.value = ''; });
        row.querySelectorAll('.nutrition-preview').forEach(c => { c.textContent = '—'; });
    }
    updateConsumido();
    updateEditActionsVisibility();
}

/* ---------- Preview y filas Objetivo/Consumido ---------- */
function previewRow(row) {
    const name = (row.querySelector('.food-select')?.value || '').trim();
    const raw = (row.querySelector('.cantidad-input')?.value || '').trim();
    const qty = parseFloat(raw.replace(',', '.'));
    const food = getAlimentoMap()[name] || null;
    PREVIEW_CELLS.forEach(([key, cls]) => {
        const cell = row.querySelector('.' + cls);
        if (!cell) return;
        cell.textContent = food && qty > 0 ? String(roundHalfUp((food[key] * qty) / 100)) : '—';
    });
}

function paramsFromInputs() {
    const get = id => parseFloat(document.getElementById(id)?.value) || 0;
    return {
        peso_kg: get('param-peso'),
        kcal_objetivo: get('param-kcal'),
        factor_proteina: get('param-factor-prot'),
        factor_grasa: get('param-factor-grasa'),
    };
}

function updateObjetivo() {
    const p = paramsFromInputs();
    const prot = roundHalfUp(p.peso_kg * p.factor_proteina);
    const fat = roundHalfUp(p.peso_kg * p.factor_grasa);
    const kcal = roundHalfUp(p.kcal_objetivo);
    const carb = roundHalfUp((kcal - 4 * prot - 9 * fat) / 4);
    TARGET_CELLS.forEach(([key, cls]) => {
        const cell = document.querySelector('.' + cls);
        if (!cell) return;
        cell.textContent = String({ kcal, carbohidratos: carb, proteina: prot, grasa: fat }[key]);
    });
    const form = document.getElementById('nutrition-form');
    if (!form) return;
    const set = (name, value) => {
        const input = form.querySelector('input[name="' + name + '"]');
        if (input) input.value = String(value);
    };
    set('peso_kg', p.peso_kg);
    set('kcal_objetivo', p.kcal_objetivo);
    set('factor_proteina', p.factor_proteina);
    set('factor_grasa', p.factor_grasa);
}

function updateConsumido() {
    const sums = { kcal: 0, carbohidratos: 0, proteina: 0, grasa: 0 };
    let grams = 0;
    document.querySelectorAll('#nutrition-rows .nutrition-row').forEach(row => {
        const qtyRaw = (row.querySelector('.cantidad-input')?.value || '').trim();
        const qty = parseFloat(qtyRaw.replace(',', '.'));
        if (qty > 0) grams += qty;
        CONSUMED_TARGETS.forEach(([key, cls]) => {
            sums[key] += parseFloat(row.querySelector('.' + PREVIEW_CELLS.find(c => c[0] === key)[1])?.textContent) || 0;
        });
    });
    CONSUMED_TARGETS.forEach(([key, cls]) => {
        const cell = document.querySelector('.' + cls);
        if (cell) cell.textContent = String(Math.round(sums[key]));
    });
    const gramsCell = document.querySelector('.consumed-grams');
    if (gramsCell) gramsCell.textContent = grams > 0 ? Math.round(grams) + ' g' : '—';
}

/* ---------- Eliminar día ---------- */
function eliminarDia() {
    if (panelEditmode() !== '1') {
        const notice = document.getElementById('notice-container');
        if (notice) {
            notice.innerHTML = '<div class="notice notice-error" data-dismiss="2500">Activa el modo editable primero.</div>';
        }
        return;
    }
    const fecha = document.querySelector('#nutrition-form input[name="fecha"]')?.value;
    if (!fecha) return;
    document.getElementById('confirm-msg').textContent = '¿Eliminar el día de alimentación?';
    showConfirmDialog(function () {
        htmx.ajax('POST', '/alimentacion/eliminar', {
            values: { fecha },
            target: 'body',
            swap: 'none',
        });
    }, null);
}

/* ---------- Navegación con cambios sin guardar ---------- */
export function requestNutritionNav(iso) {
    if (nutritionIsDirty()) {
        showConfirmDialog(
            function () {
                pendingNavIso = iso;
                nutritionSubmitSave();
            },
            function () { doNav(iso, true); }
        );
        return;
    }
    doNav(iso);
}

/* ---------- Eventos delegados ---------- */
export function syncNutritionEmptyState() {
    const p = panel();
    const st = document.getElementById('nutrition-editor-state');
    if (!p || !st) return;
    const empty = p.querySelector('[data-empty-state="nutrition"]');
    if (!empty) return;
    empty.hidden = st.dataset.hasData === '1';
}

function onClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;
    if (action === 'nutrition-toggle-edit') {
        toggleNutritionEdit();
    } else if (action === 'cancel-nutrition-edit') {
        exitNutritionEditMode();
    } else if (action === 'nutrition-delete') {
        eliminarDia();
    } else if (action === 'nutrition-row-add') {
        nutritionAddRow();
    } else if (action === 'nutrition-row-remove') {
        nutritionRemoveRow(el);
    }
}

function onInput(e) {
    if (e.target.closest('#target-params')) {
        updateObjetivo();
        updateEditActionsVisibility();
        return;
    }
    if (e.target.closest('#nutrition-form')) {
        const row = e.target.closest('.nutrition-row');
        if (row) {
            previewRow(row);
            updateConsumido();
        }
        updateEditActionsVisibility();
    }
}

function onFormSubmit(e) {
    const form = e.target.closest('#nutrition-form');
    if (!form) return;
    if (panelEditmode() !== '1') {
        e.preventDefault();
        return;
    }
    form.querySelectorAll('#nutrition-rows .nutrition-row').forEach(row => {
        const inputs = row.querySelectorAll('input');
        const empty = !(inputs[0].value.trim() || inputs[1].value.trim());
        if (empty) row.remove();
    });
}

/* ---------- Inicialización y refresco ---------- */
export function initNutritionEditor() {
    if (!bound) {
        document.addEventListener('click', onClick);
        document.addEventListener('input', onInput);
        document.addEventListener('submit', onFormSubmit, true);
        bound = true;
    }
    refreshNutritionEditor();
}

export function refreshNutritionEditor() {
    if (!document.getElementById('nutrition-form')) return;
    const st = document.getElementById('nutrition-editor-state');
    const p = panel();
    if (st && p) p.dataset.editmode = st.dataset.readonly === '1' ? '0' : '1';
    handleNutritionState();
    syncNutritionButtons();
    updateObjetivo();
    updateConsumido();
    fitNutritionRowsToPanel();
    captureBaseline();
    updateEditActionsVisibility();
    if (pendingNavIso) {
        const iso = pendingNavIso;
        pendingNavIso = null;
        doNav(iso, true);
    }
}
