"""Browser tests: analysis home + register modal (htmx editing workflows)."""

import datetime
import re

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open_modal(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="open-register-modal"]')
    page.wait_for_selector(
        '#register-modal-body #session-form input[name="fecha"]', state="attached", timeout=5000
    )
    page.wait_for_selector("#register-modal-body #nutrition-form", timeout=5000)


def _goto_date(page, server, iso):
    _open_modal(page, server)
    _switch_session_tab(page)
    before = page.locator("#session-date-title h3").inner_text()
    page.locator(f'#register-modal-body .date-num[data-iso="{iso}"]').click()
    expect(page.locator(f'#register-modal-body .date-num[data-iso="{iso}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    expect(page.locator("#session-date-title h3")).not_to_have_text(before)
    expect(page.locator("#session-date-title")).to_contain_text("Semana")
    page.wait_for_timeout(150)


def _fill_row(page, row, ejercicio="Press", kg="80", reps="8", rir="1"):
    r = page.locator("#set-rows .set-row").nth(row)
    r.locator("select[name='ejercicio']").select_option(ejercicio)
    r.locator('input[name="kg"]').fill(kg)
    r.locator('input[name="reps"]').fill(reps)
    r.locator('input[name="rir"]').fill(rir)


def _switch_session_tab(page):
    page.click('#register-tabs .pill[data-tab="session"]')
    expect(page.locator("#register-session")).to_be_visible()
    expect(page.locator("#register-nutrition")).to_be_hidden()


def _save_session(page):
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=3000)


def _show_plantillas(page):
    page.click('[data-action="toggle-plantillas"]')
    expect(page.locator("#register-plantillas")).to_be_visible()


def test_empty_state_chart(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#analysis-chart-wrap")).to_be_visible()
    expect(page.locator("#kpi-row")).to_be_visible()


def test_save_session_flow(page, server):
    iso = _iso(3)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    _fill_row(page, 0)
    _save_session(page)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "0")
    expect(page.locator('input[name="kg"]')).to_be_disabled()


def test_negative_rir_badge_forzada(page, server):
    _goto_date(page, server, _iso(4))
    _fill_row(page, 0, kg="80", reps="5", rir="-1")
    expect(page.locator("#set-rows .set-row").first.locator(".rir-badge")).to_have_text("FORZADA")
    page.locator('input[name="rir"]').fill("0")
    expect(page.locator("#set-rows .set-row").first.locator(".rir-badge")).to_have_text("FALLO")
    page.locator('input[name="rir"]').fill("2")
    expect(page.locator("#set-rows .set-row").first.locator(".rir-badge")).to_be_hidden()


def test_descanso_column_persists(page, server):
    iso = _iso(5)
    _goto_date(page, server, iso)
    _fill_row(page, 0, kg="80", reps="5", rir="0")
    page.locator('input[name="descanso"]').fill("90")
    _save_session(page)
    page.click(".pencil-btn")
    expect(page.locator('input[name="descanso"]')).to_have_value("90")


def test_unsaved_changes_confirmation(page, server):
    iso = _iso(1)
    _goto_date(page, server, iso)
    _fill_row(page, 0, kg="90")
    page.locator(f'#register-modal-body .date-num[data-iso="{_iso(2)}"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    expect(page.locator("#session-date-title")).to_contain_text("Semana")
    expect(page.locator('#session-form input[name="fecha"]')).to_have_value(_iso(2))


def test_add_remove_reorder_set(page, server):
    _goto_date(page, server, _iso(2))
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#set-rows .set-row")).to_have_count(1)

    page.locator("#set-rows .set-row").first.locator(".row-actions [title='Agregar fila']").click()
    expect(page.locator("#set-rows .set-row")).to_have_count(2)
    _fill_row(page, 0, kg="80", reps="8")
    _fill_row(page, 1, kg="70", reps="10")

    page.locator("#set-rows .set-row").nth(1).locator(
        ".row-actions [title='Eliminar fila']"
    ).click()
    expect(page.locator("#set-rows .set-row")).to_have_count(1)

    page.locator("#set-rows .set-row").first.locator(".row-actions [title='Agregar fila']").click()
    _fill_row(page, 1, kg="70", reps="10")
    expect(page.locator("#set-rows .set-row")).to_have_count(2)

    second = page.locator("#set-rows .set-row").nth(1)
    box = second.bounding_box()
    target_box = page.locator("#set-rows .set-row").nth(0).bounding_box()
    page.mouse.move(box["x"] + 8, box["y"] + 14)
    page.mouse.down()
    page.mouse.move(box["x"] + 11, box["y"] + 9, steps=2)
    page.mouse.move(target_box["x"] + 300, target_box["y"] + 14, steps=10)
    page.wait_for_timeout(150)
    page.mouse.up()
    expect(page.locator("#set-rows .set-row").nth(0).locator('input[name="kg"]')).to_have_value(
        "70"
    )
    expect(page.locator("#set-rows .set-row").nth(1).locator('input[name="kg"]')).to_have_value(
        "80"
    )


def _create_template(page, server, iso, nombre):
    _goto_date(page, server, iso)
    _fill_row(page, 0)
    page.locator("#session-editor .save-template-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    page.locator('#save-template-form input[name="nombre"]').fill(nombre)
    page.locator("#save-template-form .btn-check").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    _show_plantillas(page)
    expect(page.locator("#plantillas-section [data-pt-nombre]")).to_have_count(1, timeout=3000)


def test_apply_template(page, server):
    _create_template(page, server, _iso(3), "Mi Empuje")
    _goto_date(page, server, _iso(4))
    _show_plantillas(page)
    page.locator("#plantillas-section .pt-card").get_by_role("button", name="Aplicar").click()
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entreno aplicado", timeout=3000
    )
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "1", timeout=3000)
    expect(page.locator("#plantilla-applied")).to_have_count(0)
    expect(page.locator("#set-rows .ej-select").first).to_have_value("Press")
    expect(page.locator("#edit-actions")).not_to_have_class(re.compile(r"\binvisible\b"))


def test_template_crud_and_reorder(page, server):
    _create_template(page, server, _iso(5), "A")
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(1)

    page.locator("#plantillas-section .pt-card").get_by_role("button", name="Editar").click()
    page.locator('#plantillas-section .pt-card form input[name="nombre"]').fill("A-edit")
    page.locator(".pt-card form .btn-check").click()
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Entreno guardado", timeout=2000
    )
    expect(page.locator("#plantillas-section .pt-card").first).to_have_attribute(
        "data-pt-nombre", "A-edit"
    )

    _goto_date(page, server, _iso(6))
    _fill_row(page, 0, kg="75", reps="8")
    page.locator("#session-editor .save-template-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    page.locator('#save-template-form input[name="nombre"]').fill("B")
    page.locator("#save-template-form .btn-check").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    _show_plantillas(page)
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(2)

    page.locator("#plantillas-section .pt-card").first.get_by_role(
        "button", name="Eliminar"
    ).click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(1, timeout=3000)
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Entreno eliminado", timeout=2000
    )


