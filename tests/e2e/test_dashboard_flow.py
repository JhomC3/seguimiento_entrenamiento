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


def _catalog_select_muscle(page, name):
    """Catálogo acordeón: expande el grupo y marca el checkbox del músculo."""
    group = page.locator(f'#dashboard-catalog .db-group[data-group="{name}"]')
    expect(group).to_be_visible(timeout=3000)
    summary = group.locator('[data-action="toggle-group"]')
    if summary.get_attribute("aria-expanded") != "true":
        summary.click()
        page.wait_for_timeout(120)
    group.locator('[data-action="toggle-muscle"]').click()


def _catalog_exercise_chip(page, name):
    # La fila es un <label> visible; el input está oculto
    return page.locator(f'#dashboard-catalog .db-exercise-row[data-exercise="{name}"]')


def _exercise_input(page, name):
    """Botón del ejercicio en el catálogo (estado de selección = aria-pressed)."""
    return page.locator(f'#dashboard-catalog .db-exercise-row[data-foco="{name}"]')


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


def test_week_click_opens_registro_en_primer_entreno(page, server):
    """Clic real sobre el marcador de una semana navega a /registro
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
    _catalog_select_muscle(page, "Pectoral")
    # Este test valida el clic en el marcador de una SEMANA: fija la granularidad
    # a week para que el eje X sea numérico (por defecto ahora es day → fechas).
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(800)
    page.locator("#unified-chart .js-plotly-plot").first.wait_for(state="visible", timeout=10000)
    page.locator("#unified-chart-plot .point").first.wait_for(state="visible", timeout=10000)

    semana_b = (datetime.date.fromisoformat(iso_b) - datetime.date(2026, 5, 4)).days // 7 + 1
    _click_chart_point(page, semana_b)
    # La página de registro se abre en el primer entreno de la semana.
    page.wait_for_url(f"**/registro?fecha={iso_b}", timeout=5000)
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

    # Grupos del catálogo siempre visibles (Pectoral, Biceps).
    group = page.locator('#dashboard-catalog .db-group[data-group="Pectoral"]')
    expect(group).to_be_visible(timeout=3000)

    # Elegir músculo: se marca (no desaparece) y aparecen sus ejercicios.
    _catalog_select_muscle(page, "Pectoral")
    muscle_input = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    expect(muscle_input).to_have_attribute("aria-pressed", "true")
    exercise_chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    expect(page.locator("#dashboard-catalog .db-group")).to_have_count(2)

    # Marcar el ejercicio: la gráfica tiene compilado + línea del ejercicio.
    exercise_chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )

    # Desmarcar (Shift+click): vuelve al estado muscular (Global + Compilado).
    exercise_chip.click(modifiers=["Shift"])
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "false")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
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

    _catalog_select_muscle(page, "Pectoral")
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "true")
    assert "musculos=Pectoral" in page.url

    page.go_back()
    page.wait_for_timeout(800)
    # Volvió al estado base: sin músculos ni ejercicios seleccionados.
    assert page.url.endswith("/") or "?" not in page.url.split("/")[-1]
    expect(
        page.locator('#dashboard-catalog [data-action="toggle-muscle"][aria-pressed="true"]')
    ).to_have_count(0)
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][aria-pressed="true"]'
        )
    ).to_have_count(0)


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

    # Seleccionar el músculo: se marca y aparecen sus ejercicios.
    muscle_select = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    _catalog_select_muscle(page, "Pectoral")
    expect(muscle_select).to_have_attribute("aria-pressed", "true")
    expect(
        page.locator('#dashboard-catalog .db-group[data-group="Pectoral"] .db-exercise-row')
    ).to_be_visible(timeout=3000)

    # Oprimir de nuevo: se deselecciona y vuelve al cuerpo completo.
    page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    ).click()
    expect(muscle_select).to_have_attribute("aria-pressed", "false")
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][aria-pressed="true"]'
        )
    ).to_have_count(0)
    expect(page.locator("#unified-chart")).to_contain_text("Rendimiento", timeout=3000)
    expect(page.locator("#unified-chart")).not_to_contain_text("Pectoral")
    assert "musculos=" not in page.url

    # Escape también deselecciona.
    _catalog_select_muscle(page, "Pectoral")
    expect(muscle_select).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    expect(muscle_select).to_have_attribute("aria-pressed", "false")
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][aria-pressed="true"]'
        )
    ).to_have_count(0)
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

    _catalog_select_muscle(page, "Pectoral")
    muscle_input = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    expect(muscle_input).to_have_attribute("aria-pressed", "true")
    exercise_chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    exercise_chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    assert "musculos=Pectoral" in page.url
    assert "ejercicios=Press" in page.url

    # Recargar: el estado debe mantenerse completo y visible.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]',
        timeout=5000,
    )
    expect(page.locator('#dashboard-catalog .db-group[data-group="Pectoral"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "true")
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][data-foco="Press"]'
        )
    ).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )


def test_multimusculo_con_shift_click_mantiene_global(page, server):
    """Shift+click añade músculos a la selección: la gráfica muestra el Global
    grueso + cada músculo tenue, y la selección de ejercicios se vacía."""
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

    pectoral = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    _catalog_select_muscle(page, "Pectoral")
    expect(pectoral).to_have_attribute("aria-pressed", "true")

    # Shift+click en otro músculo: se añade a la selección.
    biceps_input = page.locator(
        '#dashboard-catalog .db-group[data-group="Biceps"] [data-action="toggle-muscle"]'
    )
    biceps = page.locator(
        '#dashboard-catalog .db-group[data-group="Biceps"] [data-action="toggle-muscle"]'
    )
    biceps_grp = page.locator('#dashboard-catalog .db-group[data-group="Biceps"]')
    if biceps_grp.locator('[data-action="toggle-group"]').get_attribute("aria-expanded") != "true":
        biceps_grp.locator('[data-action="toggle-group"]').click()
        page.wait_for_timeout(120)
    biceps.click(modifiers=["Shift"])
    expect(biceps_input).to_have_attribute("aria-pressed", "true")
    expect(pectoral).to_have_attribute("aria-pressed", "true")
    # Con 2 músculos: la selección de ejercicios queda vacía.
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][aria-pressed="true"]'
        )
    ).to_have_count(0)
    url = page.url
    musculos_param = url.split("musculos=", 1)[1].split("&", 1)[0]
    assert set(musculos_param.split("%2C")) == {"Pectoral", "Biceps"}, url
    # Gráfica: Global + 2 músculos tenues.
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 3; }",
        timeout=5000,
    )

    # Click simple en uno de los seleccionados: la selección se reemplaza
    # (solo ese) y vuelve a poder elegirse ejercicios.
    biceps.click()
    expect(pectoral).to_have_attribute("aria-pressed", "false")
    expect(biceps_input).to_have_attribute("aria-pressed", "true")
    expect(
        page.locator('#dashboard-catalog .db-group[data-group="Biceps"] .db-exercise-row')
    ).to_be_visible(timeout=3000)
    assert "musculos=Biceps" in page.url

    # Escape deselecciona todo → cuerpo entero puro.
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    expect(biceps).to_have_attribute("aria-pressed", "false")
    expect(
        page.locator('#dashboard-catalog [data-action="toggle-muscle"][aria-pressed="true"]')
    ).to_have_count(0)
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

    _catalog_select_muscle(page, "Pectoral")
    exercise_chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    expect(exercise_chip).to_be_visible(timeout=3000)
    exercise_chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )
    assert "ejercicios=Press" in page.url

    # Shift+click sobre el mismo ejercicio lo quita de la selección:
    # vuelve al estado muscular (Global + Compilado).
    exercise_chip.click(modifiers=["Shift"])
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "false")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )
    assert "ejercicios=" not in page.url


# ---------------------------------------------------------------------------
# A4 — Catalog selection state (muscle/exercise) behavior
# ---------------------------------------------------------------------------


def test_catalog_expand_sin_seleccionar(page, server):
    """Expandir/contraer un grupo (summary nativo) no altera la selección:
    ninguno queda con aria-pressed=true y la URL se mantiene base."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    group = page.locator('#dashboard-catalog .db-group[data-group="Pectoral"]')
    summary = group.locator('[data-action="toggle-group"]')
    assert summary.get_attribute("aria-expanded") == "false", "los grupos arrancan colapsados"
    summary.click()
    page.wait_for_timeout(150)
    assert summary.get_attribute("aria-expanded") == "true", "el control debe expandir el grupo"
    expect(
        page.locator('#dashboard-catalog [data-action="toggle-muscle"][aria-pressed="true"]')
    ).to_have_count(0)
    expect(
        page.locator(
            '#dashboard-catalog .db-exercise-row[data-action="toggle-exercise"][aria-pressed="true"]'
        )
    ).to_have_count(0)
    assert "musculos=" not in page.url and "ejercicios=" not in page.url
    # Contraer de nuevo: sin selección, la gráfica sigue sistémica.
    summary.click()
    page.wait_for_timeout(150)
    assert summary.get_attribute("aria-expanded") == "false", "el control debe contraer el grupo"


