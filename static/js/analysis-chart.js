// analysis-chart.js — analysis view: stacked chart rendering and day click.
// Owns: #analysis-chart-wrap (reads #analysis-chart-data JSON and renders into
// #analysis-chart-plot); refetches /analisis/chart on level/layer changes;
// click on a day loads the "¿qué pasó" panel into #day-detail-section.

import { getActiveLayers } from './layer-toggles.js';

function currentState() {
    const pill = document.querySelector('.pills-track .pill[aria-pressed="true"]');
    const nivel = (pill && pill.dataset.nivel) || 'global';
    let focus = '';
    const filters = document.getElementById('analysis-filters');
    if (filters) {
        const activeChip = filters.querySelector('.filter-chip[aria-pressed="true"]');
        if (activeChip) focus = activeChip.dataset.focus || '';
        const input = filters.querySelector('.exercise-search');
        if (input && input.value.trim()) focus = input.value.trim();
    }
    return { nivel, focus };
}

function clearFocusSelection() {
    const filters = document.getElementById('analysis-filters');
    if (!filters) return;
    filters.querySelectorAll('.filter-chip').forEach((c) => c.setAttribute('aria-pressed', 'false'));
    const input = filters.querySelector('.exercise-search');
    if (input) input.value = '';
}

function refreshChart() {
    const { nivel, focus } = currentState();
    const params = new URLSearchParams({ nivel, focus, rango: '8' });
    getActiveLayers().forEach((l) => params.append('layers', l));
    htmx.ajax('GET', '/analisis/chart?' + params.toString(), {
        target: document.body,
        swap: 'none',
    });
}

function loadDay(fechaIso) {
    const { nivel, focus } = currentState();
    const params = new URLSearchParams({ fecha: fechaIso, nivel, focus });
    htmx.ajax('GET', '/analisis/dia?' + params.toString(), {
        target: '#day-detail-section',
        swap: 'innerHTML',
    });
}

function isoFromClickX(x) {
    if (x == null) return null;
    const d = new Date(x);
    if (Number.isNaN(d.getTime())) return null;
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

export function renderAnalysisChart() {
    const dataEl = document.getElementById('analysis-chart-data');
    const plotEl = document.getElementById('analysis-chart-plot');
    if (!dataEl || !plotEl) return;
    let fig = null;
    try {
        fig = JSON.parse(dataEl.textContent);
    } catch (err) {
        console.error('figura de análisis no válida', err);
        return;
    }
    if (typeof Plotly === 'undefined') return;
    Plotly.purge(plotEl);
    Plotly.newPlot(plotEl, fig.data || [], fig.layout || {}, { displayModeBar: false }).then(
        function () {
            plotEl.on('plotly_click', function (e) {
                const points = e && e.points;
                if (!points || !points.length) return;
                const iso = isoFromClickX(points[0].x);
                if (iso) loadDay(iso);
            });
        }
    );
}

export function initAnalysisChart() {
    document.body.addEventListener('htmx:load', function (e) {
        if (e.target && e.target.id === 'analysis-chart-plot') {
            renderAnalysisChart();
        }
    });

    const wrap = document.getElementById('analysis-chart-wrap');
    if (wrap) {
        wrap.addEventListener('analysis:level-changed', function () {
            clearFocusSelection();
            refreshChart();
        });
        wrap.addEventListener('analysis:layers-changed', refreshChart);
    }

    document.addEventListener('click', function (e) {
        const chip = e.target.closest('#analysis-filters .filter-chip[data-action="set-focus"]');
        if (!chip) return;
        if (chip.getAttribute('aria-pressed') === 'true') return;
        document
            .querySelectorAll('#analysis-filters .filter-chip')
            .forEach((c) => c.setAttribute('aria-pressed', 'false'));
        chip.setAttribute('aria-pressed', 'true');
        refreshChart();
    });

    document.addEventListener('keydown', function (e) {
        const input = e.target && e.target.matches && e.target.matches('.exercise-search');
        if (!input) return;
        if (e.key !== 'Enter') return;
        e.preventDefault();
        refreshChart();
    });
}
