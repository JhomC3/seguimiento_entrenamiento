// panel-collapse.js — owns: colapso de los paneles desde el chevron del header.
// Toggle de la clase `collapsed` sobre el propio panel (#session-editor /
// #nutrition-panel); el estado se persiste en localStorage. La altura de la
// tabla es fija en CSS, así que colapsar/expandir no requiere re-medición.

const PANELS = ['session-editor', 'nutrition-panel'];
const KEYS = {
    'session-editor': 'gym.panel.session.v2',
    'nutrition-panel': 'gym.panel.nutrition.v2',
};

function applyCollapsed(panelId, collapsed) {
    const root = document.getElementById(panelId);
    if (!root) return;
    root.classList.toggle('collapsed', collapsed);
    const btn = root.querySelector('.collapse-chevron');
    if (btn) btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    try {
        localStorage.setItem(KEYS[panelId], collapsed ? '1' : '0');
    } catch (err) {
        // localStorage puede no estar disponible: no bloquea el colapso.
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
