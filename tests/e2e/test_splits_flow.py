"""Browser tests for the split manager (SortableJS DnD, shift-copy, day-copy).

Contrato: 1 instancia colocada = 1 serie; arrastre normal mueve, Shift duplica;
el handle del día copia el bloque completo con Shift. El DnD usa SortableJS:
los tests arrastran con mouse real (patrón _drag_row_up de test_dashboard_flow).
"""

from playwright.sync_api import expect


def _box(page, selector):
    return page.locator(selector).first.bounding_box()


def _goto_splits(page, server):
    # Viewport alto: el board (arriba) y el catálogo (abajo) deben ser visibles
    # a la vez para que los arrastres por coordenadas de mouse funcionen.
    page.set_viewport_size({"width": 1280, "height": 1700})
    page.goto(server + "/splits")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#split-board .split-day-zone", timeout=5000)


def _mouse_drag_shift(page, src_sel, dst_x, dst_y, steps=8):
    """Drag de mouse real con Shift (duplicación por puntero del app).

    El modo Shift no usa Sortable (handler propio de mousedown/mousemove/
    mouseup): los pasos se espacian para que el seguimiento sea estable.
    """
    src = _box(page, src_sel)
    assert src, f"origen no encontrado: {src_sel}"
    page.keyboard.down("Shift")
    sx = src["x"] + src["width"] / 2
    sy = src["y"] + src["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(sx + (dst_x - sx) * i / steps, sy + (dst_y - sy) * i / steps)
        page.wait_for_timeout(60)
    page.mouse.up()
    page.keyboard.up("Shift")
    page.wait_for_timeout(300)


def _drag_to_element(page, src_sel, target_sel, target_position):
    """Drag CDP nativo (drag_to) sobre un elemento destino con posición
    relativa: es el mecanismo fiable de inserción exacta de SortableJS."""
    page.locator(src_sel).drag_to(page.locator(target_sel), target_position=target_position)
    page.wait_for_timeout(300)


def _drag_from_catalog(page, ejercicio, day, y_offset=None):
    """Arrastra un chip del catálogo (abriendo su grupo) al día destino.

    El drop termina DENTRO de la mitad inferior de la última tarjeta (o en el
    interior de la lista si el día está vacío): Sortable solo inserta mientras
    el puntero está sobre una tarjeta; si el puntero acaba fuera, mantiene la
    última posición procesada.
    """
    chip = f'.split-catalog-chip[data-ejercicio="{ejercicio}"]'
    if page.locator(chip).is_hidden():
        group = page.locator(f".split-catalog-group:has({chip})")
        summary = group.locator("summary")
        if summary.is_visible():
            summary.click()
            page.wait_for_timeout(100)
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    n = page.locator(f"{list_sel} .split-item-card").count()
    if n:
        # Mitad inferior de la última tarjeta: Sortable inserta al final.
        _drag_to_element(
            page, chip, f"{list_sel} .split-item-card:nth-child({n})", {"x": 10, "y": 28}
        )
    else:
        _drag_to_element(page, chip, list_sel, {"x": 10, "y": 4})


def _drag_to_position(page, item_sel, day, index, shift=False):
    """Arrastra el item a la posición `index` (0=primero, >=len=final) del día."""
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    n = page.locator(f"{list_sel} .split-item-card").count()
    if shift:
        # Duplicación: drag por puntero con Shift (sin Sortable).
        if index >= n:
            box = _box(page, list_sel)
            _mouse_drag_shift(page, item_sel, box["x"] + 20, box["y"] + max(10, box["height"] - 6))
        else:
            anchor = _box(page, f"{list_sel} .split-item-card:nth-child({index + 1})")
            _mouse_drag_shift(page, item_sel, anchor["x"] + anchor["width"] / 2, anchor["y"] + 2)
        return
    if index >= n:
        if n:
            _drag_to_element(
                page, item_sel, f"{list_sel} .split-item-card:nth-child({n})", {"x": 10, "y": 28}
            )
        else:
            _drag_to_element(page, item_sel, list_sel, {"x": 10, "y": 4})
    else:
        _drag_to_element(
            page, item_sel, f"{list_sel} .split-item-card:nth-child({index + 1})", {"x": 10, "y": 2}
        )


def _drag_to_day_at(page, item_sel, day, index=None, shift=False):
    """Arrastra el item al día destino; si `index` es int, posición exacta."""
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    if shift:
        if index is None:
            n = page.locator(f"{list_sel} .split-item-card").count()
            if n:
                last = _box(page, f"{list_sel} .split-item-card:nth-child({n})")
                _mouse_drag_shift(
                    page, item_sel, last["x"] + last["width"] / 2, last["y"] + last["height"] - 6
                )
            else:
                list_box = _box(page, list_sel)
                _mouse_drag_shift(
                    page,
                    item_sel,
                    list_box["x"] + list_box["width"] / 2,
                    list_box["y"] + max(10, list_box["height"] - 10),
                )
        else:
            anchor = _box(page, f"{list_sel} .split-item-card:nth-child({index + 1})")
            _mouse_drag_shift(page, item_sel, anchor["x"] + anchor["width"] / 2, anchor["y"] + 2)
        return
    if index is None:
        n = page.locator(f"{list_sel} .split-item-card").count()
        if n:
            _drag_to_element(
                page, item_sel, f"{list_sel} .split-item-card:nth-child({n})", {"x": 10, "y": 28}
            )
        else:
            _drag_to_element(page, item_sel, list_sel, {"x": 10, "y": 4})
    else:
        _drag_to_element(
            page, item_sel, f"{list_sel} .split-item-card:nth-child({index + 1})", {"x": 10, "y": 2}
        )


def _card_names(page, day):
    return page.locator(
        f'.split-day-zone[data-day="{day}"] .split-item-card .split-item-name'
    ).all_inner_texts()


def _open_details(page, group):
    page.locator(f'.split-catalog-group[data-group="{group}"] summary').click()
    page.wait_for_timeout(80)


def test_splits_page_loads(page, server):
    _goto_splits(page, server)
    expect(page.locator("h1")).to_contain_text("Gestor de splits")
    # Layout escritorio: catálogo sticky a la izquierda, editor a la derecha.
    layout = page.evaluate(
        """() => {
            const cat = document.querySelector('.splits-catalog-col');
            const ed = document.querySelector('.splits-editor-col');
            return {
                sticky: getComputedStyle(cat).position,
                catLeft: cat.getBoundingClientRect().left < ed.getBoundingClientRect().left,
                catWidth: cat.getBoundingClientRect().width,
            };
        }"""
    )
    assert layout["sticky"] == "sticky", layout
    assert layout["catLeft"], layout
    assert 260 <= layout["catWidth"] <= 340, layout
    expect(page.locator("#split-summary-panel")).to_be_visible()
    # Catálogo agrupado y cerrado.
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).to_be_visible()
    expect(page.locator('.split-catalog-group[data-group="HIIT"]')).to_be_visible()
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).not_to_have_attribute(
        "open", ""
    )
    # Chips sin texto de grupo y tarjetas sin grupo.
    expect(page.locator('.split-catalog-chip[data-ejercicio="Press"]')).to_contain_text("Press")
    assert (
        page.locator('.split-catalog-chip[data-ejercicio="Press"]').evaluate(
            "el => el.textContent.trim()"
        )
        == "Press"
    )
    # 7 zonas + handle de copia por día.
    expect(page.locator(".split-day-copy-handle")).to_have_count(7)


