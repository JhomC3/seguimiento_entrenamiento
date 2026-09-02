// diario.js — standalone daily workspace: mode tabs and compact secondary
// dialogs. Owns: tab switching (aria-selected, view visibility, vista in URL),
// dialog open/close via modal-dialog.js (native <dialog>), and client-side
// catalog refresh after create flows (exercise/food) so the new item is
// selectable immediately without reloading the page.

import { closeDialog, openDialog } from './modal-dialog.js';

const MODES = ['entrenamiento', 'alimentacion'];

function normalizeMode(mode) {
    return MODES.includes(mode) ? mode : 'entrenamiento';
}

function setMode(mode, push = true) {
    mode = normalizeMode(mode);
    document.querySelectorAll('#daily-page [role="tab"]').forEach((tab) => {
        tab.setAttribute('aria-selected', String(tab.dataset.vista === mode));
        tab.tabIndex = tab.dataset.vista === mode ? 0 : -1;
    });
    document.querySelector('#daily-training-view')?.toggleAttribute('hidden', mode !== 'entrenamiento');
    document.querySelector('#daily-food-view')?.toggleAttribute('hidden', mode !== 'alimentacion');
    document.querySelector('#daily-page')?.setAttribute('data-vista', mode);
    if (push) {
        const url = new URL(window.location.href);
        url.searchParams.set('vista', mode);
        window.history.replaceState({}, '', url);
    }
}

function addOptionToSelects(selector, name) {
    const value = (name || '').trim();
    if (!value) return;
    document.querySelectorAll(selector).forEach((sel) => {
        const exists = Array.from(sel.options).some(
            (o) => o.value.toLowerCase() === value.toLowerCase()
        );
        if (!exists) sel.add(new Option(value, value));
    });
}

function addOptionToDatalist(listId, name) {
    const value = (name || '').trim();
    if (!value) return;
    const list = document.getElementById(listId);
    if (!list) return;
    const exists = Array.from(list.querySelectorAll('option')).some(
        (o) => o.value.toLowerCase() === value.toLowerCase()
    );
    if (!exists) {
        const opt = document.createElement('option');
        opt.value = value;
        list.appendChild(opt);
    }
}

export function initDiario() {
    document.addEventListener('click', (event) => {
        const action = event.target.closest('[data-action]');
        if (!action) return;
        if (action.dataset.action === 'daily-mode') {
            event.preventDefault();
            setMode(action.dataset.vista);
        } else if (action.dataset.action === 'open-daily-dialog') {
            event.preventDefault();
            openDialog(document.getElementById(action.dataset.dialog));
        } else if (action.dataset.action === 'close-daily-dialog') {
            event.preventDefault();
            closeDialog(action.closest('dialog'));
        }
    });

    document.querySelectorAll('.daily-dialog').forEach((dialog) => {
        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) closeDialog(dialog);
        });
    });

    // Tabs: flechas izquierda/derecha (patrón ARIA tabs).
    document.addEventListener('keydown', (event) => {
        if (!event.target.closest || !event.target.closest('#daily-page [role="tablist"]')) return;
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const tabs = Array.from(document.querySelectorAll('#daily-page [role="tab"]'));
        const idx = tabs.indexOf(event.target);
        if (idx === -1) return;
        const dir = event.key === 'ArrowRight' ? 1 : -1;
        const next = (idx + dir + tabs.length) % tabs.length;
        setMode(tabs[next].dataset.vista);
        tabs[next].focus();
    });

    // Alta de ejercicio/alimento desde los diálogos: refresco client-side de
    // los selectores (el catálogo del editor se sirve server-side y no se
    // re-renderiza con el alta) + cierre del diálogo. La config completa
    // (categoria_map/alimento_map) llega por OOB de #app-config. El nombre
    // se captura en configRequest (antes del swap) porque el formulario se
    // re-renderiza por OOB entre la petición y afterRequest y sus valores
    // quedan vacíos.
    let pendingExercise = "";
    let pendingAlimento = "";
    document.body.addEventListener('htmx:configRequest', (event) => {
        const params = event.detail ? event.detail.parameters : null;
        if (!params) return;
        // htmx serializa ejercicio/alimento como campo del formulario.
        if (params.ejercicio !== undefined) {
            pendingExercise = (params.ejercicio || "").trim();
        }
        if (params.nombre !== undefined) {
            const elt = event.detail.elt;
            const id = elt ? elt.id : "";
            // nombre aparece tanto en plantillas como en alimento; solo el
            // flujo de alimento usa la ruta /alimento/nuevo.
            if (id === 'alimento-create-form') {
                pendingAlimento = (params.nombre || "").trim();
            }
        }
    });
    document.body.addEventListener('htmx:afterRequest', (event) => {
        if (!event.detail || !event.detail.successful) return;
        const url = event.detail.xhr ? event.detail.xhr.responseURL : "";
        if (url.includes('/ejercicio/nuevo')) {
            addOptionToSelects('#set-rows .ej-select', pendingExercise);
            addOptionToSelects('#plantilla-edit-rows .pt-select', pendingExercise);
            pendingExercise = "";
            closeDialog(document.getElementById('exercise-create-dialog'));
        } else if (url.includes('/alimento/nuevo')) {
            addOptionToDatalist('food-list', pendingAlimento);
            pendingAlimento = "";
            closeDialog(document.getElementById('food-create-dialog'));
        }
    });

    setMode(document.getElementById('daily-page')?.dataset.vista, false);
}