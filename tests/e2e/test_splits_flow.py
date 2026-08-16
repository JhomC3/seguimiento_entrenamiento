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


def _mouse_drag(page, src_sel, dst_x, dst_y, steps=8, shift=False):
    """Drag de mouse real (SortableJS/nativo). Opcionalmente con Shift pulsado.

    Sortable anima 150ms cada inserción y DESCARTA los dragover mientras la
    animación corre (headless Chromium): los pasos se espacian 180ms para que
    cada posición del puntero se procese y el drop aterrice donde se suelta.
    """
    src = _box(page, src_sel)
    assert src, f"origen no encontrado: {src_sel}"
    if shift:
        page.keyboard.down("Shift")
    sx = src["x"] + src["width"] / 2
    sy = src["y"] + src["height"] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(sx + (dst_x - sx) * i / steps, sy + (dst_y - sy) * i / steps)
        page.wait_for_timeout(180)
    page.mouse.up()
    if shift:
        page.keyboard.up("Shift")
    page.wait_for_timeout(300)


def _drag_from_catalog(page, ejercicio, day, y_offset=None):
    """Arrastra un chip del catálogo (abriendo su grupo) al día destino."""
    chip = f'.split-catalog-chip[data-ejercicio="{ejercicio}"]'
    if page.locator(chip).is_hidden():
        group = page.locator(f".split-catalog-group:has({chip})")
        summary = group.locator("summary")
        if summary.is_visible():
            summary.click()
            page.wait_for_timeout(100)
    if y_offset is None:
        # Apuntar al interior de .split-day-items (contenedor Sortable):
        # el header/placeholder del día no acepta el drop de Sortable.
        list_box = _box(page, f'.split-day-zone[data-day="{day}"] .split-day-items')
        dst_x = list_box["x"] + list_box["width"] / 2
        dst_y = list_box["y"] + max(10, list_box["height"] - 10)
    else:
        zone = _box(page, f'.split-day-zone[data-day="{day}"]')
        dst_x = zone["x"] + zone["width"] / 2
        dst_y = zone["y"] + y_offset
    _mouse_drag(page, chip, dst_x, dst_y)


def _drag_to_position(page, item_sel, day, index, shift=False):
    """Arrastra el item a la posición `index` (0=primero, >=len=final) del día."""
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    n = page.locator(f"{list_sel} .split-item-card").count()
    if index >= n:
        n_cards = page.locator(f"{list_sel} .split-item-card").count()
        if n_cards:
            last = _box(page, f"{list_sel} .split-item-card:nth-child({n_cards})")
            dst_x = last["x"] + last["width"] / 2
            # Mitad inferior de la última tarjeta: Sortable inserta al final.
            dst_y = last["y"] + last["height"] - 2
        else:
            box = _box(page, list_sel)
            dst_x = box["x"] + 20
            dst_y = box["y"] + max(10, box["height"] - 2)
    else:
        anchor = _box(page, f"{list_sel} .split-item-card:nth-child({index + 1})")
        dst_x = anchor["x"] + anchor["width"] / 2
        dst_y = anchor["y"] + 2
    _mouse_drag(page, item_sel, dst_x, dst_y, shift=shift)


