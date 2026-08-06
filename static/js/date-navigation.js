// date-navigation.js — owns: date strip selection, unsaved-change confirmation, dots.
// DOM owned: #date-navigator, #date-strip, .date-num, .date-dot.
// Public API: doNav, requestNavigate, updateDateDot, selectDate, scrollDates, jumpDate.

import { getPendingNav, isDirty, setCurrentIso, setPendingNav, showConfirmDialog } from './state.js';
import { submitSave } from './editor.js';

export function doNav(iso, force) {
    if (!iso) return;
    if (force) {
        setPendingNav(null);
    } else if (getPendingNav()) {
        return;
    }
    const actions = document.getElementById('edit-actions');
    if (actions) actions.classList.add('invisible');
    setCurrentIso(iso);
    document.querySelectorAll('.date-num.selected').forEach(b => b.classList.remove('selected'));
    const btn = document.querySelector(`.date-num[data-iso="${iso}"]`);
    if (btn) btn.classList.add('selected');
    htmx.ajax('GET', `/fecha/editor?fecha=${iso}`, { target: '#session-editor-wrap', swap: 'innerHTML' });
    if (btn) btn.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
}

export function requestNavigate(iso) {
    if (isDirty()) {
        setPendingNav(iso);
        showConfirmDialog(
            function () { submitSave(); },
            function () { doNav(iso, true); }
        );
    } else {
        doNav(iso);
    }
}

export function selectDate(btn, iso) {
    requestNavigate(iso);
}

export function scrollDates(dir) {
    const strip = document.getElementById('date-strip');
    if (strip) strip.scrollBy({ left: dir * strip.clientWidth * 0.8, behavior: 'smooth' });
}

export function jumpDate(iso) {
    if (!iso) return;
    requestNavigate(iso);
}

export function updateDateDot(fecha, has) {
    const btn = document.querySelector(`.date-num[data-iso="${fecha}"]`);
    if (!btn) return;
    const dot = btn.querySelector('.date-dot');
    if (has) {
        if (!dot) btn.insertAdjacentHTML('beforeend', '<span class="date-dot"></span>');
    } else if (dot) {
        dot.remove();
    }
}