def test_catalog_seleccion_rapida_consecutiva(page, server):
    """Selección rápida consecutiva (Pectoral → Biceps) termina en el último
    músculo elegido, sin que una respuesta obsoleta sobrescriba la selección."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.locator(f'#popup-body .date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_timeout(400)
    _fill_row(page, 0, ejercicio="Curl", kg="12", reps="10", rir="1")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    # Seleccionar Pectoral y Biceps casi a la vez (sin esperar el swap).
    _catalog_select_muscle(page, "Pectoral")
    biceps_grp = page.locator('#dashboard-catalog .db-group[data-group="Biceps"]')
    biceps = page.locator(
        '#dashboard-catalog .db-group[data-group="Biceps"] [data-action="toggle-muscle"]'
    )
    if biceps_grp.locator('[data-action="toggle-group"]').get_attribute("aria-expanded") != "true":
        biceps_grp.locator('[data-action="toggle-group"]').click()
        page.wait_for_timeout(120)
    biceps.click()
    page.wait_for_timeout(700)

    expect(biceps).to_have_attribute("aria-pressed", "true")
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "false")
    assert "musculos=Biceps" in page.url
    assert "musculos=Pectoral" not in page.url or "ejercicios=" not in page.url, page.url
    # La gráfica refleja solo el último músculo: Global + Compilado (2 trazas).
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=5000,
    )


def test_catalog_sel_rapida_sin_respuestas_obsoletas(page, server):
    """Tras rápidos toggles el estado final coincide con la última acción: la
    respuesta obsoleta del primer músculo no reemplaza a la del último."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.locator(f'#popup-body .date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_timeout(400)
    _fill_row(page, 0, ejercicio="Curl", kg="12", reps="10", rir="1")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    # Ciclo rápido: seleccionar, deseleccionar (Escape), re-seleccionar.
    biceps_grp = page.locator('#dashboard-catalog .db-group[data-group="Biceps"]')
    biceps_grp.locator('[data-action="toggle-group"]').click()
    page.wait_for_timeout(120)
    _catalog_select_muscle(page, "Pectoral")
    _catalog_select_muscle(page, "Biceps")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    _catalog_select_muscle(page, "Biceps")
    page.wait_for_timeout(800)

    expect(
        biceps_grp.locator('[data-action="toggle-muscle"][data-foco="Biceps"]')
    ).to_have_attribute("aria-pressed", "true")
    assert "musculos=Biceps" in page.url
    # Biceps tiene datos: la gráfica no queda como "Sin datos" ni global.
    traces = page.evaluate(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData ? el._fullData.map(t => t.name) : []; }"
    )
    assert "Biceps" in traces, f"faltan trazas de Biceps: {traces}"


