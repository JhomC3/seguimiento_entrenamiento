// level-cascade.js — cascada de músculos: músculo → ejercicios → detalle.
// Owns: #cascade-row (.level-chip[data-action="set-focus"][data-tipo][data-foco]).
// Al cargar la página se despliegan los músculos del catálogo; al elegir uno
// se despliegan sus ejercicios; al elegir ejercicio, el detalle en #history-section.

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
        const el = e.target.closest('[data-action="set-focus"]');
        if (!el) return;
        // El detalle de ejercicio va a #history-section; los chips, a la cascada.
        const target = el.dataset.tipo === 'ejercicio' ? '#history-section' : '#cascade-row';
        const foco = encodeURIComponent(el.dataset.foco);
        htmx.ajax('GET', '/nivel?tipo=' + el.dataset.tipo + '&foco=' + foco, {
            target: target,
            swap: 'innerHTML',
        });
    });

    // Precarga: los músculos del catálogo como fila inicial de la cascada.
    refresh('musculo', '');
}