def test_delete_and_undo_session(page, server):
    iso = _iso(6)
    _goto_date(page, server, iso)
    _fill_row(page, 0)
    _save_session(page)

    page.locator(".pencil-btn").click()
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    page.locator(".delete-session-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "0", timeout=5000)

    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+z")
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "1", timeout=5000)
    expect(page.locator("#set-rows .ej-select").first).to_have_value("Press")


def test_invalid_numeric_input_blocks_save(page, server):
    _goto_date(page, server, _iso(7))
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    _fill_row(page, 0, kg="-5")
    page.click('#edit-actions button[type="submit"]')
    page.wait_for_timeout(600)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#editor-notice")).not_to_contain_text("Entrenamiento guardado")


# ---------------------------------------------------------------------------
# Análisis: píldoras de nivel, capas y panel del día
# ---------------------------------------------------------------------------


def _click_chart_day(page, iso):
    pos = page.evaluate(
        """(iso) => {
            const plotEl = document.getElementById('analysis-chart-plot');
            if (!plotEl || !plotEl._fullData || !plotEl._fullData.length) return null;
            const trace = plotEl._fullData[0];
            const idx = trace.x.findIndex(
                (v) => new Date(v).toISOString().slice(0, 10) === iso
            );
            const pts = plotEl.querySelectorAll('.point');
            if (idx < 0 || idx >= pts.length) return null;
            const r = pts[idx].getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }""",
        iso,
    )
    assert pos, f"no se encontró el marcador del día {iso}"
    page.mouse.click(pos["x"], pos["y"])


def test_level_pills_change_filters_and_chart(page, server):
    _open_modal(page, server)
    page.click('[data-action="close-register-modal"]')

    page.click('.pills-track .pill[data-nivel="grupo"]')
    expect(page.locator("#analysis-filters .filter-chip")).to_have_count(1, timeout=3000)
    expect(page.locator("#analysis-filters .filter-chip").first).to_have_attribute(
        "data-focus", "EMPUJE"
    )

    page.click('.pills-track .pill[data-nivel="musculo"]')
    expect(page.locator("#analysis-filters .filter-chip")).to_have_count(1, timeout=3000)
    expect(page.locator("#analysis-filters .filter-chip").first).to_have_attribute(
        "data-focus", "Pectoral"
    )

    page.click('.pills-track .pill[data-nivel="ejercicio"]')
    expect(page.locator("#analysis-filters .exercise-search")).to_be_visible(timeout=3000)

    page.click('.pills-track .pill[data-nivel="global"]')
    expect(page.locator("#analysis-filters .filter-chip")).to_have_count(0, timeout=3000)


