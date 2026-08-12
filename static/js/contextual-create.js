// contextual-create.js — compact create forms inside the register modal.
// Owns: #register-create-forms (toggle show/hide), + Ejercicio / + Alimento
// buttons in the modal header. Forms post via htmx; OOB swaps refresh them.

export function initContextualCreate() {
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-action="toggle-create-form"]');
        if (!btn) return;
        const kind = btn.dataset.kind;
        const form = document.querySelector(
            kind === 'ejercicio' ? '#exercise-create' : '#alimento-create'
        );
        if (!form) return;
        const visible = !form.classList.contains('hidden');
        form.classList.toggle('hidden', visible);
        if (!visible) {
            const input = form.querySelector('input[name="ejercicio"], input[name="nombre"]');
            if (input) input.focus();
        }
    });

    // Tras un alta exitosa, el OOB refresca el form (sigue oculto por su clase).
    document.body.addEventListener('htmx:afterRequest', function (e) {
        if (!e.detail || !e.detail.successful) return;
        const path = e.detail.pathInfo && e.detail.pathInfo.requestPath;
        if (path === '/ejercicio/nuevo' || path === '/alimento/nuevo') {
            const target = path === '/ejercicio/nuevo' ? '#exercise-create' : '#alimento-create';
            const form = document.querySelector(target);
            if (form) form.classList.add('hidden');
        }
    });
}
