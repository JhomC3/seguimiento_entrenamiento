// chart-interaction.js — owns: unified chart rendering and day-click.// DOM owned: #unified-chart (reads #unified-chart-data JSON, renders into the
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

function positionTooltip(clientX, clientY, plotTop) {
    const el = _tooltipEl;
    if (!el) return;
    const pad = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // Izquierda del cursor; arriba fijo de la gráfica (no sigue al punto).
    const rect = el.getBoundingClientRect();
    let left = clientX - rect.width - 14;
    let top = (typeof plotTop === 'number' && Number.isFinite(plotTop))
        ? plotTop + 12
        : clientY + 14;
    if (left < pad) left = clientX + 14;
    if (left + rect.width + pad > vw) left = Math.max(pad, vw - rect.width - pad);
    if (top + rect.height + pad > vh) top = Math.max(pad, vh - rect.height - pad);
    if (top < pad) top = pad;
    el.style.left = left + 'px';
    el.style.top = top + 'px';
}

// Contrato nutricional (4 pos.): [etiqueta, kcal_txt, peso_txt, traza].
// La fecha vive SOLO en la cabecera; los bloques no repiten la x.
function extractNutritionValuesJS(customdata) {
    if (!Array.isArray(customdata) || customdata.length !== 4) return null;
    try {
        return {
            periodo: String(customdata[0]),
            kcal: String(customdata[1]),
            peso: String(customdata[2]),
            trace: String(customdata[3]),
        };
    } catch (_) { return null; }
}

// Contrato salud (2 pos., aditivo): [etiqueta, "valor unidad"]. Una fila por
// punto con el nombre de la traza como etiqueta (nunca inventa formato).
function extractHealthValuesJS(customdata) {
    if (!Array.isArray(customdata) || customdata.length !== 2) return null;
    try {
        return {
            periodo: String(customdata[0]),
            texto: String(customdata[1]),
        };
    } catch (_) { return null; }
}

function tooltipRowsFor(pt) {
    const vals = extractPointValuesJS(pt.customdata);
    if (vals && vals.trace === 'RIR') {
        // La traza RIR solo aporta su valor: bloque compacto de una fila,
        // sin las filas vacías de Series/VAR/Reps/Peso/RM.
        return {trace: vals.trace, single: true, rows: [['RIR', vals.rir]]};
    }
    if (vals) {
        // Orden UX-2: Series, VAR, Reps, Peso, RIR, RM (sin Cobertura)
        return {
            trace: vals.trace,
            rows: [
                ['Series', vals.series],
                ['VAR', vals.delta],
                ['Reps', vals.reps],
                ['Peso', vals.peso],
                ['RIR', vals.rir],
                ['RM', vals.rm],
            ],
        };
    }
    const nut = extractNutritionValuesJS(pt.customdata);
    if (nut) {
        const isPeso = nut.trace === 'peso';
        return {
            trace: nut.trace,
            // Bloque de una sola fila: sin cabecera de traza (duplicaría la
            // etiqueta, que ya va en mayúsculas por CSS como en la principal).
            single: true,
            rows: isPeso ? [['peso', nut.peso === '—' ? '—' : nut.peso + ' kg']] : [['kcal', nut.kcal]],
        };
    }
    const health = extractHealthValuesJS(pt.customdata);
    if (health) {
        const name = (pt.data && pt.data.name) || 'Salud';
        return { trace: name, single: true, rows: [[name, health.texto]] };
    }
    return null;
}

function tooltipHeaderFor(points) {
    const first = points[0];
    const vals = extractPointValuesJS(first.customdata) || extractNutritionValuesJS(first.customdata) ||
        extractHealthValuesJS(first.customdata);
    return vals ? vals.periodo : String(first.x);
}

