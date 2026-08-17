// splits.js — owns: gestor de splits v6. Acordeón full-width con un board por
// split y tarjetas de día de dimensiones invariantes (resumen jerárquico
// colapsable arriba + lista editable abajo; dos scrolls internos).
// REGLA CENTRAL DEL DnD: arrastre normal = MOVER; Shift + arrastre = COPIAR;
// solo el catálogo clona automáticamente.
//   - catálogo: fuente clonable (pull:'clone', forceFallback) — original queda;
//   - días: destino ordenable (pull:true = movimiento real, sin clones) con
//     forceFallback + ghost estilizado (nunca una segunda tarjeta tras el
//     cursor); la tecla Shift se excluye en fase captura → duplicación por
//     puntero propio;
//   - header del día arrastrable: bloque completo MOVE (sin Shift) o COPY
//     (con Shift); alternativa accesible: icono de copia al día seleccionado.
// DOM owned: #splits-section (.split-accordion-item), #splits-catalog.
// Public API: initSplits.
//
// Regla de negocio (espejo del servidor): 1 instancia colocada = 1 serie. El
// servidor es la única autoridad (grupo, validación, métricas, límite); la
// preview client-side se descarta en cada render OOB.
//
// Estado por item (acordeón abierto/nulo <details> convive con esto): los OOB
// de #splits-section re-renderizan TODOS los items (guardar/eliminar/undo);
// un item con cambios locales sin guardar que no sea el mutado conservaría su
// DOM. Por eso se hace snapshot del estado y del DOM de los items sucios en
// htmx:beforeRequest y se restaura tras htmx:oobAfterSwap (ver A1 del plan).
// Los items nuevos sin persistir se re-insertan al tope.

import { showNotice } from './notices.js';
import { showConfirmDialog } from './state.js';

const SPLIT_DAYS = ['LUNES', 'MARTES', 'MIERCOLES', 'JUEVES', 'VIERNES', 'SABADO', 'DOMINGO'];
const DEFAULT_MAX_ITEMS = 300;
const MUTATION_PATHS = ['/split/guardar', '/split/eliminar/', '/undo'];

// Estado del módulo (no compartido con otros módulos).
const state = {
    selectedDays: new Map(), // key (split-id o id DOM) -> día seleccionado
    activeKey: null,         // key del último item interactuado (click-add)
    items: new Map(),        // key -> { editmode, dirty }
    uidSeq: 0,
    newSeq: 0,
    boardSortables: new Map(), // key -> [Sortable]
    catalogSortables: [],
    catalogEnabled: false,
    dayDragPending: null,  // arranque del día-drag (umbral de movimiento)
    dayDrag: null,         // { key, from, mode }
    itemShiftDrag: null,     // { card }
    snapshot: new Map(),     // estado+DOM capturado en htmx:beforeRequest
    pendingMutation: null,   // { kind, splitId, wasNew }
    lastNoticeAt: 0,
};

function isSplitsPage() {
    return !!document.getElementById('splits-section');
}

function itemKey(el) {
    return el.dataset.splitId || el.id;
}

function itemElByKey(key) {
    if (!key) return null;
    return document.getElementById(key) || document.querySelector('[data-split-id="' + key + '"]');
}

function dayLabel(day) {
    return day.charAt(0) + day.slice(1).toLowerCase();
}

function sortableAvailable() {
    return typeof Sortable !== 'undefined';
}

function noticeOnce(message, kind, ms) {
    const now = Date.now();
    if (now - state.lastNoticeAt < ms) return;
    state.lastNoticeAt = now;
    showNotice(message, kind, ms);
}

function safeId(value) {
    return String(value).replace(/[^A-Za-z0-9_-]/g, '-');
}

/* ---------- Estado por item ---------- */
function ensureItemState(itemEl) {
    const key = itemKey(itemEl);
    if (!state.items.has(key)) {
        state.items.set(key, { editmode: itemEl.dataset.editmode === '0' ? '0' : '1', dirty: false });
    }
    if (!state.selectedDays.has(key)) state.selectedDays.set(key, 'LUNES');
    return key;
}

function canEdit(itemEl) {
    if (!itemEl) return false;
    const st = state.items.get(ensureItemState(itemEl));
    return !!(st && st.editmode === '1');
}

function setActive(itemEl) {
    if (!itemEl) return;
    state.activeKey = ensureItemState(itemEl);
    refreshCatalogDisabled();
}

function refreshCatalogDisabled() {
    state.catalogEnabled = !!(state.activeKey && canEdit(itemElByKey(state.activeKey)));
    state.catalogSortables.forEach(function (s) { s.option('disabled', !state.catalogEnabled); });
}

function countCards(itemEl) {
    return itemEl.querySelectorAll('.split-item-card').length;
}

function itemLimit(itemEl) {
    return parseInt(itemEl.dataset.maxItems, 10) || DEFAULT_MAX_ITEMS;
}

function canAdd(itemEl, extra) {
    return countCards(itemEl) + extra <= itemLimit(itemEl);
}

function guardLimit(itemEl, extra) {
    if (canAdd(itemEl, extra)) return true;
    showNotice('No se puede: superaría el límite de ' + itemLimit(itemEl) + ' instancias del split.', 'error');
    return false;
}

function limitMessage(itemEl) {
    return 'No se puede: superaría el límite de ' + itemLimit(itemEl) + ' instancias del split.';
}

function zoneEls(itemEl) {
    return itemEl.querySelectorAll('.split-day-zone');
}

