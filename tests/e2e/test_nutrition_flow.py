"""Browser tests: nutrition editor inside /diario."""

import datetime
import sqlite3
import time

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open_food_day(page, server, iso):
    page.goto(server + f"/diario?fecha={iso}&vista=alimentacion")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-form", timeout=5000)
    page.wait_for_selector(
        f"#nutrition-form input[name='fecha'][value='{iso}']",
        state="attached",
        timeout=5000,
    )


def _food_rows(db_path, fecha: str) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT orden, alimento, cantidad_g, kcal, proteina "
            "FROM diario_alimentacion WHERE fecha = ? ORDER BY orden",
            (fecha,),
        ).fetchall()
    finally:
        conn.close()


def _open_popup(page, server):
    page.goto(server + "/diario?vista=alimentacion")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-form", timeout=5000)
    page.wait_for_selector('#session-form input[name="fecha"]', state="attached", timeout=5000)


def _fill_alimento_form(page):
    page.click('[data-action="open-daily-dialog"][data-dialog="food-create-dialog"]')
    page.wait_for_selector("#food-create-dialog[open]", timeout=5000)
    page.fill('#alimento-create-form input[name="nombre"]', "Avena")
    page.fill('#alimento-create-form input[name="categoria"]', "Cereal")
    page.fill('#alimento-create-form input[name="kcal"]', "389")
    page.fill('#alimento-create-form input[name="carbohidratos"]', "68")
    page.fill('#alimento-create-form input[name="fibra"]', "10")
    page.fill('#alimento-create-form input[name="proteina"]', "17")
    page.fill('#alimento-create-form input[name="grasa"]', "6.9")
    page.fill('#alimento-create-form input[name="hierro"]', "4.2")
    page.fill('#alimento-create-form input[name="calcio"]', "54")
    page.fill('#alimento-create-form input[name="vitamina_c"]', "0")
    page.fill('#alimento-create-form input[name="vitamina_a"]', "0")
    # htmx.ajax directo: el form se re-renderiza por OOB (#alimento-create) y el
    # click nativo puede escapar de la intercepción bajo carga.
    page.evaluate(
        """() => {
            const form = document.getElementById('alimento-create-form');
            htmx.ajax('POST', '/alimento/nuevo', {
                source: form,
                target: 'body',
                swap: 'none',
            });
        }"""
    )
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)
    page.wait_for_selector("#food-create-dialog", state="hidden", timeout=5000)


