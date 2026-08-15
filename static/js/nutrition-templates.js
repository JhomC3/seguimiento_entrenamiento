// nutrition-templates.js — owns: plantillas de alimentación (guardar desde el
// header del editor, lista del sidebar con drag&drop para reordenar y aplicar).
// Espejo del patrón DnD HTML5 de templates.js con estado local.

import { showNotice } from './notices.js';
import { persistOrderWithHtmx } from './reorder-controls.js';
import { showConfirmDialog } from './state.js';

let dragCard = null;
let dragOrderStart = null;
let droppedOnList = false;
let dragGhost = null;

function listEl() {
    return document.getElementById('nutrition-templates');
}

function currentFecha() {
    return document.querySelector('#nutrition-form input[name="fecha"]')?.value || '';
}

function entrenosOrder() {
    const list = listEl();
    if (!list) return [];
    return Array.from(list.querySelectorAll('.pt-card')).map(c => c.dataset.ptId);
}

function getDragAfterElement(list, y) {
    const els = Array.from(list.querySelectorAll('.pt-card:not(.dragging)'));
    let closest = { offset: Number.NEGATIVE_INFINITY, element: null };
    for (const el of els) {
        const box = el.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            closest = { offset, element: el };
        }
    }
    return closest.element;
}

function persistDragOrder(beforeOrder) {
    const list = listEl();
    if (!list) return;
    persistOrderWithHtmx(
        '/alimentacion/plantilla/reordenar',
        entrenosOrder(),
        list,
        beforeOrder || '',
        function () {
            showNotice('No se pudo guardar el orden. Reintenta.', 'error');
        }
    );
}

function applyTemplate(plantillaId) {
    const fecha = currentFecha();
    if (!fecha) return;
    // Política compartida: el editor de nutrición es siempre editable; si el
    // día ya tiene filas se exige confirmación de reemplazo. Un solo request
    // htmx con OOB de aviso.
    const hasRows = document.querySelectorAll('#nutrition-rows .nutrition-row').length > 0;
    const proceed = function () {
        // El body ya trae los OOB (editor + notice): swap none, solo OOB.
        htmx.ajax(
            'GET',
            '/alimentacion/plantilla/aplicar/' + plantillaId + '?fecha=' + encodeURIComponent(fecha),
            { target: 'body', swap: 'none' }
        );
    };
    if (hasRows) {
        document.getElementById('confirm-msg').textContent =
            '¿Reemplazar el día de alimentación con esta plantilla?';
        showConfirmDialog(proceed, null);
    } else {
        proceed();
    }
}

function deleteTemplate(plantillaId) {
    const fecha = currentFecha();
    htmx.ajax('POST', '/alimentacion/plantilla/eliminar/' + plantillaId, {
        target: 'body',
        swap: 'none',
    });
}

/* ---------- Guardar el día como plantilla (header) ---------- */
function toggleTemplateForm(show) {
    const wrap = document.getElementById('save-meal-template-form-wrap');
    const btn = document.querySelector('[data-action="nutrition-toggle-template-form"]');
    if (!wrap) return;
    const visible = show === undefined ? wrap.classList.contains('hidden') : show;
    wrap.classList.toggle('hidden', !visible);
    if (btn) btn.classList.toggle('on', visible);
    if (visible) {
        const input = wrap.querySelector('input[name="nombre"]');
        if (input) input.focus();
    }
}

