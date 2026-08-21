// chart-interaction.js — owns: unified chart rendering and day-click.
// DOM owned: #unified-chart (reads #unified-chart-data JSON, renders into the
// persistent #unified-chart-plot node, toggles #unified-chart-empty visibility).
// Public API: initChartInteractions, renderUnifiedChart.
//
// Plotly is lazy-loaded: the pinned/SRI <script> is appended exactly once,
// only after a valid non-empty figure JSON appears. The promise is cached so
// re-renders reuse the loaded library; failures surface as a safe notice.
// Se usa el dist "basic" (scatter/líneas/marcadores), ~80 % más ligero que el
// full; si alguna gráfica necesita trazas gl/3d, migrar con su propio SRI.

const PLOTLY_SRC = 'https://cdn.jsdelivr.net/npm/plotly.js-basic-dist@2.32.0/plotly-basic.min.js';
const PLOTLY_INTEGRITY =
    'sha384-pR9im8+rAwCpsFtVibaZ6ll8RjHAP9rxOLJOFa05gAjmTkzo0Twd+H8wEdymZ7Dc';

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

// WeakSet: nodes that already have handlers bound.
const _clickBound = new WeakSet();
const _relayoutBound = new WeakSet();
const _wheelBound = new WeakSet();

function parseAxisRange(range, axis) {
    if (!Array.isArray(range) || range.length !== 2) return null;
    if (range.every(function (value) {
        return typeof value === 'number' && Number.isFinite(value);
    })) {
        return { values: range.slice(), isDate: false };
    }
    if (axis && axis.type === 'date') {
        const values = range.map(function (value) {
            return typeof value === 'number' ? value : Date.parse(String(value));
        });
        if (values.every(Number.isFinite)) return { values: values, isDate: true };
    }
    return null;
}

function formatAxisRange(values, isDate) {
    if (!isDate) return values;
    return values.map(function (value) {
        return new Date(value).toISOString();
    });
}

function bindHorizontalWheel(plotEl, Plotly) {
    if (_wheelBound.has(plotEl)) return;
    plotEl.addEventListener(
        'wheel',
        function (event) {
            const axis = plotEl._fullLayout && plotEl._fullLayout.xaxis;
            const parsed = parseAxisRange(axis && axis.range, axis);
            if (!parsed) return;

            const delta = event.deltaY || event.deltaX;
            if (!delta) return;
            event.preventDefault();
            event.stopPropagation();

            const span = parsed.values[1] - parsed.values[0];
            if (!Number.isFinite(span) || span <= 0) return;
            const rect = plotEl.getBoundingClientRect();
            const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
            let nextRange;
            if (event.shiftKey) {
                const direction = delta > 0 ? 1 : -1;
                // Small, deliberate steps feel closer to a timeline scrubber.
                const shift = span * 0.04 * direction;
                nextRange = parsed.values.map(function (value) {
                    return value + shift;
                });
            } else {
                // Normal wheel zooms only X, anchored at the pointer.
                const zoomFactor = delta > 0 ? 0.85 : 1.15;
                const nextSpan = span * zoomFactor;
                const anchor = parsed.values[0] + span * ratio;
                nextRange = [anchor - nextSpan * ratio, anchor + nextSpan * (1 - ratio)];
            }
            Plotly.relayout(plotEl, {
                'xaxis.range': formatAxisRange(nextRange, parsed.isDate),
                'yaxis.range': plotEl._fullLayout.yaxis.range,
                'yaxis.autorange': false,
            });
        },
        // Capture all wheel events before Plotly. Both paths update only X;
        // drag-pan remains Plotly's free two-axis interaction.
        { capture: true, passive: false },
    );
    _wheelBound.add(plotEl);
}

