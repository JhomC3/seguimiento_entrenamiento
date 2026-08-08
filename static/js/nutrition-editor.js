// nutrition-editor.js — editor del día de alimentación: filas, previsualización
// desde el catálogo y navegación por fecha.
// El servidor es la fuente autoritativa del cálculo; la previsualización usa el
// mapa compacto `alimento_map` de #app-config (valores por 100 g) con redondeo
// half-up. Los totales se re-suman desde las celdas de previsualización.

import { getAlimentoMap, hideConfirmDialog, showConfirmDialog } from './state.js';

const PREVIEW_CELLS = [
    ['kcal', 'kcal-cell'],
    ['carbohidratos', 'carb-cell'],
    ['proteina', 'prot-cell'],
    ['grasa', 'fat-cell'],
];
const TOTAL_KEYS = ['kcal', 'carbohidratos', 'proteina', 'grasa'];

let bound = false;

function roundHalfUp(v) {
    return Math.floor(v + 0.5);
}

function serializeNutrition() {
    const form = document.getElementById('nutrition-form');
    if (!form) return '';
    return JSON.stringify(
        Array.from(form.querySelectorAll('#nutrition-rows .nutrition-row')).map(row =>
            Array.from(row.querySelectorAll('input')).map(i => i.value)
        )
    );
}

function captureBaseline() {
    const form = document.getElementById('nutrition-form');
    if (form) form.dataset.baseline = serializeNutrition();
}

function isDirty() {
    const form = document.getElementById('nutrition-form');
    if (!form || form.dataset.baseline === undefined) return false;
    return form.dataset.baseline !== serializeNutrition();
}

function renumber() {
    document.querySelectorAll('#nutrition-rows .nutrition-row').forEach((row, i) => {
        const num = row.querySelector('.nutrition-num');
        if (num) num.textContent = String(i + 1);
    });
}

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

function updateTotals() {
    const bar = document.getElementById('nutrition-totals');
    if (!bar) return;
    const sums = { kcal: 0, carbohidratos: 0, proteina: 0, grasa: 0 };
    document.querySelectorAll('#nutrition-rows .nutrition-row').forEach(row => {
        TOTAL_KEYS.forEach(key => {
            sums[key] += parseFloat(row.querySelector('.' + PREVIEW_CELLS.find(c => c[0] === key)[1])?.textContent) || 0;
        });
    });
    TOTAL_KEYS.forEach(key => {
        const el = bar.querySelector('[data-total="' + key + '"]');
        if (el) el.textContent = String(Math.round(sums[key]));
    });
}

function addRow() {
    const tbody = document.getElementById('nutrition-rows');
    const src = tbody && tbody.querySelector('.nutrition-row');
    if (!src) return;
    const clone = src.cloneNode(true);
    clone.querySelectorAll('input').forEach(i => { i.value = ''; });
    clone.querySelectorAll('.nutrition-preview').forEach(c => { c.textContent = '—'; });
    tbody.appendChild(clone);
    renumber();
    const first = clone.querySelector('input');
    if (first) first.focus();
}

function removeRow(btn) {
    const row = btn.closest('.nutrition-row');
    const tbody = document.getElementById('nutrition-rows');
    if (!row || !tbody) return;
    if (tbody.querySelectorAll('.nutrition-row').length > 1) {
        row.remove();
    } else {
        row.querySelectorAll('input').forEach(i => { i.value = ''; });
        row.querySelectorAll('.nutrition-preview').forEach(c => { c.textContent = '—'; });
    }
    renumber();
    updateTotals();
}

function currentIso() {
    const input = document.querySelector('#nutrition-date-navigator input[name="fecha"]');
    return input ? input.value : '';
}

function shiftDate(iso, delta) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}

function doNavigate(iso) {
    if (!iso) return;
    const input = document.querySelector('#nutrition-date-navigator input[name="fecha"]');
    if (input) input.value = iso;
    const title = document.querySelector('#nutrition-date-navigator h3');
    if (title) {
        const [y, m, d] = iso.split('-');
        title.textContent = d + '/' + m + '/' + y;
    }
    htmx.ajax('GET', '/alimentacion/editor?fecha=' + encodeURIComponent(iso), {
        target: '#nutrition-editor-wrap',
        swap: 'innerHTML',
    });
}

function navigateTo(iso) {
    if (isDirty()) {
        showConfirmDialog(() => doNavigate(iso), hideConfirmDialog, 'Hay cambios sin guardar. ¿Continuar?');
        return;
    }
    doNavigate(iso);
}

function deleteDay() {
    const fecha = currentIso();
    if (!fecha) return;
    showConfirmDialog(() => {
        htmx.ajax('POST', '/alimentacion/eliminar', {
            values: { fecha },
            target: 'body',
            swap: 'none',
        });
    }, hideConfirmDialog, '¿Eliminar el día completo?');
}

function onClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;
    if (action === 'nutrition-row-add') {
        addRow();
    } else if (action === 'nutrition-row-remove') {
        removeRow(el);
    } else if (action === 'nutrition-prev' || action === 'nutrition-next') {
        const iso = currentIso();
        if (iso) navigateTo(shiftDate(iso, action === 'nutrition-prev' ? -1 : 1));
    } else if (action === 'nutrition-delete') {
        deleteDay();
    }
}

function onInput(e) {
    if (!e.target.closest('#nutrition-form')) return;
    const row = e.target.closest('.nutrition-row');
    if (row) {
        previewRow(row);
        updateTotals();
    }
}

function onDateChange(e) {
    if (e.target.closest('#nutrition-date-navigator input[name="fecha"]')) {
        navigateTo(e.target.value);
    }
}

function onFormSubmit(e) {
    const form = e.target.closest('#nutrition-form');
    if (!form) return;
    form.querySelectorAll('#nutrition-rows .nutrition-row').forEach(row => {
        const inputs = row.querySelectorAll('input');
        const empty = !(inputs[0].value.trim() || inputs[1].value.trim());
        if (empty) row.remove();
    });
    renumber();
}

export function initNutritionEditor() {
    if (!bound) {
        document.addEventListener('click', onClick);
        document.addEventListener('input', onInput);
        document.addEventListener('change', onDateChange);
        document.addEventListener('submit', onFormSubmit, true);
        bound = true;
    }
    refreshNutritionEditor();
}

export function refreshNutritionEditor() {
    if (!document.getElementById('nutrition-form')) return;
    renumber();
    updateTotals();
    captureBaseline();
}
