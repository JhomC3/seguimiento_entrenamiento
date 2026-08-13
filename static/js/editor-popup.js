// editor-popup.js — ventana emergente de registro diario.
// Owns: #editor-popup (open/close), #popup-body (fetches /editor/popup?fecha=),
// #popup-fecha-title. Reutiliza date-navigation.js (←/→, salto de fecha).

function todayIso() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

function setFechaTitle(iso) {
    const el = document.getElementById('popup-fecha-title');
    if (!el) return;
    const [y, m, d] = iso.split('-').map(Number);
    el.textContent = d + '/' + m + '/' + String(y % 100).padStart(2, '0');
}

export function openEditorPopup(fechaIso) {
    const popup = document.getElementById('editor-popup');
    if (!popup) return;
    const iso = fechaIso || todayIso();
    setFechaTitle(iso);
    popup.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    const body = document.getElementById('popup-body');
    if (body) {
        htmx.ajax('GET', '/editor/popup?fecha=' + iso, {
            target: body,
            swap: 'innerHTML',
        });
    }
}

export function closeEditorPopup() {
    const popup = document.getElementById('editor-popup');
    if (!popup) return;
    popup.classList.add('hidden');
    document.body.style.overflow = '';
}

export function initEditorPopup() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'open-editor-popup') {
            openEditorPopup(el.dataset.fecha || todayIso());
        } else if (el.dataset.action === 'close-editor-popup') {
            closeEditorPopup();
        }
    });

    document.addEventListener('keydown', function (e) {
        const popup = document.getElementById('editor-popup');
        if (!popup || popup.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeEditorPopup();
    });

    // Tras cargar el popup, el título de fecha sigue la fecha seleccionada del navegador.
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (!e.target || e.target.id !== 'popup-body') return;
        const selected = document.querySelector('#popup-body .date-num.selected');
        if (selected) setFechaTitle(selected.dataset.iso);
    });

    // Anotación de cardio: submit del formulario dentro del popup.
    document.addEventListener('submit', function (e) {
        const form = e.target.closest && e.target.closest('[data-action="cardio-annotation-save"]');
        if (!form) return;
        e.preventDefault();
        htmx.ajax('POST', '/cardio/annotation', {
            values: new FormData(form),
            target: document.body,
            swap: 'none',
        });
    });
}