def test_nutrition_table_scrolls_horizontally_without_overlap(page, server):
    """La tabla de 21 nutrientes desborda con scroll horizontal confinado y
    sin solapes entre cabeceras (v019: anchos px + width:max-content)."""
    _open_popup(page, server)
    box = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            const ths = Array.from(
                sc.querySelectorAll('table thead tr:first-child th')
            );
            let overlap = 0;
            for (let i = 1; i < ths.length; i++) {
                const prev = ths[i - 1].getBoundingClientRect();
                const cur = ths[i].getBoundingClientRect();
                if (cur.left < prev.right - 1) overlap++;
            }
            return { scrollW: sc.scrollWidth, clientW: sc.clientWidth, overlap };
        }"""
    )
    assert box["scrollW"] > box["clientW"], f"sin scroll horizontal: {box}"
    assert box["overlap"] == 0, f"cabeceras solapadas: {box}"


def test_nutrition_header_rows_exact_height_no_gap(page, server):
    """Cabecera 36/24/24 clavados y sin huecos al fijarse (A)."""
    _open_popup(page, server)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    for _ in range(20):
        page.locator('[data-action="nutrition-row-add"]').first.click()
    heights = page.evaluate(
        """() => Array.from(
            document.querySelectorAll('#nutrition-panel .table-scroll thead tr'),
            tr => tr.getBoundingClientRect().height
        )"""
    )
    assert len(heights) == 3
    assert abs(heights[0] - 36) <= 1 and all(abs(h - 24) <= 1 for h in heights[1:]), heights
    page.evaluate("document.querySelector('#nutrition-panel .table-scroll').scrollTop = 300")
    page.wait_for_timeout(150)
    gaps = page.evaluate(
        """() => {
            const r = Array.from(
                document.querySelectorAll('#nutrition-panel .table-scroll thead tr'),
                tr => tr.getBoundingClientRect()
            );
            return [r[1].top - r[0].bottom, r[2].top - r[1].bottom];
        }"""
    )
    assert all(abs(g) <= 1 for g in gaps), gaps


def test_nutrition_first_columns_sticky(page, server):
    """Alimento + Cantidad quedan fijas al desplazar a la derecha (B)."""
    _open_popup(page, server)
    page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            sc.scrollLeft = sc.scrollWidth;
        }"""
    )
    page.wait_for_timeout(150)
    pos = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            const s = sc.getBoundingClientRect();
            const first = sc.querySelector(
                'tbody .nutrition-row td:first-child'
            ).getBoundingClientRect();
            const second = sc.querySelector(
                'tbody .nutrition-row td:nth-child(2)'
            ).getBoundingClientRect();
            return { scLeft: s.left, firstLeft: first.left, secondLeft: second.left };
        }"""
    )
    assert abs(pos["firstLeft"] - pos["scLeft"]) <= 2, pos
    assert abs(pos["secondLeft"] - pos["scLeft"] - 180) <= 2, pos


def test_nutrition_pill_overlay_and_readonly_guard(page, server):
    """La píldora +/− no altera la altura de fila, queda anclada a la derecha
    y se oculta en readonly (D)."""
    _open_popup(page, server)
    heights = page.evaluate(
        """() => {
            const row = document.querySelector('#nutrition-rows .nutrition-row');
            const pill = row.querySelector('.row-actions');
            const withPill = row.getBoundingClientRect().height;
            pill.classList.add('hidden');
            pill.hidden = true;
            const withoutPill = row.getBoundingClientRect().height;
            pill.classList.remove('hidden');
            pill.hidden = false;
            return [withPill, withoutPill];
        }"""
    )
    assert abs(heights[0] - heights[1]) <= 1, heights
    # Día guardado → readonly: la píldora no aparece ni con hover.
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    page.fill("#param-peso", "69")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-readonly", "1")
    row.hover()
    page.wait_for_timeout(250)
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('#nutrition-rows .nutrition-row .row-actions')).opacity"
        )
        == "0"
    )
    # Edición: visible en hover y anclada al borde derecho tras scroll.
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            sc.scrollLeft = sc.scrollWidth;
        }"""
    )
    page.locator("#nutrition-rows .nutrition-row").first.hover()
    page.wait_for_timeout(250)
    box = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            const s = sc.getBoundingClientRect();
            const pill = document.querySelector('#nutrition-rows .nutrition-row .row-actions');
            const p = pill.getBoundingClientRect();
            return {
                scRight: s.right,
                pillRight: p.right,
                opacity: getComputedStyle(pill).opacity,
                position: getComputedStyle(pill.closest('td')).position,
            };
        }"""
    )
    assert box["opacity"] == "1", box
    assert box["position"] == "sticky", box
    assert abs(box["pillRight"] - box["scRight"]) <= 4, box


def test_nutrition_horizontal_scroll_responds(page, server):
    """La rueda horizontal desplaza la tabla (scrollbar C funcional)."""
    _open_popup(page, server)
    page.evaluate("document.querySelector('#nutrition-panel .table-scroll').scrollLeft = 0")
    page.locator("#nutrition-panel .table-scroll").hover()
    page.mouse.wheel(400, 0)
    page.wait_for_timeout(250)
    sl = page.evaluate("document.querySelector('#nutrition-panel .table-scroll').scrollLeft")
    assert sl > 50, sl


def test_nutrition_corners_stay_on_top(page, server):
    """Las 4 esquinas Objetivo/Consumido quedan encima al desplazar (pintado,
    no solo geometría: empataban en z con sus celdas deslizantes)."""
    _open_popup(page, server)
    page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            sc.scrollLeft = sc.scrollWidth;
            sc.scrollTop = 300;
        }"""
    )
    page.wait_for_timeout(200)
    hits = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            const out = [];
            for (const r of [2, 3]) {
                for (const c of [1, 2]) {
                    const el = sc.querySelector(`thead tr:nth-child(${r}) th:nth-child(${c})`);
                    const rc = el.getBoundingClientRect();
                    out.push(
                        document.elementFromPoint(rc.left + rc.width / 2, rc.top + rc.height / 2)
                            === el
                    );
                }
            }
            return out;
        }"""
    )
    assert all(hits), hits


def test_nutrition_hover_transition_synced(page, server):
    """El fundido hover de fijas y deslizantes dura lo mismo (sin lag)."""
    _open_popup(page, server)
    durs = page.evaluate(
        """() => {
            const tr = document.querySelector('#nutrition-rows .nutrition-row');
            const td = tr.querySelector('td:first-child');
            return [
                getComputedStyle(tr).transitionDuration,
                getComputedStyle(td).transitionDuration,
            ];
        }"""
    )
    assert durs[0] == durs[1] == "0.15s", durs


def test_nutrition_scrollbar_thickness(page, server):
    """La scrollbar horizontal de nutrición es fina (~6px en modo clásico;
    0 si el SO usa overlay, que no ocupa layout)."""
    _open_popup(page, server)
    h = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            return sc.offsetHeight - sc.clientHeight;
        }"""
    )
    assert h == 0 or 4 <= h <= 8, h


