"""Frontend budget gates: first-party size limits, fingerprinting, lazy Plotly.

Constants se fijan tras la remediación de 2026-08-15 y se revisan solo con un
cambio intencional de presupuesto (commit dedicado).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Presupuestos first-party (bytes, post-remediación 2026-08-15).
# Revisado 2026-08-25: drawer móvil + ResizeObserver + altura dinámica
# añaden ~2 KB intencionales (Fase 2 visual).
# Revisado 2026-08-26: TAREA 3 comparación de puntos (+~11 KB, highlight + panel)
# requiere ~185 KB; se eleva a 190 KB para no bloquear feature (commit dedicado).
# Revisado 2026-08-28: UX-2 tooltip propio (+2.2K CSS, +5K JS) → 85K aggregate.
# Revisado 2026-09-02: Diario standalone + navegación común (workspace-nav) y
# estados vacíos añaden ~0.7K CSS legítimos → 86K aggregate.
# Revisado 2026-09-04: remediación UI/UX (skip-link, workspace-brand, sticky
# nutrición 3 filas, hit-areas 24px, nutri/chart/splits canónicos) añade ~2K
# legítimos → 89K aggregate.
# Revisado 2026-09-08: botón de sugerencia con glow (btn-suggest, +217 B
# legítimos) supera los 34K por poco → individual a 35K.
# Revisado 2026-09-12: combo custom accesible del alta (siempre hacia abajo,
# evita abrir hacia arriba del datalist nativo, +~0.9K CSS) → 36K.
CSS_INDIVIDUAL_MAX = 36 * 1024  # components.css ~35.8K tras combo custom
# Revisado 2026-09-08: lo mismo empuja el agregado (~91.4K) → 90K.
# Revisado 2026-09-10: segunda gráfica del dashboard (tendencia nutricional
# kcal+peso MA7: shell + estilos propios ~1K) → 91K.
# Revisado 2026-09-11: separación estricta HIIT (placeholder transparente en
# readonly para el fantasma "s" de Desc, ~0.2K) → 92K.
# Revisado 2026-09-12: combo custom del alta (+~0.9K CSS) → 93K.
# Revisado 2026-09-16: píldora flotante de acciones en ambos editores +
# Alimento/Cantidad fijas + scrollbar gruesa + altura de cabecera clavada
# (lote nutri-scroll, ~+2.3K) → 98K.
# Revisado 2026-09-17: estabilidad del Diario (fallbacks de altura por editor,
# min-height del banner de sugerencia, Cantidad 92px sin spinners, ~+0.7K) → 99K.
# Revisado 2026-09-17 (2): foco interior en celdas (anillo sin recorte) +
# rotación de fingerprint v2/v3, ~+0.4K → 100K.
# Revisado 2026-09-18: sección Salud en catálogo (solo separación visual, ~+0.3K) → 100K.
CSS_AGGREGATE_MAX = (
    100 * 1024
)  # ~60K → 84K tooltip → 86K Diario → 89K remediación → 90K sugerencia → 91K nutrición → 92K HIIT-estricto → 93K combo-custom → 95K nutri-scroll → 98K nutri-pill+sticky
JS_INDIVIDUAL_MAX = 64 * 1024
# Revisado 2026-09-04: remediación UI/UX (drawer por breakpoint, cardio paralelo
# con aviso, dirty-check Cancel, 9 nutrientes, copy-day, submit splits) +~8K → 200K.
# Revisado 2026-09-08: filas HIIT del editor (toggle kg/reps/rir ↔
# velocidad/dificultad) +~1K → 201K.
# Revisado 2026-09-10: render genérico de gráficas + tendencia nutricional
# (segunda serie Plotly con observer propio, ~1.4K) → 203K.
# Revisado 2026-09-10: tooltip cristal compartido + customdata nutricional
# y bloques de una fila con swatch (~1.5K) → 205K.
# Revisado 2026-09-10: Ctrl+Z local R1+R2 (historial por campo en state.js;
# el atajo ya no llama al undo global: lo guardado no se altera, ~3.2K) → 209K.
# Revisado 2026-09-11: separación estricta HIIT (modo de sesión, cabeceras
# dinámicas y bloqueo anti-mezcla en editor.js + nombre HIIT en templates.js,
# ~+3K) → 212K.
# Revisado 2026-09-12: autofill por último ejercicio (ordinal por serie,
# anti-carrera y herencia en row-add en editor.js, ~+3K) + texto del banner de
# sugerencia (~+0.3K CSS) → 216K.
# Revisado 2026-09-12: alta de ejercicio en splits (OOB `#splits-catalog` +
# re-init de Sortable y re-filtro en splits.js, ~+0.3K) → 217K.
# Revisado 2026-09-12: categoría automática (listener change en splits.js y
# diario.js, ~+0.5K) → 218K.
# Revisado 2026-09-12: grupo como texto libre con mapa JSON (sync en input y
# change, ~+0.4K) → 219K.
# Revisado 2026-09-12: combo custom accesible del alta (siempre hacia abajo,
# evita abrir hacia arriba del datalist nativo, ~+3K JS + wrapping relativo)
# → 223K.
# Revisado 2026-09-15: objetivos de micros editables + fix NaN en Consumido
# (5 inputs DRI/UL, sync live de 9 celdas objetivo, sumas de 9 nutrientes
# en nutrition-editor.js, ~+0.5K) → 224K.
# Revisado 2026-09-17: estabilidad del Diario (pre-ocultado de ambas barras,
# aria-busy + settle de navegación, ~+0.6K) → 225K.
# Revisado 2026-09-17 (2): altura determinista en CSS, medición JS eliminada
# (~-3.7K) → 222K.
# Revisado 2026-09-18: catálogo de métricas con URL + tooltip 2-pos de salud
# (~+2.4K JS en total) → 225K.
# Revisado 2026-09-18 (2): acordeón de grupos de métricas (paridad a11y con el
# catálogo de ejercicios) → 226K.
JS_AGGREGATE_MAX = (
    226 * 1024
)  # ~132K → 165K Fase 2 → ~185K TAREA 3 → ~198K remediación → ~201K HIIT → ~203K nutrición → ~205K tooltip → ~209K ctrlz-local → ~212K HIIT-estricto → ~215K autofill → ~216K splits-alta → ~217K auto-categoria → ~218K grupo-texto → ~223K combo-custom → ~224K micros-editables


def _size(path: Path) -> int:
    return path.stat().st_size


def test_first_party_css_within_budget():
    css_files = sorted((ROOT / "static" / "css").glob("*.css"))
    assert css_files
    aggregate = 0
    for path in css_files:
        assert _size(path) <= CSS_INDIVIDUAL_MAX, f"{path.name}: {_size(path)}"
        aggregate += _size(path)
    assert aggregate <= CSS_AGGREGATE_MAX, aggregate


def test_first_party_js_within_budget():
    js_files = sorted((ROOT / "static" / "js").glob("*.js"))
    assert js_files
    aggregate = 0
    for path in js_files:
        assert _size(path) <= JS_INDIVIDUAL_MAX, f"{path.name}: {_size(path)}"
        aggregate += _size(path)
    assert aggregate <= JS_AGGREGATE_MAX, aggregate


def test_no_new_synchronous_external_scripts():
    """Todo script externo debe ir con defer (o ser cargado bajo demanda)."""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<script\s+src=\"https://[^\"]+\"[^>]*>", base):
        assert "defer" in tag, tag


def test_no_eager_plotly_in_documents():
    """Plotly solo se carga bajo demanda desde chart-interaction.js."""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "cdn.plot.ly" not in base
    assert not re.search(r"<script[^>]*src=\"[^\"]*plotly[^\"]*\"", base), (
        "script de Plotly eager en base.html"
    )
    loader = (ROOT / "static" / "js" / "chart-interaction.js").read_text(encoding="utf-8")
    assert "plotly.js-basic-dist" in loader
    assert "document.createElement('script')" in loader


def test_all_assets_use_fingerprinted_urls():
    """Los assets first-party del base usan static_url(...) (cache immutable)."""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "static_url('css/tailwind.css')" in base
    assert "static_url('css/app.css')" in base
    assert "static_url('js/app.js')" in base
    assert "static_url('favicon.svg')" in base
    # Sin URLs /static desnudas en el base.
    for m in re.findall(r'(?:href|src)="/static/[^"#?]+', base):
        raise AssertionError(f"asset sin fingerprint: {m}")
