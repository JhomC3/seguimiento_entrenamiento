"""Browser smoke test: the core save workflow against an isolated server + temp DB."""

import datetime

from playwright.sync_api import expect


def _today_iso() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def test_save_session_flow(page, server):
    page.goto(server)

    expect(page.locator("#session-editor")).to_be_visible()
    expect(page.locator("#session-form")).to_be_visible()

    page.select_option('select[name="ejercicio"]', "Press")
    page.fill('input[name="kg"]', "80")
    page.fill('input[name="reps"]', "8")
    page.fill('input[name="rir"]', "1")

    page.click('#edit-actions button[type="submit"]')

    expect(page.locator("#editor-notice .notice-success")).to_contain_text("Entrenamiento guardado")
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1")
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "1")
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "0")

    expect(page.locator('input[name="kg"]')).to_be_disabled()