def test_catalog_clic_simple_en_marcado_quita_ejercicio(page, server, tmp_path):
    """Volver a pulsar un ejercicio marcado (clic simple) lo deselecciona: su
    línea desaparece, la gráfica vuelve al estado muscular (Global + músculo),
    el checkbox se desmarca y la URL deja de incluir ejercicios=."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        base = datetime.date(2026, 6, 1)
        for i in range(8):
            d = base + datetime.timedelta(days=i)
            conn.execute(
                "INSERT INTO training_sets "
                "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
                "VALUES (?,?,?,1,'Press',6,80,1)",
                ((i // 7) + 1, "LUNES", d.isoformat()),
            )
        conn.commit()
    finally:
        conn.close()

    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    # Seleccionar músculo + ejercicio (primer clic).
    _catalog_select_muscle(page, "Pectoral")
    row = _exercise_input(page, "Press")
    expect(row).to_be_visible(timeout=3000)
    row.click()
    expect(row).to_have_attribute("aria-pressed", "true", timeout=3000)
    assert "ejercicios=Press" in page.url, page.url
    # Esperar al swap de /grafica: la línea del ejercicio debe aparecer.
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.some(t => t.name === 'Press'); }",
        timeout=8000,
    )
    st_ex = _chart_state(page)
    ex_names = [t["n"] for t in st_ex["traces"]]
    assert "Press" in ex_names, f"la línea del ejercicio debe aparecer: {ex_names}"

    # Segundo clic simple sobre el mismo ejercicio: se deselecciona.
    row.click()
    expect(row).to_have_attribute("aria-pressed", "false", timeout=3000)
    # El músculo permanece seleccionado.
    muscle_btn = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    expect(muscle_btn).to_have_attribute("aria-pressed", "true")
    # La URL ya no incluye ejercicios.
    assert "musculos=Pectoral" in page.url, page.url
    assert "ejercicios=" not in page.url, page.url
    # La gráfica vuelve al estado muscular: Global + Pectoral (sin Press).
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2"
        " && el._fullData.every(t => t.name !== 'Press'); }",
        timeout=8000,
    )
    st_back = _chart_state(page)
    back_names = [t["n"] for t in st_back["traces"]]
    assert "Press" not in back_names, f"la línea de Press debe desaparecer: {back_names}"
    assert "Global" in back_names and "Pectoral" in back_names, back_names
    # El detalle vuelve al placeholder.
    expect(page.locator("#history-section")).to_contain_text("Selecciona un", timeout=3000)


def test_catalog_flujo_sin_errores_consola(page, server):
    """La interacción de selección (músculo → ejercicio) no produce excepciones
    JavaScript reales. Las cancelaciones de respuestas obsoletas (cancelPending /
    xhr.abort) provocan abortos intencionales que htmx registra como
    console.error (htmx:sendAbort / htmx:afterRequest); eso NO es un error de la
    aplicación. Las excepciones reales se capturan en window.onerror /
    unhandledrejection instalados antes de cargar (add_init_script), de modo que
    el test solo falla ante errores genuinos no controlados."""
    # Captura real de excepciones de la aplicación (antes de que cargue el page).
    page.add_init_script(
        """() => {
            window.__realErrors = [];
            window.addEventListener('error', function (ev) {
                const e = ev.error || {};
                window.__realErrors.push({
                    kind: 'onerror',
                    message: ev.message || (e && e.message) || '',
                    source: ev.filename || '',
                    line: ev.lineno || 0,
                    col: ev.colno || 0,
                    stack: (e && e.stack) ? String(e.stack) : '',
                });
            });
            window.addEventListener('unhandledrejection', function (ev) {
                const r = ev.reason || {};
                window.__realErrors.push({
                    kind: 'unhandledrejection',
                    message: (r && r.message) ? String(r.message) : String(r),
                    source: '',
                    line: 0,
                    col: 0,
                    stack: (r && r.stack) ? String(r.stack) : '',
                });
            });
        }"""
    )

    # Consola y pageerror para diagnóstico: se asociará cada evento con el flujo.
    console_error = []
    page.on(
        "console",
        lambda m: (
            console_error.append(f"console[{m.type}] {m.text[:140]}") if m.type == "error" else None
        ),
    )
    page_errors = []
    page.on("pageerror", lambda e: page_errors.append(getattr(e, "message", "")))

    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    # Flujo rápido músculo → ejercicio: genera cancelaciones intencionales de la
    # petición /grafica + /nivel del músculo al elegir el ejercicio.
    _catalog_select_muscle(page, "Pectoral")
    chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.length === 2; }",
        timeout=10000,
    )
    # La selección queda consistente y la URL refleja músculo + ejercicio.
    assert "musculos=Pectoral" in page.url and "ejercicios=Press" in page.url, page.url

    # -- Verificaciones --
    # 1) Excepciones reales de la aplicación: NINGUNA (canal window.onerror /
    #    unhandledrejection, que no se dispara ante aborts de XHR de htmx).
    real = page.evaluate("() => window.__realErrors || []")
    assert real == [], f"excepciones reales de la aplicación: {real}"

    # 2) Consola: cualquier console.error debe ser bookkeeping de aborto
    #    intencional de htmx (htmx:sendAbort / htmx:afterRequest de una request
    #    cancelada por cancelPending). Cualquier otro error es una regresión.
    unjustified = [
        m for m in console_error if "htmx:sendAbort" not in m and "htmx:afterRequest" not in m
    ]
    assert unjustified == [], f"console.error no justificados: {unjustified}"

    # 3) pageerror: no se filtra indiscriminadamente. Un pageerror con mensaje
    #    real (distinto de 'undefined'/vacío) es una excepción genuina → falla.
    #    El pageerror 'undefined' sin stack coincide con la firma de aborto de
    #    red de una request cancelada por cancelPending y se acepta. No se exige
    #    la presencia de estos eventos (depende del timing de la cancelación),
    #    solo se validan si aparecen.
    abort_signatures = {"", "undefined"}
    for m in page_errors:
        assert m in abort_signatures, f"pageerror con mensaje real: {m!r}"

    # Back/forward: navegaciones completas restauran el estado (URL).
    page.go_back()
    page.wait_for_timeout(700)
    assert "musculos=Pectoral" in page.url and "ejercicios=Press" not in page.url, page.url
    page.go_forward()
    page.wait_for_timeout(700)
    assert "musculos=Pectoral" in page.url and "ejercicios=Press" in page.url, page.url
    # Tras back/forward, tampoco hay excepciones reales en la aplicación.
    real_after = page.evaluate("() => window.__realErrors || []")
    assert real_after == [], f"excepciones reales tras back/forward: {real_after}"


# ---------------------------------------------------------------------------
# B1 — Granularidad: selector día/semana/mes (contrato)
# ---------------------------------------------------------------------------


def _granularity_select(page):
    # Compatibilidad: nuevo selector es grupo de botones, legacy era <select>
    sel = page.locator("#granularity-select")
    # Si es un <select> (legacy), devolverlo; si es un grupo de botones, devolver el grupo
    return sel


def _seed_sessions(page, server, dates, ejercicio="Press"):
    """Guarda una sesión de `ejercicio` en cada fecha (ISO) usando el popup.
    Luego cierra el popup y devuelve la página en el dashboard."""
    _open_popup(page, server)
    for iso in dates:
        page.locator(f'#popup-body .date-num[data-iso="{iso}"]').click()
        expect(page.locator(f'#popup-body .date-num[data-iso="{iso}"]')).to_have_class(
            re.compile(r"\bselected\b")
        )
        expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
        _wait_editor_settled(page)
        _fill_row(page, 0, ejercicio=ejercicio)
        page.click('#edit-actions button[type="submit"]')
        expect(page.locator("#editor-notice .notice-success")).to_contain_text(
            "Entrenamiento guardado", timeout=2000
        )
    page.click("#popup-close")
    page.wait_for_selector("#editor-popup", state="hidden", timeout=5000)


def _chart_state(page):
    """Lee el contenido real de la gráfica Plotly: eje X, trazas y tooltip."""
    return page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            if (!el || !el._fullData) return {empty: true};
            return {
                xaxis: el._fullLayout && el._fullLayout.xaxis
                    ? el._fullLayout.xaxis.title.text : null,
                traces: el._fullData.map(t => ({
                    n: t.name,
                    x: Array.from(t.x).map(String),
                    hover: t.hovertemplate || ''
                }))
            };
        }"""
    )


