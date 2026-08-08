"""Browser tests covering the high-risk htmx editing and template workflows."""

import datetime
import re

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _fill_row(page, row, ejercicio="Press", kg="80", reps="8", rir="1"):
    r = page.locator("#set-rows .set-row").nth(row)
    r.locator("select[name='ejercicio']").select_option(ejercicio)
    r.locator('input[name="kg"]').fill(kg)
    r.locator('input[name="reps"]').fill(reps)
    r.locator('input[name="rir"]').fill(rir)


def _goto_date(page, server, iso):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.locator(f'.date-num[data-iso="{iso}"]').click()
    expect(page.locator(f'.date-num[data-iso="{iso}"]')).to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#session-editor-wrap")).to_contain_text("Semana")


def _click_chart_point(page, semana):
    """Clic real de ratón sobre el marcador de una semana en la gráfica unificada."""
    pos = page.evaluate(
        """(semana) => {
            const plotEl = document.getElementById('unified-chart-plot');
            if (!plotEl) return null;
            const gd = plotEl._fullData ? plotEl : null;
            const idx = gd ? gd._fullData[0].x.indexOf(semana) : -1;
            const pts = plotEl.querySelectorAll('.point');
            if (idx >= 0 && idx < pts.length) {
                pts[idx].scrollIntoView({ block: 'center' });
                const r = pts[idx].getBoundingClientRect();
                return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
            }
            return null;
        }""",
        semana,
    )
    assert pos, f"no se encontró el marcador de la semana {semana}"
    page.mouse.click(pos["x"], pos["y"])


def test_empty_state_chart(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#unified-chart")).to_be_visible()
    expect(page.locator("#unified-chart")).to_contain_text("Sin datos")


def test_save_session_flow(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#session-editor")).to_be_visible()
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1")
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "0")
    expect(page.locator('input[name="kg"]')).to_be_disabled()


def test_unsaved_changes_confirmation(page, server):
    iso = _iso(1)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    _fill_row(page, 0, kg="90")
    page.locator(f'.date-num[data-iso="{_iso(2)}"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    expect(page.locator("#session-editor-wrap")).to_contain_text("Semana")
    expect(page.locator('input[name="fecha"]')).to_have_value(_iso(2))


def test_add_remove_reorder_set(page, server):
    iso = _iso(2)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#set-rows .set-row")).to_have_count(1)

    page.locator("#set-rows .set-row").first.locator(".row-actions [title='Agregar fila']").click()
    expect(page.locator("#set-rows .set-row")).to_have_count(2)
    _fill_row(page, 0, kg="80", reps="8")
    _fill_row(page, 1, kg="70", reps="10")

    expect(page.locator("#set-rows .set-row").nth(0).locator(".set-num")).to_have_text("1")
    expect(page.locator("#set-rows .set-row").nth(1).locator(".set-num")).to_have_text("2")

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
    expect(page.locator("#plantillas-section [data-pt-nombre]")).to_have_count(1, timeout=3000)


def test_apply_template(page, server):
    _create_template(page, server, _iso(3), "Mi Empuje")
    iso = _iso(4)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    page.locator("#plantillas-section .pt-card").get_by_role("button", name="Aplicar").click()
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entreno aplicado", timeout=3000
    )
    expect(page.locator("#set-rows .ej-select").first).to_have_value("Press")


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

    page.locator("#session-editor .save-template-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    page.locator('#save-template-form input[name="nombre"]').fill("B")
    page.locator("#save-template-form .btn-check").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(2)

    second_id = page.locator("#plantillas-section .pt-card").nth(1).get_attribute("data-pt-id")
    first_id = page.locator("#plantillas-section .pt-card").nth(0).get_attribute("data-pt-id")
    page.locator(f"#plantillas-section .pt-card[data-pt-id='{second_id}']").drag_to(
        page.locator(f"#plantillas-section .pt-card[data-pt-id='{first_id}']"),
        target_position={"x": 150, "y": 5},
    )
    expect(page.locator("#plantillas-section .pt-card").nth(0)).to_have_attribute(
        "data-pt-id", second_id, timeout=3000
    )

    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#plantillas-section .pt-card").first.get_by_role(
        "button", name="Eliminar"
    ).click()
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(1, timeout=3000)
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Entreno eliminado", timeout=2000
    )