function zoneEl(itemEl, day) {
    return itemEl.querySelector('.split-day-zone[data-day="' + day + '"]');
}

function dayList(itemEl, day) {
    const zone = zoneEl(itemEl, day);
    return zone && zone.querySelector('.split-day-items');
}

function selectDay(itemEl, day) {
    const key = itemKey(itemEl);
    state.selectedDays.set(key, day);
    itemEl.querySelectorAll('.split-day-select').forEach(function (btn) {
        btn.setAttribute('aria-pressed', String(btn.dataset.day === day));
    });
}

function selectedDayOf(itemEl) {
    return state.selectedDays.get(itemKey(itemEl)) || 'LUNES';
}

/* ---------- Modo edición por item y dirty tracking ---------- */
function applyEditMode(itemEl) {
    const key = ensureItemState(itemEl);
    const st = state.items.get(key);
    const editmode = st.editmode;
    itemEl.dataset.editmode = editmode;
    const hint = itemEl.querySelector('[data-split-dirty-hint]');
    if (hint) hint.hidden = !st.dirty;
    const editBtn = itemEl.querySelector('[data-action="split-edit"]');
    if (editBtn) {
        editBtn.setAttribute('aria-pressed', String(editmode === '1'));
        // Modo edición visible sin texto: el lápiz se ilumina (is-active).
        editBtn.classList.toggle('is-active', editmode === '1');
    }
    // Guardar habilitado solo con cambios locales (o item nuevo sin persistir);
    // deshabilitado ocupa el mismo espacio (sin salto de layout).
    const saveBtn = itemEl.querySelector('[data-action="split-save"]');
    if (saveBtn) saveBtn.disabled = !(st.dirty || !itemEl.dataset.splitId);
    const sortables = state.boardSortables.get(key) || [];
    sortables.forEach(function (s) { s.option('disabled', editmode !== '1'); });
    // Las tarjetas nunca son draggable nativo: con forceFallback el drag lo
    // maneja Sortable por mousedown (si draggable=true, el browser secuestra
    // el arrastre con DnD nativo y el fallback queda en 'chosen' sin arrancar).
    itemEl.querySelectorAll('.split-item-card').forEach(function (card) {
        card.draggable = false;
    });
    refreshCatalogDisabled();
    updatePreview(itemEl);
}

function setEditMode(itemEl, on) {
    const key = ensureItemState(itemEl);
    state.items.get(key).editmode = on ? '1' : '0';
    setActive(itemEl);
    applyEditMode(itemEl);
    if (on) {
        itemEl.scrollIntoView({ block: 'nearest' });
        showNotice('Modo edición activado.', 'success', 2000);
    }
}

function markDirty(itemEl) {
    const key = ensureItemState(itemEl);
    const st = state.items.get(key);
    if (st.editmode !== '1') return;
    st.dirty = true;
    applyEditMode(itemEl);
}

/* ---------- Tarjetas ---------- */
function finalizeCard(card, day) {
    state.uidSeq += 1;
    card.dataset.splitItemId = 'ui-' + state.uidSeq;
    card.dataset.dia = day;
    // forceFallback usa mousedown; draggable=true haría que el drag nativo
    // HTML5 secuestre el fallback.
    card.draggable = false;
    card.classList.remove('split-catalog-chip');
    card.removeAttribute('role');
    card.removeAttribute('tabindex');
    card.removeAttribute('data-action');
    if (!card.querySelector('[data-action="split-item-remove"]')) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'split-item-remove';
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
function paintDropTarget(zone) {
    document.querySelectorAll('.split-day-zone').forEach(function (z) { z.classList.remove('drop-target'); });
    if (zone) {
        const item = zone.closest('.split-accordion-item');
        if (item && canEdit(item)) zone.classList.add('drop-target');
    }
}

function buildBoardSortable(list, itemEl) {
    return Sortable.create(list, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        fallbackClass: 'split-fallback',
        forceFallback: true,
        fallbackOnBody: true,
        // El drag con Shift lo gestiona nuestro drag por puntero (duplicación):
        // la función filter impide que Sortable se inicie con Shift (la tecla
        // decide el modo desde el inicio) y que los botones inicien el drag.
        filter: function (e, target) { return e.shiftKey || target.tagName === 'BUTTON'; },
        preventOnFilter: false,
        disabled: !canEdit(itemEl),
        group: { name: 'split-days', pull: true, put: true },
        onMove: function (e) {
            // A3: nunca dejar soltar dentro de un split en visualización.
            const toItem = e.to && e.to.closest('.split-accordion-item');
            if (!toItem || !canEdit(toItem)) return false;
            const zone = e.to && e.to.closest('.split-day-zone');
            paintDropTarget(zone);
            return true;
        },
        onAdd: function (e) {
            if (!canEdit(itemEl)) { e.item.remove(); clearDragVisuals(); updatePreview(itemEl); return; }
            const targetDay = e.item.closest('.split-day-zone').dataset.day;
            if (!guardLimit(itemEl, 1)) { e.item.remove(); clearDragVisuals(); updatePreview(itemEl); return; }
            finalizeCard(e.item, targetDay);
            updatePreview(itemEl);
            markDirty(itemEl);
        },
        onUpdate: function () { updatePreview(itemEl); markDirty(itemEl); },
        onRemove: function () { updatePreview(itemEl); markDirty(itemEl); },
        onEnd: function () { clearDragVisuals(); updatePreview(itemEl); },
    });
}