def _drag_to_day_at(page, item_sel, day, index=None, shift=False):
    """Arrastra el item al día destino; si `index` es int, posición exacta."""
    list_sel = f'.split-day-zone[data-day="{day}"] .split-day-items'
    if index is None:
        list_box = _box(page, list_sel)
        dst_x = list_box["x"] + list_box["width"] / 2
        dst_y = list_box["y"] + max(10, list_box["height"] - 10)
    else:
        anchor = _box(page, f"{list_sel} .split-item-card:nth-child({index + 1})")
        dst_x = anchor["x"] + anchor["width"] / 2
        dst_y = anchor["y"] + 2
    _mouse_drag(page, item_sel, dst_x, dst_y, shift=shift)


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
    # Orden: board y resumen antes que catálogo y lista.
    order = page.evaluate(
        """() => {
            const ids = ['split-board', 'split-metrics-panel', 'Catálogo de ejercicios', 'splits-section'];
            const pos = ids.map(id => {
                const el = id.startsWith('split') ? document.getElementById(id) : [...document.querySelectorAll('h2')].find(h => h.textContent.includes('Catálogo'));
                return el ? el.getBoundingClientRect().top : 0;
            });
            return pos[0] <= pos[1] && pos[1] <= pos[2] && pos[2] <= pos[3];
        }"""
    )
    assert order, "orden visual incorrecto"
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
    expect(page.locator("#split-metrics-week")).to_contain_text("Semana — 2 series")

    _drag_from_catalog(page, "HIIT", "MARTES")
    expect(page.locator('.split-day-zone[data-day="MARTES"] .split-item-card')).to_have_count(1)
    expect(page.locator("#split-metrics-week")).to_contain_text("Semana — 3 series")
    # Resumen por ejercicio y por día.
    expect(page.locator("#split-metrics-exercises")).to_contain_text("Curl: 2 series")
    expect(page.locator("#split-metrics-days")).to_contain_text("Lunes — 2 series")
    expect(page.locator("#split-metrics-days")).to_contain_text("Martes — 1 series")


def test_resumen_sin_conteos_auxiliares(page, server):
    _goto_splits(page, server)
    expect(page.locator("#split-metrics-week")).not_to_contain_text("Días activos")
    expect(page.locator("#split-metrics-week")).not_to_contain_text("Ejercicios distintos")
    # Los 7 días aparecen aunque estén vacíos.
    expect(page.locator("#split-metrics-days")).to_contain_text("Domingo — 0 series")


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
    expect(page.locator("#split-metrics-week")).to_contain_text("Semana — 3 series")


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
    _mouse_drag(
        page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10, shift=True
    )
    # LUNES intacto, JUEVES con el mismo contenido y orden.
    assert _card_names(page, "LUNES") == ["Press", "Curl", "HIIT"]
    assert _card_names(page, "JUEVES") == ["Press", "Curl", "HIIT"]
    # Todas las copias tienen dia=JUEVES.
    dias = page.evaluate(
        """() => [...document.querySelectorAll('.split-day-zone[data-day="JUEVES"] .split-item-card')]
            .map(c => c.dataset.dia)"""
    )
    assert dias == ["JUEVES", "JUEVES", "JUEVES"]
    expect(page.locator("#split-metrics-week")).to_contain_text("Semana — 6 series")
    expect(page.locator("#split-metrics-days")).to_contain_text("Jueves — 3 series")


def test_day_copy_sobre_dia_ocupado_no_reemplaza(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    _drag_from_catalog(page, "HIIT", "JUEVES")
    handle = '.split-day-zone[data-day="LUNES"] .split-day-copy-handle'
    zone = _box(page, '.split-day-zone[data-day="JUEVES"]')
    _mouse_drag(
        page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10, shift=True
    )
    assert _card_names(page, "JUEVES") == ["HIIT", "Press"]


def test_day_copy_handle_sin_shift_no_hace_nada(page, server):
    _goto_splits(page, server)
    _drag_from_catalog(page, "Press", "LUNES")
    handle = '.split-day-zone[data-day="LUNES"] .split-day-copy-handle'
    zone = _box(page, '.split-day-zone[data-day="JUEVES"]')
    _mouse_drag(
        page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10, shift=False
    )
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
    _mouse_drag(
        page, handle, zone["x"] + zone["width"] / 2, zone["y"] + zone["height"] - 10, shift=True
    )

    page.fill("#split-nombre", "Push Pull Legs")
    page.click('[data-action="split-save"]')
    expect(page.locator("#notice-container .notice-success")).to_contain_text(
        "Split guardado.", timeout=3000
    )

    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="split-open"]')
    page.wait_for_selector('.split-day-zone[data-day="LUNES"] .split-item-card', timeout=3000)

    assert _card_names(page, "LUNES") == ["Curl", "Curl", "Press", "Press"]
    assert _card_names(page, "MARTES") == ["HIIT"]
    assert _card_names(page, "VIERNES") == ["Curl", "Curl", "Press", "Press"]
    expect(page.locator('[data-day-count="LUNES"]')).to_have_text("4 series")
    expect(page.locator("#split-metrics-week")).to_contain_text("Semana — 9 series")


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
