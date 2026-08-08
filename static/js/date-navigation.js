// date-navigation.js — owns: date strip selection, unsaved-change confirmation, dots.
// DOM owned: #date-navigator, #date-strip, .date-num, .date-dot.
// Public API: initDateNavigation, doNav, requestNavigate, updateDateDot.

import { getCurrentIso, getPendingNav, isDirty, setCurrentIso, setPendingNav, showConfirmDialog } from './state.js';
import { submitSave } from './editor.js';
import { nutritionIsDirty, requestNutritionNav } from './nutrition-editor.js';

let inFlightIso = null;

export function doNav(iso, force) {
    if (!iso) return;
    if (force) {
        setPendingNav(null);
    } else if (getPendingNav()) {
        return;
    }
    if (inFlightIso === iso) return;
    inFlightIso = iso;
    const actions = document.getElementById('edit-actions');
    if (actions) actions.classList.add('invisible');
    setCurrentIso(iso);
    document.querySelectorAll('.date-num.selected').forEach(b => b.classList.remove('selected'));
    const btn = document.querySelector(`.date-num[data-iso="${iso}"]`);
    if (btn) btn.classList.add('selected');
    const jobs = [
        htmx.ajax('GET', `/fecha/editor?fecha=${iso}`, { target: '#session-editor-wrap', swap: 'innerHTML' }),
    ];
    if (document.getElementById('nutrition-editor-wrap')) {
        jobs.push(
            htmx.ajax('GET', `/alimentacion/editor?fecha=${iso}`, { target: '#nutrition-editor-wrap', swap: 'innerHTML' })
        );
    }
    Promise.all(jobs)
        .then(function () { inFlightIso = null; })
        .catch(function () { inFlightIso = null; });
    if (btn) btn.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
}

export function requestNavigate(iso) {
    if (isDirty()) {
        setPendingNav(iso);
        showConfirmDialog(
            function () { submitSave(); },
            function () { doNav(iso, true); }
        );
    } else if (nutritionIsDirty()) {
        requestNutritionNav(iso);
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

function shiftDay(days) {
    const iso = getCurrentIso();
    if (!iso) return;
    const d = new Date(iso + 'T00:00:00');
    d.setDate(d.getDate() + days);
    requestNavigate(d.toISOString().slice(0, 10));
}

export function initDateNavigation() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'select-date') {
            requestNavigate(el.dataset.iso);
        } else if (el.dataset.action === 'goto-session') {
            requestNavigate(el.dataset.iso);
        } else if (el.dataset.action === 'jump-date') {
            jumpDate(el.dataset.iso);
        } else if (el.dataset.action === 'scroll-dates') {
            scrollDates(parseInt(el.dataset.dir, 10) || 0);
        }
    });

    document.addEventListener('change', function (e) {
        const el = e.target.closest('[data-action="jump-date-input"]');
        if (el && el.value) requestNavigate(el.value);
    });

    document.addEventListener('keydown', function (e) {
        const inField = e.target.closest && e.target.closest('input, textarea, select');
        if (inField) return;
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            shiftDay(-1);
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            shiftDay(1);
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowLeft') {
            e.preventDefault();
            shiftDay(-7);
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'ArrowRight') {
            e.preventDefault();
            shiftDay(7);
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
