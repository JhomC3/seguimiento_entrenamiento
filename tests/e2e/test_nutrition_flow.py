"""Browser test del flujo completo del panel de alimentación (crear alimento,
editar día, guardar, recargar, eliminar)."""

from playwright.sync_api import expect


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
    page.click('#alimento-create-form button[type="submit"]')


def test_nutrition_create_edit_save_reload_delete(page, server):
    page.goto(server + "/alimentacion")
    page.wait_for_function("document.body.dataset.appReady === '1'")

    # 1) Alta del alimento en el catálogo
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#alimento-create")).to_contain_text("Nuevo alimento")

    # 2) Editar el día: Avena 120 g -> previsualización 467 kcal
    page.click('[data-action="nutrition-row-add"]')
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    expect(row.locator(".kcal-cell")).to_have_text("467")
    expect(row.locator(".prot-cell")).to_have_text("20")
    expect(page.locator('#nutrition-totals [data-total="kcal"]')).to_have_text("467")

    # 3) Guardar: totales del servidor y estado registrado
    page.click('#nutrition-form button[type="submit"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator('#nutrition-totals [data-total="kcal"]')).to_have_text("467")
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 4) Recargar: la fila persiste
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#nutrition-rows .nutrition-row")).to_have_count(1)
    expect(page.locator('#nutrition-rows input[name="cantidad"]')).to_have_value("120")
    expect(page.locator("#nutrition-rows .kcal-cell")).to_have_text("467")

    # 5) Eliminar el día con confirmación
    page.click('[data-action="nutrition-delete"]')
    expect(page.locator("#confirm-modal")).not_to_have_class("hidden")
    page.click("#confirm-save")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator("#nutrition-rows .nutrition-row")).to_have_count(1)
    expect(page.locator('#nutrition-rows input[name="alimento"]')).to_have_value("")
