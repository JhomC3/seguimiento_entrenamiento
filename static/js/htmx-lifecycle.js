// htmx-lifecycle.js — owns: delegated htmx:* handlers and document-level events.
// It calls module initializers instead of duplicating their logic.
// Public API: initLifecycle.

import { doNav, updateDateDot } from './date-navigation.js';
import {
    fitRowsToPanel,
    handleEditorState,
    initEditorRowSortable,
    recalcRM,
    syncEditButtons,
    syncEditorFromContent,
    updateEditActions,
} from './editor.js';
import { scheduleNotices } from './notices.js';
import { refreshNutritionEditor } from './nutrition-editor.js';
import { refreshNutritionTemplatesDnD } from './nutrition-templates.js';
import {
    confirmEntrenoSave,
    guardarPlantillaToggle,
    initEntrenoDnD,
    initTemplateSortable,
    syncTemplateEjercicios,
} from './templates.js';
import {
    currentFecha,
    editorEditmode,
    getConfirmCbs,
    getPendingNav,
    getPlantillaAppliedPending,
    getSaveRequested,
    hideConfirmDialog,
    isDirty,
    setPendingNav,
    setPlantillaAppliedPending,
    setSaveRequested,
} from './state.js';

export function initLifecycle() {
    document.getElementById('confirm-cancel').addEventListener('click', function () {
        const cbs = getConfirmCbs();
        hideConfirmDialog();
        if (cbs && cbs.onDiscard) cbs.onDiscard();
    });
    document.getElementById('confirm-save').addEventListener('click', function () {
        const cbs = getConfirmCbs();
        hideConfirmDialog();
        if (cbs && cbs.onSave) cbs.onSave();
    });

    // htmx descarta el cuerpo de las respuestas 4xx por defecto, lo que impedía
    // que los avisos de error de dominio (validación, CSRF) llegaran al DOM vía OOB.
    // Se permite el swap solo en 4xx (respuestas propias); los 500 internos se
    // mantienen sin renderizar (log de servidor).
    document.body.addEventListener('htmx:beforeSwap', function (e) {
        const xhr = e.detail && e.detail.xhr;
        if (xhr && xhr.status >= 400 && xhr.status < 500) {
            e.detail.shouldSwap = true;
        }
    });

    document.body.addEventListener('htmx:afterSwap', function (e) {
        scheduleNotices();
        handleEditorState();
        if (e.detail && e.detail.target) {
            if (e.detail.target.id === 'session-editor-wrap') {
                syncEditorFromContent();
                if (document.getElementById('plantilla-applied')) {
                    document.getElementById('plantilla-applied').remove();
                    setPlantillaAppliedPending(true);
                }
                initEditorRowSortable();
                fitRowsToPanel();
            } else if (e.detail.target.id === 'plantillas-section') {
                initTemplateSortable();
            }
        }
    });

    document.body.addEventListener('htmx:afterSettle', function (e) {
        if (!getPlantillaAppliedPending()) return;
        const target = e.detail && e.detail.target;
        if (target && (target.id === 'session-editor-wrap' || target === document.body)) {
            setPlantillaAppliedPending(false);
            const editor = document.getElementById('session-editor');
            if (editor) {
                editor.dataset.baseline = '';
                updateEditActions();
            }
        }
    });

    document.body.addEventListener('htmx:afterRequest', function (e) {
        scheduleNotices();
        handleEditorState();
        initTemplateSortable();
        initEntrenoDnD();
        const ptForm = e.detail && e.detail.elt && e.detail.elt.closest
            ? e.detail.elt.closest('#save-template-form')
            : null;
        if (ptForm && e.detail.successful) {
            guardarPlantillaToggle(false);
        }
        // El editor nutricional se re-renderiza vía OOB (save/delete/undo/nav):
        // re-baseline para el dirty-check y totales tras cada intercambio.
        if (e.detail.successful && document.getElementById('nutrition-form')) {
            refreshNutritionEditor();
        }
        refreshNutritionTemplatesDnD();
        if (getSaveRequested() && document.getElementById('session-form')) {
            setSaveRequested(false);
            const undoRes = document.getElementById('undo-result');
            if (undoRes && undoRes.dataset.fecha) {
                updateDateDot(undoRes.dataset.fecha, undoRes.dataset.hasData === '1');
                undoRes.removeAttribute('data-fecha');
                undoRes.removeAttribute('data-has-data');
            }
            const outcome = document.getElementById('save-outcome');
            if (e.detail.successful && outcome && outcome.dataset.ok === '1') {
                // Los swaps OOB ya están aplicados en afterRequest: pintamos el
                // dot de inmediato (el navegador puede navegar justo después y
                // el estado debe ser visible sin esperar el setTimeout).
                const form = document.getElementById('session-form');
                const fechaInput = form && form.querySelector('input[name="fecha"]');
                const fecha = fechaInput ? fechaInput.value : '';
                const st = document.getElementById('editor-state');
                const hasData = st && st.dataset.hasData !== undefined ? st.dataset.hasData === '1' : null;
                if (hasData !== null) {
                    updateDateDot(fecha, hasData);
                    syncEditButtons();
                }
                setTimeout(function () {
                    recalcRM();
                    syncEditorFromContent();
                    fitRowsToPanel();
                }, 100);
                if (getPendingNav()) {
                    const target = getPendingNav();
                    setPendingNav(null);
                    setTimeout(function () { doNav(target, true); }, 150);
                }
            } else {
                setPendingNav(null);
            }
        }
    });

    document.addEventListener('submit', function (e) {
        const form = e.target.closest('#session-form');
        if (!form) return;
        if (editorEditmode() !== '1') {
            e.preventDefault();
            return;
        }
        setSaveRequested(true);
    }, true);

    document.addEventListener('input', function (e) {
        if (e.target.closest('#session-form')) {
            updateEditActions();
            syncTemplateEjercicios();
        }
    });
    document.addEventListener('change', function (e) {
        if (e.target.closest('#session-form')) {
            updateEditActions();
            syncTemplateEjercicios();
        }
    });

    document.addEventListener('keydown', function (e) {
        const inField = e.target.closest && e.target.closest('input, textarea');
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
            if (inField) return;
            e.preventDefault();
            undoAction();
            return;
        }
        if (e.key === 'Enter' && inField && e.target.closest('#save-template-form input[name="nombre"]')) {
            e.preventDefault();
            confirmEntrenoSave();
        }
    }, true);
}

/* ---------- Deshacer (Ctrl+Z / botón ↶) ---------- */
function undoAction() {
    setSaveRequested(true);
    const fecha = currentFecha();
    htmx.ajax('POST', '/undo', { values: { fecha: fecha }, target: 'body', swap: 'none' });
}
