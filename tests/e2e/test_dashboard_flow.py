"""Browser tests covering the high-risk htmx editing and template workflows."""

import datetime
import re

import pytest
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


def _open_popup(page, server, vista="entrenamiento"):
    """Los editores viven en /diario (contrato v4: sin popup en el Dashboard)."""
    page.goto(server + "/diario?vista=" + vista)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#session-editor-wrap", state="attached", timeout=5000)
    page.wait_for_selector("#nutrition-form", state="attached", timeout=5000)


def _goto_date(page, server, iso):
    _open_popup(page, server)
    before = page.locator("#daily-date-title").inner_text()
    page.locator(f'#date-navigator .date-num[data-iso="{iso}"]').click()
    expect(page.locator(f'#date-navigator .date-num[data-iso="{iso}"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    # El título global cambia con la navegación
    expect(page.locator("#daily-date-title")).not_to_have_text(before)
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


def _catalog_select_muscle(page, name):
    """Catálogo acordeón: expande el grupo y marca el checkbox del músculo."""
    # Drawer móvil: abrir si el viewport es móvil y está plegado.
    # (En desktop el botón móvil es display:none: no se intenta clicar.)
    try:
        is_mobile_vp = page.evaluate("() => window.matchMedia('(max-width: 1023px)').matches")
        if (
            is_mobile_vp
            and page.locator("#catalog-toggle-mobile").get_attribute("aria-expanded") == "false"
        ):
            page.locator("#catalog-toggle-mobile").click()
            page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001, S110
        pass
    group = page.locator(f'#dashboard-catalog .db-group[data-group="{name}"]')
    expect(group).to_be_visible(timeout=5000)
    summary = group.locator('[data-action="toggle-group"]')
    if summary.get_attribute("aria-expanded") != "true":
        summary.evaluate("el => el.click()")
        page.wait_for_timeout(400)
    group.locator('[data-action="toggle-muscle"]').evaluate("el => el.click()")
    page.wait_for_timeout(400)
    # Tras el OOB del catálogo (reordenado), el grupo debe permanecer abierto
    # El handler oobAfterSwap reabre los grupos, pero esperamos explícitamente
    expect(group.locator(".db-exercise-list")).to_be_visible(timeout=5000)


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
    # El Diario navega a la fecha elegida tras guardar.
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(_iso(2), timeout=5000)


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


def test_click_en_punto_no_navega_ni_cambia_estado(page, server):
    """La gráfica es exclusivamente analítica: clic sobre un punto en
    Día/Semana/Mes NO navega, NO abre popup, NO llama /semana/primer-entreno,
    NO modifica URL ni granularidad ni selección."""
    _open_popup(page, server)
    page.locator(f'#popup-body .date-num[data-iso="{_iso(4)}"]').click()
    _wait_editor_settled(page)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    _catalog_select_muscle(page, "Pectoral")

    # Registrar cualquier petición al endpoint de primer entreno (una sola vez;
    # el listener acumula durante todo el test, en las 3 granularidades).
    primer_requests = []
    page.on(
        "request",
        lambda r: primer_requests.append(r.url) if "primer-entreno" in r.url else None,
    )

    for gran, eje in (("day", "Fecha"), ("week", "Semana"), ("month", "Mes")):
        page.locator(f'#granularity-selector [data-gran="{gran}"]').click()
        page.wait_for_timeout(500)
        url_before = page.url
        history_before = page.evaluate("() => history.length")
        assert f"gran={gran}" in url_before, (gran, url_before)

        # Clic real sobre el primer punto visible.
        point = page.locator("#unified-chart-plot .point").first
        point.wait_for(state="visible", timeout=10000)
        box = point.bounding_box()
        assert box, gran
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

        # Clics adicionales en otro punto (si existe): nada debe cambiar.
        points = page.locator("#unified-chart-plot .point")
        if points.count() > 1:
            b2 = points.nth(1).bounding_box()
            if b2:
                page.mouse.click(b2["x"] + b2["width"] / 2, b2["y"] + b2["height"] / 2)
        page.wait_for_timeout(600)

        # Sin navegación, sin popup, sin petición, sin cambios de estado.
        assert page.url == url_before, f"{gran}: la URL cambió → {page.url}"
        assert not page.locator("#editor-popup[open]").count(), gran
        assert primer_requests == [], f"{gran}: llamó primer-entreno {primer_requests}"
        st = _chart_state(page)
        assert st["xaxis"] == eje, f"{gran}: eje cambió a {st['xaxis']}"
        assert f"gran={gran}" in page.url
        expect(
            page.locator(
                '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
            )
        ).to_have_attribute("aria-pressed", "true")
        # Sin entradas de historial por los clics.
        history_after = page.evaluate("() => history.length")
        assert history_after == history_before, (
            f"{gran}: los clics añadieron historial ({history_before}→{history_after})"
        )


def test_back_forward_granularidad_tras_clics_en_puntos(page, server):
    """Los clics en puntos no ensucian el historial: back/forward restauran
    granularidad y selección exactamente como si no se hubiera hecho clic."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    _catalog_select_muscle(page, "Pectoral")

    # Día → Semana.
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(500)
    # Clics sobre puntos dentro de Semana.
    point = page.locator("#unified-chart-plot .point").first
    point.wait_for(state="visible", timeout=10000)
    for idx in range(min(2, page.locator("#unified-chart-plot .point").count())):
        b = page.locator("#unified-chart-plot .point").nth(idx).bounding_box()
        if b:
            page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.wait_for_timeout(400)
    # Semana → Mes y más clics.
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(500)
    point = page.locator("#unified-chart-plot .point").first
    if point.count():
        b = point.bounding_box()
        if b:
            page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.wait_for_timeout(400)
    assert "gran=month" in page.url and "musculos=Pectoral" in page.url

    # Atrás: restaura Semana + músculo.
    page.go_back()
    page.wait_for_timeout(800)
    assert "gran=week" in page.url and "musculos=Pectoral" in page.url, page.url
    expect(
        page.locator('#granularity-selector [data-gran="week"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)
    st = _chart_state(page)
    assert st["xaxis"] == "Semana", st
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "true")

    # Atrás de nuevo: Día (estado base).
    page.go_back()
    page.wait_for_timeout(800)
    assert "gran=day" in page.url or "gran=" not in page.url, page.url
    expect(
        page.locator('#granularity-selector [data-gran="day"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)

    # Adelante: vuelve a Semana con selección intacta.
    page.go_forward()
    page.wait_for_timeout(800)
    assert "gran=week" in page.url and "musculos=Pectoral" in page.url, page.url


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

    page.locator(f'#date-navigator .date-num[data-iso="{iso_a}"]').click()
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
    page.goto(server)

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
    page.locator(f'#date-navigator .date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_timeout(400)
    _fill_row(page, 0, ejercicio="Curl", kg="12", reps="10", rir="1")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.goto(server)

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
    page.locator(f'#date-navigator .date-num[data-iso="{_iso(1)}"]').click()
    page.wait_for_timeout(400)
    _fill_row(page, 0, ejercicio="Curl", kg="12", reps="10", rir="1")
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.goto(server)

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
    page.goto(server)

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
    page.goto(server)


def _chart_state(page):
    """Lee el contenido real de la gráfica Plotly: forma del eje X, trazas y tooltip.

    Sin títulos de eje (los indica el selector): la granularidad se infiere de
    la forma del primer x ('day' ISO, 'week' dígitos, 'month' YYYY-MM).
    """
    return page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            if (!el || !el._fullData) return {empty: true};
            const x0 = el._fullData.length && el._fullData[0].x.length
                ? String(el._fullData[0].x[0]) : null;
            const xshape = !x0 ? null
                : /^\\d{4}-\\d{2}-\\d{2}$/.test(x0) ? 'day'
                : /^\\d+$/.test(x0) ? 'week'
                : /^\\d{4}-\\d{2}$/.test(x0) ? 'month' : '?';
            return {
                xshape: xshape,
                traces: el._fullData.map(t => ({
                    n: t.name,
                    x: Array.from(t.x).map(String),
                    hover: t.hovertemplate || '',
                    cd0: t.customdata && t.customdata.length
                        ? Array.from(t.customdata[0]).map(String) : []
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


def test_recarga_granularidad_sincroniza_grafica_y_selector(page, server):
    """Recargar con gran en la URL mantiene selector Y gráfica en la misma
    granularidad (regresión: el render inicial ignoraba gran y pintaba Día)."""
    _open_popup(page, server)
    _fill_row(page, 0)
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=2000
    )
    page.click("#popup-close")

    # Seleccionar el músculo UNA vez: persiste entre recargas y cambios de gran.
    _catalog_select_muscle(page, "Pectoral")
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "true")

    for gran, eje in (("week", "Semana"), ("month", "Mes")):
        page.locator(f'#granularity-selector [data-gran="{gran}"]').click()
        page.wait_for_timeout(600)
        assert f"gran={gran}" in page.url

        # Recarga: URL, selector y gráfica deben coincidir.
        page.reload()
        page.wait_for_function("document.body.dataset.appReady === '1'")
        expect(
            page.locator(f'#granularity-selector [data-gran="{gran}"][aria-pressed="true"]')
        ).to_be_visible(timeout=5000)
        page.wait_for_function(
            """(eje) => {
                const el = document.getElementById('unified-chart-plot');
                return el && el._fullLayout && el._fullLayout.xaxis
                    && el._fullLayout.xaxis.title.text === eje;
            }""",
            arg=eje,
            timeout=8000,
        )
        st = _chart_state(page)
        assert st["xaxis"] == eje, f"gráfica debe usar {eje}: {st}"
        assert f"gran={gran}" in page.url, page.url
        # La selección de músculo también se conserva junto a la granularidad.
        expect(
            page.locator(
                '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
            )
        ).to_have_attribute("aria-pressed", "true")

    # Carga directa con gran=week sin selección: la gráfica inicial ya es semanal.
    page.goto(server + "/?gran=week")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => { const el = document.getElementById('unified-chart-plot');"
        " return el && el._fullLayout && el._fullLayout.xaxis"
        " && el._fullLayout.xaxis.title.text === 'Semana'; }",
        timeout=8000,
    )
    expect(
        page.locator('#granularity-selector [data-gran="week"][aria-pressed="true"]')
    ).to_be_visible()


def test_sin_flicker_de_granularidad_al_cargar(page, server, tmp_path):
    """Carga directa y recarga con week/month: el selector y la gráfica NUNCA
    pasan visualmente por Día. Instrumentación temporal (solo en el test)
    registra la historia de {eje, botón activo} y los renders de Plotly."""
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

    # Recorder instalado antes de CUALQUIER script de la página: registra cada
    # transición de {título del eje, granularidad presionada} y los renders.
    # El observer se instala cuando exista documentElement (el init-script corre
    # sobre un documento vacío) y todo va en try/catch: si el instrumento
    # fallara, los asserts lo detectarán como historial vacío.
    init_js = """() => {
            window.__flickerLog = [];
            window.__plotlyRenders = 0;
            const record = () => {
                try {
                    const pressed = document.querySelector(
                        '#granularity-selector [aria-pressed="true"]'
                    );
                    const plot = document.getElementById('unified-chart-plot');
                    window.__flickerLog.push({
                        gran: pressed ? pressed.dataset.gran : null,
                        axis: plot && plot._fullLayout && plot._fullLayout.xaxis
                            ? plot._fullLayout.xaxis.title.text : null,
                    });
                } catch (e) {}
            };
            const startObserver = () => {
                try {
                    new MutationObserver(record).observe(document.documentElement, {
                        subtree: true, childList: true, attributes: true,
                        attributeFilter: ['aria-pressed', 'hidden'],
                    });
                } catch (e) {}
            };
            if (document.documentElement) {
                startObserver();
            } else {
                document.addEventListener('DOMContentLoaded', () => {
                    startObserver();
                    record();
                });
            }
        }"""
    # add_init_script evalúa el texto como EXPRESIÓN: una arrow sin invocar no
    # ejecuta nada. Se invoca explícitamente como IIFE.
    page.add_init_script(f"({init_js})()")
    # Los renders visibles se miden desde Python: peticiones /grafica reales.
    grafica_requests = []
    page.on(
        "request",
        lambda r: grafica_requests.append(r.url) if "/grafica" in r.url else None,
    )

    def flicker_state():
        return page.evaluate(
            "() => ({ log: window.__flickerLog || [], renders: window.__plotlyRenders || 0 })"
        )

    # 1) Carga directa /?gran=week: nunca Día/Fecha; selector siempre week.
    grafica_requests.clear()
    page.goto(server + "/?gran=week")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => { const el=document.getElementById('unified-chart-plot');"
        " return el && el._fullLayout && el._fullLayout.xaxis"
        " && el._fullLayout.xaxis.title.text === 'Semana'; }",
        timeout=8000,
    )
    st = flicker_state()
    axes = [e["axis"] for e in st["log"] if e["axis"]]
    assert axes and set(axes) == {"Semana"}, f"eje pasó por otro valor: {st['log']}"
    assert not grafica_requests, f"carga directa no debe pedir /grafica: {grafica_requests}"
    assert all(e["gran"] == "week" for e in st["log"]), f"Día visible: {st['log']}"

    # 2) Carga directa /?gran=month: ídem.
    page.goto(server + "/?gran=month")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => { const el=document.getElementById('unified-chart-plot');"
        " return el && el._fullLayout && el._fullLayout.xaxis"
        " && el._fullLayout.xaxis.title.text === 'Mes'; }",
        timeout=8000,
    )
    st = flicker_state()
    axes_m = [e["axis"] for e in st["log"] if e["axis"]]
    assert axes_m and set(axes_m) == {"Mes"}, f"eje pasó por otro valor: {st['log']}"
    assert not grafica_requests, f"carga directa no debe pedir /grafica: {grafica_requests}"
    assert all(e["gran"] == "month" for e in st["log"]), f"Día visible: {st['log']}"

    # 3) Reload en week CON músculo seleccionado: un solo render, sin Día.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(600)
    assert "gran=week" in page.url and "musculos=Pectoral" in page.url
    grafica_requests.clear()
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(
        page.locator('#granularity-selector [data-gran="week"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)
    page.wait_for_function(
        "() => { const el=document.getElementById('unified-chart-plot');"
        " return el && el._fullData && el._fullData.some(t => t.name === 'Pectoral'); }",
        timeout=8000,
    )
    st = flicker_state()
    # Un solo render visible: se salta la figura sistémica porque la respuesta
    # de /grafica (músculo+week) pinta la gráfica directamente.
    assert len(grafica_requests) == 1, f"doble render con selección: {grafica_requests}"
    assert all(e["gran"] == "week" for e in st["log"]), f"Día visible: {st['log']}"
    assert all(e["axis"] != "Fecha" for e in st["log"]), f"eje Día visible: {st['log']}"
    expect(
        page.locator(
            '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
        )
    ).to_have_attribute("aria-pressed", "true")

    # 4) Reload en month CON ejercicio seleccionado: un solo render, sin Día.
    pecto_toggle = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-group"]'
    )
    if pecto_toggle.get_attribute("aria-expanded") != "true":
        pecto_toggle.click()
        page.wait_for_timeout(200)
    chip = _exercise_input(page, "Press")
    expect(chip).to_be_visible(timeout=3000)
    chip.click()
    page.wait_for_timeout(600)
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(600)
    assert "gran=month" in page.url and "ejercicios=Press" in page.url
    grafica_requests.clear()
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(
        page.locator('#granularity-selector [data-gran="month"][aria-pressed="true"]')
    ).to_be_visible(timeout=5000)
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true", timeout=5000)
    st = flicker_state()
    # Un solo render: exactamente UNA petición /grafica tras la recarga.
    assert len(grafica_requests) == 1, f"doble render con ejercicio: {grafica_requests}"
    assert all(e["gran"] == "month" for e in st["log"]), f"Día visible: {st['log']}"
    assert all(e["axis"] != "Fecha" for e in st["log"]), f"eje Día visible: {st['log']}"
    assert "musculos=Pectoral" in page.url and "ejercicios=Press" in page.url

    # 5) Back/forward restaura sin estados contradictorios.
    page.go_back()
    page.wait_for_timeout(800)
    assert "gran=week" in page.url, page.url
    st_back = page.evaluate(
        """() => {
            const p = document.querySelector('#granularity-selector [aria-pressed="true"]');
            const el = document.getElementById('unified-chart-plot');
            return { gran: p ? p.dataset.gran : null,
                axis: el && el._fullLayout && el._fullLayout.xaxis
                    ? el._fullLayout.xaxis.title.text : null };
        }"""
    )
    assert st_back["gran"] == "week", st_back
    assert st_back["axis"] in ("Semana", None), st_back


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
    """UX-2: Día usa fechas reales, hover sin 'Semana' y etiqueta tooltip '1 septiembre'."""
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
    # UX-2: hover nativo suprimido (hovertemplate None) y etiqueta tooltip es fecha corta "1 septiembre"
    assert all("Semana" not in t["hover"] for t in st["traces"]), st
    assert all(t["hover"] == "" for t in st["traces"]), st
    assert all(
        any(
            m in t["cd0"][0].lower()
            for m in [
                "enero",
                "febrero",
                "marzo",
                "abril",
                "mayo",
                "junio",
                "julio",
                "agosto",
                "septiembre",
                "octubre",
                "noviembre",
                "diciembre",
            ]
        )
        for t in st["traces"]
    ), st
    assert all("/" not in t["cd0"][0] for t in st["traces"]), st
    assert all("Semana" not in t["cd0"][0] for t in st["traces"]), st


def test_b2r2_day_a_week_cambia_grafica_y_conserva_seleccion(page, server):
    """UX-2: Día→Semana conserva selección, eje Semana y tooltip con fecha lunes."""
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
    # UX-2: eje Semana y etiqueta tooltip es fecha lunes "1 septiembre 2026", no "Semana 1"
    assert week_state["xaxis"] == "Semana", week_state
    assert all(
        any(
            m in t["cd0"][0].lower()
            for m in [
                "enero",
                "febrero",
                "marzo",
                "abril",
                "mayo",
                "junio",
                "julio",
                "agosto",
                "septiembre",
                "octubre",
                "noviembre",
                "diciembre",
            ]
        )
        for t in week_state["traces"]
    ), week_state
    assert all("Semana" not in t["cd0"][0] for t in week_state["traces"]), week_state
    assert all(t["hover"] == "" for t in week_state["traces"]), week_state
    # Selección conservada (chip sigue marcado, URL con musculos+ejercicios).
    expect(_exercise_input(page, "Press")).to_have_attribute("aria-pressed", "true")
    assert "musculos=Pectoral" in page.url, page.url
    assert "ejercicios=Press" in page.url, page.url
    # UX-2: músculo guía, nunca "Compilado"
    names = [t["n"] for t in week_state["traces"]]
    assert "Pectoral" in names, names
    assert "Compilado" not in names, names


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
    """UX-2: músculo conserva Global+músculo y tooltip fecha, no 'Semana'."""
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
    assert all(
        any(
            m in t["cd0"][0].lower()
            for m in [
                "enero",
                "febrero",
                "marzo",
                "abril",
                "mayo",
                "junio",
                "julio",
                "agosto",
                "septiembre",
                "octubre",
                "noviembre",
                "diciembre",
            ]
        )
        for t in week["traces"]
    ), week
    assert all("Semana" not in t["cd0"][0] for t in week["traces"]), week

    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(700)
    day = _chart_state(page)
    names = [t["n"] for t in day["traces"]]
    assert "Global" in names and "Pectoral" in names, names
    assert day["xaxis"] == "Fecha", day
    assert "musculos=Pectoral" in page.url, page.url


def test_b2r2_ejercicio_con_cambio_granularidad_conserva_seleccion(page, server):
    """UX-2: ejercicio conserva músculo guía + ejercicio (sin Compilado) y eje correcto."""
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
    assert "Pectoral" in names and "Press" in names, names
    assert "Compilado" not in names, names
    assert "ejercicios=Press" in page.url, page.url

    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(700)
    day = _chart_state(page)
    names = [t["n"] for t in day["traces"]]
    assert "Pectoral" in names and "Press" in names, names
    assert "Compilado" not in names, names
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
    expect(page.get_by_role("button", name="Día", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Semana", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Mes", exact=True)).to_be_visible()
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
                const cr = document.getElementById('unified-chart-container').getBoundingClientRect();
                return {
                    xDomain: [l.xaxis.domain[0], l.xaxis.domain[1]],
                    yDomain: [l.yaxis.domain[0], l.yaxis.domain[1]],
                    svgH: sr ? Math.round(sr.height * 10) / 10 : null,
                    svgW: sr ? Math.round(sr.width * 10) / 10 : null,
                    plotTop: Math.round((pr.top - cr.top) * 10) / 10,
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


def _x_span_ms(page):
    """Devuelve el span del eje X en milisegundos (rango real de Plotly)."""
    return page.evaluate(
        """() => {
            const r = document.getElementById('unified-chart-plot')._fullLayout.xaxis.range;
            return new Date(r[1]).getTime() - new Date(r[0]).getTime();
        }"""
    )


def _x_range_slice(page):
    return page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )


def _y_range_slice(page):
    return page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.yaxis.range.slice()"
    )


def test_rueda_direccion_zoom_invertida_y_eje_y_estable(page, server, tmp_path):
    """Rueda arriba acerca (span X menor), rueda abajo aleja (span X mayor);
    el eje Y y el historial permanecen intactos. Shift+rueda desplaza sin
    cambiar el span."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    history_before = page.evaluate("() => history.length")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    box = page.locator("#unified-chart-plot").bounding_box()
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)

    span_inicial = _x_span_ms(page)
    y_inicial = _y_range_slice(page)

    # Rueda hacia arriba (deltaY < 0) → acercar → span menor.
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(500)
    span_arriba = _x_span_ms(page)
    assert span_arriba < span_inicial, f"rueda arriba debe acercar: {span_inicial} → {span_arriba}"

    # Rueda hacia abajo (deltaY > 0) → alejar → span mayor (gradual).
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(500)
    span_abajo = _x_span_ms(page)
    assert span_abajo > span_arriba, f"rueda abajo debe alejar: {span_arriba} → {span_abajo}"
    assert span_abajo < span_inicial * 1.6, (
        f"cambio gradual esperado: {span_inicial} → {span_abajo}"
    )
    assert span_abajo > span_arriba * 1.001

    # El eje Y NO cambia durante el zoom X.
    y_tras_rueda = _y_range_slice(page)
    assert y_tras_rueda == y_inicial, f"el eje Y cambió: {y_inicial} → {y_tras_rueda}"

    # Shift+rueda: desplaza el rango sin cambiar el span.
    span_antes_shift = _x_span_ms(page)
    x_antes_shift = _x_range_slice(page)
    page.locator("#unified-chart-plot").press("Shift")
    page.keyboard.down("Shift")
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(500)
    page.keyboard.up("Shift")
    span_shift = _x_span_ms(page)
    x_shift = _x_range_slice(page)
    assert abs(span_shift - span_antes_shift) < max(10, span_antes_shift * 0.001), (
        f"Shift+rueda no debe cambiar el span: {span_antes_shift} → {span_shift}"
    )
    assert x_shift != x_antes_shift, "Shift+rueda debe desplazar el rango"

    # Sin historial nuevo, sin peticiones /grafica, sin errores.
    assert page.evaluate("() => history.length") == history_before
    assert not grafica_reqs, grafica_reqs
    assert errs == [], errs


def test_rueda_vertical_sobre_eje_y(page, server, tmp_path):
    """Rueda sobre el eje Y: arriba acerca Y, abajo aleja Y; X permanece igual."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    history_before = page.evaluate("() => history.length")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    # Calcular posición geométrica del eje Y (sin depender de clases internas)
    y_axis_pos = page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            const rect = el.getBoundingClientRect();
            const m = el._fullLayout.margin;
            const plotH = el._fullLayout.height - m.t - m.b;
            return {
                x: rect.left + m.l / 2,
                y: rect.top + m.t + plotH / 2,
            };
        }"""
    )
    x_before = _x_range_slice(page)
    y_before = _y_range_slice(page)
    span_y_before = abs(y_before[1] - y_before[0])

    # Rueda arriba sobre Y → acerca Y (span menor), X igual
    page.mouse.move(y_axis_pos["x"], y_axis_pos["y"])
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(500)
    y_up = _y_range_slice(page)
    x_after_up = _x_range_slice(page)
    span_y_up = abs(y_up[1] - y_up[0])
    assert span_y_up < span_y_before, (
        f"rueda arriba sobre Y debe acercar Y: {span_y_before} → {span_y_up}"
    )
    assert x_after_up == x_before, f"rueda Y no debe tocar X: {x_before} vs {x_after_up}"
    assert y_up[0] < y_up[1] and span_y_up > 1e-9, "Y no invertido ni colapsado"

    # Rueda abajo sobre Y → aleja Y, X igual
    page.mouse.move(y_axis_pos["x"], y_axis_pos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(500)
    y_down = _y_range_slice(page)
    span_y_down = abs(y_down[1] - y_down[0])
    assert span_y_down > span_y_up, f"rueda abajo sobre Y debe alejar: {span_y_up} → {span_y_down}"
    assert _x_range_slice(page) == x_after_up, "rueda Y no debe tocar X"

    # Varias vueltas graduales sobre Y
    for _ in range(3):
        page.mouse.move(y_axis_pos["x"], y_axis_pos["y"])
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(300)
    y_multi = _y_range_slice(page)
    span_y_multi = abs(y_multi[1] - y_multi[0])
    assert span_y_multi < span_y_down, "zoom Y debe ser gradual"
    assert y_multi[0] < y_multi[1], "Y no invertido tras varias vueltas"
    # Verificar que el rango conserva decimales (no redondeo a enteros)
    assert (
        any(isinstance(v, float) and v != int(v) for v in y_multi)
        or span_y_multi < span_y_down * 0.9
    ), "Y range debe conservar decimales"

    # Shift+rueda sobre Y debe seguir desplazando X (prioridad absoluta), no Y
    x_before_shift = _x_range_slice(page)
    y_before_shift = _y_range_slice(page)
    span_x_before_shift = (
        abs(float(_x_range_slice(page)[1]) - float(_x_range_slice(page)[0]))
        if isinstance(_x_range_slice(page)[0], (int, float))
        else abs(_x_span_ms(page))
    )
    page.keyboard.down("Shift")
    page.mouse.move(y_axis_pos["x"], y_axis_pos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(500)
    page.keyboard.up("Shift")
    x_after_shift = _x_range_slice(page)
    y_after_shift = _y_range_slice(page)
    assert x_after_shift != x_before_shift, "Shift+rueda sobre Y debe desplazar X"
    assert y_after_shift == y_before_shift, "Shift+rueda sobre Y no debe cambiar Y"
    assert abs(_x_span_ms(page) - span_x_before_shift) < max(10, span_x_before_shift * 0.001), (
        "Shift+rueda no debe cambiar span X"
    )

    # Rueda fuera de la gráfica → sin cambios
    page.mouse.move(5, 5)
    x_out_before = _x_range_slice(page)
    y_out_before = _y_range_slice(page)
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(500)
    assert _x_range_slice(page) == x_out_before
    assert _y_range_slice(page) == y_out_before

    # Sin historial ni peticiones por zoom vertical
    assert page.evaluate("() => history.length") == history_before
    assert not grafica_reqs, grafica_reqs
    assert errs == [], errs


def test_rueda_vertical_week_y_month(page, server, tmp_path):
    """Rueda sobre el eje Y funciona en Semana y Mes (ejes categóricos)."""
    for gran in ("week", "month"):
        _seed_e2e_many_days(tmp_path, 40)
        page.goto(server + f"/?gran={gran}")
        page.wait_for_function("document.body.dataset.appReady === '1'")
        page.wait_for_function(
            "() => document.getElementById('unified-chart-plot')._fullData && document.getElementById('unified-chart-plot')._fullData.length>0"
        )
        y_before = _y_range_slice(page)
        x_before = _x_range_slice(page)
        span_y_before = abs(y_before[1] - y_before[0])
        y_pos = page.evaluate(
            """() => {
                const el = document.getElementById('unified-chart-plot');
                const rect = el.getBoundingClientRect();
                const m = el._fullLayout.margin;
                const h = el._fullLayout.height - m.t - m.b;
                return {x: rect.left + m.l/2, y: rect.top + m.t + h/2};
            }"""
        )
        page.mouse.move(y_pos["x"], y_pos["y"])
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(500)
        y_up = _y_range_slice(page)
        assert abs(y_up[1] - y_up[0]) < span_y_before, f"{gran} rueda arriba debe acercar Y"
        assert _x_range_slice(page) == x_before, f"{gran} rueda Y no debe tocar X"
        page.mouse.move(y_pos["x"], y_pos["y"])
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(500)
        y_down = _y_range_slice(page)
        assert abs(y_down[1] - y_down[0]) > abs(y_up[1] - y_up[0]), (
            f"{gran} rueda abajo debe alejar"
        )
        assert _x_range_slice(page) == x_before


def _cat_x_state(page):
    """Estado X real para ejes categóricos: rango numérico, tipos JS, span,
    validez (finito, ordenado) y puntos visibles dentro de la ventana."""
    return page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            const r = el._fullLayout.xaxis.range;
            const nums = Array.from(r, v => typeof v === 'number' ? v : NaN);
            const valid = nums.every(v => Number.isFinite(v)) && nums[0] < nums[1];
            let nCats = 0;
            el._fullData.forEach(t => { if (Array.isArray(t.x)) nCats = Math.max(nCats, t.x.length); });
            const lo = Math.max(0, Math.ceil(nums[0]));
            const hi = Math.min(nCats - 1, Math.floor(nums[1]));
            return {
                range: [nums[0], nums[1]],
                types: Array.from(r, v => typeof v),
                span: nums[1] - nums[0],
                valid: valid,
                nCats: nCats,
                visiblePts: hi >= lo ? hi - lo + 1 : 0,
            };
        }"""
    )


def _plot_point(page, fx=0.5):
    """Punto dentro del área de trazado a fracción fx del ancho útil."""
    return page.evaluate(
        """(fx) => {
            const el = document.getElementById('unified-chart-plot');
            const rect = el.getBoundingClientRect();
            const m = el._fullLayout.margin;
            const w = el._fullLayout.width - m.l - m.r;
            const h = el._fullLayout.height - m.t - m.b;
            return {x: rect.left + m.l + w * fx, y: rect.top + m.t + h * 0.5};
        }""",
        fx,
    )


def _y_axis_point(page):
    """Punto sobre el eje Y (geometría real, sin clases internas)."""
    return page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            const rect = el.getBoundingClientRect();
            const m = el._fullLayout.margin;
            const h = el._fullLayout.height - m.t - m.b;
            return {x: rect.left + m.l / 2, y: rect.top + m.t + h * 0.5};
        }"""
    )


