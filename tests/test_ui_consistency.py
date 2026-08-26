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


def test_index_html_div_balance():
    """Regresión Fase 2: el shell del dashboard debe tener <div> balanceados.

    Un cierre de más hace que el navegador repare el DOM y desplaza selectores
    (bloqueante #1 de la revisión post-Fase 2). Solo cuenta index.html porque
    los parciales se incluyen dentro de shells válidos.
    """
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    # Ignora self-contained tags y comentarios: cuenta solo aperturas/cierres.
    abiertos = html.count("<div")
    cerrados = html.count("</div>")
    assert abiertos == cerrados, f"index.html desbalanceado: {abiertos} <div> vs {cerrados} </div>"
