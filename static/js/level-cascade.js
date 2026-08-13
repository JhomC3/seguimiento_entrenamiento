// level-cascade.js — navegación por niveles + cascada grupo → músculo → ejercicio.
// Owns: .level-btn[data-action="set-level"], #cascade-row (.level-chip[data-action="set-focus"]).
// Cada paso pide /nivel?tipo=...&foco=... y la respuesta trae la siguiente fila
// de chips + el OOB de la gráfica unificada.

function refresh(nivel, foco) {
    const params = new URLSearchParams({ tipo: nivel });
    if (foco) params.set('foco', foco);
    htmx.ajax('GET', '/nivel?' + params.toString(), {
        target: '#cascade-row',
        swap: 'outerHTML',
    });
}

export function initLevelCascade() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'set-level') {
            document
                .querySelectorAll('.level-btn')
                .forEach((b) => b.classList.toggle('active', b.dataset.tipo === el.dataset.tipo));
            refresh(el.dataset.tipo, '');
        } else if (el.dataset.action === 'set-focus') {
            // El detalle de ejercicio va a #history-section; los chips, a la cascada.
            const target = el.dataset.tipo === 'ejercicio' ? '#history-section' : '#cascade-row';
            const foco = encodeURIComponent(el.dataset.foco);
            htmx.ajax('GET', '/nivel?tipo=' + el.dataset.tipo + '&foco=' + foco, {
                target: target,
                swap: 'innerHTML',
            });
        }
    });
}
