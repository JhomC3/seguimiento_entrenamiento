"""Browser tests: standalone daily page (/diario, alias /registro).

Cubre el flujo completo del Diario: carrusel compacto sin semanas, tabs de
entrenamiento/alimentación, plantillas que no mezclan sesiones, altas de
ejercicio y alimento desde diálogos, foco y Escape, ausencia de overflow
horizontal en móvil, y persistencia REAL del guardado verificada contra
SQLite. No toca las expectativas de UX-3.
"""

import datetime
import re
import sqlite3
import time

from playwright.sync_api import expect

_TITLE_RE = re.compile(r"^[A-Z]+ \d{2}/\d{2}/\d{2}$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _training_rows(db_path, fecha: str) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT set_orden, ejercicio, kg, reps, rir, descanso_seg "
            "FROM training_sets WHERE fecha = ? ORDER BY set_orden",
            (fecha,),
        ).fetchall()
    finally:
        conn.close()


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
        "aria-label", _DATE_RE
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


def test_workspace_navigation_between_pages(page, server):
    """La navegación común conecta Dashboard, Diario y Splits con aria-current."""
    page.goto(server)
    page.wait_for_selector("#dashboard-catalog", timeout=5000)
    expect(page.locator('.workspace-nav a[href="/"][aria-current="page"]')).to_have_count(1)

    page.locator('.workspace-nav a[href="/diario"]').click()
    page.wait_for_selector("#daily-page", timeout=5000)
    expect(page.locator(".daily-header h1")).to_have_text("Diario")
    expect(page.locator('.workspace-nav a[href="/diario"][aria-current="page"]')).to_have_count(1)

    page.locator('.workspace-nav a[href="/splits"]').click()
    page.wait_for_selector("#splits-section", timeout=5000)
    expect(page.locator(".splits-page-header h1")).to_have_text("Gestor de splits")
    expect(page.locator('.workspace-nav a[href="/splits"][aria-current="page"]')).to_have_count(1)

    page.locator('.workspace-nav a[href="/diario"]').click()
    page.wait_for_selector("#daily-page", timeout=5000)
    expect(page.locator(".daily-header h1")).to_have_text("Diario")


def test_diario_session_save_persists_across_reload(page, server, server_db_path):
    """Guardar una sesión nueva desde Diario persiste en SQLite y tras recargar.

    Criterio real (no solo aviso/toast): los datos sobreviven a la respuesta
    HTTP, al swap htmx, a la recarga del navegador y a una nueva lectura SQLite.
    """
    iso = _iso(-2)
    _open_diario(page, server)
    _goto_date(page, iso)

    # Sesión nueva en fecha vacía: activar edición, llenar 2 series, guardar.
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    page.locator("#set-rows .set-row").first.locator('[data-action="row-add"]').click()
    _fill_row(page, 1, "Curl", "16", "10", "0")
    _save_session(page)
    expect(page.locator("#editor-notice .notice-success")).to_be_visible()
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")

    # 1) Persistencia directa en SQLite.
    rows = _training_rows(server_db_path, iso)
    assert len(rows) == 2, f"esperadas 2 filas en DB, hay {len(rows)}"
    assert rows[0][1:4] == ("Press", 80.0, 8.0)
    assert rows[1][1:4] == ("Curl", 16.0, 10.0)

    # 2) Recarga con la misma fecha: la serie sigue presente en el editor.
    page.goto(server + f"/diario?fecha={iso}")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    expect(page.locator("#set-rows .set-row")).to_have_count(2)
    kgs = page.locator('#set-rows input[name="kg"]').evaluate_all("els => els.map(e => e.value)")
    assert kgs == ["80", "16"], f"kg tras recarga: {kgs}"


def test_diario_session_edit_save_persists_updated_value(page, server, server_db_path):
    """Editar una sesión existente desde Diario persiste el valor actualizado."""
    iso = _iso(-3)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    _save_session(page)
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")

    # Editar kg y RIR de la serie existente.
    page.locator("#session-editor .pencil-btn").click()
    page.locator('#set-rows input[name="kg"]').first.fill("92.5")
    page.locator('#set-rows input[name="rir"]').first.fill("2")
    _save_session(page)
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")

    rows = _training_rows(server_db_path, iso)
    assert len(rows) == 1
    assert rows[0][2] == 92.5, f"kg en DB: {rows[0][2]}"
    assert rows[0][4] == 2.0, f"rir en DB: {rows[0][4]}"

    page.goto(server + f"/diario?fecha={iso}")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("92.5")
    expect(page.locator('#set-rows input[name="rir"]').first).to_have_value("2")