def test_nutrition_no_sliced_row_at_fold(page, server):
    """Con desborde, el borde del contenedor cae en límite de fila (18
    enteras visibles, la 19ª oculta: nunca media fila rebanada)."""
    _open_popup(page, server)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    for _ in range(21):
        page.locator('[data-action="nutrition-row-add"]').first.click()
    page.evaluate("document.querySelector('#nutrition-panel .table-scroll').scrollTop = 0")
    page.wait_for_timeout(150)
    box = page.evaluate(
        """() => {
            const sc = document.querySelector('#nutrition-panel .table-scroll');
            const s = sc.getBoundingClientRect();
            const rows = Array.from(sc.querySelectorAll('tbody .nutrition-row'));
            const full = rows.filter(r => {
                const b = r.getBoundingClientRect();
                return b.bottom <= s.bottom + 1;
            });
            const partial = rows.filter(r => {
                const b = r.getBoundingClientRect();
                return b.top < s.bottom - 1 && b.bottom > s.bottom + 1;
            });
            return { n: rows.length, fullCount: full.length, partial: partial.length };
        }"""
    )
    assert box["n"] >= 20, box
    assert box["partial"] == 0, box
    assert box["fullCount"] == 18, box


def test_nutrition_create_edit_save_reload_delete(page, server):
    _open_popup(page, server)

    # 1) Alta del alimento en el catálogo (sidebar)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)

    # 2) Editar el día: Avena 120 g -> previsualización 467 kcal
    page.click('[data-action="nutrition-row-add"]')
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    expect(row.locator(".kcal-cell")).to_have_text("467")
    expect(row.locator(".prot-cell")).to_have_text("20")
    expect(page.locator(".consumed-kcal")).to_have_text("467")
    expect(page.locator(".consumed-grams")).to_have_text("120 g")

    # 3) Parámetros en vivo: peso 69 + kcal 2750 -> prot 104, grasa 76, carb 413
    page.fill("#param-peso", "69")
    page.fill("#param-kcal", "2750")
    expect(page.locator(".target-prot")).to_have_text("104")
    expect(page.locator(".target-fat")).to_have_text("76")
    expect(page.locator(".target-carb")).to_have_text("413")

    # 4) Guardar: persiste filas y parámetros
    page.click('#nutrition-form button[type="submit"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 5) Recargar: la URL trae ?fecha= y el Diario se restaura solo (fila y
    # parámetros persisten; el día queda readonly)
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-rows .nutrition-row", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="cantidad"]')).to_have_value("120")
    expect(page.locator("#param-peso")).to_have_value("69")
    expect(page.locator(".consumed-kcal")).to_have_text("467")

    # 6) Eliminar el día con confirmación (lápiz desbloquea el modo edición)
    page.click('[data-action="nutrition-toggle-edit"]')
    page.click('[data-action="nutrition-delete"]')
    expect(page.locator("#confirm-modal")).not_to_have_class("hidden")
    page.click("#confirm-save")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator('#nutrition-rows input[name="alimento"]')).to_have_value("")


