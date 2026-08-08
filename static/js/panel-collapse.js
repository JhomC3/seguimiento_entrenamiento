// panel-collapse.js — owns: colapso de los paneles desde el chevron del header.
// Toggle de la clase `collapsed` sobre el propio panel (#session-editor /
// #nutrition-panel); el estado se persiste en localStorage y al expandir se
// re-ejecuta el fit de altura del panel.

import { fitRowsToPanel } from './editor.js';
import { fitNutritionRowsToPanel } from './nutrition-editor.js';

const PANELS = ['session-editor', 'nutrition-panel'];
const KEYS = {
    'session-editor': 'gym.panel.session',
    'nutrition-panel': 'gym.panel.nutrition',
};

function applyCollapsed(panelId, collapsed) {
    const root = document.getElementById(panelId);
    if (!root) return;
    root.classList.toggle('collapsed', collapsed);
    const btn = root.querySelector('.collapse-chevron');
    if (btn) btn.setAttribute('aria-expanded', collapsed ? '0' : '1');
    try {
        localStorage.setItem(KEYS[panelId], collapsed ? '1' : '0');
    } catch (err) {
        // localStorage puede no estar disponible: no bloquea el colapso.
    }
    if (!collapsed) {
        if (panelId === 'session-editor') fitRowsToPanel();
        else if (panelId === 'nutrition-panel') fitNutritionRowsToPanel();
    }
}

export function initPanelCollapse() {
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-action="toggle-panel-collapse"]');
        if (!btn) return;
        const panelId = btn.dataset.target;
        if (!PANELS.includes(panelId)) return;
        const root = document.getElementById(panelId);
        if (!root) return;
        applyCollapsed(panelId, !root.classList.contains('collapsed'));
    });

    PANELS.forEach(panelId => {
        try {
            if (localStorage.getItem(KEYS[panelId]) === '1') applyCollapsed(panelId, true);
        } catch (err) {
            // sin localStorage: estado por defecto expandido
        }
    });
}