function confirmTemplateSave() {
    const wrap = document.getElementById('save-meal-template-form-wrap');
    const form = wrap && document.getElementById('save-meal-template-form');
    if (!form || wrap.classList.contains('hidden')) return;
    const nombre = form.querySelector('input[name="nombre"]')?.value.trim();
    if (!nombre) {
        form.requestSubmit();
        return;
    }
    // Copia las filas del día como hidden inputs (mismo patrón que entrenamiento).
    form.querySelectorAll('input[name="alimento"], input[name="cantidad"]').forEach(el => el.remove());
    const seen = new Set();
    document.querySelectorAll('#nutrition-rows .nutrition-row').forEach(row => {
        const alimento = row.querySelector('input[name="alimento"]')?.value.trim() || '';
        const cantidad = row.querySelector('input[name="cantidad"]')?.value.trim() || '';
        if (!alimento || !cantidad || seen.has(alimento.toLowerCase())) return;
        seen.add(alimento.toLowerCase());
        const inpA = document.createElement('input');
        inpA.type = 'hidden';
        inpA.name = 'alimento';
        inpA.value = alimento;
        form.appendChild(inpA);
        const inpC = document.createElement('input');
        inpC.type = 'hidden';
        inpC.name = 'cantidad';
        inpC.value = cantidad;
        form.appendChild(inpC);
    });
    form.requestSubmit();
    toggleTemplateForm(false);
}

/* ---------- Inicialización (eventos delegados + DnD) ---------- */
export function initNutritionTemplatesDnD() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        const action = el.dataset.action;
        if (action === 'nutrition-toggle-template-form') {
            toggleTemplateForm();
        } else if (action === 'cancel-meal-template-form') {
            toggleTemplateForm(false);
        } else if (action === 'confirm-meal-template-save') {
            confirmTemplateSave();
        } else if (action === 'delete-meal-template') {
            deleteTemplate(el.dataset.ptId);
        } else if (action === 'apply-meal-template') {
            applyTemplate(el.dataset.ptId);
        }
    });
    refreshNutritionTemplatesDnD();
}

export function refreshNutritionTemplatesDnD() {
    const list = listEl();
    if (list) bindDnD(list);
    const panel = document.getElementById('nutrition-panel');
    if (panel && !panel.dataset.dropReady) {
        panel.dataset.dropReady = '1';
        panel.addEventListener('dragover', function (e) {
            e.preventDefault();
            panel.classList.add('drop-target');
        });
        panel.addEventListener('dragleave', function () {
            panel.classList.remove('drop-target');
        });
        panel.addEventListener('drop', function (e) {
            e.preventDefault();
            panel.classList.remove('drop-target');
            const id = e.dataTransfer.getData('text/plain');
            if (id) applyTemplate(id);
        });
    }
}

function bindDnD(list) {
    list.querySelectorAll('.pt-card').forEach(card => { card.draggable = true; });
    if (list.dataset.dndReady) return;
    list.dataset.dndReady = '1';

    list.addEventListener('dragstart', function (e) {
        const card = e.target.closest('.pt-card');
        if (!card) return;
        e.dataTransfer.setData('text/plain', card.dataset.ptId);
        e.dataTransfer.effectAllowed = 'move';
        if (dragGhost) dragGhost.remove();
        const rect = card.getBoundingClientRect();
        const ghost = card.cloneNode(true);
        ghost.style.cssText = 'position:absolute;left:-9999px;top:0;pointer-events:none;';
        document.body.appendChild(ghost);
        e.dataTransfer.setDragImage(ghost, e.clientX - rect.left, e.clientY - rect.top);
        card.classList.add('dragging');
        dragCard = card;
        dragOrderStart = entrenosOrder();
        droppedOnList = false;
        dragGhost = ghost;
    });

    list.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!dragCard) return;
        const after = getDragAfterElement(list, e.clientY);
        if (after == null) list.appendChild(dragCard);
        else list.insertBefore(dragCard, after);
    });

    list.addEventListener('drop', function (e) {
        e.preventDefault();
        droppedOnList = true;
    });

    list.addEventListener('dragend', function () {
        if (dragCard) dragCard.classList.remove('dragging');
        if (droppedOnList && dragOrderStart) {
            persistDragOrder(dragOrderStart.join(','));
        }
        dragCard = null;
        dragOrderStart = null;
        dragGhost = null;
    });
}
