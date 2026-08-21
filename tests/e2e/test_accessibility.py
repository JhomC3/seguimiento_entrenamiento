"""Accessibility gates with axe-core (version bloqueada en package.json).

Estados auditados: dashboard vacío, gráfica con datos, diálogo del editor
(popup), confirmación, editor de alimentación y plantillas. Sin supresiones
globales: cada hallazgo de terceros documentado en el comentario del test.
"""

import datetime
import json

from playwright.sync_api import expect

AXE_VERSION = "4.10.0"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"

WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _fill_row(page, row, ejercicio="Press", kg="80", reps="8", rir="1"):
    r = page.locator("#set-rows .set-row").nth(row)
    r.locator("select[name='ejercicio']").select_option(ejercicio)
    r.locator('input[name="kg"]').fill(kg)
    r.locator('input[name="reps"]').fill(reps)
    r.locator('input[name="rir"]').fill(rir)


def _open_popup(page, server):
    page.click('[data-action="open-editor-popup"]')
    page.wait_for_selector("#popup-body #session-editor-wrap", timeout=5000)
    page.wait_for_selector("#popup-body #nutrition-form", timeout=5000)


def _wait_editor_settled(page):
    page.wait_for_timeout(120)


def _goto_date(page, server, iso):
    _open_popup(page, server)
    page.locator(f'#popup-body .date-num[data-iso="{iso}"]').click()
    page.wait_for_timeout(200)


def _run_axe(page):
    # La inyección local (add_script_tag path=) la bloquea la CSP estática;
    # jsdelivr está permitido (Sortable ya se sirve desde ahí) y la versión
    # está bloqueada en package.json (npm ci).
    page.add_script_tag(url=AXE_URL)
    return page.evaluate(
        f"""() => axe.run(document, {{
            runOnly: {{ type: 'tag', values: {json.dumps(WCAG_TAGS)} }}
        }}).then(r => r.violations.map(v => ({{
            id: v.id,
            impact: v.impact,
            nodes: v.nodes.length,
            help: v.help,
            targets: v.nodes.slice(0, 3).map(n => n.target)
        }})))"""
    )


def _assert_no_violations(violations, context):
    assert violations == [], f"axe {context}: {json.dumps(violations, indent=1)}"


def test_axe_empty_dashboard(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _assert_no_violations(_run_axe(page), "dashboard vacío")


def test_axe_popup_editor_and_nutrition(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _open_popup(page, server)
    page.wait_for_timeout(200)
    _assert_no_violations(_run_axe(page), "popup editor + nutrición")


def test_axe_confirmation_dialog(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _open_popup(page, server)
    page.locator("#set-rows .set-row").first.locator('input[name="kg"]').fill("80")
    page.wait_for_timeout(150)
    page.locator(f'.date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_selector("#confirm-modal[open]", timeout=5000)
    _assert_no_violations(_run_axe(page), "confirmación")


def test_axe_populated_chart(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _goto_date(page, server, _iso(1))
    _wait_editor_settled(page)
    _fill_row(page, 0)
    page.locator('input[name="kg"]').first.evaluate("el => el.focus()")
    page.keyboard.press("Enter")
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    page.click("#popup-close")
    page.wait_for_selector("#editor-popup", state="hidden", timeout=5000)
    group = page.locator('#dashboard-catalog .db-group[data-group="Pectoral"]')
    if group.locator('[data-action="toggle-group"]').get_attribute("aria-expanded") != "true":
        group.locator('[data-action="toggle-group"]').click()
        page.wait_for_timeout(120)
    page.locator(
        '#dashboard-catalog [data-action="toggle-muscle"][data-foco="Pectoral"]'
    ).click()
    page.wait_for_selector("#unified-chart-plot .main-svg", timeout=15000)
    _assert_no_violations(_run_axe(page), "gráfica con datos")


def test_axe_templates_page(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _open_popup(page, server)
    page.locator("#session-editor [data-action='toggle-edit']").click()
    page.wait_for_timeout(150)
    _fill_row(page, 0, ejercicio="Press")
    page.locator('[data-action="toggle-template-form"]').click()
    page.wait_for_selector("#confirm-modal[open]", timeout=3000)
    page.keyboard.press("Enter")
    page.wait_for_selector("#save-template-form input[name='nombre']", timeout=3000)
    page.locator('#save-template-form input[name="nombre"]').fill("Empuje A")
    page.locator('#save-template-form input[name="nombre"]').evaluate("el => el.focus()")
    page.keyboard.press("Enter")
    page.wait_for_selector("#confirm-modal[open]", timeout=3000)
    page.keyboard.press("Enter")
    page.wait_for_selector("#plantillas-list .pt-card", timeout=3000)
    _assert_no_violations(_run_axe(page), "plantillas")
