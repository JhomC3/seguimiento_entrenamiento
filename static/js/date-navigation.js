// date-navigation.js — owns: date strip selection, unsaved-change confirmation, dots.
// DOM owned: #date-navigator, #date-strip, .date-num, .date-dot.
// Public API: initDateNavigation, doNav, requestNavigate, updateDateDot.

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

function scrollDates(dir) {
    const strip = document.getElementById('date-strip');
    if (strip) strip.scrollBy({ left: dir * strip.clientWidth * 0.8, behavior: 'smooth' });
}

function jumpDate(iso) {
    if (!iso) return;
    requestNavigate(iso);
}

export function initDateNavigation() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'select-date') {
            requestNavigate(el.dataset.iso);
        } else if (el.dataset.action === 'jump-date') {
            jumpDate(el.dataset.iso);
        } else if (el.dataset.action === 'scroll-dates') {
            scrollDates(parseInt(el.dataset.dir, 10) || 0);
        }
    });

    const sel = document.querySelector('.date-num.selected');
    if (sel) sel.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'auto' });
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
