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

// --- UX-3 revisada: highlight local (sin tabla secundaria, sin customdata mutation) ---
let highlightedIds = new Set();
const _highlightBound = new WeakSet();

// --- UX-2: tooltip propio (suprime hover nativo) ---
const _tooltipBound = new WeakSet();
let _tooltipEl = null;
let _tooltipHideTimer = null;

function getOrCreateTooltip() {
    if (_tooltipEl && document.body.contains(_tooltipEl)) return _tooltipEl;
    const el = document.createElement('div');
    el.className = 'chart-tooltip';
    el.setAttribute('role', 'tooltip');
    el.setAttribute('aria-hidden', 'true');
    el.hidden = true;
    document.body.appendChild(el);
    _tooltipEl = el;
    return el;
}

function hideTooltip() {
    if (_tooltipHideTimer) {
        clearTimeout(_tooltipHideTimer);
        _tooltipHideTimer = null;
    }
    const el = _tooltipEl;
    if (!el) return;
    el.classList.remove('is-visible');
    el.setAttribute('aria-hidden', 'true');
    // Retardo para permitir transición antes de hidden
    _tooltipHideTimer = setTimeout(function () {
        if (!el.classList.contains('is-visible')) {
            el.hidden = true;
            el.textContent = '';
        }
    }, 90);
}

function positionTooltip(clientX, clientY) {
    const el = _tooltipEl;
    if (!el) return;
    const pad = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // Medir tras contenido ya renderizado pero aún oculto (visibility hidden)
    const rect = el.getBoundingClientRect();
    let left = clientX + 14;
    let top = clientY + 14;
    if (left + rect.width + pad > vw) left = clientX - rect.width - 14;
    if (left < pad) left = pad;
    if (top + rect.height + pad > vh) top = clientY - rect.height - 14;
    if (top < pad) top = pad;
    el.style.left = left + 'px';
    el.style.top = top + 'px';
}

function buildTooltipContent(points) {
    if (!points || !points.length) return null;
    // Header único: primera traza, customdata[0] ya viene formateado por backend
    // (día "18 jul" / "18 jul 2026", semana "18 jul 2026", mes "julio 2026")
    // No repetir por bloque, no usar "S1"/"Semana 1" ni ISO.
    const firstVals = extractPointValuesJS(points[0].customdata);
    const header = firstVals ? firstVals.periodo : String(points[0].x);
    const body = document.createDocumentFragment();
    const headerEl = document.createElement('div');
    headerEl.className = 'chart-tooltip__header';
    headerEl.textContent = header;
    body.appendChild(headerEl);
    const wrap = document.createElement('div');
    wrap.className = 'chart-tooltip__body';
    points.forEach(function (pt, idx) {
        const vals = extractPointValuesJS(pt.customdata);
        if (!vals) return;
        if (idx > 0) {
            const div = document.createElement('div');
            div.className = 'chart-tooltip__divider';
            div.setAttribute('aria-hidden', 'true');
            wrap.appendChild(div);
        }
        const block = document.createElement('div');
        block.className = 'chart-tooltip__block';
        const traceName = vals.trace || (pt.data && pt.data.name) || '';
        const swatchColor = (pt.data && (pt.data.line && pt.data.line.color || pt.data.marker && pt.data.marker.color)) || '';
        block.setAttribute('role', 'group');
        if (traceName) block.setAttribute('aria-label', traceName);
        const traceEl = document.createElement('div');
        traceEl.className = 'chart-tooltip__trace';
        const swatch = document.createElement('span');
        swatch.className = 'chart-tooltip__swatch';
        swatch.setAttribute('aria-hidden', 'true');
        swatch.style.background = swatchColor || 'var(--t-chart-primary)';
        const nameEl = document.createElement('span');
        nameEl.className = 'chart-tooltip__trace-name';
        nameEl.textContent = traceName;
        traceEl.appendChild(swatch);
        traceEl.appendChild(nameEl);
        block.appendChild(traceEl);
        // Orden UX-2: Series, VAR, Reps, Peso, RIR, RM (sin Cobertura)
        const rows = [
            ['Series', vals.series],
            ['VAR', vals.delta],
            ['Reps', vals.reps],
            ['Peso', vals.peso],
            ['RIR', vals.rir],
            ['RM', vals.rm],
        ];
        rows.forEach(function (pair) {
            const label = pair[0], value = pair[1];
            const row = document.createElement('div');
            row.className = 'chart-tooltip__row';
            const lab = document.createElement('span');
            lab.className = 'chart-tooltip__label';
            lab.textContent = label;
            const val = document.createElement('span');
            val.className = 'chart-tooltip__value';
            val.textContent = value || '—';
            row.appendChild(lab);
            row.appendChild(val);
            block.appendChild(row);
        });
        wrap.appendChild(block);
    });
    body.appendChild(wrap);
    return body;
}