def _fill_nutrition_day(page):
    row = page.locator("#nutrition-rows .nutrition-row").last
    alimento = row.locator('input[name="alimento"]')
    if alimento.is_disabled():
        page.locator('[data-action="nutrition-toggle-edit"]').evaluate("el => el.click()")
        page.wait_for_selector(
            "#nutrition-rows .nutrition-row input[name='alimento']:not([disabled])", timeout=3000
        )
    alimento.fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")


def _jump_date(page, iso):
    page.evaluate(
        f"const el = document.querySelector('#date-jump'); "
        f"el.value = '{iso}'; el.dispatchEvent(new Event('change', {{ bubbles: true }}));"
    )
    page.wait_for_function(
        "document.querySelector('#nutrition-form input[name=\"fecha\"]')?.value !== ''",
    )
    page.wait_for_selector(
        f"#nutrition-form input[name='fecha'][value='{iso}']",
        state="attached",
        timeout=5000,
    )


def _simulate_drag(page, source_sel, target_sel):
    """Dispara dragstart → dragover → drop → dragend con DataTransfer sintético."""
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


def test_nutrition_templates_save_reorder_apply(page, server):
    _open_popup(page, server)

    # 1) Guardar plantilla desde el header del editor
    _fill_nutrition_day(page)
    page.click('[data-action="nutrition-toggle-template-form"]')
    page.fill('#save-meal-template-form input[name="nombre"]', "Desayuno")
    page.click('[data-action="confirm-meal-template-save"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(
        page.locator('[data-action="open-daily-dialog"][data-dialog="food-templates-dialog"]')
    ).to_contain_text("Plantillas · 1")

    # 2) Aplicar por drag sobre el panel (otra fecha, sin datos); la lista se
    # arrastra desde el diálogo de plantillas de comida.
    _jump_date(page, _iso(9))
    page.click('[data-action="open-daily-dialog"][data-dialog="food-templates-dialog"]')
    page.wait_for_selector("#food-templates-dialog[open]", timeout=5000)
    _simulate_drag(page, "#nutrition-templates .pt-card", "#nutrition-panel")
    # El día prefillado tiene filas: la aplicación exige confirmación.
    page.wait_for_selector("#confirm-modal[open]", timeout=5000)
    page.keyboard.press("Enter")
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value("Avena")
    page.keyboard.press("Escape")
    page.wait_for_selector("#food-templates-dialog", state="hidden", timeout=5000)

    # 3) Reordenar por drag entre tarjetas (crear una segunda plantilla)
    _fill_nutrition_day(page)
    page.click('[data-action="nutrition-toggle-template-form"]')
    page.fill('#save-meal-template-form input[name="nombre"]', "Cena")
    page.click('[data-action="confirm-meal-template-save"]')
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    page.click('[data-action="open-daily-dialog"][data-dialog="food-templates-dialog"]')
    page.wait_for_selector("#food-templates-dialog[open]", timeout=5000)
    expect(page.locator("#nutrition-templates .pt-card")).to_have_count(2)
    _simulate_drag(page, "#nutrition-templates .pt-card:nth-child(2)", "#nutrition-templates")
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)
    page.reload()
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-form", timeout=5000)
    page.click('[data-action="open-daily-dialog"][data-dialog="food-templates-dialog"]')
    page.wait_for_selector("#food-templates-dialog[open]", timeout=5000)
    expect(page.locator("#nutrition-templates .pt-card").first).to_contain_text("Cena")


