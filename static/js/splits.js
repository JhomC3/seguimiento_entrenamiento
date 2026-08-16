// splits.js — owns: gestor de splits (SortableJS: catálogo clonable → 7 días,
// reorden/movimiento, duplicación con Shift, copia de día completo, guardar/abrir).
// DOM owned: #split-save-form, #splits-catalog, #split-board, .split-day-zone,
// .split-day-items, .split-item-card, .split-day-copy-handle, #splits-section,
// #split-metrics-panel.
// Public API: initSplits.
//
// Regla de negocio (espejo del servidor): 1 instancia colocada = 1 serie. El
// servidor es la única autoridad (grupo muscular, validación, métricas, límite);
// la preview client-side se descarta en cada render OOB.
//
// DnD estándar del proyecto (SortableJS, mismo patrón que row-sortable.js):
//   - catálogo: fuente clonable (pull:'clone') — el original permanece;
//   - días: destino ordenable con inserción en la posición exacta del puntero;
//   - Shift+arrastre de una instancia: duplica (el original vuelve a su sitio);
//   - Shift+arrastre del handle del día: copia el día completo.
// El único DnD nativo restante es el handle del día (operación de bloque, no de
// item) y usa el mismo resaltado .drop-target y las mismas tarjetas estándar.

import { showNotice } from './notices.js';
import { showConfirmDialog } from './state.js';

const SPLIT_DAYS = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO', 'DOMINGO'];

function dayLabel(day) {
    return day.charAt(0) + day.slice(1).toLowerCase();
}

// Estado del módulo (no compartido con otros módulos).
const state = {
    selectedDay: 'LUNES',
    openSplitId: null,
    uidSeq: 0,
    maxItems: 300,
    // uid del item arrastrado con Shift -> clon preparado en onStart.
    shiftCopies: new Map(),
    boardSortables: [],
    catalogSortables: [],
};

function isSplitsPage() {
    return !!document.getElementById('split-save-form');
}

function form() {
    return document.getElementById('split-save-form');
}

function readStateMarker() {
    const marker = document.getElementById('split-open-state');
    if (!marker) return null;
    return {
        splitId: marker.dataset.splitId || null,
        maxItems: parseInt(marker.dataset.maxItems, 10) || 300,
    };
}

function setFormSplitId(id) {
    const input = form() && form().querySelector('input[name="split_id"]');
    if (input) input.value = id || '';
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

function countCards() {
    return document.querySelectorAll('#split-board .split-item-card').length;
}

/* Límite global de instancias (espejo de MAX_SPLIT_ITEMS del servidor). */
function canAdd(extra) {
    return countCards() + extra <= state.maxItems;
}

function guardLimit(extra) {
    if (canAdd(extra)) return true;
    showNotice(
        'No se puede: superaría el límite de ' + state.maxItems + ' instancias del split.',
        'error'
    );
    return false;
}

function limitMessage() {
    return 'No se puede: superaría el límite de ' + state.maxItems + ' instancias del split.';
}

function finalizeCard(card, day) {
    state.uidSeq += 1;
    card.dataset.splitItemId = 'ui-' + state.uidSeq;
    card.dataset.dia = day;
    card.draggable = true;
    if (!card.querySelector('[data-action="split-item-remove"]')) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'row-btn';
        btn.dataset.action = 'split-item-remove';
        btn.setAttribute('aria-label', 'Eliminar ' + card.dataset.ejercicio + ' del día');
        btn.title = 'Eliminar';
        btn.textContent = '−';
        card.appendChild(btn);
    }
    return card;
}

function createCardFromChip(chip) {
    const card = document.createElement('div');
    card.className = 'split-item-card';
    card.dataset.ejercicio = chip.dataset.ejercicio;
    card.dataset.grupo = chip.dataset.grupo;
    card.dataset.itemType = chip.dataset.itemType;
    const name = document.createElement('span');
    name.className = 'split-item-name';
    name.textContent = chip.dataset.ejercicio;
    card.appendChild(name);
    return card;
}

