// date-navigation.js — owns: date strip selection, unsaved-change confirmation, dots.
// DOM owned: #date-navigator, #date-strip, .date-num, .date-dot.
// Public API: initDateNavigation, doNav, requestNavigate, updateDateDot.

import { getCicloStart, getCurrentIso, getPendingNav, isDirty, setCurrentIso, setPendingNav, showConfirmDialog } from './state.js';
import { submitSave } from './editor.js';
import { nutritionIsDirty, requestNutritionNav } from './nutrition-editor.js';

const DIA_MAP = {
    0: 'DOMINGO',
    1: 'LUNES',
    2: 'MARTES',
    3: 'MIERCOLES',
    4: 'JUEVES',
    5: 'VIERNES',
    6: 'SABADO',
};

let inFlightIso = null;

function updateDateTitle(iso) {
    const el = document.getElementById('session-date-title');
    if (!el) return;
    const [y, m, d] = iso.split('-').map(Number);
    const fecha = new Date(Date.UTC(y, m - 1, d));
    const h3 = el.querySelector('h3');
    if (h3) h3.textContent = DIA_MAP[fecha.getUTCDay()] + ' ' + d + '/' + m + '/' + String(y % 100).padStart(2, '0');
    const span = el.querySelector('span');
    if (!span) return;
    const start = getCicloStart();
    let semana = 1;
    if (start) {
        const [sy, sm, sd] = start.split('-').map(Number);
        const s = new Date(Date.UTC(sy, sm - 1, sd));
        const lunes = new Date(s);
        lunes.setUTCDate(s.getUTCDate() - ((s.getUTCDay() + 6) % 7));
        semana = Math.max(1, Math.floor((fecha - lunes) / 86400000 / 7) + 1);
    }
    span.textContent = 'Semana ' + semana;
}

export function doNav(iso, force) {
    if (!iso) return;
    if (force) {
        setPendingNav(null);
    } else if (getPendingNav()) {
        return;
    }
    if (inFlightIso === iso) return;
    inFlightIso = iso;
    updateDateTitle(iso);
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
        .then(function () {
            inFlightIso = null;
            // El refresh de cardio va DESPUÉS de los editores: htmx serializa los
            // requests del mismo elemento fuente (body) en una cola "last", y un
            // tercer ajax simultáneo habría reemplazado al de alimentación en cola.
            if (document.getElementById('cardio-day')) {
                htmx.ajax('GET', `/cardio/day?fecha=${iso}`, { target: '#cardio-day', swap: 'innerHTML' });
            }
        })
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
    // Las flechas navegan la VENTANA (15 días por salto): el servidor
    // re-renderiza el navigator centrado en la nueva selección.
    const iso = getCurrentIso();
    if (!iso) return;
    const d = new Date(iso + 'T00:00:00');
    d.setDate(d.getDate() + dir * 15);
    const next = d.toISOString().slice(0, 10);
    if (document.getElementById('session-form') && isDirty()) {
        setPendingNav(next);
    } else if (document.getElementById('nutrition-form') && nutritionIsDirty()) {
        requestNutritionNav(next);
    } else {
        doNav(next);
    }
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
        // Las flechas solo actúan cuando el foco está dentro del navigator.
        const inNav = e.target.closest && e.target.closest('#date-navigator');
        if (!inNav) return;
        const inField = e.target.closest('input, textarea, select');
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