function showTooltip(evt) {
    if (!evt || !evt.points || !evt.points.length) return;
    const el = getOrCreateTooltip();
    if (_tooltipHideTimer) {
        clearTimeout(_tooltipHideTimer);
        _tooltipHideTimer = null;
    }
    // Construir contenido
    const content = buildTooltipContent(evt.points);
    if (!content) return;
    el.textContent = '';
    el.appendChild(content);
    el.hidden = false;
    // Forzar layout antes de posicionar
    el.getBoundingClientRect();
    const clientX = evt.event ? evt.event.clientX : (evt.points[0].x || 0);
    const clientY = evt.event ? evt.event.clientY : (evt.points[0].y || 0);
    // Si clientX/Y no son números (p. ej. en tests), usar fallback centrado
    const x = typeof clientX === 'number' && Number.isFinite(clientX) ? clientX : window.innerWidth / 2;
    const y = typeof clientY === 'number' && Number.isFinite(clientY) ? clientY : window.innerHeight / 3;
    positionTooltip(x, y);
    el.classList.add('is-visible');
    el.setAttribute('aria-hidden', 'false');
}

function bindTooltip(plotEl, Plotly) {
    if (_tooltipBound.has(plotEl)) return;
    // Suprimir hover nativo pero conservar eventos (spike v1: hovertemplate null + hoverinfo none)
    // Usar valor único para todas las trazas (spike: Plotly.restyle(el, {hoverinfo:'none', hovertemplate:null}))
    try {
        if (plotEl._fullData && plotEl._fullData.length) {
            Plotly.restyle(plotEl, {hoverinfo: 'none', hovertemplate: null});
        }
    } catch (_) {}
    plotEl.on('plotly_hover', function (data) {
        showTooltip(data);
    });
    plotEl.on('plotly_unhover', function () {
        hideTooltip();
    });
    // También ocultar al salir del plot o al hacer scroll
    plotEl.addEventListener('mouseleave', hideTooltip);
    _tooltipBound.add(plotEl);
}

function getCurrentGranularity() {
    const sel = document.querySelector('#granularity-selector [data-gran][aria-pressed="true"]');
    return sel ? sel.dataset.gran : 'week';
}
function historicalPeriodIdJS(granularity, periodoNorm, entityNorm) {
    return `${String(granularity).toLowerCase()}|${String(periodoNorm).trim()}|${String(entityNorm).trim().toLowerCase()}`;
}
function normalizePeriodoForId(gran, xRaw) {
    // pt.x ya es normalizado: day=YYYY-MM-DD, week=number, month=YYYY-MM
    return String(xRaw).trim();
}
function extractPointValuesJS(customdata) {
    if (!Array.isArray(customdata)) return null;
    try {
        if (customdata.length === 8) {
            return {
                periodo: String(customdata[0]),
                delta: String(customdata[1]),
                series: String(customdata[2]),
                reps: String(customdata[3]),
                peso: String(customdata[4]),
                rir: String(customdata[5]),
                rm: String(customdata[6]),
                trace: String(customdata[7]),
            };
        }
        if (customdata.length >= 9) {
            return {
                periodo: String(customdata[0]),
                delta: String(customdata[1]),
                series: String(customdata[2]),
                reps: String(customdata[3]),
                peso: String(customdata[4]),
                rir: String(customdata[5]),
                rm: String(customdata[6]),
                cobertura: String(customdata[7]),
                trace: String(customdata[8]),
            };
        }
    } catch (_) { return null; }
    return null;
}

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

function clearChartHighlight(opts) {
    const silent = opts && opts.silent;
    highlightedIds.clear();
    document.querySelectorAll('#period-summary-wrap .ps-row.is-selected').forEach(function (el) {
        el.classList.remove('is-selected');
        el.removeAttribute('data-selected');
    });
    if (!silent) {
        // No live region ruidosa; highlight es sutil
    }
}

function closeAllDetails() {
    document.querySelectorAll('#period-summary-wrap .ps-row-toggle[aria-expanded="true"]').forEach(function (btn) {
        btn.setAttribute('aria-expanded', 'false');
        const id = btn.getAttribute('aria-controls');
        if (id) {
            const det = document.getElementById(id);
            if (det) det.hidden = true;
        }
    });
}

function isExercisePanelActive() {
    const panel = document.querySelector('#period-summary-wrap .ps-panel[data-nivel="exercise"]:not([hidden])');
    return !!panel && !!panel.querySelector('.ps-row[data-period-id]');
}
function highlightRow(periodId, add) {
    const panel = document.querySelector('#period-summary-wrap .ps-panel[data-nivel="exercise"]:not([hidden])');
    if (!panel) return false;
    const row = panel.querySelector('.ps-row[data-period-id="' + CSS.escape(periodId) + '"]');
    if (!row) return false;
    if (!add) clearChartHighlight({silent:true});
    if (highlightedIds.has(periodId)) {
        row.classList.remove('is-selected');
        row.removeAttribute('data-selected');
        highlightedIds.delete(periodId);
        if (highlightedIds.size===0) return true;
        return true;
    }
    row.classList.add('is-selected');
    row.setAttribute('data-selected', 'true');
    highlightedIds.add(periodId);
    // No solo color: borde + background + font-weight via CSS
    try { row.scrollIntoView({block:'nearest', behavior:'smooth'}); } catch (_) {}
    return true;
}

