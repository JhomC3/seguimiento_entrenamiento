// reorder-controls.js — shared keyboard reorder: a single grip handle per
// item. Focusing the grip and pressing ArrowUp/ArrowDown moves the item;
// pointer DnD remains an enhancement on top. Public API:
// moveListElement, bindGripMoves, persistOrderWithHtmx.

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

export function bindGripMoves(listSelector, itemSelector, onChange) {
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        if (document.activeElement !== e.target) return;
        const grip = e.target.closest('[data-action="move-grip"]');
        if (!grip) return;
        const item = grip.closest(itemSelector);
        if (!item || !item.parentElement.closest(listSelector)) return;
        e.preventDefault();
        const list = item.parentElement;
        const before = Array.from(list.children)
            .map(function (c) { return c.dataset.ptId || c.dataset.rowId || ''; })
            .join(',');
        const delta = e.key === 'ArrowUp' ? -1 : 1;
        if (moveListElement(item, delta) && onChange) {
            onChange(item, before);
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
