// level-cascade.js — cascada del catálogo izquierdo del dashboard.
// Owns: #dashboard-catalog (cabeceras con selección de músculo y control
// independiente de expansión + botones de ejercicio),
// estado de selección (músculos/ejercicios) y #history-section (detalle).
// Gráfica: /grafica (target exclusivo de gráfica). Detalle: /nivel?tipo=ejercicio.
// Cada paso empuja historial (?musculos=A,B&ejercicios=a,b) y popstate restaura.

let selectedMuscles = new Set();
let selectedExercises = new Set();

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

function refresh(target, url) {
    htmx.ajax('GET', url, {
        source: document.querySelector(target),
        target: target,
        swap: 'innerHTML',
    });
}

function pushState(url) {
    history.pushState({}, '', url);
}

function currentUrl() {
    const params = new URLSearchParams();
    params.append('musculos', [...selectedMuscles].sort().join(','));
    if (selectedExercises.size) params.append('ejercicios', [...selectedExercises].sort().join(','));
    params.set('gran', getGranularity());
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
    htmx.ajax('GET', '/grafica?' + params.toString(), {
        source: document.getElementById('unified-chart'),
        target: document.body,
        swap: 'none',
    });
}

function refreshDetail() {
    const section = document.getElementById('history-section');
    if (!section) return;
    if (selectedExercises.size === 1) {
        const ejercicio = [...selectedExercises][0];
        cancelPending('/nivel');
        refresh('#history-section', '/nivel?tipo=ejercicio&foco=' + encodeURIComponent(ejercicio));
    } else if (selectedExercises.size === 0) {
        cancelPending('/nivel');
        refresh('#history-section', '/nivel?tipo=ejercicio');
    }
    // With multiple exercises, keep the current detail (last clicked).
}

function popupIsOpen() {
    const popup = document.getElementById('editor-popup');
    return popup && popup.open;
}

function deselectAll() {
    cancelPending();
    selectedMuscles = new Set();
    selectedExercises = new Set();
    markMuscles();
    markExercises();
    refreshChart();
    refreshDetail();
    pushState('/');
}

function clickMuscle(muscle, shift) {
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
        refreshDetail();
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
    refreshDetail();
    pushState(currentUrl());
}

function clickExercise(ejercicio, shift, padre) {
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
    refreshDetail();
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
    if (muscles.length) {
        refreshChart();
        refreshDetail();
    }
}

let _granularity = 'day';
function getGranularity() { return _granularity; }
function setGranularity(g) { _granularity = g; markGranularity(); }

// Sincroniza el selector visible con la granularidad actual.
function markGranularity() {
    const g = getGranularity();
    document.querySelectorAll('#granularity-selector [data-action="set-granularity"]').forEach((btn) => {
        const isActive = btn.dataset.gran === g;
        btn.setAttribute('aria-pressed', String(isActive));
        btn.classList.toggle('bg-burgundy-600', isActive);
        btn.classList.toggle('text-white', isActive);
        btn.classList.toggle('text-neutral-400', !isActive);
        btn.classList.toggle('hover:text-white', !isActive);
    });
    // Compatibilidad con el select legacy (si existe)
    const sel = document.getElementById('granularity-select');
    if (sel) sel.value = g;
}

// Cambio de granularidad: conserva músculos/ejercicios y ventana, actualiza
// la gráfica y persiste en la URL.
function changeGranularity(g) {
    if (!['day', 'week', 'month'].includes(g)) return;
    if (g === getGranularity()) return;
    setGranularity(g);
    cancelPending();
    refreshChart();
    pushState(currentUrl());
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
        restoreFromURL();
        if (!selectedMuscles.size) {
            refreshChart();
            refreshDetail();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (popupIsOpen()) return;
        if (selectedMuscles.size) deselectAll();
    });

    restoreFromURL();
    markGranularity();
}