def _save_nutrition(page):
    """Guarda el día vía htmx.ajax (mismo POST /alimentacion/save que el form).

    El click nativo en el submit de un form re-renderizado por OOB puede
    escapar de la intercepción de htmx bajo carga (submits nativos GET); la
    llamada directa a htmx.ajax es determinista y usa el mismo camino AJAX.
    """
    page.evaluate(
        """() => {
            const form = document.getElementById('nutrition-form');
            htmx.ajax('POST', '/alimentacion/save', {
                source: form,
                target: 'body',
                swap: 'none',
            });
        }"""
    )
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)


def test_nutrition_prefill_empty_day(page, server):
    _open_popup(page, server)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice", timeout=5000)
    _fill_nutrition_day(page)
    page.fill("#param-peso", "69")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # Día siguiente (vacío): prefill desde el día previo guardado.
    manana = _iso(1)
    _jump_date(page, manana)
    page.wait_for_selector(
        "#nutrition-editor-state[data-has-data='0']", state="attached", timeout=5000
    )
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value(
        "Avena", timeout=5000
    )
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("120")
    expect(page.locator("#param-peso")).to_have_value("69")
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "0")
    expect(page.locator("body")).to_contain_text("Datos del")

    # Modificar y guardar el día precargado -> pasa a tener datos.
    page.locator('#nutrition-rows input[name="cantidad"]').first.fill("130")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute(
        "data-has-data", "1", timeout=5000
    )


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


def test_nutrition_saved_day_reorder_without_edit_mode(page, server):
    """Un día guardado está en solo lectura; el arrastre entra solo en modo
    edición y reordena (sin lápiz previo)."""
    _open_popup(page, server)
    _fill_alimento_form(page)
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)
    # Dos filas con datos (el clon puede repetir Avena; se distingue por cantidad).
    _fill_nutrition_day(page)
    page.locator('[data-action="nutrition-row-add"]').click()
    page.wait_for_timeout(120)
    rows = page.locator("#nutrition-rows .nutrition-row")
    rows.nth(1).locator('input[name="alimento"]').fill("Avena")
    rows.nth(1).locator('input[name="cantidad"]').fill("150")
    page.fill("#param-peso", "69")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-readonly", "1")
    # Arrastrar la fila 2 sobre la fila 1 sin el lápiz.
    rows = page.locator("#nutrition-rows .nutrition-row")
    _drag_row_up(page, rows, 1, ".nutrition-preview")
    page.wait_for_timeout(250)
    expect(rows.nth(0).locator('input[name="cantidad"]')).to_have_value("150")
    expect(rows.nth(1).locator('input[name="cantidad"]')).to_have_value("120")
    # Auto-entró en modo edición.
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-readonly", "0")


def test_nutrition_save_persists_across_reload(page, server, server_db_path):
    """Guardar un día nuevo desde Diario persiste en SQLite y tras recargar."""
    _open_popup(page, server)
    _fill_alimento_form(page)

    iso = _iso(-2)
    _open_food_day(page, server, iso)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    page.fill("#param-peso", "69")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # 1) Persistencia directa en SQLite: nutrientes recalculados server-side.
    rows = _food_rows(server_db_path, iso)
    assert len(rows) == 1, f"esperada 1 fila en DB, hay {len(rows)}"
    assert rows[0][1] == "Avena" and rows[0][2] == 120.0
    assert rows[0][3] == 467.0, f"kcal en DB: {rows[0][3]} (debe recalcularse 389*1.2)"

    # 2) Recarga con la misma fecha: alimento, cantidad y nutrientes siguen.
    page.goto(server + f"/diario?fecha={iso}&vista=alimentacion")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-rows .nutrition-row", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value("Avena")
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("120")
    expect(page.locator(".consumed-kcal")).to_have_text("467")