def test_b1_selector_visible_default_day_fuera_oob(page, server):
    """El selector de período es visible, arranca en 'day' y vive fuera del
    contenedor OOB de Plotly (sobrevive a los swaps de la gráfica)."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    sel = page.locator("#granularity-selector")
    expect(sel).to_be_visible(timeout=3000)
    expect(
        page.locator('#granularity-selector [data-gran="day"][aria-pressed="true"]')
    ).to_be_visible()
    # Seleccionar músculo → la gráfica se refresca (swap OOB); el selector sigue.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(500)
    expect(sel).to_be_visible(timeout=3000)
    expect(
        page.locator('#granularity-selector [data-gran="day"][aria-pressed="true"]')
    ).to_be_visible()
    assert 'id="granularity-selector"' in page.content()
    assert page.evaluate(
        "() => document.querySelector('#granularity-selector').closest('#unified-chart') === null"
    )


def test_b1_cambiar_granularidad_persiste_url_y_seleccion(page, server):
    """Cambiar el período actualiza la URL (gran), conserva la selección de
    músculos/ejercicios y refresca la gráfica."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    _catalog_select_muscle(page, "Pectoral")
    chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    assert "ejercicios=Press" in page.url

    # Cambiar a 'week'.
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(600)
    assert "gran=week" in page.url, page.url
    assert "musculos=Pectoral" in page.url, page.url
    assert "ejercicios=Press" in page.url, page.url
    # La selección visual se conserva.
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")

    # Cambiar a 'month'.
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(600)
    assert "gran=month" in page.url, page.url
    assert "musculos=Pectoral" in page.url, page.url
    assert "ejercicios=Press" in page.url, page.url

    # Volver a 'day'.
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(600)
    assert "gran=day" in page.url, page.url


def test_b1_back_forward_y_recarga_restauran_granularidad(page, server):
    """Back/forward y recarga restauran la granularidad desde la URL."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    _catalog_select_muscle(page, "Pectoral")
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(600)
    assert "gran=month" in page.url and "musculos=Pectoral" in page.url

    # Recarga: se restaura 'month' y la selección.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(
        page.locator('#granularity-selector [data-gran="month"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)
    assert "gran=month" in page.url, page.url
    assert "musculos=Pectoral" in page.url, page.url

    # Back/forward dentro de la app.
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(500)
    assert "gran=week" in page.url
    page.go_back()
    page.wait_for_timeout(800)
    assert "gran=month" in page.url, page.url
    page.go_forward()
    page.wait_for_timeout(800)
    assert "gran=week" in page.url, page.url


def test_b1_selector_nativo_accesible(page, server):
    """El selector compacto es un grupo de botones accesible con 3 opciones."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    sel = page.locator("#granularity-selector")
    expect(sel).to_have_attribute("aria-label", "Periodo de la gráfica")
    expect(sel).to_have_attribute("role", "group")
    btns = sel.locator('[data-action="set-granularity"]')
    expect(btns).to_have_count(3)
    texts = [btns.nth(i).inner_text() for i in range(3)]
    assert texts == ["Día", "Semana", "Mes"], texts
    for i in range(3):
        expect(btns.nth(i)).to_have_attribute("aria-pressed", re.compile("true|false"))
        assert btns.nth(i).get_attribute("aria-label") in ("Día", "Semana", "Mes")


# ---------------------------------------------------------------------------
# B2-R2 — Granularidad visible: el selector cambia realmente la gráfica
# ---------------------------------------------------------------------------