def test_catalogo_desplegable_y_busqueda(page, server):
    _goto_splits(page, server)
    _open_details(page, "Pectoral")
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).to_have_attribute(
        "open", ""
    )
    expect(page.locator('.split-catalog-chip[data-ejercicio="Press"]')).to_be_visible()
    # Búsqueda filtra y abre los grupos con resultados.
    page.fill("#split-catalog-search", "curl")
    expect(page.locator('.split-catalog-group[data-group="Biceps"]')).to_have_attribute("open", "")
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).to_be_hidden()
    # Vaciar restaura el estado cerrado.
    page.fill("#split-catalog-search", "")
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).to_be_visible()
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).not_to_have_attribute(
        "open", ""
    )


def test_drag_repetido_cuenta_series(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(2)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("2 series")
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 2 series")

    _drag_from_catalog(page, "HIIT", "MARTES")
    expect(page.locator('.split-day-zone[data-day="MARTES"] .split-item-card')).to_have_count(1)
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 3 series")
    # Resumen por ejercicio y por día.
    expect(page.locator("#split-summary-week")).to_contain_text("Curl", timeout=3000)
    expect(page.locator("#split-summary-days")).to_contain_text("Lunes — 2 series")
    expect(page.locator("#split-summary-days")).to_contain_text("Martes — 1 series")


def test_resumen_sin_conteos_auxiliares(page, server):
    _goto_splits(page, server)
    expect(page.locator("#split-summary-week")).not_to_contain_text("Días activos")
    expect(page.locator("#split-summary-week")).not_to_contain_text("Ejercicios distintos")
    # Los 7 días aparecen aunque estén vacíos.
    expect(page.locator("#split-summary-days")).to_contain_text("Domingo — 0 series")


def test_agregar_boton_alternativa_accesible(page, server):
    _goto_splits(page, server)
    _open_details(page, "Pectoral")
    chip = page.locator('.split-catalog-chip[data-ejercicio="Press"]')
    chip.click()
    chip.click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(2)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("2 series")


def test_reordenar_y_eliminar(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    assert _card_names(page, "LUNES") == ["Curl", "Press"]

    # Mover Press al primer lugar (arrastre normal = mover).
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "LUNES",
        0,
    )
    assert _card_names(page, "LUNES") == ["Press", "Curl"]

    # Eliminar una instancia.
    page.locator(
        '.split-day-zone[data-day="LUNES"] [data-action="split-item-remove"]'
    ).first.click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(1)


def test_insercion_posicion_exacta(page, server):
    _goto_splits(page, server)
    for ej in ("Press", "Curl", "Press", "Curl"):
        _drag_from_catalog(page, ej, "LUNES")
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press", "Curl"]
    # Soltar la última tarjeta entre las posiciones 1 y 2 → posición 2.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card:nth-child(4)',
        "LUNES",
        1,
    )
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Curl", "Press"]
    # Soltar la primera tarjeta al final → posición final.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card:nth-child(1)',
        "LUNES",
        99,
    )
    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Press", "Press"]


