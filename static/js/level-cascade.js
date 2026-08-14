// level-cascade.js — cascada: músculos siempre visibles + multi-selección de
// ejercicios. Owns: #cascade-row (músculos), #ejercicios-row (chips toggle),
// #history-section (detalle). Cada paso empuja historial (?musculo=X&ejercicios=a,b)
// y popstate restaura el estado (el botón atrás navega dentro de la app).

let selectedMuscle = null;
let selectedExercises = new Set();

// Cancela requests htmx en vuelo de la cascada (evita que una respuesta vieja
// sobrescriba el estado tras un toggle rápido o Escape).
let pendingXhrs = new Set();
function trackXhr(e) {
    const path = e.detail && e.detail.requestConfig && e.detail.requestConfig.path;
    if (!path) return;
    if (path.startsWith('/nivel') || path.startsWith('/grafica')) {
        pendingXhrs.add(e.detail.xhr);
        e.detail.xhr.addEventListener('loadend', () => pendingXhrs.delete(e.detail.xhr));
    }
}
function cancelPending() {
    pendingXhrs.forEach((xhr) => {
        if (xhr.readyState < 4) xhr.abort();
    });
    pendingXhrs.clear();
}

function refresh(target, url) {
    htmx.ajax('GET', url, { target: target, swap: 'innerHTML' });
}

function pushState(url) {
    history.pushState({}, '', url);
}

function markMuscle(muscle) {
    document.querySelectorAll('#cascade-row .level-chip').forEach((chip) => {
        chip.classList.toggle('selected', chip.dataset.foco === muscle);
    });
}

function refreshChart(muscle, exercises) {
    const params = new URLSearchParams({ musculo: muscle });
    exercises.forEach((e) => params.append('ejercicios', e));
    htmx.ajax('GET', '/grafica?' + params.toString(), {
        target: document.body,
        swap: 'none',
    });
}

function selectMuscle(muscle) {
    if (selectedMuscle === muscle) {
        // Toggle: volver a oprimir el músculo seleccionado lo deselecciona y
        // regresa al grupo completo del cuerpo.
        deselectAll();
        return;
    }
    cancelPending();
    selectedMuscle = muscle;
    selectedExercises = new Set();
    markMuscle(muscle);
    refresh('#ejercicios-row', '/nivel?tipo=musculo&foco=' + encodeURIComponent(muscle));
    pushState('?musculo=' + encodeURIComponent(muscle));
}

function deselectAll() {
    cancelPending();
    selectedMuscle = null;
    selectedExercises = new Set();
    markMuscle(null);
    const row = document.getElementById('ejercicios-row');
    if (row) row.innerHTML = '';
    // Vuelve al grupo completo del cuerpo: fila de músculos sin marca y
    // gráfica sistémica (el response de /nivel?tipo=global trae ambos).
    refresh('#cascade-row', '/nivel?tipo=global');
    pushState('/');
}

function popupIsOpen() {
    const popup = document.getElementById('editor-popup');
    return popup && !popup.classList.contains('hidden');
}

function toggleExercise(muscle, ejercicio) {
    if (selectedExercises.has(ejercicio)) {
        selectedExercises.delete(ejercicio);
    } else {
        selectedExercises.add(ejercicio);
    }
    markExercises();
    refreshChart(muscle, [...selectedExercises]);
    const params = new URLSearchParams({ musculo: muscle });
    [...selectedExercises].forEach((e) => params.append('ejercicios', e));
    pushState('?' + params.toString());
}

function markExercises() {
    document.querySelectorAll('#ejercicios-row .exercise-chip').forEach((chip) => {
        chip.setAttribute('aria-pressed', String(selectedExercises.has(chip.dataset.foco)));
    });
}

function restoreFromURL() {
    const params = new URLSearchParams(location.search);
    const muscle = params.get('musculo');
    const exercises = params.getAll('ejercicios').flatMap((v) => v.split(',')).filter(Boolean);
    // La fila de músculos ya está cargada (loadMuscles se ejecuta siempre en init);
    // aquí solo se aplica la selección recordada en la URL.
    if (!muscle) {
        selectedMuscle = null;
        selectedExercises = new Set();
        markMuscle(null);
        const row = document.getElementById('ejercicios-row');
        if (row) row.innerHTML = '';
        return;
    }
    selectedMuscle = muscle;
    selectedExercises = new Set(exercises);
    markMuscle(muscle);
    refresh('#ejercicios-row', '/nivel?tipo=musculo&foco=' + encodeURIComponent(muscle));
    refreshChart(muscle, [...selectedExercises]);
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
            selectMuscle(el.dataset.foco);
        } else if (el.dataset.action === 'toggle-exercise') {
            const muscle = el.dataset.padre || selectedMuscle;
            if (muscle) toggleExercise(muscle, el.dataset.foco);
        } else if (el.dataset.action === 'exercise-detail') {
            refresh('#history-section', '/nivel?tipo=ejercicio&foco=' + encodeURIComponent(el.dataset.foco));
        }
    });

    // Registra los xhr de la cascada para poder cancelarlos en toggles rápidos.
    document.body.addEventListener('htmx:beforeRequest', trackXhr);

    window.addEventListener('popstate', function () {
        // Al volver atrás, la fila de músculos se recarga y se aplica la selección.
        loadMuscles();
        restoreFromURL();
    });

    // Escape deselecciona el músculo (vuelve al grupo completo del cuerpo),
    // salvo que la ventana de registro esté abierta (ahí Escape la cierra).
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (popupIsOpen()) return;
        if (selectedMuscle) deselectAll();
    });

    // Los músculos SIEMPRE se cargan al abrir la página.
    loadMuscles();
    restoreFromURL();
}
