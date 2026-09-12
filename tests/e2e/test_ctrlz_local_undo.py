"""Browser tests: Ctrl+Z local R1+R2 en /diario (sesión + nutrición).

R1: fuera de modo edición, Ctrl+Z no llama a POST /undo ni altera la DB.
R2: en edición con cambios, Ctrl+Z restaura solo el último campo (pila
local, sin servidor); nunca revierte un día guardado.
"""

import datetime
import sqlite3

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open(page, server):
    page.goto(server + "/diario")
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.wait_for_selector("#date-navigator", timeout=5000)


def _goto(page, iso):
    page.locator(f'#date-navigator .date-num[data-iso="{iso}"]').click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    page.wait_for_timeout(150)


def _spy_undo(page):
    posts = []

    def _spy(r):
        if r.method == "POST" and r.url.endswith("/undo"):
            posts.append(r.url)

    page.on("request", _spy)
    return posts


def _training_rows(db_path, fecha):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT ejercicio, kg, reps, rir FROM training_sets WHERE fecha = ? ORDER BY set_orden",
            (fecha,),
        ).fetchall()
    finally:
        conn.close()


def _diario_rows(db_path, fecha):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT alimento, cantidad_g FROM diario_alimentacion WHERE fecha = ? ORDER BY orden",
            (fecha,),
        ).fetchall()
    finally:
        conn.close()


