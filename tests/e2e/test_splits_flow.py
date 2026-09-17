"""Browser tests for the split manager v5 (acordeón full-width + tarjetas de
día de dimensiones invariantes, SortableJS DnD, shift-copy, day-copy, undo).

Contrato: 1 instancia colocada = 1 serie; arrastre normal mueve, Shift duplica;
el handle del día copia el bloque completo con Shift; los items guardados
arrancan colapsados en modo visualización y "Editar" habilita la edición; los
OOB de sección NO deben perder las ediciones no guardadas de otros items.

Helpers por item: los drags de construcción operan sobre el item editable
(`[data-editmode="1"]`); las asserts de vista pasan el item explícitamente.
"""

import re

from playwright.sync_api import expect


def _box(loc):
    return loc.bounding_box()


def _goto_splits(page, server):
    # Viewport alto: los boards (en la columna derecha) y el catálogo sticky
    # (izquierda) deben ser visibles a la vez para los drags por coordenadas.
    page.set_viewport_size({"width": 1280, "height": 1700})
    page.goto(server + "/splits")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#splits-section", timeout=5000)


def _editable(page):
    return page.locator('.split-accordion-item[data-editmode="1"]')


def _item(page, idx=0):
    return page.locator(".split-accordion-item").nth(idx)


def _item_by_name(page, nombre):
    return (
        page.locator(".split-accordion-item")
        .filter(has=page.locator(".split-accordion-name", has_text=nombre))
        .first
    )


def _open_item(page, item):
    details = item.locator("details.split-accordion")
    if not details.evaluate("el => el.open"):
        item.locator("summary.split-accordion-summary").click()
        page.wait_for_timeout(120)


def _toggle_item(page, item):
    item.locator("summary.split-accordion-summary").click()
    page.wait_for_timeout(120)


def _nuevo(page):
    page.click('[data-action="split-new"]')
    page.wait_for_selector('.split-accordion-item[data-editmode="1"]', timeout=3000)
    page.wait_for_timeout(100)


def _dias(page, item=None):
    scope = item or _editable(page)
    return scope.locator(".split-day-zone")


def _list(page, day, item=None):
    scope = item or _editable(page)
    return scope.locator(f'.split-day-zone[data-day="{day}"] .split-day-items')


def _cards(page, day, item=None):
    return _list(page, day, item).locator(".split-item-card")


def _card_names(page, day, item=None):
    return _list(page, day, item).locator(".split-item-card .split-item-name").all_inner_texts()


