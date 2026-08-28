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
CSS_INDIVIDUAL_MAX = 32 * 1024  # tailwind.css ~16K; cada CSS componente muy por debajo
CSS_AGGREGATE_MAX = 85 * 1024  # ~60K → 84K con tooltip
JS_INDIVIDUAL_MAX = 64 * 1024
JS_AGGREGATE_MAX = 190 * 1024  # ~132K → 165K Fase 2 → ~185K TAREA 3


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
