"""Browser tests: standalone daily page (/diario, alias /registro).

Cubre el flujo completo del Diario: carrusel compacto sin semanas, tabs de
entrenamiento/alimentación, plantillas que no mezclan sesiones, altas de
ejercicio y alimento desde diálogos, foco y Escape, y ausencia de overflow
horizontal en móvil. No toca las expectativas de UX-3.
"""

import datetime
import re

from playwright.sync_api import expect

_TITLE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open_diario(page, server):
    page.goto(server + "/diario")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#date-navigator", timeout=5000)


def _settle(page):
    page.wait_for_timeout(150)


def _goto_date(page, iso):
    page.locator(f'#date-navigator .date-num[data-iso="{iso}"]').click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    _settle(page)


def _fill_row(page, row, ejercicio="Press", kg="80", reps="8", rir="1"):
    r = page.locator("#set-rows .set-row").nth(row)
    r.locator("select[name='ejercicio']").select_option(ejercicio)
    r.locator('input[name="kg"]').fill(kg)
    r.locator('input[name="reps"]').fill(reps)
    r.locator('input[name="rir"]').fill(rir)


def _save_session(page):
    page.locator('#session-form button[type="submit"]').click()
    page.wait_for_selector("#editor-notice .notice", timeout=5000)
    _settle(page)


def _fill_alimento_form(page, nombre="Avena"):
    page.locator('#alimento-create-form input[name="nombre"]').fill(nombre)
    page.locator('#alimento-create-form input[name="categoria"]').fill("Cereal")
    page.locator('#alimento-create-form input[name="kcal"]').fill("389")
    page.locator('#alimento-create-form input[name="carbohidratos"]').fill("68")
    page.locator('#alimento-create-form input[name="fibra"]').fill("10")
    page.locator('#alimento-create-form input[name="proteina"]').fill("17")
    page.locator('#alimento-create-form input[name="grasa"]').fill("6.9")
    page.locator('#alimento-create-form input[name="hierro"]').fill("4.2")
    page.locator('#alimento-create-form input[name="calcio"]').fill("54")
    page.locator('#alimento-create-form input[name="vitamina_c"]').fill("0")
    page.locator('#alimento-create-form input[name="vitamina_a"]').fill("0")