def test_diario_save_error_400_preserves_values_and_shows_notice(page, server):
    """Un 400 de dominio no descarta los valores del formulario y es visible."""
    iso = _iso(-4)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    page.locator("#set-rows .set-row").first.locator('select[name="ejercicio"]').select_option(
        "Press"
    )
    page.locator('#set-rows input[name="kg"]').first.fill("77")
    page.locator('#set-rows input[name="reps"]').first.fill("5")
    # Vaciar el ejercicio → error de dominio 400 "Debes seleccionar un ejercicio".
    page.locator("#set-rows .set-row").first.locator('select[name="ejercicio"]').select_option("")
    _save_session(page)
    expect(page.locator("#editor-notice .notice-error")).to_be_visible()
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "0")
    # Valores locales preservados tras el error.
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("77")
    expect(page.locator('#set-rows input[name="reps"]').first).to_have_value("5")
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator('#session-form button[type="submit"]')).to_be_enabled()


def test_diario_save_error_500_shows_notice_and_keeps_values(page, server):
    """Un 500 interno muestra aviso visible y conserva los valores (sin swap)."""
    iso = _iso(-5)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    # Interceptar el POST y responder 500 (el servidor real nunca llega a guardar).
    page.route(
        "**/entrenamiento/session/save",
        lambda route: route.fulfill(status=500, body="<html>boom</html>"),
    )
    _save_session(page)
    expect(page.locator("#editor-notice .notice-error")).to_be_visible()
    expect(page.locator("#editor-notice")).to_contain_text("Error interno")
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("80")
    expect(page.locator('#session-form button[type="submit"]')).to_be_enabled()
    page.unroute("**/entrenamiento/session/save")


def test_diario_save_csrf_403_shows_notice(page, server):
    """Un 403 de CSRF (token rechazado) es visible y no pierde el formulario."""
    iso = _iso(-6)

    # Interceptar el HTML de /diario y corromper el token en #app-config ANTES
    # de que el JS lo cargue: el POST real sale con token inválido y el
    # middleware responde 403 (no es un mock del servidor).
    def _corrupt(route):
        resp = route.fetch()
        html = resp.text()
        html = html.replace('"csrf_token": "', '"csrf_token": "corrupto', 1)
        route.fulfill(response=resp, body=html)

    page.route("**/diario*", _corrupt)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    _save_session(page)
    expect(page.locator("#editor-notice .notice-error")).to_be_visible()
    expect(page.locator("#editor-notice")).to_contain_text("no autorizada")
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("80")
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    page.unroute("**/diario*")


def test_diario_save_double_click_single_request(page, server):
    """El botón se deshabilita durante el vuelo: doble clic = 1 sola petición."""
    iso = _iso(-7)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")

    posts = []
    page.on(
        "request",
        lambda r: posts.append(r.url) if r.method == "POST" and "session/save" in r.url else None,
    )

    def _slow_save(route):
        time.sleep(0.6)
        route.fulfill(
            status=200,
            body=(
                '<div id="editor-notice" hx-swap-oob="innerHTML"><div class="notice notice-success">Entrenamiento guardado.</div></div>'
                '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>'
                '<div id="editor-state" hx-swap-oob="outerHTML" data-readonly="1" data-has-data="1" hidden></div>'
            ),
        )

    page.route("**/entrenamiento/session/save", _slow_save)
    # Clics nativos consecutivos: el primero dispara el submit y deshabilita
    # el botón; el segundo cae sobre el botón deshabilitado (sin petición).
    page.evaluate(
        """() => {
            const btn = document.querySelector('#session-form button[type="submit"]');
            btn.click();
            btn.click();
        }"""
    )
    page.wait_for_function(
        """() => {
            const b = document.querySelector('#session-form button[type="submit"]');
            return b && b.textContent.trim().startsWith('Guardando');
        }""",
        timeout=3000,
    )
    page.wait_for_timeout(900)
    assert len(posts) == 1, f"doble clic generó {len(posts)} peticiones"
    page.unroute("**/entrenamiento/session/save")


def test_diario_navigation_with_unsaved_changes_confirms(page, server):
    """Navegar con cambios sin guardar muestra confirmación; cancelar conserva."""
    iso_a = _iso(-8)
    iso_b = _iso(-9)
    _open_diario(page, server)
    _goto_date(page, iso_a)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    page.locator(f'#date-navigator .date-num[data-iso="{iso_b}"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    # La fecha NO cambia mientras el modal está abierto.
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_a)
    # Descartar cambios → navega y pierde los valores (decisión explícita).
    page.locator("#confirm-cancel").click()
    page.wait_for_timeout(600)
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_b)


def test_diario_reload_with_unsaved_changes_confirms(page, server):
    """Recargar con cambios pendientes dispara la confirmación beforeunload."""
    iso = _iso(-10)
    _open_diario(page, server)
    _goto_date(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    _fill_row(page, 0, "Press", "80", "8", "1")
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.type), d.accept()))
    # reload() de Playwright espera la navegación; un dismiss la cancela y
    # hace timeout. location.reload() dispara el mismo beforeunload sin
    # bloquear al runner.
    page.evaluate("window.location.reload()")
    page.wait_for_timeout(500)
    assert dialogs, "no se mostró la confirmación beforeunload con cambios pendientes"
    page.wait_for_function("document.body.dataset.appReady === '1'")