function handlePointHighlight(pointData, shiftKey) {
    if (!pointData || !pointData.points || !pointData.points.length) return;
    const pt = pointData.points[0];
    const vals = extractPointValuesJS(pt.customdata);
    // No usar customdata[0] para id; usar pt.x normalizado + traza
    const gran = getCurrentGranularity();
    const xRaw = normalizePeriodoForId(gran, pt.x);
    const traceName = String(pt.data && pt.data.name ? pt.data.name : (vals && vals.trace) ? vals.trace : '');
    const periodoNorm = xRaw; // ya normalizado: YYYY-MM-DD / number / YYYY-MM
    const id = historicalPeriodIdJS(gran, periodoNorm, traceName);
    // Solo exercise tiene correspondencia; si no hay fila, no error y no fetch
    highlightRow(id, !!shiftKey);
}

function bindHighlight(plotEl) {
    if (_highlightBound.has(plotEl)) return;
    plotEl.on('plotly_click', function (data) {
        const shiftKey = data.event ? !!data.event.shiftKey : false;
        handlePointHighlight(data, shiftKey);
    });
    _highlightBound.add(plotEl);
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
        clearChartHighlight({silent:true});
        closeAllDetails();
        hideTooltip();
        return;
    }

    // Nueva figura OOB: limpiar highlight previo (puntos ya no pertenecen)
    clearChartHighlight({silent:true});
    closeAllDetails();

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
            // UX-2: suprimir tooltip nativo (hovertemplate ya null en servidor), conservar eventos
            fig.data.forEach(function (t) {
                t.hoverinfo = 'none';
                t.hovertemplate = null;
            });
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
            plotEl.setAttribute('tabindex', '0');
            if (!_relayoutBound.has(plotEl)) {
                plotEl.on('plotly_relayout', function (e) {
                    // El rango Y se deja libre para que el pan con clic
                    // sostenido funcione tanto vertical como horizontalmente.
                });
                _relayoutBound.add(plotEl);
            }
            bindHorizontalWheel(plotEl, Plotly);
            bindHighlight(plotEl);
            bindTooltip(plotEl, Plotly);
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
    // Escape con prioridad existente: dialog/drawer > highlight+acordeón (level-cascade gestiona drawer)
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (highlightedIds.size === 0 && !document.querySelector('#period-summary-wrap .ps-row-toggle[aria-expanded="true"]')) return;
        const drawerOpen = document.querySelector('.dashboard-page') && !document.querySelector('.dashboard-page').classList.contains('is-catalog-collapsed') && window.matchMedia('(max-width: 1023px)').matches;
        if (drawerOpen) return;
        // Solo highlight/acordeón exercise Day; conservar prioridad global
        e.preventDefault();
        clearChartHighlight();
        closeAllDetails();
    });
    document.body.addEventListener('htmx:oobAfterSwap', function (e) {
        if (e.detail.target && e.detail.target.id === 'period-summary-wrap') {
            clearChartHighlight({silent:true});
            closeAllDetails();
        }
    });
    // Exponer para level-cascade (cambios de granularidad/selección/ventana)
    window.clearChartHighlight = clearChartHighlight;
    window.closeAllDetails = closeAllDetails;
    window.getChartHighlight = function () { return Array.from(highlightedIds); };
    window.clearChartComparison = clearChartHighlight; // compat legacy tests
    window.getChartComparison = window.getChartHighlight;
    // Helpers para tests E2E (simulan clic sin depender de coordenadas SVG)
    window.__testHighlightClick = function (traceIdx, pointIdx, shiftKey) {
        const plotEl = document.getElementById('unified-chart-plot');
        if (!plotEl || !Array.isArray(plotEl._fullData)) return false;
        const trace = plotEl._fullData[traceIdx];
        if (!trace || !trace.x || typeof trace.x.length !== 'number' || !Array.isArray(trace.customdata)) return false;
        const cd = trace.customdata[pointIdx];
        const x = trace.x[pointIdx];
        if (cd === undefined || x === undefined) return false;
        const pt = {x: x, customdata: cd, curveNumber: traceIdx, pointNumber: pointIdx, data: trace};
        handlePointHighlight({points: [pt]}, !!shiftKey);
        return true;
    };
    window.__testComparisonClick = window.__testHighlightClick;
    window.__testComparisonState = function () {
        return { count: highlightedIds.size, ids: Array.from(highlightedIds), periods: Array.from(highlightedIds) };
    };
    window.__testHighlightState = window.__testComparisonState;
}
