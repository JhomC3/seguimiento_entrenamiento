"""Verificación E2E del editor de sesión (requiere playwright instalado).

Levanta un servidor temporal con una DB de prueba y valida con Chrome headless:
hover de filas, fila fallback, dot del strip, recalculo de RM, tarjeta estable,
espacio fijo de los botones, flujos del modal y regresiones del modo editable.

Uso:
    uv run playwright install chromium   # una sola vez
    uv run python scripts/verify_editor.py
"""
import datetime
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    from playwright.sync_api import sync_playwright

    tmpdir = tempfile.mkdtemp()
    db = os.path.join(tmpdir, "gym.db")
    shutil.copy(os.path.join(ROOT, "data", "gym.db"), db)

    today = datetime.date.today()
    iso_today = today.strftime("%Y-%m-%d")
    import sqlite3
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from training_service import fecha_to_db
    conn = sqlite3.connect(db)
    taken = {r[0] for r in conn.execute("SELECT DISTINCT fecha FROM training_sets").fetchall()}
    conn.close()
    iso_future = ""
    iso_future2 = ""
    iso_future3 = ""
    iso_future4 = ""
    iso_future5 = ""
    iso_future6 = ""
    empties = []
    for delta in range(1, 15):
        d = today + datetime.timedelta(days=delta)
        if fecha_to_db(d) not in taken:
            empties.append(d.strftime("%Y-%m-%d"))
    if len(empties) >= 6:
        iso_future, iso_future2, iso_future3, iso_future4, iso_future5, iso_future6 = empties[:6]
    iso_past = ""
    for delta in range(2, 20):
        d = today - datetime.timedelta(days=delta)
        if fecha_to_db(d) not in taken:
            iso_past = d.strftime("%Y-%m-%d")
            break
    port = free_port()

    server_code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, '{ROOT}')
        import app as appmod
        appmod.DB_PATH = '{db}'
        from src.database import init_db, insert_exercise
        init_db(appmod.DB_PATH)
        import sqlite3 as _sqlite3
        _conn = _sqlite3.connect(appmod.DB_PATH)
        _conn.execute("DELETE FROM plantilla_sets")
        _conn.execute("DELETE FROM plantillas")
        _conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('plantillas', 'plantilla_sets')")
        _conn.commit()
        _conn.close()
        insert_exercise(appmod.DB_PATH, 'Press Repro', 'Pectoral', 'EMPUJE')
        insert_exercise(appmod.DB_PATH, 'Curl Repro', 'Biceps', 'TIRON')
        from src.training_service import save_session
        import datetime
        save_session(appmod.DB_PATH, datetime.date.today().strftime('%Y-%m-%d'),
                     [{{"ejercicio": "Press Repro", "kg": 100, "reps": 8, "rir": 1}}])
        import uvicorn
        uvicorn.run(appmod.app, port={port}, log_level='error')
    """)
    server_path = os.path.join(tmpdir, "server.py")
    with open(server_path, "w") as f:
        f.write(server_code)

    proc = subprocess.Popen(
        [os.path.join(ROOT, ".venv", "bin", "python"), server_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)

    results: list[str] = []
    failures: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            time.sleep(1.5)

            def em() -> str:
                return page.evaluate("document.getElementById('session-editor')?.dataset.editmode")

            def row_bg() -> str:
                return page.evaluate("""(() => {
                    const row = document.querySelector('#set-rows .set-row');
                    return getComputedStyle(row).backgroundColor;
                })()""")

            def nrows() -> int:
                return page.evaluate('document.querySelectorAll("#set-rows .set-row").length')

            def modal() -> bool:
                return page.evaluate("!document.getElementById('confirm-modal').classList.contains('hidden')")

            def check(label: str, cond: bool) -> None:
                results.append(f"{'OK ' if cond else 'FAIL'} {label}")
                if not cond:
                    failures.append(label)

            def wait_fecha(iso: str) -> None:
                page.wait_for_function(
                    "iso => document.querySelector('#session-form input[name=\"fecha\"]')?.value === iso",
                    arg=iso, timeout=5000,
                )
                time.sleep(0.3)

            def drag_row(src_idx: int, dst_idx: int) -> None:
                sb = page.locator(f"#set-rows .set-row:nth-child({src_idx}) .set-num").bounding_box()
                db = page.locator(f"#set-rows .set-row:nth-child({dst_idx}) .set-num").bounding_box()
                page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2)
                page.mouse.down()
                page.mouse.move(db["x"] + db["width"] / 2, db["y"] + db["height"] / 2, steps=15)
                time.sleep(0.3)
                page.mouse.up()
                time.sleep(0.5)

            def row_order() -> list:
                return page.evaluate(
                    'Array.from(document.querySelectorAll("#set-rows .set-row")).map(r => r.querySelector(".ej-select").value)'
                )

            def nav(iso: str) -> None:
                page.evaluate(f"requestNavigate('{iso}')")
                wait_fecha(iso)

            # A. fecha pasada sin datos -> fila fallback (readonly)
            nav(iso_past)
            check(f"pasada vacía: 1 fila fallback (editmode={em()})", nrows() == 1 and em() == "0")

            # B. lápiz -> hover ilumina en pasada vacía
            page.click(".pencil-btn")
            time.sleep(0.3)
            before = row_bg()
            page.hover("#set-rows .set-row")
            time.sleep(0.25)
            check("hover ilumina en pasada vacía (editmode=1)", row_bg() != before)

            # C. + funciona en pasada vacía con lápiz
            page.click("#session-editor .row-actions button:nth-child(2)")
            time.sleep(0.2)
            check("+ agrega fila en pasada vacía", nrows() == 2)

            # D. navegar con cambios -> modal -> descartar
            page.evaluate(f"requestNavigate('{iso_today}')")
            time.sleep(0.4)
            check("navegar con cambios abre modal", modal())
            page.click("#confirm-cancel")
            wait_fecha(iso_today)

            # E. hover en hoy CON datos con lápiz activo
            page.click(".pencil-btn")
            time.sleep(0.3)
            before = row_bg()
            page.hover("#set-rows .set-row")
            time.sleep(0.25)
            check("hover ilumina en hoy con datos (editmode=1)", row_bg() != before)

            # F. guardar -> RM recalcula + dot aparece sin recargar
            page.fill('#session-form input[name="kg"]', "110")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            rm = page.evaluate("document.querySelector('#set-rows .rm-cell').textContent")
            check(f"RM recalculado tras guardar ({rm})", rm == "146.6")
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_today}\"] .date-dot')")
            check("dot aparece tras guardar", dot)

            # G. borrar sesión -> dot desaparece
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.evaluate("Array.from(document.querySelectorAll('#set-rows .set-row')).forEach(r => removeRow(r.querySelector('.row-btn')))")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_today}\"] .date-dot')")
            check("dot desaparece tras guardar vacío", not dot)
            check(f"tras guardar vacío sigue editable (editmode={em()})", em() == "1")

            # H. tarjeta estable al navegar (mismo nodo)
            page.evaluate("""(() => { const el = document.getElementById('session-editor'); if (!el.getAttribute('data-x')) el.setAttribute('data-x','marca'); })()""")
            nav(iso_future)
            check("tarjeta estable tras navegar", page.evaluate("document.getElementById('session-editor').getAttribute('data-x')") == "marca")

            # I. altura del panel estable al mostrar/ocultar botones
            h1 = page.evaluate("document.getElementById('session-editor').getBoundingClientRect().height")
            page.fill('#session-form input[name="kg"]', "50")
            time.sleep(0.3)
            h2 = page.evaluate("document.getElementById('session-editor').getBoundingClientRect().height")
            check(f"altura estable con/sin botones ({h1:.0f}/{h2:.0f})", abs(h1 - h2) < 1)

            # J. hover en futura vacía (editable) y en futura con datos (lápiz)
            page.mouse.move(10, 10)
            time.sleep(0.25)
            before = row_bg()
            page.hover("#set-rows .set-row")
            time.sleep(0.25)
            check("hover ilumina en futura vacía editable", row_bg() != before)

            # K. guardar con datos en futura -> readonly + dot
            page.select_option('#session-form select[name="ejercicio"]', "Press Repro")
            page.fill('#session-form input[name="kg"]', "80")
            page.fill('#session-form input[name="reps"]', "6")
            page.fill('#session-form input[name="rir"]', "1")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            check(f"futura guardada pasa a readonly (editmode={em()})", em() == "0")
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_future}\"] .date-dot')")
            check("dot aparece en futura", dot)

            # L. bloqueo de filas en readonly + readonly persistente al volver
            page.evaluate("Array.from(document.querySelectorAll('.row-actions')).forEach(el => el.classList.remove('hidden'))")
            before_n = nrows()
            page.click("#session-editor .row-actions button:nth-child(2)")
            time.sleep(0.2)
            check("+ bloqueado en readonly", nrows() == before_n)
            nav(iso_future)
            check(f"futura guardada sigue readonly al volver (editmode={em()})", em() == "0")

            # M. modal Guardar (lápiz off con cambios) persiste el cambio
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.fill('#session-form input[name="kg"]', "90")
            page.fill('#session-form input[name="reps"]', "5")
            page.fill('#session-form input[name="rir"]', "1")
            page.click(".pencil-btn")
            time.sleep(0.3)
            check("modal al desactivar lápiz con cambios", modal())
            page.click("#confirm-save")
            time.sleep(1.2)
            kg = page.evaluate("document.querySelector('#session-form input[name=\"kg\"]').value")
            check(f"modal Guardar persiste (kg={kg})", kg == "90" and em() == "0")

            # N. guardado con error -> botones se mantienen; corregido -> se ocultan
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.fill('#session-form input[name="kg"]', "95")
            page.fill('#session-form input[name="reps"]', "4")
            page.evaluate("document.querySelector('#set-rows .ej-select').value = ''")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            actions_vis = page.evaluate("!document.getElementById('edit-actions').classList.contains('invisible')")
            err = page.evaluate("!!document.querySelector('#editor-notice .notice-error')")
            check(f"tras error de validación botones visibles ({actions_vis})", actions_vis)
            check("tras error de validación aviso de error visible", err)
            kg = page.evaluate("document.querySelector('#session-form input[name=\"kg\"]').value")
            check(f"datos fallidos conservados (kg={kg})", kg == "95")
            panel_box = page.evaluate("document.getElementById('session-editor').getBoundingClientRect()")
            notice_box = page.evaluate("document.querySelector('#editor-notice .notice-error').getBoundingClientRect()")
            inside = panel_box["top"] <= notice_box["top"] + 2 and notice_box["bottom"] <= panel_box["bottom"] + 2
            big = notice_box["height"] >= 32
            check(f"aviso dentro del panel ({inside}) y tamaño mayor ({notice_box['height']:.0f}px)", inside and big)
            page.select_option('#session-form select[name="ejercicio"]', "Press Repro")
            page.fill('#session-form input[name="rir"]', "")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            err_rir = page.evaluate("!!document.querySelector('#editor-notice .notice-error')")
            actions_vis = page.evaluate("!document.getElementById('edit-actions').classList.contains('invisible')")
            check(f"RIR vacío rechazado con botones visibles ({actions_vis})", err_rir and actions_vis)
            page.fill('#session-form input[name="rir"]', "0")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            actions_vis = page.evaluate("!document.getElementById('edit-actions').classList.contains('invisible')")
            check(f"tras guardar corregido botones ocultos ({em()})", em() == "0" and not actions_vis)
            rir0 = page.evaluate("document.querySelector('#session-form input[name=\"rir\"]').value")
            check(f"RIR 0 guardado y mostrado sin decimales ({rir0})", rir0 == "0")

            # O. formato de enteros sin decimales tras re-render (server %g)
            nav(iso_past)
            nav(iso_future)
            kg_val = page.evaluate("document.querySelector('#session-form input[name=\"kg\"]').value")
            rir_val = page.evaluate("document.querySelector('#session-form input[name=\"rir\"]').value")
            check(f"valores enteros sin decimales (kg={kg_val}, rir={rir_val})", kg_val == "95" and rir_val == "0")

            # P. drag and drop de filas (solo en modo editable)
            nav(iso_future2)
            page.select_option('#set-rows .set-row:nth-child(1) select[name="ejercicio"]', "Press Repro")
            page.fill('#set-rows .set-row:nth-child(1) input[name="kg"]', "80")
            page.fill('#set-rows .set-row:nth-child(1) input[name="reps"]', "6")
            page.fill('#set-rows .set-row:nth-child(1) input[name="rir"]', "1")
            page.click("#session-editor .row-actions button:nth-child(2)")
            page.select_option('#set-rows .set-row:nth-child(2) select[name="ejercicio"]', "Curl Repro")
            page.fill('#set-rows .set-row:nth-child(2) input[name="kg"]', "16")
            page.fill('#set-rows .set-row:nth-child(2) input[name="reps"]', "8")
            page.fill('#set-rows .set-row:nth-child(2) input[name="rir"]', "2")
            check("orden inicial (Press, Curl)", row_order() == ["Press Repro", "Curl Repro"])
            drag_row(2, 1)
            check("drag reordena filas (Curl, Press)", row_order() == ["Curl Repro", "Press Repro"])
            nums = page.evaluate('Array.from(document.querySelectorAll("#set-rows .set-num")).map(t => t.textContent)')
            check(f"columna # renumera ({nums})", nums == ["1", "2"])
            actions_vis = page.evaluate("!document.getElementById('edit-actions').classList.contains('invisible')")
            check("reorden marca dirty (botones visibles)", actions_vis)
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            check(f"tras guardar readonly (editmode={em()})", em() == "0")
            nav(iso_past)
            nav(iso_future2)
            check("orden persistido (Curl, Press)", row_order() == ["Curl Repro", "Press Repro"])
            before = row_order()
            drag_row(1, 2)
            check("drag bloqueado en readonly", row_order() == before)

            # Q. panel compacto: altura fija de 18 filas, scroll solo con más filas
            def scroll_metrics():
                return page.evaluate(
                    '(() => { const w = document.querySelector("#session-editor .table-scroll"); '
                    'return { client: w.clientHeight, scroll: w.scrollHeight, h: getComputedStyle(w).height, rows: document.querySelectorAll("#set-rows .set-row").length }; })()'
                )
            m = scroll_metrics()
            h_px = float(m["h"].replace("px", ""))
            row_px = page.evaluate('document.querySelector("#set-rows .set-row").offsetHeight')
            check(f"altura fija = thead + 18 filas ({h_px:.0f}px ≈ 18*{row_px})", abs(h_px - (18 * row_px)) <= 40)
            check(f"panel con pocas filas sin scroll (rows={m['rows']}, scroll<=client)", m["scroll"] <= m["client"])
            page.click(".pencil-btn")
            for _ in range(16):
                page.click("#set-rows .set-row:nth-child(1) .row-actions button:nth-child(2)")
            m = scroll_metrics()
            check(f"18 filas: tabla llena el panel sin hueco ni scroll ({m['rows']} rows, {m['scroll']}=={m['client']})", m["rows"] == 18 and m["scroll"] == m["client"])
            page.click("#set-rows .set-row:nth-child(1) .row-actions button:nth-child(2)")
            m = scroll_metrics()
            check(f"19+ filas -> scroll vertical interno ({m['rows']} rows, {m['scroll']}>{m['client']})", m["rows"] == 19 and m["scroll"] > m["client"])
            check("altura sin cambios con 19+ filas", m["h"] == f"{h_px:.0f}px")
            page.click("#edit-actions button:not([type=submit])")
            time.sleep(0.8)
            m = scroll_metrics()
            check(f"panel conserva sus dimensiones tras cancelar ({m['h']}, {m['rows']} rows)", m["h"] == f"{h_px:.0f}px" and m["scroll"] <= m["client"])

            # R. entrenos: guardar como entreno, aplicar, editar, eliminar
            def entrenos_names() -> list:
                return page.evaluate('Array.from(document.querySelectorAll("#plantillas-list .pt-card > span")).map(s => s.textContent)')

            def mouse_drag(src_loc, dst_loc) -> None:
                sb = src_loc.bounding_box()
                db = dst_loc.bounding_box()
                page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + 16)
                page.mouse.down()
                page.mouse.move(db["x"] + db["width"] / 2, db["y"] + 16, steps=15)
                time.sleep(0.3)
                page.mouse.up()
                time.sleep(0.8)

            def save_entreno(nombre: str) -> None:
                page.click(".pencil-btn")
                time.sleep(0.3)
                page.click(".save-template-btn")
                time.sleep(0.3)
                check("crear entreno: anuncio previo", modal())
                page.click("#confirm-save")
                time.sleep(0.3)
                page.fill('#save-template-form input[name="nombre"]', nombre)
                page.keyboard.press("Enter")
                time.sleep(0.3)
                check("guardar entreno abre confirmación", modal())
                page.click("#confirm-save")
                time.sleep(1.2)

            page.on("dialog", lambda d: d.accept())
            nav(iso_future2)
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.click(".save-template-btn")
            time.sleep(0.3)
            check("crear entreno: anuncio previo", modal())
            page.click("#confirm-save")
            time.sleep(0.3)
            sugg = page.input_value('#save-template-form input[name="nombre"]')
            check(f"nombre sugerido por clasificación ({sugg})", sugg == "Torso")
            page.fill('#save-template-form input[name="nombre"]', "Mi Torso")
            page.keyboard.press("Enter")
            time.sleep(0.3)
            check("guardar entreno abre confirmación", modal())
            page.click("#confirm-save")
            time.sleep(1.2)
            sidebar_txt = page.evaluate("document.getElementById('plantillas-section').textContent")
            check("entreno guardado en sidebar (solo nombre)", "Mi Torso" in sidebar_txt and "TORSO" not in sidebar_txt)
            nav(iso_future3)
            page.click("#pt-card-1 .pt-btn-burgundy")
            time.sleep(1.0)
            check(f"aplicar entreno: editable ({em()})", em() == "1")
            check("aplicar entreno: filas con últimos valores", row_order() == ["Curl Repro", "Press Repro"])
            kgs = page.evaluate('Array.from(document.querySelectorAll("#set-rows input[name=\\"kg\\"]")).map(i => i.value)')
            check(f"aplicar entreno: kg del último realizado ({kgs})", kgs == ["16", "80"])
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            check(f"sesión aplicada guardada en {iso_future3} (readonly={em()})", em() == "0")
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_future3}\"] .date-dot')")
            check("dot aparece en la fecha aplicada", dot)
            page.click("#pt-card-1 .pt-btn:not(.pt-btn-burgundy)")
            time.sleep(0.8)
            page.fill('#pt-card-1 form input[name="nombre"]', "Mi Torso V2")
            page.click('#pt-card-1 button[onclick="ptAddRow(this)"]')
            page.select_option('#pt-card-1 .pt-row:last-child select', "Press Militar")
            page.click('#pt-card-1 form button[type=submit]')
            time.sleep(1.2)
            sidebar_txt = page.evaluate("document.getElementById('plantillas-section').textContent")
            check("entreno editado (Mi Torso V2)", "Mi Torso V2" in sidebar_txt)
            page.locator("#pt-card-1 .pt-btn").nth(2).click()
            time.sleep(1.2)
            sidebar_txt = page.evaluate("document.getElementById('plantillas-section').textContent")
            check("entreno eliminado (sidebar vacío)", "Aún no hay entrenos" in sidebar_txt)

            # S. drag and drop: reordenar entrenos y soltar sobre el editor vacío
            nav(iso_future4)
            page.select_option('#set-rows .set-row:nth-child(1) select[name="ejercicio"]', "Press Repro")
            page.fill('#set-rows .set-row:nth-child(1) input[name="kg"]', "80")
            page.fill('#set-rows .set-row:nth-child(1) input[name="reps"]', "6")
            page.fill('#set-rows .set-row:nth-child(1) input[name="rir"]', "1")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            save_entreno("Empuje")
            nav(iso_future5)
            page.select_option('#set-rows .set-row:nth-child(1) select[name="ejercicio"]', "Curl Repro")
            page.fill('#set-rows .set-row:nth-child(1) input[name="kg"]', "16")
            page.fill('#set-rows .set-row:nth-child(1) input[name="reps"]', "8")
            page.fill('#set-rows .set-row:nth-child(1) input[name="rir"]', "2")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            save_entreno("Mi Jalón")
            check("dos entrenos en orden de creación", entrenos_names() == ["Empuje", "Mi Jalón"])
            mouse_drag(page.locator('#plantillas-list .pt-card').nth(1), page.locator('#plantillas-list .pt-card').nth(0))
            page.evaluate("refreshPlantillas()")
            time.sleep(0.8)
            check("reorden persistido tras refrescar", entrenos_names() == ["Mi Jalón", "Empuje"])
            nav(iso_future6)
            check(f"fecha vacía editable para drop ({em()})", em() == "1")
            mouse_drag(page.locator('#plantillas-list .pt-card').nth(1), page.locator('#set-rows .set-row').first)
            time.sleep(1.0)
            check(f"drop aplica entreno: editable ({em()})", em() == "1")
            check("drop aplica entreno: filas con últimos valores", row_order() == ["Press Repro"])
            kgs = page.evaluate('Array.from(document.querySelectorAll("#set-rows input[name=\\"kg\\"]")).map(i => i.value)')
            check(f"drop aplica entreno: kg ({kgs})", kgs == ["80"])
            page.click("#edit-actions button:not([type=submit])")
            time.sleep(0.8)
            check("cancelar tras drop restaura fila vacía", nrows() == 1 and em() == "1")
            nav(iso_future3)
            check(f"drop bloqueado en fecha con datos ({em()})", em() == "0")
            before = row_order()
            mouse_drag(page.locator('#plantillas-list .pt-card').first, page.locator('#set-rows .set-row').first)
            check("drop bloqueado: editor sin cambios", row_order() == before and em() == "0")

            # T. eliminar entreno del día + confirmación de reemplazo + ✓ solo editable
            nav(iso_future6)
            page.select_option('#set-rows .set-row:nth-child(1) select[name="ejercicio"]', "Press Repro")
            page.fill('#set-rows .set-row:nth-child(1) input[name="kg"]', "100")
            page.fill('#set-rows .set-row:nth-child(1) input[name="reps"]', "6")
            page.fill('#set-rows .set-row:nth-child(1) input[name="rir"]', "1")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_future6}\"] .date-dot')")
            check("dot visible tras guardar en T", dot)
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.click(".delete-session-btn")
            time.sleep(0.3)
            check("eliminar entreno abre confirmación", modal())
            page.click("#confirm-save")
            time.sleep(1.2)
            check(f"sesión eliminada: editor vacío editable ({em()})", em() == "1" and nrows() == 1)
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_future6}\"] .date-dot')")
            check("dot desaparece tras eliminar", not dot)
            nav(iso_future3)
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.click(".save-template-btn")
            time.sleep(0.3)
            check("crear entreno: anuncio previo", modal())
            page.click("#confirm-save")
            time.sleep(0.3)
            page.fill('#save-template-form input[name="nombre"]', "Empuje")
            page.keyboard.press("Enter")
            time.sleep(0.3)
            check("nombre existente pregunta reemplazo", modal())
            msg = page.evaluate("document.getElementById('confirm-msg').textContent")
            check(f"mensaje de reemplazo ({msg})", "Reemplazar" in msg)
            page.click("#confirm-save")
            time.sleep(1.2)
            closed = page.evaluate("document.getElementById('save-template-form-wrap').classList.contains('hidden')")
            notice = page.evaluate("document.getElementById('notice-container').textContent")
            check("reemplazo guardado y form cerrado", closed and "actualizado" in notice)

            # U. modo editable estricto: gating + iluminación + altura estable al eliminar
            def icon_state() -> dict:
                return page.evaluate("""(() => {
                    const q = s => document.querySelector(s);
                    const st = s => { const e = q(s); return e ? { on: e.classList.contains('on'), off: e.classList.contains('off'), hidden: e.hidden } : null; };
                    return {
                        pencil: st('#session-editor .pencil-btn'),
                        bookmark: st('#session-editor .save-template-btn'),
                        trash: st('#session-editor .delete-session-btn'),
                        saveDisabled: q('#edit-actions button[type=submit]') ? q('#edit-actions button[type=submit]').disabled : null,
                    };
                })()""")

            nav(iso_future3)
            st = icon_state()
            check("readonly: lápiz apagado", st["pencil"]["off"] and not st["pencil"]["on"])
            check("readonly: marcador difuminado", not st["bookmark"]["on"])
            check("readonly: papelera difuminada y visible", not st["trash"]["on"] and not st["trash"]["hidden"])
            check("readonly: ✓ deshabilitado", st["saveDisabled"] is True)
            page.click(".save-template-btn")
            time.sleep(0.3)
            hidden_form = page.evaluate("document.getElementById('save-template-form-wrap').classList.contains('hidden')")
            check("readonly: no abre form de entreno", hidden_form)
            page.click(".delete-session-btn")
            time.sleep(0.3)
            check("readonly: no abre modal de eliminar", not modal())
            before = row_order()
            page.click("#plantillas-list .pt-card .pt-btn-burgundy")
            time.sleep(0.5)
            check("readonly: Aplicar no modifica el editor", row_order() == before)
            page.click(".pencil-btn")
            time.sleep(0.3)
            st = icon_state()
            check("editable: lápiz encendido", st["pencil"]["on"])
            check("editable: marcador encendido", st["bookmark"]["on"])
            check("editable: papelera encendida", st["trash"]["on"])
            check("editable: ✓ habilitado", st["saveDisabled"] is False)
            page.click(".save-template-btn")
            time.sleep(0.3)
            check("editable: anuncio de crear entreno", modal())
            page.click("#confirm-save")
            time.sleep(0.3)
            hidden_form = page.evaluate("document.getElementById('save-template-form-wrap').classList.contains('hidden')")
            check("editable: abre form de entreno", not hidden_form)
            page.click("#save-template-form .btn-x")
            time.sleep(0.2)
            page.click(".delete-session-btn")
            time.sleep(0.3)
            check("editable: abre modal de eliminar", modal())
            page.click("#confirm-cancel")
            time.sleep(0.3)
            nav(iso_future6)
            page.select_option('#set-rows .set-row:nth-child(1) select[name="ejercicio"]', "Press Repro")
            page.fill('#set-rows .set-row:nth-child(1) input[name="kg"]', "100")
            page.fill('#set-rows .set-row:nth-child(1) input[name="reps"]', "6")
            page.fill('#set-rows .set-row:nth-child(1) input[name="rir"]', "1")
            page.click("#edit-actions button[type=submit]")
            time.sleep(1.2)
            page.evaluate("""(() => {
                window.__ys = [];
                const el = document.getElementById('unified-chart-container');
                const loop = () => { window.__ys.push(el.getBoundingClientRect().top); if (window.__ys.length < 80) requestAnimationFrame(loop); };
                loop();
            })()""")
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.click(".delete-session-btn")
            time.sleep(0.3)
            page.click("#confirm-save")
            time.sleep(1.0)
            ys = page.evaluate("window.__ys")
            check(f"gráfica inmóvil durante delete (rango {max(ys) - min(ys):.2f}px)", len(ys) > 20 and (max(ys) - min(ys)) < 1)

            # V. deshacer (botón ↶ y Ctrl+Z)
            check("V: f6 quedó vacío tras U", em() == "1" and nrows() == 1)
            page.click(".undo-btn")
            time.sleep(1.5)
            check("undo restaura la sesión eliminada", em() == "0" and nrows() >= 1)
            dot = page.evaluate(f"!!document.querySelector('.date-num[data-iso=\"{iso_future6}\"] .date-dot')")
            check("undo devuelve el dot de la fecha", dot)
            page.click(".pencil-btn")
            time.sleep(0.3)
            page.click(".undo-btn")
            time.sleep(1.5)
            check("undo quita la sesión guardada", em() == "1" and nrows() == 1)
            page.click(".undo-btn")
            time.sleep(1.2)
            page.locator('#plantillas-list .pt-card').nth(1).locator('.pt-btn').nth(1).click()
            time.sleep(0.8)
            n_pt_rows = page.evaluate('document.querySelectorAll("#plantilla-edit-rows .pt-row").length')
            check(f"undo de entreno restaura ejercicios originales ({n_pt_rows})", n_pt_rows == 1)
            page.evaluate("refreshPlantillas()")
            time.sleep(0.6)
            mouse_drag(page.locator('#plantillas-list .pt-card').nth(0), page.locator('#plantillas-list .pt-card').nth(1))
            check("V: reorden manual aplicado", entrenos_names() == ["Empuje", "Mi Jalón"])
            page.keyboard.press("Control+z")
            time.sleep(1.2)
            check("Ctrl+Z deshace el reorden", entrenos_names() == ["Mi Jalón", "Empuje"])
            page.click(".save-template-btn")
            time.sleep(0.3)
            page.click("#confirm-save")
            time.sleep(0.3)
            page.click('#save-template-form input[name="nombre"]')
            page.keyboard.type("Zzz")
            time.sleep(0.2)
            page.keyboard.press("Control+z")
            time.sleep(0.4)
            val = page.input_value('#save-template-form input[name="nombre"]')
            check(f"Ctrl+Z en input no deshace la app (valor '{val}', sidebar intacta)", entrenos_names() == ["Mi Jalón", "Empuje"])
            page.click("#save-template-form .btn-x")
            time.sleep(0.3)

            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(tmpdir, ignore_errors=True)
        print("\n".join(results))
        print(f"\n{len(results) - len(failures)}/{len(results)} OK")
        if failures:
            print("FALLOS:", ", ".join(failures))


if __name__ == "__main__":
    raise SystemExit(main())
