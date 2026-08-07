// chart-interaction.js — owns: week-click filtering from the unified chart.
// DOM owned: none (listens on document for plotly_click, which bubbles from the
// chart div on every OOB swap).
// Public API: initChartInteractions.

import { requestNavigate } from './date-navigation.js';
import { getActiveFilter } from './dashboard-filters.js';

function firstTrainingOfWeek(semana) {
    const filter = getActiveFilter();
    const params = new URLSearchParams({ semana: String(semana) });
    if (filter.grupo) params.set('grupo', filter.grupo);
    if (filter.ejercicio) params.set('ejercicio', filter.ejercicio);
    fetch(`/semana/primer-entreno?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            if (data && data.fecha) requestNavigate(data.fecha);
        })
        .catch(() => {});
}

export function initChartInteractions() {
    document.addEventListener('plotly_click', function (e) {
        const points = e.detail && e.detail.points;
        if (!points || !points.length) return;
        const semana = points[0].x;
        if (semana == null) return;
        firstTrainingOfWeek(semana);
    });
}
