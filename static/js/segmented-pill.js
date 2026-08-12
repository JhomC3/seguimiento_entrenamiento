// segmented-pill.js — segmented pill navigation with sliding active pill.
// Owns: .pills-track/.pill/.pills-slider; positions the slider via transform
// (no inline left/width styles in HTML). Emits analysis:level-changed on the
// #analysis-chart-wrap element so the analysis view can refetch.

const SLIDER_SELECTOR = '.pills-slider';

export function positionSlider(track) {
    const slider = track.querySelector(SLIDER_SELECTOR);
    const active = track.querySelector('.pill[aria-pressed="true"]');
    if (!slider) return;
    if (!active) {
        slider.style.transform = 'translateX(0px)';
        slider.style.width = '0px';
        slider.style.opacity = '0';
        return;
    }
    slider.style.opacity = '1';
    slider.style.width = active.offsetWidth + 'px';
    slider.style.transform = 'translateX(' + active.offsetLeft + 'px)';
}

function selectPill(track, pill) {
    track.querySelectorAll('.pill').forEach((p) => p.setAttribute('aria-pressed', 'false'));
    pill.setAttribute('aria-pressed', 'true');
    positionSlider(track);
}

export function setActivePill(track, valueAttr) {
    const pill = track.querySelector(`.pill[data-value="${valueAttr}"]`);
    if (pill) selectPill(track, pill);
}

export function initSegmentedPills() {
    document.addEventListener('click', (e) => {
        const pill = e.target.closest('.pill[data-action="set-level"]');
        if (!pill) return;
        const track = pill.closest('.pills-track');
        if (!track) return;
        if (pill.getAttribute('aria-pressed') === 'true') return;
        selectPill(track, pill);
        const chartWrap = document.getElementById('analysis-chart-wrap');
        if (chartWrap) {
            chartWrap.dispatchEvent(
                new CustomEvent('analysis:level-changed', { detail: { nivel: pill.dataset.nivel } })
            );
        }
    });

    // Reposiciona el slider tras cualquier render (htmx swap o reflow).
    document.body.addEventListener('htmx:load', (e) => {
        e.target.querySelectorAll?.('.pills-track').forEach(positionSlider);
    });

    // Inicial: reposiciona todos los sliders ya renderizados.
    requestAnimationFrame(() => {
        document.querySelectorAll('.pills-track').forEach(positionSlider);
    });
}
