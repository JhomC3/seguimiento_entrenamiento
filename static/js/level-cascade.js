// level-cascade.js — cascada del catálogo izquierdo + gráfica + panel derecho.
// Owns: #dashboard-catalog (cabeceras con selección de músculo y control
// independiente de expansión + botones de ejercicio), estado de selección
// (músculos/ejercicios), #unified-chart vía /grafica y #period-summary-wrap
// (resumen periódico, misma respuesta que la gráfica; pestañas locales).
// DEPRECATED (Fase 3): #history-section y /nivel?tipo=ejercicio ya sin caller;
// el stub oculto y la ruta se retiran cuando audit_ui/E2E migren.
// Cada paso empuja historial (?musculos=A,B&ejercicios=a,b) y popstate restaura.

let selectedMuscles = new Set();
let selectedExercises = new Set();

import { getMetricsSelection, setMetricsSelection } from './chart-interaction.js';

// Métricas: la URL manda (pushState centralizado aquí).
document.addEventListener('metrics:change', function () {
    pushState(currentUrl());
});

// Per-resource sequence counters for stale-response veto.
const seqs = { chart: 0, detail: 0 };

const PATH_TYPES = [
    { type: 'chart', prefix: '/grafica' },
    { type: 'detail', prefix: '/nivel?tipo=ejercicio' },
];

function seqType(path) {
    for (const t of PATH_TYPES) {
        if (path.startsWith(t.prefix)) return t.type;
    }
    return null;
}

// Cancela requests htmx en vuelo de la cascada (evita que una respuesta vieja
// sobrescriba el estado tras un toggle rápido o Escape).
let pendingXhrs = new Set();
function trackXhr(e) {
    const path = e.detail && e.detail.requestConfig && e.detail.requestConfig.path;
    if (!path) return;
    // TODO(Fase 3): retirar '/nivel' cuando la ruta deprecada se elimine.
    if (path.startsWith('/nivel') || path.startsWith('/grafica')) {
        const xhr = e.detail.xhr;
        xhr._cascadePath = path;
        pendingXhrs.add(xhr);
        xhr.addEventListener('loadend', () => pendingXhrs.delete(xhr));
    }
}
function cancelPending(pathPrefix) {
    pendingXhrs.forEach((xhr) => {
        const path = xhr._cascadePath || '';
        if (xhr.readyState < 4 && (!pathPrefix || path.startsWith(pathPrefix))) {
            xhr.abort();
        }
    });
    if (!pathPrefix) pendingXhrs.clear();
}

function stampSeq(e) {
    const xhr = e.detail && e.detail.xhr;
    const path = e.detail && e.detail.requestConfig && e.detail.requestConfig.path;
    const type = path ? seqType(path) : null;
    if (xhr && type) {
        xhr._seq = ++seqs[type];
    }
}

function pushState(url) {
    history.pushState({}, '', url);
}

function currentUrl() {
    const params = new URLSearchParams();
    params.append('musculos', [...selectedMuscles].sort().join(','));
    if (selectedExercises.size) params.append('ejercicios', [...selectedExercises].sort().join(','));
    params.set('gran', getGranularity());
    params.set('metricas', getMetricsSelection().join(','));
    const q = params.toString();
    return q ? '?' + q : '/';
}

function openGroup(name, open) {
    const grp = document.querySelector(`#dashboard-catalog .db-group[data-group="${CSS.escape(name)}"]`);
    if (!grp) return;
    const toggle = grp.querySelector('[data-action="toggle-group"]');
    const panel = grp.querySelector('.db-exercise-list');
    if (toggle) {
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', `${open ? 'Contraer' : 'Expandir'} ${name}`);
    }
    if (panel) panel.hidden = !open;
    grp.classList.toggle('is-open', open);
}

function markMuscles() {
    document.querySelectorAll('#dashboard-catalog .db-group').forEach((grp) => {
        const muscle = grp.dataset.group;
        const isSel = selectedMuscles.has(muscle);
        grp.classList.toggle('selected', isSel);
        const control = grp.querySelector('[data-action="toggle-muscle"]');
        if (control) {
            control.setAttribute('aria-pressed', String(isSel));
            const icon = control.querySelector('[aria-hidden="true"]');
            if (icon) icon.textContent = isSel ? '✓' : '□';
        }
    });
}

