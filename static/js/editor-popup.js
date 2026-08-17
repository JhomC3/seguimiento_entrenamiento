// editor-popup.js — ventana emergente de registro diario (dialog nativo).
// Owns: #editor-popup (open/close via showModal/close), #popup-body (fetches
// /editor/popup?fecha=), #popup-fecha-title. Reutiliza date-navigation.js.

import { closeDialog, openDialog } from './modal-dialog.js';

let suppressPopstate = false;

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
    openDialog(popup);
    const body = document.getElementById('popup-body');
    if (body) {
        htmx.ajax('GET', '/editor/popup?fecha=' + iso, {
            target: body,
            swap: 'innerHTML',
        });
    }
    // El registro entra en el historial: "atrás" cierra la ventana sin salir de la app.
    if (new URLSearchParams(location.search).get('registro') !== iso) {
        history.pushState({}, '', '?registro=' + iso);
    }
}

export function closeEditorPopup() {
    const popup = document.getElementById('editor-popup');
    if (!popup) return;
    closeDialog(popup);
    // Deshace la entrada ?registro del historial sin que el popstate resultante
    // vuelva a abrir la ventana (suppressPopstate se limpia en ese evento).
    const params = new URLSearchParams(location.search);
    if (params.has('registro')) {
        suppressPopstate = true;
        history.back();
    }
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

    // Escape: el dialog nativo dispara "cancel"; lo interceptamos para que el
    // cierre también deshaga la entrada ?registro del historial.
    const popup = document.getElementById('editor-popup');
    if (popup) {
        popup.addEventListener('cancel', function (e) {
            e.preventDefault();
            closeEditorPopup();
        });
    }

    // Sincroniza la ventana con el historial (atrás/adelante del navegador).
    window.addEventListener('popstate', function () {
        const el = document.getElementById('editor-popup');
        if (!el) return;
        const params = new URLSearchParams(location.search);
        if (suppressPopstate) {
            suppressPopstate = false;
            return;
        }
        if (params.has('registro')) {
            if (!el.open) openEditorPopup(params.get('registro'));
        } else if (el.open) {
            closeDialog(el);
        }
    });

    // Recarga o navegación directa con ?registro: abrir el popup en esa fecha.
    const initialParams = new URLSearchParams(location.search);
    if (initialParams.has('registro')) {
        openEditorPopup(initialParams.get('registro'));
    }

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
