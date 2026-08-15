"""Browser tests: nutrition editor inside the register popup."""

import datetime

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open_popup(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="open-editor-popup"]')
    page.wait_for_selector("#popup-body #nutrition-form", timeout=5000)
    page.wait_for_selector(
        '#popup-body #session-form input[name="fecha"]', state="attached", timeout=5000
    )


def _fill_alimento_form(page):
    page.fill('#alimento-create-form input[name="nombre"]', "Avena")
    page.fill('#alimento-create-form input[name="categoria"]', "Cereal")
    page.fill('#alimento-create-form input[name="kcal"]', "389")
    page.fill('#alimento-create-form input[name="carbohidratos"]', "68")
    page.fill('#alimento-create-form input[name="fibra"]', "10")
    page.fill('#alimento-create-form input[name="proteina"]', "17")
    page.fill('#alimento-create-form input[name="grasa"]', "6.9")
    page.fill('#alimento-create-form input[name="hierro"]', "4.2")
    page.fill('#alimento-create-form input[name="calcio"]', "54")
    page.fill('#alimento-create-form input[name="vitamina_c"]', "0")
    page.fill('#alimento-create-form input[name="vitamina_a"]', "0")
    # htmx.ajax directo: el form se re-renderiza por OOB (#alimento-create) y el
    # click nativo puede escapar de la intercepción bajo carga.
    page.evaluate(
        """() => {
            const form = document.getElementById('alimento-create-form');
            htmx.ajax('POST', '/alimento/nuevo', {
                source: form,
                target: 'body',
                swap: 'none',
            });
        }"""
    )
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)


def test_nutrition_create_edit_save_reload_delete(page, server):
    _open_popup(page, server)

    # 1) Alta del alimento en el catálogo (sidebar)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)

    # 2) Editar el día: Avena 120 g -> previsualización 467 kcal
    page.click('[data-action="nutrition-row-add"]')
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    expect(row.locator(".kcal-cell")).to_have_text("467")
    expect(row.locator(".prot-cell")).to_have_text("20")
    expect(page.locator(".consumed-kcal")).to_have_text("467")
    expect(page.locator(".consumed-grams")).to_have_text("120 g")

    # 3) Parámetros en vivo: peso 69 + kcal 2750 -> prot 104, grasa 76, carb 413
    page.fill("#param-peso", "69")
    page.fill("#param-kcal", "2750")
    expect(page.locator(".target-prot")).to_have_text("104")
    expect(page.locator(".target-fat")).to_have_text("76")
    expect(page.locator(".target-carb")).to_have_text("413")

    # 4) Guardar: persiste filas y parámetros
    page.click('#nutrition-form button[type="submit"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 5) Recargar: la URL trae ?registro y el popup se restaura solo (fila y
    # parámetros persisten; el día queda readonly)
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#popup-body #nutrition-rows .nutrition-row", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="cantidad"]')).to_have_value("120")
    expect(page.locator("#param-peso")).to_have_value("69")
    expect(page.locator(".consumed-kcal")).to_have_text("467")

    # 6) Eliminar el día con confirmación (lápiz desbloquea el modo edición)
    page.click('[data-action="nutrition-toggle-edit"]')
    page.click('[data-action="nutrition-delete"]')
    expect(page.locator("#confirm-modal")).not_to_have_class("hidden")
    page.click("#confirm-save")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator('#nutrition-rows input[name="alimento"]')).to_have_value("")


def _fill_nutrition_day(page):
    row = page.locator("#nutrition-rows .nutrition-row").last
    alimento = row.locator('input[name="alimento"]')
    if alimento.is_disabled():
        page.locator('[data-action="nutrition-toggle-edit"]').evaluate("el => el.click()")
        page.wait_for_selector(
            "#nutrition-rows .nutrition-row input[name='alimento']:not([disabled])", timeout=3000
        )
    alimento.fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")


def _jump_date(page, iso):
    page.evaluate(
        f"const el = document.querySelector('#popup-body #date-jump'); "
        f"el.value = '{iso}'; el.dispatchEvent(new Event('change', {{ bubbles: true }}));"
    )
    page.wait_for_function(
        "document.querySelector('#nutrition-form input[name=\"fecha\"]')?.value !== ''",
    )
    page.wait_for_selector(
        f"#nutrition-form input[name='fecha'][value='{iso}']",
        state="attached",
        timeout=5000,
    )


def _simulate_drag(page, source_sel, target_sel):
    """Dispara dragstart → dragover → drop → dragend con DataTransfer sintético."""
    page.evaluate(
        """([src, tgt]) => {
            const card = document.querySelector(src);
            const target = document.querySelector(tgt);
            const dt = new DataTransfer();
            card.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
            target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
            target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            card.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        }""",
        [source_sel, target_sel],
    )


def test_nutrition_templates_save_reorder_apply(page, server):
    _open_popup(page, server)

    # 1) Guardar plantilla desde el header del editor
    _fill_nutrition_day(page)
    page.click('[data-action="nutrition-toggle-template-form"]')
    page.fill('#save-meal-template-form input[name="nombre"]', "Desayuno")
    page.click('[data-action="confirm-meal-template-save"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-templates")).to_contain_text("Desayuno")

    # 2) Aplicar por drag sobre el panel (otra fecha, sin datos)
    _jump_date(page, _iso(9))
    _simulate_drag(page, "#nutrition-templates .pt-card", "#nutrition-panel")
    # El día prefillado tiene filas: la aplicación exige confirmación.
    page.wait_for_selector("#confirm-modal[open]", timeout=5000)
    page.keyboard.press("Enter")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value("Avena")

    # 3) Reordenar por drag entre tarjetas (crear una segunda plantilla)
    _fill_nutrition_day(page)
    page.click('[data-action="nutrition-toggle-template-form"]')
    page.fill('#save-meal-template-form input[name="nombre"]', "Cena")
    page.click('[data-action="confirm-meal-template-save"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-templates .pt-card")).to_have_count(2)
    _simulate_drag(page, "#nutrition-templates .pt-card:nth-child(2)", "#nutrition-templates")
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#popup-body #nutrition-form", timeout=5000)
    expect(page.locator("#nutrition-templates .pt-card").first).to_contain_text("Cena")


def _save_nutrition(page):
    """Guarda el día vía htmx.ajax (mismo POST /alimentacion/save que el form).

    El click nativo en el submit de un form re-renderizado por OOB puede
    escapar de la intercepción de htmx bajo carga (submits nativos GET); la
    llamada directa a htmx.ajax es determinista y usa el mismo camino AJAX.
    """
    page.evaluate(
        """() => {
            const form = document.getElementById('nutrition-form');
            htmx.ajax('POST', '/alimentacion/save', {
                source: form,
                target: 'body',
                swap: 'none',
            });
        }"""
    )
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)


def test_nutrition_prefill_empty_day(page, server):
    _open_popup(page, server)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    _fill_nutrition_day(page)
    page.fill("#param-peso", "69")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # Día siguiente (vacío): prefill desde el día previo guardado.
    manana = _iso(1)
    _jump_date(page, manana)
    page.wait_for_selector(
        "#nutrition-editor-state[data-has-data='0']", state="attached", timeout=5000
    )
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value(
        "Avena", timeout=5000
    )
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("120")
    expect(page.locator("#param-peso")).to_have_value("69")
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator("body")).to_contain_text("Datos del")

    # Modificar y guardar el día precargado -> pasa a tener datos.
    page.locator('#nutrition-rows input[name="cantidad"]').first.fill("130")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute(
        "data-has-data", "1", timeout=5000
    )
