// splits.js — owns: gestor de splits (catálogo → semana, DnD nativo, guardar/abrir/eliminar).
// DOM owned: #split-save-form, #splits-catalog, #split-board, .split-day-zone,
// .split-item-card, #splits-section, #split-metrics-panel.
// Public API: initSplits.
//
// Regla de negocio (espejo del servidor): 1 instancia colocada = 1 serie. El
// servidor es la única autoridad (grupo muscular, validación, métricas); la
// preview client-side se descarta en cada render OOB.

import { showNotice } from './notices.js';
import { showConfirmDialog } from './state.js';

// Estado del módulo (no compartido con otros módulos).
const state = {
    selectedDay: 'LUNES',
    openSplitId: null,
    uidSeq: 0,
    catalogDrag: false,
};

function isSplitsPage() {
    return !!document.getElementById('split-save-form');
}

function form() {
    return document.getElementById('split-save-form');
}

function readOpenSplitId() {
    const marker = document.getElementById('split-open-state');
    return marker && marker.dataset.splitId ? marker.dataset.splitId : null;
}

function setFormSplitId(id) {
    const input = form() && form().querySelector('input[name="split_id"]');
    if (input) input.value = id || '';
}

function selectedDayButton(day) {
    return document.querySelector(`.split-day-select[data-day="${day}"]`);
}

function selectDay(day) {
    state.selectedDay = day;
    document.querySelectorAll('.split-day-select').forEach(function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.day === day));
    });
}

function dayZone(day) {
    return document.querySelector(`.split-day-zone[data-day="${day}"]`);
}

function dayList(day) {
    const zone = dayZone(day);
    return zone && zone.querySelector('.split-day-items');
}

function makeItemCard(ejercicio, grupo, itemType) {
    const card = document.createElement('div');
    card.className = 'split-item-card';
    card.draggable = true;
    state.uidSeq += 1;
    card.dataset.splitItemId = 'ui-' + state.uidSeq;
    card.dataset.ejercicio = ejercicio;
    card.dataset.grupo = grupo;
    card.dataset.itemType = itemType;

    const name = document.createElement('span');
    name.className = 'split-item-name';
    name.textContent = ejercicio;
    name.title = ejercicio;

    const group = document.createElement('span');
    group.className = 'split-item-group';
    group.textContent = grupo;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'row-btn';
    btn.dataset.action = 'split-item-remove';
    btn.setAttribute('aria-label', 'Eliminar ' + ejercicio + ' del día');
    btn.title = 'Eliminar';
    btn.textContent = '−';

    card.appendChild(name);
    card.appendChild(group);
    card.appendChild(btn);
    return card;
}

function addItemToDay(day, ejercicio, grupo, itemType) {
    const list = dayList(day);
    if (!list) return;
    const card = makeItemCard(ejercicio, grupo, itemType);
    card.dataset.dia = day;
    list.appendChild(card);
    updatePreview();
}

/* ---------- Preview client-side de métricas (nunca se envía al servidor) ---------- */
function previewSpan(label, value, group) {
    const span = document.createElement('span');
    span.className = 'split-metric';
    if (group) span.dataset.previewGroup = group;
    span.appendChild(document.createTextNode(label + ': '));
    const strong = document.createElement('strong');
    strong.textContent = String(value);
    span.appendChild(strong);
    return span;
}

function updatePreview() {
    if (!isSplitsPage()) return;

    // Contadores por día + placeholder vacío.
    const cards = [];
    document.querySelectorAll('.split-day-zone').forEach(function (zone) {
        const items = zone.querySelectorAll('.split-item-card');
        const count = items.length;
        const countEl = zone.querySelector('.split-day-count');
        if (countEl) countEl.textContent = count + ' serie' + (count === 1 ? '' : 's');
        const empty = zone.querySelector('.split-empty');
        if (empty) empty.hidden = count > 0;
        items.forEach(function (c) { cards.push(c); });
    });

    const preview = document.getElementById('split-metrics-preview');
    if (!preview) return;
    const days = new Set();
    const exercises = new Set();
    const groups = {};
    cards.forEach(function (c) {
        days.add(c.dataset.dia);
        exercises.add(c.dataset.ejercicio);
        groups[c.dataset.grupo] = (groups[c.dataset.grupo] || 0) + 1;
    });
    const total = cards.length;
    preview.replaceChildren(
        previewSpan('Series', total),
        previewSpan('Días activos', days.size),
        previewSpan('Ejercicios distintos', exercises.size)
    );
    Object.keys(groups).sort().forEach(function (g) {
        preview.appendChild(previewSpan(g, groups[g], g));
    });
}

