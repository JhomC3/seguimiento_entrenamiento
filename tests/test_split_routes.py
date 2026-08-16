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
    # Orden visual: board y resumen ANTES que el catálogo y la lista.
    assert r.text.index('id="split-board"') < r.text.index("Catálogo de ejercicios")
    assert r.text.index("Catálogo de ejercicios") < r.text.index('id="splits-section"')


def test_splits_page_catalogo_agrupado_y_detalles(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, ("Press", "Pectoral", "EMPUJE"), ("Curl", "Biceps", "TIRON"))
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/splits")
    assert r.status_code == 200
    assert r.text.count('<details class="split-catalog-group"') == 3  # Pectoral, Biceps, HIIT
    assert 'data-group="Pectoral"' in r.text
    assert 'data-group="Biceps"' in r.text
    assert 'data-group="HIIT"' in r.text
    assert '<summary class="split-catalog-summary">HIIT</summary>' in r.text
    # Los chips del catálogo muestran SOLO el nombre (sin texto de grupo visible).
    assert '<span class="split-item-name">Press</span>' in r.text
    assert '<span class="split-item-group">' not in r.text


def test_splits_page_resumen_v2(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(
        client, dias=("LUNES", "MARTES"), tipos=("ejercicio", "hiit"), ejercicios=("Press", "HIIT")
    )
    r = client.get("/splits?abrir=1")
    assert r.status_code == 200
    # Sin conteos auxiliares.
    assert "Días activos" not in r.text
    assert "Ejercicios distintos" not in r.text
    # Resumen semanal + por ejercicio + por día (7 días, incluso vacíos).
    assert 'id="split-metrics-week"' in r.text
    assert 'id="split-metrics-exercises"' in r.text
    assert 'id="split-metrics-days"' in r.text
    assert "Semana — <strong>2</strong> series" in r.text
    assert "HIIT: <strong>1</strong> series" in r.text
    assert "Domingo — <strong>0</strong> series" in r.text
    assert r.text.count("— <strong>") >= 7  # los 7 días del resumen
    # Handle de copia de día con aria-label y title.
    assert 'class="split-day-copy-handle"' in r.text
    assert 'aria-label="Copiar todo el día Lunes manteniendo Shift"' in r.text
    assert 'title="Mantén Shift y arrastra para copiar el día completo"' in r.text
    # Límite expuesto para el guard client-side.
    assert 'data-max-items="300"' in r.text


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


def test_splits_js_sin_dnd_nativo_paralelo():
    """El DnD de items es SortableJS (no deben quedar listeners nativos a nivel
    document). El único DnD nativo permitido es el del handle de día, que se
    vincula POR ELEMENTO (no en document)."""
    from pathlib import Path

    src = Path("static/js/splits.js").read_text(encoding="utf-8")
    assert "document.addEventListener('dragstart'" not in src
    assert "document.addEventListener('dragend'" not in src
    assert "document.addEventListener('dragover'" not in src or "daycopy:" in src
    assert "Sortable.create" in src
    assert "sortable-ghost" in src
    assert "sortable-chosen" in src