function initItemSortables(itemEl) {
    const key = itemKey(itemEl);
    const old = state.boardSortables.get(key) || [];
    old.forEach(function (s) { s.destroy(); });
    const arr = [];
    if (sortableAvailable()) {
        itemEl.querySelectorAll('.split-day-items').forEach(function (list) {
            arr.push(buildBoardSortable(list, itemEl));
        });
    } else {
        console.warn('splits: SortableJS no disponible; drag de días desactivado.');
    }
    state.boardSortables.set(key, arr);
    bindDropGuards(itemEl);
}

/* A3 — defensa doble contra drops nativos en boards no editables: Sortable
   deshabilitado no impide la inserción HTML5 nativa (dragover/drop) cuando el
   arrastre proviene de otro board editable. Se bloquea POR ELEMENTO (no a
   nivel document, para no crear DnD nativo paralelo) sobre toda la tarjeta
   (zona + lista, los eventos burbujean hasta la zona) y SOLO cuando el item
   no está en modo edición. */
function bindDropGuards(itemEl) {
    itemEl.querySelectorAll('.split-day-zone').forEach(function (zone) {
        if (zone.dataset.dropGuard) return;
        zone.dataset.dropGuard = '1';
        zone.addEventListener('dragover', function (e) {
            const item = zone.closest('.split-accordion-item');
            if (!item || !canEdit(item)) e.preventDefault();
        });
        zone.addEventListener('drop', function (e) {
            const item = zone.closest('.split-accordion-item');
            if (!item || !canEdit(item)) e.preventDefault();
        });
    });
}

/* ---------- SortableJS: catálogo (fuente clonable) ---------- */
function buildCatalogSortable(list) {
    return Sortable.create(list, {
        animation: 150,
        sort: false,
        disabled: true,
        fallbackClass: 'split-fallback',
        forceFallback: true,
        fallbackOnBody: true,
        removeCloneOnHide: true,
        revertClone: true,
        group: { name: 'split-days', pull: 'clone', put: false },
        onStart: function (e) { e.item.classList.add('copy-mode'); },
        onEnd: function (e) { e.item.classList.remove('copy-mode'); },
    });
}

function initCatalogSortables() {
    state.catalogSortables.forEach(function (s) { s.destroy(); });
    state.catalogSortables = [];
    if (!sortableAvailable()) {
        console.warn('splits: SortableJS no disponible; catálogo sin arrastre.');
        return;
    }
    document.querySelectorAll('[data-catalog-list]').forEach(function (list) {
        state.catalogSortables.push(buildCatalogSortable(list));
    });
}

/* ---------- Duplicación de instancia con Shift (drag por puntero) ----------
Chromium no inicia el drag de Sortable con Shift: el modo Shift de items usa un
drag propio por puntero (mousedown+Shift → seguimiento → drop por Y). En
navegadores reales Sortable neutraliza su propio drag vía onMove(shiftKey)=false. */
function onItemShiftDown(e) {
    if (!e.shiftKey) return;
    const card = e.target.closest('.split-item-card');
    if (!card || card.closest('#splits-catalog')) return;
    const item = card.closest('.split-accordion-item');
    if (!item || !canEdit(item)) return;
    e.preventDefault();
    const list = card.parentElement;
    if (!list || !list.closest('.split-day-zone')) return;
    state.itemShiftDrag = { card: card };
    card.classList.add('copy-mode');
    document.addEventListener('mousemove', onItemShiftMove, true);
    document.addEventListener('mouseup', onItemShiftUp, true);
}

function onItemShiftMove(e) {
    if (!state.itemShiftDrag) return;
    paintDropTarget(e.target.closest('.split-day-zone'));
}

function onItemShiftUp(e) {
    if (!state.itemShiftDrag) return;
    const card = state.itemShiftDrag.card;
    state.itemShiftDrag = null;
    card.classList.remove('copy-mode');
    document.removeEventListener('mousemove', onItemShiftMove, true);
    document.removeEventListener('mouseup', onItemShiftUp, true);
    clearDragVisuals();
    const zone = e.target.closest('.split-day-zone');
    if (!zone) return;
    const toItem = zone.closest('.split-accordion-item');
    if (!toItem || !canEdit(toItem)) return;
    const targetList = zone.querySelector('.split-day-items');
    if (!targetList) return;
    if (!guardLimit(toItem, 1)) return;
    const targetDay = zone.dataset.day;
    const copy = card.cloneNode(true);
    finalizeCard(copy, targetDay);
    let anchor = null;
    const targetCards = Array.from(targetList.querySelectorAll('.split-item-card'));
    for (const c of targetCards) {
        const box = c.getBoundingClientRect();
        if (e.clientY < box.top + box.height / 2) { anchor = c; break; }
    }
    if (anchor) targetList.insertBefore(copy, anchor);
    else targetList.appendChild(copy);
    updatePreview(toItem);
    markDirty(toItem);
}

/* ---------- Mover/copiar un día completo desde el header ----------
Todo el header del día (nombre + series + área libre) es el área de arrastre:
sin Shift MUEVE el bloque completo, con Shift LO COPIA (drag por puntero
propio, igual que la duplicación de items). Reglas:
  - el mousedown de INICIO excluye los botones del header (day-select sigue
    siendo clicable y no inicia el drag);
  - en el mouseup la zona destino se resuelve con closest('.split-day-zone')
    (el botón de selección está DENTRO de la zona);
  - límite: copiar valida `guardLimit` ANTES de tocar el DOM (rechazo → origen
    intacto); mover no cambia el total del split, así que el límite se cumple
    por invariante;
  - inserción: por mitad de tarjeta destino si el puntero cae sobre la lista,
    al final si cae sobre el header del día destino;
  - mover re-parenta las tarjetas (sin cloneNode); copiar usa cloneNode. */
