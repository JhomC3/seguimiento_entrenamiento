"""Browser: sección Salud en el panel izquierdo + gráfica única de métricas.

La gráfica vive en el slot de nutrition-trend (ids reutilizados); el catálogo
vive dentro de #dashboard-catalog-list. Sin red no hay Plotly: las aserciones
de rangos se omiten con skip explícito.
"""

import json
import sqlite3
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect


def _seed_health(db_path, days=70):
    base = datetime(2026, 6, 10, 9, 0, 0, tzinfo=UTC)
    conn = sqlite3.connect(str(db_path))
    for d in range(days):
        start = base + timedelta(days=d)
        end = start + timedelta(hours=1)
        payload = json.dumps(
            {
                "hc_id": f"seed-{d}",
                "record_type": "STEPS_H1",
                "revision": 1,
                "start_epoch_ms": int(start.timestamp() * 1000),
                "value": {"count": 5000 + d},
            }
        )
        conn.execute(
            "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms,"
            " last_modified_epoch_ms, payload_schema_version, value_json, device_id,"
            " received_at, updated_at) VALUES (?, 'STEPS_H1', ?, ?, ?, 1, ?, '', 'x', 'x')",
            (
                f"seed-{d}",
                int(start.timestamp() * 1000),
                int(end.timestamp() * 1000),
                int(start.timestamp() * 1000),
                payload,
            ),
        )
    for d in range(10):
        day_ts = int((base + timedelta(days=d)).timestamp() * 1000)
        conn.execute(
            "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms,"
            " last_modified_epoch_ms, payload_schema_version, value_json, device_id,"
            " received_at, updated_at) VALUES (?, 'WEIGHT', ?, ?, ?, 1, ?, '', 'x', 'x')",
            (
                f"seed-w-{d}",
                day_ts,
                day_ts,
                day_ts,
                json.dumps({"value": {"kg": 70.0 + d * 0.1}}),
            ),
        )
    conn.commit()
    conn.close()


def _require_plotly(page):
    try:
        page.wait_for_function("typeof window.Plotly !== 'undefined'", timeout=15000)
    except Exception:  # noqa: BLE001 - sin red no hay Plotly: skip, no fallo
        pytest.skip("Plotly por CDN no disponible (sin red)")


