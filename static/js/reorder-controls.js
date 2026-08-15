// reorder-controls.js — shared keyboard reorder: explicit ↑/↓ buttons for
// every sortable list. Pointer DnD remains an enhancement on top; the buttons
// are the accessible path and the only one that must work without a mouse.
// Public API: moveListElement, syncMoveButtons, persistOrderWithHtmx.

import { showNotice } from './notices.js';

export function moveListElement(item, delta) {
    const list = item.parentElement;
    if (!list) return false;
    const items = Array.from(list.children);
    const idx = items.indexOf(item);
    if (idx === -1) return false;
    const target = idx + delta;
    if (target < 0 || target >= items.length) return false;
    list.insertBefore(item, items[target + (delta > 0 ? 1 : 0)]);
    return true;
}

export function syncMoveButtons(listSelector, itemSelector) {
    const list = document.querySelector(listSelector);
    if (!list) return;
    const items = Array.from(list.querySelectorAll(itemSelector));
    items.forEach((item, i) => {
        const up = item.querySelector('[data-action="move-item"][data-dir="-1"]');
        const down = item.querySelector('[data-action="move-item"][data-dir="1"]');
        if (up) up.disabled = i === 0;
        if (down) down.disabled = i === items.length - 1;
    });
}

export function bindMoveButtons(listSelector, itemSelector, onChange) {
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-action="move-item"]');
        if (!btn) return;
        const item = btn.closest(itemSelector);
        if (!item || !item.parentElement.closest(listSelector)) return;
        const delta = parseInt(btn.dataset.dir, 10) || 0;
        const list = item.parentElement;
        const before = Array.from(list.children)
            .map(function (c) { return c.dataset.ptId || c.dataset.rowId || ''; })
            .join(',');
        if (moveListElement(item, delta)) {
            syncMoveButtons(listSelector, itemSelector);
            if (onChange) onChange(item, before);
        }
    });
}

export function persistOrderWithHtmx(url, ids, listEl, beforeOrder, onError) {
    const after = ids.join(',');
    if (beforeOrder === after) return;
    htmx.ajax('POST', url, { values: { id: ids }, target: 'body', swap: 'none' });

    const restore = function () {
        const cards = Array.from(listEl.children);
        const byId = {};
        cards.forEach(function (c) { byId[c.dataset.ptId] = c; });
        beforeOrder.split(',').forEach(function (id) {
            const card = byId[id];
            if (card) listEl.appendChild(card);
        });
        syncMoveButtons('#' + listEl.id, '.pt-card');
    };

    const onAfter = function (e) {
        const detail = e.detail || {};
        const path = (detail.requestConfig && detail.requestConfig.path) || detail.path;
        if (path !== url) return;
        document.body.removeEventListener('htmx:afterRequest', onAfter);
        if (!detail.successful) {
            restore();
            if (onError) onError();
            else showNotice('No se pudo guardar el orden. Reintenta.', 'error');
        }
    };
    document.body.addEventListener('htmx:afterRequest', onAfter);
}
