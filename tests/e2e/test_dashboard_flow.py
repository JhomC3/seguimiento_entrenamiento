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


def test_rir_any_decimal_and_01_step(page, server):
    """RIR acepta cualquier decimal y las flechas (botones y teclado) avanzan 0,1."""
    _goto_date(page, server, _iso(10))
    row = page.locator("#set-rows .set-row").first
    rir = row.locator('input[name="rir"]')
    expect(rir).to_have_attribute("step", "any")

    rir.fill("0.25")
    row.locator('[data-action="rir-step"][data-delta="0.1"]').click()
    expect(rir).to_have_value("0.35")
    row.locator('[data-action="rir-step"][data-delta="-0.1"]').click()
    expect(rir).to_have_value("0.25")

    rir.focus()
    page.keyboard.press("ArrowDown")
    expect(rir).to_have_value("0.15")
    page.keyboard.press("ArrowUp")
    expect(rir).to_have_value("0.25")

    # Guardado con decimal arbitrario: el servidor lo acepta tal cual.
    _fill_row(page, 0, rir="0.25")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    expect(rir).to_have_value("0.25")


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


def test_week_click_opens_popup_en_primer_entreno(page, server):
    """Clic real sobre el marcador de una semana abre la ventana de registro
    en el primer entreno de esa semana."""
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

    page.click("#popup-close")
    page.locator('#cascade-row .level-chip[data-foco="Pectoral"]').click()
    page.wait_for_timeout(800)
    page.locator("#unified-chart .js-plotly-plot").first.wait_for(state="visible", timeout=5000)
    page.locator("#unified-chart-plot .point").first.wait_for(state="visible", timeout=5000)

    semana_b = (datetime.date.fromisoformat(iso_b) - datetime.date(2026, 5, 4)).days // 7 + 1
    _click_chart_point(page, semana_b)
    # La ventana de registro se abre en el primer entreno de la semana.
    expect(page.locator("#editor-popup")).to_be_visible(timeout=3000)
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso_b, timeout=3000)
    assert "registro=" + iso_b in page.url


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
    expect(page.locator("#cascade-row .level-chip")).to_have_count(2)  # sigue visible

    # Marcar el ejercicio: la gráfica tiene compilado + línea del ejercicio.
    exercise_chip.click()
    expect(exercise_chip).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )

    # Desmarcar (Shift+click): vuelve a solo el compilado.
    exercise_chip.click(modifiers=["Shift"])
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
    assert "musculos=Pectoral" in page.url

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


