// date-navigation.js — owns: date strip selection, unsaved-change confirmation, dots.
// DOM owned: #date-navigator, #date-strip, .date-num, .date-dot.
// Public API: initDateNavigation, doNav, requestNavigate, updateDateDot.

import { getCicloStart, getCurrentIso, getPendingNav, isDirty, setCurrentIso, setPendingNav, showConfirmDialog } from './state.js';
import { submitSave } from './editor.js';
import { nutritionIsDirty, requestNutritionNav } from './nutrition-editor.js';
import { showNotice } from './notices.js';

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
    const [y, m, d] = iso.split('-').map(Number);
    const fecha = new Date(Date.UTC(y, m - 1, d));
    // Página independiente del Diario: título propio en formato corto, sin semana.
    const dailyTitle = document.getElementById('daily-date-title');
    if (dailyTitle) {
        dailyTitle.textContent =
            DIA_MAP[fecha.getUTCDay()] + ' '
            + String(d).padStart(2, '0') + '/' + String(m).padStart(2, '0') + '/' + String(y % 100).padStart(2, '0');
        return;
    }
    const el = document.getElementById('session-date-title');
    if (!el) return;
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
    // Pre-oculta AMBAS barras (sesión + nutrición): los swaps llegan en
    // distinto orden y la barra pendiente conservaría el día anterior y
    // parpadearía. `invisible` reserva el hueco (sin layout shift).
    for (const id of ['edit-actions', 'nutrition-edit-actions']) {
        document.getElementById(id)?.classList.add('invisible');
    }
    for (const id of ['session-editor-wrap', 'nutrition-editor-wrap']) {
        document.getElementById(id)?.setAttribute('aria-busy', 'true');
    }
    setCurrentIso(iso);
    document.querySelectorAll('.date-num.selected').forEach(b => {
        b.classList.remove('selected');
        b.removeAttribute('aria-current');
    });
    const btn = document.querySelector(`.date-num[data-iso="${iso}"]`);
    if (btn) {
        btn.classList.add('selected');
        btn.setAttribute('aria-current', 'date');
    }
    const jobs = [
        htmx.ajax('GET', `/fecha/editor?fecha=${iso}`, { target: '#session-editor-wrap', swap: 'innerHTML' }),
    ];
    if (document.getElementById('nutrition-editor-wrap')) {
        jobs.push(
            htmx.ajax('GET', `/alimentacion/editor?fecha=${iso}`, { target: '#nutrition-editor-wrap', swap: 'innerHTML' })
        );
    }
    // Diario: las flechas navegan la ventana (15 días por salto); el carrusel
    // se regenera en cada navegación para que la fecha seleccionada quede
    // siempre visible y nunca se salga de la ventana. El ajax usa como source
    // el propio carrusel: htmx encola las peticiones por elemento fuente con
    // política "last", y un tercer ajax desde body habría descartado el de
    // alimentación en cola (dejando la fecha del editor de comida atrasada).
    if (document.getElementById('daily-page')) {
        const navEl = document.getElementById('date-navigator');
        if (navEl) {
            const vista = document.getElementById('daily-page')?.dataset.vista || 'entrenamiento';
            jobs.push(
                htmx.ajax('GET', `/diario/navigator?fecha=${iso}&vista=${vista}`, {
                    source: navEl,
                    target: '#date-navigator',
                    swap: 'outerHTML',
                })
            );
        }
    }
    // Cardio en paralelo con source propio (#cardio-day): no compite en la cola
    // "last" de body con los editores y las navegaciones rápidas descartan la
    // respuesta obsoleta en vez de pintar el día anterior.
    const cardioEl = document.getElementById('cardio-day');
    if (cardioEl) {
        jobs.push(
            htmx.ajax('GET', `/cardio/day?fecha=${iso}`, {
                source: cardioEl,
                target: '#cardio-day',
                swap: 'innerHTML',
            })
        );
    }
    // Banner de sugerencia con fuente propia (igual que cardio): no compite
    // en la cola "last" de body y las navegaciones rápidas lo descartan.
    const suggEl = document.getElementById('suggestion-banner');
    if (suggEl) {
        jobs.push(
            htmx.ajax('GET', `/sugerencia/banner?fecha=${iso}`, {
                source: suggEl,
                target: '#suggestion-banner',
                swap: 'innerHTML',
            })
        );
    }
    // Asentamiento: las alturas son fijas en CSS, aquí solo se limpia el
    // estado de vuelo (aria-busy) cuando todos los swaps terminaron.
    function settleNavFlight() {
        inFlightIso = null;
        for (const id of ['session-editor-wrap', 'nutrition-editor-wrap']) {
            document.getElementById(id)?.removeAttribute('aria-busy');
        }
    }
    Promise.all(jobs)
        .then(settleNavFlight)
        .catch(function () {
            settleNavFlight();
            showNotice('No se pudo cargar el día. Reintenta.', 'error');
        });
    if (btn) {
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        btn.scrollIntoView({ inline: 'center', block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' });
    }
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

    // Diario: el carrusel se regenera tras cada navegación (las flechas saltan
    // la ventana ±15 días); al re-crearse los botones hay que volver a anclar
    // la vista a la selección para que siga visible.
    if (document.getElementById('daily-page')) {
        document.body.addEventListener('htmx:afterSwap', function (e) {
            const target = e.detail && e.detail.target;
            if (target && target.id === 'date-navigator') {
                const selected = document.querySelector('.date-num.selected');
                if (selected) {
                    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                    selected.scrollIntoView({ inline: 'center', block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' });
                }
            }
        });
    }
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
