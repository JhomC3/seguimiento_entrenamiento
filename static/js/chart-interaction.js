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
const _relayoutBound = new WeakSet();
const _wheelBound = new WeakSet();
const _plotResizeObserver = new WeakMap();

// Lista real de categorías del eje: interna de Plotly o reconstruida desde las
// trazas en orden de aparición (mismo criterio por defecto de Plotly para
// categoryorder). Nunca se infiere de los valores del rango.
function categoryListOf(plotEl, axis) {
    const internal = axis && (axis._categories || axis.categoryarray);
    if (Array.isArray(internal) && internal.length) return internal.map(String);
    const cats = [];
    const seen = Object.create(null);
    const fullData = plotEl && plotEl._fullData;
    if (Array.isArray(fullData)) {
        fullData.forEach(function (trace) {
            if (!trace || !Array.isArray(trace.x)) return;
            if (axis && axis._id && trace.xaxis && trace.xaxis !== axis._id) return;
            trace.x.forEach(function (value) {
                const key = String(value);
                if (!(key in seen)) {
                    seen[key] = true;
                    cats.push(key);
                }
            });
        });
    }
    return cats.length ? cats : null;
}

function parseAxisRange(plotEl, axis) {
    const range = axis && axis.range;
    if (!Array.isArray(range) || range.length !== 2) return null;
    if (range.every(function (value) {
        return typeof value === 'number' && Number.isFinite(value);
    })) {
        // El rango ya es numérico (índices con decimales incluidos): usarlo tal cual.
        return { values: range.slice(), isDate: false, isCategory: false };
    }
    if (axis.type === 'date') {
        const values = range.map(function (value) {
            return typeof value === 'number' ? value : Date.parse(String(value));
        });
        if (values.every(Number.isFinite)) return { values: values, isDate: true, isCategory: false };
    }
    if (axis.type === 'category') {
        // Las etiquetas categóricas se resuelven EXCLUSIVAMENTE contra la lista
        // real de categorías del eje. Si no se pueden resolver, no hay zoom:
        // nunca se convierte un string numérico a índice con Number() porque la
        // etiqueta "2" (Semana 2) no representa el índice 2.
        if (range.every(function (value) { return typeof value === 'string'; })) {
            const cats = categoryListOf(plotEl, axis);
            if (!cats) return null;
            const indexOfCat = Object.create(null);
            cats.forEach(function (cat, i) {
                if (!(cat in indexOfCat)) indexOfCat[cat] = i;
            });
            const values = range.map(function (value) {
                const idx = indexOfCat[value];
                return typeof idx === 'number' ? idx : NaN;
            });
            if (values.every(Number.isFinite)) {
                return { values: values, isDate: false, isCategory: true };
            }
        }
    }
    return null;
}

function formatAxisRange(values, parsed) {
    // Compatibilidad: segundo arg puede ser boolean isDate o objeto parsed.
    const isDate = parsed && typeof parsed === 'object' ? !!parsed.isDate : !!parsed;
    if (isDate) {
        return values.map(function (value) {
            return new Date(value).toISOString();
        });
    }
    // Numérico y categórico: devolver los números tal cual, conservando los
    // decimales producidos por zoom/pan. Plotly acepta rangos numéricos
    // fraccionarios en ejes categoría; redondear a etiquetas destruye la
    // precisión y hace saltar el rango tras varias operaciones.
    return values;
}