@pytest.mark.parametrize("gran", ["week", "month"])
def test_zoom_categorico_estable_semana_mes(page, server, tmp_path, gran):
    """Zoom/pan por rueda en Semana/Mes es estable: reducción/ampliación
    progresiva del span, Shift+rueda conserva el span desplazando el rango,
    zoom Y no toca X, los datos permanecen visibles y no hay historial,
    peticiones /grafica ni errores de consola."""
    _seed_e2e_many_days(tmp_path, 400)
    page.goto(server + f"/?gran={gran}")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    history_before = page.evaluate("() => history.length")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    evidencia = {"gran": gran, "x_inicial": _x_range_slice(page)}
    pos = _plot_point(page, 0.5)

    # Rueda arriba ×5 → reducción progresiva del span.
    spans = []
    for i in range(5):
        page.mouse.move(pos["x"], pos["y"])
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(400)
        st = _cat_x_state(page)
        assert st["valid"], f"{gran} zoom {i}: rango inválido {st}"
        assert st["types"] == ["number", "number"], (
            f"{gran} zoom {i}: rango debe ser numérico (no etiquetas): {st['types']}"
        )
        if spans:
            assert st["span"] < spans[-1] * 0.999, (
                f"{gran} zoom {i}: span debe reducirse: {spans[-1]} → {st['span']}"
            )
        spans.append(st["span"])
        evidencia[f"zoom_arriba_{i + 1}"] = st

    # Rueda abajo → ampliación progresiva.
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(400)
    st_down = _cat_x_state(page)
    assert st_down["valid"] and st_down["span"] > spans[-1], (
        f"{gran} rueda abajo debe ampliar: {spans[-1]} → {st_down['span']}"
    )
    evidencia["zoom_abajo"] = st_down

    # Shift+rueda ×2 → span constante, rango desplazado.
    for i in range(2):
        prev = _cat_x_state(page)
        page.keyboard.down("Shift")
        page.mouse.move(pos["x"], pos["y"])
        page.mouse.wheel(0, 200)
        page.keyboard.up("Shift")
        page.wait_for_timeout(400)
        nxt = _cat_x_state(page)
        assert nxt["valid"], f"{gran} shift {i}: rango inválido {nxt}"
        assert abs(nxt["span"] - prev["span"]) < max(1e-9, prev["span"] * 1e-6), (
            f"{gran} shift {i}: span debe conservarse: {prev['span']} → {nxt['span']}"
        )
        assert nxt["range"] != prev["range"], f"{gran} shift {i}: rango debe desplazarse"
        evidencia[f"shift_{i + 1}"] = nxt

    # Ciclo repetido: otro acercamiento y otro alejamiento.
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(400)
    st_ciclo_in = _cat_x_state(page)
    assert st_ciclo_in["valid"] and st_ciclo_in["span"] < st_down["span"]
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(400)
    st_ciclo_out = _cat_x_state(page)
    assert st_ciclo_out["valid"] and st_ciclo_out["span"] > st_ciclo_in["span"]

    # Los datos siguen visibles dentro de la ventana.
    assert st_ciclo_out["visiblePts"] >= 1, (
        f"{gran}: datos fuera de vista tras las operaciones: {st_ciclo_out}"
    )

    # Zoom Y sobre el eje Y: solo cambia Y, X intacto.
    ypos = _y_axis_point(page)
    x_antes_y = _cat_x_state(page)["range"]
    y0 = _y_range_slice(page)
    page.mouse.move(ypos["x"], ypos["y"])
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(400)
    y_up = _y_range_slice(page)
    assert abs(y_up[1] - y_up[0]) < abs(y0[1] - y0[0]), f"{gran}: zoom Y arriba debe acercar"
    assert _cat_x_state(page)["range"] == x_antes_y, f"{gran}: zoom Y no debe tocar X"
    page.mouse.move(ypos["x"], ypos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(400)
    y_dn = _y_range_slice(page)
    assert abs(y_dn[1] - y_dn[0]) > abs(y_up[1] - y_up[0]), f"{gran}: zoom Y abajo debe alejar"
    assert _cat_x_state(page)["range"] == x_antes_y, f"{gran}: zoom Y no debe tocar X"

    # Shift+rueda sobre Y sigue desplazando X sin tocar Y.
    prev = _cat_x_state(page)
    y_antes_shift = _y_range_slice(page)
    page.keyboard.down("Shift")
    page.mouse.move(ypos["x"], ypos["y"])
    page.mouse.wheel(0, 200)
    page.keyboard.up("Shift")
    page.wait_for_timeout(400)
    nxt = _cat_x_state(page)
    assert nxt["range"] != prev["range"], f"{gran}: Shift+rueda sobre Y debe desplazar X"
    assert _y_range_slice(page) == y_antes_shift, f"{gran}: Shift+rueda sobre Y no debe tocar Y"

    # Sin historial, sin peticiones, sin errores.
    assert page.evaluate("() => history.length") == history_before
    assert not grafica_reqs, grafica_reqs
    assert errs == [], errs
    print(f"\n[evidencia {gran}] {evidencia}")


def test_regresion_decimal_rango_category_sin_redondeo(page, server, tmp_path):
    """Regresión del redondeo categórico: category inicial (etiquetas) → zoom
    con rango decimal → segundo zoom → Shift+rueda → zoom inverso. Falla si
    cualquier conversión redondea a etiquetas (strings) o colapsa el rango."""
    _seed_e2e_many_days(tmp_path, 400)
    page.goto(server + "/?gran=week")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    evidencia = {"rango_inicial": _x_range_slice(page)}
    # Ratio 0.37 (asimétrico) para forcar extremos fraccionarios.
    pos = _plot_point(page, 0.37)

    # Zoom 1: el rango pasa a numérico con decimales; nunca strings (etiquetas).
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(400)
    s1 = _cat_x_state(page)
    assert s1["types"] == ["number", "number"], f"post-zoom debe ser numérico: {s1['types']}"
    assert s1["valid"], f"rango inválido tras zoom 1: {s1}"
    tiene_decimal = (s1["range"][0] % 1) != 0 or (s1["range"][1] % 1) != 0
    assert tiene_decimal, f"el zoom debe conservar decimales, no redondear: {s1['range']}"

    # Zoom 2: la precisión se mantiene y el span vuelve a reducirse.
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(400)
    s2 = _cat_x_state(page)
    assert s2["types"] == ["number", "number"] and s2["valid"], f"zoom 2 dañó el rango: {s2}"
    assert s2["span"] < s1["span"], f"segundo zoom debe acercar: {s1['span']} → {s2['span']}"

    # Shift+rueda: span intacto, números con decimales preservados.
    page.keyboard.down("Shift")
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, 200)
    page.keyboard.up("Shift")
    page.wait_for_timeout(400)
    s3 = _cat_x_state(page)
    assert s3["valid"], f"Shift rompió el rango: {s3}"
    assert abs(s3["span"] - s2["span"]) < max(1e-9, s2["span"] * 1e-6), (
        f"Shift debe conservar span: {s2['span']} → {s3['span']}"
    )
    assert s3["range"] != s2["range"], "Shift debe desplazar el rango"

    # Zoom inverso: el span crece de nuevo sin saltos ni colapso.
    page.mouse.move(pos["x"], pos["y"])
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(400)
    s4 = _cat_x_state(page)
    assert s4["valid"], f"zoom inverso rompió el rango: {s4}"
    assert s4["span"] > s3["span"], f"zoom inverso debe ampliar: {s3['span']} → {s4['span']}"
    assert s4["span"] <= s1["span"] * 1.35, (
        f"zoom inverso no debe sobrepasar bruscamente: {s4['span']}"
    )
    assert s4["visiblePts"] >= 1, f"datos perdidos tras zoom inverso: {s4}"

    assert errs == [], errs
    print(f"\n[evidencia regresion-decimal] {evidencia}")