function markExercises() {
    document.querySelectorAll('#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"]').forEach((exercise) => {
        const isSel = selectedExercises.has(exercise.dataset.foco);
        exercise.setAttribute('aria-pressed', String(isSel));
        exercise.classList.toggle('selected', isSel);
    });
}

function refreshChart() {
    // Abort any in-flight /grafica request so a stale response can't
    // overwrite the newest state (abort is the primary stale-protection).
    cancelPending('/grafica');
    const params = new URLSearchParams();
    [...selectedMuscles].sort().forEach((m) => params.append('musculos', m));
    [...selectedExercises].sort().forEach((e) => params.append('ejercicios', e));
    params.set('gran', getGranularity());
    // Métricas: la selección viaja siempre (si no, /grafica la reinicia a
    // defaults y los chips mienten). Vacía explícita = todo oculto.
    params.set('metricas', getMetricsSelection().join(','));
    // Ventana técnica fija de la gráfica; el historial muestra todo el ciclo.
    params.set('ventana', '8');
    htmx.ajax('GET', '/grafica?' + params.toString(), {
        source: document.getElementById('unified-chart'),
        target: document.body,
        swap: 'none',
    });
}

function popupIsOpen() {
    const popup = document.getElementById('editor-popup');
    if (popup) return !!popup.open;
    return !!document.querySelector('dialog[open]');
}

function clearHighlightAndDetails() {
    if (window.clearChartHighlight) window.clearChartHighlight({silent:true});
    if (window.closeAllDetails) window.closeAllDetails();
}
function deselectAll() {
    cancelPending();
    clearHighlightAndDetails();
    selectedMuscles = new Set();
    selectedExercises = new Set();
    markMuscles();
    markExercises();
    refreshChart();
    pushState('/');
}

function clickMuscle(muscle, shift) {
    clearHighlightAndDetails();
    if (shift) {
        if (selectedMuscles.has(muscle)) {
            selectedMuscles.delete(muscle);
            if (selectedMuscles.size === 0) {
                deselectAll();
                return;
            }
        } else {
            selectedMuscles.add(muscle);
        }
        selectedExercises = new Set();
        markMuscles();
        refreshChart();
        pushState(currentUrl());
        return;
    }
    if (selectedMuscles.size === 1 && selectedMuscles.has(muscle)) {
        deselectAll();
        return;
    }
    cancelPending();
    selectedMuscles = new Set([muscle]);
    selectedExercises = new Set();
    markMuscles();
    refreshChart();
    pushState(currentUrl());
}

function clickExercise(ejercicio, shift, padre) {
    clearHighlightAndDetails();
    if (shift) {
        if (selectedExercises.has(ejercicio)) {
            selectedExercises.delete(ejercicio);
        } else {
            selectedExercises.add(ejercicio);
        }
        if (padre) selectedMuscles.add(padre);
    } else if (selectedExercises.has(ejercicio)) {
        // Segundo clic sobre un ejercicio ya marcado: lo quita. Su línea
        // desaparece y la gráfica vuelve al estado muscular (Global + padre);
        // el músculo permanece seleccionado.
        selectedExercises.delete(ejercicio);
    } else {
        if (padre) selectedMuscles = new Set([padre]);
        selectedExercises = new Set([ejercicio]);
    }
    markMuscles();
    markExercises();
    refreshChart();
    pushState(currentUrl());
}

function restoreFromURL() {
    const params = new URLSearchParams(location.search);
    const muscles = (params.get('musculos') || '').split(',').filter(Boolean);
    const exercises = (params.get('ejercicios') || '').split(',').filter(Boolean);
    const gran = params.get('gran');
    if (gran && ['day', 'week', 'month'].includes(gran)) setGranularity(gran);
    selectedMuscles = new Set(muscles);
    selectedExercises = new Set(exercises);
    markMuscles();
    markExercises();
    // Métricas: visibilidad sin refetch (los datos ya viajan todos). Sin
    // parámetro se conserva el render del servidor (defaults).
    const metricas = params.get('metricas');
    if (metricas) setMetricsSelection(metricas.split(',').filter(Boolean), { pushUrl: false });
    if (muscles.length) {
        refreshChart();
    }
}

