"""Auditoría funcional de UI (barrido Playwright).

Recorre las rutas y estados del dashboard con un navegador real y captura:
  - errores de consola y excepciones JS no capturadas
  - requests fallidas / 4xx / 5xx / errores de red
  - ausencia de marcadores de contrato (IDs, data-action)
  - data-action visibles sin handler conocido en el JS
  - screenshot PNG por estado

Uso:
    uv run python scripts/audit_ui.py [--db .tmp/audit/lifestyle.db]
        [--out .tmp/audit] [--report docs/analysis/2026-08-15-ui-audit.md]
        [--no-server] [--base http://127.0.0.1:PORT]

El servidor se levanta en un puerto libre con LIFESTYLE_DB_PATH apuntando a
una copia de la DB real (nunca toca la original).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JS_GLOB = ROOT / "static" / "js"
TEMPLATES_GLOB = ROOT / "templates"

# Marcadores de contrato (docs/architecture/current-ui-contract.md).
INDEX_MARKERS = [
    "#app-config",
    "#cascade-row .level-chip",
    "#unified-chart",
    "#notice-container",
    "#editor-popup",
    "#confirm-modal",
]
POPUP_MARKERS = [
    "#popup-body #date-navigator",
    "#popup-body #session-date-title",
    "#popup-body #nutrition-editor-wrap",
    "#popup-body #session-editor-wrap",
    "#popup-body #cardio-day",
    "#popup-body #exercise-create",
    "#popup-body #alimento-create",
    "#popup-body #plantillas-section",
    "#popup-body #editor-notice",
    "#popup-body #save-outcome",
]


class Audit:
    """Acumula hallazgos y capturas de red/consola de una sesión."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.bad_responses: list[str] = []
        self.network_failures: list[str] = []
        self.findings: list[dict] = []
        self.step_counter = 0

    # -- eventos de página -------------------------------------------------
    def on_console(self, msg) -> None:
        if msg.type in ("error",):
            self.console_errors.append(msg.text)

    def on_pageerror(self, exc) -> None:
        self.page_errors.append(str(exc))

    def on_response(self, resp: Response) -> None:
        if resp.status >= 400:
            self.bad_responses.append(f"{resp.status} {resp.url}")

    def on_requestfailed(self, req) -> None:
        self.network_failures.append(f"{req.method} {req.url} :: {req.failure}")

    def attach(self, page: Page) -> None:
        page.on("console", self.on_console)
        page.on("pageerror", self.on_pageerror)
        page.on("response", self.on_response)
        page.on("requestfailed", self.on_requestfailed)

    # -- helpers ------------------------------------------------------------
    def screenshot(self, page: Page, name: str) -> str:
        path = self.out_dir / "screenshots" / f"{self.step_counter:02d}-{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)

    def step(self, page: Page, name: str, label: str) -> str:
        self.step_counter += 1
        shot = self.screenshot(page, name)
        errors = self.console_errors[:]
        self.console_errors = []
        if errors:
            self.add("P0", "consola", f"{label}: {len(errors)} error(es) de consola", errors, shot)
        if self.page_errors:
            self.add(
                "P0",
                "js",
                f"{label}: excepción JS no capturada",
                self.page_errors[:],
                shot,
            )
            self.page_errors = []
        if self.network_failures:
            self.add(
                "P1",
                "red",
                f"{label}: {len(self.network_failures)} fallo(s) de red",
                self.network_failures[:],
                shot,
            )
            self.network_failures = []
        if self.bad_responses:
            self.add(
                "P0" if any(r.startswith("5") for r in self.bad_responses) else "P1",
                "http",
                f"{label}: {len(self.bad_responses)} respuesta(s) HTTP ≥400",
                self.bad_responses[:],
                shot,
            )
            self.bad_responses = []
        return shot

    def check_markers(self, page: Page, label: str, markers: list[str], shot: str) -> None:
        missing = []
        for sel in markers:
            if page.locator(sel).count() == 0:
                missing.append(sel)
        if missing:
            self.add("P0", "contrato", f"{label}: marcadores ausentes", missing, shot)

    def check_actions(self, page: Page, known: set[str], label: str, shot: str) -> None:
        dom_actions = page.eval_on_selector_all(
            "[data-action]", "els => Array.from(new Set(els.map(e => e.dataset.action)))"
        )
        unknown = sorted(a for a in dom_actions if a not in known)
        if unknown:
            self.add(
                "P1",
                "contrato",
                f"{label}: data-action sin handler conocido",
                unknown,
                shot,
            )

    def add(self, sev: str, area: str, title: str, detail: list[str], shot: str) -> None:
        self.findings.append(
            {
                "severity": sev,
                "area": area,
                "title": title,
                "detail": detail,
                "screenshot": Path(shot).name,
            }
        )