/* ---------- SortableJS: board (días) ---------- */
function buildBoardSortable(list) {
    return Sortable.create(list, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        draggable: '.split-item-card',
        filter: 'button',
        preventOnFilter: false,
        group: { name: 'split-days', pull: true, put: true },
        onStart: function (e) {
            if (e.originalEvent && e.originalEvent.shiftKey) {
                // Shift: copiar. Se prepara el clon; el original volverá a su
                // posición y la copia ocupará el punto de suelta (onAdd/onUpdate).
                state.shiftCopies.set(e.item.dataset.splitItemId, e.item.cloneNode(true));
                e.item.classList.add('copy-mode');
            }
        },
        onAdd: function (e) {
            const targetDay = e.item.closest('.split-day-zone').dataset.day;
            const copy = state.shiftCopies.get(e.item.dataset.splitItemId);
            if (copy) {
                state.shiftCopies.delete(e.item.dataset.splitItemId);
                const original = e.item;
                original.remove();
                if (!canAdd(1)) {
                    showNotice(limitMessage(), 'error');
                    const source = e.from;
                    source.insertBefore(
                        original,
                        source.children[Math.min(e.oldIndex, source.children.length)] || null
                    );
                    clearDragVisuals();
                    updatePreview();
                    return;
                }
                finalizeCard(copy, targetDay);
                const target = e.to;
                target.insertBefore(copy, target.children[Math.min(e.newIndex, target.children.length)] || null);
                const source = e.from;
                source.insertBefore(original, source.children[Math.min(e.oldIndex, source.children.length)] || null);
            } else {
                if (!canAdd(1)) {
                    showNotice(limitMessage(), 'error');
                    e.item.remove();
                    clearDragVisuals();
                    updatePreview();
                    return;
                }
                finalizeCard(e.item, targetDay);
            }
            updatePreview();
        },
        onUpdate: function (e) {
            const copy = state.shiftCopies.get(e.item.dataset.splitItemId);
            if (copy) {
                state.shiftCopies.delete(e.item.dataset.splitItemId);
                const original = e.item;
                const list = e.from;
                const day = list.closest('.split-day-zone').dataset.day;
                original.remove();
                if (!canAdd(1)) {
                    showNotice(limitMessage(), 'error');
                    list.insertBefore(
                        original,
                        list.children[Math.min(e.oldIndex, list.children.length)] || null
                    );
                    clearDragVisuals();
                    updatePreview();
                    return;
                }
                finalizeCard(copy, day);
                list.insertBefore(copy, list.children[Math.min(e.newIndex, list.children.length)] || null);
                list.insertBefore(original, list.children[Math.min(e.oldIndex, list.children.length)] || null);
            }
            updatePreview();
        },
        onRemove: function () {
            updatePreview();
        },
        onMove: function (e) {
            const zone = e.to && e.to.closest('.split-day-zone');
            document.querySelectorAll('.split-day-zone').forEach(function (z) {
                z.classList.remove('drop-target');
            });
            if (zone) zone.classList.add('drop-target');
            return true;
        },
        onEnd: function () {
            clearDragVisuals();
            updatePreview();
        },
    });
}

function initBoardSortables() {
    state.boardSortables.forEach(function (s) { s.destroy(); });
    state.boardSortables = [];
    document.querySelectorAll('.split-day-items').forEach(function (list) {
        state.boardSortables.push(buildBoardSortable(list));
    });
}

/* ---------- SortableJS: catálogo (fuente clonable) ---------- */
function buildCatalogSortable(list) {
    return Sortable.create(list, {
        animation: 150,
        sort: false,
        group: { name: 'split-days', pull: 'clone', put: false },
        onStart: function (e) {
            // El catálogo SIEMPRE copia (pull:'clone'): indicador visual.
            e.item.classList.add('copy-mode');
        },
        onEnd: function (e) {
            e.item.classList.remove('copy-mode');
        },
    });
}

function initCatalogSortables() {
    state.catalogSortables.forEach(function (s) { s.destroy(); });
    state.catalogSortables = [];
    document.querySelectorAll('[data-catalog-list]').forEach(function (list) {
        state.catalogSortables.push(buildCatalogSortable(list));
    });
}

/* ---------- Copia de día completo (handle con Shift) ---------- */
function bindDayCopyHandles() {
    document.querySelectorAll('.split-day-copy-handle').forEach(function (handle) {
        if (handle.dataset.copyReady) return;
        handle.dataset.copyReady = '1';
        handle.addEventListener('dragstart', function (e) {
            // Sin Shift no se inicia ningún arrastre: el día nunca se mueve.
            if (!e.shiftKey) {
                e.preventDefault();
                return;
            }
            e.dataTransfer.setData('text/plain', 'daycopy:' + handle.dataset.day);
            e.dataTransfer.effectAllowed = 'copy';
            handle.classList.add('dragging-day');
        });
        handle.addEventListener('dragend', function () {
            handle.classList.remove('dragging-day');
            clearDragVisuals();
        });
    });
}

