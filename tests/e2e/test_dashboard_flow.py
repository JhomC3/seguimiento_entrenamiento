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


def _wait_editor_settled(page):
    """El swap htmx termina tras afterSwap/afterSettle: esperar el settle evita
    que un fill automatizado aterrice en el editor antiguo a mitad de swap."""
    page.wait_for_timeout(120)


def _open_popup(page, server):
    """Los editores viven en la ventana emergente de registro (contrato v3)."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="open-editor-popup"]')
    page.wait_for_selector("#popup-body #session-editor-wrap", timeout=5000)
    page.wait_for_selector("#popup-body #nutrition-form", timeout=5000)


def _goto_date(page, server, iso):
    _open_popup(page, server)
    before = page.locator("#session-date-title h3").inner_text()
    page.locator(f'#popup-body .date-num[data-iso="{iso}"]').click()
    expect(page.locator(f'#popup-body .date-num[data-iso="{iso}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    # El título global cambia con la navegación
    expect(page.locator("#session-date-title h3")).not_to_have_text(before)
    expect(page.locator("#session-date-title")).to_contain_text("Semana")
    _wait_editor_settled(page)


def _simulate_drag(page, source_sel, target_sel):
    """Drag HTML5 sintético (dragstart → dragover → drop → dragend)."""
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


def _click_chart_point(page, semana):
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
    _open_popup(page, server)
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
    expect(page.locator("#session-date-title")).to_contain_text("Semana")
    expect(page.locator('#session-form input[name="fecha"]')).to_have_value(_iso(2))


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
    # Las plantillas viven dentro del popup: permanece abierto.
    expect(page.locator("#plantillas-section [data-pt-nombre]")).to_have_count(1, timeout=3000)


def test_apply_template(page, server):
    _create_template(page, server, _iso(3), "Mi Empuje")
    iso = _iso(4)
    _goto_date(page, server, iso)
    expect(page.locator("#session-editor")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "0")
    page.locator("#plantillas-section .pt-card").get_by_role("button", name="Aplicar").click()
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entreno aplicado", timeout=3000
    )
    # El contenido aplicado aterriza en el editor (el día pasa a tener datos) y el
    # marcador interno del swap se consume.
    expect(page.locator("#editor-state")).to_have_attribute("data-has-data", "1", timeout=3000)
    expect(page.locator("#plantilla-applied")).to_have_count(0)
    expect(page.locator("#set-rows .ej-select").first).to_have_value("Press")
    # Aplicar deja el editor guardable: baseline limpio y #edit-actions visible.
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

    _open_popup(page, server)
    _fill_row(page, 0, kg="75", reps="8")
    page.locator("#session-editor .save-template-btn").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    page.locator('#save-template-form input[name="nombre"]').fill("B")
    page.locator("#save-template-form .btn-check").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(2)

    second_id = page.locator("#plantillas-section .pt-card").nth(1).get_attribute("data-pt-id")
    _simulate_drag(
        page,
        f"#plantillas-section .pt-card[data-pt-id='{second_id}']",
        "#plantillas-section #plantillas-list",
    )
    expect(page.locator("#plantillas-section .pt-card").nth(0)).to_have_attribute(
        "data-pt-id", second_id, timeout=3000
    )

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
    expect(page.locator("#confirm-modal")).to_be_visible()
    expect(page.locator("#confirm-msg")).to_contain_text(PAYLOAD)
    assert len(dialogs) == 0, f"no debe haber dialogs nativos, visto: {dialogs}"


def test_hostile_exercise_notice_creates_no_image_node(page, server):
    _open_popup(page, server)

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
    _open_popup(page, server)

    # Dos sesiones en semanas distintas (lunes 10/08 y lunes 17/08) para que el
    # primer entreno de la semana del segundo clic sea inequívoco.
    iso_a = _iso(4)
    iso_b = _iso(11)
    for iso in (iso_a, iso_b):
        page.locator(f'#popup-body .date-num[data-iso="{iso}"]').click()
        expect(page.locator(f'#popup-body .date-num[data-iso="{iso}"]')).to_have_class(
            re.compile(r"\bselected\b")
        )
        expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
        _wait_editor_settled(page)
        _fill_row(page, 0)
        page.click('#edit-actions button[type="submit"]')
        expect(page.locator("#editor-notice .notice-success")).to_contain_text(
            "Entrenamiento guardado", timeout=2000
        )

    # El popup se cierra pero su DOM persiste: la navegación desde la gráfica
    # actualiza el editor oculto.
    page.click("#popup-close")
    page.locator('#cascade-row .level-chip[data-foco="Pectoral"]').click()
    page.wait_for_timeout(800)
    page.locator("#unified-chart .js-plotly-plot").first.wait_for(state="visible", timeout=5000)
    page.locator("#unified-chart-plot .point").first.wait_for(state="visible", timeout=5000)

    semana_b = (datetime.date.fromisoformat(iso_b) - datetime.date(2026, 5, 4)).days // 7 + 1
    _click_chart_point(page, semana_b)
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_b, timeout=3000)


def test_cascade_musculo_persistente_y_multi_traza(page, server):
    """El músculo elegido permanece visible y la gráfica suma líneas por
    ejercicio marcado (compilado + individuales)."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    # Fila de músculos siempre visible.
    muscle_chip = page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')
    expect(muscle_chip).to_be_visible(timeout=3000)

    # Elegir músculo: se marca (no desaparece) y aparecen sus ejercicios.
    muscle_chip.click()
    expect(muscle_chip).to_have_class(re.compile(r"\bselected\b"))
    exercise_chip = page.locator('#ejercicios-row .exercise-chip[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    expect(page.locator("#cascade-row .level-chip")).to_have_count(1)  # sigue visible

    # Marcar el ejercicio: la gráfica tiene compilado + línea del ejercicio.
    exercise_chip.click()
    expect(exercise_chip).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )

    # Desmarcar: vuelve a solo el compilado.
    exercise_chip.click()
    expect(exercise_chip).to_have_attribute("aria-pressed", "false")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 1; }",
        timeout=5000,
    )


