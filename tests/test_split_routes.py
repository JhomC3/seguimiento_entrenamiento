"""Tests de integración de las rutas del gestor de splits (CSRF, OOB, undo)."""

from fastapi.testclient import TestClient

import app as appmod
from src.database import get_split, init_db, insert_exercise
from src.mutation_service import clear_undo_stack
from src.security import get_csrf_secret, make_csrf_token


def _client():
    return TestClient(appmod.app, headers={"X-CSRF-Token": make_csrf_token(get_csrf_secret())})


def _setup_db(tmp_path, *ejercicios):
    db = str(tmp_path / "gym.db")
    init_db(db)
    for ejercicio, grupo, categoria in ejercicios or [("Press", "Pectoral", "EMPUJE")]:
        insert_exercise(db, ejercicio, grupo, categoria)
    return db


def _guardar(
    client,
    nombre="Push Pull Legs",
    dias=("LUNES",),
    tipos=("ejercicio",),
    ejercicios=("Press",),
    split_id=None,
):
    data = {
        "nombre": nombre,
        "dia": list(dias),
        "item_type": list(tipos),
        "ejercicio": list(ejercicios),
    }
    if split_id is not None:
        data["split_id"] = str(split_id)
    return client.post("/split/guardar", data=data)


def test_splits_page_render(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, ("Press", "Pectoral", "EMPUJE"), ("Curl", "Biceps", "TIRON"))
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/splits")
    assert r.status_code == 200
    assert "Gestor de splits" in r.text
    assert "Press" in r.text
    assert "Curl" in r.text
    assert 'data-item-type="hiit"' in r.text
    for day in ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"):
        assert f'data-day="{day}"' in r.text
    assert 'id="splits-section"' in r.text
    assert 'id="split-board"' in r.text


def test_splits_page_con_abrir(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(client)
    split_id = get_split(db, 1)["id"]
    r = client.get(f"/splits?abrir={split_id}")
    assert r.status_code == 200
    assert "Push Pull Legs" in r.text


def test_split_guardar_crea_con_oob(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = _guardar(client)
    assert r.status_code == 200
    assert 'id="splits-section" hx-swap-oob="outerHTML"' in r.text
    assert 'id="split-board" hx-swap-oob="innerHTML"' in r.text
    assert "Split guardado." in r.text
    assert get_split(db, 1) is not None


def test_split_guardar_mismo_nombre_actualiza(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(client)
    r = _guardar(client, dias=("MARTES",), ejercicios=("Press",))
    assert "Split actualizado." in r.text
    split = get_split(db, 1)
    assert split["items"][0]["dia"] == "MARTES"


def test_split_guardar_duplicado_por_nombre_rechazado(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(client, nombre="A")
    _guardar(client, nombre="B")
    r = _guardar(client, nombre="A", split_id=2)
    assert r.status_code == 400
    assert "notice-error" in r.text


def test_split_guardar_errores_dominio(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = _guardar(client, nombre="")
    assert r.status_code == 422  # Form(...) requerido: vacío es campo ausente
    r = _guardar(client, dias=("LUNESSS",))
    assert r.status_code == 400
    r = _guardar(client, ejercicios=("No Existe",))
    assert r.status_code == 400
    r = _guardar(client, dias=("LUNES",), tipos=("ejercicio",), ejercicios=("Press", "Press"))
    assert r.status_code == 400
    assert "Datos incompletos" in r.text


def test_split_guardar_hiit(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    r = _guardar(
        client, dias=("LUNES", "MARTES"), tipos=("ejercicio", "hiit"), ejercicios=("Press", "HIIT")
    )
    assert r.status_code == 200
    split = get_split(db, 1)
    assert len(split["items"]) == 2
    assert split["items"][1]["item_type"] == "hiit"


def test_split_guardar_requiere_csrf(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = TestClient(appmod.app)
    r = client.post(
        "/split/guardar",
        data={"nombre": "X", "dia": ["LUNES"], "item_type": ["ejercicio"], "ejercicio": ["Press"]},
    )
    assert r.status_code == 403
    assert get_split(db, 1) is None


def test_split_eliminar(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(client)
    assert get_split(db, 1) is not None
    r = client.post("/split/eliminar/1")
    assert r.status_code == 200
    assert "Split eliminado." in r.text
    assert 'id="split-board" hx-swap-oob="innerHTML"' in r.text
    assert get_split(db, 1) is None
    r = client.post("/split/eliminar/1")
    assert r.status_code == 400


def test_split_get_no_existe(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/split/999")
    assert r.status_code == 400
    assert "no existe" in r.text


def test_splits_no_se_contaminan(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(client, nombre="A", dias=("LUNES",), ejercicios=("Press",))
    _guardar(client, nombre="B", dias=("VIERNES",), ejercicios=("Press",))
    a = get_split(db, 1)
    b = get_split(db, 2)
    assert [i["dia"] for i in a["items"]] == ["LUNES"]
    assert [i["dia"] for i in b["items"]] == ["VIERNES"]


def test_undo_split_restaura_lista(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    _guardar(client)
    assert get_split(db, 1) is not None
    r = client.post("/undo", data={"fecha": ""})
    assert r.status_code == 200
    assert 'id="splits-section" hx-swap-oob="outerHTML"' in r.text
    assert "Aún no hay splits" in r.text
    assert get_split(db, 1) is None
    clear_undo_stack()


def test_undo_empty_no_rompe(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    clear_undo_stack()
    client = _client()
    r = client.post("/undo", data={"fecha": ""})
    assert r.status_code == 200
    assert "Nada que deshacer." in r.text
    clear_undo_stack()
