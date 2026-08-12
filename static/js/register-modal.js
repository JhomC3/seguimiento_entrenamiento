// register-modal.js — full-screen register modal.
// Owns: #register-modal (open/close), #register-tabs (Alimentación/Entrenamiento),
// #register-fecha-title, #register-modal-body (fetches /registrar/editor).

import { setActivePill } from './segmented-pill.js';

function todayIso() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

function setFechaTitle(iso) {
    const el = document.getElementById('register-fecha-title');
    if (!el) return;
    const [y, m, d] = iso.split('-').map(Number);
    el.textContent = d + '/' + m + '/' + String(y % 100).padStart(2, '0');
}

function applyTab() {
    const activeTab = document.querySelector('#register-tabs .pill[aria-pressed="true"]');
    const tab = (activeTab && activeTab.dataset.tab) || 'nutrition';
    const nutrition = document.getElementById('register-nutrition');
    const session = document.getElementById('register-session');
    if (nutrition) nutrition.hidden = tab !== 'nutrition';
    if (session) session.hidden = tab !== 'session';
}

export function openRegisterModal(fechaIso) {
    const modal = document.getElementById('register-modal');
    if (!modal) return;
    const iso = fechaIso || todayIso();
    setFechaTitle(iso);
    modal.dataset.open = '1';
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    const body = document.getElementById('register-modal-body');
    if (body) {
        htmx.ajax('GET', '/registrar/editor?fecha=' + iso, {
            target: body,
            swap: 'innerHTML',
        });
    }
    requestAnimationFrame(function () {
        setActivePill(document.getElementById('register-tabs'), 'nutrition');
        applyTab();
    });
}

export function closeRegisterModal() {
    const modal = document.getElementById('register-modal');
    if (!modal) return;
    modal.dataset.open = '0';
    modal.classList.add('hidden');
    document.body.style.overflow = '';
}

export function initRegisterModal() {
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        if (el.dataset.action === 'open-register-modal') {
            openRegisterModal(el.dataset.fecha || todayIso());
        } else if (el.dataset.action === 'close-register-modal') {
            closeRegisterModal();
        } else if (el.dataset.action === 'set-register-tab') {
            setActivePill(el.closest('.pills-track'), el.dataset.tab);
            applyTab();
        } else if (el.dataset.action === 'toggle-plantillas') {
            const section = document.getElementById('register-plantillas');
            if (section) section.classList.toggle('hidden');
        }
    });

    document.addEventListener('keydown', function (e) {
        const modal = document.getElementById('register-modal');
        if (!modal || modal.dataset.open !== '1') return;
        if (e.key === 'Escape') closeRegisterModal();
    });

    // La navegación de fechas del modal refresca el título.
    document.body.addEventListener('htmx:afterSwap', function (e) {
        if (!e.target || e.target.id !== 'register-modal-body') return;
        const selected = document.querySelector('#register-modal-body .date-num.selected');
        if (selected) setFechaTitle(selected.dataset.iso);
        requestAnimationFrame(function () { applyTab(); });
    });
}