# ---------------------------------------------------------------------------
# Acciones conocidas: las que el JS declara como handler (case / === '...').
# ---------------------------------------------------------------------------
def known_actions() -> set[str]:
    actions: set[str] = set()
    pat = re.compile(
        r"""(?:(?:dataset\.action|action)\s*===\s*|data-action\s*=\s*|case\s+)['"]([a-z-]+)['"]"""
    )
    for js in JS_GLOB.glob("*.js"):
        text = js.read_text(encoding="utf-8")
        for m in pat.finditer(text):
            actions.add(m.group(1))
    return actions


# ---------------------------------------------------------------------------
# Servidor temporal
# ---------------------------------------------------------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(base: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            last = e
            time.sleep(0.2)
    raise RuntimeError(f"servidor no respondió: {last}")


def start_server(db: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = dict(os.environ)
    env["LIFESTYLE_DB_PATH"] = str(db)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_ready(base)
    except Exception:
        out, _ = proc.communicate(timeout=5)
        proc.kill()
        raise RuntimeError(f"arranque fallido:\n{out.decode()[-3000:]}")
    return proc, base


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Pasos del barrido
# ---------------------------------------------------------------------------
def wait_ready_dom(page: Page) -> None:
    page.wait_for_function("document.body.dataset.appReady === '1'", timeout=15000)


def open_popup(page: Page, base: str) -> None:
    page.goto(base + "/")
    wait_ready_dom(page)
    page.click('[data-action="open-editor-popup"]')
    page.wait_for_selector("#popup-body #session-editor-wrap", timeout=8000)
    page.wait_for_selector("#popup-body #nutrition-form", timeout=8000)


def audit_routes(page: Page, base: str, audit: Audit, known: set[str], db: Path) -> None:
    # 1. Index
    page.goto(base + "/")
    wait_ready_dom(page)
    shot = audit.step(page, "index", "GET /")
    audit.check_markers(page, "index", INDEX_MARKERS, shot)
    audit.check_actions(page, known, "index", shot)
    # JSON de config válido
    cfg = page.eval_on_selector(
        "#app-config",
        "el => { try { JSON.parse(el.textContent); return true; } catch { return false; } }",
    )
    if not cfg:
        audit.add("P0", "contrato", "index: #app-config no es JSON válido", [], shot)

    # 2. Cascada: músculo -> ejercicios -> detalle
    first_muscle = page.locator("#cascade-row .level-chip").first
    n_muscles = page.locator("#cascade-row .level-chip").count()
    if n_muscles == 0:
        audit.add("P1", "contrato", "index: sin chips de músculos", [], shot)
    else:
        first_muscle.click()
        page.wait_for_selector("#ejercicios-row .exercise-chip", timeout=8000)
        page.wait_for_timeout(400)
        shot = audit.step(page, "muscle", "cascada: selección de músculo")
        audit.check_markers(
            page, "músculo", ["#ejercicios-row .exercise-chip", "#unified-chart"], shot
        )
        audit.check_actions(page, known, "músculo", shot)
        if page.locator("#ejercicios-row .exercise-chip").count() > 0:
            page.locator("#ejercicios-row .exercise-chip").first.click()
            page.wait_for_timeout(800)
            shot = audit.step(page, "exercise", "cascada: selección de ejercicio")
            audit.check_actions(page, known, "ejercicio", shot)

    # 3. Popup de registro
    open_popup(page, base)
    shot = audit.step(page, "popup", "popup de registro")
    audit.check_markers(page, "popup", POPUP_MARKERS, shot)
    audit.check_actions(page, known, "popup", shot)
    nav_markers = ["#popup-body .date-num", "#popup-body .today-btn", "#popup-body #date-jump"]
    audit.check_markers(page, "navegador", nav_markers, shot)

    # 4. Fecha con datos (dot) en el navegador del popup
    dotted = page.locator("#popup-body .date-num .date-dot").count()
    if dotted > 0:
        page.locator("#popup-body .date-num .date-dot").first.click()
        page.wait_for_timeout(700)
        shot = audit.step(page, "fecha-datos", "popup: fecha con datos")
        has_rows = page.locator("#popup-body #set-rows .set-row").count() > 0
        if not has_rows:
            audit.add("P1", "funcional", "popup: fecha con dot sin filas en el editor", [], shot)
    else:
        audit.add("P2", "funcional", "popup: sin fechas con datos (dot) en el rango", [], shot)

    # 5. Editor: toggle edición + guardar sesión (fecha futura SIN datos)
    import sqlite3 as _sqlite3

    _conn = _sqlite3.connect(str(db))
    _taken = {r[0] for r in _conn.execute("SELECT DISTINCT fecha FROM training_sets").fetchall()}
    _conn.close()
    iso_future = ""
    for _d in range(1, 45):
        _iso = (datetime.date.today() + datetime.timedelta(days=_d)).isoformat()
        if _iso not in _taken:
            iso_future = _iso
            break
    if not iso_future:
        audit.add("P1", "funcional", "editor: no hay fecha futura vacía en 45 días", [], "")
        return
    # Navegación precisa al día futuro vía input date (fill + change explícito)
    page.fill("#popup-body #date-jump", iso_future)
    page.eval_on_selector(
        "#popup-body #date-jump",
        "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
    )
    page.wait_for_timeout(700)
    editmode = page.locator("#popup-body #session-editor").get_attribute("data-editmode")
    if editmode != "1":
        audit.add(
            "P1",
            "funcional",
            f"editor: fecha {iso_future} no quedó en modo edición (editmode={editmode})",
            [],
            audit.screenshot(page, "editor-editmode"),
        )
    page.locator("#popup-body [data-action='toggle-edit']").click()
    page.wait_for_timeout(300)
    shot = audit.step(page, "editor-editmode", "editor: modo edición")
    # completar primera fila
    row = page.locator("#popup-body #set-rows .set-row").first
    selects = row.locator("select[name='ejercicio']")
    opts = selects.locator("option").all_inner_texts()
    if len(opts) > 1:
        selects.select_option(opts[1])
        row.locator('input[name="kg"]').fill("80")
        row.locator('input[name="reps"]').fill("8")
        row.locator('input[name="rir"]').fill("1")
        state = page.eval_on_selector_all(
            "#popup-body",
            """els => { const ed = document.querySelector('#popup-body #session-editor');
                const st = document.querySelector('#popup-body #editor-state');
                const act = document.querySelector('#popup-body #edit-actions');
                return { editmode: ed?.dataset.editmode, readonly: st?.dataset.readonly,
                    hasData: st?.dataset.hasData, actionsInvisible: act?.classList.contains('invisible'),
                    fecha: document.querySelector('#popup-body #session-form input[name="fecha"]')?.value,
                    rows: document.querySelectorAll('#popup-body #set-rows .set-row').length }; }""",
        )
        shot = audit.screenshot(page, "editor-prefill")
        if state["actionsInvisible"]:
            audit.add(
                "P1",
                "funcional",
                f"editor: #edit-actions invisible tras llenar fila ({state})",
                [],
                shot,
            )
        try:
            page.click("#popup-body #edit-actions button[type='submit']", timeout=8000)
            page.wait_for_selector("#popup-body #editor-notice .notice-success", timeout=5000)
            page.wait_for_timeout(400)
            shot = audit.step(page, "editor-guardar", "editor: guardar sesión")
            if page.locator("#popup-body #editor-state").get_attribute("data-readonly") != "1":
                audit.add("P1", "funcional", "editor: guardado sin pasar a readonly", [], shot)
        except Exception:
            shot = audit.step(page, "editor-guardar-err", "editor: guardar sesión (fallo)")
            audit.add("P0", "funcional", "editor: guardar sesión no muestra éxito", [], shot)

    # 6. Alimentación: toggle edición + guardar
    page.locator("#popup-body [data-action='nutrition-toggle-edit']").click()
    page.wait_for_timeout(300)
    shot = audit.step(page, "nutrition-editmode", "nutrición: modo edición")
    nrows = page.locator("#popup-body #nutrition-rows .nutrition-row").count()
    if nrows == 0:
        audit.add("P1", "funcional", "nutrición: sin filas en modo edición", [], shot)
    audit.check_actions(page, known, "nutrición", shot)

    # 7. Cardio: día con EXERCISE_SESSION espejadas (2026-08-14 en la DB real).
    #    Se ejecuta ANTES de mutaciones del editor para que la navegación sea limpia.
    page.fill("#popup-body #date-jump", "2026-08-14")
    page.eval_on_selector(
        "#popup-body #date-jump",
        "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
    )
    page.wait_for_timeout(700)
    fecha_actual = page.locator('#popup-body #session-form input[name="fecha"]').input_value()
    shot = audit.step(page, "cardio", "panel cardio (2026-08-14)")
    audit.check_markers(page, "cardio", ["#popup-body #cardio-day"], shot)
    cardio_forms = page.locator(
        "#popup-body #cardio-day form[data-action='cardio-annotation-save']"
    )
    if cardio_forms.count() == 0:
        audit.add(
            "P1",
            "funcional",
            "cardio: día con EXERCISE_SESSION sin formularios de anotación",
            [f"fecha_editor={fecha_actual!r}", f"forms={cardio_forms.count()}"],
            shot,
        )
    else:
        # Guardar una anotación real en la primera sesión
        first = cardio_forms.first
        try:
            first.locator('input[name="velocidad_kmh"]').fill("9.5")
            first.get_by_role("button", name="Guardar").click(timeout=5000)
            page.wait_for_timeout(700)
            shot = audit.step(page, "cardio-guardar", "cardio: guardar anotación")
            notice_ok = page.locator("#notice-container .notice-success").count()
            saved = (
                page.locator("#popup-body #cardio-day form[data-action='cardio-annotation-save']")
                .first.locator('input[name="velocidad_kmh"]')
                .input_value()
            )
            if notice_ok == 0 and saved != "9.5":
                audit.add(
                    "P0",
                    "funcional",
                    "cardio: guardar anotación sin confirmación",
                    [f"saved={saved!r}"],
                    shot,
                )
        except Exception:
            shot = audit.step(page, "cardio-guardar-err", "cardio: guardar anotación (fallo)")
            audit.add("P0", "funcional", "cardio: guardar anotación falló", [], shot)

    # 7b. Plantillas de alimentación (existen en la DB real)
    meal_cards = page.locator("#popup-body #nutrition-templates .pt-card")
    if meal_cards.count() > 0:
        try:
            meal_cards.first.get_by_role("button", name="Aplicar").click(timeout=5000)
            page.wait_for_timeout(500)
            # Confirmación de reemplazo si el día tiene filas
            if page.locator("#confirm-modal[open]").count() > 0:
                page.locator("#confirm-save").click()
                page.wait_for_timeout(700)
            shot = audit.step(page, "meal-plantilla-aplicar", "aplicar plantilla de comida")
            if page.locator("#popup-body #nutrition-form").count() == 0:
                audit.add("P1", "funcional", "meal: aplicar plantilla perdió el editor", [], shot)
        except Exception:
            shot = audit.step(page, "meal-plantilla-err", "aplicar plantilla de comida (fallo)")
            audit.add("P0", "funcional", "meal: aplicar plantilla no funcionó", [], shot)
    else:
        audit.add("P2", "contrato", "meal: sin plantillas de alimentación para probar", [], shot)

    # 7c. Plantillas de entrenamiento: aplicar (exige modo edición) en fecha futura vacía
    pt_cards = page.locator("#popup-body #plantillas-list .pt-card")
    if pt_cards.count() > 0:
        page.fill("#popup-body #date-jump", iso_future)
        page.eval_on_selector(
            "#popup-body #date-jump",
            "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
        )
        page.wait_for_timeout(600)
        page.locator("#popup-body [data-action='toggle-edit']").click()
        page.wait_for_timeout(300)
        try:
            page.locator("#popup-body .pt-card").first.get_by_role("button", name="Aplicar").click(
                timeout=5000
            )
            page.wait_for_timeout(500)
            if page.locator("#confirm-modal[open]").count() > 0:
                page.locator("#confirm-save").click()
                page.wait_for_timeout(600)
            shot = audit.step(page, "plantilla-aplicar", "aplicar plantilla de entreno")
            has_data = page.locator("#popup-body #editor-state").get_attribute("data-has-data")
            notice_ok = page.locator("#popup-body #editor-notice .notice-success").count()
            if has_data != "1" and notice_ok == 0:
                audit.add(
                    "P1",
                    "funcional",
                    "plantilla: aplicar no marcó datos ni mostró éxito",
                    [f"has_data={has_data}"],
                    shot,
                )
        except Exception:
            shot = audit.step(page, "plantilla-aplicar-err", "aplicar plantilla (fallo)")
            audit.add("P0", "funcional", "plantilla: aplicar no funcionó", [], shot)
    else:
        audit.add("P2", "contrato", "plantillas: sin tarjetas para probar aplicar", [], shot)

    # 8. Undo visible via Ctrl+Z (pila persistente tiene entradas reales)
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+z")
    page.wait_for_timeout(900)
    shot = audit.step(page, "undo", "undo (Ctrl+Z)")
    if (
        page.locator("#notice-container .notice-success, #editor-notice .notice-success").count()
        == 0
    ):
        # Puede ser "Nada que deshacer." (error notice) si la pila quedó vacía
        err = (
            page.locator("#notice-container .notice-error").inner_text()
            if page.locator("#notice-container .notice-error").count()
            else ""
        )
        if "Nada que deshacer" not in err:
            audit.add(
                "P1",
                "funcional",
                "undo: Ctrl+Z sin respuesta esperada",
                [f"error={err!r}"],
                shot,
            )

    # 9. Exports
    for path, fname in [
        ("/exportar/health-connect.csv", "health_connect.csv"),
    ]:
        try:
            with urllib.request.urlopen(base + path, timeout=10) as r:
                body = r.read(3)
                ok = r.status == 200 and body.startswith(b"\xef\xbb\xbf")
                if not ok:
                    audit.add(
                        "P0" if r.status >= 500 else "P1",
                        "export",
                        f"{path}: status {r.status} o sin BOM",
                        [f"bom={body!r}"],
                        "",
                    )
        except Exception as e:
            audit.add("P1", "export", f"{path}: error de descarga", [str(e)], "")

    # 10. /nivel y /grafica (fragmentos)
    page.goto(base + "/nivel?tipo=global")
    page.wait_for_timeout(600)
    shot = audit.step(page, "nivel-global", "GET /nivel?tipo=global")
    audit.check_markers(page, "nivel-global", ["#cascade-row .level-chip"], shot)
    muscle = page.locator("#cascade-row .level-chip").first
    if muscle.count() > 0:
        foco = muscle.get_attribute("data-foco")
        page.goto(base + f"/grafica?musculo={foco}")
        page.wait_for_timeout(600)
        shot = audit.step(page, "grafica", f"GET /grafica?musculo={foco}")
        if page.locator("#unified-chart").count() == 0:
            audit.add("P1", "contrato", "grafica: fragmento sin #unified-chart", [], shot)


def main() -> int:
    ap = argparse.ArgumentParser(description="Barrido de auditoría funcional de UI")
    ap.add_argument("--db", default=str(ROOT / ".tmp/audit/lifestyle.db"))
    ap.add_argument("--out", default=str(ROOT / ".tmp/audit"))
    ap.add_argument("--report", default=str(ROOT / ".tmp/audit/report-auto.md"))
    ap.add_argument("--no-server", action="store_true", help="usar --base ya levantado")
    ap.add_argument("--base", default="")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(exist_ok=True)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no existe {db}", file=sys.stderr)
        return 2

    proc = None
    if args.no_server:
        base = args.base or "http://127.0.0.1:8000"
        wait_ready(base)
    else:
        proc, base = start_server(db)

    audit = Audit(out_dir)
    known = known_actions()
    print(f"Acciones conocidas en JS: {len(known)}")

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            audit.attach(page)
            audit_routes(page, base, audit, known, db)
            browser.close()
    finally:
        if proc:
            stop_server(proc)

    # Reporte
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Informe de Auditoría Funcional de UI (2026-08-15)",
        "",
        (
            f"> Barrido automatizado con Playwright sobre copia de la DB real "
            f"(`{db.name}`). {len(audit.findings)} hallazgo(s)."
        ),
        "",
        "## Hallazgos",
        "",
    ]
    if not audit.findings:
        lines.append("Sin hallazgos.")
    for f in audit.findings:
        lines.append(f"### {f['severity']} — {f['title']}")
        lines.append("")
        lines.append(f"- **Área:** {f['area']}")
        if f["detail"]:
            for d in f["detail"]:
                lines.append(f"- `{d}`")
        if f["screenshot"]:
            lines.append(f"- Screenshot: `screenshots/{f['screenshot']}`")
        lines.append("")
    report.write_text("\n".join(lines), encoding="utf-8")

    (out_dir / "findings.json").write_text(
        json.dumps(audit.findings, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    by_sev = {"P0": 0, "P1": 0, "P2": 0}
    for f in audit.findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    print(
        f"HALLAZGOS: P0={by_sev['P0']} P1={by_sev['P1']} P2={by_sev['P2']} total={len(audit.findings)}"
    )
    print(f"Reporte: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