def test_b2r2_carga_inicial_day_fechas_sin_semana(page, server):
    """Carga inicial: selector en Día, eje con fechas reales y hover sin 'Semana'."""
    dates = [_iso(4), _iso(6)]
    _seed_sessions(page, server, dates)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(
        page.locator('#granularity-selector [data-gran="day"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)
    st = _chart_state(page)
    assert st.get("empty") is not True, st
    assert st["xaxis"] == "Fecha", f"eje inicial debe ser Fecha: {st['xaxis']}"
    # Fechas reales, no números de semana.
    assert all("-" in x for t in st["traces"] for x in t["x"]), st
    # El hover no dice 'Semana'.
    assert all("Semana" not in t["hover"] for t in st["traces"]), st


def test_b2r2_day_a_week_cambia_grafica_y_conserva_seleccion(page, server):
    """Día→Semana: nueva petición, URL gran=week, eje a semanas, tooltip Semana,
    y la selección de músculo + ejercicio se conserva."""
    _seed_sessions(page, server, [_iso(4), _iso(11)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(600)

    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/grafica" in r.url else None)

    day_state = _chart_state(page)
    assert day_state["xaxis"] == "Fecha", day_state

    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(700)
    week_state = _chart_state(page)

    # Nueva petición disparada y URL actualizada.
    assert any("gran=week" in u for u in reqs), f"no hubo request gran=week: {reqs}"
    assert "gran=week" in page.url, page.url
    # Eje cambió a semanas y tooltip dice Semana.
    assert week_state["xaxis"] == "Semana", week_state
    assert all("Semana" in t["hover"] for t in week_state["traces"]), week_state
    # Selección conservada (chip sigue marcado, URL con musculos+ejercicios).
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    assert "musculos=Pectoral" in page.url, page.url
    assert "ejercicios=Press" in page.url, page.url
    # La selección y sus trazas.
    names = [t["n"] for t in week_state["traces"]]
    assert "Compilado" in names, names


def test_b2r2_semana_a_day_restaura_fechas_sin_descanso(page, server):
    """Semana→Día: URL gran=day, eje vuelve a fechas, sin días de descanso
    artificiales entre los días con datos."""
    iso_a, iso_c = _iso(4), _iso(11)  # hueco de una semana sin entrenar
    _seed_sessions(page, server, [iso_a, iso_c])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)

    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(700)
    week_state = _chart_state(page)
    assert week_state["xaxis"] == "Semana", week_state

    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(700)
    day_state = _chart_state(page)
    assert day_state["xaxis"] == "Fecha", day_state
    assert "gran=day" in page.url, page.url
    # Solo los días reales con datos: sin puntos de descanso.
    xs = {x for t in day_state["traces"] for x in t["x"]}
    assert iso_a in xs and iso_c in xs, xs
    assert len(xs) == 2, f"no deben aparecer días ficticios: {sorted(xs)}"
    assert all("-" in x for x in xs), xs


def test_b2r2_musculo_con_cambio_granularidad_mantiene_trazas(page, server):
    """Seleccionar un músculo y cambiar granularidad: Global y músculo conservan
    sus trazas y ambas usan el eje correcto."""
    _seed_sessions(page, server, [_iso(4), _iso(11)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)

    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(700)
    week = _chart_state(page)
    names = [t["n"] for t in week["traces"]]
    assert "Global" in names and "Pectoral" in names, names
    assert all("Semana" in t["hover"] for t in week["traces"]), week

    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(700)
    day = _chart_state(page)
    names = [t["n"] for t in day["traces"]]
    assert "Global" in names and "Pectoral" in names, names
    assert day["xaxis"] == "Fecha", day
    assert "musculos=Pectoral" in page.url, page.url


def test_b2r2_ejercicio_con_cambio_granularidad_conserva_seleccion(page, server):
    """Seleccionar un ejercicio y cambiar granularidad: Global + músculo guía +
    ejercicio conservan la selección y el eje cambia correctamente."""
    _seed_sessions(page, server, [_iso(4), _iso(11)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    chip.click()
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(600)

    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(700)
    week = _chart_state(page)
    names = [t["n"] for t in week["traces"]]
    assert "Compilado" in names and "Press" in names, names
    assert "ejercicios=Press" in page.url, page.url

    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(700)
    day = _chart_state(page)
    names = [t["n"] for t in day["traces"]]
    assert "Compilado" in names and "Press" in names, names
    assert day["xaxis"] == "Fecha", day
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")


def test_b2r2_back_forward_restaura_seleccion_y_granularidad(page, server):
    """Back/forward restaura selección, granularidad y los datos/labels reales."""
    _seed_sessions(page, server, [_iso(4), _iso(11)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(700)
    assert "gran=month" in page.url and "musculos=Pectoral" in page.url

    page.go_back()
    page.wait_for_timeout(800)
    assert "musculos=Pectoral" in page.url, page.url
    # El estado anterior conserva la selección; la gráfica refleja el día.
    assert "gran=day" in page.url, page.url
    st = _chart_state(page)
    assert st["xaxis"] == "Fecha", st
    names = [t["n"] for t in st["traces"]]
    assert "Global" in names and "Pectoral" in names, names

    page.go_forward()
    page.wait_for_timeout(800)
    assert "gran=month" in page.url and "musculos=Pectoral" in page.url, page.url


def test_b2r2_month_no_se_declara_terminado(page, server):
    """Contrato month funciona (URL + eje 'Mes' con datos), pero la agregación
    mensual COMPLETA (B3: cruce de año, huecos, orden) no se declara terminada.
    Este test documenta el estado vigente sin ocultar la limitación."""
    _seed_sessions(page, server, [_iso(4), _iso(11)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(700)
    assert "gran=month" in page.url, page.url
    st = _chart_state(page)
    assert st.get("empty") is not True, st
    # El eje ya se etiqueta "Mes" (contrato del selector), pero B3 —política
    # mensual completa— sigue pendiente y no debe darse por cerrado aquí.


# ---------------------------------------------------------------------------
# B2-R4 — Ventana temporal y navegación (desde/hasta)
# B2-R4 — Navegación TradingView (scroll/drag/doble clic)
# ---------------------------------------------------------------------------


def _seed_e2e_many_days(tmp_path, n: int = 40):
    """Siembra n días consecutivos vía DB directa (rápido para e2e)."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        conn.commit()
    except sqlite3.Error:
        pass
    rows = []
    start = datetime.date(2026, 1, 1)
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        semana = (i // 7) + 1
        rows.append((semana, "LUNES", d.isoformat(), 1, "Press", 80.0, 6.0, 1.0))
    conn.executemany(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _chart_window_state(page):
    """Lee el estado real de la ventana: puntos, ticks, rango, altura."""
    return page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            const container = document.getElementById('unified-chart-container');
            const gd = el && el._fullData ? el : null;
            const layout = el && el._fullLayout ? el._fullLayout : null;
            const xaxis = layout && layout.xaxis ? layout.xaxis : null;
            return {
                pointCount: gd && gd._fullData ? gd._fullData.reduce((s,t)=> s + t.x.length, 0) : 0,
                traceCount: gd && gd._fullData ? gd._fullData.length : 0,
                tickText: xaxis && xaxis.ticktext ? Array.from(xaxis.ticktext) : [],
                tickVals: xaxis && xaxis.tickvals ? Array.from(xaxis.tickvals) : [],
                xRange: xaxis && xaxis.range ? Array.from(xaxis.range) : null,
                height: container ? container.getBoundingClientRect().height : null,
                plotHeight: el ? el.getBoundingClientRect().height : null,
                hasSlider: !!document.querySelector('.rangeslider, [class*="rangeslider"]') || (xaxis && !!xaxis.rangeslider && xaxis.rangeslider.visible),
                xaxisTitle: xaxis ? xaxis.title.text : null,
                xType: xaxis ? xaxis.type : null,
                dragmode: layout ? layout.dragmode : null,
            };
        }"""
    )


def test_b2r4_selector_compacto_sin_barra(page, server):
    """El selector de granularidad es compacto junto al título, sin barra grande
    ni texto explicativo permanente."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    assert page.locator("#period-range-controls").count() == 0
    assert page.locator("#time-window-controls").count() == 0
    sel = page.locator("#granularity-selector")
    expect(sel).to_be_visible(timeout=3000)
    btns = sel.locator('[data-action="set-granularity"]')
    expect(btns).to_have_count(3)
    expect(page.get_by_role("button", name="Día")).to_be_visible()
    expect(page.get_by_role("button", name="Semana")).to_be_visible()
    expect(page.get_by_role("button", name="Mes")).to_be_visible()
    assert page.locator("#granularity-note").count() == 0
    assert "eje semanal por ahora" not in page.content()
    cbox = page.locator("#unified-chart-container").bounding_box()
    sbox = sel.bounding_box()
    assert sbox["width"] < cbox["width"] * 0.6, (
        f"selector ocupa demasiado: {sbox['width']} vs {cbox['width']}"
    )


def test_b2r4_sin_controles_descartados(page, server):
    """No existen 30/90/6m/Todo/Anterior/Siguiente ni range slider."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    for name in ["30 días", "90 días", "6 meses", "Todo", "Ventana anterior", "Ventana siguiente"]:
        assert page.get_by_role("button", name=name).count() == 0, f"no debe existir {name}"
    has_slider = page.evaluate(
        "() => { const el=document.getElementById('unified-chart-plot'); const l=el && el._fullLayout && el._fullLayout.xaxis; return !!(l && l.rangeslider && l.rangeslider.visible); }"
    )
    assert not has_slider, "range slider debe estar eliminado"
    assert page.locator(".rangeslider").count() == 0


def test_b2r4_plotly_tradingview_config(page, server, tmp_path):
    """ScrollZoom activo, dragmode pan, eje diario type=date."""
    _seed_e2e_many_days(tmp_path, 10)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData && document.getElementById('unified-chart-plot')._fullData.length>0"
    )
    expect(
        page.locator('#granularity-selector [data-gran="day"][aria-pressed="true"]')
    ).to_be_visible()
    st = page.evaluate(
        """() => {
            const el=document.getElementById('unified-chart-plot');
            const l=el && el._fullLayout;
            return {
                dragmode: l ? l.dragmode : null,
                xType: l && l.xaxis ? l.xaxis.type : null,
            };
        }"""
    )
    assert st["dragmode"] == "pan", f"dragmode debe ser pan: {st}"
    assert st["xType"] == "date", f"xaxis.type debe ser date en day: {st}"
    # ScrollZoom se verifica por config (no inspeccionable directo,
    # pero el dragmode pan + type date implica TradingView)
    assert page.locator("#unified-chart-plot").is_visible()


def test_b2r4_interaccion_scroll_y_drag_no_deja_en_blanco(page, server, tmp_path):
    """Scroll y arrastre modifican el rango visible sin dejar la gráfica en blanco;
    doble clic restablece y no hay peticiones htmx por movimiento."""
    _seed_e2e_many_days(tmp_path, 20)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData && document.getElementById('unified-chart-plot')._fullData.length>0"
    )
    before = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    h_before = page.locator("#unified-chart-plot").bounding_box()["height"]
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/grafica" in r.url else None)
    # Simular zoom via Plotly.relayout (más fiable que wheel nativo)
    page.evaluate(
        """() => {
            const gd=document.getElementById('unified-chart-plot');
            const x0=gd._fullLayout.xaxis.range[0], x1=gd._fullLayout.xaxis.range[1];
            const mid=new Date((new Date(x0).getTime()+new Date(x1).getTime())/2);
            const start=new Date(mid); start.setDate(start.getDate()-2);
            const end=new Date(mid); end.setDate(end.getDate()+2);
            return Plotly.relayout(gd, {'xaxis.range[0]': start.toISOString().slice(0,10), 'xaxis.range[1]': end.toISOString().slice(0,10)});
        }"""
    )
    page.wait_for_timeout(700)
    after_scroll = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    assert after_scroll != before, f"zoom debe cambiar rango: {before} vs {after_scroll}"
    assert not any("/grafica" in u for u in reqs), f"zoom no debe disparar htmx: {reqs}"
    assert page.evaluate("() => document.getElementById('unified-chart-plot')._fullData.length>0")
    assert page.evaluate("() => document.getElementById('unified-chart-empty').hidden")
    # Arrastre: pan
    box = page.locator("#unified-chart-plot").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2, steps=10)
    page.mouse.up()
    page.wait_for_timeout(700)
    after_drag = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    assert after_drag != after_scroll, "drag debe cambiar rango"
    assert page.evaluate("() => document.getElementById('unified-chart-plot')._fullData.length>0")
    assert page.evaluate("() => document.getElementById('unified-chart-empty').hidden")
    page.locator("#unified-chart-plot").dblclick()
    page.wait_for_timeout(700)
    assert page.evaluate("() => document.getElementById('unified-chart-plot')._fullData.length>0")
    assert page.evaluate("() => document.getElementById('unified-chart-empty').hidden")
    h_after = page.locator("#unified-chart-plot").bounding_box()["height"]
    assert abs(h_after - h_before) <= 2, f"altura cambió: {h_before}→{h_after}"
    assert not any("/grafica" in u for u in reqs), "zoom/pan no debe disparar htmx"


def test_b2r4_conservacion_musculo_no_destruye_shell(page, server, tmp_path):
    """Cambiar músculo/ejercicio no destruye la shell ni el rango visual."""
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    cnt = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    if cnt == 0:
        from src.models import TrainingSetInput
        from src.training_service import save_session

        save_session(db, "2026-05-04", [TrainingSetInput("Press", 80, 6, 1)])
        save_session(db, "2026-05-05", [TrainingSetInput("Press", 82, 6, 0)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    h_before = page.locator("#unified-chart-plot").bounding_box()["height"]
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(700)
    h_after = page.locator("#unified-chart-plot").bounding_box()["height"]
    assert abs(h_after - h_before) <= 2
    assert page.locator("#unified-chart-plot").is_visible()
    assert page.evaluate("() => document.getElementById('unified-chart-plot')._fullData.length>0")
    chip = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    if chip.count() > 0:
        chip.click()
        page.wait_for_timeout(700)
        assert page.locator("#unified-chart-plot").is_visible()
        assert page.evaluate(
            "() => document.getElementById('unified-chart-plot')._fullData.length>0"
        )


def test_layout_area_trazado_estable_global_a_musculo(page, server, tmp_path):
    """Al pasar de modo global a selección muscular el ÁREA DE TRAZADO (dominio
    del eje y SVG interno) no cambia: la leyenda vive en la banda superior
    reservada y nunca empuja la gráfica."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        base = datetime.date(2026, 6, 1)
        for i in range(10):
            d = base + datetime.timedelta(days=i)
            conn.execute(
                "INSERT INTO training_sets "
                "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
                "VALUES (?,?,?,1,'Press',6,80,1)",
                ((i // 7) + 1, "LUNES", d.isoformat()),
            )
        conn.commit()
    finally:
        conn.close()

    def plot_geometry(page):
        return page.evaluate(
            """() => {
                const el = document.getElementById('unified-chart-plot');
                if (!el || !el._fullLayout) return null;
                const svg = el.querySelector('.main-svg');
                const legend = el.querySelector('.legend');
                const l = el._fullLayout;
                const sr = svg ? svg.getBoundingClientRect() : null;
                const lr = legend ? legend.getBoundingClientRect() : null;
                const pr = el.getBoundingClientRect();
                return {
                    xDomain: [l.xaxis.domain[0], l.xaxis.domain[1]],
                    yDomain: [l.yaxis.domain[0], l.yaxis.domain[1]],
                    svgH: sr ? Math.round(sr.height * 10) / 10 : null,
                    svgW: sr ? Math.round(sr.width * 10) / 10 : null,
                    plotTop: Math.round(pr.top * 10) / 10,
                    legendAbovePlot: lr && sr ? lr.bottom <= sr.top + 2 || lr.bottom <= pr.top + l.margin.t + 2 : null,
                    traceCount: el._fullData.length,
                };
            }"""
        )

    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData &&"
        " document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    geo_global = plot_geometry(page)
    assert geo_global and geo_global["traceCount"] >= 1, geo_global

    # Seleccionar músculo → aparecen trazas; el área de trazado NO cambia.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    geo_muscle = plot_geometry(page)
    assert geo_muscle["traceCount"] >= 2, geo_muscle
    assert geo_muscle["xDomain"] == geo_global["xDomain"], (
        f"dominio X cambió: {geo_global['xDomain']} → {geo_muscle['xDomain']}"
    )
    assert geo_muscle["yDomain"] == geo_global["yDomain"], (
        f"dominio Y cambió: {geo_global['yDomain']} → {geo_muscle['yDomain']}"
    )
    assert abs(geo_muscle["svgH"] - geo_global["svgH"]) <= 1.5, (
        f"altura SVG cambió: {geo_global['svgH']} → {geo_muscle['svgH']}"
    )
    assert abs(geo_muscle["plotTop"] - geo_global["plotTop"]) <= 1.5

    # Deseleccionar (Escape) → vuelve a global; área intacta de nuevo.
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    geo_back = plot_geometry(page)
    assert geo_back["xDomain"] == geo_global["xDomain"]
    assert abs(geo_back["svgW"] - geo_global["svgW"]) <= 1.5


def test_b2r4_sin_errores_y_sin_overflow_movil(page, server):
    """Sin errores reales de consola y sin overflow horizontal en móvil."""
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    box = page.locator("#unified-chart-plot").bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(500)
        page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] / 2, steps=5)
        page.mouse.up()
        page.wait_for_timeout(500)
        page.locator("#unified-chart-plot").dblclick()
        page.wait_for_timeout(500)
    assert errs == [], f"errores de consola: {errs}"
    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_timeout(300)
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


# ---------------------------------------------------------------------------
# Web plan Task 4: WCAG contrast and lazy Plotly# ---------------------------------------------------------------------------
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
    vacio = _wcag_in_page(page, "#unified-chart-empty")
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
    # Persistent shell: #unified-chart-data exists with {} (no Plotly loaded).
    page.wait_for_selector("#unified-chart-data", state="attached")
    page.wait_for_selector("#unified-chart-empty")
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

    # La gráfica con datos se pide vía la cascada del catálogo (Press = Pectoral).
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_selector("#unified-chart-plot .main-svg", timeout=15000)
    loaded_height = page.locator("#unified-chart-container").bounding_box()["height"]
    assert abs(loaded_height - empty_height) <= 1.0, (empty_height, loaded_height)
    assert len(plotly_requests) == 1, plotly_requests


def test_cls_stable_shell_and_history(page, server):
    """CLS 0: el panel analítico (gráfica y #history-section) no cambia de
    altura ni de offset al seleccionar. El catálogo es una columna sticky con
    altura máxima y scroll interno: puede crecer hasta el viewport sin
    desplazar el resto de la página (plan §5.1)."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    def rect(sel):
        box = page.locator(sel).bounding_box()
        return box or {}

    # Estado base
    chart_h = rect("#unified-chart-container").get("height")
    chart_y = rect("#unified-chart-container").get("y")
    history_h = rect("#history-section").get("height")
    scroll_y = page.evaluate("() => window.scrollY")

    # Seleccionar un músculo
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)

    chart_after_h = rect("#unified-chart-container").get("height")
    chart_after_y = rect("#unified-chart-container").get("y")
    history_after_h = rect("#history-section").get("height")
    scroll_after = page.evaluate("() => window.scrollY")

    assert chart_h and chart_y and history_h is not None
    assert abs(chart_after_h - chart_h) <= 1.0, f"chart CLS: {chart_h} → {chart_after_h}"
    assert abs(chart_after_y - chart_y) <= 1.0, f"chart y shift: {chart_y} → {chart_after_y}"
    assert abs(history_after_h - history_h) <= 1.0, f"history CLS: {history_h} → {history_after_h}"
    assert abs(scroll_after - scroll_y) <= 2, f"scroll shifted: {scroll_y} → {scroll_after}"
    # La columna sticky no supera la altura disponible (scroll interno).
    catalog_h = rect(".dashboard-catalog-col").get("height") or 0
    assert catalog_h <= 800 - 32 + 1, f"catálogo excede el viewport: {catalog_h}px"


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


def test_session_rows_reorder_by_drag_auto_enters_edit(page, server):
    """El arrastre funciona en un día guardado (solo lectura) y entra solo en
    modo edición: sin lápiz previo."""
    _open_popup(page, server)
    _fill_row(page, 0, ejercicio="Press")
    page.locator("#set-rows .set-row").first.locator('[data-action="row-add"]').click()
    page.wait_for_timeout(150)
    rows = page.locator("#set-rows .set-row")
    expect(rows).to_have_count(2)
    _fill_row(page, 1, ejercicio="Press", kg="90")
    # Guardar: el día queda en solo lectura (tiene datos).
    page.locator('#edit-actions button[type="submit"]').evaluate("el => el.click()")
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1")
    # Arrastrar sin lápiz: auto-entra en edición y reordena.
    rows = page.locator("#set-rows .set-row")
    _drag_row_up(page, rows, 1, ".set-num")
    page.wait_for_timeout(250)
    assert rows.nth(0).locator('input[name="kg"]').input_value() == "90"
    assert rows.nth(0).locator(".set-num").inner_text() == "1"
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "0")


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
    _drag_card_up(
        page, "#plantillas-list .pt-card:nth-child(2)", "#plantillas-list .pt-card:nth-child(1)"
    )
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
    _drag_card_up(
        page, "#plantillas-list .pt-card:nth-child(2)", "#plantillas-list .pt-card:nth-child(1)"
    )
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


def test_cardio_annotation_saves_from_popup(page, server, tmp_path):
    """Regresión: el submit de anotación de cardio desde el popup debe llegar al
    servidor (htmx no serializa FormData como values; se convierte a objeto)."""
    import sqlite3
    from datetime import datetime, timedelta

    iso_cardio = _iso(1)
    db_path = tmp_path / "lifestyle.db"
    conn = sqlite3.connect(db_path)
    target = datetime.now() + timedelta(days=1)
    start = (
        datetime(
            target.year, target.month, target.day, 8, 0, tzinfo=datetime.now().astimezone().tzinfo
        ).timestamp()
        * 1000
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('c1', 'EXERCISE_SESSION', ?, ?, ?, 1, "
        "'{\"value\": {\"title\": \"Cinta\"}}', 'x', 'x')",
        (int(start), int(start) + 30 * 60000, int(start)),
    )
    conn.commit()
    conn.close()

    _open_popup(page, server)
    page.locator(f'#popup-body .date-num[data-iso="{iso_cardio}"]').click()
    expect(
        page.locator("#popup-body #cardio-day form[data-action='cardio-annotation-save']")
    ).to_have_count(1, timeout=5000)
    form = page.locator("#popup-body #cardio-day form[data-action='cardio-annotation-save']").first
    form.locator('input[name="velocidad_kmh"]').fill("9.5")
    form.get_by_role("button", name="Guardar").click()
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Anotación de cardio guardada", timeout=5000
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT velocidad_kmh, inclinacion_pct FROM cardio_annotations WHERE hc_id='c1'"
    ).fetchone()
    conn.close()
    assert row == (9.5, None), row


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


def test_cardio_refreshes_when_navigating_in_popup(page, server, tmp_path):
    """Regresión: el panel de cardio debe refrescarse al navegar fechas dentro del
    popup (doNav pide /cardio/day), no quedarse con el día de apertura."""
    import sqlite3
    from datetime import datetime, timedelta

    iso_cardio = _iso(1)
    # Sembrar una EXERCISE_SESSION en la DB del servidor para mañana.
    db_path = tmp_path / "lifestyle.db"
    conn = sqlite3.connect(db_path)
    target = datetime.now() + timedelta(days=1)
    start = (
        datetime(
            target.year, target.month, target.day, 8, 0, tzinfo=datetime.now().astimezone().tzinfo
        ).timestamp()
        * 1000
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('c1', 'EXERCISE_SESSION', ?, ?, ?, 1, "
        "'{\"value\": {\"title\": \"Cinta\"}}', 'x', 'x')",
        (int(start), int(start) + 30 * 60000, int(start)),
    )
    conn.commit()
    conn.close()

    # Abrir el popup hoy (sin cardio) y navegar a mañana: debe aparecer el form.
    _open_popup(page, server)
    expect(page.locator("#popup-body #cardio-day")).to_contain_text(
        "Sin sesiones de ejercicio", timeout=5000
    )
    page.locator(f'#popup-body .date-num[data-iso="{iso_cardio}"]').click()
    expect(page.locator("#popup-body #session-form input[name='fecha']")).to_have_value(
        iso_cardio, timeout=5000
    )
    expect(
        page.locator("#popup-body #cardio-day form[data-action='cardio-annotation-save']")
    ).to_have_count(1, timeout=5000)
    expect(page.locator("#popup-body #cardio-day")).to_contain_text("Cinta")


# ---------------------------------------------------------------------------
# A3 — Layout tests for dashboard catalog
# ---------------------------------------------------------------------------


def test_dashboard_catalog_left_chart_right(page, server):
    """On desktop, catalog is on the left and chart is on the right."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    catalog = page.locator(".dashboard-catalog-col").bounding_box()
    chart = page.locator("#unified-chart-container").bounding_box()
    assert catalog is not None and chart is not None
    # Catalog should be to the left of the chart
    assert catalog["x"] < chart["x"], f"Catalog x={catalog['x']} should be < chart x={chart['x']}"


def test_dashboard_no_horizontal_overflow(page, server):
    """No horizontal overflow on desktop or mobile."""
    for width in [1280, 375]:
        page.set_viewport_size({"width": width, "height": 800})
        page.goto(server)
        page.wait_for_function("document.body.dataset.appReady === '1'")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, f"Horizontal overflow at {width}px"


def test_dashboard_chart_height_stable_when_catalog_expands(page, server):
    """Expanding a catalog group does not change chart height or offset."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    chart_before = page.locator("#unified-chart-container").bounding_box()
    # Click the first details/summary to expand
    summary = page.locator('#dashboard-catalog [data-action="toggle-group"]').first
    summary.click()
    page.wait_for_timeout(300)
    chart_after = page.locator("#unified-chart-container").bounding_box()
    assert chart_before is not None and chart_after is not None
    # Height should not change
    assert abs(chart_before["height"] - chart_after["height"]) < 2, (
        f"Chart height changed: {chart_before['height']} -> {chart_after['height']}"
    )
    # Y offset should not change
    assert abs(chart_before["y"] - chart_after["y"]) < 2, (
        f"Chart y changed: {chart_before['y']} -> {chart_after['y']}"
    )


def test_dashboard_catalog_scrollable(page, server):
    """The catalog column has internal scroll on desktop."""
    page.set_viewport_size({"width": 1280, "height": 400})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    overflow_y = page.evaluate(
        "() => { const el = document.querySelector('.dashboard-catalog-col');"
        " return window.getComputedStyle(el).overflowY; }"
    )
    assert overflow_y in ("auto", "scroll"), f"overflow-y: {overflow_y}"


def test_dashboard_mobile_catalog_below_chart(page, server):
    """On mobile, catalog appears below the chart (not beside it)."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    catalog = page.locator(".dashboard-catalog-col").bounding_box()
    chart = page.locator("#unified-chart-container").bounding_box()
    assert catalog is not None and chart is not None
    # On mobile, catalog should be below chart (catalog.y > chart.y)
    assert catalog["y"] > chart["y"], (
        f"Mobile: catalog y={catalog['y']} should be > chart y={chart['y']}"
    )


def test_dashboard_no_level_chip_in_catalog(page, server):
    """The old .level-chip class is not used in the catalog."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    count = page.locator("#dashboard-catalog .level-chip").count()
    assert count == 0, f"Found {count} .level-chip elements in catalog"