def test_grafica_atras_del_navegador_restaura(page, server):
    """El botón atrás navega dentro de la app (músculo → estado base)."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    page.locator('#cascade-row .level-chip[data-foco="Pectoral"]').click()
    expect(page.locator("#ejercicios-row .exercise-chip")).to_be_visible(timeout=3000)
    assert "musculo=Pectoral" in page.url

    page.go_back()
    page.wait_for_timeout(800)
    # Volvió al estado base: sin ejercicios seleccionados y dentro de la app.
    assert page.url.endswith("/") or "?" not in page.url.split("/")[-1]
    expect(page.locator("#ejercicios-row .exercise-chip")).to_have_count(0)


def test_mobile_viewport_renders(page, server):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="open-editor-popup"]')
    page.wait_for_selector("#popup-body #session-editor-wrap", timeout=5000)
    assert page.is_visible("#session-editor")
    assert page.is_visible("#date-navigator")
    can_scroll = page.evaluate(
        "() => { const el = document.querySelector('#session-editor .table-scroll');"
        " return el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight; }"
    )
    assert can_scroll


def test_keyboard_day_shift_updates_editor(page, server):
    _open_popup(page, server)
    page.locator("#popup-body .today-btn").click()
    _wait_editor_settled(page)
    fecha = page.input_value("#session-form input[name='fecha']")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(
        "(expected) => document.querySelector(\"#session-form input[name='fecha']\").value !== expected",
        arg=fecha,
    )


def test_keyboard_focus_ring_visible(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.keyboard.press("Tab")
    has_outline = page.evaluate(
        "() => { const e = document.activeElement; const cs = getComputedStyle(e);"
        " return cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px'; }"
    )
    assert has_outline


def test_template_delete_uses_custom_modal(page, server):
    _create_template(page, server, _iso(5), "Eliminame")
    page.locator("#plantillas-section .pt-card").get_by_role("button", name="Eliminar").click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    expect(page.locator("#confirm-msg")).to_contain_text("Eliminame")
    page.locator("#confirm-save").click()
    expect(page.locator("#plantillas-section .pt-card")).to_have_count(0, timeout=3000)
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Entreno eliminado", timeout=2000
    )


def test_navigate_por_fecha_del_navegador_del_popup(page, server):
    """Navegar por el strip de fechas actualiza el editor del popup."""
    iso_a = _iso(8)
    iso_b = _iso(9)
    _goto_date(page, server, iso_a)
    _fill_row(page, 0, kg="80")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=5000)

    _goto_date(page, server, iso_b)
    _fill_row(page, 0, kg="90")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=5000)

    page.locator(f'#popup-body .date-num[data-iso="{iso_a}"]').click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_a, timeout=3000)
    expect(page.locator('input[name="kg"]')).to_have_value("80")
