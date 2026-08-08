"""RM-adjusted formula: single source of truth and JS regression guard."""

from pathlib import Path

from src.metrics_engine import RM_FACTOR, rm_ajustado


def test_rm_ajustado_escalar():
    assert rm_ajustado(90, 7, 1.2) == 90 * (1 + 0.0333 * (7 + 1 + 1.2))


def test_factor_constante():
    assert RM_FACTOR == 0.0333


def test_editor_js_usa_misma_constante_rm():
    src = Path("static/js/editor.js").read_text()
    assert "0.0333" in src