function copyDayTo(fromDay, toDay, y) {
    if (fromDay === toDay) {
        showNotice('El día destino es el mismo.', 'error');
        return;
    }
    const sourceList = dayList(fromDay);
    const targetList = dayList(toDay);
    if (!sourceList || !targetList) return;
    const cards = Array.from(sourceList.querySelectorAll('.split-item-card'));
    if (!cards.length) {
        showNotice('El día ' + dayLabel(fromDay) + ' no tiene ejercicios.', 'error');
        return;
    }
    if (!guardLimit(cards.length)) return;
    // Posición exacta de inserción según el puntero (antes del card cuya mitad
    // se supera; al final si el puntero cae debajo de todos).
    let anchor = null;
    if (y !== null && y !== undefined) {
        const targetCards = Array.from(targetList.querySelectorAll('.split-item-card'));
        for (const c of targetCards) {
            const box = c.getBoundingClientRect();
            if (y < box.top + box.height / 2) {
                anchor = c;
                break;
            }
        }
    }
    cards.forEach(function (c) {
        const copy = c.cloneNode(true);
        finalizeCard(copy, toDay);
        if (anchor) targetList.insertBefore(copy, anchor);
        else targetList.appendChild(copy);
    });
    updatePreview();
    showNotice('Día ' + dayLabel(fromDay) + ' copiado a ' + dayLabel(toDay) + '.', 'success', 2500);
}

/* ---------- Preview client-side de métricas (nunca se envía al servidor) ---------- */
function metricRow(labelText, value, suffix) {
    const p = document.createElement('p');
    p.className = 'split-metric';
    p.appendChild(document.createTextNode(labelText));
    const strong = document.createElement('strong');
    strong.textContent = String(value);
    p.appendChild(strong);
    if (suffix) p.appendChild(document.createTextNode(suffix));
    return p;
}

function tally(cards, key) {
    const counts = {};
    cards.forEach(function (c) {
        const k = c.dataset[key];
        counts[k] = (counts[k] || 0) + 1;
    });
    return counts;
}