def _undo_count(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM undo_entries").fetchone()[0]
    finally:
        conn.close()


def _save_session(page):
    page.locator('#session-form button[type="submit"]').click()
    page.wait_for_selector("#editor-notice .notice", timeout=5000)
    page.wait_for_timeout(150)


def _blur(page, selector):
    page.locator(selector).click(position={"x": 2, "y": 2})
    page.wait_for_timeout(150)


def test_ctrlz_fuera_de_edicion_no_undo_ni_cambios(page, server, server_db_path):
    """R1 (sesión): tras guardar, Ctrl+Z no pide /undo y la DB queda intacta."""
    iso = _iso(-2)
    _open(page, server)
    _goto(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    row = page.locator("#set-rows .set-row").first
    row.locator("select[name='ejercicio']").select_option("Press")
    row.locator('input[name="kg"]').fill("80")
    row.locator('input[name="reps"]').fill("8")
    row.locator('input[name="rir"]').fill("1")
    _save_session(page)
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")

    before = _training_rows(server_db_path, iso)
    assert len(before) == 1
    undos = _undo_count(server_db_path)
    posts = _spy_undo(page)

    _blur(page, "#session-editor")
    page.keyboard.press("Control+z")
    page.wait_for_timeout(400)

    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"
    assert _training_rows(server_db_path, iso) == before
    assert _undo_count(server_db_path) == undos
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("80")


def test_ctrlz_en_edicion_restaura_ultimo_campo_lifo(page, server, server_db_path):
    """R2 (sesión): Ctrl+Z revierte un campo cada vez, sin servidor."""
    iso = _iso(-3)
    _open(page, server)
    _goto(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    row = page.locator("#set-rows .set-row").first
    row.locator("select[name='ejercicio']").select_option("Press")
    row.locator('input[name="kg"]').fill("80")
    row.locator('input[name="reps"]').fill("8")
    row.locator('input[name="rir"]').fill("1")
    _save_session(page)
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")
    posts = _spy_undo(page)

    page.locator("#session-editor .pencil-btn").click()
    page.locator('#set-rows input[name="kg"]').first.fill("92.5")
    page.locator('#set-rows input[name="rir"]').first.fill("2")
    _blur(page, "#session-editor")

    page.keyboard.press("Control+z")
    expect(page.locator('#set-rows input[name="rir"]').first).to_have_value("1")
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("92.5")
    page.keyboard.press("Control+z")
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("80")
    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"

    _save_session(page)
    rows = _training_rows(server_db_path, iso)
    assert rows[0] == ("Press", 80.0, 8.0, 1.0), rows


def test_ctrlz_restaura_select_sin_servidor(page, server):
    """R2 (sesión): el desplegable de ejercicio también es 'último campo'."""
    iso = _iso(-4)
    _open(page, server)
    _goto(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    row = page.locator("#set-rows .set-row").first
    row.locator("select[name='ejercicio']").select_option("Press")
    row.locator('input[name="kg"]').fill("80")
    row.locator('input[name="reps"]').fill("8")
    row.locator('input[name="rir"]').fill("1")
    _save_session(page)
    expect(page.locator("#save-outcome")).to_have_attribute("data-ok", "1")
    posts = _spy_undo(page)

    page.locator("#session-editor .pencil-btn").click()
    row.locator("select[name='ejercicio']").select_option("Curl")
    _blur(page, "#session-editor")
    page.keyboard.press("Control+z")
    expect(row.locator("select[name='ejercicio']")).to_have_value("Press")
    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"


def test_ctrl_shift_z_no_hace_nada(page, server, server_db_path):
    """Ctrl+Mayús+Z (rehacer) no dispara undo ni toca el campo."""
    iso = _iso(-5)
    _open(page, server)
    _goto(page, iso)
    page.locator("#session-editor .pencil-btn").click()
    row = page.locator("#set-rows .set-row").first
    row.locator("select[name='ejercicio']").select_option("Press")
    row.locator('input[name="kg"]').fill("80")
    row.locator('input[name="reps"]').fill("8")
    row.locator('input[name="rir"]').fill("1")
    posts = _spy_undo(page)

    _blur(page, "#session-editor")
    page.keyboard.press("Control+Shift+z")
    page.wait_for_timeout(300)
    expect(page.locator('#set-rows input[name="kg"]').first).to_have_value("80")
    assert posts == [], f"Ctrl+Mayús+Z llamó a /undo: {posts}"


def _create_avena(page):
    page.locator('[data-action="open-daily-dialog"][data-dialog="food-create-dialog"]').click()
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


def _nutrition_edit(page):
    page.locator('[data-action="nutrition-toggle-edit"]').click()
    page.wait_for_selector(
        "#nutrition-rows .nutrition-row input[name='alimento']:not([disabled])",
        timeout=3000,
    )


def _save_nutrition(page):
    # htmx.ajax directo (mismo POST /alimentacion/save que el form; el clic
    # nativo en forms re-renderizados por OOB es inestable bajo carga).
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
    page.wait_for_timeout(150)


def test_ctrlz_nutricion_r1_r2(page, server, server_db_path):
    """R1+R2 (nutrición): fuera de edición nada; en edición, último campo."""
    iso = _iso(-6)
    _open(page, server)
    _goto(page, iso)
    page.locator('[data-action="daily-mode"][data-vista="alimentacion"]').click()
    expect(page.locator("#daily-page")).to_have_attribute("data-vista", "alimentacion")
    _create_avena(page)
    _nutrition_edit(page)
    row = page.locator("#nutrition-rows .nutrition-row").first
    row.locator('input[name="alimento"]').fill("Avena")
    row.locator('input[name="cantidad"]').fill("120")
    _save_nutrition(page)
    expect(page.locator("#nutrition-editor-state")).to_have_attribute("data-has-data", "1")
    posts = _spy_undo(page)

    # R1: recién guardado (readonly), Ctrl+Z no hace nada.
    _blur(page, "#nutrition-panel")
    page.keyboard.press("Control+z")
    page.wait_for_timeout(300)
    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"
    assert _diario_rows(server_db_path, iso) == [("Avena", 120.0)]

    # R2: en edición, revierte un campo cada vez (LIFO), sin servidor.
    _nutrition_edit(page)
    page.locator('#nutrition-rows input[name="cantidad"]').first.fill("200")
    page.locator('#nutrition-rows input[name="alimento"]').first.fill("Arroz Blanco")
    _blur(page, "#nutrition-panel")
    page.keyboard.press("Control+z")
    expect(page.locator('#nutrition-rows input[name="alimento"]').first).to_have_value("Avena")
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("200")
    page.keyboard.press("Control+z")
    expect(page.locator('#nutrition-rows input[name="cantidad"]').first).to_have_value("120")
    assert posts == [], f"Ctrl+Z llamó a /undo: {posts}"
