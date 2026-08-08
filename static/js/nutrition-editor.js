// nutrition-editor.js — editor del día de alimentación: filas, previsualización
// de los 9 nutrientes desde el catálogo, filas Objetivo/Consumido en vivo.
// El servidor es la fuente autoritativa del cálculo; la previsualización usa el
// mapa compacto `alimento_map` de #app-config (valores por 100 g) y las mismas
// fórmulas de objetivo (Atwater 4/4/9) con redondeo half-up.

import { getAlimentoMap, hideConfirmDialog, showConfirmDialog } from './state.js';

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

function addRow() {
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
    updateConsumido();
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
    if (e.target.closest('#target-params')) {
        updateObjetivo();
        return;
    }
    if (e.target.closest('#nutrition-form')) {
        const row = e.target.closest('.nutrition-row');
        if (row) {
            previewRow(row);
            updateConsumido();
        }
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
    updateObjetivo();
    updateConsumido();
    captureBaseline();
}
