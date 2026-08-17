"""Gate de consistencia de la UI: los templates usan el vocabulario canónico
de componentes (static/css/components.css) y no reintroducen utilidades de
color inline repetidas, micro-tipografía ni colores literales en CSS.

Refleja scripts/audit_consistency.py para que CI lo ejecute vía pytest.
"""

from pathlib import Path

from scripts.audit_consistency import audit_css, audit_templates

ROOT = Path(__file__).resolve().parents[1]


def test_templates_use_canonical_component_vocabulary():
    issues = audit_templates()
    assert issues == [], "Patrones inline prohibidos:\n" + "\n".join(issues)


def test_css_has_no_literal_colors_outside_tokens():
    issues = audit_css()
    assert issues == [], "Colores literales en CSS de componentes:\n" + "\n".join(issues)
