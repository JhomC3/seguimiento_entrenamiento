// templates.js — owns: plantilla (entreno) list, form, apply/delete/edit/reorder, DnD.
// DOM owned: #plantillas-section, #plantillas-list, .pt-card, #plantilla-edit-rows,
// #save-template-form-wrap, #save-template-form, #session-editor (drop target).
// Public API: editorHasData, aplicarPlantilla, eliminarPlantilla, editarPlantilla,
// refreshPlantillas, suggestedTemplateName, syncTemplateEjercicios,
// setEntrenoBtnVisible, openEntrenoForm, guardarPlantillaToggle, confirmEntrenoSave,
// ptAddRow, ptRemoveRow, initTemplateSortable, entrenosOrder, initEntrenoDnD.

import { flashEditorNotice } from './notices.js';
import {
    currentFecha,
    editorEditmode,
    getApplyInFlight,
    getCategoriaMap,
    getDragCard,
    getDragGhost,
    getDragOrderStart,
    getDroppedOnList,
    getDropHandled,
    setApplyInFlight,
    setDragCard,
    setDragGhost,
    setDragOrderStart,
    setDroppedOnList,
    setDropHandled,
    showConfirmDialog,
} from './state.js';

export function editorHasData() {
    return Array.from(document.querySelectorAll('#set-rows .ej-select')).some(sel => sel.value.trim() !== '');
}

export function aplicarPlantilla(id) {
    if (editorEditmode() !== '1') {
        flashEditorNotice('Activa el modo editable primero.', 'error');
        return;
    }
    const fecha = currentFecha();
    if (!fecha) return;
    const key = `${id}|${fecha}`;
    if (getApplyInFlight() === key) return;
    setApplyInFlight(key);
    setTimeout(function () { if (getApplyInFlight() === key) setApplyInFlight(null); }, 600);
    htmx.ajax('GET', `/plantilla/aplicar/${id}?fecha=${fecha}`, { target: '#session-editor-wrap', swap: 'none' });
}

export function eliminarPlantilla(id, nombre) {
    if (!confirm(`¿Eliminar el entreno "${nombre}"?`)) return;
    htmx.ajax('POST', `/plantilla/eliminar/${id}`, { target: 'body', swap: 'none' });
}

export function editarPlantilla(id) {
    htmx.ajax('GET', `/plantillas?editar=${id}`, { target: '#plantillas-section', swap: 'innerHTML' });
}

export function refreshPlantillas() {
    htmx.ajax('GET', '/plantillas', { target: '#plantillas-section', swap: 'innerHTML' });
}

export function suggestedTemplateName() {
    const cats = new Set();
    const seen = new Set();
    document.querySelectorAll('#set-rows .ej-select').forEach(sel => {
        const v = sel.value.trim();
        if (!v || seen.has(v.toLowerCase())) return;
        seen.add(v.toLowerCase());
        const c = getCategoriaMap()[v.toLowerCase()];
        if (c) cats.add(c.toUpperCase());
    });
    if (!cats.size) return '';
    const hE = cats.has('EMPUJE'), hT = cats.has('TIRON'), hP = cats.has('PIERNA');
    if (hP && (hE || hT)) return 'Full Body';
    if (hE && hT) return 'Torso';
    if (hT) return 'Jalón';
    if (hE) return 'Empuje';
    if (hP) return 'Pierna';
    return 'Core';
}

export function syncTemplateEjercicios() {
    const wrap = document.getElementById('save-template-form-wrap');
    const form = wrap && document.getElementById('save-template-form');
    if (!form || wrap.classList.contains('hidden')) return;
    form.querySelectorAll('input[name="ejercicio"]').forEach(el => el.remove());
    const seen = new Set();
    document.querySelectorAll('#set-rows .ej-select').forEach(sel => {
        const v = sel.value.trim();
        if (!v || seen.has(v.toLowerCase())) return;
        seen.add(v.toLowerCase());
        const inp = document.createElement('input');
        inp.type = 'hidden';
        inp.name = 'ejercicio';
        inp.value = v;
        form.appendChild(inp);
    });
}