export function renderUnifiedChart() {
    const dataEl = document.getElementById('unified-chart-data');
    const plotEl = document.getElementById('unified-chart-plot');
    const emptyEl = document.getElementById('unified-chart-empty');
    if (!dataEl || !plotEl) return;

    let fig = null;
    try {
        fig = JSON.parse(dataEl.textContent);
    } catch (err) {
        console.error('figura de gráfica no válida', err);
        return;
    }

    if (!plotData(fig)) {
        // Empty state: purge plot, hide it, show empty div.
        if (typeof Plotly !== 'undefined') Plotly.purge(plotEl);
        plotEl.hidden = true;
        if (emptyEl) emptyEl.hidden = false;
        return;
    }

    // Data state: hide empty div, show plot, react.
    if (emptyEl) emptyEl.hidden = true;
    plotEl.hidden = false;

    // TradingView: zoom y pan exclusivamente horizontal.
    loadPlotly()
        .then(function (Plotly) {
            const layout = fig.layout || {};
            // The server-owned chart header carries the contextual title and
            // cycle label. Keeping Plotly's internal title as well duplicates
            // the heading and makes the chart feel vertically misaligned.
            layout.title = { ...(layout.title || {}), text: '' };
            layout.dragmode = 'pan';
            layout.uirevision = 'chart';
            // El pan con clic sostenido permite mover ambos ejes.
            if (!layout.xaxis) layout.xaxis = {};
            if (!layout.yaxis) layout.yaxis = {};
            layout.xaxis.fixedrange = false;
            layout.yaxis.fixedrange = false;
            layout.xaxis.rangeslider = { visible: false };
            return Plotly.react(plotEl, fig.data, layout, {
                displayModeBar: false,
                scrollZoom: false,
                doubleClick: 'reset',
                responsive: true,
            });
        })
        .then(function () {
        })
        .then(function () {
            // Accesibilidad: aria-label y foco visible para el gráfico
            plotEl.setAttribute('aria-label', 'Gráfica de rendimiento');
            plotEl.setAttribute('role', 'img');
            // Bind plotly_click once per node (WeakSet).
            if (!_clickBound.has(plotEl)) {
                plotEl.on('plotly_click', function (e) {
                    const points = e && e.points;
                    if (!points || !points.length) return;
                    const semana = points[0].x;
                    if (semana == null) return;
                    firstTrainingOfWeek(semana, 0);
                });
                _clickBound.add(plotEl);
            }
            if (!_relayoutBound.has(plotEl)) {
                plotEl.on('plotly_relayout', function (e) {
                    // El rango Y se deja libre para que el pan con clic
                    // sostenido funcione tanto vertical como horizontalmente.
                });
                _relayoutBound.add(plotEl);
            }
            bindHorizontalWheel(plotEl, Plotly);
        })
        .catch(function (err) {
            showChartError(err && err.message ? err.message : 'Error al renderizar la gráfica.');
        });
}

function firstTrainingOfWeek(semana, attempt) {
    const params = new URLSearchParams({ semana: String(semana) });
    fetch(`/semana/primer-entreno?${params.toString()}`)
        .then(function (r) {
            if (!r.ok) {
                throw new Error('No se pudo obtener el primer entreno de la semana.');
            }
            return r.json();
        })
        .then(function (data) {
            if (data && data.fecha) {
                window.location.href = '/registro?fecha=' + data.fecha;
            }
        })
        .catch(function (err) {
            if (!attempt) {
                setTimeout(function () { firstTrainingOfWeek(semana, 1); }, 400);
                return;
            }
            showChartError(err && err.message ? err.message : 'No se pudo abrir el entreno de la semana.');
        });
}

export function initChartInteractions() {
    // Render after every successful /grafica request: by afterRequest time the
    // OOB swaps have been applied to the DOM (afterSwap does not fire for OOB
    // elements when the main swap is 'none'). Stale protection lives in
    // level-cascade.js (cancelPending aborts in-flight /grafica requests).
    document.body.addEventListener('htmx:afterRequest', function (e) {
        const req = e.detail && e.detail.requestConfig;
        const path = req && req.path;
        if (path && path.startsWith('/grafica') && e.detail.successful) {
            renderUnifiedChart();
        }
    });
}
