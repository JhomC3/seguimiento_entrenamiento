import datetime

import pytest
from fastapi.testclient import TestClient

import app as appmod
from src.database import get_plantillas, get_sets_by_fecha, init_db, insert_exercise
from src.training_service import fecha_to_db, save_session

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
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "pencil-btn off" in r.text
    assert 'duration-150 hidden"' in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text
    assert 'id="edit-actions" class="mt-2 h-8 flex items-center gap-2 invisible"' in r.text
    assert 'aria-label="Cancelar"' in r.text
    assert "rm-cell" in r.text

def test_saved_future_is_readonly(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(1), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "pencil-btn off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="1"' in r.text

def test_empty_future_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "pencil-btn on" in r.text
    assert 'transition-opacity duration-150' in r.text
    assert 'duration-150 hidden"' not in r.text
    assert 'data-readonly="0"' in r.text
    assert 'data-has-data="0"' in r.text
    assert 'id="edit-actions" class="mt-2 h-8 flex items-center gap-2 invisible"' in r.text
    assert 'aria-label="Cancelar"' in r.text

def test_empty_today_is_editable(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "pencil-btn on" in r.text

def test_empty_past_is_readonly_with_fallback_row(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(-2)}")
    assert "pencil-btn off" in r.text
    assert 'data-readonly="1"' in r.text
    assert 'data-has-data="0"' in r.text
    assert r.text.count('<tr class="set-row') == 1

def test_index_uses_stable_card(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get("/")
    assert 'id="session-editor" data-editmode="0"' in r.text
    assert 'id="session-editor-wrap"' in r.text
    assert "rm-cell" in r.text
    assert 'id="save-outcome" data-ok="0" hidden' in r.text
    assert '<div id="editor-notice"></div>' in r.text


def test_save_valid_returns_ok_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["1"],
    })
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="1"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "Entrenamiento guardado" in r.text


def test_save_invalid_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": [""], "kg": ["80"], "reps": ["8"], "rir": [""],
    })
    assert 'id="save-outcome" hx-swap-oob="outerHTML" data-ok="0"' in r.text
    assert 'id="editor-notice" hx-swap-oob="innerHTML"' in r.text
    assert "notice-error" in r.text
    assert 'data-ok="1"' not in r.text


def test_save_empty_rir_returns_fail_marker(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": [""],
    })
    assert 'data-ok="0"' in r.text
    assert "RIR" in r.text


def test_save_zero_rir_succeeds(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["0"],
    })
    assert 'data-ok="1"' in r.text


def test_index_renders_plantillas_section(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get("/")
    assert 'id="plantillas-section"' in r.text
    assert "Aún no hay entrenos" in r.text


def test_plantilla_guardar_crea_y_oob(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/plantilla/guardar", data={
        "nombre": "Mi Empuje", "ejercicio": ["Press"],
    })
    assert "Entreno guardado" in r.text
    assert 'id="plantillas-section" hx-swap-oob="outerHTML"' in r.text


def test_plantilla_guardar_mismo_nombre_actualiza(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = TestClient(appmod.app)
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    assert "Entreno actualizado" in r.text


def test_plantilla_guardar_sin_ejercicios_error(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).post("/plantilla/guardar", data={"nombre": "Vacia", "ejercicio": []})
    assert "notice-error" in r.text
    assert "al menos un ejercicio" in r.text


def test_plantilla_eliminar(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = TestClient(appmod.app)
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
    client = TestClient(appmod.app)
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
    client = TestClient(appmod.app)
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.post("/plantilla/editar/1", data={"nombre": "Mi Torso", "ejercicio": ["Press", "Curl"]})
    assert "Entreno guardado" in r.text
    assert "Mi Torso" in r.text


def test_plantillas_view_editar_expande_formulario(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = TestClient(appmod.app)
    client.post("/plantilla/guardar", data={"nombre": "Mi Empuje", "ejercicio": ["Press"]})
    r = client.get("/plantillas", params={"editar": 1})
    assert 'id="plantilla-edit-rows"' in r.text
    assert 'hx-post="/plantilla/editar/1"' in r.text


def test_plantilla_reordenar(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = TestClient(appmod.app)
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
    r = TestClient(appmod.app).post("/entrenamiento/session/eliminar", data={"fecha": _fecha()})
    assert 'data-ok="1"' in r.text
    assert "Entreno eliminado" in r.text
    assert 'data-has-data="0"' in r.text
    assert get_sets_by_fecha(db, fecha_to_db(datetime.date.today())) == []


def test_editor_botones_texto_en_panel_e_iconos_en_form(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert ">Guardar</button>" in r.text
    assert ">Cancelar</button>" in r.text
    assert 'class="btn-x"' in r.text
    assert 'class="btn-check"' not in r.text
    assert 'class="edit-toggle undo-btn"' in r.text


def test_undo_sesion_restaura_filas(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    appmod.UNDO_STACK.clear()
    client = TestClient(appmod.app)
    client.post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["80"], "reps": ["8"], "rir": ["1"],
    })
    r = client.post("/undo")
    assert "Acción deshecha" in r.text
    assert 'data-ok="1"' in r.text
    assert get_sets_by_fecha(db, fecha_to_db(datetime.date.today())) == []


def test_undo_sesion_restaura_estado_previo(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    appmod.UNDO_STACK.clear()
    client = TestClient(appmod.app)
    client.post("/entrenamiento/session/save", data={
        "fecha": _fecha(), "ejercicio": ["Press"], "kg": ["90"], "reps": ["6"], "rir": ["2"],
    })
    client.post("/undo")
    rows = get_sets_by_fecha(db, fecha_to_db(datetime.date.today()))
    assert len(rows) == 1
    assert rows[0]["kg"] == 80 and rows[0]["reps"] == 8


def test_undo_entrenos_restaura_snapshot(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    appmod.UNDO_STACK.clear()
    client = TestClient(appmod.app)
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
    appmod.UNDO_STACK.clear()
    client = TestClient(appmod.app)
    client.post("/plantilla/guardar", data={"nombre": "A", "ejercicio": ["Press"]})
    client.post("/plantilla/guardar", data={"nombre": "B", "ejercicio": ["Press"]})
    client.post("/plantilla/reordenar", data={"id": ["2", "1"]})
    client.post("/undo")
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["A", "B"]


def test_undo_pila_vacia_avisa(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    appmod.UNDO_STACK.clear()
    r = TestClient(appmod.app).post("/undo")
    assert "Nada que deshacer" in r.text


def test_undo_pila_limitada_a_10(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    appmod.UNDO_STACK.clear()
    client = TestClient(appmod.app)
    for i in range(12):
        client.post("/plantilla/guardar", data={"nombre": f"E{i}", "ejercicio": ["Press"]})
    assert len(appmod.UNDO_STACK) == 10


def test_entreno_guardado_con_papelera_cuando_hay_datos(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    save_session(db, _fecha(), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha()}")
    assert "delete-session-btn" in r.text
    assert 'delete-session-btn"\n                hidden' not in r.text
    r2 = TestClient(appmod.app).get(f"/fecha/editor?fecha={_fecha(1)}")
    assert "delete-session-btn" in r2.text
    assert "hidden" in r2.text[r2.text.find("delete-session-btn"):r2.text.find("delete-session-btn") + 200]