def _mouse_drag(page, src, dst_x, dst_y, steps=8):
    """Drag de mouse real SIN Shift (SortableJS forceFallback: mode fallback)."""
    src_box = _box(src)
    assert src_box, f"origen no encontrado: {src}"
    sx = src_box["x"] + src_box["width"] / 2
    sy = src_box["y"] + src_box["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(sx + (dst_x - sx) * i / steps, sy + (dst_y - sy) * i / steps)
        page.wait_for_timeout(60)
    page.mouse.up()
    page.wait_for_timeout(300)


def _mouse_drag_shift(page, src, dst_x, dst_y, steps=8):
    """Drag de mouse real con Shift (duplicación por puntero del app)."""
    src_box = _box(src)
    assert src_box, f"origen no encontrado: {src}"
    page.keyboard.down("Shift")
    sx = src_box["x"] + src_box["width"] / 2
    sy = src_box["y"] + src_box["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(sx + (dst_x - sx) * i / steps, sy + (dst_y - sy) * i / steps)
        page.wait_for_timeout(60)
    page.mouse.up()
    page.keyboard.up("Shift")
    page.wait_for_timeout(300)


def _target_abs(page, target, target_position):
    box = _box(target)
    assert box, f"destino no encontrado: {target}"
    return box["x"] + target_position["x"], box["y"] + target_position["y"]


def _drag_to_element(page, src, target, target_position):
    """Drag por mouse (fallback de SortableJS) sobre un destino con posición."""
    dx, dy = _target_abs(page, target, target_position)
    _mouse_drag(page, src, dx, dy)


def _drag_from_catalog(page, ejercicio, day, item=None):
    """Arrastra un chip del catálogo (abriendo su grupo) al día del item."""
    scope = item or _editable(page)
    chip_sel = f'.split-catalog-chip[data-ejercicio="{ejercicio}"]'
    chip = page.locator(chip_sel)
    if chip.is_hidden():
        g = page.locator(f".split-catalog-group:has({chip_sel})")
        if g.locator("summary").is_visible():
            g.locator("summary").click()
            page.wait_for_timeout(100)
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    n = _cards(page, day, item).count()
    if n:
        target = scope.locator(f"{list_sel} .split-item-card:nth-child({n})")
        _drag_to_element(page, chip, target, {"x": 20, "y": 24})
    else:
        _drag_to_element(page, chip, scope.locator(list_sel), {"x": 20, "y": 6})


def _drag_to_position(page, item_sel, day, index, shift=False, item=None):
    scope = item or _editable(page)
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    n = _cards(page, day, item).count()
    src = scope.locator(item_sel)
    if shift:
        if index >= n:
            box = _box(scope.locator(list_sel))
            _mouse_drag_shift(page, src, box["x"] + 20, box["y"] + max(10, box["height"] - 8))
        else:
            anchor = _box(scope.locator(f"{list_sel} .split-item-card:nth-child({index + 1})"))
            _mouse_drag_shift(page, src, anchor["x"] + anchor["width"] / 2, anchor["y"] + 4)
        return
    if index >= n:
        if n:
            _drag_to_element(
                page,
                src,
                scope.locator(f"{list_sel} .split-item-card:nth-child({n})"),
                {"x": 20, "y": 24},
            )
        else:
            _drag_to_element(page, src, scope.locator(list_sel), {"x": 20, "y": 6})
    else:
        _drag_to_element(
            page,
            src,
            scope.locator(f"{list_sel} .split-item-card:nth-child({index + 1})"),
            {"x": 20, "y": 4},
        )


def _drag_to_day_at(page, item_sel, day, index=None, shift=False, item=None):
    scope = item or _editable(page)
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    src = scope.locator(item_sel)
    if shift:
        n = _cards(page, day, item).count()
        if n:
            last = _box(scope.locator(f"{list_sel} .split-item-card:nth-child({n})"))
            _mouse_drag_shift(
                page, src, last["x"] + last["width"] / 2, last["y"] + last["height"] - 8
            )
        else:
            lb = _box(scope.locator(list_sel))
            _mouse_drag_shift(
                page, src, lb["x"] + lb["width"] / 2, lb["y"] + max(10, lb["height"] - 10)
            )
        return
    if index is None:
        n = _cards(page, day, item).count()
        if n:
            _drag_to_element(
                page,
                src,
                scope.locator(f"{list_sel} .split-item-card:nth-child({n})"),
                {"x": 20, "y": 24},
            )
        else:
            _drag_to_element(page, src, scope.locator(list_sel), {"x": 20, "y": 6})
    else:
        _drag_to_element(
            page,
            src,
            scope.locator(f"{list_sel} .split-item-card:nth-child({index + 1})"),
            {"x": 20, "y": 4},
        )


def _save(page, nombre, item=None):
    scope = item or _editable(page)
    scope.locator('input[name="nombre"]').fill(nombre)
    save_btn = scope.locator('[data-action="split-save"]')
    expect(save_btn).to_be_enabled()
    save_btn.click()
    expect(page.locator("#notice-container .notice-success").first).to_contain_text(
        "Split", timeout=4000
    )
    page.wait_for_selector('.split-accordion-item[data-editmode="0"]', timeout=3000)
    page.wait_for_timeout(150)


def _open_details(page, group):
    g = page.locator(f'.split-catalog-group[data-group="{group}"]')
    if not g.evaluate("el => el.open"):
        g.locator("summary").click()
        page.wait_for_timeout(80)


def _no_overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def _card_rect(page, day, item=None):
    scope = item or _editable(page)
    return scope.locator(f'.split-day-zone[data-day="{day}"]').bounding_box()


# --------------------------------------------------------------------------- #
# Estructura, overflow, acordeón y estado vacío
# --------------------------------------------------------------------------- #


def test_pagina_estructura_sin_overflow(page, server):
    _goto_splits(page, server)
    # Estado vacío: solo CTA, sin letrero.
    expect(page.locator("#splits-section")).not_to_contain_text("Todavía no hay splits guardados")
    expect(page.locator('#splits-section [data-action="split-new"]')).to_be_visible()
    # Sin panel ledger v3 ni página fragmento.
    expect(page.locator("#split-summary-panel")).to_have_count(0)
    # Catálogo a la izquierda (sticky) de la columna de splits.
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
    # Contrato Fase 2-layout: el catálogo comparte el token compacto
    # --split-catalog-w = clamp(232px, 18vw, 260px) (antes fijo 280px).
    assert 230 <= layout["catWidth"] <= 300, layout
    # Grupos del catálogo cerrados por defecto, sin título de panel.
    expect(page.locator('.split-catalog-group[data-group="Pectoral"]')).not_to_have_attribute(
        "open", ""
    )
    assert "Catálogo de ejercicios" not in page.content()
    # La página usa el ancho disponible sin overflow horizontal.
    assert _no_overflow(page)


def test_nuevo_split_desde_estado_vacio_y_guardar(page, server):
    _goto_splits(page, server)
    page.click('#splits-section [data-action="split-new"]')
    page.wait_for_selector('.split-accordion-item[data-editmode="1"]', timeout=3000)
    # Item nuevo editable: open, 7 tarjetas y nombre enfocado.
    expect(_dias(page)).to_have_count(7)
    expect(page.locator('input[name="nombre"]')).to_be_focused()
    # Agregar por clic al día seleccionado (LUNES por defecto) y guardar.
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    expect(_cards(page, "LUNES")).to_have_count(1)
    _save(page, "Mi split")
    # Tras guardar: el item queda en modo visualización.
    expect(_item(page, 0)).to_have_attribute("data-editmode", "0")
    expect(_item(page, 0).locator(".split-accordion-name")).to_contain_text("Mi split")
    # Recargar: persiste y arranca colapsado (modo vista).
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#splits-section")).to_contain_text("Mi split")
    assert page.locator("details.split-accordion[open]").count() == 0


def test_acordeon_colapsado_e_independiente(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _cards(page, "LUNES")
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    _save(page, "A")
    _nuevo(page)
    _open_details(page, "Biceps")
    page.locator('.split-catalog-chip[data-ejercicio="Curl"]').click()
    _save(page, "B")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    assert page.locator("details.split-accordion[open]").count() == 0
    itemA = _item_by_name(page, "A")
    itemB = _item_by_name(page, "B")
    # Expandir A no abre B.
    _open_item(page, itemA)
    expect(page.locator("details.split-accordion[open]")).to_have_count(1)
    expect(itemB.locator("details.split-accordion")).not_to_have_attribute("open", "")
    # Expandir B: ambos abiertos; cerrar A: solo B visible.
    _open_item(page, itemB)
    expect(page.locator("details.split-accordion[open]")).to_have_count(2)
    _toggle_item(page, itemA)
    expect(page.locator("details.split-accordion[open]")).to_have_count(1)
    expect(itemB.locator("details.split-accordion")).to_have_attribute("open", "")


# --------------------------------------------------------------------------- #
# Tarjetas de dimensiones invariantes y resumen jerárquico
# --------------------------------------------------------------------------- #


def test_tarjeta_dimensiones_invariantes(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _save(page, "Dim")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Dim")
    _open_item(page, item)

    def rect():
        return _card_rect(page, "LUNES", item=item)

    def panel_rect():
        return item.locator(".split-accordion-content").bounding_box()

    base = rect()
    assert base, "tarjeta LUNES no visible"
    panel_base = panel_rect()
    assert panel_base
    # Entrar en modo edición no cambia el tamaño (tarjeta ni panel).
    item.locator('[data-action="split-edit"]').click()
    expect(item).to_have_attribute("data-editmode", "1")
    after_edit = rect()
    assert abs(after_edit["width"] - base["width"]) < 0.5
    assert abs(after_edit["height"] - base["height"]) < 0.5
    panel_edit = panel_rect()
    assert abs(panel_edit["height"] - panel_base["height"]) < 0.5
    # Expandir un grupo del resumen no cambia el tamaño.
    item.locator('.split-summary-group-toggle[data-summary-group="Pectoral"]').click()
    expect(
        item.locator('.split-summary-group-toggle[data-summary-group="Pectoral"]')
    ).to_have_attribute("aria-expanded", "true")
    after_group = rect()
    assert after_group["height"] == base["height"]
    # Agregar una instancia no cambia el tamaño.
    _open_details(page, "Biceps")
    page.locator('.split-catalog-chip[data-ejercicio="Curl"]').click()
    expect(_cards(page, "LUNES", item=item)).to_have_count(3)
    after_add = rect()
    assert after_add["height"] == base["height"] and after_add["width"] == base["width"]
    # Colapsar y reabrir el split: mismo tamaño.
    _open_item(page, item)
    _open_item(page, item)
    re_open = rect()
    assert re_open["height"] == base["height"]
    # Guardar: el item vuelve a vista con el mismo tamaño de tarjeta.
    _save(page, "Dim", item=item)
    expect(item).to_have_attribute("data-editmode", "0")
    after_save = rect()
    assert after_save["height"] == base["height"] and after_save["width"] == base["width"]


def test_panel_mas_alto(page, server):
    """El panel expandido debe ser más alto que en v4 (tarjetas >= 600px)."""
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Alto")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Alto")
    _open_item(page, item)
    h = _card_rect(page, "LUNES", item=item)["height"]
    assert h >= 600, f"tarjeta demasiado baja: {h}"


def test_resumen_jerarquico_por_tarjeta(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    _save(page, "Resumen")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Resumen")
    _open_item(page, item)
    _open_details(page, "Pectoral")
    item.locator('[data-action="split-edit"]').click()
    page.wait_for_timeout(100)
    # Total del día en el header de la tarjeta; resumen con grupos colapsados.
    expect(item.locator('[data-day-count="LUNES"]')).to_contain_text("3 series")
    expect(item.locator('[data-day-count="MARTES"]')).to_contain_text("1 serie")
    peek = item.locator('.split-summary-group-toggle[data-summary-group="Pectoral"]')
    expect(peek).to_have_attribute("aria-expanded", "false")
    # Los ejercicios de los grupos colapsados están en el DOM pero ocultos.
    expect(item.locator(".split-summary-exercise")).to_have_count(3)
    assert item.locator(".split-summary-exercise:visible").count() == 0
    # Expandir Pectoral muestra sus ejercicios con totales.
    peek.click()
    expect(peek).to_have_attribute("aria-expanded", "true")
    expect(item.locator(".split-summary-exercise").filter(has_text="Press")).to_be_visible()
    expect(item.locator(".split-summary-exercise").filter(has_text="Press")).to_contain_text(
        "2 series"
    )
    expect(item.locator(".split-summary-exercise").filter(has_text="Curl")).to_be_hidden()
    # Copiar un grupo igual en MARTES (HIIT) existe.
    expect(
        item.locator('.split-summary-group-toggle[data-summary-group="HIIT"]')
    ).to_have_attribute("aria-expanded", "false")


# --------------------------------------------------------------------------- #
# DnD estándar (SortableJS) y alternativas accesibles
# --------------------------------------------------------------------------- #


def test_dnd_reordenar_y_eliminar(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    assert _card_names(page, "LUNES") == ["Curl", "Press"]
    # Arrastre normal = mover.
    _drag_to_position(page, '.split-item-card[data-ejercicio="Press"]', "LUNES", 0)
    assert _card_names(page, "LUNES") == ["Press", "Curl"]
    # Eliminar una instancia.
    _cards(page, "LUNES").locator('[data-action="split-item-remove"]').first.click()
    expect(_cards(page, "LUNES")).to_have_count(1)


def test_insercion_posicion_exacta(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    for ej in ("Press", "Curl", "Press", "Curl"):
        _drag_from_catalog(page, ej, "LUNES")
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press", "Curl"]
    _drag_to_position(page, ".split-item-card:nth-child(4)", "LUNES", 1)
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Curl", "Press"]
    _drag_to_position(page, ".split-item-card:nth-child(1)", "LUNES", 99)
    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Press", "Press"]


def test_mover_entre_dias(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_to_day_at(page, '.split-item-card[data-ejercicio="Press"]', "MARTES")
    assert _card_names(page, "LUNES") == ["Curl"]
    assert _card_names(page, "MARTES") == ["Press"]


def test_shift_duplica_instancia(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    # Mismo día al final: original permanece.
    _drag_to_position(page, '.split-item-card[data-ejercicio="Press"]', "LUNES", 99, shift=True)
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press"]
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("3 series")
    # Entre días: JUEVES recibe la copia, LUNES intacto.
    _drag_to_day_at(page, '.split-item-card[data-ejercicio="Curl"]', "JUEVES", shift=True)
    assert _card_names(page, "LUNES") == ["Press", "Curl", "Press"]
    assert _card_names(page, "JUEVES") == ["Curl"]


def test_day_move_header_sin_shift(page, server):
    """¿Mover el día completo desde el header sin Shift: bloque a VIERNES."""
    _goto_splits(page, server)
    _nuevo(page)
    for ej in ("Press", "Curl", "HIIT"):
        _drag_from_catalog(page, ej, "LUNES")
    header = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="VIERNES"]'))
    _mouse_drag(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    # Origen vacío, destino con el bloque en orden, total constante.
    assert _card_names(page, "LUNES") == []
    assert _card_names(page, "VIERNES") == ["Press", "Curl", "HIIT"]
    dias = page.evaluate(
        """() => [...document.querySelectorAll('.split-day-zone[data-day="VIERNES"] .split-item-card')]
            .map(c => c.dataset.dia)"""
    )
    assert dias == ["VIERNES", "VIERNES", "VIERNES"]
    expect(page.locator('[data-day-count="VIERNES"]')).to_have_text("3 series")
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("0 series")


def test_day_copy_header_con_shift(page, server):
    """Shift + arrastrar el header: el origen conserva y el destino recibe."""
    _goto_splits(page, server)
    _nuevo(page)
    for ej in ("Press", "Curl", "HIIT"):
        _drag_from_catalog(page, ej, "LUNES")
    header = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="JUEVES"]'))
    _mouse_drag_shift(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    assert _card_names(page, "LUNES") == ["Press", "Curl", "HIIT"]
    assert _card_names(page, "JUEVES") == ["Press", "Curl", "HIIT"]
    dias = page.evaluate(
        """() => [...document.querySelectorAll('.split-day-zone[data-day="JUEVES"] .split-item-card')]
            .map(c => c.dataset.dia)"""
    )
    assert dias == ["JUEVES", "JUEVES", "JUEVES"]
    expect(page.locator('[data-day-count="JUEVES"]')).to_have_text("3 series")


def test_day_move_sobre_dia_ocupado_no_reemplaza(page, server):
    """El día-drag a un día con ejercicios inserta sin reemplazar (append)."""
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "VIERNES")
    header = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="VIERNES"]'))
    _mouse_drag(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    assert _card_names(page, "LUNES") == []
    # VIERNES conserva HIIT y recibe Press (append si cae sobre el header).
    assert _card_names(page, "VIERNES") == ["HIIT", "Press"]


def test_day_move_dia_vacio_no_inicia(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    header = _editable(page).locator('.split-day-zone[data-day="MARTES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="VIERNES"]'))
    _mouse_drag(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    expect(_cards(page, "VIERNES")).to_have_count(0)
    expect(page.locator("#notice-container .notice-error")).to_be_visible()


def test_day_copy_limite_rechaza_origen_intacto(page, server):
    """El límite (data-max-items) se respeta y el origen queda intacto."""
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "LUNES")
    _drag_from_catalog(page, "Curl", "MARTES")
    page.evaluate("""() => {
        const item = document.querySelector('.split-accordion-item[data-editmode="1"]');
        item.dataset.maxItems = '2';
    }""")
    header = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="VIERNES"]'))
    _mouse_drag_shift(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    # Rechazo: origen intacto, destino vacío, aviso de límite.
    assert _card_names(page, "LUNES") == ["Press", "HIIT"]
    expect(_cards(page, "VIERNES")).to_have_count(0)
    expect(page.locator("#notice-container .notice-error")).to_be_visible()


def test_clic_y_teclado_agregar(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _open_details(page, "Pectoral")
    chip = page.locator('.split-catalog-chip[data-ejercicio="Press"]')
    chip.click()
    expect(_cards(page, "LUNES")).to_have_count(1)
    # Seleccionar MARTES y agregar por clic al día seleccionado.
    _editable(page).locator('[data-action="split-day-select"][data-day="MARTES"]').click()
    chip.click()
    expect(_cards(page, "MARTES")).to_have_count(1)
    expect(_cards(page, "LUNES")).to_have_count(1)
    # Teclado: Enter en el chip agrega al día seleccionado actual.
    page.locator('[data-action="split-day-select"][data-day="VIERNES"]').click()
    chip.focus()
    page.keyboard.press("Enter")
    expect(_cards(page, "VIERNES")).to_have_count(1)


# --------------------------------------------------------------------------- #
# Guardas (A1/A3) y flujos de persistencia/undo
# --------------------------------------------------------------------------- #


def test_drag_a_split_no_editable_no_muta(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Vista")
    # Item editable (nuevo) junto al guardado en modo vista: abrir el item en
    # vista para que su board sea un destino VISIBLE (aunque no editable).
    vista = _item_by_name(page, "Vista")
    _open_item(page, vista)
    _nuevo(page)
    _drag_from_catalog(page, "Curl", "LUNES")

    def intenta(src, target, pos):
        # Con forceFallback el drag es por puntero; el board en vista (Sortable
        # deshabilitado) nunca recibe el drop. No muta nada.
        _drag_to_element(page, src, target, pos)

    target = vista.locator('.split-day-zone[data-day="LUNES"] .split-day-items')
    # Arrastrar una instancia del item editable al board en vista: no muta.
    a_first = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-item-card').first
    intenta(a_first, target, {"x": 10, "y": 8})
    # Vista conserva solo su Press original; el item editable conserva su Curl.
    expect(_cards(page, "LUNES", item=vista)).to_have_count(1)
    assert _card_names(page, "LUNES", item=vista) == ["Press"]
    expect(_cards(page, "LUNES")).to_have_count(1)
    assert _card_names(page, "LUNES") == ["Curl"]
    # Arrastrar del catálogo a la vista: tampoco muta.
    _open_details(page, "Biceps")
    intenta(
        page.locator('.split-catalog-chip[data-ejercicio="Curl"]'),
        target,
        {"x": 10, "y": 8},
    )
    expect(_cards(page, "LUNES", item=vista)).to_have_count(1)
    assert _card_names(page, "LUNES", item=vista) == ["Press"]


def test_click_sin_split_editable_muestra_aviso(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    _save(page, "X")
    # Todo en vista: el clic no agrega y muestra un aviso.
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    page.wait_for_timeout(150)
    expect(_cards(page, "LUNES", item=_item(page, 0))).to_have_count(1)
    expect(page.locator("#notice-container .notice-error")).to_be_visible()


def test_edicion_simultanea_conserva_no_guardado(page, server):
    """A1: guardar un item no debe destruir las ediciones sin guardar de otro."""
    _goto_splits(page, server)
    # Split A persistido.
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "A")
    # Item nuevo B con cambios locales sin guardar.
    _nuevo(page)
    _drag_from_catalog(page, "Curl", "MARTES")
    # Guardar A de nuevo mientras B tiene cambios: A necesita una mutación
    # (Guardar está deshabilitado sin cambios).
    itemA = _item_by_name(page, "A")
    _open_item(page, itemA)
    itemA.locator('[data-action="split-edit"]').click()
    _open_details(page, "Biceps")
    page.locator('.split-catalog-chip[data-ejercicio="Curl"]').click()
    expect(_cards(page, "LUNES", item=itemA)).to_have_count(2)
    itemA.locator('[data-action="split-save"]').click()
    expect(page.locator("#notice-container .notice-success").first).to_contain_text(
        "Split actualizado.", timeout=4000
    )
    # B conserva su edición no guardada (MARTES con Curl + hint de modificado).
    b = page.locator('.split-accordion-item[data-split-id=""]')
    expect(b).to_have_attribute("data-editmode", "1")
    expect(_cards(page, "MARTES", item=b)).to_have_count(1)
    expect(b.locator("[data-split-dirty-hint]")).to_be_visible()
    assert _card_names(page, "MARTES", item=b) == ["Curl"]
    # Guardar B: ambos persisten.
    b.locator('input[name="nombre"]').fill("B")
    save_b = b.locator('[data-action="split-save"]')
    expect(save_b).to_be_enabled()
    save_b.click()
    expect(page.locator("#notice-container .notice-success").first).to_contain_text(
        "Split guardado.", timeout=4000
    )
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    itemB = _item_by_name(page, "B")
    _open_item(page, itemB)
    assert _card_names(page, "MARTES", item=itemB) == ["Curl"]


def test_guardar_recargar_conserva_estado(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    _drag_to_position(page, '.split-item-card[data-ejercicio="Press"]', "LUNES", 99, shift=True)
    header = _editable(page).locator('.split-day-zone[data-day="LUNES"] .split-day-header')
    zone = _box(_editable(page).locator('.split-day-zone[data-day="VIERNES"]'))
    _mouse_drag_shift(page, header, zone["x"] + zone["width"] / 2, zone["y"] + 10)
    _save(page, "Push Pull Legs")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Push Pull Legs")
    _open_item(page, item)
    item.locator('[data-action="split-edit"]').click()
    expect(item).to_have_attribute("data-editmode", "1")
    assert _card_names(page, "LUNES", item=item) == ["Curl", "Curl", "Press", "Press"]
    assert _card_names(page, "MARTES", item=item) == ["HIIT"]
    assert _card_names(page, "VIERNES", item=item) == ["Curl", "Curl", "Press", "Press"]
    expect(item.locator('[data-day-count="LUNES"]')).to_have_text("4 series")


def test_borrar_dia_con_confirmacion(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Curl", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    # Cancelar no borra.
    _editable(page).locator('[data-action="split-day-clear"][data-day="LUNES"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-cancel").click()
    expect(_cards(page, "LUNES")).to_have_count(2)
    # Confirmar borra solo el lunes.
    _editable(page).locator('[data-action="split-day-clear"][data-day="LUNES"]').click()
    page.locator("#confirm-save").click()
    expect(_cards(page, "LUNES")).to_have_count(0)
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("0 series")
    assert _card_names(page, "MARTES") == ["HIIT"]
    expect(_editable(page).locator("[data-split-dirty-hint]")).to_be_visible()
    # Guardar y recargar: lunes sigue vacío.
    _save(page, "Día borrado")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Día borrado")
    _open_item(page, item)
    item.locator('[data-action="split-edit"]').click()
    page.wait_for_timeout(100)
    assert _card_names(page, "LUNES", item=item) == []
    assert _card_names(page, "MARTES", item=item) == ["HIIT"]


def test_eliminar_split_con_confirmacion(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Temporal")
    item = _item_by_name(page, "Temporal")
    _open_item(page, item)
    item.locator('[data-action="split-delete"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    page.locator("#confirm-save").click()
    expect(page.locator('#splits-empty [data-action="split-new"]')).to_be_visible(timeout=4000)


def test_ctrlz_no_restaura_split_guardado(page, server):
    """R1: Ctrl+Z fuera de edición no revierte un split guardado (sin /undo)."""
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Undoable")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#splits-section")).to_contain_text("Undoable")
    posts = []

    def _spy(r):
        if r.method == "POST" and r.url.endswith("/undo"):
            posts.append(r.url)

    page.on("request", _spy)
    page.keyboard.press("Control+z")
    page.wait_for_timeout(400)
    expect(page.locator("#splits-section")).to_contain_text("Undoable")
    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"


# --------------------------------------------------------------------------- #
# Responsive y anchos
# --------------------------------------------------------------------------- #


def test_layout_movil_sin_overflow(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Movil")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(200)
    layout = page.evaluate(
        """() => {
            const cat = document.querySelector('.splits-catalog-col');
            const ed = document.querySelector('.splits-editor-col');
            const board = document.querySelector('#splits-section .split-accordion-item .split-board-scroll');
            return {
                direction: getComputedStyle(document.querySelector('.splits-layout')).flexDirection,
                editorAbove: ed.getBoundingClientRect().top < cat.getBoundingClientRect().top,
                sticky: getComputedStyle(cat).position,
                boardScrolls: board.scrollWidth > board.clientWidth,
            };
        }"""
    )
    assert layout["direction"] == "column", layout
    assert layout["editorAbove"], layout
    assert layout["sticky"] != "sticky", layout
    # El scroll horizontal queda EN el board; la página no deja de caber.
    assert layout["boardScrolls"], "el board debería scrollear horizontalmente en móvil"
    assert _no_overflow(page)


def test_desktop_1920_caben_7_dias(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Wide")
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(200)
    item = _item_by_name(page, "Wide")
    _open_item(page, item)
    board = item.locator(".split-board-scroll")
    fits = board.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    assert fits, "en 1920 los 7 días deben caber sin scroll del board"
    assert _no_overflow(page)
    layout = page.evaluate(
        """() => document.querySelector('.splits-catalog-col')
            .getBoundingClientRect().left
            < document.querySelector('.splits-editor-col').getBoundingClientRect().left"""
    )
    assert layout


def test_item_guardado_sube_al_tope(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Primero")
    _nuevo(page)
    _drag_from_catalog(page, "Curl", "LUNES")
    _save(page, "Reciente")
    # El más recientemente actualizado va al tope de la lista.
    expect(page.locator(".split-accordion-name").first).to_contain_text("Reciente")
    expect(page.locator(".split-accordion-name").nth(1)).to_contain_text("Primero")


# --------------------------------------------------------------------------- #
# v5: cabecera con resumen semanal, iconos agrupados y columnas full-width
# --------------------------------------------------------------------------- #


def test_header_resumen_semanal_sin_fecha(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "MARTES")
    _save(page, "Semanal")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Semanal")
    _open_item(page, item)
    strip = item.locator(".split-summary-strip")
    # Resumen semanal junto al nombre: total + grupos ordenados por series.
    expect(strip).to_contain_text("3 series")
    expect(strip).to_contain_text("Pectoral 2")
    expect(strip).to_contain_text("HIIT 1")
    # Scroll horizontal interno del strip (no rompe el layout).
    assert strip.evaluate("el => getComputedStyle(el).overflowX") == "auto"
    # Sin fecha ni texto "actualizado" en la sección.
    section_text = page.locator("#splits-section").inner_text()
    assert "actualizado" not in section_text
    assert not re.search(r"\d{2}/\d{2} \d{2}:\d{2}", section_text)
    assert _no_overflow(page)


def test_acciones_iconos_agrupados(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Iconos")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Iconos")
    _open_item(page, item)
    actions = item.locator(".split-item-actions .split-action-btn")
    expect(actions).to_have_count(4)
    # Misma fila y orden: check-actual < lápiz < guardar < papelera.
    tops = actions.evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().top))")
    assert len(set(tops)) == 1, tops
    xs = actions.evaluate_all("els => els.map(e => Math.round(e.getBoundingClientRect().left))")
    assert xs == sorted(xs), xs
    # aria-labels y tooltips completos.
    expect(actions.nth(0)).to_have_attribute("aria-label", "Marcar como split actual")
    expect(actions.nth(1)).to_have_attribute("aria-label", "Editar el split")
    expect(actions.nth(2)).to_have_attribute("aria-label", "Guardar el split")
    expect(actions.nth(3)).to_have_attribute("aria-label", "Eliminar el split")
    expect(actions.nth(1)).to_have_attribute("title", "Editar el split")
    # Guardar deshabilitado en vista, mismo box tras Editar y tras mutar.
    save_btn = actions.nth(2)
    expect(save_btn).to_be_disabled()
    box_off = save_btn.bounding_box()
    item.locator('[data-action="split-edit"]').click()
    expect(item).to_have_attribute("data-editmode", "1")
    expect(save_btn).to_be_disabled()
    box_edit = save_btn.bounding_box()
    assert abs(box_edit["width"] - box_off["width"]) < 0.5
    assert abs(box_edit["height"] - box_off["height"]) < 0.5
    _open_details(page, "Pectoral")
    page.locator('.split-catalog-chip[data-ejercicio="Press"]').click()
    expect(save_btn).to_be_enabled()
    box_on = save_btn.bounding_box()
    assert abs(box_on["width"] - box_off["width"]) < 0.5
    assert abs(box_on["height"] - box_off["height"]) < 0.5


def test_split_actual_primero_abierto_y_persiste(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "SplitA")
    _nuevo(page)
    _drag_from_catalog(page, "Press", "VIERNES")
    _save(page, "SplitB")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item_b = _item_by_name(page, "SplitB")
    _open_item(page, item_b)
    item_b.locator('[data-action="split-activate"]').click()
    expect(page.locator('.split-accordion-item[data-active="1"]')).to_have_count(1)
    # Tras activar, el actual queda primero y abierto.
    first = page.locator("#splits-list .split-accordion-item").first
    expect(first).to_have_attribute("data-active", "1")
    expect(first.locator("details.split-accordion")).to_have_js_property("open", True)
    # Persiste tras recargar.
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    first = page.locator("#splits-list .split-accordion-item").first
    expect(first).to_have_attribute("data-active", "1")
    expect(first.locator("details.split-accordion")).to_have_js_property("open", True)


def test_columnas_ancho_completo_sin_hueco(page, server):
    _goto_splits(page, server)
    _nuevo(page)
    _drag_from_catalog(page, "Press", "LUNES")
    _save(page, "Columnas")
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    item = _item_by_name(page, "Columnas")
    _open_item(page, item)
    for width in (1440, 1920):
        page.set_viewport_size({"width": width, "height": 1000})
        page.wait_for_timeout(250)
        zones = item.locator(".split-day-zone")
        widths = zones.evaluate_all(
            "els => els.map(e => Math.round(e.getBoundingClientRect().width))"
        )
        assert len(set(widths)) == 1, (width, widths)
        board = item.locator(".split-board-scroll")
        assert board.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), width
        grid_box = item.locator(".split-columns").bounding_box()
        board_box = board.bounding_box()
        # La grid llena el ancho útil del board (contenido, sin su padding).
        assert grid_box["width"] >= board_box["width"] - 24 - 1, (width, grid_box, board_box)
        last = zones.last.bounding_box()
        right = last["x"] + last["width"]
        grid_right = grid_box["x"] + grid_box["width"]
        assert abs(right - grid_right) <= 2, (width, right, grid_right)
        assert _no_overflow(page)


def test_splits_crear_ejercicio_refresca_catalogo(page, server, server_db_path):
    """El alta bajo el catálogo avisa, resetea el form y el chip nuevo existe
    sin recargar (OOB de `#splits-catalog`)."""
    import sqlite3

    _goto_splits(page, server)
    # El alta vive en un grupo colapsable bajo el catálogo.
    page.locator(
        ".split-catalog-group > summary.split-catalog-summary", has_text="Nuevo ejercicio"
    ).click()
    form = page.locator("#exercise-create #exercise-create-form")
    expect(form).to_be_visible()
    form.locator('input[name="ejercicio"]').fill("Press Pausado")
    form.locator('input[name="grupo_muscular"]').fill("Pectoral")
    # La categoría se auto-asigna (Pectoral → EMPUJE) sin campo visible.
    expect(form.locator('input[name="categoria"]')).to_have_value("EMPUJE")
    expect(form.locator('select[name="grupo_muscular"]')).to_have_count(0)
    form.locator('button[type="submit"]').click()
    expect(page.locator("#notice-container .notice-success").first).to_contain_text(
        "Press Pausado", timeout=5000
    )
    chip = page.locator('.split-catalog-chip[data-ejercicio="Press Pausado"]')
    # El grupo Pectoral arranca colapsado: basta con que el chip exista
    # (el OOB lo trajo); al abrirlo se ve y es arrastrable.
    expect(chip).to_be_attached(timeout=5000)
    page.locator('.split-catalog-group[data-group="Pectoral"] > summary').click()
    expect(chip).to_be_visible()
    # El formulario queda limpio para la siguiente alta.
    expect(form.locator('input[name="ejercicio"]')).to_have_value("")
    # Persiste en el catálogo.
    conn = sqlite3.connect(str(server_db_path))
    try:
        row = conn.execute(
            "SELECT grupo_muscular, categoria FROM ejercicios WHERE ejercicio = ?",
            ("Press Pausado",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Pectoral", "EMPUJE")