function onDayHeaderDown(e) {
    const header = e.target.closest('.split-day-header');
    if (!header) return;
    const item = header.closest('.split-accordion-item');
    if (!item || !canEdit(item)) return;
    const day = header.closest('.split-day-zone').dataset.day;
    const sourceList = dayList(item, day);
    if (!sourceList || !sourceList.querySelectorAll('.split-item-card').length) {
        showNotice('El día ' + dayLabel(day) + ' no tiene ejercicios.', 'error');
        return;
    }
    // No se excluye el day-select del inicio: el umbral de movimiento distingue
    // clic (selecciona el día) de arrastre (mueve/copia el bloque).
    state.dayDragPending = {
        x: e.clientX,
        y: e.clientY,
        key: itemKey(item),
        from: day,
        mode: e.shiftKey ? 'copy' : 'move',
        header: header,
    };
}

function onDayHeaderMove(e) {
    const pending = state.dayDragPending;
    if (pending && !state.dayDrag) {
        if (Math.abs(e.clientX - pending.x) + Math.abs(e.clientY - pending.y) > 5) {
            e.preventDefault();
            state.dayDrag = { key: pending.key, from: pending.from, mode: pending.mode };
            pending.header.classList.add('dragging-day');
            state.dayDragPending = null;
        }
    }
    if (!state.dayDrag) return;
    const zones = zoneEls(itemElByKey(state.dayDrag.key));
    zones.forEach(function (z) { z.classList.remove('drop-target'); });
    const zone = e.target.closest('.split-day-zone');
    if (zone && Array.prototype.indexOf.call(zones, zone) !== -1 && zone.dataset.day !== state.dayDrag.from) {
        zone.classList.add('drop-target');
    }
}

function onDayHeaderUp(e) {
    state.dayDragPending = null;
    if (!state.dayDrag) return;
    const { key, from, mode } = state.dayDrag;
    state.dayDrag = null;
    itemElByKey(key).querySelectorAll('.split-day-header.dragging-day').forEach(function (h) {
        h.classList.remove('dragging-day');
    });
    const zones = zoneEls(itemElByKey(key));
    zones.forEach(function (z) { z.classList.remove('drop-target'); });
    const zone = e.target.closest('.split-day-zone');
    if (!zone || Array.prototype.indexOf.call(zones, zone) === -1 || zone.dataset.day === from) return;
    const onHeader = !!e.target.closest('.split-day-header');
    applyDayBlock(key, from, zone, mode, onHeader, e.clientY);
}

function dayInsertionAnchor(targetList, y) {
    const targetCards = Array.from(targetList.querySelectorAll('.split-item-card'));
    for (const c of targetCards) {
        const box = c.getBoundingClientRect();
        if (y < box.top + box.height / 2) return c;
    }
    return null;
}

function applyDayBlock(key, fromDay, destZone, mode, onHeader, y) {
    const item = itemElByKey(key);
    if (!item || !canEdit(item)) return;
    const toDay = destZone.dataset.day;
    if (fromDay === toDay) {
        showNotice('El día destino es el mismo.', 'error');
        return;
    }
    const sourceList = dayList(item, fromDay);
    const targetList = destZone.querySelector('.split-day-items');
    if (!sourceList || !targetList) return;
    const cards = Array.from(sourceList.querySelectorAll('.split-item-card'));
    if (!cards.length) {
        showNotice('El día ' + dayLabel(fromDay) + ' no tiene ejercicios.', 'error');
        return;
    }
    // Insertar el bloque: al final si cae sobre el header destino o sobre la
    // zona vacía; si no, en la posición exacta del puntero (mitad de tarjeta).
    const anchor = onHeader || y === null || y === undefined ? null : dayInsertionAnchor(targetList, y);
    if (mode === 'move') {
        // Mover: el total del split no cambia (límite por invariante); el
        // bloque se re-parenta en orden (insertBefore secuencial preserva el
        // orden relativo) y las tarjetas pasan al día destino.
        insertCardsAt(targetList, cards, anchor);
        cards.forEach(function (c) { c.dataset.dia = toDay; });
    } else {
        if (!guardLimit(item, cards.length)) return; // rechazo → origen intacto
        const copies = cards.map(function (c) { return finalizeCard(c.cloneNode(true), toDay); });
        insertCardsAt(targetList, copies, anchor);
        showNotice('Día ' + dayLabel(fromDay) + ' copiado a ' + dayLabel(toDay) + '.', 'success', 2500);
    }
    updatePreview(item);
    markDirty(item);
}

function insertCardsAt(targetList, cards, anchor) {
    cards.forEach(function (card) {
        if (anchor) targetList.insertBefore(card, anchor);
        else targetList.appendChild(card);
    });
}

/* ---------- Preview client-side de métricas (nunca se envía al servidor) ---------- */
function tally(cards, key) {
    const counts = {};
    cards.forEach(function (c) { counts[c.dataset[key]] = (counts[c.dataset[key]] || 0) + 1; });
    return counts;
}

