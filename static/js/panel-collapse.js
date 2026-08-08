// panel-collapse.js — owns: barras de colapso de los paneles (Entrenamiento y
// Alimentación). El estado se persiste en localStorage; al expandir se
// re-ejecuta el fit de altura del panel correspondiente.

import { fitRowsToPanel } from './editor.js';
import { fitNutritionRowsToPanel } from './nutrition-editor.js';

const PANELS = ['nutrition-panel-body', 'session-panel-body'];
const KEYS = {
    'nutrition-panel-body': 'gym.panel.nutrition',
    'session-panel-body': 'gym.panel.session',
};

function applyCollapsed(id, collapsed) {
    const body = document.getElementById(id);
    if (!body) return;
    body.classList.toggle('collapsed', collapsed);
    const card = body.closest('.panel-collapse-card');
    if (card) card.classList.toggle('collapsed', collapsed);
    const btn = document.querySelector(`[data-action="toggle-panel-collapse"][data-target="${id}"]`);
    if (btn) btn.setAttribute('aria-expanded', collapsed ? '0' : '1');
    try {
        localStorage.setItem(KEYS[id], collapsed ? '1' : '0');
    } catch (err) {
        // localStorage puede no estar disponible (modo privado): no bloquea.
    }
    if (!collapsed) {
        if (id === 'session-panel-body') fitRowsToPanel();
        else if (id === 'nutrition-panel-body') fitNutritionRowsToPanel();
    }
}

export function initPanelCollapse() {
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-action="toggle-panel-collapse"]');
        if (!btn) return;
        const id = btn.dataset.target;
        const body = document.getElementById(id);
        if (!body) return;
        applyCollapsed(id, !body.classList.contains('collapsed'));
    });

    PANELS.forEach(id => {
        try {
            if (localStorage.getItem(KEYS[id]) === '1') applyCollapsed(id, true);
        } catch (err) {
            // sin localStorage: estado por defecto expandido
        }
    });
}