// La granularidad inicial NO es siempre 'day': se adopta del botón activo
// server-renderizado (index.html recibe effective_gran de la URL). Así el
// primer paint ya representa la granularidad de la URL sin parpadeo.
let _granularity =
    document.querySelector('#granularity-selector [data-gran][aria-pressed="true"]')?.dataset.gran ||
    'day';
function getGranularity() { return _granularity; }
function setGranularity(g) { _granularity = g; markGranularity(); }

// Sincroniza el selector visible con la granularidad actual.
function markGranularity() {
    const g = getGranularity();
    document.querySelectorAll('#granularity-selector [data-action="set-granularity"]').forEach((btn) => {
        btn.setAttribute('aria-pressed', String(btn.dataset.gran === g));
    });
    const sel = document.getElementById('granularity-select');
    if (sel) sel.value = g;
}

// Cambio de granularidad: conserva músculos/ejercicios, actualiza
// la gráfica y persiste en la URL.
function changeGranularity(g) {
    if (!['day', 'week', 'month'].includes(g)) return;
    if (g === getGranularity()) return;
    clearHighlightAndDetails();
    setGranularity(g);
    cancelPending();
    refreshChart();
    pushState(currentUrl());
}

function activateSummaryTab(index, focus) {
    const tabs = [...document.querySelectorAll('#period-summary-wrap [role="tab"]')];
    if (!tabs.length) return;
    const target = tabs.find((t) => t.dataset.tabIndex === String(index));
    if (!target) return;
    tabs.forEach((t) => {
        const isTarget = t === target;
        t.setAttribute('aria-selected', String(isTarget));
        t.tabIndex = isTarget ? 0 : -1;
        t.classList.toggle('ps-tab-active', isTarget);
        const panel = document.getElementById(t.getAttribute('aria-controls'));
        if (panel) panel.hidden = !isTarget;
    });
    // Al cambiar tab, cerrar detalles que dejan de ser visibles para no conservar obsoletos
    clearHighlightAndDetails();
    if (focus) target.focus();
}

function initPanelTabsKeyboard() {
    document.addEventListener('keydown', function (e) {
        const tab = e.target.closest && e.target.closest('#period-summary-wrap [role="tab"]');
        if (!tab) return;
        const tabs = [...document.querySelectorAll('#period-summary-wrap [role="tab"]')];
        const idx = tabs.indexOf(tab);
        let next = null;
        if (e.key === 'ArrowRight') next = tabs[(idx + 1) % tabs.length];
        else if (e.key === 'ArrowLeft') next = tabs[(idx - 1 + tabs.length) % tabs.length];
        else if (e.key === 'Home') next = tabs[0];
        else if (e.key === 'End') next = tabs[tabs.length - 1];
        else return;
        e.preventDefault();
        activateSummaryTab(next.dataset.tabIndex, true);
    });
}

function updateDashboardViewportOffset() {
    const page = document.querySelector('.dashboard-page');
    const isMobile = window.matchMedia('(max-width: 1023px)').matches;
    const anchor = isMobile
        ? document.querySelector('.dashboard-summary-col')
        : document.querySelector('.dashboard-layout');
    if (!page || !anchor) return;
    const top = anchor.getBoundingClientRect().top;
    page.style.setProperty('--dashboard-layout-top', `${Math.max(0, top)}px`);
    const header = document.querySelector('.dashboard-header');
    if (header) {
        const headerH = Math.ceil(header.getBoundingClientRect().height + 32);
        page.style.setProperty('--dashboard-header-h', `${Math.max(60, headerH)}px`);
    }
}

