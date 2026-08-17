// reorder-controls.js — persistencia de órdenes reordenadas por DnD.
// Public API: persistOrderWithHtmx.

import { showNotice } from './notices.js';

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