function rebuildDaySummary(itemEl, day, cards, key) {
    const summary = itemEl.querySelector('[data-day-summary="' + day + '"]');
    if (!summary) return;
    const expanded = new Set();
    summary.querySelectorAll('.split-summary-group-toggle[aria-expanded="true"]').forEach(function (b) {
        if (b.dataset.summaryGroup) expanded.add(b.dataset.summaryGroup);
    });
    summary.replaceChildren();
    const groups = tally(cards, 'grupo');
    Object.keys(groups).sort().forEach(function (grp) {
        const groupEl = document.createElement('div');
        groupEl.className = 'split-summary-group';
        groupEl.dataset.summaryGroup = grp;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'split-summary-group-toggle';
        btn.dataset.action = 'split-summary-toggle';
        btn.dataset.summaryGroup = grp;
        const isOpen = expanded.has(grp);
        btn.setAttribute('aria-expanded', String(isOpen));
        const chev = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        chev.setAttribute('width', '10');
        chev.setAttribute('height', '10');
        chev.setAttribute('viewBox', '0 0 24 24');
        chev.setAttribute('fill', 'none');
        chev.setAttribute('stroke', 'currentColor');
        chev.setAttribute('stroke-width', '2');
        chev.setAttribute('stroke-linecap', 'round');
        chev.setAttribute('stroke-linejoin', 'round');
        chev.setAttribute('aria-hidden', 'true');
        chev.classList.add('split-summary-chevron');
        const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        poly.setAttribute('points', '9 18 15 12 9 6');
        chev.appendChild(poly);
        const name = document.createElement('span');
        name.className = 'split-summary-name';
        name.textContent = grp;
        const tot = document.createElement('span');
        tot.className = 'split-summary-total';
        tot.textContent = groups[grp] + ' series';
        btn.appendChild(chev);
        btn.appendChild(name);
        btn.appendChild(tot);
        groupEl.appendChild(btn);
        const body = document.createElement('div');
        body.className = 'split-summary-group-body';
        const bodyId = 'sg-' + safeId(key) + '-' + safeId(day) + '-' + safeId(grp);
        body.id = bodyId;
        btn.setAttribute('aria-controls', bodyId);
        if (!isOpen) body.hidden = true;
        const byEx = {};
        cards.forEach(function (c) {
            if (c.dataset.grupo === grp) byEx[c.dataset.ejercicio] = (byEx[c.dataset.ejercicio] || 0) + 1;
        });
        Object.keys(byEx).sort().forEach(function (ej) {
            const row = document.createElement('div');
            row.className = 'split-summary-row split-summary-exercise';
            const n = document.createElement('span');
            n.className = 'split-summary-name';
            n.textContent = ej;
            const t = document.createElement('span');
            t.className = 'split-summary-total';
            t.textContent = byEx[ej] + ' series';
            row.appendChild(n);
            row.appendChild(t);
            body.appendChild(row);
        });
        groupEl.appendChild(body);
        summary.appendChild(groupEl);
    });
}

function updatePreview(itemEl) {
    if (!itemEl) return;
    const key = itemKey(itemEl);
    let itemTotal = 0;
    zoneEls(itemEl).forEach(function (zone) {
        const day = zone.dataset.day;
        const cards = zone.querySelectorAll('.split-item-card');
        const count = cards.length;
        itemTotal += count;
        const countEl = zone.querySelector('.split-day-count');
        if (countEl) countEl.textContent = count + ' serie' + (count === 1 ? '' : 's');
        const empty = zone.querySelector('.split-empty');
        if (empty) empty.hidden = count > 0;
        rebuildDaySummary(itemEl, day, cards, key);
    });
    rebuildStrip(itemEl, itemTotal);
}

/* Resumen semanal de la cabecera (junto al nombre): total + grupos ordenados
   por series desc (empate por nombre), mismo formato que el servidor. */
function rebuildStrip(itemEl, total) {
    const strip = itemEl.querySelector('.split-summary-strip');
    if (!strip) return;
    const cards = itemEl.querySelectorAll('.split-item-card');
    const groups = tally(cards, 'grupo');
    strip.replaceChildren();
    const t = document.createElement('strong');
    t.textContent = total;
    strip.appendChild(t);
    strip.appendChild(document.createTextNode(' series'));
    Object.keys(groups)
        .sort(function (a, b) { return groups[b] - groups[a] || a.localeCompare(b); })
        .forEach(function (g) {
            const sep = document.createElement('span');
            sep.className = 'split-summary-strip-sep';
            sep.textContent = '·';
            const name = document.createElement('span');
            name.textContent = ' ' + g + ' ';
            const n = document.createElement('strong');
            n.textContent = groups[g];
            strip.appendChild(sep);
            strip.appendChild(name);
            strip.appendChild(n);
        });
}

/* ---------- Sincronización del formulario (arrays alineados, orden visual) ---------- */
function syncSplitForm(itemEl) {
    const form = itemEl.querySelector('form.split-item-form');
    if (!form) return;
    form.querySelectorAll('input[name="dia"], input[name="item_type"], input[name="ejercicio"]')
        .forEach(function (el) { el.remove(); });
    zoneEls(itemEl).forEach(function (zone) {
        zone.querySelectorAll('.split-item-card').forEach(function (card) {
            ['dia', 'item_type', 'ejercicio'].forEach(function (name) {
                const inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = name;
                inp.value = name === 'dia' ? zone.dataset.day
                    : name === 'item_type' ? card.dataset.itemType
                        : card.dataset.ejercicio;
                form.appendChild(inp);
            });
        });
    });
}