// --- Catálogo: máquina de estado única (rail desktop / drawer móvil) -------
// Todos los controles ([data-action="toggle-catalog"]) comparten esta función:
// sincroniza aria-expanded/aria-label, rail, overlay e inert en un solo sitio.
function setCatalogCollapsed(collapsed) {
    const pageEl = document.querySelector('.dashboard-page');
    if (!pageEl) return;
    const overlay = document.getElementById('catalog-overlay');
    const main = document.querySelector('.dashboard-analytics-col');
    const summary = document.getElementById('period-summary-wrap');
    const rail = document.querySelector('.catalog-rail');
    const catalog = document.getElementById('dashboard-catalog');
    const isMobile = window.matchMedia('(max-width: 1023px)').matches;

    pageEl.classList.toggle('is-catalog-collapsed', collapsed);
    document.querySelectorAll('[data-action="toggle-catalog"]').forEach((b) => {
        b.setAttribute('aria-expanded', String(!collapsed));
        b.setAttribute('aria-label', collapsed ? 'Mostrar catálogo' : 'Ocultar catálogo');
    });
    // Rail: solo escritorio plegado.
    if (rail) rail.hidden = !(collapsed && !isMobile);
    // Overlay: solo drawer móvil abierto.
    if (overlay) overlay.hidden = collapsed || !isMobile;
    // inert al contenido principal cuando el drawer móvil cubre la página.
    const drawerOpen = !collapsed && isMobile;
    if ('inert' in HTMLElement.prototype) {
        if (main) main.inert = drawerOpen;
        if (summary) summary.inert = drawerOpen;
    } else {
        [main, summary].forEach((el) => {
            if (!el) return;
            if (drawerOpen && !el.contains(document.activeElement)) el.setAttribute('aria-hidden', 'true');
            else el.removeAttribute('aria-hidden');
        });
    }
    // Gestión de foco por contexto.
    if (collapsed && !isMobile) {
        document.getElementById('catalog-rail-toggle')?.focus();
    } else if (collapsed && isMobile) {
        document.getElementById('catalog-toggle-mobile')?.focus();
    } else if (isMobile) {
        catalog?.querySelector('.db-group-name, [data-action]')?.focus();
    } else {
        document.getElementById('catalog-toggle')?.focus();
    }
}

function toggleCatalog() {
    const pageEl = document.querySelector('.dashboard-page');
    if (!pageEl) return;
    setCatalogCollapsed(!pageEl.classList.contains('is-catalog-collapsed'));
}

function initCatalogDrawer() {
    const pageEl = document.querySelector('.dashboard-page');
    const overlay = document.getElementById('catalog-overlay');
    if (!pageEl) return;
    // Estado inicial: escritorio abierto; móvil cerrado (drawer fuera).
    if (window.matchMedia('(max-width: 1023px)').matches) {
        setCatalogCollapsed(true);
    }
    if (overlay) {
        overlay.addEventListener('click', () => {
            if (!pageEl.classList.contains('is-catalog-collapsed')) setCatalogCollapsed(true);
        });
    }
}



