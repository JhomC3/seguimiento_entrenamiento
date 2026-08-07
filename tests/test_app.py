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
    """Tripwire: every third-party <script src> must carry integrity=, except the
    Tailwind CDN runtime (JIT, dynamic response + redirect — cannot be SRI-pinned;
    documented in docs/architecture/security-model.md)."""
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    with open(os.path.join(os.path.dirname(__file__), "..", "templates", "base.html")) as f:
        source = f.read()
    for tag in re.findall(r'<script\s+src="https://[^"]+"[^>]*>', source):
        if "cdn.tailwindcss.com" in tag:
            continue
        assert "integrity=" in tag, f"script sin SRI: {tag}"
        assert "crossorigin=" in tag, f"script sin crossorigin: {tag}"


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
        data={"ejercicio": "Press", "grupo_muscular": "Pectoral", "categoria": "EMPUJE"},
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