def test_mover_entre_dias(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    # Mover Press de LUNES a MARTES sin Shift: se mueve, no duplica.
    _drag_to_day_at(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "MARTES",
        index=None,
    )
    assert _card_names(page, "LUNES") == ["Curl"]
    assert _card_names(page, "MARTES") == ["Press"]


def test_shift_copia_dentro_del_mismo_dia(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")  # Isquio → Press
    _drag_from_catalog(page, "Curl", "LUNES")
    assert _card_names(page, "LUNES") == ["Press", "Curl"]
    # Shift + arrastrar Press debajo de Curl → copia, original permanece.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "LUNES",
        99,
        shift=True,
    )
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press"]
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("3 series")


def test_shift_copia_entre_dias_con_dia_destino_correcto(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    # Shift + arrastrar Press a JUEVES: original permanece en LUNES.
    _drag_to_day_at(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "JUEVES",
        index=None,
        shift=True,
    )
    assert _card_names(page, "LUNES") == ["Press", "Curl"]
    assert _card_names(page, "JUEVES") == ["Press"]
    # La copia tiene el día destino real.
    dia = page.evaluate(
        """() => document.querySelector('.split-day-zone[data-day="JUEVES"] .split-item-card').dataset.dia"""
    )
    assert dia == "JUEVES"
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 3 series")


def test_shift_copia_posicion_exacta(page, server):
    _goto_splits(page, server)
    for ej in ("Press", "Curl", "HIIT"):
        _drag_from_catalog(page, ej, "LUNES")
    assert _card_names(page, "LUNES") == ["Press", "Curl", "HIIT"]
    # Shift + soltar Press entre Curl(2) y HIIT(3) → posición 3 (0-based 2).
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]:nth-child(1)',
        "LUNES",
        2,
        shift=True,
    )
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press", "HIIT"]