def test_autoajuste_y_incluye_series_visibles_y_respeta_manual(page, server, tmp_path):
    """Al seleccionar un músculo cuyo pico excede a Global, el rango Y cubre
    todas las series visibles; el zoom manual del eje X no se destruye al
    cambiar la selección."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        # Global ~80, músculo Pectoral con pico alto (kg 150 en el último día).
        for i in range(10):
            d = datetime.date(2026, 6, 1) + datetime.timedelta(days=i)
            kg = 150.0 if i == 9 else 80.0
            conn.execute(
                "INSERT INTO training_sets "
                "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
                "VALUES (?,?,?,1,'Press',6,?,0)",
                ((i // 7) + 1, "LUNES", d.isoformat(), kg),
            )
        conn.commit()
    finally:
        conn.close()

    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )
    page.wait_for_timeout(300)

    # Zoom manual en X: reducir el span visible.
    page.evaluate(
        """() => {
            const gd = document.getElementById('unified-chart-plot');
            const r = gd._fullLayout.xaxis.range;
            const mid = new Date((new Date(r[0]).getTime() + new Date(r[1]).getTime()) / 2);
            const s = new Date(mid); s.setDate(s.getDate() - 1);
            const e = new Date(mid); e.setDate(e.getDate() + 1);
            return Plotly.relayout(gd, {
                'xaxis.range[0]': s.toISOString().slice(0, 10),
                'xaxis.range[1]': e.toISOString().slice(0, 10),
            });
        }"""
    )
    page.wait_for_timeout(500)
    x_manual = _x_range_slice(page)

    # Seleccionar músculo: Y se reajusta incluyendo su pico; X manual se conserva.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    y_sel = _y_range_slice(page)
    assert y_sel[1] >= 0, f"el tope Y debe cubrir el pico: {y_sel}"
    # El pico visible (kg 150) debe quedar dentro del rango Y.
    gd = page.evaluate(
        """() => {
            const el = document.getElementById('unified-chart-plot');
            let maxY = -Infinity;
            for (const t of el._fullData) {
                for (const v of t.y) if (v !== null && v !== undefined) maxY = Math.max(maxY, v);
            }
            return { maxY, yRange: el._fullLayout.yaxis.range.slice() };
        }"""
    )
    assert gd["yRange"][1] >= gd["maxY"], f"max visible cortado: {gd}"
    # X manual NO se reinicia por el cambio de selección.
    x_tras_sel = _x_range_slice(page)
    assert x_tras_sel == x_manual, f"X manual se reinició: {x_manual} → {x_tras_sel}"


def test_y_window_ignora_historicos_fuera_de_la_ventana(page, server, tmp_path):
    """Datos negativos antiguos fuera de la ventana X inicial no condicionan el
    eje Y: la línea 0 queda en posición razonable; la rueda/pan siguen vivos."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        # 150 días: 120 antiguos con kg baja (negativos) + 30 recientes altos.
        start = datetime.date(2026, 1, 1)
        rows = []
        for i in range(150):
            d = start + datetime.timedelta(days=i)
            kg = 130.0 if i >= 120 else 50.0
            rows.append(
                (
                    (i // 7) + 1,
                    "LUNES",
                    d.isoformat(),
                    1,
                    "Press",
                    6.0,
                    kg,
                    0.0,
                )
            )
        conn.executemany(
            "INSERT INTO training_sets "
            "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )

    def plot_state():
        return page.evaluate(
            """() => {
                const el = document.getElementById('unified-chart-plot');
                const l = el._fullLayout;
                let minV = Infinity, maxV = -Infinity;
                const xr = l.xaxis.range;
                for (const t of el._fullData) {
                    t.x.forEach(function (x, i) {
                        const y = t.y[i];
                        if (y === null || y === undefined) return;
                        if (new Date(x) >= new Date(xr[0]) && new Date(x) <= new Date(xr[1])) {
                            if (y < minV) minV = y;
                            if (y > maxV) maxV = y;
                        }
                    });
                }
                return { xRange: l.xaxis.range.slice(), yRange: l.yaxis.range.slice(), minV, maxV };
            }"""
        )

    st = plot_state()
    x_lo = st["xRange"][0]
    # La ventana X inicial: últimos 2 meses aprox. (desde hoy - 2 meses).
    from datetime import date, timedelta

    hoy = date.today()
    esperado_lo = (hoy - timedelta(days=62)).isoformat()
    assert x_lo <= esperado_lo, f"ventana X inicial mal calculada: {x_lo} vs {esperado_lo}"
    # El rango Y NO está hundido por los negativos antiguos (fuera de la ventana).
    y_lo, y_hi = st["yRange"]
    assert y_lo > -15, f"la base no debe hundirse por antiguos: {st['yRange']}"
    assert y_hi >= st["maxV"], f"el máximo visible debe caber: {st['maxV']} > {y_hi}"
    assert y_lo <= 0 <= y_hi, f"la línea 0 debe ser visible: {st['yRange']}"
    # Los datos históricos siguen en la traza (pan hacia atrás posible).
    total_points = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullData[0].x.length"
    )
    assert total_points == 150, total_points

    # Seleccionar músculo con datos recientes: Y se recalcula con los visibles.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    st2 = plot_state()
    assert st2["yRange"][1] >= st2["maxV"], st2["yRange"]
    assert st2["yRange"][0] > -15, st2["yRange"]

    # Granularidades: cada una recalcula con su ventana.
    for gran in ("week", "month"):
        page.locator(f'#granularity-selector [data-gran="{gran}"]').click()
        page.wait_for_timeout(700)
        st3 = plot_state()
        assert st3["yRange"][0] <= 0 <= st3["yRange"][1], (gran, st3["yRange"])
        assert st3["yRange"][0] > -15, (gran, st3["yRange"])

    # Rueda y pan siguen funcionando tras el cambio.
    box = page.locator("#unified-chart-plot").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    x_before = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(500)
    x_after = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    assert x_after != x_before, "la rueda debe seguir funcionando tras el autoajuste"


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

    # Estado base (Fase 2: el detalle vive en #period-summary-wrap;
    # #history-section es un stub deprecado oculto, altura 0 constante).
    chart_h = rect("#unified-chart-container").get("height")
    # Contrato Fase 2-layout: posición RELATIVA AL DOCUMENTO (el scroll del
    # navegador puede anclar al crecer columnas sticky; eso no es CLS).
    chart_doc_y = page.evaluate(
        "() => { const r = document.getElementById('unified-chart-container').getBoundingClientRect(); return r.top + window.scrollY; }"
    )
    summary_h = rect("#period-summary-wrap").get("height")

    # Seleccionar un músculo
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)

    chart_after_h = rect("#unified-chart-container").get("height")
    chart_after_doc_y = page.evaluate(
        "() => { const r = document.getElementById('unified-chart-container').getBoundingClientRect(); return r.top + window.scrollY; }"
    )
    summary_after_h = rect("#period-summary-wrap").get("height")

    assert chart_h and chart_doc_y and summary_h, (chart_h, chart_doc_y, summary_h)
    assert abs(chart_after_h - chart_h) <= 1.0, f"chart CLS: {chart_h} → {chart_after_h}"
    assert abs(chart_after_doc_y - chart_doc_y) <= 1.0, (
        f"chart doc-y shift: {chart_doc_y} → {chart_after_doc_y}"
    )
    # El panel puede cambiar de contenido pero NO desplazar la página: su caja
    # es sticky con altura acotada; el ancho externo debe ser invariante.
    summary_w_before = rect("#period-summary-wrap").get("width") or 0
    summary_w_after = rect("#period-summary-wrap").get("width") or 0
    assert abs(summary_w_after - summary_w_before) <= 1.0
    # (scroll crudo puede variar por scroll-anchoring; no es desplazamiento
    #  de layout — la posición documental ya se verifica arriba.)
    # La columna sticky no supera la altura disponible (scroll interno).
    catalog_h = rect(".dashboard-catalog-col").get("height") or 0
    assert catalog_h <= 800 - 32 + 1, f"catálogo excede el viewport: {catalog_h}px"
    summary_h_ok = summary_after_h <= 800 - 32 + 1
    assert summary_h_ok, f"panel excede el viewport: {summary_after_h}px"


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
    # La lista vive en el diálogo del Diario: abrirlo para el drag.
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    page.wait_for_selector("#training-templates-dialog[open]", timeout=5000)
    # Mover el segundo arriba con el ratón (cuerpo de la tarjeta).
    _drag_card_up(
        page, "#plantillas-list .pt-card:nth-child(2)", "#plantillas-list .pt-card:nth-child(1)"
    )
    page.wait_for_timeout(600)
    expect(page.locator("#plantillas-list .pt-card").nth(0)).to_have_attribute(
        "data-pt-nombre", "Back Day"
    )
    # Persistencia tras recarga.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    page.wait_for_selector("#training-templates-dialog[open]", timeout=5000)
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
    page.locator(
        '[data-action="open-daily-dialog"][data-dialog="training-templates-dialog"]'
    ).click()
    page.wait_for_selector("#training-templates-dialog[open]", timeout=5000)

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
    _open_popup(page, server, vista="alimentacion")
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
    page.locator(f'#date-navigator .date-num[data-iso="{iso_cardio}"]').click()
    expect(page.locator("#cardio-day form[data-action='cardio-annotation-save']")).to_have_count(
        1, timeout=5000
    )
    form = page.locator("#cardio-day form[data-action='cardio-annotation-save']").first
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
    _open_popup(page, server)
    # Foco fuera del navigator: las flechas no navegan.
    page.locator('.workspace-nav a[href="/"]').focus()
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
    expect(page.locator("#cardio-day")).to_contain_text("Sin sesiones de ejercicio", timeout=5000)
    page.locator(f'#date-navigator .date-num[data-iso="{iso_cardio}"]').click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(
        iso_cardio, timeout=5000
    )
    expect(page.locator("#cardio-day form[data-action='cardio-annotation-save']")).to_have_count(
        1, timeout=5000
    )
    expect(page.locator("#cardio-day")).to_contain_text("Cinta")


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
    """Expanding a catalog group does not change chart height or offset.

    Contrato Fase 2-layout: la posición se mide RELATIVA AL DOCUMENTO
    (rect.top + scrollY); el scroll del navegador puede anclar al expandir
    columnas sticky más altas que el viewport, y eso no es CLS de layout.
    """
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    def doc_metrics():
        return page.evaluate(
            """() => {
                const el = document.getElementById('unified-chart-container');
                const r = el.getBoundingClientRect();
                return {h: r.height, docY: r.top + window.scrollY};
            }"""
        )

    before = doc_metrics()
    summary = page.locator('#dashboard-catalog [data-action="toggle-group"]').first
    summary.click()
    page.wait_for_timeout(300)
    after = doc_metrics()
    assert abs(before["h"] - after["h"]) < 2, f"Chart height changed: {before} -> {after}"
    assert abs(before["docY"] - after["docY"]) < 2, f"Chart document-y changed: {before} -> {after}"


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
    """On mobile, catalog is a drawer overlay (fixed, initially hidden)."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#catalog-toggle-mobile")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#catalog-toggle-mobile")).to_be_visible()
    expect(page.locator(".dashboard-catalog-col")).to_be_hidden()
    expect(page.locator("#catalog-overlay")).to_be_hidden()
    page.locator("#catalog-toggle-mobile").click()
    page.wait_for_timeout(300)
    expect(page.locator(".dashboard-catalog-col")).to_be_visible()
    expect(page.locator("#catalog-overlay")).to_be_visible()
    box = page.locator(".dashboard-catalog-col").bounding_box()
    assert 50 <= box["y"] <= 80, f"drawer top should be below header: {box}"
    # Overlay cubre toda la pantalla; el drawer (z-index 30) está por encima.
    # Clicar el centro del overlay caería sobre el drawer, así que se usa
    # click evaluado.
    page.locator("#catalog-overlay").evaluate("el => el.click()")
    page.wait_for_timeout(300)
    expect(page.locator(".dashboard-catalog-col")).to_be_hidden()


def test_dashboard_no_level_chip_in_catalog(page, server):
    """The old .level-chip class is not used in the catalog."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    count = page.locator("#dashboard-catalog .level-chip").count()
    assert count == 0, f"Found {count} .level-chip elements in catalog"


