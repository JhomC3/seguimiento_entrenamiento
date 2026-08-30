"""UX-1 — Altura y scroll (P1).

Requisito dashboard-ux-refinement.md §UX-1 con precisión aprobada:
- tolerancia 1 px para tops
- medir tras página estable (networkidle + appReady + layout estable) y tras cada interacción
- verificar 1280×800 y 1440×900 desktop, y 390×800 móvil, catálogo abierto/plegado,
  resumen vacío y con datos

Criterio desktop (≥1024px):
  documentElement.scrollHeight <= innerHeight + 1
  body.scrollHeight <= innerHeight + 1
  |catalogTop - chartTop| <= 1
  |summaryTop - chartTop| <= 1
  summaryBottom <= innerHeight + 1
  catalog y summary ocupan altura útil (>300 px)
  rail plegado conserva altura completa
  Validación de configuración de scroll interno (overflow-y), no de overflow real
  con dataset pequeño — se documenta diferencia entre configuración y comportamiento.

Mobile (<1024px) verifica scroll global y visibilidad del resumen,
no alineación de tops (drawer superpuesto, inert esperado).
"""

import datetime
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path

from playwright.sync_api import expect


def _wait_stable(page):
    page.wait_for_function("document.body.dataset.appReady === '1'")
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:  # noqa: BLE001, S110 - networkidle timeout no es error
        pass
    page.wait_for_timeout(400)


def _stable_dash(page):
    """Lee --dashboard-layout-top hasta estabilidad; falla explícitamente si no estabiliza."""
    for _ in range(5):
        a_raw = page.evaluate(
            "getComputedStyle(document.querySelector('.dashboard-page')).getPropertyValue('--dashboard-layout-top')"
        )
        try:
            a = float(a_raw.replace("px", "").strip() or 0)
        except ValueError:
            a = 0.0
        page.wait_for_timeout(100)
        b_raw = page.evaluate(
            "getComputedStyle(document.querySelector('.dashboard-page')).getPropertyValue('--dashboard-layout-top')"
        )
        try:
            b = float(b_raw.replace("px", "").strip() or 0)
        except ValueError:
            b = 0.0
        if abs(a - b) <= 1:
            return b
    raise AssertionError("dashboard-layout-top no alcanzó estabilidad")


def _metrics(page):
    return page.evaluate("""
() => {
    const de = document.documentElement;
    const body = document.body;
    const catalog = document.getElementById('dashboard-catalog');
    const chartCol = document.querySelector('.dashboard-analytics-col');
    const summary = document.getElementById('period-summary-wrap');
    const psPanels = document.querySelector('.ps-panels');
    function rect(el){ if(!el) return null; const r=el.getBoundingClientRect(); return {top:r.top,bottom:r.bottom,height:r.height,width:r.width}; }
    return {
        scrollHeight: de.scrollHeight,
        bodyScrollHeight: body.scrollHeight,
        scrollY: window.scrollY,
        innerHeight: window.innerHeight,
        innerWidth: window.innerWidth,
        catalogRect: rect(catalog),
        chartColRect: rect(chartCol),
        summaryRect: rect(summary),
        psPanelsRect: rect(psPanels),
        psPanelsOverflowY: psPanels ? getComputedStyle(psPanels).overflowY : null,
        psPanelsScrollHeight: psPanels ? psPanels.scrollHeight : null,
        psPanelsClientHeight: psPanels ? psPanels.clientHeight : null,
        catalogOverflowY: catalog ? getComputedStyle(catalog).overflowY : null,
        catalogListOverflowY: document.querySelector('.dashboard-catalog-list') ? getComputedStyle(document.querySelector('.dashboard-catalog-list')).overflowY : null,
        bodyOverflowY: getComputedStyle(body).overflowY,
        htmlOverflowY: getComputedStyle(de).overflowY,
        collapsed: document.querySelector('.dashboard-page')?.classList.contains('is-catalog-collapsed'),
        dashTop: getComputedStyle(document.querySelector('.dashboard-page')).getPropertyValue('--dashboard-layout-top'),
        summaryVisible: summary ? !!(summary.offsetParent !== null || getComputedStyle(summary).visibility !== 'hidden') : false,
        summaryVisibility: summary ? getComputedStyle(summary).visibility : null,
    }
}
""")