def test_muscle_toggle_y_escape_vuelven_al_cuerpo_completo(page, server):
    """Oprimir de nuevo el músculo seleccionado (o Escape) vuelve al grupo
    completo del cuerpo: gráfica sistémica, ejercicios limpios, URL base."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    muscle_chip = page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')
    expect(muscle_chip).to_be_visible(timeout=3000)

    # Seleccionar el músculo: se marca y aparecen sus ejercicios.
    muscle_chip.click()
    expect(muscle_chip).to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#ejercicios-row .exercise-chip")).to_be_visible(timeout=3000)

    # Oprimir de nuevo: se deselecciona y vuelve al cuerpo completo.
    muscle_chip.click()
    expect(muscle_chip).not_to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#ejercicios-row .exercise-chip")).to_have_count(0)
    expect(page.locator("#unified-chart")).to_contain_text("Rendimiento", timeout=3000)
    expect(page.locator("#unified-chart")).not_to_contain_text("Pectoral")
    assert "musculos=" not in page.url

    # Escape también deselecciona.
    muscle_chip.click()
    expect(muscle_chip).to_have_class(re.compile(r"\bselected\b"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    expect(muscle_chip).not_to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#ejercicios-row .exercise-chip")).to_have_count(0)
    assert "musculos=" not in page.url


def test_recarga_mantiene_musculo_y_ejercicios_seleccionados(page, server):
    """Tras recargar la página, el músculo sigue visiblemente seleccionado,
    los ejercicios marcados y la gráfica restaurada."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    muscle_chip = page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')
    expect(muscle_chip).to_be_visible(timeout=3000)
    muscle_chip.click()
    expect(muscle_chip).to_have_class(re.compile(r"\bselected\b"))
    exercise_chip = page.locator('#ejercicios-row .exercise-chip[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    exercise_chip.click()
    expect(exercise_chip).to_have_attribute("aria-pressed", "true")
    assert "musculos=Pectoral" in page.url
    assert "ejercicios=Press" in page.url

    # Recargar: el estado debe mantenerse completo y visible.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector('#cascade-row .level-chip[data-foco="Pectoral"]', timeout=5000)
    expect(page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator('#ejercicios-row .exercise-chip[data-foco="Press"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )


def test_multimusculo_con_shift_click_mantiene_global(page, server):
    """Shift+click añade músculos a la selección: la gráfica muestra el Global
    grueso + cada músculo tenue, y la fila de ejercicios se oculta."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    # Sesión del segundo músculo (día distinto) para que su traza tenga datos.
    page.locator(f'#popup-body .date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_timeout(400)
    _fill_row(page, 0, ejercicio="Curl", kg="12", reps="10", rir="1")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    pectoral = page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')
    expect(pectoral).to_be_visible(timeout=3000)
    pectoral.click()
    expect(pectoral).to_have_class(re.compile(r"\bselected\b"))
    # Fila de ejercicios visible con 1 músculo.
    expect(page.locator("#ejercicios-row .exercise-chip")).to_be_visible(timeout=3000)

    # Shift+click en otro músculo: se añade a la selección.
    biceps = page.locator('#cascade-row .level-chip[data-foco="Biceps"]')
    biceps.click(modifiers=["Shift"])
    expect(biceps).to_have_class(re.compile(r"\bselected\b"))
    expect(pectoral).to_have_class(re.compile(r"\bselected\b"))
    # Con 2 músculos: la fila de ejercicios se oculta.
    expect(page.locator("#ejercicios-row .exercise-chip")).to_have_count(0)
    assert "musculos=Pectoral%2CBiceps" in page.url
    # Gráfica: Global + 2 músculos tenues.
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 3; }",
        timeout=5000,
    )

    # Click simple en uno de los seleccionados: la selección se reemplaza
    # (solo ese) y la fila de ejercicios reaparece.
    biceps.click()
    expect(pectoral).not_to_have_class(re.compile(r"\bselected\b"))
    expect(biceps).to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#ejercicios-row .exercise-chip")).to_be_visible(timeout=3000)
    assert "musculos=Biceps" in page.url

    # Escape deselecciona todo → cuerpo entero puro.
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    expect(biceps).not_to_have_class(re.compile(r"\bselected\b"))
    expect(page.locator("#ejercicios-row .exercise-chip")).to_have_count(0)
    assert "musculos=" not in page.url


def test_multiejercicios_con_shift_click(page, server):
    """Shift+click añade ejercicios: compilado + cada ejercicio tenue."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    pectoral = page.locator('#cascade-row .level-chip[data-foco="Pectoral"]')
    expect(pectoral).to_be_visible(timeout=3000)
    pectoral.click()
    exercise_chip = page.locator('#ejercicios-row .exercise-chip[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    exercise_chip.click()
    expect(exercise_chip).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )
    assert "ejercicios=Press" in page.url

    # Shift+click sobre el mismo ejercicio lo quita de la selección.
    exercise_chip.click(modifiers=["Shift"])
    expect(exercise_chip).to_have_attribute("aria-pressed", "false")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 1; }",
        timeout=5000,
    )
    assert "ejercicios=" not in page.url


# ---------------------------------------------------------------------------
# Web plan Task 4: WCAG contrast and lazy Plotly
# ---------------------------------------------------------------------------


def _wcag_in_page(page, selector, pseudo=None):
    """Devuelve el ratio de contraste WCAG del color de texto calculado del
    elemento contra el background del body (fondo más claro disponible)."""
    return page.evaluate(
        """([sel, pseudo]) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const cs = getComputedStyle(el, pseudo || null);
            const bg = getComputedStyle(document.body).backgroundColor;
            const lin = (v) => {
                const c = v / 255;
                return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
            };
            const lum = (rgb) => {
                const m = rgb.match(/\\(([\\d.]+), ([\\d.]+), ([\\d.]+)/);
                if (!m) return 0;
                return 0.2126 * lin(+m[1]) + 0.7152 * lin(+m[2]) + 0.0722 * lin(+m[3]);
            };
            const l1 = lum(cs.color);
            const l2 = lum(bg);
            const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
            return (hi + 0.05) / (lo + 0.05);
        }""",
        [selector, pseudo],
    )


def test_wcag_contrast_critical_elements(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    vacio = _wcag_in_page(page, "#unified-chart .flex.items-center")
    assert vacio is not None and vacio >= 4.5, f"vacio: {vacio}"

    # El navigator y los inputs viven en el popup de registro.
    _open_popup(page, server)
    ratios = {
        "hoy": _wcag_in_page(page, ".today-btn"),
        "placeholder": _wcag_in_page(page, "input[placeholder]", "::placeholder"),
    }
    assert all(r is not None for r in ratios.values()), ratios
    for name, ratio in ratios.items():
        assert ratio >= 4.5, f"{name}: {ratio:.2f}:1"


def test_lazy_plotly_no_request_on_empty_chart(page, server):
    plotly_requests = []
    page.on("request", lambda r: plotly_requests.append(r.url) if "plotly" in r.url else None)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#unified-chart-data", state="detached")  # sin datos: no hay JSON
    page.wait_for_selector("#unified-chart .flex.items-center")
    assert plotly_requests == [], plotly_requests


def test_lazy_plotly_single_request_and_shell_stable(page, server):
    plotly_requests = []
    page.on("request", lambda r: plotly_requests.append(r.url) if "plotly" in r.url else None)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    empty_height = page.locator("#unified-chart-container").bounding_box()["height"]

    _goto_date(page, server, _iso(1))
    _wait_editor_settled(page)
    _fill_row(page, 0)
    # Envío nativo del form: el contenedor scrolleable del popup engaña a la
    # actionability de Playwright, así que se enfoca el input por DOM.
    page.locator('input[name="kg"]').first.evaluate("el => el.focus()")
    page.keyboard.press("Enter")
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    _wait_editor_settled(page)
    page.click("#popup-close")
    page.wait_for_selector("#editor-popup", state="hidden", timeout=5000)

    # La gráfica con datos se pide vía la cascada de niveles (Press = Pectoral).
    page.locator('.level-chip[data-action="select-muscle"][data-foco="Pectoral"]').click()
    page.wait_for_selector("#unified-chart-plot .main-svg", timeout=15000)
    loaded_height = page.locator("#unified-chart-container").bounding_box()["height"]
    assert abs(loaded_height - empty_height) <= 1.0, (empty_height, loaded_height)
    assert len(plotly_requests) == 1, plotly_requests


# ---------------------------------------------------------------------------
# Web plan Task 6: native dialogs and focus management
# ---------------------------------------------------------------------------


def test_popup_dialog_focus_roundtrip(page, server):
    """Abrir el popup mueve el foco dentro; cerrarlo lo devuelve al botón."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    trigger = page.locator('[data-action="open-editor-popup"]')
    trigger.focus()
    trigger.click()
    page.wait_for_selector("#popup-body #session-editor-wrap", timeout=5000)
    page.wait_for_timeout(200)
    inside = page.evaluate(
        "document.getElementById('editor-popup').contains(document.activeElement)"
    )
    assert inside, "el foco debe estar dentro del popup tras abrirlo"
    page.click("#popup-close")
    page.wait_for_selector("#editor-popup", state="hidden", timeout=5000)
    restored = page.evaluate(
        "document.activeElement === document.querySelector('[data-action=\"open-editor-popup\"]')"
    )
    assert restored, "el foco debe volver al botón que abrió el popup"


def test_confirm_dialog_focus_and_escape(page, server):
    """La confirmación de cambios sin guardar: foco dentro, Escape la cierra
    y restaura el foco al elemento que la disparó."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _open_popup(page, server)
    page.locator("#set-rows .set-row").first.locator('input[name="kg"]').fill("80")
    page.wait_for_timeout(150)
    page.locator('.date-num[data-iso="' + _iso(1) + '"]').click()
    page.wait_for_selector("#confirm-modal[open]", timeout=5000)
    inside = page.evaluate(
        "document.getElementById('confirm-modal').contains(document.activeElement)"
    )
    assert inside, "el foco debe estar dentro de la confirmación"
    page.keyboard.press("Escape")
    page.wait_for_selector("#confirm-modal", state="hidden", timeout=5000)
    assert page.locator("#editor-popup").evaluate("el => el.open"), "el popup debe seguir abierto"


def test_confirm_dialog_inside_popup_escape_chain(page, server):
    """Escape cierra solo la confirmación anidada; el popup sigue abierto y el
    foco vuelve a la confirmación anterior/dentro del popup."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _open_popup(page, server)
    page.locator("#set-rows .set-row").first.locator('input[name="kg"]').fill("80")
    page.wait_for_timeout(150)
    page.locator('.date-num[data-iso="' + _iso(1) + '"]').click()
    page.wait_for_selector("#confirm-modal[open]", timeout=5000)
    # Escape sobre la confirmación: se cierra solo ella.
    page.keyboard.press("Escape")
    page.wait_for_selector("#confirm-modal", state="hidden", timeout=5000)
    assert page.locator("#editor-popup").evaluate("el => el.open")
    inside = page.evaluate(
        "document.getElementById('editor-popup').contains(document.activeElement)"
    )
    assert inside, "el foco debe quedar dentro del popup tras cerrar la confirmación"
    # Escape ahora cierra el popup (cancel del dialog nativo).
    page.keyboard.press("Escape")
    page.wait_for_selector("#editor-popup", state="hidden", timeout=5000)


# ---------------------------------------------------------------------------
# Web plan Task 7: keyboard reorder, apply policy, undo, scoped arrows
# ---------------------------------------------------------------------------


def _edit_mode_on(page):
    """Entra en modo edición de la sesión (pencil)."""
    btn = page.locator('[data-action="toggle-edit"]')
    if "on" not in (btn.get_attribute("class") or ""):
        btn.click()
        page.wait_for_timeout(150)





def _drag_row_up(page, rows, idx, cell_selector):
    """Arrastra la fila idx hasta la posición de la fila idx-1 (Sortable).

    Se agarra desde una celda no-control (el selector indicado) para no
    disparar inputs/selects/buttons.
    """
    src = rows.nth(idx).locator(cell_selector).first.bounding_box()
    dst = rows.nth(idx - 1).locator(cell_selector).first.bounding_box()
    page.mouse.move(src["x"] + 10, src["y"] + src["height"] / 2)
    page.mouse.down()
    page.mouse.move(dst["x"] + 10, dst["y"] + dst["height"] / 2, steps=8)
    page.mouse.up()


def _drag_card_up(page, source_selector, target_selector):
    """Arrastra una tarjeta sobre la anterior (HTML5 draggable nativo).

    drag_to usa el drag de Chromium (la API mouse no dispara dragstart).
    Se agarra de la esquina superior (nombre), nunca del centro: el centro
    cae sobre los botones Aplicar/Editar/Eliminar y el dragstart los excluye.
    """
    page.locator(source_selector).drag_to(
        page.locator(target_selector),
        source_position={"x": 6, "y": 6},
        target_position={"x": 6, "y": 6},
    )


def test_session_rows_reorder_by_drag(page, server):
    _open_popup(page, server)
    _edit_mode_on(page)
    _fill_row(page, 0, ejercicio="Press")
    page.locator("#set-rows .set-row").first.locator('[data-action="row-add"]').click()
    page.wait_for_timeout(150)
    rows = page.locator("#set-rows .set-row")
    expect(rows).to_have_count(2)
    rows.nth(1).locator('input[name="kg"]').fill("90")
    _drag_row_up(page, rows, 1, ".set-num")
    page.wait_for_timeout(200)
    assert rows.nth(0).locator('input[name="kg"]').input_value() == "90"
    assert rows.nth(0).locator(".set-num").inner_text() == "1"


def test_training_cards_reorder_and_persist(page, server):
    _open_popup(page, server)
    page.locator("#session-editor [data-action='toggle-edit']").click()
    page.wait_for_timeout(150)
    # Guardar dos plantillas vía el form del editor (requiere fila con ejercicio).
    for i, nombre in enumerate(("Press Day", "Back Day")):
        _fill_row(page, 0, ejercicio="Press")
        page.locator('[data-action="toggle-template-form"]').click()
        page.wait_for_selector("#confirm-modal[open]", timeout=3000)
        page.keyboard.press("Enter")
        page.wait_for_selector("#save-template-form input[name='nombre']", timeout=3000)
        page.locator('#save-template-form input[name="nombre"]').fill(nombre)
        page.locator('#save-template-form input[name="nombre"]').evaluate("el => el.focus()")
        page.keyboard.press("Enter")
        # Segunda confirmación: guardar la plantilla con ese nombre.
        page.wait_for_selector("#confirm-modal[open]", timeout=3000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
    cards = page.locator("#plantillas-list .pt-card")
    expect(cards).to_have_count(2, timeout=3000)
    assert cards.nth(0).get_attribute("data-pt-nombre") == "Press Day"
    # Mover el segundo arriba con el ratón (cuerpo de la tarjeta).
    _drag_card_up(page, "#plantillas-list .pt-card:nth-child(2)", "#plantillas-list .pt-card:nth-child(1)")
    page.wait_for_timeout(600)
    expect(page.locator("#plantillas-list .pt-card").nth(0)).to_have_attribute(
        "data-pt-nombre", "Back Day"
    )
    # Persistencia tras recarga (el popup se reabre solo vía ?registro).
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#plantillas-list .pt-card", timeout=5000)
    expect(page.locator("#plantillas-list .pt-card").nth(0)).to_have_attribute(
        "data-pt-nombre", "Back Day"
    )


def test_reorder_failure_restores_order_and_notifies(page, server):
    _open_popup(page, server)
    page.locator("#session-editor [data-action='toggle-edit']").click()
    page.wait_for_timeout(150)
    for nombre in ("Press Day", "Back Day"):
        _fill_row(page, 0, ejercicio="Press")
        page.locator('[data-action="toggle-template-form"]').click()
        page.wait_for_selector("#confirm-modal[open]", timeout=3000)
        page.keyboard.press("Enter")
        page.wait_for_selector("#save-template-form input[name='nombre']", timeout=3000)
        page.locator('#save-template-form input[name="nombre"]').fill(nombre)
        page.locator('#save-template-form input[name="nombre"]').evaluate("el => el.focus()")
        page.keyboard.press("Enter")
        # Segunda confirmación: guardar la plantilla con ese nombre.
        page.wait_for_selector("#confirm-modal[open]", timeout=3000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
    cards = page.locator("#plantillas-list .pt-card")
    expect(cards).to_have_count(2, timeout=3000)

    def fail_reorder(route):
        route.abort()

    page.route("**/plantilla/reordenar", fail_reorder)
    _drag_card_up(page, "#plantillas-list .pt-card:nth-child(2)", "#plantillas-list .pt-card:nth-child(1)")
    page.wait_for_timeout(800)
    page.unroute("**/plantilla/reordenar")
    expect(page.locator("#plantillas-list .pt-card").nth(0)).to_have_attribute(
        "data-pt-nombre", "Press Day"
    )
    notices = page.evaluate(
        "[...document.querySelectorAll('#notice-container .notice, #editor-notice .notice')].map(n => n.textContent).join('|')"
    )
    assert "No se pudo guardar el orden" in notices


def test_nutrition_apply_confirms_replacement(page, server):
    _open_popup(page, server)
    # Crear una plantilla de alimentación: guardar el día con una fila.
    page.locator("#nutrition-rows .nutrition-row").first.locator('input[name="alimento"]').fill(
        "Pollo"
    )
    page.locator("#nutrition-rows .nutrition-row").first.locator('input[name="cantidad"]').fill(
        "150"
    )
    page.locator('[data-action="nutrition-toggle-template-form"]').click()
    page.locator('#save-meal-template-form input[name="nombre"]').fill("Comida A")
    page.locator('[data-action="confirm-meal-template-save"]').click()
    page.wait_for_timeout(500)
    apply_btn = page.locator('[data-action="apply-meal-template"]')
    expect(apply_btn).to_have_count(1, timeout=3000)
    # El día ya tiene filas: aplicar exige confirmación de reemplazo.
    apply_btn.click()
    page.wait_for_selector("#confirm-modal[open]", timeout=3000)
    msg = page.locator("#confirm-msg").inner_text()
    assert "Reemplazar" in msg
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    assert page.locator("#nutrition-rows .nutrition-row").count() >= 1




def test_date_arrows_ignored_outside_navigator(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    # Foco fuera del navigator: las flechas no navegan.
    page.locator('[data-action="open-editor-popup"]').focus()
    fecha_before = page.evaluate(
        "document.querySelector('.date-num.selected') ? document.querySelector('.date-num.selected').dataset.iso : null"
    )
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    fecha_after = page.evaluate(
        "document.querySelector('.date-num.selected') ? document.querySelector('.date-num.selected').dataset.iso : null"
    )
    assert fecha_before == fecha_after


def test_nutrition_rows_reorder_by_drag(page, server):
    _open_popup(page, server)
    page.locator('[data-action="nutrition-row-add"]').click()
    page.wait_for_timeout(120)
    rows = page.locator("#nutrition-rows .nutrition-row")
    expect(rows).to_have_count(2)
    rows.nth(0).locator('input[name="alimento"]').fill("Avena")
    rows.nth(0).locator('input[name="cantidad"]').fill("120")
    rows.nth(1).locator('input[name="alimento"]').fill("Pollo")
    rows.nth(1).locator('input[name="cantidad"]').fill("150")
    if rows.nth(0).locator('input[name="alimento"]').is_disabled():
        page.locator('[data-action="nutrition-toggle-edit"]').evaluate("el => el.click()")
        page.wait_for_timeout(150)
    _drag_row_up(page, rows, 1, ".nutrition-preview")
    page.wait_for_timeout(250)
    expect(rows.nth(0).locator('input[name="alimento"]')).to_have_value("Pollo")
    expect(rows.nth(1).locator('input[name="alimento"]')).to_have_value("Avena")
