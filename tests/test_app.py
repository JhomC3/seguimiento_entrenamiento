import datetime
import os
import re
import sqlite3

from fastapi.testclient import TestClient

import app as appmod
from src.database import get_plantillas, get_sets_by_fecha, init_db, insert_exercise
from src.mutation_service import clear_undo_stack, undo_stack_size
from src.security import get_csrf_secret, make_csrf_token
from src.training_service import fecha_to_db, save_session


def _client():
    return TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})


def _setup_db(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    return db


def _fecha(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def test_saved_today_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha()}")
    assert "pencil-btn off" in r.text
    assert 'duration-150 hidden"' in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text
    assert 'id="edit-actions" class="mt-1 h-7 flex items-center gap-2 invisible"' in r.text
    assert 'aria-label="Cancelar"' in r.text
    assert "rm-cell" in r.text


def test_saved_future_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(1), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "pencil-btn off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text


def test_empty_future_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "pencil-btn on" in r.text
    assert "transition-opacity duration-150" in r.text
    assert 'duration-150 hidden"' not in r.text
    assert 'data-readonly="0"' in r.text
    assert 'data-has-data="0"' in r.text
    assert 'id="edit-actions" class="mt-1 h-7 flex items-center gap-2 invisible"' in r.text
    assert 'aria-label="Cancelar"' in r.text


def test_empty_today_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha()}")
    assert "pencil-btn on" in r.text


def test_empty_past_is_readonly_with_fallback_row(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha(-2)}")
    assert "pencil-btn off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="0"' in r.text
    assert r.text.count('<tr class="set-row') == 1


def test_index_uses_stable_card(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert 'id="session-editor" data-editmode="0"' in r.text
    assert 'id="session-editor-wrap"' in r.text
    assert "rm-cell" in r.text
    assert 'id="save-outcome" data-ok="0" hidden' in r.text
    assert '<div id="editor-notice"></div>' in r.text


def test_save_valid_returns_ok_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="1"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "Entrenamiento guardado" in r.text


def test_save_invalid_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": [""],
            "kg": ["80"],
            "reps": ["8"],
            "rir": [""],
        },
    )
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="0"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "notice-error" in r.text
    assert 'data-ok="1"' not in r.text


def test_save_empty_rir_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": [""],
        },
    )
    assert 'data-ok="0"' in r.text
    assert "RIR" in r.text


def test_save_zero_rir_succeeds(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["0"],
        },
    )
    assert 'data-ok="1"' in r.text