/* ---------- Acciones delegadas (data-action) ---------- */
function splitSave(itemEl) {
    const form = itemEl.querySelector('form.split-item-form');
    if (!form) return;
    const nombre = form.querySelector('input[name="nombre"]');
    if (!nombre || !nombre.value.trim()) {
        if (nombre) nombre.focus();
        showNotice('Ponle nombre al split antes de guardar.', 'error');
        return;
    }
    syncSplitForm(itemEl);
    form.requestSubmit();
}

function splitNew() {
    htmx.ajax('GET', '/split/nuevo', { target: 'body', swap: 'none' });
}

function insertNewItem(html) {
    const section = document.getElementById('splits-section');
    if (!section) return;
    let list = section.querySelector('#splits-list');
    if (!list) {
        list = document.createElement('div');
        list.id = 'splits-list';
        list.className = 'flex flex-col gap-4';
        section.replaceChildren(list);
    }
    const wrap = document.createElement('div');
    wrap.innerHTML = html;
    const node = wrap.firstElementChild;
    state.newSeq += 1;
    node.id = 'split-item-nuevo-' + state.newSeq;
    list.insertBefore(node, list.firstChild);
    processHtmx(node);
    ensureItemState(node);
    selectDay(node, 'LUNES');
    setActive(node);
    initItemSortables(node);
    applyEditMode(node);
    refreshCatalogDisabled();
    const details = node.querySelector('details.split-accordion');
    if (details && !details.open) details.open = true;
    const nombre = node.querySelector('input[name="nombre"]');
    if (nombre) nombre.focus();
    showNotice('Nuevo split: arma la semana desde el catálogo.', 'success', 3000);
}

function splitDelete(itemEl) {
    const sid = itemEl.dataset.splitId;
    if (!sid) return;
    const nombre = itemEl.dataset.splitNombre || '';
    document.getElementById('confirm-msg').textContent = '¿Eliminar el split "' + nombre + '"?';
    showConfirmDialog(function () {
        htmx.ajax('POST', '/split/eliminar/' + sid, { target: 'body', swap: 'none' });
    }, null);
}

function splitDayClear(itemEl, day) {
    if (!canEdit(itemEl)) return;
    const list = dayList(itemEl, day);
    if (!list) return;
    const cards = list.querySelectorAll('.split-item-card');
    if (!cards.length) return;
    document.getElementById('confirm-msg').textContent =
        '¿Borrar todos los ejercicios del ' + dayLabel(day) + '?';
    showConfirmDialog(function () {
        cards.forEach(function (c) { c.remove(); });
        updatePreview(itemEl);
        markDirty(itemEl);
    }, null);
}

function addItemToDay(itemEl, day, chip) {
    if (!canEdit(itemEl)) return;
    if (!guardLimit(itemEl, 1)) return;
    const list = dayList(itemEl, day);
    if (!list) return;
    const card = finalizeCard(createCardFromChip(chip), day);
    list.appendChild(card);
    updatePreview(itemEl);
    markDirty(itemEl);
}

function toggleSummaryGroup(btn) {
    const expanded = btn.getAttribute('aria-expanded') === 'true';
    const body = btn.getAttribute('aria-controls') ? document.getElementById(btn.getAttribute('aria-controls')) : null;
    btn.setAttribute('aria-expanded', String(!expanded));
    if (body) body.hidden = expanded;
}

function clearDragVisuals() {
    document.querySelectorAll('.split-day-zone').forEach(function (z) { z.classList.remove('drop-target'); });
    document.querySelectorAll('.split-item-card.copy-mode').forEach(function (c) { c.classList.remove('copy-mode'); });
    document.querySelectorAll('.split-day-header.dragging-day').forEach(function (h) { h.classList.remove('dragging-day'); });
}

/* El DOM insertado por JS (no vía swap htmx) no se procesa solo: hay que
   llamar a htmx.process para enlazar los hx-* del item (p. ej. hx-post del
   formulario de guardado). Sin esto, requestSubmit haría un GET nativo. */
function processHtmx(node) {
    if (typeof window.htmx !== 'undefined' && typeof htmx.process === 'function') {
        htmx.process(node);
    }
}

function chipNeedEditNotice() {
    noticeOnce('Pulsa Editar en un split para poder añadir ejercicios.', 'error', 2500);
}

/* ---------- Snapshot / restore tras OOB de #splits-section ---------- */
function requestPath(e) {
    return (e.detail && e.detail.requestConfig && e.detail.requestConfig.path) || '';
}

function snapshotBeforeMutation(e) {
    const path = requestPath(e);
    if (MUTATION_PATHS.indexOf(path) === -1 && path.indexOf('/split/eliminar/') === -1) return;
    const req = e.detail.requestConfig || {};
    let splitId = null;
    let wasNew = false;
    if (path === '/split/guardar') {
        const form = req.elt && req.elt.tagName === 'FORM' ? req.elt : req.elt && req.elt.closest ? req.elt.closest('form') : null;
        const hid = form && form.querySelector('input[name="split_id"]');
        wasNew = !(hid && hid.value);
        splitId = hid && hid.value ? hid.value : null;
    }
    state.pendingMutation = {
        kind: path === '/undo' ? 'undo' : path.indexOf('/split/eliminar/') !== -1 ? 'delete' : 'save',
        splitId: splitId,
        wasNew: wasNew,
    };
    state.snapshot.clear();
    document.querySelectorAll('#splits-section .split-accordion-item').forEach(function (itemEl) {
        const key = itemKey(itemEl);
        const st = state.items.get(key) || ensureItemState(itemEl);
        const openEl = itemEl.querySelector('details.split-accordion');
        const snap = {
            key: key,
            isNew: !itemEl.dataset.splitId,
            open: !!(openEl && openEl.open),
            editmode: st.editmode,
            dirty: !!st.dirty,
            selectedDay: state.selectedDays.get(key) || 'LUNES',
            nombre: (itemEl.querySelector('input[name="nombre"]') || {}).value || '',
        };
        if (snap.dirty || snap.isNew) snap.html = itemEl.outerHTML;
        state.snapshot.set(key, snap);
    });
}

