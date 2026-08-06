// dashboard-filters.js — owns: category and exercise selection and highlighting.
// DOM owned: .category-btn, .filter-btn, #exercise-section, #history-section.
// Public API: initDashboardFilters.

let currentCategory = null;
let currentExercise = null;

function highlightCategoryBtn(category) {
    document.querySelectorAll('.category-btn').forEach(btn => {
        btn.classList.remove('bg-burgundy-950/40', 'text-burgundy-400', 'shadow-[0_0_10px_rgba(155,27,48,0.5)]');
        btn.classList.add('bg-matte-950', 'text-neutral-300');
    });
    if (category) {
        const activeBtn = document.getElementById(`cat-btn-${category}`);
        if (activeBtn) {
            activeBtn.classList.remove('bg-matte-950', 'text-neutral-300');
            activeBtn.classList.add('bg-burgundy-950/40', 'text-burgundy-400', 'shadow-[0_0_10px_rgba(155,27,48,0.5)]');
        }
    }
}

function toggleCategory(category) {
    if (currentCategory === category) {
        resetToGlobal();
    } else {
        currentCategory = category;
        currentExercise = null;
        highlightCategoryBtn(category);
        const historySec = document.getElementById('history-section');
        if (historySec) historySec.innerHTML = '';

        htmx.ajax('GET', `/select?grupo=${encodeURIComponent(category)}`, '#exercise-section');
    }
}

function toggleExercise(exercise) {
    if (currentExercise === exercise) {
        currentExercise = null;
        highlightExerciseBtn(null);

        htmx.ajax('GET', `/grupo/reset?grupo=${encodeURIComponent(currentCategory)}`, '#history-section');
    } else {
        currentExercise = exercise;
        highlightExerciseBtn(exercise);

        htmx.ajax('GET', `/ejercicio?ejercicio=${encodeURIComponent(exercise)}`, '#history-section');
    }
}

function highlightExerciseBtn(exercise) {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('bg-burgundy-950/40', 'text-burgundy-400', 'border-burgundy-800');
        btn.classList.add('bg-matte-950', 'text-neutral-300', 'border-neutral-800');
    });
    if (exercise) {
        const buttons = document.querySelectorAll('.filter-btn');
        buttons.forEach(btn => {
            const span = btn.querySelector('span');
            if (span && span.textContent.trim() === exercise) {
                btn.classList.remove('bg-matte-950', 'text-neutral-300', 'border-neutral-800');
                btn.classList.add('bg-burgundy-950/40', 'text-burgundy-400', 'border-burgundy-800');
            }
        });
    }
}

function resetToGlobal() {
    currentCategory = null;
    currentExercise = null;
    highlightCategoryBtn(null);

    const historySec = document.getElementById('history-section');
    if (historySec) historySec.innerHTML = '';

    htmx.ajax('GET', '/select', '#exercise-section');
}

export function initDashboardFilters() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'select-category') {
            toggleCategory(el.dataset.category);
        } else if (el.dataset.action === 'select-exercise') {
            toggleExercise(el.dataset.exercise);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' || event.keyCode === 27) {
            resetToGlobal();
        }
    });

    document.body.addEventListener('htmx:afterRequest', function (event) {
        const elt = event.detail.elt;
        if (elt && elt.id === 'exercise-create-form' && event.detail.successful) {
            if (currentCategory) {
                htmx.ajax('GET', `/select?grupo=${encodeURIComponent(currentCategory)}`, '#exercise-section');
            } else {
                htmx.ajax('GET', '/select', '#exercise-section');
            }
        }
    });
}
