// layer-toggles.js — chart layer chips with localStorage persistence.
// Owns: #layer-toggles (.layer-chip[aria-pressed]); emits analysis:layers-changed
// on #analysis-chart-wrap. State: gym.layers.v1 (array of layer ids).

const LS_KEY = 'gym.layers.v1';
const DEFAULT_LAYERS = ['pfr', 'volumen', 'peso'];

export function getActiveLayers() {
    try {
        const raw = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
        if (Array.isArray(raw) && raw.length > 0) return raw;
    } catch (err) {
        // estado corrupto: se ignora y se usa el default
    }
    return [...DEFAULT_LAYERS];
}

function saveLayers(layers) {
    localStorage.setItem(LS_KEY, JSON.stringify(layers));
}

export function syncLayerChips() {
    const active = getActiveLayers();
    document.querySelectorAll('#layer-toggles .layer-chip').forEach((chip) => {
        chip.setAttribute('aria-pressed', String(active.includes(chip.dataset.layer)));
    });
}

export function initLayerToggles() {
    document.addEventListener('click', (e) => {
        const chip = e.target.closest('#layer-toggles .layer-chip');
        if (!chip) return;
        const layer = chip.dataset.layer;
        if (!layer) return;
        let active = getActiveLayers();
        if (active.includes(layer)) {
            if (active.length === 1) return; // nunca desactivar la última capa
            active = active.filter((l) => l !== layer);
        } else {
            active = [...active, layer];
        }
        saveLayers(active);
        syncLayerChips();
        const chartWrap = document.getElementById('analysis-chart-wrap');
        if (chartWrap) {
            chartWrap.dispatchEvent(
                new CustomEvent('analysis:layers-changed', { detail: { layers: active } })
            );
        }
    });

    document.body.addEventListener('htmx:load', (e) => {
        if (e.target && e.target.id === 'layer-toggles') syncLayerChips();
    });

    syncLayerChips();
}