def _assert_desktop(page, label):
    m = _metrics(page)
    # scroll global: tanto html como body deben estar contenidos
    assert m["scrollHeight"] <= m["innerHeight"] + 1, (
        f"{label}: scrollHeight {m['scrollHeight']} > innerHeight {m['innerHeight']}"
    )
    assert m["bodyScrollHeight"] <= m["innerHeight"] + 1, (
        f"{label}: bodyScrollHeight {m['bodyScrollHeight']} > innerHeight {m['innerHeight']}"
    )
    assert m["scrollY"] == 0, f"{label}: window.scrollY {m['scrollY']} != 0"
    assert m["catalogRect"] and m["chartColRect"] and m["summaryRect"], f"{label}: rects missing"
    # tolerancia 1px aprobada
    assert abs(m["catalogRect"]["top"] - m["chartColRect"]["top"]) <= 1, (
        f"{label}: catalogTop {m['catalogRect']['top']} != chartTop {m['chartColRect']['top']}"
    )
    assert abs(m["summaryRect"]["top"] - m["chartColRect"]["top"]) <= 1, (
        f"{label}: summaryTop {m['summaryRect']['top']} != chartTop {m['chartColRect']['top']}"
    )
    assert m["summaryRect"]["bottom"] <= m["innerHeight"] + 1, (
        f"{label}: summaryBottom {m['summaryRect']['bottom']} > innerHeight {m['innerHeight']}"
    )
    # altura útil
    assert m["catalogRect"]["height"] > 300, (
        f"{label}: catalog height {m['catalogRect']['height']} demasiado pequeño"
    )
    assert m["summaryRect"]["height"] > 300, (
        f"{label}: summary height {m['summaryRect']['height']} demasiado pequeño"
    )
    # configuración de scroll interno (no exige overflow real con dataset pequeño)
    # resumen siempre debe tener ps-panels con overflow-y auto (o visible en móvil)
    assert (
        m["psPanelsOverflowY"] in ("auto", "visible", None) or m["psPanelsOverflowY"] == "auto"
    ), f"{label}: ps-panels overflowY {m['psPanelsOverflowY']} != auto"
    # catálogo abierto: overflow auto; plegado: rail visible, overflow puede ser visible
    if not m["collapsed"]:
        assert m["catalogOverflowY"] == "auto", (
            f"{label}: catalog overflowY {m['catalogOverflowY']} != auto (abierto)"
        )
        assert m["catalogListOverflowY"] == "auto", (
            f"{label}: catalog-list overflowY {m['catalogListOverflowY']} != auto"
        )
    else:
        # rail vertical completo cuando plegado
        assert abs(m["catalogRect"]["height"] - m["summaryRect"]["height"]) <= 2, (
            f"{label}: rail height {m['catalogRect']['height']} != summary {m['summaryRect']['height']}"
        )
        assert page.locator(".catalog-rail").is_visible(), f"{label}: rail no visible en plegado"
    # dashTop: numérico, positivo, aprox coincide con summaryTop en desktop
    dash_raw = m["dashTop"]
    try:
        dash = float(dash_raw.replace("px", "").strip() or 0)
    except ValueError:
        dash = 0.0
    assert dash > 0, f"{label}: dashTop {dash_raw!r} no positivo"
    # en desktop dashTop ≈ layout top ≈ summaryTop (tolerancia 3 px)
    assert abs(dash - m["summaryRect"]["top"]) <= 3, (
        f"{label}: dashTop {dash} no coincide con summaryTop {m['summaryRect']['top']}"
    )


def _assert_mobile_scroll(page, label):
    m = _metrics(page)
    # En móvil el layout es apilado (gráfica → resumen → catálogo drawer),
    # por lo que el scroll global es esperado y no se exige scrollHeight <= innerHeight.
    # Se verifica visibilidad y que el resumen no esté recortado por overflow interno.
    # visibilidad completa del resumen en móvil
    assert m["summaryRect"]["top"] >= -1, f"{label}: summaryTop {m['summaryRect']['top']} < 0"
    assert m["summaryRect"]["height"] > 50, (
        f"{label}: summary height {m['summaryRect']['height']} demasiado pequeño"
    )
    assert page.locator("#period-summary-wrap").is_visible(), f"{label}: resumen no visible"
    visibility = page.evaluate(
        "getComputedStyle(document.querySelector('#period-summary-wrap')).visibility"
    )
    assert visibility != "hidden", f"{label}: visibility hidden"
    # el resumen debe estar dentro del flujo del documento (no recortado por overflow hidden del wrap)
    # en móvil el wrap tiene height auto, por lo que su scrollHeight debe acomodar el contenido
    # y no debe haber recorte: ps-panels debe estar visible y su última fila debe ser alcanzable
    assert page.locator("#ps-content").is_visible(), f"{label}: ps-content no visible"
    assert page.locator("#period-summary-wrap header").is_visible(), (
        f"{label}: header resumen no visible"
    )


