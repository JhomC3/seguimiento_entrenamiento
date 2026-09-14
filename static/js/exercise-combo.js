// exercise-combo.js — combobox accesible del alta de ejercicio.
// La lista SIEMPRE se pinta debajo del campo (CSS `.combo-list`, top:100%):
// el `<datalist>` nativo lo abría el navegador hacia arriba sin control.
// Delegado a document: sobrevive a los swaps OOB del form. Idempotente.
// Public API: initExerciseCombo.

const FORM_SEL = '#exercise-create-form';
const INPUT_SEL = FORM_SEL + ' input[name="grupo_muscular"]';
const LIST_SEL = '.combo-list';

function comboInput(el) {
    return el && el.closest ? el.closest('.combo-wrap')?.querySelector('input[name="grupo_muscular"]') : null;
}

function comboList(input) {
    const wrap = input && input.closest ? input.closest('.combo-wrap') : null;
    return wrap ? wrap.querySelector(LIST_SEL) : null;
}

function comboHidden(input) {
    const form = input && input.closest ? input.closest('form') : null;
    return form ? form.querySelector('input[name="categoria"]') : null;
}

function comboOptions(input) {
    const list = comboList(input);
    return list ? Array.from(list.querySelectorAll('[role="option"]')) : [];
}

function syncHidden(input) {
    const hidden = comboHidden(input);
    if (!hidden) return;
    const want = (input.value || '').trim().toLowerCase();
    const hit = comboOptions(input).find(function (o) {
        return (o.dataset.value || '').toLowerCase() === want;
    });
    hidden.value = hit ? (hit.dataset.categoria || '') : '';
}

function isOpen(input) {
    const list = comboList(input);
    return !!list && !list.hidden;
}

function setActive(input, option) {
    comboOptions(input).forEach(function (o) {
        const on = o === option;
        o.setAttribute('aria-selected', on ? 'true' : 'false');
        o.classList.toggle('active', on);
    });
    if (option) input.setAttribute('aria-activedescendant', option.id);
    else input.removeAttribute('aria-activedescendant');
}

function openCombo(input) {
    const list = comboList(input);
    if (!list) return;
    filterCombo(input);
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    const wrap = input.closest('.combo-wrap');
    if (wrap && wrap.scrollIntoView) wrap.scrollIntoView({ block: 'nearest' });
}

function closeCombo(input) {
    const list = comboList(input);
    if (!list || list.hidden) return;
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    setActive(input, null);
}

function closeAllCombos() {
    document.querySelectorAll(FORM_SEL + ' input[name="grupo_muscular"]').forEach(closeCombo);
}

function filterCombo(input) {
    const q = (input.value || '').trim().toLowerCase();
    comboOptions(input).forEach(function (o) {
        const match = !q || (o.dataset.value || '').toLowerCase().indexOf(q) !== -1;
        o.hidden = !match;
    });
}

function visibleOptions(input) {
    return comboOptions(input).filter(function (o) { return !o.hidden; });
}

function pickOption(input, option) {
    if (!option) return;
    input.value = option.dataset.value || '';
    syncHidden(input);
    closeCombo(input);
    // El focus() tras clic re-dispararía focusin y reabriría: suprimir una vez.
    input.dataset.comboPicked = String(Date.now());
    input.focus();
}

export function initExerciseCombo() {
    if (document.body.dataset.exerciseComboReady) return;
    document.body.dataset.exerciseComboReady = '1';

    document.addEventListener('focusin', function (e) {
        const input = e.target.closest ? e.target.closest(INPUT_SEL) : null;
        if (!input) return;
        const picked = parseInt(input.dataset.comboPicked || '0', 10) || 0;
        if (Date.now() - picked < 500) {
            delete input.dataset.comboPicked;
            return;
        }
        openCombo(input);
    });

    document.addEventListener('input', function (e) {
        const input = e.target.closest ? e.target.closest(INPUT_SEL) : null;
        if (!input) return;
        filterCombo(input);
        syncHidden(input);
        const list = comboList(input);
        if (list && list.hidden) openCombo(input);
    });

    document.addEventListener('click', function (e) {
        const option = e.target.closest ? e.target.closest(LIST_SEL + ' [role="option"]') : null;
        if (option) {
            pickOption(comboInput(option), option);
            return;
        }
        if (!e.target.closest || !e.target.closest('.combo-wrap')) closeAllCombos();
    });

    document.addEventListener('keydown', function (e) {
        const input = e.target.closest ? e.target.closest(INPUT_SEL) : null;
        if (!input) return;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!isOpen(input)) {
                openCombo(input);
                setActive(input, visibleOptions(input)[0] || null);
                return;
            }
            const opts = visibleOptions(input);
            if (!opts.length) return;
            const idx = opts.indexOf(comboOptions(input).find(function (o) {
                return o.classList.contains('active');
            }));
            const next = e.key === 'ArrowDown'
                ? opts[(idx + 1) % opts.length]
                : opts[(idx - 1 + opts.length) % opts.length];
            setActive(input, next);
        } else if (e.key === 'Enter') {
            if (isOpen(input)) {
                const active = comboOptions(input).find(function (o) {
                    return o.classList.contains('active');
                });
                if (active) {
                    e.preventDefault();
                    pickOption(input, active);
                }
            }
        } else if (e.key === 'Escape') {
            if (isOpen(input)) {
                e.preventDefault();
                e.stopPropagation();
                closeCombo(input);
            }
        }
    });
}