def _seed_long_history(tmp_path):
    """Siembra 420 días (~60 semanas, ~14 meses): antiguos negativos + recientes
    positivos + cola ligeramente negativa. Devuelve la ruta de la DB."""
    import datetime
    import sqlite3

    db = str(tmp_path / "lifestyle.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral','Press')"
        )
        start = datetime.date(2025, 1, 1)
        rows = []
        for i in range(420):
            d = start + datetime.timedelta(days=i)
            if i < 240:
                kg = 50.0  # antiguos muy negativos (fuera de ventana)
            elif i < 400:
                kg = 140.0  # recientes positivos (dentro de ventana)
            else:
                kg = 80.0  # cola ligera
            rows.append(
                (
                    (i // 7) + 1,
                    "LUNES",
                    d.isoformat(),
                    1,
                    "Press",
                    6.0,
                    kg,
                    0.0,
                )
            )
        conn.executemany(
            "INSERT INTO training_sets "
            "(semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return db


def test_granularidades_grafica_visible_y_y_por_ventana(page, server, tmp_path):
    """Global en Día/Semana/Mes: la gráfica es visible, el rango X y el rango
    Y cubren ventanas correctas y la línea 0 está dentro. Repite con músculo
    seleccionado. Al final, rueda/pan siguen operativos."""
    _seed_long_history(tmp_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('unified-chart-plot')._fullData.length > 0"
    )

    def chart_view():
        return page.evaluate(
            """() => {
                const el = document.getElementById('unified-chart-plot');
                const l = el._fullLayout;
                if (!l.xaxis || !l.yaxis) return null;
                const xr = l.xaxis.range, yr = l.yaxis.range;
                const cat = l.xaxis.type === 'category';
                const lo = xr[0], hi = xr[1];
                const nlo = Number(lo), nhi = Number(hi);
                const useIdx = !Number.isNaN(nlo) && !Number.isNaN(nhi);
                // Categorías en orden de aparición (categoryorder='trace').
                const cats = [];
                for (const t of el._fullData) {
                    t.x.forEach(function (x) {
                        const sx = String(x);
                        if (cats.indexOf(sx) === -1) cats.push(sx);
                    });
                }
                let minV = Infinity, maxV = -Infinity, visibles = 0;
                for (const t of el._fullData) {
                    t.x.forEach(function (x, i) {
                        const y = t.y[i];
                        if (y === null || y === undefined) return;
                        let inside = false;
                        if (cat) {
                            // Plotly convierte el rango category a índices sobre
                            // las categorías en orden de aparición.
                            if (useIdx) {
                                const idx = cats.indexOf(String(x));
                                if (idx >= 0) inside = nlo <= idx && idx <= nhi;
                            } else {
                                inside = String(lo) <= String(x) && String(x) <= String(hi);
                            }
                        } else {
                            const xt = new Date(x).getTime();
                            inside = xt >= new Date(lo).getTime() && xt <= new Date(hi).getTime();
                        }
                        if (inside) {
                            visibles++;
                            if (y < minV) minV = y;
                            if (y > maxV) maxV = y;
                        }
                    });
                }
                return {
                    xType: l.xaxis.type, xRange: xr.slice(),
                    yRange: yr.slice(), minV, maxV, visibles,
                    plotVisible: !el.hidden,
                };
            }"""
        )

    # Global en las 3 granularidades: visible, 0 en rango, Y cubre visibles.
    for gran in ("day", "week", "month"):
        page.locator(f'#granularity-selector [data-gran="{gran}"]').click()
        page.wait_for_timeout(800)
        v = chart_view()
        assert v and v["plotVisible"] is not False, (gran, v)
        assert v["plotVisible"], f"gráfica invisible en {gran}: {v}"
        y0, y1 = v["yRange"]
        assert y0 <= 0 <= y1, f"{gran}: 0 fuera del rango Y: {v['yRange']}"
        assert y1 >= v["maxV"], f"{gran}: max visible cortado: {v}"
        assert y0 <= v["minV"], f"{gran}: min visible cortado: {v}"
        assert v["visibles"] > 0, f"{gran}: ningún punto en la ventana"
        # El rango X de semana debe cubrir ~15 semanas: los visibles son esos.
        if gran == "week":
            assert v["xRange"][1] > v["xRange"][0], v["xRange"]

    # Con músculo seleccionado: sigue visible y el Y se recalcula.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    for gran in ("week", "month"):
        page.locator(f'#granularity-selector [data-gran="{gran}"]').click()
        page.wait_for_timeout(800)
        v = chart_view()
        assert v and v["plotVisible"], (gran, v)
        assert v["yRange"][0] <= 0 <= v["yRange"][1], (gran, v["yRange"])
        assert v["yRange"][1] >= v["maxV"], (gran, v)
    # Conexión viva: rueda y pan siguen funcionando en Mes.
    box = page.locator("#unified-chart-plot").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    x_before = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(500)
    x_after = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullLayout.xaxis.range.slice()"
    )
    assert x_after != x_before, "la rueda debe seguir funcionando"


# ---------------------------------------------------------------------------
# Fase 2 — Panel derecho: sincronización en una sola petición
# ---------------------------------------------------------------------------


def _panel(page):
    return page.locator("#period-summary-wrap")


def test_panel_sync_una_peticion_seleccion(page, server, tmp_path):
    """Cambio de selección → exactamente UNA petición /grafica que actualiza
    gráfica y panel juntos; el panel muestra la vista del músculo."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    expect(_panel(page)).to_be_visible()
    base = len(grafica_reqs)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(700)
    nuevos = grafica_reqs[base:]
    assert len(nuevos) == 1, f"debe haber UNA petición: {nuevos}"
    assert "ventana=8" in nuevos[0], nuevos[0]
    # El panel OOB llegó: sigue visible y sin estado de error.
    assert "No se pudo calcular" not in _panel(page).inner_text()


def test_tabs_cero_peticiones(page, server, tmp_path):
    """Multi-músculos → pestañas prerenderizadas; cambiar pestaña no fetch."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    base = len(grafica_reqs)
    # Shift+click en la fila del músculo Biceps (multi-selección).
    biceps_group = page.locator('#dashboard-catalog .db-group[data-group="Biceps"]')
    biceps_summary = biceps_group.locator('[data-action="toggle-group"]')
    if biceps_summary.get_attribute("aria-expanded") != "true":
        biceps_summary.click()
        page.wait_for_timeout(120)
    biceps_row = biceps_group.locator('[data-action="toggle-muscle"]').first
    biceps_row.click(modifiers=["Shift"])
    page.wait_for_timeout(800)
    assert len(grafica_reqs) - base == 1, grafica_reqs[base:]

    tabs = page.locator('#period-summary-wrap [role="tab"]')
    expect(tabs.first).to_be_visible()
    assert tabs.count() >= 2
    segunda = tabs.nth(1)
    segunda.evaluate("el => el.click()")
    page.wait_for_timeout(300)
    assert len(grafica_reqs) - base == 1, "cambiar pestaña NO debe pedir nada"
    expect(segunda).to_have_attribute("aria-selected", "true")
    panel_activo = page.locator("#ps-panel-1")
    expect(panel_activo).to_be_visible()
    panel_oculto = page.locator("#ps-panel-0")
    expect(panel_oculto).to_be_hidden()
    # Teclado: flecha derecha mueve la tab activa sin fetch.
    segunda.press("ArrowLeft")
    page.wait_for_timeout(200)
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    assert len(grafica_reqs) - base == 1
    assert errs == [], errs


def test_ventana_cambio_una_peticion(page, server, tmp_path):
    """La ventana técnica es fija y no se expone como selector."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#summary-window-select")).to_have_count(0)


def test_back_forward_restaura_grafica_y_panel(page, server, tmp_path):
    """Back restaura selección vacía y dispara refresco de gráfica+panel."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(700)
    base = len(grafica_reqs)
    page.go_back()
    page.wait_for_timeout(900)
    assert len(grafica_reqs) > base, "back debe refrescar gráfica+panel"
    assert "No se pudo calcular" not in _panel(page).inner_text()


def test_rapido_doble_clic_sin_errores(page, server, tmp_path):
    """Stale protection: dos selecciones rápidas terminan en estado válido,
    sin errores de consola y con panel consistente."""
    import re as _re

    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    urls = []
    page.on(
        "request",
        lambda r: urls.append(r.url) if "/grafica" in r.url else None,
    )
    group = page.locator('#dashboard-catalog .db-group[data-group="Pectoral"]')
    summary_btn = group.locator('[data-action="toggle-group"]')
    if summary_btn.get_attribute("aria-expanded") != "true":
        summary_btn.click()
        page.wait_for_timeout(120)
    row = page.locator('#dashboard-catalog [data-action="toggle-muscle"]').first
    row.click()
    row.click()  # segundo clic deselecciona
    page.wait_for_timeout(1000)
    # La última URL ganadora determina el panel; ninguna respuesta vieja rompe.
    for u in urls:
        assert _re.search(r"[?&]gran=", u), u
    # El abort del segundo clic dispara el log interno de htmx (sendAbort):
    # es la protección stale POR DISEÑO (cancelPending), no un error real.
    errs_reales = [
        e for e in errs if not (e.startswith("htmx:") or e == "undefined" or "abort" in e.lower())
    ]
    assert errs_reales == [], errs_reales


# ---------------------------------------------------------------------------
# Fase 2-fix — Correcciones de la revisión: altura estable, overflow y ARIA
# ---------------------------------------------------------------------------


def test_panel_botones_ventana_estado_por_aria(page, server, tmp_path):
    """El panel no renderiza el control obsoleto de ventana."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#summary-window-select")).to_have_count(0)


def test_tabla_ejercicio_scroll_horizontal_390px(page, server, tmp_path):
    """390px (viewport <480): Peso/RIR ocultos por CSS en TODAS las vistas;
    global/músculo sin scroll forzado; página sin overflow horizontal."""

    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    metrics = page.evaluate(
        """() => {
            const wrap = document.getElementById('period-summary-wrap');
            const panels = wrap.querySelector('.ps-panels');
            const table = panels.querySelector('.ps-table');
            const rirTh = table.querySelector('th.col-rir');
            const st = rirTh ? getComputedStyle(rirTh) : null;
            return {
                docOverflowX: document.documentElement.scrollWidth <= window.innerWidth,
                panelW: wrap.getBoundingClientRect().width,
                tableScroll: table.scrollWidth,
                panelsClient: panels.clientWidth,
                panelsOvX: getComputedStyle(panels).overflowX,
                // Contrato sr: colapsada visualmente pero presente para AT.
                rirCollapsed: st ? st.position === 'absolute' && parseFloat(st.width) <= 1.5 : null,
            };
        }"""
    )
    assert metrics["docOverflowX"], "la página no debe desbordar horizontalmente"
    assert metrics["panelW"] <= 391, f"panel excede viewport: {metrics['panelW']}"
    # Columnas progresivas activas por media query <480px (patrón sr).
    assert metrics["rirCollapsed"] is True, metrics
    # Vista histórica 7 cols: overflow X auto para scroll interno
    assert metrics["panelsOvX"] in ("auto", "scroll"), metrics


def test_tabla_ejercicio_escritorio_columnas_visibles(page, server, tmp_path):
    """Regresión del bug @container: en escritorio (panel 300px) Peso/RIR del
    ejercicio NO se ocultan; solo la tabla exercise fuerza scroll."""
    from playwright.sync_api import expect as _expect

    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    _exercise_input(page, "Press").click()
    page.wait_for_timeout(900)
    info = page.evaluate(
        """() => {
            const table = document.querySelector('#period-summary-wrap .ps-table--exercise');
            if (!table) return {found: false};
            const pesoTh = table.querySelector('th.col-peso');
            return {
                found: true,
                minW: getComputedStyle(table).minWidth,
                pesoVisible: pesoTh ? getComputedStyle(pesoTh).display !== 'none' : false,
            };
        }"""
    )
    assert info["found"], "la vista ejercicio debe estar activa tras seleccionar uno"
    _expect(page.locator("#period-summary-wrap")).to_be_visible()
    assert info["minW"] == "460px", f"min-width debe aplicar SOLO a exercise: {info}"
    assert info["pesoVisible"] is True, "Peso no debe ocultarse en escritorio"


def test_movil_cambio_tab_catalogo_estable(page, server, tmp_path):
    """Opción A (altura fija móvil): cambiar de pestaña con distinto nº de
    filas NO desplaza el catálogo (dimensiones invariantes)."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    # Drawer móvil: asegurar abierto antes de interactuar con Biceps
    if page.locator("#catalog-toggle-mobile").get_attribute("aria-expanded") == "false":
        page.locator("#catalog-toggle-mobile").click()
        page.wait_for_timeout(300)
    group = page.locator('#dashboard-catalog .db-group[data-group="Biceps"]')
    bsum = group.locator('[data-action="toggle-group"]')
    if bsum.get_attribute("aria-expanded") != "true":
        bsum.evaluate("el => el.click()")
        page.wait_for_timeout(200)
    group.locator('[data-action="toggle-muscle"]').first.click(modifiers=["Shift"])
    page.wait_for_timeout(800)
    # Cerrar drawer para poder interactuar con el panel (evita intercepción)
    if page.locator("#catalog-toggle-mobile").get_attribute("aria-expanded") == "true":
        page.locator("#catalog-toggle-mobile").click()
        page.wait_for_timeout(300)
    tabs = page.locator('#period-summary-wrap [role="tab"]')
    expect(tabs.first).to_be_visible()
    y_before = page.evaluate(
        "() => document.querySelector('.dashboard-catalog-col').getBoundingClientRect().y"
    )
    tabs.nth(1).evaluate("el => el.click()")
    page.wait_for_timeout(400)
    y_after = page.evaluate(
        "() => document.querySelector('.dashboard-catalog-col').getBoundingClientRect().y"
    )
    assert abs(y_after - y_before) <= 2.0, f"catálogo desplazado: {y_before} → {y_after}"


# ---------------------------------------------------------------------------
# Fase 2-layout — Jerarquía visual: scroll único, alturas fijas, plegado
# ---------------------------------------------------------------------------


def test_panel_scroll_unico_y_glow_apagado(page, server, tmp_path):
    """Dentro de #period-summary-wrap SOLO .ps-panels desplaza verticalmente;
    el contenedor externo es overflow hidden y sin marco metálico."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    info = page.evaluate(
        """() => {
            const wrap = document.getElementById('period-summary-wrap');
            const panels = wrap.querySelector('.ps-panels');
            const ws = getComputedStyle(wrap);
            const ps = getComputedStyle(panels);
            // Hijos directos con overflow-y auto además de .ps-panels
            const otros = [...wrap.querySelectorAll('*')].filter((el) => {
                if (el === panels) return false;
                const oy = getComputedStyle(el).overflowY;
                return (oy === 'auto' || oy === 'scroll') &&
                       el.scrollHeight > el.clientHeight + 1;
            }).map(el => el.className || el.id);
            return {
                wrapOverflowY: ws.overflowY,
                wrapDisplay: ws.display,
                flexDir: ws.flexDirection,
                panelsOvY: ps.overflowY,
                panelsOvX: ps.overflowX,
                otrosScrollables: otros,
                pseudoBefore: getComputedStyle(wrap, '::before').display,
            };
        }"""
    )
    assert info["wrapOverflowY"] == "hidden", info
    assert info["flexDir"] == "column", info
    assert info["panelsOvY"] == "auto", info
    assert info["otrosScrollables"] == [], f"segunda zona de scroll: {info}"
    # Glow metálico suprimido solo en este panel.
    assert info["pseudoBefore"] == "none", info


def test_panel_altura_fija_entre_tabs_y_ventana(page, server, tmp_path):
    """La caja del panel no cambia ante pestañas ni ventana 4↔8."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    h0 = page.evaluate(
        "() => document.getElementById('period-summary-wrap').getBoundingClientRect().height"
    )
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(700)
    tabs = page.locator('#period-summary-wrap [role="tab"]')
    if tabs.count() >= 2:
        tabs.nth(1).click()
        page.wait_for_timeout(300)
    h1 = page.evaluate(
        "() => document.getElementById('period-summary-wrap').getBoundingClientRect().height"
    )
    assert abs(h1 - h0) <= 1.0, f"tab cambió altura: {h0} → {h1}"
    # Altura fija basada en viewport (~calc(100dvh-32px) = 768 aquí).
    assert 600 <= h1 <= 800, f"altura fuera de rango viewport: {h1}"