/* ---------- Sincronización del formulario (arrays alineados, orden visual) ---------- */
function syncSplitForm() {
    const f = form();
    if (!f) return;
    f.querySelectorAll('input[name="dia"], input[name="item_type"], input[name="ejercicio"]')
        .forEach(function (el) { el.remove(); });
    document.querySelectorAll('.split-day-zone').forEach(function (zone) {
        zone.querySelectorAll('.split-item-card').forEach(function (card) {
            ['dia', 'item_type', 'ejercicio'].forEach(function (name) {
                const inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = name;
                inp.value = name === 'dia' ? zone.dataset.day
                    : name === 'item_type' ? card.dataset.itemType
                        : card.dataset.ejercicio;
                f.appendChild(inp);
            });
        });
    });
}

/* ---------- Acciones delegadas (data-action) ---------- */
function splitSave() {
    const f = form();
    if (!f) return;
    const nombre = f.querySelector('input[name="nombre"]');
    if (!nombre || !nombre.value.trim()) {
        if (nombre) nombre.focus();
        showNotice('Ponle nombre al split antes de guardar.', 'error');
        return;
    }
    syncSplitForm();
    f.requestSubmit();
}

function splitNew() {
    const f = form();
    if (!f) return;
    setFormSplitId(null);
    const nombre = f.querySelector('input[name="nombre"]');
    if (nombre) nombre.value = '';
    document.querySelectorAll('#split-board .split-item-card').forEach(function (c) { c.remove(); });
    selectDay('LUNES');
    updatePreview();
    if (nombre) nombre.focus();
    showNotice('Nuevo split: arma la semana desde el catálogo.', 'success', 3000);
}

function splitOpen(id) {
    state.openSplitId = String(id);
    setFormSplitId(id);
    htmx.ajax('GET', '/split/' + id, { target: 'body', swap: 'none' });
}

function splitDelete(id, nombre) {
    document.getElementById('confirm-msg').textContent =
        '¿Eliminar el split "' + nombre + '"?';
    showConfirmDialog(function () {
        htmx.ajax('POST', '/split/eliminar/' + id, { target: 'body', swap: 'none' });
    }, null);
}