export function initLevelCascade() {
    // Selection buttons are not text-entry controls. Prevent pointer selection
    // from leaving a focus ring over only the label, especially during
    // Shift+click multi-selection. Keyboard focus remains available through
    // normal Tab navigation.
    document.addEventListener('pointerdown', function (e) {
        const selectionButton = e.target.closest('.db-group-name, .db-exercise-row');
        if (selectionButton) e.preventDefault();
    });

    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'toggle-period-detail') {
            e.preventDefault();
            const expanded = el.getAttribute('aria-expanded') === 'true';
            el.setAttribute('aria-expanded', String(!expanded));
            const det = document.getElementById(el.getAttribute('aria-controls') || '');
            if (det) det.hidden = expanded;
            // No fetch, solo local
            return;
        }
        if (el.dataset.action === 'toggle-muscle') {
            // Native checkbox activation supplies the accessible checked state;
            // only row-level clicks need their default suppressed.
            if (el.tagName !== 'INPUT') e.preventDefault();
            e.stopPropagation();
            clickMuscle(el.dataset.foco, e.shiftKey);
        } else if (el.dataset.action === 'toggle-exercise') {
            if (el.tagName !== 'INPUT') e.preventDefault();
            clickExercise(el.dataset.foco, e.shiftKey, el.dataset.padre);
        } else if (el.dataset.action === 'toggle-group') {
            e.preventDefault();
            const group = el.closest('.db-group');
            const isOpen = el.getAttribute('aria-expanded') === 'true';
            openGroup(group.dataset.group, !isOpen);
        } else if (el.dataset.action === 'set-granularity') {
            e.preventDefault();
            changeGranularity(el.dataset.gran);
        } else if (el.dataset.action === 'select-summary-tab') {
            // Cambio de pestaña 100 % local: cero peticiones.
            e.preventDefault();
            activateSummaryTab(el.dataset.tabIndex, false);
        } else if (el.dataset.action === 'toggle-catalog') {
            // Plegado visual del catálogo: sin fetch, sin URL, sin history.
            e.preventDefault();
            toggleCatalog();
        }
    });

    // Registra los xhr de la cascada para poder cancelarlos en toggles rápidos.
    document.body.addEventListener('htmx:beforeRequest', function (e) {
        trackXhr(e);
        stampSeq(e);
    });

    // Stale-response veto: abort swap if this response is older than the latest
    // request of the SAME resource type.
    document.body.addEventListener('htmx:beforeSwap', function (e) {
        const xhr = e.detail && e.detail.xhr;
        if (xhr && typeof xhr._seq === 'number') {
            const path = xhr._cascadePath || '';
            const type = seqType(path);
            if (type && xhr._seq < seqs[type]) {
                e.detail.shouldSwap = false;
            }
        }
    });

    window.addEventListener('popstate', function () {
        cancelPending();
        clearHighlightAndDetails();
        restoreFromURL();
        if (!selectedMuscles.size) {
            refreshChart();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (popupIsOpen()) return;
        const pageEl = document.querySelector('.dashboard-page');
        const drawerOpen = pageEl && !pageEl.classList.contains('is-catalog-collapsed')
            && window.matchMedia('(max-width: 1023px)').matches;
        if (drawerOpen) {
            const toggle = document.getElementById('catalog-toggle');
            toggleCatalog();
            e.preventDefault();
            return;
        }
        // Prioridad existente: dialog/drawer > highlight+acordeón > deselección músculos
        const hasHighlight = window.getChartHighlight ? window.getChartHighlight().length > 0 : false;
        const hasOpenDetail = !!document.querySelector('#period-summary-wrap .ps-row-toggle[aria-expanded="true"]');
        if (hasHighlight || hasOpenDetail) {
            clearHighlightAndDetails();
            e.preventDefault();
            return;
        }
        if (selectedMuscles.size) deselectAll();
    });

    // Cerrar drawer con Tab ciclo: atrapa foco dentro del drawer cuando está abierto en móvil
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Tab') return;
        const pageEl = document.querySelector('.dashboard-page');
        if (!pageEl || pageEl.classList.contains('is-catalog-collapsed')) return;
        if (!window.matchMedia('(max-width: 1023px)').matches) return;
        const catalog = document.getElementById('dashboard-catalog');
        if (!catalog || !catalog.contains(document.activeElement)) return;
        const focusable = [...catalog.querySelectorAll('button, [href], input, select, [tabindex]:not([tabindex="-1"])')].filter(el => !el.hidden && el.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    });

    // Orden dinámico compartido: tras OOB del catálogo, conserva selección y reordena
    let _openGroupsBeforeSwap = [];
    document.body.addEventListener('htmx:oobBeforeSwap', function (e) {
        if (e.detail.target.id !== 'dashboard-catalog-list') return;
        _openGroupsBeforeSwap = [...document.querySelectorAll('#dashboard-catalog .db-group.is-open')].map(g => g.dataset.group);
    });
    document.body.addEventListener('htmx:oobAfterSwap', function (e) {
        if (e.detail.target.id !== 'dashboard-catalog-list') return;
        markMuscles();
        markExercises();
        _openGroupsBeforeSwap.forEach(name => openGroup(name, true));
        _openGroupsBeforeSwap = [];
        const active = document.activeElement;
        if (active && active.closest('#dashboard-catalog')) {
            const first = document.querySelector('#dashboard-catalog [data-action]');
            if (first) first.focus();
        }
    });
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.detail.target.id === 'dashboard-catalog-list') {
            markMuscles();
            markExercises();
        }
    });

    initPanelTabsKeyboard();
    initCatalogDrawer();
    updateDashboardViewportOffset();
    new ResizeObserver(updateDashboardViewportOffset).observe(document.querySelector('.dashboard-header') || document.body);
    window.addEventListener('resize', updateDashboardViewportOffset);
    // Cambio de breakpoint: re-sincroniza drawer/rail sin perder selección.
    let _lastMobile = window.matchMedia('(max-width: 1023px)').matches;
    window.addEventListener('resize', function () {
        const isMobile = window.matchMedia('(max-width: 1023px)').matches;
        if (isMobile === _lastMobile) return;
        _lastMobile = isMobile;
        const pageEl = document.querySelector('.dashboard-page');
        if (!pageEl) return;
        const collapsed = pageEl.classList.contains('is-catalog-collapsed');
        setCatalogCollapsed(isMobile ? true : collapsed);
        updateDashboardViewportOffset();
    });
    restoreFromURL();
    markGranularity();
}