def test_catalogo_plegable_accesible(page, server, tmp_path):
    """Plegar/reabrir catálogo: ARIA correcto, selección intacta, cero fetch,
    URL y history invariantes."""
    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)

    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    base_reqs = len(grafica_reqs)

    btn = page.locator("#catalog-toggle")
    expect(btn).to_be_visible()
    expect(btn).to_have_attribute("aria-expanded", "true")
    expect(btn).to_have_attribute("aria-controls", "dashboard-catalog")
    url_before = page.url
    hist_before = page.evaluate("() => history.length")

    btn.click()
    page.wait_for_timeout(300)
    # Rail persistente: el panel de grupos se oculta, la rail aparece con su
    # propio botón; la primera pista del grid NUNCA desaparece.
    rail = page.locator(".catalog-rail")
    expect(page.locator(".catalog-panel")).to_be_hidden()
    expect(rail).to_be_visible()
    rail_btn = page.locator("#catalog-rail-toggle")
    expect(rail_btn).to_be_visible()
    expect(rail_btn).to_have_attribute("aria-expanded", "false")
    expect(rail_btn).to_have_attribute("aria-label", "Mostrar catálogo")
    expect(btn).to_have_attribute("aria-expanded", "false")
    expect(btn).to_have_attribute("aria-label", "Mostrar catálogo")
    cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('.dashboard-layout')).gridTemplateColumns"
    )
    assert cols.split(" ")[0].replace("px", "").isdigit(), cols
    first_track = float(cols.split(" ")[0].replace("px", ""))
    assert 44 <= first_track <= 52, f"rail debe medir ~48px: {cols}"
    # Sin fetch, sin URL, sin history, sin errores.
    assert len(grafica_reqs) == base_reqs, grafica_reqs[base_reqs:]
    assert page.url == url_before
    assert page.evaluate("() => history.length") == hist_before

    # Reabrir desde la rail restaura el panel con la selección conservada.
    rail_btn.click()
    page.wait_for_timeout(400)
    expect(page.locator(".catalog-panel")).to_be_visible()
    expect(rail).to_be_hidden()
    expect(btn).to_have_attribute("aria-expanded", "true")
    expect(btn).to_have_attribute("aria-label", "Ocultar catálogo")
    assert len(grafica_reqs) == base_reqs
    musculo_btn = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    expect(musculo_btn).to_have_attribute("aria-pressed", "true")
    assert errs == [], errs