/* ---------- DnD nativo: catálogo (copia) y reorden/movimiento entre días ---------- */
function getDragAfterElement(container, y) {
    const cards = Array.from(container.querySelectorAll('.split-item-card:not(.dragging)'));
    return cards.reduce(function (closest, child) {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return { offset: offset, element: child };
        return closest;
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function onDragStart(e) {
    const chip = e.target.closest('.split-catalog-chip');
    if (chip) {
        state.catalogDrag = true;
        e.dataTransfer.setData('text/plain', JSON.stringify({
            ejercicio: chip.dataset.ejercicio,
            grupo: chip.dataset.grupo,
            itemType: chip.dataset.itemType,
        }));
        e.dataTransfer.effectAllowed = 'copy';
        return;
    }
    const card = e.target.closest('.split-item-card');
    if (!card) return;
    if (e.target.closest('button')) { e.preventDefault(); return; }
    state.catalogDrag = false;
    e.dataTransfer.setData('text/plain', 'item:' + card.dataset.splitItemId);
    e.dataTransfer.effectAllowed = 'move';
    card.classList.add('dragging');
}

function onDragOver(e) {
    const zone = e.target.closest('.split-day-zone');
    if (!zone) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = state.catalogDrag ? 'copy' : 'move';
    if (!zone.classList.contains('drop-target')) zone.classList.add('drop-target');
    if (!state.catalogDrag) {
        const list = zone.querySelector('.split-day-items');
        const dragging = document.querySelector('.split-item-card.dragging');
        if (list && dragging && dragging.parentElement === list) {
            const after = getDragAfterElement(list, e.clientY);
            if (after == null) list.appendChild(dragging);
            else list.insertBefore(dragging, after);
        }
    }
}

function onDrop(e) {
    const zone = e.target.closest('.split-day-zone');
    if (!zone) return;
    const payload = e.dataTransfer.getData('text/plain');
    if (!payload) return;
    e.preventDefault();
    if (payload.startsWith('item:')) {
        const id = payload.slice(5);
        const card = document.querySelector(
            '.split-item-card[data-split-item-id="' + id + '"]'
        );
        if (card) {
            const list = zone.querySelector('.split-day-items');
            // Intra-día: el dragover ya fijó la posición; solo re-append si la
            // tarjeta viene de OTRO día (movimiento entre zonas).
            if (list && card.parentElement !== list) {
                list.appendChild(card);
                card.dataset.dia = zone.dataset.day;
            }
        }
    } else {
        try {
            const p = JSON.parse(payload);
            addItemToDay(zone.dataset.day, p.ejercicio, p.grupo, p.itemType);
        } catch (err) {
            // Payload desconocido: ignorar (nunca reaccionar a datos externos).
        }
    }
    updatePreview();
}

function onDragEnd(e) {
    document.querySelectorAll('.split-day-zone.drop-target').forEach(function (z) {
        z.classList.remove('drop-target');
    });
    const card = e.target.closest('.split-item-card');
    if (card) card.classList.remove('dragging');
    state.catalogDrag = false;
    updatePreview();
}

/* ---------- Init (idempotente, contrato v3: listeners delegados) ---------- */
export function initSplits() {
    if (!isSplitsPage()) return;
    if (document.body.dataset.splitsReady) return;
    document.body.dataset.splitsReady = '1';

    state.openSplitId = readOpenSplitId() || null;
    if (!state.openSplitId) setFormSplitId(null);

    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        switch (el.dataset.action) {
            case 'split-day-select':
                selectDay(el.dataset.day);
                break;
            case 'split-add-item':
                addItemToDay(state.selectedDay, el.dataset.ejercicio, el.dataset.grupo, el.dataset.itemType);
                break;
            case 'split-item-remove':
                el.closest('.split-item-card').remove();
                updatePreview();
                break;
            case 'split-open':
                splitOpen(el.dataset.splitId);
                break;
            case 'split-delete':
                splitDelete(el.dataset.splitId, el.dataset.splitNombre);
                break;
            case 'split-new':
                splitNew();
                break;
            case 'split-save':
                splitSave();
                break;
        }
    });

    document.addEventListener('input', function (e) {
        if (!e.target.closest || e.target.dataset.action !== 'split-catalog-search') return;
        const query = e.target.value.trim().toLowerCase();
        let visible = 0;
        document.querySelectorAll('#splits-catalog > div').forEach(function (group) {
            let groupVisible = false;
            group.querySelectorAll('.split-catalog-chip').forEach(function (chip) {
                const match = !query || chip.textContent.toLowerCase().indexOf(query) !== -1;
                chip.hidden = !match;
                if (match) groupVisible = true;
            });
            group.hidden = !groupVisible;
            if (groupVisible) visible += 1;
        });
        const empty = document.getElementById('split-catalog-empty');
        if (empty) empty.hidden = visible > 0;
    });

    document.addEventListener('dragstart', onDragStart);
    document.addEventListener('dragover', onDragOver);
    document.addEventListener('drop', onDrop);
    document.addEventListener('dragend', onDragEnd);

    // Board refrescado por OOB (guardar/abrir/eliminar/undo): re-sincronizar
    // el split abierto desde el marcador server-side.
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.detail && e.detail.target && e.detail.target.id === 'split-board') {
            const id = readOpenSplitId();
            state.openSplitId = id || null;
            if (!id) setFormSplitId(null);
            selectDay(state.selectedDay);
        }
    });

    document.body.addEventListener('htmx:afterRequest', function (e) {
        const path = (e.detail && e.detail.requestConfig && e.detail.requestConfig.path) || '';
        if (path === '/undo' && state.openSplitId) {
            // El undo puede haber restaurado/eliminado el split abierto:
            // refetch del board para reflejar el estado real.
            htmx.ajax('GET', '/split/' + state.openSplitId, { target: 'body', swap: 'none' });
        }
    });

    selectDay('LUNES');
    updatePreview();
}
