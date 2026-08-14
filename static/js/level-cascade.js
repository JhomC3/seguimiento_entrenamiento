// level-cascade.js — cascada: músculos siempre visibles con selección simple
// (click) o múltiple (Shift+click); ejercicios con la misma mecánica.
// Owns: #cascade-row (músculos), #ejercicios-row (chips toggle), #history-section.
// Gráfica: 1 músculo → compilado + ejercicios; 2+ músculos → Global + músculos.
// Cada paso empuja historial (?musculos=A,B&ejercicios=a,b) y popstate restaura.

let selectedMuscles = new Set();
let selectedExercises = new Set();

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
        if (xhr.readyState < 4 && (!pathPrefix || (xhr._cascadePath || '').startsWith(pathPrefix))) {
            xhr.abort();
        }
    });
    if (!pathPrefix) pendingXhrs.clear();
}

function refresh(target, url) {
    htmx.ajax('GET', url, { target: target, swap: 'innerHTML' });
}

function pushState(url) {
    history.pushState({}, '', url);
}

function currentUrl() {
    const params = new URLSearchParams();
    if (selectedMuscles.size) params.set('musculos', [...selectedMuscles].join(','));
    if (selectedExercises.size) params.set('ejercicios', [...selectedExercises].join(','));
    const q = params.toString();
    return q ? '?' + q : '/';
}

function markMuscles() {
    document.querySelectorAll('#cascade-row .level-chip').forEach((chip) => {
        chip.classList.toggle('selected', selectedMuscles.has(chip.dataset.foco));
    });
}

function markExercises() {
    document.querySelectorAll('#ejercicios-row .exercise-chip').forEach((chip) => {
        chip.setAttribute('aria-pressed', String(selectedExercises.has(chip.dataset.foco)));
    });
}

function refreshChart() {
    const params = new URLSearchParams();
    [...selectedMuscles].forEach((m) => params.append('musculo', m));
    [...selectedExercises].forEach((e) => params.append('ejercicios', e));
    htmx.ajax('GET', '/grafica?' + params.toString(), {
        target: document.body,
        swap: 'none',
    });
}

function refreshExerciseRow() {
    const row = document.getElementById('ejercicios-row');
    if (selectedMuscles.size === 1) {
        // Solo con 1 músculo tiene sentido la fila de ejercicios. Se cancela
        // solo el pedido previo de la fila (no la carga de los músculos).
        const muscle = [...selectedMuscles][0];
        cancelPending('/nivel?tipo=musculo');
        refresh('#ejercicios-row', '/nivel?tipo=musculo&foco=' + encodeURIComponent(muscle));
    } else if (row) {
        row.innerHTML = '';
    }
}

function popupIsOpen() {
    const popup = document.getElementById('editor-popup');
    return popup && !popup.classList.contains('hidden');
}

function deselectAll() {
    cancelPending();
    selectedMuscles = new Set();
    selectedExercises = new Set();
    markMuscles();
    const row = document.getElementById('ejercicios-row');
    if (row) row.innerHTML = '';
    // Vuelve al grupo completo del cuerpo: fila de músculos sin marca y
    // gráfica sistémica (el response de /nivel?tipo=global trae ambos).
    refresh('#cascade-row', '/nivel?tipo=global');
    pushState('/');
}

function clickMuscle(muscle, shift) {
    if (shift) {
        // Shift+click: añade/quita de la selección múltiple.
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
        refreshExerciseRow();
        refreshChart();
        pushState(currentUrl());
        return;
    }
    // Click simple: selecciona solo este; si ya era el único, deselecciona.
    if (selectedMuscles.size === 1 && selectedMuscles.has(muscle)) {
        deselectAll();
        return;
    }
    cancelPending();
    selectedMuscles = new Set([muscle]);
    selectedExercises = new Set();
    markMuscles();
    refreshExerciseRow();
    refreshChart();
    pushState(currentUrl());
}

function clickExercise(ejercicio, shift) {
    if (shift) {
        // Shift+click: añade/quita de la selección de ejercicios.
        if (selectedExercises.has(ejercicio)) {
            selectedExercises.delete(ejercicio);
        } else {
            selectedExercises.add(ejercicio);
        }
    } else {
        // Click simple: solo este ejercicio.
        selectedExercises = new Set([ejercicio]);
    }
    markExercises();
    refreshChart();
    pushState(currentUrl());
}

function restoreFromURL() {
    const params = new URLSearchParams(location.search);
    const muscles = (params.get('musculos') || '').split(',').filter(Boolean);
    const exercises = (params.get('ejercicios') || '').split(',').filter(Boolean);
    // La fila de músculos ya está cargada (loadMuscles se ejecuta siempre);
    // aquí solo se aplica la selección recordada en la URL.
    if (!muscles.length) {
        selectedMuscles = new Set();
        selectedExercises = new Set();
        markMuscles();
        const row = document.getElementById('ejercicios-row');
        if (row) row.innerHTML = '';
        return;
    }
    selectedMuscles = new Set(muscles);
    selectedExercises = new Set(exercises);
    markMuscles();
    refreshExerciseRow();
    refreshChart();
}

function loadMuscles() {
    // Estado base: fila de músculos + gráfica sistémica, siempre al iniciar.
    refresh('#cascade-row', '/nivel?tipo=global');
}

export function initLevelCascade() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'select-muscle') {
            clickMuscle(el.dataset.foco, e.shiftKey);
        } else if (el.dataset.action === 'toggle-exercise') {
            clickExercise(el.dataset.foco, e.shiftKey);
        } else if (el.dataset.action === 'exercise-detail') {
            refresh('#history-section', '/nivel?tipo=ejercicio&foco=' + encodeURIComponent(el.dataset.foco));
        }
    });

    // Registra los xhr de la cascada para poder cancelarlos en toggles rápidos.
    document.body.addEventListener('htmx:beforeRequest', trackXhr);

    // Cada vez que la fila de músculos se renderiza (carga inicial, recarga,
    // popstate), se re-aplican las marcas de los músculos seleccionados.
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (e.target && e.target.id === 'cascade-row') {
            markMuscles();
        }
    });

    window.addEventListener('popstate', function () {
        // Al volver atrás, la fila de músculos se recarga y se aplica la selección.
        loadMuscles();
        restoreFromURL();
    });

    // Escape deselecciona todo (vuelve al grupo completo del cuerpo), salvo
    // que la ventana de registro esté abierta (ahí Escape la cierra).
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (popupIsOpen()) return;
        if (selectedMuscles.size) deselectAll();
    });

    // Los músculos SIEMPRE se cargan al abrir la página.
    loadMuscles();
    restoreFromURL();
}