def test_nutrition_edit_save_persists_updated_quantity(page, server, server_db_path):
    """Editar la cantidad de un día existente persiste el valor actualizado."""
    _open_popup(page, server)
    _fill_alimento_form(page)

    iso = _iso(-3)
    _open_food_day(page, server, iso)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    # Editar la cantidad existente con el submit real del botón (flujo del
    # usuario) y esperar la respuesta HTTP, no solo un aviso previo.
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    page.locator('#nutrition-rows input[name="cantidad"]').first.fill("200")
    with page.expect_response("**/alimentacion/save") as resp:
        page.locator('#nutrition-form button[type="submit"]').click()
    assert resp.value.status == 200
    page.wait_for_selector("#notice-container .notice-success", timeout=5000)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")

    rows = _food_rows(server_db_path, iso)
    assert len(rows) == 1
    assert rows[0][2] == 200.0, f"cantidad en DB: {rows[0][2]}"
    assert rows[0][3] == 778.0, f"kcal en DB: {rows[0][3]} (389*2)"

    page.goto(server + f"/diario?fecha={iso}&vista=alimentacion")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#nutrition-rows .nutrition-row", timeout=5000)
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("200")
    expect(page.locator(".consumed-kcal")).to_have_text("778")


def test_nutrition_save_error_400_preserves_values_and_shows_notice(page, server):
    """Un 400 (alimento desconocido) es visible y conserva los valores locales."""
    _open_popup(page, server)
    iso = _iso(-4)
    _open_food_day(page, server, iso)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("No Existe")
    row.locator('input[name="cantidad"]').fill("100")
    # Submit real del formulario (el helper _save_nutrition espera success).
    page.locator('#nutrition-form button[type="submit"]').click()
    page.wait_for_selector("#notice-container .notice-error", timeout=5000)
    expect(page.locator("#notice-container")).to_contain_text("no encontrado")
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-readonly", "0")
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value("No Existe")
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("100")
    expect(page.locator('#nutrition-form button[type="submit"]')).to_be_enabled()


def test_nutrition_save_double_click_single_request(page, server):
    """Doble clic en Guardar de alimentación = 1 sola petición."""
    _open_popup(page, server)
    _fill_alimento_form(page)
    iso = _iso(-5)
    _open_food_day(page, server, iso)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")

    posts = []
    page.on(
        "request",
        lambda r: (
            posts.append(r.url) if r.method == "POST" and "alimentacion/save" in r.url else None
        ),
    )

    # El fulfill es instantáneo; sin delay el botón se rehabilita antes del
    # segundo clic y el test no mediría el vuelo real. El delay mantiene la
    # petición en vuelo durante los dos clics.
    def _slow_save(route):
        time.sleep(0.6)
        route.fulfill(
            status=200,
            body=(
                '<div id="notice-container" hx-swap-oob="innerHTML"><div class="notice notice-success">Día guardado.</div></div>'
                '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>'
            ),
        )

    page.route("**/alimentacion/save", _slow_save)
    # Clics nativos consecutivos (sin actionability de Playwright): el primer
    # clic dispara el submit y deshabilita el botón (beforeRequest síncrono);
    # el segundo clic cae sobre el botón deshabilitado y no genera petición.
    page.evaluate(
        """() => {
            const btn = document.querySelector('#nutrition-form button[type="submit"]');
            btn.click();
            btn.click();
        }"""
    )
    page.wait_for_function(
        """() => {
            const b = document.querySelector('#nutrition-form button[type="submit"]');
            return b && b.textContent.trim().startsWith('Guardando');
        }""",
        timeout=3000,
    )
    page.wait_for_timeout(900)
    assert len(posts) == 1, f"doble clic generó {len(posts)} peticiones"
    page.unroute("**/alimentacion/save")


def test_nutrition_navigation_with_unsaved_changes_confirms(page, server):
    """Navegar con cambios sin guardar en alimentación muestra confirmación."""
    _open_popup(page, server)
    _fill_alimento_form(page)
    iso_a = _iso(-6)
    iso_b = _iso(-7)
    _open_food_day(page, server, iso_a)
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    row = page.locator("#nutrition-rows .nutrition-row").last
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    page.locator(f'#date-navigator .date-num[data-iso="{iso_b}"]').click()
    expect(page.locator("#confirm-modal")).to_be_visible()
    expect(page.locator("#nutrition-form input[name='fecha']")).to_have_value(iso_a)
    # Guardar y continuar: la navegación espera al guardado.
    page.locator("#confirm-save").click()
    page.wait_for_timeout(800)
    expect(page.locator("#nutrition-form input[name='fecha']")).to_have_value(iso_b)