function applyStateToElement(el, snap) {
    const key = itemKey(el);
    state.items.set(key, { editmode: snap.editmode, dirty: snap.dirty });
    const openEl = el.querySelector('details.split-accordion');
    if (openEl) openEl.open = snap.open;
    const nombre = el.querySelector('input[name="nombre"]');
    if (nombre && (snap.dirty || snap.isNew)) nombre.value = snap.nombre;
    state.selectedDays.set(key, snap.selectedDay);
    selectDay(el, snap.selectedDay);
    applyEditMode(el);
}

function restoreAfterSectionSwap(e) {
    if (!(e.detail && e.detail.target && e.detail.target.id === 'splits-section')) return;
    const pm = state.pendingMutation;
    const saveTarget = pm && pm.kind === 'save' ? pm.splitId : null;
    const newItemSaved = !!(pm && pm.kind === 'save' && pm.wasNew);
    // 1) restaurar el DOM de los items sucios/nuevos (salvo el recién guardado).
    state.snapshot.forEach(function (snap) {
        if (snap.isNew && newItemSaved) return;
        if (!snap.html) return;
        const el = itemElByKey(snap.key);
        if (!el || (saveTarget !== null && snap.key === saveTarget)) return;
        const wrap = document.createElement('div');
        wrap.innerHTML = snap.html;
        const node = wrap.firstElementChild;
        el.replaceWith(node);
        processHtmx(node);
        applyStateToElement(node, snap);
    });
    // 2) restaurar estado del resto: el guardado vuelve a modo vista manteniendo
    // la expansión; los sucios (no guardados) conservan su edición; los limpios
    // conservan estado visual; los nuevos sin persistir se re-insertan al tope.
    state.snapshot.forEach(function (snap) {
        const el = itemElByKey(snap.key);
        const isSaved = saveTarget !== null && snap.key === saveTarget;
        if (el && isSaved) {
            const openEl = el.querySelector('details.split-accordion');
            if (openEl) openEl.open = snap.open;
            state.items.set(snap.key, { editmode: '0', dirty: false });
            state.selectedDays.set(snap.key, snap.selectedDay);
            selectDay(el, snap.selectedDay);
            applyEditMode(el);
        } else if (el) {
            const st = state.items.get(snap.key);
            if (st && st.dirty) {
                applyStateToElement(el, snap);
            } else {
                const openEl = el.querySelector('details.split-accordion');
                if (openEl) openEl.open = snap.open;
                state.selectedDays.set(snap.key, snap.selectedDay);
                selectDay(el, snap.selectedDay);
                applyEditMode(el);
            }
        } else if (snap.isNew && !newItemSaved && snap.html) {
            const section = document.getElementById('splits-section');
            if (!section) return;
            let list = section.querySelector('#splits-list');
            if (!list) {
                list = document.createElement('div');
                list.id = 'splits-list';
                list.className = 'flex flex-col gap-4';
                section.replaceChildren(list);
            }
            const wrap = document.createElement('div');
            wrap.innerHTML = snap.html;
            const node = wrap.firstElementChild;
            list.insertBefore(node, list.firstChild);
            processHtmx(node);
            applyStateToElement(node, snap);
        }
    });
    reconcileState();
    reinitAll();
    state.pendingMutation = null;
}

function reconcileState() {
    const present = new Set();
    document.querySelectorAll('#splits-section .split-accordion-item').forEach(function (el) {
        present.add(itemKey(el));
    });
    Array.from(state.items.keys()).forEach(function (k) { if (!present.has(k)) state.items.delete(k); });
    Array.from(state.selectedDays.keys()).forEach(function (k) { if (!present.has(k)) state.selectedDays.delete(k); });
    Array.from(state.boardSortables.keys()).forEach(function (k) { if (!present.has(k)) state.boardSortables.delete(k); });
    if (state.activeKey && !present.has(state.activeKey)) state.activeKey = null;
}

function reinitAll() {
    document.querySelectorAll('#splits-section .split-accordion-item').forEach(function (itemEl) {
        initItemSortables(itemEl);
        applyEditMode(itemEl);
    });
    refreshCatalogDisabled();
}