export function setEntrenoBtnVisible(visible) {
    const btn = document.querySelector('#session-editor .save-template-btn');
    if (btn) btn.hidden = !visible;
}

export function openEntrenoForm() {
    const wrap = document.getElementById('save-template-form-wrap');
    if (!wrap) return;
    const input = wrap.querySelector('input[name="nombre"]');
    if (input && !input.value) input.value = suggestedTemplateName();
    wrap.classList.remove('hidden');
    setEntrenoBtnVisible(false);
    syncTemplateEjercicios();
    if (input) input.focus();
}

export function guardarPlantillaToggle(force) {
    const wrap = document.getElementById('save-template-form-wrap');
    if (!wrap) return;
    if (force === false) {
        wrap.classList.add('hidden');
        setEntrenoBtnVisible(true);
        return;
    }
    if (editorEditmode() !== '1') {
        flashEditorNotice('Activa el modo editable primero.', 'error');
        return;
    }
    if (!editorHasData()) {
        flashEditorNotice('No hay nada que guardar como entreno.', 'error');
        return;
    }
    if (wrap.classList.contains('hidden')) {
        document.getElementById('confirm-msg').textContent = '¿Desea crear un nuevo entrenamiento?';
        showConfirmDialog(function () { openEntrenoForm(); }, null);
    } else {
        wrap.classList.add('hidden');
        setEntrenoBtnVisible(true);
    }
}

export function confirmEntrenoSave() {
    const form = document.getElementById('save-template-form');
    if (!form) return;
    const nombre = form.querySelector('input[name="nombre"]').value.trim();
    if (!nombre) {
        form.requestSubmit();
        return;
    }
    const exists = Array.from(document.querySelectorAll('#plantillas-section [data-pt-nombre]'))
        .some(el => el.dataset.ptNombre.toLowerCase() === nombre.toLowerCase());
    document.getElementById('confirm-msg').textContent = exists
        ? `Ya existe el entreno '${nombre}'. ¿Reemplazarlo?`
        : `¿Guardar el entreno '${nombre}'?`;
    showConfirmDialog(function () {
        form.requestSubmit();
    }, null);
}

export function ptAddRow(btn) {
    const container = document.getElementById('plantilla-edit-rows');
    const first = container && container.querySelector('.pt-row');
    if (!container || !first) return;
    const clone = first.cloneNode(true);
    clone.querySelector('.pt-select').value = '';
    container.appendChild(clone);
}

export function ptRemoveRow(btn) {
    const container = document.getElementById('plantilla-edit-rows');
    if (!container || container.querySelectorAll('.pt-row').length <= 1) return;
    btn.closest('.pt-row').remove();
}

export function initTemplateSortable() {
    const container = document.getElementById('plantilla-edit-rows');
    if (container && typeof Sortable !== 'undefined' && !container.dataset.sortableReady) {
        container.dataset.sortableReady = '1';
        Sortable.create(container, {
            animation: 150,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            filter: 'input, select, button',
            preventOnFilter: false,
        });
    }
}

export function entrenosOrder() {
    return Array.from(document.querySelectorAll('#plantillas-list .pt-card')).map(el => el.dataset.ptId);
}

/* ---------- Drag & drop nativo de entrenos: lista -> reordenar, panel -> aplicar ---------- */
export function getDragAfterElement(container, y) {
    const cards = Array.from(container.querySelectorAll('.pt-card:not(.dragging)'));
    return cards.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return { offset, element: child };
        return closest;
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

export function restoreDragOrder() {
    const dragCard = getDragCard();
    const dragOrderStart = getDragOrderStart();
    if (!dragCard || !dragOrderStart || !dragCard.parentElement) return;
    const list = dragCard.parentElement;
    const cards = Array.from(list.querySelectorAll('.pt-card'));
    cards.sort(function (a, b) {
        return dragOrderStart.indexOf(a.dataset.ptId) - dragOrderStart.indexOf(b.dataset.ptId);
    });
    cards.forEach(function (c) { list.appendChild(c); });
}

export function persistDragOrder() {
    const params = new URLSearchParams();
    entrenosOrder().forEach(id => params.append('id', id));
    fetch('/plantilla/reordenar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
    });
}

