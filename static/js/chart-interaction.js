// chart-interaction.js — owns: unified chart rendering and day-click.
// DOM owned: #unified-chart (reads the #unified-chart-data JSON and renders it
// into #unified-chart-plot on initial load and on every htmx swap).
// Public API: initChartInteractions, renderUnifiedChart.
//
// Plotly is lazy-loaded: the pinned/SRI <script> is appended exactly once,
// only after a valid non-empty figure JSON appears. The promise is cached so
// re-renders reuse the loaded library; failures surface as a safe notice.

import { openEditorPopup } from './editor-popup.js';

const PLOTLY_SRC = 'https://cdn.plot.ly/plotly-2.32.0.min.js';
const PLOTLY_INTEGRITY =
    'sha384-7TVmlZWH60iKX5Uk7lSvQhjtcgw2tkFjuwLcXoRSR4zXTyWFJRm9aPAguMh7CIra';

let plotlyPromise = null;

function loadPlotly() {
    if (plotlyPromise) return plotlyPromise;
    plotlyPromise = new Promise(function (resolve, reject) {
        const script = document.createElement('script');
        script.src = PLOTLY_SRC;
        script.integrity = PLOTLY_INTEGRITY;
        script.crossOrigin = 'anonymous';
        script.onload = function () {
            resolve(window.Plotly);
        };
        script.onerror = function () {
            plotlyPromise = null;
            reject(new Error('No se pudo cargar la gráfica (CDN no disponible).'));
        };
        document.head.appendChild(script);
    });
    return plotlyPromise;
}

function showChartError(message) {
    const container = document.getElementById('notice-container');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'notice notice-error';
    div.dataset.dismiss = '5000';
    div.setAttribute('role', 'alert');
    div.textContent = message;
    container.appendChild(div);
    import('./notices.js').then(function (notices) {
        notices.scheduleNotices();
    });
}

function plotData(fig) {
    return fig && Array.isArray(fig.data) && fig.data.length ? fig.data : null;
}

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
    if (!plotData(fig)) return; // estado vacío: el shell no mueve layout
    loadPlotly()
        .then(function (Plotly) {
            Plotly.purge(plotEl);
            return Plotly.newPlot(
                plotEl,
                fig.data,
                fig.layout || {},
                { displayModeBar: false }
            );
        })
        .then(function () {
            // plotly_click se registra sobre el div de la gráfica: la API de
            // Plotly no emite CustomEvents que burbujeen al document.
            plotEl.on('plotly_click', function (e) {
                const points = e && e.points;
                if (!points || !points.length) return;
                const semana = points[0].x;
                if (semana == null) return;
                firstTrainingOfWeek(semana);
            });
        })
        .catch(function (err) {
            showChartError(err && err.message ? err.message : 'Error al renderizar la gráfica.');
        });
}

function firstTrainingOfWeek(semana) {
    const params = new URLSearchParams({ semana: String(semana) });
    fetch(`/semana/primer-entreno?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            // El clic en un punto abre la ventana de registro en el primer
            // entreno de esa semana (alimentación + sesión + cardio del día).
            if (data && data.fecha) openEditorPopup(data.fecha);
        })
        .catch(() => {});
}

export function initChartInteractions() {
    // htmx:load dispara por cada nodo insertado en un swap (principal u OOB)
    // durante el settle, así que cubre la página inicial y /nivel, /grafica
    // sin depender de si la gráfica llegó como swap principal u OOB.
    document.body.addEventListener('htmx:load', function (e) {
        if (e.target && e.target.id === 'unified-chart-plot') {
            renderUnifiedChart();
        }
    });
}