function buildTooltipContent(points) {
    if (!points || !points.length) return null;
    // Header único: primera traza, customdata[0] ya viene formateado por backend
    // (día "18 jul" / "18 jul 2026", semana "18 jul 2026", mes "julio 2026")
    // No repetir por bloque, no usar "S1"/"Semana 1" ni ISO.
    const header = tooltipHeaderFor(points);
    const body = document.createDocumentFragment();
    const headerEl = document.createElement('div');
    headerEl.className = 'chart-tooltip__header';
    headerEl.textContent = header;
    body.appendChild(headerEl);
    const wrap = document.createElement('div');
    wrap.className = 'chart-tooltip__body';
    points.forEach(function (pt, idx) {
        const shaped = tooltipRowsFor(pt);
        if (!shaped) return;
        if (idx > 0) {
            const div = document.createElement('div');
            div.className = 'chart-tooltip__divider';
            div.setAttribute('aria-hidden', 'true');
            wrap.appendChild(div);
        }
        const block = document.createElement('div');
        block.className = 'chart-tooltip__block';
        const traceName = shaped.trace || (pt.data && pt.data.name) || '';
        const swatchColor = (pt.data && (pt.data.line && pt.data.line.color || pt.data.marker && pt.data.marker.color)) || '';
        block.setAttribute('role', 'group');
        if (traceName) block.setAttribute('aria-label', traceName);
        if (!shaped.single) {
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
        }
        // Bloque de una fila (nutrición): sin cabecera de traza, el swatch va
        // junto a la etiqueta para no duplicarla (va en mayúsculas por CSS).
        const rows = shaped.rows;
        rows.forEach(function (pair, rowIdx) {
            const label = pair[0], value = pair[1];
            const row = document.createElement('div');
            row.className = 'chart-tooltip__row';
            const lab = document.createElement('span');
            lab.className = 'chart-tooltip__label';
            if (shaped.single && rowIdx === 0) {
                const dot = document.createElement('span');
                dot.className = 'chart-tooltip__swatch';
                dot.setAttribute('aria-hidden', 'true');
                dot.style.background = swatchColor || 'var(--t-chart-primary)';
                dot.style.display = 'inline-block';
                dot.style.marginRight = '6px';
                lab.appendChild(dot);
            }
            lab.appendChild(document.createTextNode(label));
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

function showTooltip(evt, plotEl) {
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
    positionTooltip(x, y, plotEl ? plotEl.getBoundingClientRect().top : null);
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
        showTooltip(data, plotEl);
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

export function renderPlotFromIds(dataId, plotId, emptyId, opts) {
    const dataEl = document.getElementById(dataId);
    const plotEl = document.getElementById(plotId);
    const emptyEl = emptyId ? document.getElementById(emptyId) : null;
    const useTooltip = !opts || opts.tooltip !== false;
    const useHighlight = !opts || opts.highlight !== false;
    if (!dataEl || !plotEl) return Promise.resolve(false);

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
        if (useHighlight) {
            clearChartHighlight({silent:true});
            closeAllDetails();
        }
        if (useTooltip) hideTooltip();
        return Promise.resolve(false);
    }

    // Nueva figura OOB: limpiar highlight previo (puntos ya no pertenecen)
    if (useHighlight) {
        clearChartHighlight({silent:true});
        closeAllDetails();
    }

    // Data state: hide empty div, show plot, react.
    if (emptyEl) emptyEl.hidden = true;
    plotEl.hidden = false;

    // TradingView: zoom y pan exclusivamente horizontal.
    return loadPlotly()
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
            if (useTooltip) {
                // UX-2: suprimir tooltip nativo y conservar eventos (ambas
                // gráficas sirven customdata para el tooltip cristal propio).
                fig.data.forEach(function (t) {
                    t.hoverinfo = 'none';
                    t.hovertemplate = null;
                });
            }
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
            // Accesibilidad: el plot es focuseable (foco visible en CSS) y los
            // valores se consultan en el panel Historial (el tooltip es hover-only).
            const label = plotId === 'nutrition-trend-plot'
                ? 'Gráfica de nutrición: media de 7 días de calorías y peso corporal.'
                : 'Gráfica de rendimiento. Consulta los valores por periodo en el panel Historial.';
            plotEl.setAttribute('aria-label', label);
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
            if (useHighlight) bindHighlight(plotEl);
            if (useTooltip) bindTooltip(plotEl, Plotly);
            return true;
        })
        .catch(function (err) {
            showChartError(err && err.message ? err.message : 'Error al renderizar la gráfica.');
            return false;
        });
}

export function renderUnifiedChart() {
    const p = renderPlotFromIds('unified-chart-data', 'unified-chart-plot', 'unified-chart-empty');
    if (p && typeof p.then === 'function') {
        p.then(function (ok) {
            const plotEl = document.getElementById('unified-chart-plot');
            if (!plotEl) return;
            if (ok && window.Plotly) {
                bindAxisAnchor(plotEl, 'nutrition-trend-plot', window.Plotly);
            }
            maybeAlignMetricsToUnified(window.Plotly);
        });
    }
}

// --- Catálogo de métricas ---
export function getMetricsSelection() {
    return [...document.querySelectorAll('#metrics-catalog [data-metric][aria-pressed="true"]')]
        .map(function (b) { return b.dataset.metric; });
}

function applyMetricsVisibility(keys) {
    // El slot es el de nutrition-trend (ids reutilizados a propósito).
    // OJO: Plotly.restyle reconstruye _fullData y las trazas pierden `meta`;
    // el mapa key→índice se lee siempre de el.data (estable), nunca de _fullData.
    const plotEl = document.getElementById('nutrition-trend-plot');
    if (!plotEl || !plotEl._fullData || !window.Plotly) return;
    const metas = plotEl.data.map(function (t) { return t.meta; });
    window.Plotly.restyle(plotEl, {
        visible: plotEl._fullData.map(function (_, i) { return keys.indexOf(metas[i]) >= 0; }),
    });
}

export function setMetricsSelection(keys, opts) {
    const pushUrl = !opts || opts.pushUrl !== false;
    const chips = [...document.querySelectorAll('#metrics-catalog [data-metric]')];
    const valid = chips.filter(function (b) { return b.getAttribute('aria-disabled') !== 'true'; })
        .map(function (b) { return b.dataset.metric; });
    const wanted = (keys || []).filter(function (k) { return valid.indexOf(k) >= 0; });
    chips.forEach(function (b) {
        if (b.getAttribute('aria-disabled') === 'true') return;
        b.setAttribute('aria-pressed', String(wanted.indexOf(b.dataset.metric) >= 0));
    });
    applyMetricsVisibility(wanted);
    if (pushUrl) {
        document.dispatchEvent(new CustomEvent('metrics:change', { detail: { keys: wanted } }));
    }
}

export function toggleMetric(key) {
    const btn = document.querySelector('#metrics-catalog [data-metric="' + CSS.escape(key) + '"]');
    if (!btn || btn.getAttribute('aria-disabled') === 'true') return;
    const selected = getMetricsSelection();
    const i = selected.indexOf(key);
    if (i >= 0) selected.splice(i, 1);
    else selected.push(key);
    setMetricsSelection(selected);
}

export function initMetricsCatalog() {
    document.addEventListener('click', function (e) {
        const btn = e.target && e.target.closest ? e.target.closest('[data-action="toggle-metric"]') : null;
        if (btn && btn.dataset.metric) {
            toggleMetric(btn.dataset.metric);
            return;
        }
        const grp = e.target && e.target.closest ? e.target.closest('[data-action="toggle-metric-group"]') : null;
        if (grp) toggleMetricGroup(grp);
    });
}

export function toggleMetricGroup(btn) {
    const section = btn.closest ? btn.closest('section.db-group') : null;
    const panel = section ? section.querySelector('.db-exercise-list') : null;
    if (!panel) return;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', String(open));
    const label = btn.dataset.mgroup || 'grupo';
    btn.setAttribute('aria-label', (open ? 'Contraer ' : 'Expandir ') + label);
    panel.hidden = !open;
}

export function renderNutritionTrend() {
    const dataEl = document.getElementById('nutrition-trend-data');
    if (!dataEl) return;
    // Mismo tooltip cristal que la principal; highlight desactivado: el clic
    // no cambia (la de métricas es solo visualización).
    const p = renderPlotFromIds('nutrition-trend-data', 'nutrition-trend-plot', 'nutrition-trend-empty', {
        tooltip: true,
        highlight: false,
    });
    if (p && typeof p.then === 'function') {
        p.then(function (ok) {
            const plotEl = document.getElementById('nutrition-trend-plot');
            if (!plotEl) return;
            if (ok && window.Plotly) {
                bindAxisAnchor(plotEl, 'unified-chart-plot', window.Plotly);
            }
            maybeAlignMetricsToUnified(window.Plotly);
        });
    }
}

// --- Anclaje temporal métricas ↔ ejercicios (solo cliente) ---
//
// El servidor NUNCA fuerza rango en la figura de ejercicios (regresión
// verificada: rompe la preservación uirevision del zoom manual). Alineado
// first-paint + propagación de gestos, todo aquí. Eje Y siempre local.
// "Agrupar" = granularidad (servidor, ambas vía /grafica) o zoom-in por gesto.

let manualXRange = false; // rango X manual vigente (gesto real, no eco)
const _anchorBound = new WeakSet();
const _lastAppliedRange = new WeakMap(); // plotEl -> [r0, r1] eco a ignorar
const _autoApplied = new WeakSet(); // plotEl con autorange propagado pendiente

export function resetAnchorRegime() {
    // Granularidad nueva = régimen nuevo (los OOB traen sus iniciales).
    manualXRange = false;
}

function traceXKind(xs) {
    const s0 = String(xs[0]);
    if (/^\d{4}-\d{2}-\d{2}/.test(s0)) return 'date';
    if (/^\d{4}-\d{2}$/.test(s0)) return 'category';
    return 'linear';
}

function xToNum(kind, v) {
    if (kind === 'date') {
        const n = Date.parse(String(v));
        return Number.isFinite(n) ? n : Number(v);
    }
    return Number(v);
}

export function plotXDomain(plotEl) {
    // Unión de todas las trazas con x: {kind, lo, hi, labels|null}. Pura.
    let kind = null;
    let labels = null;
    let nums = [];
    (plotEl._fullData || []).forEach(function (t) {
        if (!Array.isArray(t.x) || !t.x.length) return;
        const k = traceXKind(t.x);
        if (!kind) {
            kind = k;
            if (k === 'category') labels = t.x.map(String);
        }
        if (k !== kind) return;
        t.x.forEach(function (v) {
            if (k === 'category') {
                const i = labels.indexOf(String(v));
                if (i >= 0) nums.push(i);
            } else {
                const n = xToNum(k, v);
                if (Number.isFinite(n)) nums.push(n);
            }
        });
    });
    if (!kind || !nums.length) return null;
    return { kind: kind, lo: Math.min.apply(null, nums), hi: Math.max.apply(null, nums), labels: labels };
}

export function currentXRange(plotEl) {
    // Rango X actual en números de dominio (o índices si category), o null. Pura.
    const dom = plotXDomain(plotEl);
    if (!dom || !(dom.hi > dom.lo)) return null;
    const layout = plotEl._fullLayout && plotEl._fullLayout.xaxis;
    const r = layout && layout.range;
    if (!Array.isArray(r) || r.length < 2) return [dom.lo, dom.hi];
    if (dom.kind === 'category') {
        const i0 = dom.labels.indexOf(String(r[0]));
        const i1 = dom.labels.indexOf(String(r[1]));
        if (i0 < 0 || i1 < 0) return [0, dom.labels.length - 1];
        return [Math.min(i0, i1), Math.max(i0, i1)];
    }
    const n0 = xToNum(dom.kind, r[0]);
    const n1 = xToNum(dom.kind, r[1]);
    if (!Number.isFinite(n0) || !Number.isFinite(n1)) return [dom.lo, dom.hi];
    return [Math.min(n0, n1), Math.max(n0, n1)];
}

export function fractionsOf(dom, r0, r1) {
    // Fracciones [f0, f1] de un rango sobre su dominio. Pura.
    return [(r0 - dom.lo) / (dom.hi - dom.lo), (r1 - dom.lo) / (dom.hi - dom.lo)];
}

function sameRange(a, b) {
    if (!a || !b) return false;
    return a.every(function (v, i) {
        if (typeof v === 'number' && typeof b[i] === 'number') return Math.abs(v - b[i]) < 1e-9;
        return String(v) === String(b[i]);
    });
}

function applyXFractions(plotEl, Plotly, f0, f1) {
    const dom = plotXDomain(plotEl);
    if (!dom || !(dom.hi > dom.lo)) return false;
    let r0;
    let r1;
    if (dom.kind === 'category') {
        const n = dom.labels.length;
        const i0 = Math.min(n - 1, Math.max(0, Math.round(f0 * (n - 1))));
        const i1 = Math.min(n - 1, Math.max(0, Math.round(f1 * (n - 1))));
        r0 = dom.labels[Math.min(i0, i1)];
        r1 = dom.labels[Math.max(i0, i1)];
    } else {
        r0 = dom.lo + f0 * (dom.hi - dom.lo);
        r1 = dom.lo + f1 * (dom.hi - dom.lo);
    }
    _lastAppliedRange.set(plotEl, [r0, r1]);
    Plotly.relayout(plotEl, { 'xaxis.range[0]': r0, 'xaxis.range[1]': r1 });
    return true;
}

function maybeAlignMetricsToUnified(Plotly) {
    // Sin manual: métricas adopta la ventana de ejercicios. Con manual no se
    // toca nada (uirevision lo conserva y la propagación en vivo ya alineó).
    // No-op si alguna gráfica está vacía.
    if (!Plotly || manualXRange) return;
    const a = document.getElementById('unified-chart-plot');
    const b = document.getElementById('nutrition-trend-plot');
    if (!a || !b || !a._fullData || !b._fullData) return;
    const ra = currentXRange(a);
    const domA = plotXDomain(a);
    if (!ra || !domA || !(domA.hi > domA.lo)) return;
    const span = domA.hi - domA.lo;
    applyXFractions(b, Plotly, (ra[0] - domA.lo) / span, (ra[1] - domA.lo) / span);
}

function anchorRelayout(plotEl, otherId, Plotly, e) {
    const echo = _lastAppliedRange.get(plotEl);
    if (echo) {
        const cur = currentXRange(plotEl);
        _lastAppliedRange.delete(plotEl);
        if (sameRange(cur, echo)) return; // eco de nuestra propia propagación
    }
    if (_autoApplied.has(plotEl)) {
        _autoApplied.delete(plotEl);
        return; // eco de autorange propagado
    }
    const other = document.getElementById(otherId);
    if (!other || !other._fullData) return;
    if (e && e['xaxis.autorange'] === true) {
        manualXRange = false;
        _autoApplied.add(other);
        Plotly.relayout(other, { 'xaxis.autorange': true });
        return;
    }
    if (!e || e['xaxis.range[0]'] === undefined || e['xaxis.range[1]'] === undefined) return;
    const dom = plotXDomain(plotEl);
    if (!dom || !(dom.hi > dom.lo)) return;
    let n0;
    let n1;
    if (dom.kind === 'category') {
        const i0 = dom.labels.indexOf(String(e['xaxis.range[0]']));
        const i1 = dom.labels.indexOf(String(e['xaxis.range[1]']));
        if (i0 < 0 || i1 < 0) return;
        n0 = Math.min(i0, i1);
        n1 = Math.max(i0, i1);
    } else {
        n0 = xToNum(dom.kind, e['xaxis.range[0]']);
        n1 = xToNum(dom.kind, e['xaxis.range[1]']);
        if (!Number.isFinite(n0) || !Number.isFinite(n1)) return;
    }
    manualXRange = true;
    const f = fractionsOf(dom, Math.min(n0, n1), Math.max(n0, n1));
    applyXFractions(other, Plotly, f[0], f[1]);
}

function bindAxisAnchor(plotEl, otherId, Plotly) {
    if (_anchorBound.has(plotEl)) return;
    _anchorBound.add(plotEl);
    plotEl.on('plotly_relayout', function (e) {
        anchorRelayout(plotEl, otherId, Plotly, e || {});
    });
}

export function initChartInteractions() {
    // Render after every successful /grafica request: by afterRequest time the
    // OOB swaps have been applied to the DOM (afterSwap does not fire for OOB
    // elements when the main swap is 'none'). Stale protection lives in
    // level-cascade.js (cancelPending aborts in-flight /grafica requests).
    // La tendencia nutricional viaja en la MISMA respuesta: se renderiza junta.
    document.body.addEventListener('htmx:afterRequest', function (e) {
        const req = e.detail && e.detail.requestConfig;
        const path = req && req.path;
        if (path && path.startsWith('/grafica') && e.detail.successful) {
            renderUnifiedChart();
            renderNutritionTrend();
        }
    });
    document.body.addEventListener('htmx:oobAfterSwap', function (e) {
        if (e.detail.target && e.detail.target.id === 'nutrition-trend-data') {
            renderNutritionTrend();
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