def test_delete_and_undo_session(page, server):
    iso = _iso(6)
    _goto_date(page, server, iso)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=5000)

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
    iso = _iso(7)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    _fill_row(page, 0, kg="-5")
    page.click('#edit-actions button[type="submit"]')
    page.wait_for_timeout(600)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#editor-notice")).not_to_contain_text("Entrenamiento guardado")


# ---------------------------------------------------------------------------
# XSS execution regressions (Task 1)
# ---------------------------------------------------------------------------

PAYLOAD = "x');alert(1)//<img src=x onerror=alert(2)>"


def test_hostile_template_name_does_not_execute(page, server):
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

    _create_template(page, server, _iso(8), PAYLOAD)
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(1)

    page.locator("#plantillas-section .pt-card").first.get_by_role(
        "button", name="Eliminar"
    ).click()
    page.wait_for_timeout(800)

    assert len(dialogs) == 1, f"esperado solo el confirm del dashboard, visto: {dialogs}"


def test_hostile_exercise_notice_creates_no_image_node(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    page.fill('#exercise-create-form input[name="ejercicio"]', PAYLOAD)
    page.fill('#exercise-create-form input[name="grupo_muscular"]', "Pectoral")
    page.select_option('#exercise-create-form select[name="categoria"]', "EMPUJE")
    page.click('#exercise-create-form button[type="submit"]')

    expect(page.locator("#notice-container .notice")).to_be_visible(timeout=3000)
    page.wait_for_timeout(500)
    assert page.locator("#notice-container img").count() == 0, "el payload no debe crear nodos HTML"
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


def test_week_click_navigates_to_first_session_of_week(page, server):
    """Clic real sobre el marcador de una semana lleva el editor al primer entreno de esa semana."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    # Dos sesiones en semanas distintas (lunes 10/08 y lunes 17/08) para que el
    # primer entreno de la semana del segundo clic sea inequívoco.
    iso_a = _iso(4)
    iso_b = _iso(11)
    for iso in (iso_a, iso_b):
        page.locator(f'.date-num[data-iso="{iso}"]').click()
        expect(page.locator(f'.date-num[data-iso="{iso}"]')).to_have_class(
            re.compile(r"\bselected\b")
        )
        _fill_row(page, 0)
        page.click('#edit-actions button[type="submit"]')
        expect(page.locator("#editor-notice .notice-success")).to_contain_text(
            "Entrenamiento guardado", timeout=2000
        )

    page.click("#cat-btn-Pectoral")
    page.locator("#unified-chart .js-plotly-plot").first.wait_for(state="visible", timeout=5000)
    page.locator("#unified-chart-plot .point").first.wait_for(state="visible", timeout=5000)

    semana_b = (datetime.date.fromisoformat(iso_b) - datetime.date(2026, 5, 4)).days // 7 + 1
    _click_chart_point(page, semana_b)
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_b, timeout=3000)


def test_category_filters_dots_sin_saltar_editor(page, server):
    """El botón de categoría filtra los dots del navegador y deja el editor en su fecha."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    iso = _iso(3)
    page.locator(f'.date-num[data-iso="{iso}"]').click()
    expect(page.locator(f'.date-num[data-iso="{iso}"]')).to_have_class(re.compile(r"\bselected\b"))
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )

    page.click(".today-btn")
    expect(page.locator(f'.date-num[data-iso="{_iso(0)}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    assert page.evaluate("document.querySelectorAll('.date-num .date-dot').length") >= 1

    page.click("#cat-btn-Pectoral")
    page.wait_for_timeout(800)
    assert page.evaluate("document.querySelectorAll('.date-num .date-dot').length") == 1
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(_iso(0), timeout=3000)

    page.click("#cat-btn-Pectoral")
    page.wait_for_timeout(800)
    assert page.evaluate("document.querySelectorAll('.date-num .date-dot').length") >= 1


def test_navigate_from_session_history(page, server):
    """Clic en una sesión del historial navega al editor de su fecha."""
    iso_a = _iso(8)
    iso_b = _iso(9)
    _goto_date(page, server, iso_a)
    _fill_row(page, 0, kg="80")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=5000)
    expect(page.locator("#session-history [data-action='goto-session']")).to_have_count(
        1, timeout=3000
    )

    _goto_date(page, server, iso_b)
    _fill_row(page, 0, kg="90")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=5000)
    expect(page.locator("#session-history [data-action='goto-session']")).to_have_count(
        2, timeout=3000
    )

    page.locator(f"#session-history [data-action='goto-session'][data-iso='{iso_a}']").click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_a, timeout=3000)
    expect(page.locator('input[name="kg"]')).to_have_value("80")