export function initEntrenoDnD() {
    const panel = document.getElementById('session-editor');
    const list = document.getElementById('plantillas-list');
    if (!panel) return;

    if (!panel.dataset.dndPanelReady) {
        panel.dataset.dndPanelReady = '1';

        panel.addEventListener('dragover', function (e) {
            if (!getDragCard()) return;
            const ok = editorEditmode() === '1';
            panel.classList.toggle('drop-target', ok);
            if (ok) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            }
        });

        panel.addEventListener('dragleave', function (e) {
            if (!getDragCard()) return;
            if (!panel.contains(e.relatedTarget)) panel.classList.remove('drop-target');
        });

        panel.addEventListener('drop', function (e) {
            panel.classList.remove('drop-target');
            if (!getDragCard()) return;
            if (editorEditmode() !== '1') return;
            const id = e.dataTransfer.getData('text/plain');
            if (!id || getDropHandled()) return;
            setDropHandled(true);
            e.preventDefault();
            const st = document.getElementById('editor-state');
            if (st && st.dataset.hasData === '1') {
                document.getElementById('confirm-msg').textContent = '¿Reemplazar el entrenamiento del día?';
                showConfirmDialog(function () { aplicarPlantilla(parseInt(id, 10)); }, null);
            } else {
                aplicarPlantilla(parseInt(id, 10));
            }
        });
    }

    if (!list || list.dataset.dndListReady) return;
    list.dataset.dndListReady = '1';
    list.querySelectorAll('.pt-card').forEach(card => { card.draggable = true; });

    list.addEventListener('dragstart', function (e) {
        const card = e.target.closest('.pt-card');
        if (!card) return;
        if (e.target.closest('input, select, button')) { e.preventDefault(); return; }
        e.dataTransfer.setData('text/plain', card.dataset.ptId);
        e.dataTransfer.effectAllowed = 'move';
        const ghost = getDragGhost();
        if (ghost) ghost.remove();
        const rect = card.getBoundingClientRect();
        const newGhost = card.cloneNode(true);
        newGhost.style.cssText = 'position:absolute;left:-9999px;top:0;pointer-events:none;';
        document.body.appendChild(newGhost);
        e.dataTransfer.setDragImage(newGhost, e.clientX - rect.left, e.clientY - rect.top);
        card.classList.add('dragging');
        setDragCard(card);
        setDragOrderStart(entrenosOrder());
        setDroppedOnList(false);
        setDropHandled(false);
        setDragGhost(newGhost);
    });

    list.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!getDragCard()) return;
        const after = getDragAfterElement(list, e.clientY);
        if (after == null) list.appendChild(getDragCard());
        else list.insertBefore(getDragCard(), after);
    });

    list.addEventListener('drop', function (e) {
        e.preventDefault();
        setDroppedOnList(true);
    });

    list.addEventListener('dragend', function () {
        const dragCard = getDragCard();
        if (dragCard) dragCard.classList.remove('dragging');
        if (getDroppedOnList()) {
            if (getDragOrderStart() && getDragOrderStart().join() !== entrenosOrder().join()) {
                persistDragOrder();
            }
        } else {
            restoreDragOrder();
        }
        setDragCard(null);
        setDragOrderStart(null);
        setDroppedOnList(false);
        setDropHandled(false);
        const ghost = getDragGhost();
        if (ghost) {
            ghost.remove();
            setDragGhost(null);
        }
        panel.classList.remove('drop-target');
    });
}