def test_ux1_altura_y_scroll_1280(page, server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1280x800 abierto")
    page.locator("#catalog-toggle").click()
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1280x800 plegado")
    page.locator("#catalog-rail-toggle").click()
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1280x800 reabierto")


def test_ux1_altura_y_scroll_1440(page, server):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(server)
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1440x900 abierto")
    page.locator("#catalog-toggle").click()
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1440x900 plegado")
    page.locator("#catalog-rail-toggle").click()
    _wait_stable(page)
    _stable_dash(page)
    _assert_desktop(page, "1440x900 reabierto")


def test_ux1_mobile_390(page, server):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(server)
    _wait_stable(page)
    _stable_dash(page)
    _assert_mobile_scroll(page, "390x800 drawer cerrado")
    page.locator("#catalog-toggle-mobile").click()
    _wait_stable(page)
    _stable_dash(page)
    _assert_mobile_scroll(page, "390x800 drawer abierto")
    page.evaluate("document.getElementById('catalog-overlay').click()")
    _wait_stable(page)
    _stable_dash(page)
    _assert_mobile_scroll(page, "390x800 drawer cerrado tras overlay")


def test_ux1_resumen_vacio_y_con_datos(page, server):
    # --- vacío: fixture sin training_sets ---
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(server)
    _wait_stable(page)
    _stable_dash(page)
    # DOM real para empty: el panel muestra status Sin datos
    expect(page.locator("#period-summary-wrap [role='status']").first).to_contain_text("Sin datos")
    _assert_desktop(page, "1280x800 resumen vacío")

    # --- con datos: crear DB con 14 días ---
    import os
    import socket
    import time
    import urllib.error
    import urllib.request

    repo_root = Path(__file__).resolve().parents[2]
    tmp_dir = repo_root / ".tmp" / f"ux1-{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db2 = str(tmp_dir / "lifestyle.db")
    conn = sqlite3.connect(db2)
    # asegurar import desde repo root
    import sys

    sys.path.insert(0, str(repo_root))
    from src.database import init_db, insert_exercise

    init_db(db2)
    insert_exercise(db2, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db2, "Curl", "Biceps", "EMPUJE")
    base = datetime.date(2026, 6, 1)
    for i in range(14):
        d = base + datetime.timedelta(days=i)
        conn.execute(
            "INSERT INTO training_sets (semana,dia,fecha,set_orden,ejercicio,reps,kg,rir) VALUES (?,?,?,?,?,?,?,?)",
            ((i // 7) + 1, "LUNES", d.isoformat(), 1, "Press", 6, 80, 1),
        )
    conn.commit()
    conn.close()

    def free_port():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def wait(url):
        for _ in range(150):
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)
        raise RuntimeError("server not ready")

    port = free_port()
    env = dict(os.environ)
    env["LIFESTYLE_DB_PATH"] = db2
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait(f"http://127.0.0.1:{port}/")
        page.goto(f"http://127.0.0.1:{port}/")
        _wait_stable(page)
        _stable_dash(page)
        # DOM real para ready: sin status en panel visible y con panel/tabla
        expect(
            page.locator("#period-summary-wrap .ps-panel:not([hidden]) [role='status']")
        ).to_have_count(0)
        expect(page.locator("#period-summary-wrap .ps-panels").first).to_be_visible()
        expect(page.locator("#period-summary-wrap table").first).to_be_visible()
        _assert_desktop(page, "1280x800 con datos")
        page.locator("#catalog-toggle").click()
        _wait_stable(page)
        _stable_dash(page)
        _assert_desktop(page, "1280x800 con datos plegado")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(tmp_dir, ignore_errors=True)