def _seed_sugerencia(server_db_path):
    """Split LUNES:[Press] activo y deuda del lunes pasado con pesos previos."""
    import sqlite3

    from src.database import set_active_split
    from src.models import SplitInput, SplitItemInput
    from src.split_service import save_split
    from src.training_service import save_session

    db = str(server_db_path)
    # Solo el lunes anterior (el de la semana pasada se falta): el martes
    # debe LUNES con los pesos de entonces.
    save_session(
        db,
        _prev_monday(),
        [{"ejercicio": "Press", "kg": 70, "reps": 8, "rir": 1}],
    )
    result = save_split(
        db, SplitInput(nombre="PPL", items=[SplitItemInput(dia="LUNES", ejercicio="Press")])
    )
    set_active_split(db, result.id)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE training_splits SET created_at = '2026-08-01 10:00:00'")
    conn.commit()
    conn.close()


def _last_monday():
    today = datetime.date.today()
    return (today - datetime.timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")


def _prev_monday():
    mon = datetime.date.fromisoformat(_last_monday())
    return (mon - datetime.timedelta(days=7)).strftime("%Y-%m-%d")


def test_diario_sugerencia_banner_aplicar_y_guardar(page, server, server_db_path):
    """La rueda propone el lunes pendiente con sus últimos pesos; aplicar y
    guardar persiste sin teclear nada (paridad app/web)."""
    _seed_sugerencia(server_db_path)
    mon = _last_monday()
    tue = (datetime.date.fromisoformat(mon) + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    page.goto(server + f"/diario?fecha={tue}")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    banner_btn = page.locator('#suggestion-banner [data-action="apply-suggestion"]')
    expect(banner_btn).to_be_visible(timeout=5000)
    expect(banner_btn).to_have_class(re.compile(r"btn-suggest"))
    # Modo edición y aplicar: filas con los últimos pesos, sin guardar aún.
    page.locator("#session-editor .pencil-btn").click()
    banner_btn.click()
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "0", timeout=5000)
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("70", timeout=5000)
    kgs = page.locator('#set-rows input[name="kg"]').evaluate_all("els => els.map(e => e.value)")
    assert kgs == ["70"], f"kg sugeridos: {kgs}"
    assert _training_rows(server_db_path, tue) == []
    # Guardar persiste.
    _save_session(page)
    rows = _training_rows(server_db_path, tue)
    assert len(rows) == 1
    assert rows[0][1:4] == ("Press", 70.0, 8.0)


def test_diario_hiit_pide_velocidad_dificultad(page, server, server_db_path):
    """HIIT muestra velocidad+dificultad (no kg/reps/rir) y persiste redondeado."""
    iso = _iso(2)
    _open_diario(page, server)
    _goto_date(page, iso)
    # doNav dispara varios ajax en paralelo (editor, navigator, cardio,
    # banner): esperar a que terminen antes de tocar el formulario, o un
    # swap tardío pisaría la selección.
    page.wait_for_selector(".htmx-request", state="detached", timeout=10000)
    # Un día futuro vacío ya arranca editable: solo pulsar el lápiz si hace
    # falta (pulsarlo en modo edición haría exitEditMode + swap que pisaría).
    if page.locator("#session-editor").get_attribute("data-editmode") != "1":
        page.locator("#session-editor .pencil-btn").click()
    row = page.locator("#set-rows .set-row").first
    row.locator("select[name='ejercicio']").select_option("HIIT")
    print("ROWHTML:", row.evaluate("el => el.outerHTML.slice(0, 1500)"))
    expect(row.locator('input[name="velocidad"]')).to_be_visible(timeout=3000)
    expect(row.locator('input[name="dificultad"]')).to_be_visible()
    expect(row.locator('input[name="kg"]')).to_be_hidden()
    expect(row.locator('input[name="reps"]')).to_be_hidden()
    expect(row.locator('input[name="rir"]')).to_be_hidden()
    row.locator('input[name="velocidad"]').fill("12.34")
    row.locator('input[name="dificultad"]').fill("7.5")
    _save_session(page)
    expect(page.locator("#editor-notice .notice-success")).to_be_visible()
    rows = _training_rows(server_db_path, iso)
    assert len(rows) == 1
    conn = sqlite3.connect(str(server_db_path))
    try:
        r = conn.execute(
            "SELECT ejercicio, kg, reps, rir, velocidad_kmh, dificultad "
            "FROM training_sets WHERE fecha = ?",
            (iso,),
        ).fetchone()
    finally:
        conn.close()
    assert r == ("HIIT", None, None, None, 12.3, 7.5)
