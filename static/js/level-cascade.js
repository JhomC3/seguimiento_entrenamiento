// level-cascade.js — cascada: músculos siempre visibles + multi-selección de
// ejercicios. Owns: #cascade-row (músculos), #ejercicios-row (chips toggle),
// #history-section (detalle). Cada paso empuja historial (?musculo=X&ejercicios=a,b)
// y popstate restaura el estado (el botón atrás navega dentro de la app).

let selectedMuscle = null;
let selectedExercises = new Set();

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
    selectedMuscle = muscle;
    selectedExercises = new Set();
    markMuscle(muscle);
    refresh('#ejercicios-row', '/nivel?tipo=musculo&foco=' + encodeURIComponent(muscle));
    pushState('?musculo=' + encodeURIComponent(muscle));
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
    if (!muscle) {
        // Estado base: fila de músculos + gráfica sistémica (una sola petición).
        selectedMuscle = null;
        selectedExercises = new Set();
        markMuscle(null);
        const row = document.getElementById('ejercicios-row');
        if (row) row.innerHTML = '';
        refresh('#cascade-row', '/nivel?tipo=global');
        return;
    }
    selectedMuscle = muscle;
    selectedExercises = new Set(exercises);
    markMuscle(muscle);
    refresh('#ejercicios-row', '/nivel?tipo=musculo&foco=' + encodeURIComponent(muscle));
    refreshChart(muscle, [...selectedExercises]);
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

    window.addEventListener('popstate', restoreFromURL);

    // Precarga: los músculos del catálogo como fila inicial.
    restoreFromURL();
}
