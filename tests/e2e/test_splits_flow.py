"""Browser tests for the split manager: drag & drop, series counting, persistence.

Contrato: 1 instancia colocada = 1 serie. El DnD es nativo (DragEvent) y
reacciona a eventos sintéticos, igual que el reorden de plantillas.
"""

from playwright.sync_api import expect


def _drag_from_catalog(page, ejercicio, day):
    page.evaluate(
        """([ej, day]) => {
            const chip = [...document.querySelectorAll('.split-catalog-chip')]
                .find(c => c.dataset.ejercicio === ej);
            const zone = document.querySelector(`.split-day-zone[data-day="${day}"]`);
            const dt = new DataTransfer();
            chip.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
            zone.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
            zone.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            chip.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        }""",
        [ejercicio, day],
    )


def _move_card(page, item_selector, day):
    page.evaluate(
        """([sel, day]) => {
            const card = document.querySelector(sel);
            const zone = document.querySelector(`.split-day-zone[data-day="${day}"]`);
            const dt = new DataTransfer();
            card.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
            zone.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
            zone.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            card.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        }""",
        [item_selector, day],
    )


def _reorder_to_index(page, item_selector, day, index):
    """Mueve la tarjeta dentro del día a la posición `index` (0 = primero;
    >= len = final)."""
    page.evaluate(
        """([sel, day, index]) => {
            const card = document.querySelector(sel);
            const list = document.querySelector(
                `.split-day-zone[data-day="${day}"] .split-day-items`);
            const others = [...list.querySelectorAll('.split-item-card')].filter(c => c !== card);
            const anchor = others[index];
            const y = anchor
                ? anchor.getBoundingClientRect().top + 1
                : list.getBoundingClientRect().bottom + 10;
            const dt = new DataTransfer();
            card.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
            list.dispatchEvent(new DragEvent('dragover', {
                bubbles: true, cancelable: true, dataTransfer: dt, clientY: y }));
            list.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            card.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        }""",
        [item_selector, day, index],
    )


def _goto_splits(page, server):
    page.goto(server + "/splits")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#split-board .split-day-zone", timeout=5000)


def _card_names(page, day):
    return page.locator(
        f'.split-day-zone[data-day="{day}"] .split-item-card .split-item-name'
    ).all_inner_texts()


def test_splits_page_loads(page, server):
    _goto_splits(page, server)
    expect(page.locator("h1")).to_contain_text("Gestor de splits")
    expect(page.locator(".split-catalog-chip", has_text="HIIT")).to_be_visible()
    expect(page.locator('.split-catalog-chip[data-ejercicio="Press"]')).to_be_visible()
    for day in ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"):
        expect(page.locator(f'.split-day-zone[data-day="{day}"]')).to_be_visible()


def test_drag_repetido_cuenta_series(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(2)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("2 series")
    expect(page.locator("#split-metrics-preview")).to_contain_text("Series: 2")

    _drag_from_catalog(page, "HIIT", "MARTES")
    expect(page.locator('.split-day-zone[data-day="MARTES"] .split-item-card')).to_have_count(1)
    expect(page.locator('[data-day-count="MARTES"]')).to_have_text("1 serie")
    expect(page.locator("#split-metrics-preview")).to_contain_text("Series: 3")


def test_agregar_boton_alternativa_accesible(page, server):
    _goto_splits(page, server)
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(2)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("2 series")


def test_reordenar_y_eliminar(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    assert _card_names(page, "LUNES") == ["Curl", "Press"]

    # Reordenar: mover Press al primer lugar.
    _reorder_to_index(page, '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]', "LUNES", 0)
    assert _card_names(page, "LUNES") == ["Press", "Curl"]

    # Eliminar una instancia: solo debe quedar una.
    page.locator('.split-day-zone[data-day="LUNES"] [data-action="split-item-remove"]').first.click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(1)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("1 serie")
    expect(page.locator("#split-metrics-preview")).to_contain_text("Series: 1")


def test_guardar_recargar_abrir_conserva_estado(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")

    page.fill("#split-nombre", "Push Pull Legs")
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split guardado.", timeout=3000
    )
    expect(page.locator("#splits-list .card")).to_have_count(1)

    # Recargar y abrir desde la lista.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="split-open"]')
    page.wait_for_selector('.split-day-zone[data-day="LUNES"] .split-item-card', timeout=3000)

    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(3)
    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Press"]
    expect(page.locator('.split-day-zone[data-day="MARTES"] .split-item-card')).to_have_count(1)
    assert _card_names(page, "MARTES") == ["HIIT"]
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("3 series")
    expect(page.locator('[data-day-count="MARTES"]')).to_have_text("1 serie")
    expect(page.locator("#split-metrics-preview")).to_contain_text("Series: 4")


def test_eliminar_split_desde_lista_con_confirmacion(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    page.fill("#split-nombre", "Temporal")
    page.click('[data-action="split-save"]')
    expect(page.locator("#splits-list .card")).to_have_count(1, timeout=3000)
    page.click('[data-action="split-delete"]')
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#splits-section")).to_contain_text("Aún no hay splits", timeout=3000)
    expect(page.locator("#split-board .split-item-card")).to_have_count(0)