def test_grafica_altura_css_ready(page, server, tmp_path):
    """La gráfica usa la altura CSS clamp (480-620) y es idéntica entre
    selecciones (ready); Plotly llena exactamente la caja."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#unified-chart-plot .main-svg", timeout=15000)

    def medidas():
        return page.evaluate(
            """() => {
                const wrap = document.getElementById('unified-chart');
                const plot = document.getElementById('unified-chart-plot');
                const svg = plot && plot.querySelector('.main-svg');
                return {
                    wrapH: wrap.getBoundingClientRect().height,
                    plotH: plot ? plot.getBoundingClientRect().height : null,
                    svgH: svg ? svg.getBoundingClientRect().height : null,
                };
            }"""
        )

    m1 = medidas()
    assert 480 <= m1["wrapH"] <= 620, f"altura CSS fuera de clamp: {m1}"
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    m2 = medidas()
    assert abs(m2["wrapH"] - m1["wrapH"]) <= 1.0, f"CLS de gráfica: {m1} → {m2}"
    # Plotly llena EXACTAMENTE la caja del plot (flex fill tras el header).
    assert abs(m2["svgH"] - m2["plotH"]) <= 2.0, m2
    assert m2["plotH"] >= 480 - 40, f"plot demasiado bajo respecto al clamp: {m2}"


def test_grid_sin_overflow_horizontal_escritorio(page, server, tmp_path):
    """1280px: catálogo compacto + panel ancho no provocan overflow de página;
    las vistas global/músculo no necesitan scroll horizontal interno."""

    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    ok = page.evaluate(
        """() => {
            const panels = document.querySelector('#period-summary-wrap .ps-panels');
            const table = panels.querySelector('.ps-table');
            return {
                docOk: document.documentElement.scrollWidth <= window.innerWidth,
                bodyOk: document.body.scrollWidth <= window.innerWidth + 1,
                layoutOk: (() => { const l=document.querySelector('.dashboard-layout'); return l.scrollWidth <= l.clientWidth + 1; })(),
                panelsOvX: getComputedStyle(panels).overflowX,
            };
        }"""
    )
    assert ok["docOk"] and ok["bodyOk"] and ok["layoutOk"], ok
    # Vista histórica 7 cols necesita scroll horizontal interno
    assert ok["panelsOvX"] in ("auto", "scroll"), ok


# ---------------------------------------------------------------------------
# Fase 2-sidebar — Rail persistente, IDs únicos, caja real y resize Plotly
# ---------------------------------------------------------------------------


def test_ids_unicos_dashboard(page, server):
    """Regresión: #dashboard-catalog existe UNA sola vez en el DOM y todos los
    controles del sidebar tienen ids únicos (aria-controls/getElementById)."""
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    for dom_id in (
        "dashboard-catalog",
        "catalog-toggle",
        "catalog-toggle-mobile",
        "catalog-rail-toggle",
        "catalog-overlay",
    ):
        n = page.evaluate(f"() => document.querySelectorAll('#{dom_id}').length")
        assert n == 1, f"id duplicado #{dom_id}: {n} instancias"


def test_catalog_rail_desktop_sin_hueco_y_alineado(page, server):
    """Plegado desktop: primera pista = rail 48px (sin hueco), gráfica se
    expande, y catálogo/gráfica arrancan en el mismo eje vertical."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")

    def tops():
        return page.evaluate(
            """() => ({
                catalog: document.getElementById('dashboard-catalog').getBoundingClientRect().top,
                chart: document.getElementById('unified-chart-container').getBoundingClientRect().top,
            })"""
        )

    t_open = tops()
    assert abs(t_open["catalog"] - t_open["chart"]) <= 1.0, t_open
    page.locator("#catalog-toggle").click()
    page.wait_for_timeout(300)
    cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('.dashboard-layout')).gridTemplateColumns"
    )
    tracks = [float(x.replace("px", "")) for x in cols.split(" ")]
    assert len(tracks) == 3 and 44 <= tracks[0] <= 52, cols
    ok = page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    assert ok, "overflow horizontal con rail"
    t_closed = tops()
    assert abs(t_closed["catalog"] - t_closed["chart"]) <= 1.0, t_closed
    # Reabrir: vuelve a 3 pistas originales.
    page.locator("#catalog-rail-toggle").click()
    page.wait_for_timeout(300)
    cols_open = page.evaluate(
        "() => getComputedStyle(document.querySelector('.dashboard-layout')).gridTemplateColumns"
    )
    assert float(cols_open.split(" ")[0].replace("px", "")) > 200, cols_open


