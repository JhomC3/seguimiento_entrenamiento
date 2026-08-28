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

// --- TAREA 3: comparación de puntos ---
const COMPARISON_MAX = 8;
let selectedComparison = []; // orden de selección
let clickTimer = null;
let lastFigData = null;
const _comparisonBound = new WeakSet();

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

const MESES_CORTO_JS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];

function formatDayShortJS(isoDate, allDates) {
    try {
        const s = String(isoDate);
        const parts = s.split("-");
        if (parts.length < 3) return s;
        const y = parts[0], m = parseInt(parts[1],10), d = parseInt(parts[2],10);
        const mes = MESES_CORTO_JS[m-1] || parts[1];
        let base = `${d} ${mes}`;
        if (Array.isArray(allDates)) {
            const years = new Set(allDates.map(v => String(v).split("-")[0]));
            if (years.size > 1) base += ` ${y.slice(2)}`;
        }
        return base;
    } catch (_) { return String(isoDate); }
}
function formatWeekShortJS(semana) {
    const n = parseInt(String(semana).trim(), 10);
    return Number.isFinite(n) ? `S${n}` : `S${semana}`;
}
function formatMonthShortJS(periodo) {
    try {
        const s = String(periodo).trim();
        const parts = s.split("-");
        const y = parseInt(parts[0],10), m = parseInt(parts[1],10);
        const mes = MESES_CORTO_JS[m-1] || parts[1];
        return `${mes} ${String(y).slice(2)}`;
    } catch (_) { return String(periodo); }
}
function getCurrentGranularity() {
    const sel = document.querySelector('#granularity-selector [data-gran][aria-pressed="true"]');
    return sel ? sel.dataset.gran : 'week';
}
function formatPeriodoCompact(periodoRaw, granularity, allX) {
    if (granularity === 'day') return formatDayShortJS(periodoRaw, allX);
    if (granularity === 'week') return formatWeekShortJS(periodoRaw);
    if (granularity === 'month') return formatMonthShortJS(periodoRaw);
    return String(periodoRaw);
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
function pointComparisonIdJS(granularity, periodo, traceName) {
    return `${String(granularity).toLowerCase()}|${String(periodo)}|${String(traceName).trim().toLowerCase()}`;
}
function getAllXForGranularity() {
    const plotEl = document.getElementById('unified-chart-plot');
    if (!plotEl || !Array.isArray(plotEl._fullData)) return null;
    const xs = [];
    plotEl._fullData.forEach(t => {
        if (t.x && typeof t.x.length === 'number') {
            // x puede ser Array o TypedArray (Int8Array) serializado por Plotly
            for (let i = 0; i < t.x.length; i++) xs.push(t.x[i]);
        }
    });
    return xs;
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

function renderComparisonPanel() {
    const wrap = document.getElementById('period-summary-wrap');
    if (!wrap) return;
    const content = document.getElementById('ps-content');
    const comp = document.getElementById('ps-comparison');
    const live = document.getElementById('ps-comparison-live');
    if (!content || !comp) return;
    if (selectedComparison.length === 0) {
        content.hidden = false;
        comp.hidden = true;
        comp.setAttribute('aria-hidden', 'true');
        if (live) live.textContent = '';
        return;
    }
    content.hidden = true;
    comp.hidden = false;
    comp.removeAttribute('aria-hidden');
    if (live) live.textContent = `${selectedComparison.length} punto${selectedComparison.length>1?'s':''} seleccionado${selectedComparison.length>1?'s':''}`;
    const tbody = comp.querySelector('tbody');
    if (!tbody) return;
    // Limpiar filas existentes de forma segura
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    selectedComparison.forEach(function (rec, idx) {
        const tr = document.createElement('tr');
        tr.className = idx === 0 ? 'ps-comparison-row is-base' : 'ps-comparison-row';
        if (idx === 0) tr.setAttribute('aria-label', 'Base');
        // Periodo
        const th = document.createElement('th');
        th.scope = 'row';
        const badge = document.createElement('span');
        if (idx === 0) {
            badge.className = 'ps-badge';
            badge.textContent = 'Base';
            th.appendChild(badge);
            th.appendChild(document.createTextNode(' ' + rec.periodShort));
        } else {
            const label = document.createElement('span');
            label.className = 'ps-compare-label';
            label.textContent = `Comparado ${idx+1}`;
            // No solo color: etiqueta textual visible
            label.setAttribute('aria-hidden', 'true');
            th.appendChild(label);
            th.appendChild(document.createTextNode(' ' + rec.periodShort));
            tr.setAttribute('aria-label', `Comparado ${idx+1} ${rec.periodShort}`);
        }
        if (idx===0) tr.setAttribute('aria-label', `Base ${rec.periodShort}`);
        tr.appendChild(th);
        // Columnas en orden: VAR | Series | Reps | Peso | RIR | RM aj.
        const cols = [rec.delta, rec.series, rec.reps, rec.peso, rec.rir, rec.rm];
        cols.forEach(function (val) {
            const td = document.createElement('td');
            td.className = 'num';
            td.textContent = val || '—';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function applyHighlight() {
    const plotEl = document.getElementById('unified-chart-plot');
    if (!plotEl || !plotEl._fullData) return;
    const Plotly = window.Plotly;
    if (!Plotly) return;
    // Construir selectedpoints por traza
    const perTrace = {};
    selectedComparison.forEach(function (rec) {
        const key = rec.curveNumber;
        if (!(key in perTrace)) perTrace[key] = [];
        perTrace[key].push(rec.pointNumber);
    });
    // Aplicar por traza: usar restyle con marker.size/line para halo visible en oscuro
    // Guardamos tamaños originales en _originalMarker si no existe
    if (!plotEl._originalMarker) {
        plotEl._originalMarker = plotEl._fullData.map(function (t) {
            return {
                size: t.marker && t.marker.size,
                color: t.marker && t.marker.color,
                lineWidth: t.marker && t.marker.line && t.marker.line.width,
                lineColor: t.marker && t.marker.line && t.marker.line.color,
            };
        });
    }
    const nTraces = plotEl._fullData.length;
    for (let i = 0; i < nTraces; i++) {
        const sel = perTrace[i] || null;
        if (sel && sel.length) {
            // Aumentar tamaño y borde para seleccionados
            // Construir arrays de tamaño por punto
            const trace = plotEl._fullData[i];
            const nPoints = trace.x && typeof trace.x.length === 'number' ? trace.x.length : 0;
            const sizes = new Array(nPoints);
            const lineWidths = new Array(nPoints);
            const lineColors = new Array(nPoints);
            const baseSize = 3;
            const selSize = 10;
            // Color canónico: --t-detail-white (src/design_tokens.py) resuelto vía CSS, sin hex literal
            let detailWhite = '';
            try {
                detailWhite = getComputedStyle(document.documentElement).getPropertyValue('--t-detail-white').trim()
                    || getComputedStyle(document.documentElement).getPropertyValue('--t-chart-hover-text').trim();
            } catch (_) {}
            if (!detailWhite) detailWhite = 'white';
            for (let p = 0; p < nPoints; p++) {
                if (sel.indexOf(p) !== -1) {
                    sizes[p] = selSize;
                    lineWidths[p] = 2;
                    lineColors[p] = detailWhite;
                } else {
                    sizes[p] = baseSize;
                    lineWidths[p] = 0;
                    lineColors[p] = 'rgba(0,0,0,0)';
                }
            }
            try {
                Plotly.restyle(plotEl, {
                    'marker.size': [sizes],
                    'marker.line.width': [lineWidths],
                    'marker.line.color': [lineColors],
                }, [i]);
            } catch (_) {}
        } else {
            // Restaurar traza no seleccionada
            const orig = plotEl._originalMarker[i];
            if (orig) {
                try {
                    Plotly.restyle(plotEl, {
                        'marker.size': [orig.size],
                        'marker.line.width': [orig.lineWidth || 0],
                        'marker.line.color': [orig.lineColor || 'rgba(0,0,0,0)'],
                    }, [i]);
                } catch (_) {}
            }
        }
    }
}

function clearComparison(opts) {
    const silent = opts && opts.silent;
    selectedComparison = [];
    renderComparisonPanel();
    hideTooltip();
    const plotEl = document.getElementById('unified-chart-plot');
    if (plotEl && plotEl._fullData && window.Plotly) {
        // Restaurar marcadores originales
        if (plotEl._originalMarker) {
            plotEl._fullData.forEach(function (_, i) {
                const orig = plotEl._originalMarker[i];
                if (!orig) return;
                try {
                    window.Plotly.restyle(plotEl, {
                        'marker.size': [orig.size],
                        'marker.line.width': [orig.lineWidth || 0],
                        'marker.line.color': [orig.lineColor || 'rgba(0,0,0,0)'],
                    }, [i]);
                } catch (_) {}
            });
        }
    }
    if (!silent) {
        const live = document.getElementById('ps-comparison-live');
        if (live) live.textContent = 'Comparación limpiada';
    }
}

function handlePointSelection(pointData, shiftKey) {
    if (!pointData || !pointData.points || !pointData.points.length) return;
    const pt = pointData.points[0];
    const customdata = pt.customdata;
    const vals = extractPointValuesJS(customdata);
    if (!vals) return;
    const plotEl = document.getElementById('unified-chart-plot');
    const granularity = getCurrentGranularity();
    // El identificador único incluye granularidad + periodo (x) + traza
    const xRaw = String(pt.x);
    const traceName = String(pt.data ? pt.data.name : vals.trace);
    const id = pointComparisonIdJS(granularity, xRaw, traceName);
    const allX = getAllXForGranularity();
    const periodShort = formatPeriodoCompact(xRaw, granularity, allX);
    const rec = {
        id: id,
        traceName: traceName,
        granularity: granularity,
        xRaw: xRaw,
        periodShort: periodShort,
        delta: vals.delta,
        series: vals.series,
        reps: vals.reps,
        peso: vals.peso,
        rir: vals.rir,
        rm: vals.rm,
        curveNumber: pt.curveNumber,
        pointNumber: pt.pointNumber,
    };
    if (!shiftKey) {
        selectedComparison = [rec];
    } else {
        const idx = selectedComparison.findIndex(r => r.id === id);
        if (idx !== -1) {
            selectedComparison.splice(idx, 1);
            if (selectedComparison.length === 0) {
                clearComparison();
                return;
            }
        } else {
            if (selectedComparison.length >= COMPARISON_MAX) return;
            selectedComparison.push(rec);
        }
    }
    renderComparisonPanel();
    applyHighlight();
}

function bindComparison(plotEl) {
    if (_comparisonBound.has(plotEl)) return;
    // plotly_click con debounce para doble-clic (200-250ms)
    plotEl.on('plotly_click', function (data) {
        // Si hay timer pendiente, es segundo clic dentro de ventana -> doble clic
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
            // Doble clic: abrir editor/detalle existente si aplica (conservar funcionalidad)
            // Si el flujo actual no abre editor, no hacer nada extra
            const point = data.points && data.points[0];
            if (point && point.x) {
                // Intentar disparar acción existente de doble clic si está definida
                // Por ahora no hay acción de clic simple, así que no inventamos.
                // Solo limpiamos el highlight? No, doble clic debe conservar comparación?
                // Spec: doble clic conserva acción existente, no limpia comparación automáticamente
            }
            return;
        }
        // Guardar evento para posible single-click tras timeout
        const shiftKey = data.event ? !!data.event.shiftKey : false;
        // Necesitamos capturar shiftKey del evento original
        clickTimer = setTimeout(function () {
            clickTimer = null;
            handlePointSelection(data, shiftKey);
        }, 220);
    });
    // Escuchar doble clic nativo para cancelar single
    plotEl.on('plotly_doubleclick', function () {
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
        }
    });
    _comparisonBound.add(plotEl);
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
        if (selectedComparison.length) clearComparison({silent:true});
        hideTooltip();
        return;
    }

    // Si hay comparación activa y llega nueva figura (OOB), limpiar (spec: eliminar al actualizar vía OOB)
    if (selectedComparison.length) {
        try {
            const newSig = JSON.stringify(fig.data.map(t => t.name).sort());
            const oldSig = lastFigData ? JSON.stringify(lastFigData.map(t => t.name).sort()) : null;
            if (oldSig !== null) {
                clearComparison({silent:true});
            }
        } catch (_) {}
    }
    try {
        lastFigData = fig.data.map(t => ({
            name: t.name,
            x: Array.isArray(t.x) ? t.x.slice(0, 2) : (t.x ? [String(t.x).slice(0,2)] : []),
        }));
    } catch (_) {
        lastFigData = fig.data.map(t => ({name: t.name, x: []}));
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
            plotEl.setAttribute('aria-describedby', 'ps-comparison-desc');
            if (!_relayoutBound.has(plotEl)) {
                plotEl.on('plotly_relayout', function (e) {
                    // El rango Y se deja libre para que el pan con clic
                    // sostenido funcione tanto vertical como horizontalmente.
                });
                _relayoutBound.add(plotEl);
            }
            bindHorizontalWheel(plotEl, Plotly);
            bindComparison(plotEl);
            bindTooltip(plotEl, Plotly);
            // Restaurar highlight si aún hay selección (p. ej. tras resize)
            if (selectedComparison.length) {
                applyHighlight();
                renderComparisonPanel();
            }
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
    // Escape limpia comparación (si gráfica o panel tienen foco, o global)
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (selectedComparison.length === 0) return;
        const active = document.activeElement;
        const inChart = active && active.closest && active.closest('#unified-chart-plot');
        const inPanel = active && active.closest && active.closest('#period-summary-wrap');
        const inBody = !inChart && !inPanel;
        // Si hay drawer móvil abierto, dejar que level-cascade lo maneje primero
        const drawerOpen = document.querySelector('.dashboard-page') && !document.querySelector('.dashboard-page').classList.contains('is-catalog-collapsed') && window.matchMedia('(max-width: 1023px)').matches;
        if (drawerOpen) return;
        // Limpiar comparación
        e.preventDefault();
        clearComparison();
    });
    // Limpiar comparación cuando el panel es reemplazado vía OOB (cambio de selección/ventana)
    document.body.addEventListener('htmx:oobAfterSwap', function (e) {
        if (e.detail.target && e.detail.target.id === 'period-summary-wrap') {
            // Si el swap vino de /grafica, renderUnifiedChart ya limpió; si es otro OOB, asegurar
            // que el DOM de comparación se re-crea (el nuevo panel no tiene #ps-comparison poblado)
            // Mantener comportamiento: cualquier OOB limpia selección previa
            if (selectedComparison.length) clearComparison({silent:true});
            // Re-render del panel vacío se hará en próximo ciclo; asegurar que live region existe
        }
    });
    // Exponer para level-cascade (cambios de granularidad/selección/ventana)
    window.clearChartComparison = clearComparison;
    window.getChartComparison = function () { return selectedComparison.slice(); };
    // Helpers para tests E2E (simulan clic sin depender de coordenadas SVG)
    window.__testComparisonClick = function (traceIdx, pointIdx, shiftKey) {
        const plotEl = document.getElementById('unified-chart-plot');
        if (!plotEl || !Array.isArray(plotEl._fullData)) return false;
        const trace = plotEl._fullData[traceIdx];
        if (!trace || !trace.x || typeof trace.x.length !== 'number' || !Array.isArray(trace.customdata)) return false;
        const cd = trace.customdata[pointIdx];
        const x = trace.x[pointIdx];
        if (cd === undefined || x === undefined) return false;
        const pt = {x: x, customdata: cd, curveNumber: traceIdx, pointNumber: pointIdx, data: trace};
        // Simular estructura de plotly_click
        handlePointSelection({points: [pt]}, !!shiftKey);
        return true;
    };
    window.__testComparisonState = function () {
        return {
            count: selectedComparison.length,
            ids: selectedComparison.map(r => r.id),
            periods: selectedComparison.map(r => r.periodShort),
        };
    };
}
