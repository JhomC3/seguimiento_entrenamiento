"""Browser test del panel de alimentación integrado en la página principal:
crear alimento, editar día, objetivo en vivo, guardar, recargar, eliminar."""

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
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    # 1) El panel está debajo del navegador y el editor de sesión intacto
    expect(page.locator("#nutrition-panel")).to_be_visible()
    expect(page.locator("#nutrition-panel")).to_contain_text("Objetivo")
    expect(page.locator("#nutrition-panel")).to_contain_text("Consumido")

    # 1b) Colapso desde el chevron del header (persiste tras recargar)
    page.click('#nutrition-panel [data-action="toggle-panel-collapse"]')
    expect(page.locator("#nutrition-form")).to_be_hidden()
    page.click('#nutrition-panel [data-action="toggle-panel-collapse"]')
    expect(page.locator("#nutrition-form")).to_be_visible()
    page.click('#nutrition-panel [data-action="toggle-panel-collapse"]')
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#nutrition-form")).to_be_hidden()
    page.click('#nutrition-panel [data-action="toggle-panel-collapse"]')
    expect(page.locator("#nutrition-form")).to_be_visible()

    # 2) Alta del alimento en el catálogo (sidebar)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)

    # 3) Editar el día: Avena 120 g -> previsualización 467 kcal
    page.click('[data-action="nutrition-row-add"]')
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    expect(row.locator(".kcal-cell")).to_have_text("467")
    expect(row.locator(".prot-cell")).to_have_text("20")
    expect(page.locator(".consumed-kcal")).to_have_text("467")
    expect(page.locator(".consumed-grams")).to_have_text("120 g")

    # 4) Parámetros en vivo: peso 69 + kcal 2750 -> prot 104, grasa 76, carb 413
    page.fill("#param-peso", "69")
    page.fill("#param-kcal", "2750")
    expect(page.locator(".target-prot")).to_have_text("104")
    expect(page.locator(".target-fat")).to_have_text("76")
    expect(page.locator(".target-carb")).to_have_text("413")

    # 5) Guardar: persiste filas y parámetros
    page.click('#nutrition-form button[type="submit"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 6) Recargar: fila y parámetros persisten; el día queda readonly
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#nutrition-rows .nutrition-row")).to_have_count(1)
    expect(page.locator('#nutrition-rows input[name="cantidad"]')).to_have_value("120")
    expect(page.locator("#param-peso")).to_have_value("69")
    expect(page.locator(".consumed-kcal")).to_have_text("467")

    # 7) Eliminar el día con confirmación (lápiz desbloquea el modo edición)
    page.click('[data-action="nutrition-toggle-edit"]')
    page.click('[data-action="nutrition-delete"]')
    expect(page.locator("#confirm-modal")).not_to_have_class("hidden")
    page.click("#confirm-save")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator('#nutrition-rows input[name="alimento"]')).to_have_value("")
