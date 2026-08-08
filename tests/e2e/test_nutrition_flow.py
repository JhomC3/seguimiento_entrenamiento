"""Browser test del flujo completo del panel de alimentación (crear alimento,
editar día, guardar, recargar, eliminar).

NOTA: el flujo se reescribe en la Task 3.2 del rebuild (el panel pasa a la
página principal, arriba del editor de entrenamiento).
"""

import pytest
from playwright.sync_api import expect


@pytest.mark.skip(reason="rebuild: el panel de alimentación se integra en / (Task 3.2)")
def test_nutrition_create_edit_save_reload_delete(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#nutrition-editor")).to_be_visible()