function updatePreview() {
    if (!isSplitsPage()) return;

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

    // Resumen semanal: total + por grupo.
    const week = document.getElementById('split-metrics-week');
    if (week) {
        week.replaceChildren(metricRow('Semana — ', cards.length, ' series'));
        const groups = tally(cards, 'grupo');
        Object.keys(groups).sort().forEach(function (g) {
            week.appendChild(metricRow('· ' + g + ': ', groups[g], ' series'));
        });
    }

    // Resumen por ejercicio (totales semanales).
    const ex = document.getElementById('split-metrics-exercises');
    if (ex) {
        ex.replaceChildren();
        const byExercise = tally(cards, 'ejercicio');
        Object.keys(byExercise).sort().forEach(function (ej) {
            ex.appendChild(metricRow(ej + ': ', byExercise[ej], ' series'));
        });
    }

    // Resumen por día: los 7 días, series totales + por grupo.
    const days = document.getElementById('split-metrics-days');
    if (days) {
        days.replaceChildren();
        SPLIT_DAYS.forEach(function (day) {
            const dayCards = cards.filter(function (c) { return c.dataset.dia === day; });
            const row = metricRow(dayLabel(day) + ' — ', dayCards.length, ' series');
            const groups = tally(dayCards, 'grupo');
            Object.keys(groups).sort().forEach(function (g) {
                const span = document.createElement('span');
                span.textContent = '· ' + g + ': ' + groups[g];
                row.appendChild(span);
            });
            days.appendChild(row);
        });
    }
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

function addItemToDay(day, chip) {
    if (!guardLimit(1)) return;
    const list = dayList(day);
    if (!list) return;
    const card = finalizeCard(createCardFromChip(chip), day);
    list.appendChild(card);
    updatePreview();
}

function clearDragVisuals() {
    document.querySelectorAll('.split-day-zone').forEach(function (z) {
        z.classList.remove('drop-target');
    });
    document.querySelectorAll('.split-item-card.copy-mode').forEach(function (c) {
        c.classList.remove('copy-mode');
    });
    state.shiftCopies.clear();
}

/* ---------- Init (idempotente, contrato v3: listeners delegados) ---------- */
export function initSplits() {
    if (!isSplitsPage()) return;
    if (document.body.dataset.splitsReady) return;
    document.body.dataset.splitsReady = '1';

    const marker = readStateMarker();
    state.openSplitId = marker ? marker.splitId : null;
    state.maxItems = marker ? marker.maxItems : 300;
    if (!state.openSplitId) setFormSplitId(null);

    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        switch (el.dataset.action) {
            case 'split-day-select':
                selectDay(el.dataset.day);
                break;
            case 'split-add-item':
                if (el.closest('#splits-catalog')) addItemToDay(state.selectedDay, el);
                break;
            case 'split-item-remove':
                // Defensivo: solo instancias del board (nunca chips del catálogo).
                if (!el.closest('#splits-catalog')) {
                    el.closest('.split-item-card').remove();
                    updatePreview();
                }
                break;
            case 'split-day-copy':
                // Alternativa accesible: Shift+click copia al día seleccionado.
                if (e.shiftKey) copyDayTo(el.dataset.day, state.selectedDay, null);
                else selectDay(el.dataset.day);
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

    document.addEventListener('keydown', function (e) {
        // Alternativa accesible de teclado para los chips del catálogo
        // (role=button): Enter/Espacio disparan la misma acción que el click.
        const chip = e.target.closest && e.target.closest('[data-action="split-add-item"]');
        if (chip && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            addItemToDay(state.selectedDay, chip);
        }
    });

    document.addEventListener('input', function (e) {
        if (!e.target.closest || e.target.dataset.action !== 'split-catalog-search') return;
        const query = e.target.value.trim().toLowerCase();
        let visible = 0;
        document.querySelectorAll('#splits-catalog > details.split-catalog-group').forEach(function (group) {
            let groupVisible = false;
            group.querySelectorAll('.split-catalog-chip').forEach(function (chip) {
                const match = !query || chip.dataset.ejercicio.toLowerCase().indexOf(query) !== -1;
                chip.hidden = !match;
                if (match) groupVisible = true;
            });
            group.hidden = !groupVisible;
            group.open = groupVisible;
            if (groupVisible) visible += 1;
        });
        const empty = document.getElementById('split-catalog-empty');
        if (empty) empty.hidden = visible > 0;
        if (!query) {
            // Estado inicial: grupos visibles y cerrados.
            document.querySelectorAll('#splits-catalog > details').forEach(function (g) {
                g.hidden = false;
                g.open = false;
            });
        }
    });

    // Day-copy: el único DnD nativo restante (operación de bloque de día).
    // Los drags de ITEMS los maneja SortableJS; estos handlers solo actúan
    // cuando el payload es daycopy:...
    document.addEventListener('dragover', function (e) {
        const payload = e.dataTransfer && e.dataTransfer.getData('text/plain');
        if (!payload || payload.indexOf('daycopy:') !== 0) return;
        const zone = e.target.closest('.split-day-zone');
        if (!zone) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        zone.classList.add('drop-target');
    });

    document.addEventListener('drop', function (e) {
        const payload = e.dataTransfer && e.dataTransfer.getData('text/plain');
        if (!payload || payload.indexOf('daycopy:') !== 0) return;
        const zone = e.target.closest('.split-day-zone');
        if (!zone) return;
        e.preventDefault();
        copyDayTo(payload.slice('daycopy:'.length), zone.dataset.day, e.clientY);
    });

    // Board refrescado por OOB (guardar/abrir/eliminar/undo): re-sincronizar
    // estado, recrear Sortables y re-vincular handles del día.
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.detail && e.detail.target && e.detail.target.id === 'split-board') {
            const marker = readStateMarker();
            state.openSplitId = marker ? marker.splitId : null;
            state.maxItems = marker ? marker.maxItems : 300;
            if (!state.openSplitId) setFormSplitId(null);
            selectDay(state.selectedDay);
            initBoardSortables();
            bindDayCopyHandles();
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

    initCatalogSortables();
    initBoardSortables();
    bindDayCopyHandles();
    selectDay('LUNES');
    updatePreview();
}