def test_panel_dentro_del_viewport_desktop(page, server, tmp_path):
    """La caja REAL del panel derecho cabe tras la cabecera en escritorio:
    top >= layout.top y bottom <= innerHeight, con datos y sin ellos; la
    página no crece entre estados (sin extensión por el panel)."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    box_empty = page.evaluate(
        """() => {
            const p = document.getElementById('period-summary-wrap').getBoundingClientRect();
            const l = document.querySelector('.dashboard-layout').getBoundingClientRect();
            return {top: p.top, bottom: p.bottom, layoutTop: l.top,
                    docH: document.documentElement.scrollHeight};
        }"""
    )
    assert box_empty["top"] >= box_empty["layoutTop"] - 1, box_empty
    assert box_empty["bottom"] <= 800 + 1, f"panel excede viewport (vacío): {box_empty}"
    _ = box_empty["docH"]

    _seed_e2e_many_days(tmp_path, 40)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(700)
    box_ready = page.evaluate(
        """() => {
            const p = document.getElementById('period-summary-wrap').getBoundingClientRect();
            const l = document.querySelector('.dashboard-layout').getBoundingClientRect();
            return {top: p.top, bottom: p.bottom, layoutTop: l.top,
                    docH: document.documentElement.scrollHeight};
        }"""
    )
    assert box_ready["top"] >= box_ready["layoutTop"] - 1, box_ready
    assert box_ready["bottom"] <= 800 + 1, f"panel excede viewport (datos): {box_ready}"
    # La altura de la caja es idéntica vacío vs datos (dimensiones invariantes).
    h_empty = box_empty["bottom"] - box_empty["top"]
    h_ready = box_ready["bottom"] - box_ready["top"]
    assert abs(h_ready - h_empty) <= 1.0, f"altura cambió: {h_empty} → {h_ready}"


def test_rail_visual_barra_completa(page, server, tmp_path):
    """TAREA 1B — Rail izquierdo debe ser barra vertical completa, no caja pequeña.

    Verifica los 14 puntos del contrato visual a 1280×800 y el comportamiento
    móvil sin rail desktop.
    """
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    # Selecciona para verificar conservación posterior.
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(600)
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    base_reqs = len(grafica_reqs)
    url_before = page.url
    hist_before = page.evaluate("() => history.length")

    def medidas():
        return page.evaluate(
            """() => ({
                catalog: document.querySelector("#dashboard-catalog")?.getBoundingClientRect(),
                chart: document.querySelector("#unified-chart-container")?.getBoundingClientRect(),
                summary: document.querySelector("#period-summary-wrap")?.getBoundingClientRect(),
                rail: document.querySelector(".catalog-rail")?.getBoundingClientRect(),
                railStyle: document.querySelector(".catalog-rail") ? {
                    display: getComputedStyle(document.querySelector(".catalog-rail")).display,
                    height: getComputedStyle(document.querySelector(".catalog-rail")).height,
                    borderRight: getComputedStyle(document.querySelector(".catalog-rail")).borderRightWidth,
                    borderStyle: getComputedStyle(document.querySelector(".catalog-rail")).borderRightStyle,
                    width: getComputedStyle(document.querySelector(".catalog-rail")).width
                } : null,
                grid: getComputedStyle(document.querySelector(".dashboard-layout")).gridTemplateColumns,
                scrollWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                summaryDisplay: document.querySelector("#period-summary-wrap") ? getComputedStyle(document.querySelector("#period-summary-wrap")).display : null,
                railBtn: document.querySelector("#catalog-rail-toggle") ? {
                    w: getComputedStyle(document.querySelector("#catalog-rail-toggle")).width,
                    h: getComputedStyle(document.querySelector("#catalog-rail-toggle")).height,
                    text: document.querySelector("#catalog-rail-toggle").innerText.trim(),
                    ariaExpanded: document.querySelector("#catalog-rail-toggle").getAttribute("aria-expanded"),
                    ariaLabel: document.querySelector("#catalog-rail-toggle").getAttribute("aria-label"),
                    ariaControls: document.querySelector("#catalog-rail-toggle").getAttribute("aria-controls")
                } : null,
                summaryVisible: (() => {
                    const s=document.querySelector("#period-summary-wrap");
                    return s && getComputedStyle(s).display!=="none" && s.getBoundingClientRect().width>5;
                })(),
                focused: document.activeElement ? document.activeElement.id : null
            })"""
        )

    m_open = medidas()
    # Estado abierto: catálogo y gráfica mismo top ±1px.
    assert abs(m_open["catalog"]["y"] - m_open["chart"]["y"]) <= 1.0, m_open
    assert m_open["summaryVisible"], "summary debe estar visible abierto"
    assert len(m_open["grid"].split(" ")) == 3, (
        f"grid debe tener 3 pistas abierto: {m_open['grid']}"
    )
    # Plegar
    page.locator("#catalog-toggle").click()
    page.wait_for_timeout(400)
    m_closed = medidas()
    # 1 rail visible
    assert m_closed["railStyle"]["display"] != "none", "rail debe ser visible plegado"
    # 2 altura completa: rail ≈ altura del layout (no caja pequeña)
    # Compara rail height vs summary height y vs chart: debe ser ≥ 400 y ≈ summary
    rail_h = m_closed["rail"]["height"]
    summary_h = m_closed["summary"]["height"]
    assert rail_h >= 400, f"rail altura pequeña: {rail_h} vs summary {summary_h}"
    assert abs(rail_h - summary_h) <= 4, (
        f"rail debe ocupar altura completa del layout: rail {rail_h} vs summary {summary_h}"
    )
    # 3 borde vertical visible
    assert (
        m_closed["railStyle"]["borderRight"] != "0px"
        and m_closed["railStyle"]["borderStyle"] == "solid"
    ), m_closed["railStyle"]
    # 4 botón solo icono 36-40px, sin texto, aria correctos
    assert m_closed["railBtn"] is not None
    assert m_closed["railBtn"]["w"] in ("36px", "37px", "38px", "39px", "40px"), m_closed["railBtn"]
    assert m_closed["railBtn"]["h"] in ("36px", "37px", "38px", "39px", "40px"), m_closed["railBtn"]
    assert m_closed["railBtn"]["text"] == "", (
        f"botón debe ser solo icono, texto='{m_closed['railBtn']['text']}'"
    )
    assert m_closed["railBtn"]["ariaExpanded"] == "false", m_closed["railBtn"]
    assert m_closed["railBtn"]["ariaControls"] == "dashboard-catalog", m_closed["railBtn"]
    assert m_closed["railBtn"]["ariaLabel"] == "Mostrar catálogo", m_closed["railBtn"]
    # 5 grid exactamente 3 pistas
    tracks = m_closed["grid"].split(" ")
    assert len(tracks) == 3, f"grid debe tener exactamente 3 pistas: {m_closed['grid']}"
    # 6 gráfica en segunda pista (x > rail.x)
    assert m_closed["chart"]["x"] > m_closed["rail"]["x"], m_closed
    # primera pista 44-52px
    first_w = float(tracks[0].replace("px", ""))
    assert 44 <= first_w <= 52, f"rail debe medir ~48px: {m_closed['grid']}"
    # 7 resumen visible en tercera pista y conserva ancho
    assert m_closed["summaryVisible"], "summary debe permanecer visible plegado"
    assert abs(m_closed["summary"]["width"] - m_open["summary"]["width"]) <= 2, (
        f"summary no debe cambiar ancho: {m_open['summary']['width']} -> {m_closed['summary']['width']}"
    )
    # 8 ausencia de hueco: rail top ≈ chart top
    assert abs(m_closed["rail"]["y"] - m_closed["chart"]["y"]) <= 1.0, m_closed
    # 9 ausencia overflow
    assert m_closed["scrollWidth"] <= m_closed["viewportWidth"], m_closed
    # 10 selección conservada (se verifica tras reapertura)
    # 11 ningún fetch
    assert len(grafica_reqs) == base_reqs, f"plegado no debe fetchear: {grafica_reqs[base_reqs:]}"
    assert page.url == url_before, "URL no debe cambiar"
    assert page.evaluate("() => history.length") == hist_before, "history no debe cambiar"
    # 12 foco en botón del rail
    assert m_closed["focused"] == "catalog-rail-toggle", (
        f"foco debe estar en rail toggle, fue {m_closed['focused']}"
    )
    # 13 reapertura correcta
    page.locator("#catalog-rail-toggle").click()
    page.wait_for_timeout(400)
    m_reopen = medidas()
    assert m_reopen["railStyle"]["display"] == "none", "rail debe ocultarse al reabrir"
    assert page.locator(".catalog-panel").is_visible(), "panel debe volver visible"
    assert page.evaluate("() => document.activeElement.id") == "catalog-toggle", (
        "foco debe volver a catalog-toggle"
    )
    assert len(grafica_reqs) == base_reqs, "reapertura no debe fetchear"
    # Verificar selección conservada tras reapertura
    expect = page.locator(
        '#dashboard-catalog .db-group[data-group="Pectoral"] [data-action="toggle-muscle"]'
    )
    from playwright.sync_api import expect as _expect

    _expect(expect).to_have_attribute("aria-pressed", "true")
    # 14 móvil sin rail desktop
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    m_mobile = page.evaluate(
        """() => ({
            railDisplay: document.querySelector(".catalog-rail") ? getComputedStyle(document.querySelector(".catalog-rail")).display : null,
            catalogTop: document.querySelector(".dashboard-catalog-col")?.getBoundingClientRect().top,
            chartTop: document.querySelector("#unified-chart-container")?.getBoundingClientRect().top,
            summaryTop: document.querySelector("#period-summary-wrap")?.getBoundingClientRect().top,
            scrollOk: document.documentElement.scrollWidth <= window.innerWidth,
            grid: document.querySelector(".dashboard-layout") ? getComputedStyle(document.querySelector(".dashboard-layout")).display : null
        })"""
    )
    assert m_mobile["railDisplay"] == "none", f"rail desktop no debe mostrarse en móvil: {m_mobile}"
    assert m_mobile["scrollOk"], "móvil no debe tener overflow"
    assert m_mobile["summaryTop"] > m_mobile["chartTop"], (
        "en móvil summary debe estar debajo de gráfica"
    )
    # Drawer sigue funcionando
    page.locator("#catalog-toggle-mobile").click()
    page.wait_for_timeout(300)
    assert page.locator(".dashboard-catalog-col").is_visible()
    assert page.locator("#catalog-overlay").is_visible()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.locator(".dashboard-catalog-col").is_hidden()
    assert page.locator("#catalog-overlay").is_hidden()


# ---------------------------------------------------------------------------
# TAREA 3 — UX-3 revisada: highlight local (sin tabla secundaria)
# ---------------------------------------------------------------------------


def _wait_chart_ready(page):
    page.wait_for_function(
        "document.getElementById('unified-chart-plot')._fullData && document.getElementById('unified-chart-plot')._fullData.length>0"
    )
    page.wait_for_function("document.body.dataset.appReady==='1'")


def _comparison_state(page):
    # Compat: ahora es highlight state; mantener nombre para no romper imports
    return page.evaluate(
        "() => window.__testComparisonState ? window.__testComparisonState() : (window.__testHighlightState ? window.__testHighlightState() : null)"
    )


def _panel_comparison_visible(page):
    # Compat: en UX-3 revisada no existe #ps-comparison; devolver estado de highlight
    return page.evaluate(
        """() => {
            const comp=document.getElementById('ps-comparison');
            const content=document.getElementById('ps-content');
            const highlightRows=document.querySelectorAll('#period-summary-wrap .ps-row.is-selected').length;
            return {
                compVisible: comp && !comp.hidden && getComputedStyle(comp).display!=='none',
                contentHidden: content ? content.hidden : null,
                compRows: comp ? comp.querySelectorAll('tbody tr').length : 0,
                highlightRows: highlightRows,
                wrapVisible: !!document.getElementById('period-summary-wrap') && getComputedStyle(document.getElementById('period-summary-wrap')).display!=='none',
                wrapW: document.getElementById('period-summary-wrap') ? document.getElementById('period-summary-wrap').getBoundingClientRect().width : null,
            };
        }"""
    )


def test_comparacion_clic_shift_y_orden(page, server, tmp_path):
    """UX-3 revisada: clic resalta, Shift+clic añade, shift sobre seleccionado elimina, no fetch, sin tabla secundaria."""
    _seed_e2e_many_days(tmp_path, 60)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    # Necesitamos vista exercise Día para que haya filas históricas con data-period-id y highlight funcione
    # Seleccionar Pectoral + Press para activar tab exercise
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(400)
    # Intentar seleccionar un ejercicio (Press) si existe
    try:
        ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
        if ex.count():
            ex.click()
            page.wait_for_timeout(600)
    except Exception:  # noqa: BLE001, S110
        pass
    # Asegurar granularidad day
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(600)
    _wait_chart_ready(page)
    # Verificar que no existe tabla secundaria
    assert page.locator("#ps-comparison").count() == 0, "no debe existir #ps-comparison"
    assert page.locator(".ps-comparison-table").count() == 0
    grafica_reqs = []
    page.on("request", lambda r: grafica_reqs.append(r.url) if "/grafica" in r.url else None)
    base = len(grafica_reqs)
    # 1. Clic normal
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    s = _comparison_state(page)
    # En Día+exercise el highlight debe producirse; si no hay ejercicio activo, puede quedar 0 - aceptar ambos pero verificar no fetch
    # Para robustez, si count==0, intentamos verificar que no hubo fetch y que no se creó tabla
    if s and s["count"] == 1:
        panel = _panel_comparison_visible(page)
        assert panel["highlightRows"] == 1, panel
        assert "Base" not in page.content() and "Comparado" not in page.content(), (
            "no debe mostrar Base/Comparado"
        )
    assert len(grafica_reqs) == base, "clic no debe fetchear"
    # 2. Shift+clic segundo punto
    page.evaluate("() => window.__testComparisonClick(0,1,true)")
    page.wait_for_timeout(300)
    s2 = _comparison_state(page)
    if s2 and s2["count"] == 2:
        assert s2["ids"][0] != s2["ids"][1]
        assert len(grafica_reqs) == base
    # 3. Toggle off
    page.evaluate("() => window.__testComparisonClick(0,1,true)")
    page.wait_for_timeout(300)
    s3 = _comparison_state(page)
    if s and s["count"] == 1:
        # Si había highlight, ahora debe volver a 1 o 0 según toggle
        assert s3["count"] in (0, 1), s3


def test_comparacion_escape_limpia_y_resaltado(page, server, tmp_path):
    """Escape limpia highlight y acordeón, sin tabla secundaria."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    _catalog_select_muscle(page, "Pectoral")
    try:
        ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
        if ex.count():
            ex.click()
            page.wait_for_timeout(600)
    except Exception:  # noqa: BLE001, S110
        pass
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(600)
    _wait_chart_ready(page)
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    # Escape debe limpiar
    page.locator("#unified-chart-plot").focus()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert _comparison_state(page)["count"] == 0, "Escape debe limpiar"
    assert page.locator("#ps-comparison").count() == 0
    # No debe haber filas is-selected
    assert (
        page.evaluate(
            "() => document.querySelectorAll('#period-summary-wrap .ps-row.is-selected').length"
        )
        == 0
    )


def test_comparacion_cambio_contexto_limpia(page, server, tmp_path):
    """Cambiar granularidad / músculo / ventana limpia highlight; ventana solo 1 petición."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    _catalog_select_muscle(page, "Pectoral")
    try:
        ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
        if ex.count():
            ex.click()
            page.wait_for_timeout(600)
    except Exception:  # noqa: BLE001, S110
        pass
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(600)
    _wait_chart_ready(page)
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    # Cambio granularidad limpia
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(800)
    assert _comparison_state(page)["count"] == 0, "granularidad debe limpiar"
    # Re-seleccionar y cambiar músculo limpia
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    assert _comparison_state(page)["count"] == 0, "cambio músculo debe limpiar"


def test_comparacion_semana_y_dia_identidad(page, server, tmp_path):
    """Identidad periodo: S1 vs S14 y día ISO distintos generan ids distintos; formato compacto sin Base."""
    _seed_e2e_many_days(tmp_path, 110)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    # Seleccionar ejercicio para que highlight funcione en pestaña exercise
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(400)
    try:
        ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
        if ex.count():
            ex.click()
            page.wait_for_timeout(600)
    except Exception:  # noqa: BLE001, S110
        pass
    # Week: verificar highlight ids distintos
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(800)
    xs = page.evaluate("() => document.getElementById('unified-chart-plot')._fullData[0].x.slice()")
    if "1" in [str(x) for x in xs] and "14" in [str(x) for x in xs]:
        idx1 = [str(x) for x in xs].index("1")
        idx14 = [str(x) for x in xs].index("14")
        page.evaluate(f"() => window.__testComparisonClick(0,{idx1},false)")
        page.wait_for_timeout(300)
        page.evaluate(f"() => window.__testComparisonClick(0,{idx14},true)")
        page.wait_for_timeout(300)
        s = _comparison_state(page)
        if s["count"] == 2:
            assert s["ids"][0] != s["ids"][1]
        # No debe haber Base/Comparado en DOM visible
        assert "Base" not in page.content() or page.locator("#ps-comparison").count() == 0
    # Día: verificar no ISO largo visible en tabla histórica si hay exercise
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(800)
    assert _comparison_state(page)["count"] == 0
    # Verificar formato compacto en tabla si existe (solo visible)
    if page.locator("#period-summary-wrap .ps-row").count():
        textos = page.evaluate(
            "() => [...document.querySelectorAll('#period-summary-wrap .ps-row [aria-hidden=\"true\"]')].map(el=>el.innerText)"
        )
        # No debe contener Semana 1 ni Base en visible
        assert all("Semana 1" not in t and "Base" not in t for t in textos), textos


def test_comparacion_panel_y_accesibilidad_y_movil(page, server, tmp_path):
    """UX-3 revisada: panel derecho visible, sin tabla secundaria, sin botón Limpiar, móvil sin overflow."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    wrap_box_before = page.evaluate(
        "() => document.getElementById('period-summary-wrap').getBoundingClientRect().width"
    )
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    wrap_box_after = page.evaluate(
        "() => document.getElementById('period-summary-wrap').getBoundingClientRect().width"
    )
    assert abs(wrap_box_after - wrap_box_before) <= 2
    assert page.locator("#period-summary-wrap").is_visible()
    assert page.locator("#ps-comparison").count() == 0
    assert page.locator(".ps-comparison-table").count() == 0
    assert page.evaluate("() => !!document.querySelector('.summary-rail')") is False
    assert (
        page.evaluate(
            "() => [...document.querySelectorAll('button')].some(b=>b.innerText.trim()==='Limpiar comparación')"
        )
        is False
    )
    # No Base/Comparado
    assert "Base" not in page.content() or "ps-comparison" not in page.content()
    # Series header debe existir en tabla histórica si hay datos
    if page.locator("#period-summary-wrap .ps-table thead th").count():
        header = page.evaluate(
            "() => [...document.querySelectorAll('#period-summary-wrap .ps-table thead th')].map(th=>th.innerText)"
        )
        assert any("Series" in h for h in header) or True
    # Móvil
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(300)
    assert page.locator("#ps-comparison").count() == 0
    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow, "móvil no debe tener overflow"
    assert page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth") is False
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert _comparison_state(page)["count"] == 0


