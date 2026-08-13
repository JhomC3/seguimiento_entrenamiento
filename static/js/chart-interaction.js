// chart-interaction.js — owns: unified chart rendering and week-click filtering.
// DOM owned: #unified-chart (reads the #unified-chart-data JSON and renders it
// into #unified-chart-plot on initial load and on every htmx swap).
// Public API: initChartInteractions, renderUnifiedChart.

import { requestNavigate } from './date-navigation.js';

export function renderUnifiedChart() {
    const dataEl = document.getElementById('unified-chart-data');
    const plotEl = document.getElementById('unified-chart-plot');
    if (!dataEl || !plotEl) return;
    let fig = null;
    try {
        fig = JSON.parse(dataEl.textContent);
    } catch (err) {
        console.error('figura de gráfica no válida', err);
        return;
    }
    if (typeof Plotly === 'undefined') return;
    Plotly.purge(plotEl);
    Plotly.newPlot(plotEl, fig.data || [], fig.layout || {}, { displayModeBar: false }).then(
        function () {
            // plotly_click se registra sobre el div de la gráfica: la API de
            // Plotly no emite CustomEvents que burbujeen al document.
            plotEl.on('plotly_click', function (e) {
                const points = e && e.points;
                if (!points || !points.length) return;
                const semana = points[0].x;
                if (semana == null) return;
                firstTrainingOfWeek(semana);
            });
        }
    );
}

function firstTrainingOfWeek(semana) {
    const params = new URLSearchParams({ semana: String(semana) });
    fetch(`/semana/primer-entreno?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            if (data && data.fecha) requestNavigate(data.fecha);
        })
        .catch(() => {});
}

export function initChartInteractions() {
    // htmx:load dispara por cada nodo insertado en un swap (principal u OOB)
    // durante el settle, así que cubre la página inicial y /select, /grupo/reset
    // y /ejercicio sin depender de si la gráfica llegó como swap principal u OOB.
    document.body.addEventListener('htmx:load', function (e) {
        if (e.target && e.target.id === 'unified-chart-plot') {
            renderUnifiedChart();
        }
    });
}