def test_index_renders_plantillas_section(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert 'id="plantillas-section"' in r.text
    assert "Aún no hay entrenos" in r.text


def test_plantilla_guardar_crea_y_oob(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/plantilla/guardar",
        data={
            "nombre": "Mi Empuje",
            "ejercicio": ["Press"],
        },
    )
    assert "Entreno guardado" in r.text
    assert 'id="plantillas-section" hx-swap-oob="outerHTML"' in r.text


def test_plantilla_guardar_mismo_nombre_actualiza(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    assert "Entreno actualizado" in r.text


def test_plantilla_guardar_sin_ejercicios_error(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post("/plantilla/guardar", data={"nombre": "Vacia", "ejercicio": []})
    assert "notice-error" in r.text
    assert "al menos un ejercicio" in r.text


def test_plantilla_eliminar(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.post("/plantilla/eliminar/1")
    assert "Entreno eliminado" in r.text
    assert "Aún no hay entrenos" in r.text


def test_plantilla_aplicar_rellena_con_ultimos_valores(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    insert_exercise(db, "Curl", "Biceps", "TIRON")
    save_session(db, _fecha(-3), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    save_session(db, _fecha(-2), [{"ejercicio": "Curl", "kg": 16, "reps": 10, "rir": 0}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press", "Curl"]})
    r = client.get("/plantilla/aplicar/1", params={"fecha": _fecha()})
    assert 'id="session-editor-wrap" hx-swap-oob="innerHTML"' in r.text
    assert 'data-readonly="0"' in r.text
    assert "Press" in r.text and "Curl" in r.text
    assert 'value="80"' in r.text and 'value="16"' in r.text
    assert "Entreno aplicado" in r.text


def test_plantilla_editar_renombra(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    insert_exercise(db, "Curl", "Biceps", "TIRON")
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.post(
        "/plantilla/editar/1", data={"nombre": "Mi Torso", "ejercicio": ["Press", "Curl"]}
    )
    assert "Entreno guardado" in r.text
    assert "Mi Torso" in r.text


def test_plantillas_view_editar_expande_formulario(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.get("/plantillas", params={"editar": 1})
    assert 'id="plantilla-edit-rows"' in r.text
    assert 'hx-post="/plantilla/editar/1"' in r.text


def test_plantilla_reordenar(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    r = client.post("/plantilla/reordenar", data={"id": ["2", "1"]})
    assert r.status_code == 200
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["B", "A"]


def test_eliminar_sesion_vacia_el_dia(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post("/entrenamiento/session/eliminar", data={"fecha": _fecha()})
    assert 'data-ok="1"' in r.text
    assert "Entreno eliminado" in r.text
    assert 'data-has-data="0"' in r.text
    assert get_sets_by_fecha(db, fecha_to_db(datetime.date.today())) == []


def test_editor_botones_texto_en_panel_e_iconos_en_form(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha()}")
    assert ">Guardar</button>" in r.text
    assert ">Cancelar</button>" in r.text
    assert 'class="btn-x"' in r.text
    assert 'class="btn-check"' in r.text
    assert "undo-btn" not in r.text


def test_editor_usa_hooks_de_controles_compactos(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    html = _client().get(f"/fecha/editor?fecha={_fecha()}").text

    assert 'class="editor-header-actions' in html
    assert 'class="row-actions' in html
    assert 'class="set-actions-column' in html


def test_undo_sesion_restaura_filas(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    r = client.post("/undo", data={"fecha": _fecha()})
    assert "Acción deshecha" in r.text
    assert 'data-ok="1"' in r.text
    assert 'id="session-editor-wrap" hx-swap-oob="innerHTML"' in r.text
    assert get_sets_by_fecha(db, fecha_to_db(datetime.date.today())) == []


def test_undo_sesion_fecha_distinta_no_swapea_editor(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    r = client.post("/undo", data={"fecha": _fecha(5)})
    assert "Acción deshecha" in r.text
    assert 'id="undo-result"' in r.text
    assert f'data-fecha="{_fecha()}"' in r.text
    assert 'data-has-data="0"' in r.text
    assert 'id="session-editor-wrap" hx-swap-oob="innerHTML"' not in r.text
    assert get_sets_by_fecha(db, fecha_to_db(datetime.date.today())) == []


def test_undo_sesion_restaura_estado_previo(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["90"],
            "reps": ["6"],
            "rir": ["2"],
        },
    )
    client.post("/undo")
    rows = get_sets_by_fecha(db, fecha_to_db(datetime.date.today()))
    assert len(rows) == 1
    assert rows[0]["kg"] == 80 and rows[0]["reps"] == 8


def test_undo_entrenos_restaura_snapshot(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    r = client.post("/plantilla/eliminar/2")
    assert "Entreno eliminado" in r.text
    r = client.post("/undo")
    assert "Acción deshecha" in r.text
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["A", "B"]


def test_undo_reorden_vuelve_al_orden_original(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    client.post("/plantilla/reordenar", data={"id": ["2", "1"]})
    client.post("/undo")
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["A", "B"]


def test_undo_pila_vacia_avisa(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    r = _client().post("/undo")
    assert "Nada que deshacer" in r.text


def test_undo_pila_limitada_a_10(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    for i in range(12):
        client.post("/plantilla/guardar", data={"nombre": f"E{i}", "ejercicio": ["Press"]})
    assert undo_stack_size() == 10


def test_entreno_guardado_con_papelera_cuando_hay_datos(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get(f"/fecha/editor?fecha={_fecha()}")
    assert "delete-session-btn" in r.text
    assert 'delete-session-btn"\n                hidden' not in r.text
    r2 = _client().get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "delete-session-btn" in r2.text
    assert (
        "hidden"
        in r2.text[r2.text.find("delete-session-btn") : r2.text.find("delete-session-btn") + 200]
    )


def test_index_references_static_assets(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert 'href="/static/css/app.css"' in r.text
    assert 'src="/static/js/app.js"' in r.text


def test_static_css_served(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/static/css/app.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")


def test_static_js_served(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/static/js/app.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")


def test_app_css_imports_ordered(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/static/css/app.css")
    assert r.status_code == 200
    ordered = [
        "theme.css",
        "components.css",
        "date-navigator.css",
        "session-editor.css",
        "templates.css",
    ]
    positions = [r.text.find(f'"{name}"') for name in ordered]
    assert all(p >= 0 for p in positions), f"missing import: {r.text}"
    assert positions == sorted(positions), "css imports out of order"
    for name in ordered:
        resp = _client().get(f"/static/css/{name}")
        assert resp.status_code == 200, f"{name} not served"


def test_base_template_has_no_inline_style_block(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert "tailwind.config" not in r.text
    base_path = os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")
    with open(base_path) as f:
        source = f.read()
    assert "<style>" not in source
    assert ".date-num {" not in source
    assert 'href="/static/css/app.css"' in source


def test_base_template_loads_only_module_js(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    with open(os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")) as f:
        source = f.read()
    assert '<script type="module" src="/static/js/app.js"></script>' in source
    for banned in (
        "function submitSave",
        "function doNav",
        "function aplicarPlantilla",
        "function recalcRM",
    ):
        assert banned not in source


def test_base_template_cdn_scripts_pin_sri(tmp_path, monkeypatch):
    """Tripwire: every third-party <script src> must carry integrity= and crossorigin=."""
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    with open(os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")) as f:
        source = f.read()
    scripts = re.findall(r'<script\s+src="https://[^"]+"[^>]*>', source)
    assert len(scripts) == 3, f"CDNs esperados: htmx, sortablejs, plotly; hay {len(scripts)}"
    for tag in scripts:
        assert "integrity=" in tag, f"script sin SRI: {tag}"
        assert "crossorigin=" in tag, f"script sin crossorigin: {tag}"


def test_base_template_sin_cdn_tailwind(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    with open(os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")) as f:
        source = f.read()
    assert "cdn.tailwindcss.com" not in source
    assert '<link rel="stylesheet" href="/static/css/tailwind.css">' in source


def test_static_tailwind_css_served(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/static/css/tailwind.css")
    assert r.status_code == 200
    assert ".bg-matte-950" in r.text


def test_index_uses_app_config_json(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert 'id="app-config" type="application/json"' in r.text
    assert "CATEGORIA_MAP" not in r.text
    assert "categoria_map" in r.text


def test_static_js_modules_served(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    for name in (
        "app.js",
        "state.js",
        "notices.js",
        "editor.js",
        "row-sortable.js",
        "templates.js",
        "date-navigation.js",
        "htmx-lifecycle.js",
    ):
        resp = _client().get(f"/static/js/{name}")
        assert resp.status_code == 200, f"{name} not served"
        assert resp.headers["content-type"].startswith("text/javascript")


def test_index_includes_global_partials_once(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert r.text.count('id="confirm-modal"') == 1
    assert r.text.count('id="notice-container"') == 1
    assert r.text.count('id="app-config"') == 1
    assert r.text.count("<!DOCTYPE html>") == 1


def test_htmx_partial_has_single_document(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    for path in (
        f"/fecha/editor?fecha={_fecha()}",
        "/plantillas",
        "/select",
        "/ejercicio?ejercicio=Press",
    ):
        r = _client().get(path)
        assert r.text.count("<!DOCTYPE html>") == 0, f"{path} devuelve un documento completo"
        assert r.text.count("<html") == 0, f"{path} contiene <html>"


def test_mutating_routes_return_200(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    r = client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": ["Press"],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.status_code == 200
    r = client.post("/entrenamiento/session/eliminar", data={"fecha": _fecha()})
    assert r.status_code == 200
    r = client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 200
    r = client.post("/plantilla/editar/1", data={"nombre": "B", "ejercicio": ["Press"]})
    assert r.status_code == 200
    r = client.post("/plantilla/reordenar", data={"id": ["1"]})
    assert r.status_code == 200
    r = client.get("/plantilla/aplicar/1", params={"fecha": _fecha(1)})
    assert r.status_code == 200
    r = client.post("/undo", data={"fecha": _fecha()})
    assert r.status_code == 200
    r = client.post(
        "/ejercicio/nuevo",
        data={"ejercicio": "Fondos", "grupo_muscular": "Pectoral", "categoria": "EMPUJE"},
    )
    assert r.status_code == 200


def test_select_and_grupo_reset_oob_chart(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = client.get("/select")
    assert r.status_code == 200
    assert 'id="unified-chart" hx-swap-oob="innerHTML"' in r.text
    r = client.get("/select", params={"grupo": "Pectoral"})
    assert 'id="unified-chart" hx-swap-oob="innerHTML"' in r.text
    r = client.get("/grupo/reset", params={"grupo": "Pectoral"})
    assert r.status_code == 200
    assert 'id="unified-chart" hx-swap-oob="innerHTML"' in r.text


def test_ejercicio_history_oob_chart(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/ejercicio", params={"ejercicio": "Press"})
    assert r.status_code == 200
    assert 'id="unified-chart" hx-swap-oob="innerHTML"' in r.text
    assert "Resumen por Sesión" in r.text


def test_ejercicio_nuevo_oob_markers(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = client.post(
        "/ejercicio/nuevo",
        data={"ejercicio": "Dominadas", "grupo_muscular": "Espalda", "categoria": "TIRON"},
    )
    assert r.status_code == 200
    assert 'id="notice-container" hx-swap-oob="innerHTML"' in r.text
    assert 'id="exercise-create" hx-swap-oob="outerHTML"' in r.text
    assert "Dominadas" in r.text
    r = client.post(
        "/ejercicio/nuevo",
        data={"ejercicio": "   ", "grupo_muscular": "Espalda", "categoria": "TIRON"},
    )
    assert "notice-error" in r.text
    assert 'id="exercise-create" hx-swap-oob="outerHTML"' not in r.text


def test_undo_entrenos_oob_plantillas(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    r = client.post("/undo", data={"fecha": _fecha()})
    assert r.status_code == 200
    assert 'id="plantillas-section" hx-swap-oob="outerHTML"' in r.text
    assert "Aún no hay entrenos" in r.text


def test_domain_errors_return_400_with_notice(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": _fecha(),
            "ejercicio": [""],
            "kg": ["80"],
            "reps": ["8"],
            "rir": ["1"],
        },
    )
    assert r.status_code == 400
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "notice-error" in r.text
    r = client.post("/plantilla/guardar", data={"nombre": "Vacia", "ejercicio": []})
    assert r.status_code == 400
    assert "notice-error" in r.text
    r = client.get("/plantilla/aplicar/999", params={"fecha": _fecha()})
    assert r.status_code == 400
    assert "La plantilla no existe" in r.text


def test_edit_duplicate_name_shows_inline_error(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    r = client.post("/plantilla/editar/2", data={"nombre": "A", "ejercicio": ["Press"]})
    assert r.status_code == 200
    assert 'id="plantillas-section" hx-swap-oob="outerHTML"' in r.text
    assert "Ya existe un entreno llamado" in r.text


# ---------------------------------------------------------------------------
# Mutation failure truthfulness (Task 4)
# ---------------------------------------------------------------------------


def _seed_session(db, fecha_iso=None):
    from src.models import TrainingSetInput

    fecha_iso = fecha_iso or _fecha()
    save_session(db, fecha_iso, [TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1)])


def test_delete_session_failure_returns_500_and_keeps_state(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    _seed_session(db)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    monkeypatch.setattr("src.mutation_service.delete_session_by_fecha", _db_locked)

    r = _client().post("/entrenamiento/session/eliminar", data={"fecha": _fecha()})
    assert r.status_code == 500
    assert "Ocurrió un error inesperado" in r.text
    assert "Entreno eliminado" not in r.text
    assert 'data-ok="0"' in r.text
    assert undo_stack_size() == 0
    assert len(get_sets_by_fecha(db, fecha_to_db(datetime.date.today()))) == 1


def test_delete_template_failure_returns_500_and_keeps_state(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    _client().post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    monkeypatch.setattr("src.mutation_service.delete_plantilla", _db_locked)

    r = _client().post("/plantilla/eliminar/1")
    assert r.status_code == 500
    assert "Ocurrió un error inesperado" in r.text
    assert "Entreno eliminado" not in r.text
    assert undo_stack_size() == 1  # solo el guardar previo
    assert len(get_plantillas(db)) == 1


def test_reorder_failure_returns_500_and_keeps_order(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    monkeypatch.setattr("src.mutation_service.reorder_plantillas", _db_locked)

    r = client.post("/plantilla/reordenar", data={"id": ["2", "1"]})
    assert r.status_code == 500
    assert "Ocurrió un error inesperado" in r.text
    assert undo_stack_size() == 2  # solo los guardar previos
    assert [p["nombre"] for p in get_plantillas(db)] == ["A", "B"]


def test_undo_failure_returns_500_and_keeps_stack(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    _client().post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    monkeypatch.setattr("src.mutation_service.restore_entrenos", _db_locked)

    r = _client().post("/undo", data={"fecha": _fecha()})
    assert r.status_code == 500
    assert "Ocurrió un error inesperado" in r.text
    assert undo_stack_size() == 1  # la entrada no se pierde
    assert len(get_plantillas(db)) == 1


def _db_locked(*args, **kwargs):
    raise sqlite3.OperationalError("database locked")


def test_semana_primer_entreno_global(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-08-03", [TrainingSetInput("Press", 90, 6, 1)])
    save_session(db, "2026-08-06", [TrainingSetInput("Press", 92, 6, 1)])
    save_session(db, "2026-07-29", [TrainingSetInput("Press", 88, 6, 1)])
    r = _client().get("/semana/primer-entreno?semana=14")
    assert r.status_code == 200
    assert r.json() == {"fecha": "2026-08-03"}


def test_semana_primer_entreno_sin_datos(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/semana/primer-entreno?semana=99")
    assert r.json() == {"fecha": None}


def test_select_grupo_filtra_navegador_sin_saltar_editor(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-05-04", [TrainingSetInput("Press", 80, 8, 1)])
    save_session(db, "2026-05-06", [TrainingSetInput("Press", 82, 8, 1)])
    save_session(db, "2026-05-08", [TrainingSetInput("Press", 84, 8, 1)])
    r = _client().get("/select?grupo=Pectoral&fecha=2026-06-01")
    assert 'id="date-navigator" hx-swap-oob="outerHTML"' in r.text
    assert "filter-jump" not in r.text
    assert r.text.count("date-dot") == 3
    # El navegador mantiene seleccionada la fecha actual, no la del primer entreno.
    assert re.search(r'data-iso="2026-06-01"\s+class="date-num selected"', r.text)


def test_select_global_restaura_dots_y_mantiene_fecha(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-05-04", [TrainingSetInput("Press", 80, 8, 1)])
    r = _client().get("/select?fecha=2026-05-06")
    assert "filter-jump" not in r.text
    assert re.search(r'data-iso="2026-05-06"\s+class="date-num selected"', r.text)
    assert r.text.count("date-dot") >= 1


def test_ejercicio_filtra_navegador_sin_saltar_editor(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-05-04", [TrainingSetInput("Press", 80, 8, 1)])
    save_session(db, "2026-05-05", [TrainingSetInput("Press", 82, 8, 1)])
    r = _client().get("/ejercicio?ejercicio=Press&fecha=2026-06-01")
    assert "filter-jump" not in r.text
    assert 'id="date-navigator" hx-swap-oob="outerHTML"' in r.text
    assert r.text.count("date-dot") == 2
    assert re.search(r'data-iso="2026-06-01"\s+class="date-num selected"', r.text)


def test_export_csv_orden_cronologico(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    for iso, sets in [
        ("2026-01-15", [TrainingSetInput("Press", 90, 7, 1)]),
        ("2026-02-03", [TrainingSetInput("Press", 92, 7, 1)]),
        ("2026-01-09", [TrainingSetInput("Press", 88, 7, 1)]),
    ]:
        save_session(db, iso, sets)
    resp = client.get("/exportar/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.splitlines()
    fecha_idx = lines[0].split(",").index("fecha")
    fechas = [ln.split(",")[fecha_idx] for ln in lines[1:]]
    assert fechas == ["2026-01-09", "2026-01-15", "2026-02-03"]


def test_undo_restaura_origen_google(tmp_path, monkeypatch):
    from src.db_connection import transaction

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    with transaction(db) as conn:
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (1, 'LUNES', '2026-08-06', 1, 'Press', 7, 90, 1.2, 'google')"
        )
    fecha = "2026-08-06"
    client = _client()
    client.post(
        "/entrenamiento/session/save",
        data={"fecha": fecha, "ejercicio": ["Press"], "kg": ["95"], "reps": ["6"], "rir": ["1"]},
    )
    client.post("/undo", data={"fecha": fecha})
    rows = get_sets_by_fecha(db, "2026-08-06")
    assert rows[0]["kg"] == 90 and rows[0]["origen"] == "google"


def test_sesiones_view_renders_ultimas(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-08-06", [TrainingSetInput("Press", 90, 7, 1)])
    resp = _client().get("/sesiones")
    assert resp.status_code == 200
    assert "2026-08-06" in resp.text and "series" in resp.text


def test_index_incluye_historial_sesiones(tmp_path, monkeypatch):
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    save_session(db, "2026-08-06", [TrainingSetInput("Press", 90, 7, 1)])
    resp = _client().get("/")
    assert 'id="session-history"' in resp.text
    assert "6/8/26" in resp.text


def test_save_incluye_oob_history(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    resp = _client().post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2026-08-06",
            "ejercicio": ["Press"],
            "kg": ["90"],
            "reps": ["7"],
            "rir": ["1"],
        },
    )
    assert 'id="session-history" hx-swap-oob="innerHTML"' in resp.text


def test_undo_incluye_oob_history(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    client.post(
        "/entrenamiento/session/save",
        data={
            "fecha": "2026-08-06",
            "ejercicio": ["Press"],
            "kg": ["90"],
            "reps": ["7"],
            "rir": ["1"],
        },
    )
    resp = client.post("/undo", data={"fecha": "2026-08-06"})
    assert 'id="session-history" hx-swap-oob="innerHTML"' in resp.text


def test_lifespan_warns_sin_csrf_secret(tmp_path, monkeypatch, caplog):
    import logging

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    monkeypatch.delenv("GYM_CSRF_SECRET", raising=False)
    with caplog.at_level(logging.WARNING), TestClient(appmod.app) as c:
        c.get("/")
    assert any("GYM_CSRF_SECRET" in r.message for r in caplog.records)


def _seed_nutrition(tmp_path) -> str:
    from src.database import insert_alimento

    db = _setup_db(tmp_path)
    insert_alimento(
        db,
        {
            "nombre": "Avena",
            "categoria": "Cereal",
            "kcal": 389.0,
            "carbohidratos": 68.0,
            "fibra": 10.0,
            "proteina": 17.0,
            "grasa": 6.9,
            "hierro": 4.2,
            "calcio": 54.0,
            "vitamina_c": 0.0,
            "vitamina_a": 0.0,
        },
    )
    return db


def test_alimentacion_save_guarda_parametros_y_filas(tmp_path, monkeypatch):
    from src.database import get_diario_by_fecha, get_parametros_diarios

    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/alimentacion/save",
        data={
            "fecha": "2025-04-26",
            "alimento": ["Avena"],
            "cantidad": ["120"],
            "peso_kg": "69",
            "factor_proteina": "1.5",
            "factor_grasa": "1.1",
            "kcal_objetivo": "2750",
        },
    )
    assert r.status_code == 200
    assert get_diario_by_fecha(db, "2025-04-26")[0]["kcal"] == 467.0
    params = get_parametros_diarios(db, "2025-04-26")
    assert params["peso_kg"] == 69.0
    assert params["kcal_objetivo"] == 2750.0


def test_index_app_config_tiene_alimento_map(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert '"alimento_map"' in r.text


def test_index_renders_global_date_title_below_navigator(tmp_path, monkeypatch):
    from datetime import date

    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert r.status_code == 200
    assert 'id="session-date-title"' in r.text
    assert "Semana" in r.text
    assert r.text.index('id="date-navigator"') < r.text.index('id="session-date-title"')
    assert r.text.index('id="session-date-title"') < r.text.index('id="nutrition-panel"')
    # El título incluye el día actual (8/8/2026 = sábado)
    assert "SABADO" in r.text or "DOMINGO" in r.text or date.today().strftime("%A").upper() in r.text


def test_panel_titles_are_static(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert r.status_code == 200
    # El editor de sesión tiene título estático "Entrenamiento" sin fecha
    session_title = r.text[r.text.index('<h3 class="text-sm font-black tracking-[0.2em] text-burgundy-400 uppercase neon-title truncate">') :]
    assert ">Entrenamiento</h3>" in session_title
    assert "SABADO" not in session_title.split("</h3>")[0]
    # La fecha vive en el título global, no en los paneles
    assert 'id="session-date-title"' in r.text


def test_index_renders_nutrition_panel_above_session_editor(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert r.status_code == 200
    # Navegador arriba de todo, panel de nutrición antes del editor de sesión
    assert r.text.index('id="date-navigator"') < r.text.index('id="nutrition-panel"')
    assert r.text.index('id="nutrition-panel"') < r.text.index('id="session-editor"')
    assert 'id="target-params"' in r.text
    assert 'id="alimento-create"' in r.text
    # Chevrons de colapso dentro de cada panel (header), sin barras externas
    assert r.text.count('data-action="toggle-panel-collapse"') == 2
    assert 'id="session-editor" data-editmode="0" data-target' not in r.text
    assert "collapse-chevron" in r.text


def test_nutrition_editor_tabla_esquema_11_columnas(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/alimentacion/editor?fecha=2025-04-24")
    assert r.status_code == 200
    for label in (
        "Calorías (kcal)",
        "Carbohidratos (g)",
        "Proteína (g)",
        "Grasa (g)",
        "Fibra (g)",
        "Hierro (mg)",
        "Calcio (mg)",
        "Vitamina C (mg)",
        "Vitamina A",
    ):
        assert label in r.text
    assert "Objetivo" in r.text
    assert "Consumido" in r.text


def test_alimentacion_standalone_page_removed(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/alimentacion")
    assert r.status_code == 404


def test_index_no_tiene_enlace_alimentacion(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/")
    assert 'href="/alimentacion"' not in r.text


def test_alimentacion_editor_fragment(tmp_path, monkeypatch):
    from src.database import replace_diario_by_fecha

    db = _seed_nutrition(tmp_path)
    replace_diario_by_fecha(
        db,
        "2025-04-24",
        [
            {
                "alimento": "Avena",
                "cantidad_g": 120.0,
                "kcal": 467.0,
                "carbohidratos": 82.0,
                "fibra": 12.0,
                "proteina": 20.0,
                "grasa": 8.0,
                "hierro": 5.0,
                "calcio": 65.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
                "origen": "google",
            }
        ],
    )
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/alimentacion/editor?fecha=2025-04-24")
    assert r.status_code == 200
    assert "Avena" in r.text
    assert 'name="fecha" value="2025-04-24"' in r.text
    assert "Consumido" in r.text
    assert "Objetivo" in r.text
    assert 'data-has-data="1"' in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-action="nutrition-toggle-edit"' in r.text


def test_alimentacion_save_computes_and_returns_oob(tmp_path, monkeypatch):
    from src.database import get_diario_by_fecha

    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/alimentacion/save",
        data={"fecha": "2025-04-26", "alimento": ["Avena"], "cantidad": ["120"]},
    )
    assert r.status_code == 200
    assert 'id="nutrition-editor-wrap" hx-swap-oob' in r.text
    rows = get_diario_by_fecha(db, "2025-04-26")
    assert len(rows) == 1
    assert rows[0]["alimento"] == "Avena"
    assert rows[0]["kcal"] == 467.0
    assert rows[0]["origen"] == "manual"


def test_alimentacion_save_unknown_food_is_400(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/alimentacion/save",
        data={"fecha": "2025-04-26", "alimento": ["No Existe"], "cantidad": ["100"]},
    )
    assert r.status_code == 400
    assert "Alimento no encontrado" in r.text


def test_alimentacion_eliminar(tmp_path, monkeypatch):
    from src.database import get_diario_by_fecha, replace_diario_by_fecha

    db = _seed_nutrition(tmp_path)
    replace_diario_by_fecha(
        db,
        "2025-04-26",
        [
            {
                "alimento": "Avena",
                "cantidad_g": 120.0,
                "kcal": 467.0,
                "carbohidratos": 82.0,
                "fibra": 12.0,
                "proteina": 20.0,
                "grasa": 8.0,
                "hierro": 5.0,
                "calcio": 65.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
                "origen": "manual",
            }
        ],
    )
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post("/alimentacion/eliminar", data={"fecha": "2025-04-26"})
    assert r.status_code == 200
    assert get_diario_by_fecha(db, "2025-04-26") == []


def test_alimento_nuevo(tmp_path, monkeypatch):
    from src.database import find_alimento

    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/alimento/nuevo",
        data={
            "nombre": "Aceite de Oliva",
            "categoria": "Procesado",
            "kcal": "819",
            "carbohidratos": "0",
            "fibra": "0",
            "proteina": "0",
            "grasa": "92",
            "hierro": "0",
            "calcio": "0",
            "vitamina_c": "0",
            "vitamina_a": "0",
        },
    )
    assert r.status_code == 200
    assert 'id="alimento-create" hx-swap-oob="outerHTML"' in r.text
    assert find_alimento(db, "aceite de oliva") is not None


def test_alimentacion_export_csv(tmp_path, monkeypatch):
    from src.database import replace_diario_by_fecha

    db = _seed_nutrition(tmp_path)
    replace_diario_by_fecha(
        db,
        "2025-04-24",
        [
            {
                "alimento": "Avena",
                "cantidad_g": 120.0,
                "kcal": 467.0,
                "carbohidratos": 82.0,
                "fibra": 12.0,
                "proteina": 20.0,
                "grasa": 8.0,
                "hierro": 5.0,
                "calcio": 65.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
                "origen": "google",
            }
        ],
    )
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/alimentacion/exportar/csv")
    assert r.status_code == 200
    assert "alimento" in r.text
    assert "Avena" in r.text
    assert "2025-04-24" in r.text


def test_alimentacion_save_requires_csrf(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post(
        "/alimentacion/save",
        data={"fecha": "2025-04-26", "alimento": ["Avena"], "cantidad": ["120"]},
    )
    assert r.status_code == 403


def test_alimento_nuevo_escapes_name_in_app_config_oob(tmp_path, monkeypatch):
    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().post(
        "/alimento/nuevo",
        data={
            "nombre": "</script><b>x</b>",
            "categoria": "X",
            "kcal": "1",
            "carbohidratos": "0",
            "fibra": "0",
            "proteina": "0",
            "grasa": "0",
            "hierro": "0",
            "calcio": "0",
            "vitamina_c": "0",
            "vitamina_a": "0",
        },
    )
    assert r.status_code == 200
    assert 'id="app-config" hx-swap-oob="outerHTML"' in r.text
    assert "<\\u003c/script>" not in r.text
    assert "\\u003c/script\\u003e" in r.text


def test_undo_alimentacion_refreshes_nutrition_editor(tmp_path, monkeypatch):
    from src.database import get_diario_by_fecha

    db = _seed_nutrition(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    _client().post(
        "/alimentacion/save",
        data={"fecha": "2025-04-26", "alimento": ["Avena"], "cantidad": ["120"]},
    )
    r = _client().post("/undo", data={"fecha": "2025-04-26"})
    assert r.status_code == 200
    assert 'id="nutrition-editor-wrap" hx-swap-oob' in r.text
    assert get_diario_by_fecha(db, "2025-04-26") == []


def test_get_first_session_date_con_iso(tmp_path):
    from src.dashboard_service import get_first_session_date
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    save_session(db, "2026-08-18", [TrainingSetInput("Press", 80, 8, 1)])
    save_session(db, "2026-08-11", [TrainingSetInput("Press", 80, 8, 1)])
    assert get_first_session_date(db, 15, grupo="Pectoral") == "2026-08-11"


def test_fechas_con_datos_con_iso(tmp_path):
    from src.dashboard_service import fechas_con_datos
    from src.models import TrainingSetInput

    db = _setup_db(tmp_path)
    save_session(db, "2026-08-11", [TrainingSetInput("Press", 80, 8, 1)])
    assert fechas_con_datos(db) == {"2026-08-11"}