/* ---------- Init (idempotente, contrato v3: listeners delegados) ---------- */
export function initSplits() {
    if (!isSplitsPage()) return;
    if (document.body.dataset.splitsReady) return;
    document.body.dataset.splitsReady = '1';

    document.querySelectorAll('#splits-section .split-accordion-item').forEach(function (itemEl) {
        ensureItemState(itemEl);
        selectDay(itemEl, 'LUNES');
    });
    if (!state.activeKey && state.items.size) state.activeKey = Array.from(state.items.keys())[0];

    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        const itemEl = el.closest('.split-accordion-item');
        switch (el.dataset.action) {
            case 'split-new':
                splitNew();
                break;
            case 'split-summary-toggle':
                toggleSummaryGroup(el);
                break;
            case 'split-day-select':
                if (itemEl) { setActive(itemEl); selectDay(itemEl, el.dataset.day); }
                break;
            case 'split-add-item':
                if (el.closest('#splits-catalog')) {
                    const target = itemElByKey(state.activeKey);
                    if (!target || !canEdit(target)) { chipNeedEditNotice(); return; }
                    addItemToDay(target, selectedDayOf(target), el);
                }
                break;
            case 'split-item-remove':
                if (itemEl && canEdit(itemEl)) {
                    el.closest('.split-item-card').remove();
                    updatePreview(itemEl);
                    markDirty(itemEl);
                }
                break;
            case 'split-day-clear':
                if (itemEl) splitDayClear(itemEl, el.dataset.day);
                break;
            case 'split-day-copy':
                // Alternativa accesible al header-drag: copia el día al día
                // seleccionado (append). 
                if (!itemEl) return;
                setActive(itemEl);
                applyDayBlock(
                    itemKey(itemEl),
                    el.dataset.day,
                    zoneEl(itemEl, selectedDayOf(itemEl)),
                    'copy',
                    false,
                    null
                );
                break;
            case 'split-edit':
                if (itemEl) {
                    setActive(itemEl);
                    const key = itemKey(itemEl);
                    const st = state.items.get(key);
                    if (st) setEditMode(itemEl, st.editmode === '0');
                }
                break;
            case 'split-save':
                if (itemEl) splitSave(itemEl);
                break;
            case 'split-delete':
                if (itemEl) splitDelete(itemEl);
                break;
        }
    });

    document.addEventListener('keydown', function (e) {
        const chip = e.target.closest && e.target.closest('[data-action="split-add-item"]');
        if (chip && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            const target = itemElByKey(state.activeKey);
            if (!target || !canEdit(target)) { chipNeedEditNotice(); return; }
            addItemToDay(target, selectedDayOf(target), chip);
        }
    });

    // Teclear el nombre marca el split como modificado (habilita Guardar;
    // también cubre el alta de un split nuevo).
    document.addEventListener('input', function (e) {
        const item = e.target.closest && e.target.closest('.split-accordion-item');
        if (item && e.target.matches('input[name="nombre"]')) markDirty(item);
    });

    // Búsqueda en el catálogo: abre los grupos con resultados, oculta el resto
    // y restaura el estado cerrado al vaciar.
    document.addEventListener('input', function (e) {
        if (!e.target.closest || !e.target.matches('#split-catalog-search')) return;
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
            document.querySelectorAll('#splits-catalog > details').forEach(function (g) {
                g.hidden = false;
                g.open = false;
            });
        }
    });

    document.addEventListener('pointerdown', function (e) {
        const item = e.target.closest('.split-accordion-item');
        if (item) setActive(item);
    }, true);

    // Feedback al intentar arrastrar/agregar sin un split editable activo.
    document.addEventListener('mousedown', function (e) {
        if (e.target.closest('#splits-catalog')) {
            const active = itemElByKey(state.activeKey);
            if (!active || !canEdit(active)) chipNeedEditNotice();
        }
    });

    // Mover/copiar día completo desde el header: drag por puntero propio.
    document.addEventListener('mousedown', onDayHeaderDown);
    document.addEventListener('mousemove', onDayHeaderMove);
    document.addEventListener('mouseup', onDayHeaderUp);
    // Duplicación de instancia con Shift (drag por puntero propio). En fase
    // CAPTURA para que el preventDefault corra ANTES del fallback de Sortable:
    // así la tecla Shift decide el modo de operación desde el inicio del
    // arrastre y nunca coexisten movimiento normal y duplicación.
    document.addEventListener('mousedown', onItemShiftDown, true);

    // A1/B1: snapshot del estado/DOM antes de cada mutación que re-renderiza
    // #splits-section; restore tras su swap OOB.
    document.body.addEventListener('htmx:beforeRequest', snapshotBeforeMutation);
    document.body.addEventListener('htmx:oobAfterSwap', restoreAfterSectionSwap);

    document.body.addEventListener('htmx:afterRequest', function (e) {
        const path = requestPath(e);
        if (path === '/split/nuevo') {
            const html = e.detail.xhr && e.detail.xhr.responseText;
            if (html) insertNewItem(html);
        }
        if (!e.detail.successful && (MUTATION_PATHS.indexOf(path) !== -1 || path.indexOf('/split/eliminar/') !== -1)) {
            state.pendingMutation = null;
        }
    });

    safeInitCatalog();
    try {
        reinitAll();
    } catch (err) {
        console.error('splits: init de boards/handles falló', err);
    }
    // CDN lento: Sortable puede llegar tras DOMContentLoaded; reintentar en load.
    if (!sortableAvailable()) {
        noticeOnce('El arrastre no está disponible; agrega ejercicios con clic.', 'error', 0);
        window.addEventListener('load', function () {
            safeInitCatalog();
            try {
                reinitAll();
            } catch (err) {
                console.error('splits: init de boards/handles falló (retry)', err);
            }
            refreshCatalogDisabled();
        });
    }
}

function safeInitCatalog() {
    try {
        initCatalogSortables();
    } catch (err) {
        console.error('splits: init del catálogo falló', err);
    }
}