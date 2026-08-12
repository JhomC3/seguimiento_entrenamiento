"""Browser tests: analysis view (day panel, KPIs, correlations)."""

import datetime

from playwright.sync_api import expect


def _iso(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _open_modal(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.click('[data-action="open-register-modal"]')
    page.wait_for_selector(
        '#register-modal-body #session-form input[name="fecha"]', state="attached", timeout=5000
    )
    page.wait_for_selector("#register-modal-body #nutrition-form", timeout=5000)


def _switch_session_tab(page):
    page.click('#register-tabs .pill[data-tab="session"]')
    expect(page.locator("#register-session")).to_be_visible()


def _fill_row(page, row, ejercicio="Press", kg="80", reps="8", rir="1"):
    r = page.locator("#set-rows .set-row").nth(row)
    r.locator("select[name='ejercicio']").select_option(ejercicio)
    r.locator('input[name="kg"]').fill(kg)
    r.locator('input[name="reps"]').fill(reps)
    r.locator('input[name="rir"]').fill(rir)


def _save_session(page):
    page.click('#edit-actions button[type="submit"]')
    expect(page.locator("#editor-notice .notice-success")).to_contain_text(
        "Entrenamiento guardado", timeout=3000
    )
    expect(page.locator("#editor-state")).to_have_attribute("data-readonly", "1", timeout=3000)


def _click_chart_day(page, iso):
    pos = page.evaluate(
        """(iso) => {
            const plotEl = document.getElementById('analysis-chart-plot');
            if (!plotEl || !plotEl._fullData || !plotEl._fullData.length) return null;
            const trace = plotEl._fullData[0];
            const idx = trace.x.findIndex(
                (v) => new Date(v).toISOString().slice(0, 10) === iso
            );
            const pts = plotEl.querySelectorAll('.point');
            if (idx < 0 || idx >= pts.length) return null;
            const r = pts[idx].getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }""",
        iso,
    )
    assert pos, f"no se encontró el marcador del día {iso}"
    page.mouse.click(pos["x"], pos["y"])


def test_kpis_reflect_saved_data(page, server):
    _open_modal(page, server)
    page.click('[data-action="close-register-modal"]')
    # Sin datos: KPIs vacíos ("—")
    expect(page.locator("#kpi-row")).to_contain_text("—")

    # Guardar una sesión desde el modal -> la gráfica y los KPIs se refrescan.
    page.click('[data-action="open-register-modal"]')
    _switch_session_tab(page)
    page.locator("#set-rows .set-row").first.locator("select[name='ejercicio']").select_option(
        "Press"
    )
    page.locator('input[name="kg"]').fill("80")
    page.locator('input[name="reps"]').fill("8")
    page.locator('input[name="rir"]').fill("0")
    _save_session(page)
    page.click('[data-action="close-register-modal"]')
    page.locator("#analysis-chart-plot .point").first.wait_for(state="visible", timeout=5000)
    expect(page.locator("#kpi-row")).to_contain_text("PFR actual", timeout=5000)
    expect(page.locator("#kpi-row")).to_contain_text("100.0%", timeout=5000)
    expect(page.locator("#kpi-row")).to_contain_text("Sets al fallo")


def test_fallo_day_highlights_next_day(page, server):
    _open_modal(page, server)
    iso = _iso(3)
    _switch_session_tab(page)
    page.locator(f'#register-modal-body .date-num[data-iso="{iso}"]').click()
    expect(page.locator("#session-form input[name='fecha']")).to_have_value(iso)
    page.wait_for_timeout(150)
    _fill_row(page, 0, rir="0")  # serie al fallo
    _save_session(page)
    page.click('[data-action="close-register-modal"]')
    page.locator("#analysis-chart-plot .point").first.wait_for(state="visible", timeout=5000)
    _click_chart_day(page, iso)
    expect(page.locator("#day-detail-wrap")).to_contain_text("FALLO", timeout=5000)
    expect(page.locator("#day-detail-wrap")).to_contain_text("día siguiente")
    # La banda de correlación se dibuja en la gráfica.
    shapes = page.evaluate(
        "() => { const el = document.getElementById('analysis-chart-plot');"
        " return (el.layout && el.layout.shapes || []).length; }"
    )
    assert shapes > 0, "debe existir la banda vertical del día siguiente"


def test_exercise_search_filters_chart(page, server):
    _open_modal(page, server)
    page.click('[data-action="close-register-modal"]')
    page.click('.pills-track .pill[data-nivel="ejercicio"]')
    expect(page.locator("#analysis-filters .exercise-search")).to_be_visible(timeout=3000)
    search = page.locator("#analysis-filters .exercise-search")
    search.fill("Press")
    search.press("Enter")
    page.wait_for_timeout(800)
    # La píldora de nivel y el buscador se mantienen; la gráfica refetchea sin error.
    expect(page.locator("#analysis-chart-wrap")).to_be_visible()


def test_register_modal_tabs_switch_panels(page, server):
    _open_modal(page, server)
    expect(page.locator("#register-nutrition")).to_be_visible()
    expect(page.locator("#register-session")).to_be_hidden()
    page.click('#register-tabs .pill[data-tab="session"]')
    expect(page.locator("#register-session")).to_be_visible()
    expect(page.locator("#register-nutrition")).to_be_hidden()
    page.click('#register-tabs .pill[data-tab="nutrition"]')
    expect(page.locator("#register-nutrition")).to_be_visible()