def test_layer_toggle_persists_and_refetches(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    chip = page.locator('#layer-toggles .layer-chip[data-layer="peso"]')
    expect(chip).to_have_attribute("aria-pressed", "true")
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "false")
    assert "peso" not in page.evaluate("localStorage.getItem('gym.layers.v1')")
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "true")


def test_chart_day_click_opens_day_panel(page, server):
    _open_modal(page, server)
    iso = _iso(3)
    _goto_date(page, server, iso)
    _fill_row(page, 0)
    _save_session(page)
    page.click('[data-action="close-register-modal"]')

    page.locator("#analysis-chart-plot .point").first.wait_for(state="visible", timeout=5000)
    _click_chart_day(page, iso)
    expect(page.locator("#day-detail-section #day-detail-wrap")).to_be_visible(timeout=5000)
    expect(page.locator("#day-detail-wrap")).to_contain_text(f"¿Qué pasó el {iso}")
    expect(page.locator("#day-detail-wrap")).to_contain_text("Press")


def test_day_panel_shows_fallo_badge(page, server):
    _open_modal(page, server)
    iso = _iso(4)
    _goto_date(page, server, iso)
    _fill_row(page, 0, kg="80", reps="5", rir="0")
    _save_session(page)
    page.click('[data-action="close-register-modal"]')

    page.locator("#analysis-chart-plot .point").first.wait_for(state="visible", timeout=5000)
    _click_chart_day(page, iso)
    expect(page.locator("#day-detail-wrap")).to_contain_text("FALLO", timeout=5000)


def test_register_modal_escape_closes(page, server):
    _open_modal(page, server)
    page.keyboard.press("Escape")
    expect(page.locator("#register-modal")).to_be_hidden()


# ---------------------------------------------------------------------------
# XSS execution regressions
# ---------------------------------------------------------------------------

PAYLOAD = "x');alert(1)//<img src=x onerror=alert(2)>"


def test_hostile_template_name_does_not_execute(page, server):
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _create_template(page, server, _iso(8), PAYLOAD)
    page.locator("#plantillas-section .pt-card").first.get_by_role(
        "button", name="Eliminar"
    ).click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    expect(page.locator("#confirm-msg")).to_contain_text(PAYLOAD)
    assert len(dialogs) == 0, f"no debe haber dialogs nativos, visto: {dialogs}"


def test_hostile_exercise_notice_creates_no_image_node(page, server):
    _open_modal(page, server)
    page.click('[data-action="toggle-create-form"][data-kind="ejercicio"]')
    page.fill('#exercise-create-form input[name="ejercicio"]', PAYLOAD)
    page.fill('#exercise-create-form input[name="grupo_muscular"]', "Pectoral")
    page.select_option('#exercise-create-form select[name="categoria"]', "EMPUJE")
    page.click('#exercise-create-form button[type="submit"]')
    expect(page.locator("#notice-container .notice")).to_be_visible(timeout=3000)
    page.wait_for_timeout(500)
    assert page.locator("#notice-container img").count() == 0
    expect(page.locator("#notice-container")).to_contain_text(PAYLOAD)


def test_dynamic_script_does_not_execute(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.evaluate(
        """() => {
            window.__xssProbe = false;
            const s = document.createElement('script');
            s.textContent = 'window.__xssProbe = true';
            document.body.appendChild(s);
        }"""
    )
    page.wait_for_timeout(400)
    assert page.evaluate("window.__xssProbe") is False, "la CSP debe bloquear scripts inyectados"


def test_keyboard_day_shift_updates_editor(page, server):
    _open_modal(page, server)
    fecha = page.input_value("#session-form input[name='fecha']")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(
        "(expected) => document.querySelector(\"#session-form input[name='fecha']\").value !== expected",
        arg=fecha,
    )


def test_mobile_viewport_renders(page, server):
    page.set_viewport_size({"width": 375, "height": 800})
    _open_modal(page, server)
    _switch_session_tab(page)
    assert page.is_visible("#session-editor")
    assert page.is_visible("#date-navigator")
    can_scroll = page.evaluate(
        "() => { const el = document.querySelector('#session-editor .table-scroll');"
        " return el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight; }"
    )
    assert can_scroll