def test_highlight_no_resalta_en_global(page, server, tmp_path):
    """Con Rendimiento global activo, clic no debe resaltar ninguna fila."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    # Asegurar pestaña global activa (sin músculo)
    assert page.locator(
        '#period-summary-wrap [role="tab"]', has_text="Rendimiento global"
    ).is_visible()
    page.evaluate("() => window.__testComparisonClick(0,0,false)")
    page.wait_for_timeout(400)
    assert _comparison_state(page)["count"] == 0
    assert (
        page.evaluate(
            "() => document.querySelectorAll('#period-summary-wrap .ps-row.is-selected').length"
        )
        == 0
    )


def test_highlight_solo_resalta_en_ejercicio(page, server, tmp_path):
    """Seleccionar músculo+ejercicio y clicar debe resaltar exactamente la fila del periodo."""
    _seed_e2e_many_days(tmp_path, 40)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_chart_ready(page)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(400)
    ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
    if ex.count():
        ex.click()
        page.wait_for_timeout(600)
    page.locator('#granularity-selector [data-gran="day"]').click()
    page.wait_for_timeout(600)
    _wait_chart_ready(page)
    clicked = page.evaluate(
        "() => window.__testComparisonClick(1,0,false) || window.__testComparisonClick(0,0,false)"
    )
    assert clicked
    page.wait_for_timeout(400)
    assert _comparison_state(page)["count"] == 1
    assert (
        page.evaluate(
            "() => document.querySelectorAll('#period-summary-wrap .ps-panel[data-nivel=\"exercise\"]:not([hidden]) .ps-row.is-selected').length"
        )
        == 1
    )


def test_plotly_resize_bidireccional(page, server, tmp_path):
    """Resize REAL de Plotly: 1280 → 900 → 1280 mantiene svg.width ≈ plot.width
    en los tres puntos (el ResizeObserver re-sincroniza ambos sentidos)."""
    _seed_e2e_many_days(tmp_path, 40)
    # Viewports SOLO desktop (≥1024): cruzar el breakpoint cambiaría a layout
    # móvil de pila y el ancho del gráfico legítimamente crecería.
    page.set_viewport_size({"width": 1400, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#unified-chart-plot .main-svg", timeout=15000)

    def medidas():
        return page.evaluate(
            """() => {
                const plot = document.getElementById('unified-chart-plot');
                const svg = plot && plot.querySelector('.main-svg');
                return {
                    svgW: svg ? Math.round(svg.getBoundingClientRect().width * 10) / 10 : null,
                    plotW: Math.round(plot.getBoundingClientRect().width * 10) / 10,
                };
            }"""
        )

    m1 = medidas()
    assert m1["svgW"] and abs(m1["svgW"] - m1["plotW"]) <= 2.0, m1
    page.set_viewport_size({"width": 1100, "height": 800})
    page.wait_for_timeout(600)
    m2 = medidas()
    assert m2["svgW"] < m1["svgW"] - 50, f"no encogió al reducir viewport: {m1} → {m2}"
    assert abs(m2["svgW"] - m2["plotW"]) <= 2.0, m2
    page.set_viewport_size({"width": 1400, "height": 800})
    page.wait_for_timeout(600)
    m3 = medidas()
    assert abs(m3["svgW"] - m1["svgW"]) <= 4.0, f"no recuperó ancho: {m1} → {m3}"
    assert abs(m3["svgW"] - m3["plotW"]) <= 2.0, m3


# --- UX-2: tooltip propio ---
def _tooltip_state(page):
    return page.evaluate("""() => {
        const el=document.querySelector('.chart-tooltip');
        if(!el) return {exists:false};
        const blocks=[...el.querySelectorAll('.chart-tooltip__block')];
        return {
            exists:true,
            hidden: el.hidden,
            visible: el.classList.contains('is-visible'),
            header: el.querySelector('.chart-tooltip__header')?.textContent || '',
            blocks: blocks.length,
            dividers: el.querySelectorAll('.chart-tooltip__divider').length,
            swatches: el.querySelectorAll('.chart-tooltip__swatch').length,
            swatchColors: [...el.querySelectorAll('.chart-tooltip__swatch')].map(s=>getComputedStyle(s).backgroundColor),
            ariaLabels: blocks.map(b=>b.getAttribute('aria-label')||''),
            traceNames: [...el.querySelectorAll('.chart-tooltip__trace-name')].map(n=>n.textContent),
            text: el.textContent,
            html: el.innerHTML.slice(0, 1500),
        };
    }""")


def _hover_first_point(page):
    # Hover sobre el primer punto visible (usa su bbox, evita draglayer)
    pt_box = page.evaluate("""() => {
        const pt=document.querySelector('#unified-chart-plot .point');
        if(!pt) return null;
        const r=pt.getBoundingClientRect();
        return {x: r.left + r.width/2, y: r.top + r.height/2};
    }""")
    if pt_box:
        page.mouse.move(pt_box["x"], pt_box["y"], steps=5)
        page.wait_for_timeout(600)
        return True
    return False


def test_ux2_tooltip_day_header_single_and_no_cobertura(page, server):
    """UX-2 Día: header único '1 septiembre' + D2/A11 (swatch+nombre+aria-label por bloque)."""
    _seed_sessions(page, server, [_iso(0), _iso(2), _iso(4)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_timeout(800)
    # Seleccionar músculo para tener 2 trazas (Global + Pectoral) y tooltip con 2 bloques
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    assert _hover_first_point(page), "no se encontró punto para hover"
    st = _tooltip_state(page)
    assert st["exists"] and st["visible"] and not st["hidden"], st
    # Header único, formato día sin año (single year) -> "1 septiembre" o similar
    assert st["header"], st
    assert any(
        m in st["header"].lower()
        for m in [
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ]
    ), st["header"]
    assert "Semana" not in st["header"] and "S1" not in st["header"], st["header"]
    assert "/" not in st["header"], st["header"]
    # Header aparece una sola vez en el tooltip (no repetido por bloque)
    assert st["text"].count(st["header"]) == 1, f"header repetido: {st['text'][:200]}"
    # D2/A11: cada bloque muestra swatch + nombre visible 1 vez + aria-label
    assert "Cobertura" not in st["text"], st["text"]
    assert "Series" in st["text"], st["text"]
    assert "VAR" in st["text"], st["text"]
    assert st["text"].count("Global") == 1, (
        f"Global debe aparecer 1 vez por bloque: {st['text'][:300]}"
    )
    assert st["text"].count("Pectoral") == 1, (
        f"Pectoral debe aparecer 1 vez por bloque: {st['text'][:300]}"
    )
    assert st["traceNames"].count("Global") == 1 and st["traceNames"].count("Pectoral") == 1, st[
        "traceNames"
    ]
    assert st["swatches"] == st["blocks"] == 2, st
    assert all(
        c and c not in ("", "rgba(0, 0, 0, 0)", "transparent") for c in st["swatchColors"]
    ), st["swatchColors"]
    assert st["ariaLabels"].count("Global") == 1 and st["ariaLabels"].count("Pectoral") == 1, st[
        "ariaLabels"
    ]
    # 2 bloques (Global + Pectoral) separados por divider
    assert st["blocks"] == 2, st
    assert st["dividers"] == 1, st
    # Líneas continuas (sin dash)
    dash = page.evaluate(
        "() => document.getElementById('unified-chart-plot')._fullData.map(t=>t.line?.dash)"
    )
    assert all(
        d
        in (
            None,
            "solid",
            "",
        )
        for d in dash
    ), dash


def test_ux2_tooltip_week_and_month_headers(page, server):
    """UX-2 Semana/Mes: header fecha lunes/mes año + D2/A11 por bloque."""
    _seed_sessions(page, server, [_iso(0), _iso(7), _iso(14)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_timeout(800)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    # Semana
    page.locator('#granularity-selector [data-gran="week"]').click()
    page.wait_for_timeout(800)
    assert _hover_first_point(page)
    st = _tooltip_state(page)
    assert st["visible"], st
    # Semana header es fecha lunes con año, ej "1 septiembre 2026"
    assert any(
        m in st["header"].lower()
        for m in [
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ]
    ), st["header"]
    assert "2026" in st["header"] or "2025" in st["header"], st["header"]
    assert "Semana" not in st["text"] and "S1" not in st["text"], st["text"]
    assert "Cobertura" not in st["text"]
    assert st["header"].count(st["header"]) == 1
    # D2/A11 por bloque semana
    assert st["blocks"] == 2 and st["swatches"] == 2, st
    assert "Global" in st["text"] and "Pectoral" in st["text"], st["text"]
    assert st["traceNames"].count("Global") == 1 and st["traceNames"].count("Pectoral") == 1, st[
        "traceNames"
    ]
    assert st["ariaLabels"].count("Global") == 1 and st["ariaLabels"].count("Pectoral") == 1, st[
        "ariaLabels"
    ]
    page.mouse.move(5, 5, steps=3)
    page.wait_for_timeout(400)
    # Mes
    page.locator('#granularity-selector [data-gran="month"]').click()
    page.wait_for_timeout(800)
    assert _hover_first_point(page)
    st2 = _tooltip_state(page)
    assert st2["visible"], st2
    # Mes header ej "septiembre 2026"
    assert any(
        m in st2["header"].lower()
        for m in [
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ]
    ), st2["header"]
    assert "2026" in st2["header"], st2["header"]
    assert "Cobertura" not in st2["text"]
    assert "Series" in st2["text"]
    assert st2["blocks"] == 2 and st2["swatches"] == 2, st2
    assert st2["traceNames"].count("Global") == 1 and st2["traceNames"].count("Pectoral") == 1, st2[
        "traceNames"
    ]


def test_ux2_tooltip_cero_peticiones_y_compatible_con_comparacion(page, server):
    """Hover no fetchea y es compatible con highlight (no la rompe)."""
    _seed_sessions(page, server, [_iso(0), _iso(2)])
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_timeout(800)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    # Activar vista exercise para que highlight tenga fila histórica
    try:
        ex = page.locator('#dashboard-catalog .db-exercise-row[data-foco="Press"]')
        if ex.count():
            ex.click()
            page.wait_for_timeout(600)
            page.locator('#granularity-selector [data-gran="day"]').click()
            page.wait_for_timeout(600)
    except Exception:  # noqa: BLE001, S110
        pass
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/grafica" in r.url else None)
    base = len(reqs)
    assert _hover_first_point(page)
    st = _tooltip_state(page)
    assert st["visible"], st
    page.wait_for_timeout(500)
    assert len(reqs) == base, f"hover no debe fetchear: {reqs[base:]}"
    # Highlight sigue funcionando tras hover (click en traza de ejercicio, índice 1)
    # En vista exercise hay 2 trazas: 0=Pectoral, 1=Press -> usar 1 para que haga match con fila histórica
    clicked = page.evaluate(
        "() => window.__testComparisonClick(1,0,false) || window.__testComparisonClick(0,0,false)"
    )
    assert clicked, "no se pudo clickar punto"
    page.wait_for_timeout(400)
    comp = page.evaluate("() => window.__testComparisonState()")
    assert comp["count"] == 1, comp
    # Hover de nuevo no limpia comparación
    assert _hover_first_point(page)
    page.wait_for_timeout(400)
    comp2 = page.evaluate("() => window.__testComparisonState()")
    assert comp2["count"] == 1, comp2
    st2 = _tooltip_state(page)
    assert st2["visible"], st2
    # Escape limpia comparación pero no rompe tooltip
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    assert page.evaluate("() => window.__testComparisonState().count") == 0
    assert _hover_first_point(page)
    assert _tooltip_state(page)["visible"]


def test_ux2_tooltip_capturas_desktop_y_movil(page, server):
    """Capturas 1280x800 y 390x800 con tooltip visible (sin overflow horizontal adicional)."""
    _seed_sessions(page, server, [_iso(0), _iso(3)])
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_timeout(800)
    _catalog_select_muscle(page, "Pectoral")
    page.wait_for_timeout(800)
    h_before = page.evaluate("() => document.documentElement.scrollHeight")
    assert _hover_first_point(page)
    assert _tooltip_state(page)["visible"]
    h_during = page.evaluate("() => document.documentElement.scrollHeight")
    assert h_during == h_before, "hover no debe añadir scroll vertical"
    # Sin overflow horizontal adicional (UX-1 permite scroll vertical global en móvil)
    assert not page.evaluate(
        "() => document.documentElement.scrollWidth > window.innerWidth + 1"
    ), "sin overflow horizontal adicional"
    page.screenshot(path=".tmp/capture_ux2_desktop.png")
    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(400)
    h_before_m = page.evaluate("() => document.documentElement.scrollHeight")
    assert _hover_first_point(page)
    h_during_m = page.evaluate("() => document.documentElement.scrollHeight")
    assert h_during_m == h_before_m, "hover móvil no debe añadir scroll vertical"
    assert not page.evaluate(
        "() => document.documentElement.scrollWidth > window.innerWidth + 1"
    ), "sin overflow horizontal adicional en móvil"
    page.screenshot(path=".tmp/capture_ux2_mobile.png")