def test_day_copy_con_shift(page, server):
    _goto_splits(page, server)
    for ej in ("Press", "Curl", "HIIT"):
        _drag_from_catalog(page, ej, "LUNES")
    # Copiar LUNES → JUEVES con Shift desde el handle.
    handle = '.split-day-zone[data-day="LUNES"] .split-day-copy-handle'
    zone = _box(page, '.split-day-zone[data-day="JUEVES"]')
    _mouse_drag_shift(page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10)
    # LUNES intacto, JUEVES con el mismo contenido y orden.
    assert _card_names(page, "LUNES") == ["Press", "Curl", "HIIT"]
    assert _card_names(page, "JUEVES") == ["Press", "Curl", "HIIT"]
    # Todas las copias tienen dia=JUEVES.
    dias = page.evaluate(
        """() => [...document.querySelectorAll('.split-day-zone[data-day="JUEVES"] .split-item-card')]
            .map(c => c.dataset.dia)"""
    )
    assert dias == ["JUEVES", "JUEVES", "JUEVES"]
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 6 series")
    expect(page.locator("#split-summary-days")).to_contain_text("Jueves — 3 series")


def test_day_copy_sobre_dia_ocupado_no_reemplaza(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "JUEVES")
    handle = '.split-day-zone[data-day="LUNES"] .split-day-copy-handle'
    zone = _box(page, '.split-day-zone[data-day="JUEVES"]')
    _mouse_drag_shift(page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10)
    assert _card_names(page, "JUEVES") == ["HIIT", "Press"]


def test_day_copy_handle_sin_shift_no_hace_nada(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    zone = _box(page, '.split-day-zone[data-day="JUEVES"]')
    page.mouse.move(zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10)
    page.mouse.down()
    page.mouse.move(zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10, steps=4)
    page.mouse.up()
    page.wait_for_timeout(200)
    expect(page.locator('.split-day-zone[data-day="JUEVES"] .split-item-card')).to_have_count(0)
    assert _card_names(page, "LUNES") == ["Press"]


def test_guardar_recargar_abrir_conserva_estado(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    # Shift-copy y day-copy antes de guardar.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "LUNES",
        99,
        shift=True,
    )
    handle = '.split-day-zone[data-day="LUNES"] .split-day-copy-handle'
    zone = _box(page, '.split-day-zone[data-day="VIERNES"]')
    _mouse_drag_shift(page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10)

    page.fill("#split-nombre", "Push Pull Legs")
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split guardado.", timeout=3000
    )

    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    # El split guardado abre en modo visualización: "Editar" lo habilita.
    page.click('[data-action="split-edit-open"]')
    page.wait_for_selector('.split-day-zone[data-day="LUNES"] .split-item-card', timeout=3000)
    page.wait_for_selector('#split-board-week[data-editmode="1"]', timeout=3000)
    expect(page.locator("#split-board-week")).to_have_attribute("data-editmode", "1")

    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Press", "Press"]
    assert _card_names(page, "MARTES") == ["HIIT"]
    assert _card_names(page, "VIERNES") == ["Curl", "Curl", "Press", "Press"]
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("4 series")
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 9 series")


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