def test_metrics_section_in_catalog(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    section = page.locator("#metrics-catalog")
    expect(section).to_be_attached()
    expect(section).to_contain_text("Salud")
    chips = page.locator("#metrics-catalog [data-metric]")
    expect(chips.first).to_be_attached()
    expect(
        page.locator('#metrics-catalog [data-metric][aria-pressed="true"]').first
    ).to_be_attached()
    # Series sin datos: deshabilitadas con aria-disabled, visibles en lista.
    expect(page.locator('#metrics-catalog [data-metric="vo2max"]').first).to_have_attribute(
        "aria-disabled", "true"
    )


def test_metrics_single_chart_slot(page, server, server_db_path):
    _seed_health(server_db_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    expect(page.locator("#nutrition-trend-header")).to_contain_text("Métricas")
    expect(page.locator("#nutrition-trend-empty")).to_be_hidden()


def test_metrics_toggle_updates_url(page, server, server_db_path):
    _seed_health(server_db_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.locator(
        '#metrics-catalog [data-action="toggle-metric-group"][data-mgroup="Actividad"]'
    ).click()
    chip = page.locator('#metrics-catalog [data-metric="steps"]').first
    before = chip.get_attribute("aria-pressed")
    chip.click()
    expect(chip).not_to_have_attribute("aria-pressed", before)
    assert "metricas=" in page.url


def test_metrics_groups_collapse(page, server):
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    toggle = page.locator(
        '#metrics-catalog [data-action="toggle-metric-group"][data-mgroup="Actividad"]'
    )
    panel = page.locator("#metrics-catalog #db-metrics-2")
    expect(panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    expect(panel).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(panel).to_be_hidden()


def test_metrics_toggle_visibility_roundtrip(page, server, server_db_path):
    _seed_health(server_db_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _require_plotly(page)
    page.locator(
        '#metrics-catalog [data-action="toggle-metric-group"][data-mgroup="Vitales"]'
    ).click()
    chip = page.locator('#metrics-catalog [data-metric="weight"]').first
    n_scatter = (
        "() => document.getElementById('nutrition-trend-plot')"
        ".querySelectorAll('.scatterlayer .trace').length"
    )
    assert page.evaluate(n_scatter) >= 1  # peso MA7 prendido por defecto
    chip.click()
    page.wait_for_function(
        "() => document.getElementById('nutrition-trend-plot')"
        ".querySelectorAll('.scatterlayer .trace').length === 0"
    )
    chip.click()
    page.wait_for_function(
        "() => document.getElementById('nutrition-trend-plot')"
        ".querySelectorAll('.scatterlayer .trace').length >= 1"
    )


def test_granularity_keeps_selection(page, server, server_db_path):
    _seed_health(server_db_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    page.locator(
        '#metrics-catalog [data-action="toggle-metric-group"][data-mgroup="Actividad"]'
    ).click()
    # steps arranca apagado (defaults: peso + kcal): prender y apagar para
    # dejarlo explícitamente fuera antes del cambio de granularidad.
    page.locator('#metrics-catalog [data-metric="steps"]').first.click()
    page.locator('#metrics-catalog [data-metric="steps"]').first.click()
    with page.expect_request(
        lambda r: "/grafica" in r.url and "gran=week" in r.url and "metricas=" in r.url
    ) as req_info:
        page.locator('#granularity-selector [data-gran="week"]').click()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(req_info.value.url).query)
    assert "steps" not in query.get("metricas", [""])[0].split(",")
    assert "gran=week" in page.url
    page.wait_for_function(
        """() => {
            try {
                const fig = JSON.parse(
                    document.getElementById('nutrition-trend-data').textContent
                );
                const t = fig.data.find((tr) => tr.meta === 'steps');
                return t && t.visible === false;
            } catch (e) {
                return false;
            }
        }""",
        timeout=10000,
    )


def test_axis_anchor_follows_pan(page, server, server_db_path):
    _seed_health(server_db_path)
    conn = sqlite3.connect(str(server_db_path))
    conn.execute(
        "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press')"
    )
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
        "VALUES (1, 'LUNES', '2026-06-10', 1, 'Press', 8, 80, 2),"
        "       (5, 'LUNES', '2026-07-10', 1, 'Press', 8, 90, 2),"
        "       (10, 'LUNES', '2026-08-18', 1, 'Press', 8, 100, 2)"
    )
    conn.commit()
    conn.close()
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    _require_plotly(page)
    page.wait_for_function(
        "() => document.getElementById('unified-chart-plot')._fullData"
        " && document.getElementById('nutrition-trend-plot')._fullData"
    )
    ranges = page.evaluate(
        """() => {
            const num = (id) => document.getElementById(id)._fullLayout.xaxis.range.map((v) => Date.parse(v));
            const a = num('unified-chart-plot');
            const b = num('nutrition-trend-plot');
            return Math.abs(a[0] - b[0]) < 60000 && Math.abs(a[1] - b[1]) < 60000
                ? 'aligned'
                : ('MISALIGNED ' + a + ' vs ' + b);
        }"""
    )
    assert ranges == "aligned", ranges
    page.evaluate(
        """() => Plotly.relayout(document.getElementById('unified-chart-plot'),
            {'xaxis.range[0]': '2026-07-01', 'xaxis.range[1]': '2026-07-10'})"""
    )
    page.wait_for_function(
        """() => {
            const num = (id) => document.getElementById(id)._fullLayout.xaxis.range.map((v) => Date.parse(v));
            const a = num('unified-chart-plot');
            const b = num('nutrition-trend-plot');
            return Math.abs(a[0] - b[0]) < 60000 && Math.abs(a[1] - b[1]) < 60000;
        }""",
        timeout=5000,
    )


def test_granularity_refreshes_metrics(page, server, server_db_path):
    _seed_health(server_db_path)
    page.goto(server)
    page.wait_for_function("document.body.dataset.appReady === '1'")
    with page.expect_request(lambda r: "/grafica" in r.url and "gran=week" in r.url):
        page.locator('#granularity-selector [data-gran="week"]').click()
    assert "gran=week" in page.url