function bindHorizontalWheel(plotEl, Plotly) {
    if (_wheelBound.has(plotEl)) return;
    plotEl.addEventListener(
        'wheel',
        function (event) {
            const full = plotEl._fullLayout;
            if (!full || !full.xaxis || !full.yaxis) return;
            const delta = event.deltaY || event.deltaX;
            if (!delta) return;

            // Shift+rueda tiene prioridad absoluta: siempre desplazamiento horizontal sobre X,
            // incluso cuando el cursor está sobre el eje Y.
            if (event.shiftKey) {
                const axis = full.xaxis;
                const parsed = parseAxisRange(plotEl, axis);
                if (!parsed) return;
                const span = parsed.values[1] - parsed.values[0];
                if (!Number.isFinite(span) || span <= 0) return;
                event.preventDefault();
                event.stopPropagation();
                const direction = delta > 0 ? 1 : -1;
                const shift = span * 0.04 * direction;
                const nextRange = parsed.values.map(function (value) {
                    return value + shift;
                });
                Plotly.relayout(plotEl, {
                    'xaxis.range': formatAxisRange(nextRange, parsed),
                    'yaxis.range': full.yaxis.range,
                    'yaxis.autorange': false,
                });
                return;
            }

            // Detección geométrica del eje Y (sin depender de clases internas de Plotly).
            const rect = plotEl.getBoundingClientRect();
            const margin = full.margin || { l: 0, r: 0, t: 0, b: 0 };
            const plotWidth = (full.width || rect.width) - margin.l - margin.r;
            const plotHeight = (full.height || rect.height) - margin.t - margin.b;
            const plotLeft = rect.left + margin.l;
            const plotTop = rect.top + margin.t;
            const isOverYAxis =
                event.clientX >= rect.left &&
                event.clientX < plotLeft &&
                event.clientY >= plotTop &&
                event.clientY < plotTop + plotHeight;
            const isOverPlot =
                event.clientX >= plotLeft &&
                event.clientX < plotLeft + plotWidth &&
                event.clientY >= plotTop &&
                event.clientY < plotTop + plotHeight;
            if (!isOverYAxis && !isOverPlot) return;

            event.preventDefault();
            event.stopPropagation();

            if (isOverYAxis) {
                const axis = full.yaxis;
                const parsed = parseAxisRange(plotEl, axis);
                if (!parsed) return;
                const span = parsed.values[1] - parsed.values[0];
                if (!Number.isFinite(span) || span <= 0) return;
                const ratioY = Math.min(1, Math.max(0, (event.clientY - plotTop) / plotHeight));
                const zoomFactor = delta > 0 ? 1.15 : 0.85;
                let nextSpan = span * zoomFactor;
                const minSpan = 1e-9;
                if (nextSpan < minSpan) nextSpan = minSpan;
                const anchor = parsed.values[0] + span * ratioY;
                let nextRange = [anchor - nextSpan * ratioY, anchor + nextSpan * (1 - ratioY)];
                if (nextRange[0] >= nextRange[1]) return;
                Plotly.relayout(plotEl, {
                    'yaxis.range': formatAxisRange(nextRange, parsed),
                    'xaxis.range': full.xaxis.range,
                    'xaxis.autorange': false,
                });
            } else {
                const axis = full.xaxis;
                const parsed = parseAxisRange(plotEl, axis);
                if (!parsed) return;
                const span = parsed.values[1] - parsed.values[0];
                if (!Number.isFinite(span) || span <= 0) return;
                const ratio = Math.min(1, Math.max(0, (event.clientX - plotLeft) / plotWidth));
                const zoomFactor = delta > 0 ? 1.15 : 0.85;
                let nextSpan = span * zoomFactor;
                const minSpan = 1e-9;
                if (nextSpan < minSpan) nextSpan = minSpan;
                const anchor = parsed.values[0] + span * ratio;
                let nextRange = [anchor - nextSpan * ratio, anchor + nextSpan * (1 - ratio)];
                if (nextRange[0] >= nextRange[1]) return;
                Plotly.relayout(plotEl, {
                    'xaxis.range': formatAxisRange(nextRange, parsed),
                    'yaxis.range': full.yaxis.range,
                    'yaxis.autorange': false,
                });
            }
        },
        // Capture all wheel events before Plotly.
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
        // Empty state: purge plot, hide it, show empty div. Desconectar observer.
        if (_plotResizeObserver.has(plotEl)) {
            _plotResizeObserver.get(plotEl).disconnect();
            _plotResizeObserver.delete(plotEl);
        }
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
            // La caja visual la fija el CSS (#unified-chart clamp + flex):
            // se pasan ancho y alto EXPLÍCITOS medidos del propio plot para
            // evitar la carrera del primer render (sin CLS ready/empty).
            const targetW = plotEl.clientWidth;
            const targetH = plotEl.clientHeight;
            if (targetW > 0) layout.width = targetW;
            if (targetH > 0) layout.height = targetH;
            if (targetW > 0 || targetH > 0) layout.autosize = false;
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
            }).then(function () {
                // ResizeObserver robusto: observa #unified-chart-plot y mantiene
                // Plotly sincronizado con el contenedor en ambas direcciones.
                if (_plotResizeObserver.has(plotEl)) {
                    _plotResizeObserver.get(plotEl).disconnect();
                }
                const ro = new ResizeObserver(function () {
                    if (plotEl.hidden) return;
                    const w = plotEl.clientWidth;
                    const h = plotEl.clientHeight;
                    if (w < 10 || h < 10) return;
                    const layoutW = plotEl._fullLayout && plotEl._fullLayout.width;
                    const layoutH = plotEl._fullLayout && plotEl._fullLayout.height;
                    if (Math.abs(w - layoutW) > 1 || Math.abs(h - layoutH) > 1) {
                        Plotly.relayout(plotEl, { width: w, height: h, autosize: false });
                    }
                });
                ro.observe(plotEl);
                _plotResizeObserver.set(plotEl, ro);
            });
        })
        .then(function () {
        })
        .then(function () {
            // Accesibilidad: aria-label y foco visible para el gráfico
            plotEl.setAttribute('aria-label', 'Gráfica de rendimiento');
            plotEl.setAttribute('role', 'img');
            // La gráfica es EXCLUSIVAMENTE analítica: sin handler de
            // plotly_click. Un clic sobre un punto no navega, no abre registro
            // ni modifica URL/selección (zoom, pan y tooltips quedan intactos).
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