def test_editar_activa_modo_edicion(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    page.fill("#split-nombre", "Con Editar")
    page.click('[data-action="split-save"]')
    expect(page.locator("#splits-list .card")).to_have_count(1, timeout=3000)

    # Abrir un split guardado: modo visualización (sin controles, drag inerte).
    page.goto(server + "/splits?abrir=1")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector('#split-board-week[data-editmode="0"]', timeout=3000)
    expect(page.locator("#split-board-week .row-btn").first).to_be_hidden()
    # En modo visualización el drag no mueve nada (ni siquiera a otro día).
    _drag_to_day_at(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "MARTES",
    )
    assert _card_names(page, "LUNES") == ["Press"]
    assert _card_names(page, "MARTES") == []

    # "Editar" activa el modo edición.
    page.click('[data-action="split-edit"]')
    expect(page.locator("#split-board-week")).to_have_attribute("data-editmode", "1")
    expect(page.locator("#split-board-week .row-btn").first).to_be_visible()
    # Agregar desde el catálogo y marcar modificado.
    _drag_from_catalog(page, "Curl", "LUNES")
    assert _card_names(page, "LUNES") == ["Press", "Curl"]
    expect(page.locator("#split-dirty-hint")).to_be_visible()
    # Guardar persiste y vuelve a modo visualización.
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split actualizado.", timeout=3000
    )
    page.wait_for_selector('#split-board-week[data-editmode="0"]', timeout=3000)
    expect(page.locator("#split-dirty-hint")).to_be_hidden()
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="split-edit-open"]')
    page.wait_for_selector('#split-board-week:has-text("Con Editar")', timeout=3000)
    assert _card_names(page, "LUNES") == ["Press", "Curl"]


def test_borrar_dia_con_confirmacion(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("2 series")

    # Cancelar no borra.
    page.click('.split-day-zone[data-day="LUNES"] [data-action="split-day-clear"]')
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-cancel").click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(2)

    # Confirmar borra solo el lunes.
    page.click('.split-day-zone[data-day="LUNES"] [data-action="split-day-clear"]')
    page.locator("#confirm-save").click()
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(0)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("0 series")
    assert _card_names(page, "MARTES") == ["HIIT"]
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 1 series")
    expect(page.locator("#split-dirty-hint")).to_be_visible()

    # Guardar y recargar: lunes sigue vacío.
    page.fill("#split-nombre", "Día borrado")
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split guardado.", timeout=3000
    )
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="split-edit-open"]')
    page.wait_for_selector('#split-board-week:has-text("Día borrado")', timeout=3000)
    assert _card_names(page, "LUNES") == []
    assert _card_names(page, "MARTES") == ["HIIT"]


def test_layout_movil_apilado(page, server):
    page.set_viewport_size({"width": 600, "height": 1200})
    page.goto(server + "/splits")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    layout = page.evaluate(
        """() => {
            const cat = document.querySelector('.splits-catalog-col');
            const ed = document.querySelector('.splits-editor-col');
            return {
                direction: getComputedStyle(document.querySelector('.splits-layout')).flexDirection,
                editorAbove: ed.getBoundingClientRect().top < cat.getBoundingClientRect().top,
                sticky: getComputedStyle(cat).position,
            };
        }"""
    )
    assert layout["direction"] == "column", layout
    assert layout["editorAbove"], layout
    assert layout["sticky"] != "sticky", layout


def test_flujo_completo_navegador(page, server):
    """Los 9 pasos del requerimiento: click, drag, drag repetido, mover,
    mover a otro día, Shift duplicar, guardar, recargar, abrir."""
    _goto_splits(page, server)
    # 1. Click en un ejercicio del catálogo.
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    # 2-3. Arrastrar dos veces el mismo ejercicio al lunes.
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    expect(page.locator('.split-day-zone[data-day="LUNES"] .split-item-card')).to_have_count(3)
    # 4. Moverlo dentro del lunes.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "LUNES",
        0,
    )
    assert _card_names(page, "LUNES")[0] == "Press"
    # 5. Moverlo de lunes a jueves.
    _drag_to_day_at(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Press"]',
        "JUEVES",
    )
    assert _card_names(page, "JUEVES") == ["Press"]
    # 6. Duplicar con Shift.
    _drag_to_position(
        page,
        '.split-day-zone[data-day="LUNES"] .split-item-card[data-ejercicio="Curl"]:nth-child(1)',
        "LUNES",
        99,
        shift=True,
    )
    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Curl"]
    # 7-9. Guardar, recargar, abrir.
    page.fill("#split-nombre", "Flujo completo")
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split guardado.", timeout=3000
    )
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="split-edit-open"]')
    page.wait_for_selector('#split-board-week:has-text("Flujo completo")', timeout=3000)
    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Curl"]
    assert _card_names(page, "JUEVES") == ["Press"]
    expect(page.locator("#split-summary-week")).to_contain_text("Semana — 4 series")