def test_diario_carousel_compact_and_arrows(page, server):
    _open_diario(page, server)

    # 2) La app está lista y 3) el carrusel aparece.
    expect(page.locator("#date-navigator")).to_be_visible()
    # 4) Título corto dd/mm/aa y sin "Semana" en la página.
    expect(page.locator("#daily-date-title")).to_have_text(_TITLE_RE)
    expect(page.locator("#daily-page")).not_to_contain_text("Semana")
    # Las etiquetas de los días del carrusel son compactas (dd/mm/aa en aria).
    today = _iso(0)
    expect(page.locator(f'#date-navigator .date-num[data-iso="{today}"]')).to_have_attribute(
        "aria-label", _TITLE_RE
    )

    # 5) Seleccionar otra fecha por clic en el carrusel.
    iso = _iso(2)
    _goto_date(page, iso)
    expect(page.locator(f'#date-navigator .date-num[data-iso="{iso}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    # El editor de alimentación también sigue la fecha seleccionada (la cola
    # htmx del carrusel es independiente de la de los editores).
    expect(page.locator("#nutrition-form input[name='fecha']")).to_have_value(iso)

    # 6-7) Flecha posterior: salta 15 días desde la selección y el carrusel se
    # regenera (la fecha seleccionada queda visible y aparecen fechas fuera de
    # la ventana previa).
    page.locator('[data-action="scroll-dates"][data-dir="1"]').click()
    _settle(page)
    expect(page.locator(f'#date-navigator .date-num[data-iso="{_iso(17)}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(_iso(17))
    expect(page.locator("#nutrition-form input[name='fecha']")).to_have_value(_iso(17))
    expect(page.locator(f'#date-navigator .date-num[data-iso="{_iso(22)}"]')).to_be_visible()

    # Flecha anterior: vuelve a la selección previa y la ventana se re-centra.
    page.locator('[data-action="scroll-dates"][data-dir="-1"]').click()
    _settle(page)
    expect(page.locator(f'#date-navigator .date-num[data-iso="{_iso(2)}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#daily-date-title")).to_have_text(_TITLE_RE)


def test_diario_tabs_separate_training_and_food(page, server):
    _open_diario(page, server)

    # Por defecto: entrenamiento visible, alimentación oculta.
    expect(page.locator("#daily-training-view")).to_be_visible()
    expect(page.locator("#daily-food-view")).to_be_hidden()

    # 8) Cambiar a Alimentación sin recargar la página.
    page.locator('[data-action="daily-mode"][data-vista="alimentacion"]').click()
    expect(page.locator("#daily-food-view")).to_be_visible()
    expect(page.locator("#daily-training-view")).to_be_hidden()
    expect(page.locator("#daily-page")).to_have_attribute("data-vista", "alimentacion")

    # La URL mantiene la vista; la fecha seleccionada se conserva.
    expect(page).to_have_url(re.compile(r"vista=alimentacion"))

    # Teclado en tabs: flecha izquierda vuelve a entrenamiento.
    page.locator('#daily-page [role="tab"]').nth(1).focus()
    page.keyboard.press("ArrowLeft")
    expect(page.locator("#daily-training-view")).to_be_visible()
    expect(page.locator("#daily-page")).to_have_attribute("data-vista", "entrenamiento")


def test_diario_session_templates_do_not_mix_sessions(page, server):
    _open_diario(page, server)

    # Sesión A (hoy-3): sesión de torso completa (Press + Curl).
    iso_a = _iso(-3)
    _goto_date(page, iso_a)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    page.locator("#set-rows .set-row").first.locator('[data-action="row-add"]').click()
    _fill_row(page, 1, "Curl", "16", "10", "0")
    # 13) Guardar como plantilla "Torso" (desde el editor, con confirmación).
    page.locator("#session-editor .save-template-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    page.locator('#save-template-form input[name="nombre"]').fill("Torso")
    page.locator("#save-template-form .btn-check").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    _save_session(page)
    # La plantilla queda guardada y visible en el diálogo de Plantillas.
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    expect(page.locator("#plantillas-section [data-pt-nombre]")).to_have_count(1, timeout=3000)
    page.keyboard.press("Escape")

    # Sesión B (hoy-1): solo Curl, posterior.
    iso_b = _iso(-1)
    _goto_date(page, iso_b)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Curl", "20", "12", "1")
    _save_session(page)

    # 14) Aplicar la plantilla en un día vacío (hoy+1): debe copiar la sesión
    # de torso completa (80/16), no mezclar con la sesión B (20).
    iso_c = _iso(1)
    _goto_date(page, iso_c)
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    page.locator("#plantillas-section .pt-card", has_text="Torso").get_by_role(
        "button", name="Aplicar"
    ).click()
    _settle(page)
    # El editor queda editable, marcado como modificado (Guardar visible) y la
    # respuesta solo reemplaza el editor, no la página.
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_c)
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "0")
    expect(page.locator("#edit-actions button[type='submit']")).to_be_enabled()
    kgs = page.locator('#set-rows input[name="kg"]').evaluate_all("els => els.map(e => e.value)")
    reps = page.locator('#set-rows input[name="reps"]').evaluate_all("els => els.map(e => e.value)")
    assert kgs == ["80", "16"], f"kg mezclados: {kgs}"
    assert reps == ["8", "10"], f"reps mezcladas: {reps}"
    # Cerrar el diálogo de plantillas antes de guardar.
    page.keyboard.press("Escape")
    expect(page.locator("#training-templates-dialog")).not_to_be_visible()

    # 15) Guardar sin reemplazar toda la página: el carrusel sigue presente.
    _save_session(page)
    expect(page.locator("#date-navigator")).to_be_visible()
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "1")


def test_diario_food_flow_with_dialog_create(page, server):
    _open_diario(page, server)
    page.locator('[data-action="daily-mode"][data-vista="alimentacion"]').click()

    # 19) Abrir Nuevo alimento (diálogo compacto).
    page.locator('[data-action="open-daily-dialog"][data-dialog="food-create-dialog"]').click()
    expect(page.locator("#food-create-dialog")).to_be_visible()
    # 24) Escape cierra el diálogo y restaura el foco en el trigger.
    page.keyboard.press("Escape")
    expect(page.locator("#food-create-dialog")).not_to_be_visible()
    page.locator('[data-action="open-daily-dialog"][data-dialog="food-create-dialog"]').click()

    # 20) Crear el alimento.
    _fill_alimento_form(page)
    page.locator('#alimento-create-form button[type="submit"]').click()
    # Se cierra solo tras el alta exitosa.
    expect(page.locator("#food-create-dialog")).not_to_be_visible()
    expect(page.locator("#notice-container .notice")).to_be_visible()

    # 9) Editar el día: Avena 120 g → preview 467 kcal (server-authoritative).
    page.locator('[data-action="nutrition-row-add"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    expect(row.locator(".kcal-cell")).to_have_text("467")
    expect(row.locator(".prot-cell")).to_have_text("20")
    # Guardar el día.
    page.locator('#nutrition-form button[type="submit"]').click()
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    _settle(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 10) Guardar plantilla de alimentación desde el panel.
    page.locator('[data-action="nutrition-toggle-template-form"]').click()
    page.locator('#save-meal-template-form input[name="nombre"]').fill("Desayuno")
    page.locator('#save-meal-template-form [data-action="confirm-meal-template-save"]').click()
    page.wait_for_selector("#notice-container .notice", timeout=5000)

    # 11) Aplicar la plantilla desde el diálogo (confirma reemplazo).
    page.locator('[data-action="open-daily-dialog"][data-dialog="food-templates-dialog"]').click()
    expect(page.locator("#nutrition-templates-section .pt-card")).to_have_count(1, timeout=3000)
    page.locator("#nutrition-templates-section .pt-card").get_by_role(
        "button", name="Aplicar"
    ).click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    _settle(page)
    expect(
        page.locator("#nutrition-rows .nutrition-row").first.locator('input[name="alimento"]')
    ).to_have_value("Avena")
    page.keyboard.press("Escape")

    # 12) Cambiar a Entrenamiento: la vista se restaura sin recargar.
    page.locator('[data-action="daily-mode"][data-vista="entrenamiento"]').click()
    expect(page.locator("#daily-training-view")).to_be_visible()

    # 16) Abrir Nuevo ejercicio (diálogo compacto).
    page.locator('[data-action="open-daily-dialog"][data-dialog="exercise-create-dialog"]').click()
    expect(page.locator("#exercise-create-dialog")).to_be_visible()
    page.locator('#exercise-create-form input[name="ejercicio"]').fill("Press Pausado")
    page.locator('#exercise-create-form input[name="grupo_muscular"]').fill("Pectoral")
    page.locator('#exercise-create-form select[name="categoria"]').select_option("EMPUJE")
    # 17) Crear el ejercicio.
    page.locator('#exercise-create-form button[type="submit"]').click()
    expect(page.locator("#exercise-create-dialog")).not_to_be_visible()
    expect(page.locator("#notice-container .notice")).to_be_visible()
    # 18) Aparece en el editor sin recargar la página.
    options = page.locator("#set-rows .ej-select").first.locator("option").all_text_contents()
    assert "Press Pausado" in options


def test_diario_dialogs_restore_focus_and_escape(page, server):
    _open_diario(page, server)
    trigger = page.locator(
        '[data-action="open-daily-dialog"][data-dialog="exercise-create-dialog"]'
    )
    trigger.click()
    expect(page.locator("#exercise-create-dialog")).to_be_visible()
    # Foco inicial dentro del diálogo (el módulo modal-dialog enfoca el primer
    # elemento enfocable).
    in_dialog = page.evaluate(
        """() => {
            const d = document.getElementById('exercise-create-dialog');
            return d.contains(document.activeElement);
        }"""
    )
    assert in_dialog
    # Escape cierra el diálogo.
    page.keyboard.press("Escape")
    expect(page.locator("#exercise-create-dialog")).not_to_be_visible()
    # 23) El foco vuelve al trigger que abrió el diálogo.
    focused = page.evaluate(
        """() => {
            const el = document.activeElement;
            return el && el.closest('[data-action="open-daily-dialog"]') ? el.closest('[data-action="open-daily-dialog"]').dataset.dialog : null;
        }"""
    )
    assert focused == "exercise-create-dialog"


def test_diario_no_horizontal_overflow_mobile(page, server):
    page.set_viewport_size({"width": 390, "height": 844})
    _open_diario(page, server)
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow
