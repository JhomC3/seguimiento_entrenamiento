"""API v1 del diario de entrenamiento (contrato training-api-contract.md).

Cubre autenticación X-Sync-Token, CRUD de sesión por fecha, catálogo y el
gate LAN sync-only. El cliente de estos tests NO envía cabecera CSRF: cada
POST/DELETE que pasa demuestra la exención exacta de CSRF_EXEMPT_PATHS.
"""

import datetime
import sqlite3

from fastapi.testclient import TestClient

import app as appmod
from src.database import init_db, insert_exercise

SYNC_TOKEN = "secret-training-api"


def _client():
    # Sin cabecera CSRF a propósito (ver docstring del módulo).
    return TestClient(appmod.app)


def _setup_db(tmp_path):
    db = str(tmp_path / "gym_api.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db, "Remo", "Espalda", "TIRON")
    return db


def _auth(monkeypatch, tmp_path, token=SYNC_TOKEN):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    monkeypatch.setattr(appmod, "HC_SYNC_TOKEN", token)
    return db


def _h(token=SYNC_TOKEN):
    return {"X-Sync-Token": token}


def _fecha(delta: int = 0) -> str:
    return (datetime.date.today() + datetime.timedelta(days=delta)).strftime("%Y-%m-%d")


def _sets():
    return [
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
        {"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2, "descanso_seg": 90},
    ]


# --- Auth: 503 sin token configurado ----------------------------------------


def test_api_503_cuando_no_hay_token(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    monkeypatch.setattr(appmod, "HC_SYNC_TOKEN", "")
    c = _client()
    assert c.get("/api/v1/sesion?fecha=2026-09-07", headers=_h("x")).status_code == 503
    assert c.get("/api/v1/ejercicios", headers=_h("x")).status_code == 503
    assert c.get("/api/v1/sugerencia?fecha=2026-09-07", headers=_h("x")).status_code == 503
    assert c.get("/api/v1/ejercicio/ultimo?ejercicio=Press", headers=_h("x")).status_code == 503
    assert c.post("/api/v1/sesion", json={}, headers=_h("x")).status_code == 503
    assert c.delete("/api/v1/sesion?fecha=2026-09-07", headers=_h("x")).status_code == 503


def test_api_401_token_ausente_o_incorrecto(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.get("/api/v1/sesion?fecha=2026-09-07").status_code == 401
    assert c.get("/api/v1/sesion?fecha=2026-09-07", headers=_h("otro")).status_code == 401
    assert c.get("/api/v1/ejercicios").status_code == 401
    assert c.post("/api/v1/sesion", json={}).status_code == 401
    assert c.delete("/api/v1/sesion?fecha=2026-09-07").status_code == 401


# --- GET sesión --------------------------------------------------------------


def test_api_get_dia_vacio(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    r = _client().get(f"/api/v1/sesion?fecha={_fecha()}", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["fecha"] == _fecha()
    assert data["semana"] >= 1
    assert data["dia"] in (
        "LUNES",
        "MARTES",
        "MIERCOLES",
        "JUEVES",
        "VIERNES",
        "SABADO",
        "DOMINGO",
    )
    assert data["has_data"] is False
    assert data["sets"] == []


def test_api_get_fecha_requerida_e_invalida(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.get("/api/v1/sesion", headers=_h()).status_code == 400
    assert c.get("/api/v1/sesion?fecha=no-fecha", headers=_h()).status_code == 400
    assert c.get("/api/v1/sesion?fecha=07/09/2026", headers=_h()).status_code == 400


# --- POST sesión -------------------------------------------------------------


def test_api_post_roundtrip_con_rm(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    r = c.post("/api/v1/sesion", json={"fecha": fecha, "sets": _sets()}, headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["fecha"] == fecha
    assert data["saved_count"] == 2
    assert data["has_data"] is True
    first, second = data["sets"]
    assert (first["set_orden"], first["ejercicio"]) == (1, "Press")
    assert (second["set_orden"], second["ejercicio"]) == (2, "Remo")
    assert second["descanso_seg"] == 90
    # RM recalculado en servidor (kg=80, reps=8, rir=1 → 80*(1+0.0333*9)).
    assert first["rm"] == round(80 * (1 + 0.0333 * 9), 1)

    got = c.get(f"/api/v1/sesion?fecha={fecha}", headers=_h())
    assert got.status_code == 200
    assert len(got.json()["sets"]) == 2

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets WHERE fecha=?", (fecha,)).fetchone()[0]
    conn.close()
    assert count == 2


def test_api_post_es_idempotente(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    c = _client()
    body = {"fecha": _fecha(), "sets": _sets()}
    first = c.post("/api/v1/sesion", json=body, headers=_h())
    second = c.post("/api/v1/sesion", json=body, headers=_h())
    assert first.status_code == second.status_code == 200
    assert second.json()["saved_count"] == 2
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 2


def test_api_post_reemplaza_el_dia(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    c.post("/api/v1/sesion", json={"fecha": fecha, "sets": _sets()}, headers=_h())
    r = c.post(
        "/api/v1/sesion",
        json={"fecha": fecha, "sets": [{"ejercicio": "Press", "kg": 85, "reps": 5, "rir": 0}]},
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json()["saved_count"] == 1
    assert r.json()["sets"][0]["kg"] == 85


def test_api_post_validacion_400(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    # Sin fecha / sin sets / sets vacío.
    assert c.post("/api/v1/sesion", json={"sets": _sets()}, headers=_h()).status_code == 400
    assert c.post("/api/v1/sesion", json={"fecha": fecha}, headers=_h()).status_code == 400
    assert (
        c.post("/api/v1/sesion", json={"fecha": fecha, "sets": []}, headers=_h()).status_code == 400
    )
    # Ejercicio desconocido / peso inválido / serie no-objeto.
    assert (
        c.post(
            "/api/v1/sesion",
            json={
                "fecha": fecha,
                "sets": [{"ejercicio": "Inexistente", "kg": 10, "reps": 5, "rir": 0}],
            },
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/sesion",
            json={"fecha": fecha, "sets": [{"ejercicio": "Press", "kg": -5, "reps": 5, "rir": 0}]},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post("/api/v1/sesion", json={"fecha": fecha, "sets": ["Press"]}, headers=_h()).status_code
        == 400
    )
    # Fecha inválida y lote excesivo.
    assert (
        c.post("/api/v1/sesion", json={"fecha": "ayer", "sets": _sets()}, headers=_h()).status_code
        == 400
    )
    big = {"fecha": fecha, "sets": [_sets()[0] for _ in range(101)]}
    assert c.post("/api/v1/sesion", json=big, headers=_h()).status_code == 400
    # Cuerpo no-JSON.
    r = c.post(
        "/api/v1/sesion",
        content=b"esto no es json",
        headers={**_h(), "Content-Type": "application/json"},
    )
    assert r.status_code == 400


# --- DELETE sesión -----------------------------------------------------------


def test_api_delete_idempotente(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    c.post("/api/v1/sesion", json={"fecha": fecha, "sets": _sets()}, headers=_h())
    r = c.delete(f"/api/v1/sesion?fecha={fecha}", headers=_h())
    assert r.status_code == 200
    assert r.json() == {"schema_version": 1, "fecha": fecha, "deleted": True}
    assert c.get(f"/api/v1/sesion?fecha={fecha}", headers=_h()).json()["has_data"] is False
    # Segundo borrado del día ya vacío: sigue 200 (reintento móvil seguro).
    again = c.delete(f"/api/v1/sesion?fecha={fecha}", headers=_h())
    assert again.status_code == 200
    assert again.json()["deleted"] is True


def test_api_delete_fecha_requerida_e_invalida(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.delete("/api/v1/sesion", headers=_h()).status_code == 400
    assert c.delete("/api/v1/sesion?fecha=ayer", headers=_h()).status_code == 400


# --- Catálogo -----------------------------------------------------------------


def test_api_ejercicios_catalogo(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    r = _client().get("/api/v1/ejercicios", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["count"] == 2
    by_name = {e["ejercicio"]: e for e in data["ejercicios"]}
    assert by_name["Press"]["grupo_muscular"] == "Pectoral"
    assert by_name["Press"]["categoria"] == "EMPUJE"


# --- Gate LAN ------------------------------------------------------------------


def _lan_scope(*, method="GET", path="/", client=("192.168.1.25", 50000)):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "scheme": "http",
        "server": ("0.0.0.0", 8000),
        "client": client,
        "headers": [],
    }


def _run_lan(scope):
    """Ejecuta un scope contra LanSyncOnlyMiddleware en un hilo propio.

    Igual que tests/test_security.py::_run: los e2e de Playwright dejan un
    event loop en marcha en el hilo principal y estos tests deben funcionar
    en cualquier orden de ejecución de pytest.
    """
    import asyncio
    import threading

    from src.network_access import LanSyncOnlyMiddleware

    outcome = {}

    async def send(message):
        if message["type"] == "http.response.start":
            outcome["status"] = message["status"]

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(LanSyncOnlyMiddleware(_ok_inner)(scope, receive, send))
        finally:
            loop.close()

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    return outcome.get("status", 0)


async def _ok_inner(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_api_lan_permite_solo_rutas_api_y_sync(monkeypatch):
    monkeypatch.setenv("GYM_LAN_SYNC_ONLY", "1")
    # Permitidas remotas (v1 + sync existente).
    for method, path in (
        ("GET", "/api/v1/sesion"),
        ("POST", "/api/v1/sesion"),
        ("DELETE", "/api/v1/sesion"),
        ("GET", "/api/v1/ejercicios"),
        ("GET", "/api/v1/plantillas"),
        ("POST", "/api/v1/plantilla/guardar"),
        ("POST", "/api/v1/plantilla/aplicar"),
        ("POST", "/api/v1/ejercicio"),
        ("GET", "/api/v1/undo/peek"),
        ("POST", "/api/v1/undo"),
        ("GET", "/api/v1/diario"),
        ("POST", "/api/v1/diario"),
        ("DELETE", "/api/v1/diario"),
        ("GET", "/api/v1/alimentos"),
        ("POST", "/api/v1/alimento"),
        ("GET", "/api/v1/plantillas-comida"),
        ("POST", "/api/v1/plantilla-comida/guardar"),
        ("POST", "/api/v1/plantilla-comida/aplicar"),
        ("GET", "/api/v1/sugerencia"),
        ("GET", "/api/v1/ejercicio/ultimo"),
        ("GET", "/api/v1/cardio"),
        ("POST", "/api/v1/cardio/anotacion"),
        ("GET", "/api/v1/fechas"),
        ("POST", "/sync/health-connect"),
    ):
        assert _run_lan(_lan_scope(method=method, path=path)) == 200
    # Todo lo demás remoto sigue 403: dashboard, htmx, prefijos y métodos cruzados.
    for method, path in (
        ("GET", "/"),
        ("GET", "/diario"),
        ("POST", "/entrenamiento/session/save"),
        ("GET", "/sync/health-connect"),
        ("POST", "/api/v1/ejercicios"),
        ("POST", "/api/v1/plantillas"),
        ("GET", "/api/v1/plantilla/guardar"),
        ("GET", "/api/v1/ejercicio"),
        ("GET", "/api/v1/undo"),
        ("POST", "/api/v1/alimentos"),
        ("POST", "/api/v1/cardio"),
        ("GET", "/api/v1/cardio/anotacion"),
        ("GET", "/api/v1/alimento"),
        ("POST", "/api/v1/plantillas-comida"),
        ("GET", "/api/v1/sesion/extra"),
        ("POST", "/api/v1/sesion/extra"),
        ("POST", "/api/v1/plantilla/1/aplicar"),
    ):
        assert _run_lan(_lan_scope(method=method, path=path)) == 403


def test_api_lan_loopback_sigue_intacto(monkeypatch):
    monkeypatch.setenv("GYM_LAN_SYNC_ONLY", "1")
    assert _run_lan(_lan_scope(path="/", client=("127.0.0.1", 55555))) == 200


# --- B1: plantillas -----------------------------------------------------------


def _make_template(db):
    from src.models import TemplateInput
    from src.template_service import save_template

    return save_template(db, TemplateInput(nombre="Tiron", ejercicios=["Remo", "Press"]))


def test_api_plantillas_lista(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    tpl = _make_template(db)
    r = _client().get("/api/v1/plantillas", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["count"] == 1
    item = data["plantillas"][0]
    assert item["id"] == tpl.id
    assert item["nombre"] == "Tiron"
    assert item["ejercicios"] == ["Remo", "Press"]
    assert item["clasificacion"]


def test_api_plantilla_aplicar_preview_sin_escribir(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    tpl = _make_template(db)
    fecha = _fecha()
    # Con historial: hereda kg/reps de la última vez por ejercicio.
    ordered = [
        {"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2, "descanso_seg": 90},
        {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
    ]
    _client().post("/api/v1/sesion", json={"fecha": fecha, "sets": ordered}, headers=_h())
    r = _client().post(
        "/api/v1/plantilla/aplicar", json={"plantilla_id": tpl.id, "fecha": fecha}, headers=_h()
    )
    assert r.status_code == 200
    data = r.json()
    assert data["plantilla_id"] == tpl.id
    assert data["fecha"] == fecha
    assert [s["ejercicio"] for s in data["sets"]] == ["Remo", "Press"]
    assert data["sets"][0]["kg"] == 60
    assert data["sets"][0]["set_orden"] == 1
    # Sin escribir: el día sigue intacto.
    got = _client().get(f"/api/v1/sesion?fecha={fecha}", headers=_h()).json()
    assert [s["ejercicio"] for s in got["sets"]] == ["Remo", "Press"]


def test_api_plantilla_aplicar_sin_historial_filas_vacias(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    tpl = _make_template(db)
    r = _client().post(
        "/api/v1/plantilla/aplicar", json={"plantilla_id": tpl.id, "fecha": _fecha()}, headers=_h()
    )
    assert r.status_code == 200
    assert all(s["kg"] is None for s in r.json()["sets"])


def test_api_plantilla_aplicar_404_y_400(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert (
        c.post(
            "/api/v1/plantilla/aplicar", json={"plantilla_id": 999, "fecha": _fecha()}, headers=_h()
        ).status_code
        == 404
    )
    assert (
        c.post("/api/v1/plantilla/aplicar", json={"fecha": _fecha()}, headers=_h()).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla/aplicar", json={"plantilla_id": "x", "fecha": _fecha()}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla/aplicar", json={"plantilla_id": 1, "fecha": "ayer"}, headers=_h()
        ).status_code
        == 400
    )


def test_api_plantilla_guardar_upsert(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    r = c.post(
        "/api/v1/plantilla/guardar",
        json={"nombre": "Empuje", "ejercicios": ["Press"]},
        headers=_h(),
    )
    assert r.status_code == 200
    data = r.json()["plantilla"]
    assert data["nombre"] == "Empuje"
    assert data["updated"] is False
    # Mismo nombre → actualiza (upsert como la web), no duplica.
    again = c.post(
        "/api/v1/plantilla/guardar",
        json={"nombre": "empuje", "ejercicios": ["Press", "Remo"]},
        headers=_h(),
    )
    assert again.status_code == 200
    assert again.json()["plantilla"]["updated"] is True
    assert again.json()["plantilla"]["id"] == data["id"]
    assert c.get("/api/v1/plantillas", headers=_h()).json()["count"] == 1


def test_api_plantilla_guardar_400(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert (
        c.post(
            "/api/v1/plantilla/guardar", json={"ejercicios": ["Press"]}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla/guardar", json={"nombre": "X", "ejercicios": []}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post("/api/v1/plantilla/guardar", json={"nombre": "X"}, headers=_h()).status_code == 400
    )


# --- B1: alta de ejercicio -----------------------------------------------------


def test_api_ejercicio_alta_y_409_duplicado(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    r = c.post(
        "/api/v1/ejercicio",
        json={"ejercicio": "Sentadilla", "grupo_muscular": "Cuadriceps", "categoria": "PIERNA"},
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json()["ejercicio"]["ejercicio"] == "Sentadilla"
    assert r.json()["ejercicio"]["categoria"] == "PIERNA"
    assert c.get("/api/v1/ejercicios", headers=_h()).json()["count"] == 3
    # Duplicado case-insensitive → 409 (no 400).
    dup = c.post(
        "/api/v1/ejercicio",
        json={"ejercicio": "sentadilla", "grupo_muscular": "Cuadriceps", "categoria": "PIERNA"},
        headers=_h(),
    )
    assert dup.status_code == 409
    # La categoría se deriva: aunque venga otra, manda el grupo (EMPUJE).
    derived = c.post(
        "/api/v1/ejercicio",
        json={"ejercicio": "Aperturas", "grupo_muscular": "Pectoral", "categoria": "PIERNA"},
        headers=_h(),
    )
    assert derived.status_code == 200
    assert derived.json()["ejercicio"]["categoria"] == "EMPUJE"
    # Sin categoría también vale (se deriva); grupo desconocido → 400.
    nocat = c.post(
        "/api/v1/ejercicio",
        json={"ejercicio": "Curl", "grupo_muscular": "Biceps"},
        headers=_h(),
    )
    assert nocat.status_code == 200
    assert nocat.json()["ejercicio"]["categoria"] == "TIRON"
    bad = c.post(
        "/api/v1/ejercicio",
        json={"ejercicio": "X", "grupo_muscular": "Y", "categoria": "NOPE"},
        headers=_h(),
    )
    assert bad.status_code == 400
    assert c.post("/api/v1/ejercicio", json={"ejercicio": "X"}, headers=_h()).status_code == 400


def test_api_ejercicios_incluye_meta_categorias(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    data = _client().get("/api/v1/ejercicios", headers=_h()).json()
    names = [c["name"] for c in data["meta"]["categorias"]]
    assert "EMPUJE" in names
    assert any("Pectoral" in c["muscles"] for c in data["meta"]["categorias"])


# --- B1: undo ------------------------------------------------------------------


def test_api_undo_peek_vacio_y_sesion(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.get("/api/v1/undo/peek", headers=_h()).json() == {"schema_version": 1, "kind": "empty"}
    fecha = _fecha()
    c.post("/api/v1/sesion", json={"fecha": fecha, "sets": _sets()}, headers=_h())
    peek = c.get("/api/v1/undo/peek", headers=_h()).json()
    assert peek == {"schema_version": 1, "kind": "sesion", "fecha_iso": fecha}
    # El peek no consume: sigue ahí.
    assert c.get("/api/v1/undo/peek", headers=_h()).json()["kind"] == "sesion"


def test_api_undo_restaura_sesion(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    c.post("/api/v1/sesion", json={"fecha": fecha, "sets": _sets()}, headers=_h())
    r = c.post("/api/v1/undo", json={"fecha": fecha}, headers=_h())
    assert r.status_code == 200
    assert r.json() == {
        "schema_version": 1,
        "kind": "sesion",
        "fecha_iso": fecha,
        "has_data": False,
    }
    assert c.get(f"/api/v1/sesion?fecha={fecha}", headers=_h()).json()["has_data"] is False
    # Pila vacía: kind empty, y el peek lo confirma.
    empty = c.post("/api/v1/undo", json={}, headers=_h())
    assert empty.json()["kind"] == "empty"
    assert c.get("/api/v1/undo/peek", headers=_h()).json()["kind"] == "empty"


def test_api_undo_sin_cuerpo_y_401(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    assert c.post("/api/v1/undo", headers=_h()).json()["kind"] == "empty"
    assert c.post("/api/v1/undo", json={}).status_code == 401
    assert c.get("/api/v1/undo/peek").status_code == 401


# --- B2: diario de alimentación --------------------------------------------------


def _seed_food(db):
    from src.database import insert_alimento

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
    insert_alimento(
        db,
        {
            "nombre": "Pollo",
            "categoria": "Carne",
            "kcal": 165.0,
            "carbohidratos": 0.0,
            "fibra": 0.0,
            "proteina": 31.0,
            "grasa": 3.6,
            "hierro": 1.0,
            "calcio": 15.0,
            "vitamina_c": 0.0,
            "vitamina_a": 0.0,
        },
    )


def _auth_food(monkeypatch, tmp_path):
    db = _auth(monkeypatch, tmp_path)
    _seed_food(db)
    return db


def _food_entries():
    return [
        {"alimento": "Avena", "cantidad_g": 50},
        {"alimento": "Pollo", "cantidad_g": 200},
    ]


def test_api_diario_vacio_con_objetivo_por_defecto(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    r = _client().get(f"/api/v1/diario?fecha={_fecha()}", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["has_data"] is False
    assert data["entradas"] == []
    assert data["prefilled"] is False
    assert data["prefill_source"] is None
    # Defaults web: peso 70 → prot 105, grasa 77, kcal 2300, carb 297.
    assert data["parametros"]["peso_kg"] == 70.0
    assert data["objetivo"] == {
        "kcal": 2300.0,
        "carbohidratos": 297.0,
        "proteina": 105.0,
        "grasa": 77.0,
        "fibra": 38.0,
        "hierro": 8.0,
        "calcio": 1000.0,
        "vitamina_c": 90.0,
        "vitamina_a": 900.0,
    }


def test_api_diario_prefill_del_dia_previo(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    ayer = _fecha(-1)
    c.post("/api/v1/diario", json={"fecha": ayer, "entradas": _food_entries()}, headers=_h())
    data = c.get(f"/api/v1/diario?fecha={_fecha()}", headers=_h()).json()
    assert data["has_data"] is False
    assert data["prefilled"] is True
    assert data["prefill_source"] == ayer
    assert [e["alimento"] for e in data["entradas"]] == ["Avena", "Pollo"]


def test_api_diario_post_recalcula_en_servidor(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    body = {
        "fecha": fecha,
        "entradas": _food_entries(),
        "peso_kg": 80,
        "factor_proteina": 2,
        "factor_grasa": 1,
        "kcal_objetivo": 2500,
        "fibra_objetivo": 30,
        "hierro_objetivo": 10,
        "calcio_objetivo": 1200,
        "vitamina_c_objetivo": 100,
        "vitamina_a_objetivo": 800,
    }
    r = c.post("/api/v1/diario", json=body, headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["saved_count"] == 2
    assert data["has_data"] is True
    avena, pollo = data["entradas"]
    # Avena 50 g: 389*0.5=194.5 → 195 (half-up servidor, nunca del cliente).
    assert avena["kcal"] == 195.0
    assert avena["proteina"] == 9.0
    assert pollo["kcal"] == 330.0
    assert data["consumido"]["kcal"] == 525.0
    assert data["consumido"]["cantidad_g"] == 250.0
    assert data["objetivo"]["proteina"] == 160.0
    assert data["objetivo"]["grasa"] == 80.0
    assert data["objetivo"]["carbohidratos"] == 285.0
    assert data["objetivo"]["fibra"] == 30.0
    assert data["objetivo"]["vitamina_a"] == 800.0
    assert data["parametros"]["peso_kg"] == 80.0
    assert data["parametros"]["calcio_objetivo"] == 1200.0
    # Relectura idéntica.
    assert (
        c.get(f"/api/v1/diario?fecha={fecha}", headers=_h()).json()["consumido"]
        == data["consumido"]
    )


def test_api_diario_post_idempotente_y_reemplaza(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    body = {"fecha": fecha, "entradas": _food_entries()}
    assert c.post("/api/v1/diario", json=body, headers=_h()).status_code == 200
    assert c.post("/api/v1/diario", json=body, headers=_h()).status_code == 200
    assert len(c.get(f"/api/v1/diario?fecha={fecha}", headers=_h()).json()["entradas"]) == 2
    one = {"fecha": fecha, "entradas": [{"alimento": "Avena", "cantidad_g": 100}]}
    assert c.post("/api/v1/diario", json=one, headers=_h()).json()["saved_count"] == 1


def test_api_diario_post_400(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    assert (
        c.post("/api/v1/diario", json={"entradas": _food_entries()}, headers=_h()).status_code
        == 400
    )
    assert (
        c.post("/api/v1/diario", json={"fecha": fecha, "entradas": []}, headers=_h()).status_code
        == 400
    )
    # Alimento desconocido → 404; cantidad 0 → 400; fila parcial → 400.
    unknown = {"fecha": fecha, "entradas": [{"alimento": "Nada", "cantidad_g": 10}]}
    assert c.post("/api/v1/diario", json=unknown, headers=_h()).status_code == 404
    zero = {"fecha": fecha, "entradas": [{"alimento": "Avena", "cantidad_g": 0}]}
    assert c.post("/api/v1/diario", json=zero, headers=_h()).status_code == 400
    partial = {"fecha": fecha, "entradas": [{"alimento": "Avena"}]}
    assert c.post("/api/v1/diario", json=partial, headers=_h()).status_code == 400
    # Parámetros inválidos → 400.
    bad_param = {"fecha": fecha, "entradas": _food_entries(), "peso_kg": -80}
    assert c.post("/api/v1/diario", json=bad_param, headers=_h()).status_code == 400
    bad_param2 = {"fecha": fecha, "entradas": _food_entries(), "peso_kg": "mucho"}
    assert c.post("/api/v1/diario", json=bad_param2, headers=_h()).status_code == 400
    assert (
        c.post(
            "/api/v1/diario", json={"fecha": "ayer", "entradas": _food_entries()}, headers=_h()
        ).status_code
        == 400
    )


def test_api_diario_delete_idempotente(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    c.post("/api/v1/diario", json={"fecha": fecha, "entradas": _food_entries()}, headers=_h())
    r = c.delete(f"/api/v1/diario?fecha={fecha}", headers=_h())
    assert r.json() == {"schema_version": 1, "fecha": fecha, "deleted": True}
    assert c.get(f"/api/v1/diario?fecha={fecha}", headers=_h()).json()["has_data"] is False
    assert c.delete(f"/api/v1/diario?fecha={fecha}", headers=_h()).status_code == 200


def test_api_undo_alimentacion(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    c.post("/api/v1/diario", json={"fecha": fecha, "entradas": _food_entries()}, headers=_h())
    assert c.get("/api/v1/undo/peek", headers=_h()).json() == {
        "schema_version": 1,
        "kind": "alimentacion",
        "fecha_iso": fecha,
    }
    r = c.post("/api/v1/undo", json={"fecha": fecha}, headers=_h())
    assert r.json()["kind"] == "alimentacion"
    assert r.json()["has_data"] is False
    assert c.get(f"/api/v1/diario?fecha={fecha}", headers=_h()).json()["has_data"] is False


# --- B2: alimentos -----------------------------------------------------------------


def test_api_alimentos_lista_con_meta(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    data = _client().get("/api/v1/alimentos", headers=_h()).json()
    assert data["schema_version"] == 1
    assert data["count"] == 2
    avena = next(a for a in data["alimentos"] if a["nombre"] == "Avena")
    assert avena["kcal"] == 389.0
    assert avena["categoria"] == "Cereal"
    assert [n["name"] for n in data["meta"]["nutrientes"]] == [
        "kcal",
        "carbohidratos",
        "fibra",
        "proteina",
        "grasa",
        "hierro",
        "calcio",
        "vitamina_c",
        "vitamina_a",
    ]


def test_api_alimento_alta_y_409(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    body = {
        "nombre": "Huevo",
        "categoria": "Proteina",
        "kcal": 155,
        "carbohidratos": 1.1,
        "fibra": 0,
        "proteina": 13,
        "grasa": 11,
        "hierro": 1.8,
        "calcio": 50,
        "vitamina_c": 0,
        "vitamina_a": 160,
    }
    r = c.post("/api/v1/alimento", json=body, headers=_h())
    assert r.status_code == 200
    assert r.json()["alimento"] == {"nombre": "Huevo", "categoria": "Proteina"}
    assert c.get("/api/v1/alimentos", headers=_h()).json()["count"] == 3
    dup = c.post("/api/v1/alimento", json={**body, "nombre": "huevo"}, headers=_h())
    assert dup.status_code == 409
    bad = c.post("/api/v1/alimento", json={**body, "nombre": "X", "kcal": -1}, headers=_h())
    assert bad.status_code == 400
    assert c.post("/api/v1/alimento", json={}, headers=_h()).status_code == 400


# --- B2: plantillas de comida ---------------------------------------------------------


def test_api_plantilla_comida_guardar_listar_aplicar(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    r = c.post(
        "/api/v1/plantilla-comida/guardar",
        json={"nombre": "Desayuno", "entradas": _food_entries()},
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json()["plantilla"]["updated"] is False
    pid = r.json()["plantilla"]["id"]
    again = c.post(
        "/api/v1/plantilla-comida/guardar",
        json={"nombre": "desayuno", "entradas": [{"alimento": "Avena", "cantidad_g": 100}]},
        headers=_h(),
    )
    assert again.json()["plantilla"] == {"id": pid, "nombre": "desayuno", "updated": True}
    listed = c.get("/api/v1/plantillas-comida", headers=_h()).json()
    assert listed["count"] == 1
    assert listed["plantillas"][0]["alimentos"] == [{"alimento": "Avena", "cantidad_g": 100.0}]
    # Aplicar: preview recalculado, sin escribir en el día.
    fecha = _fecha()
    preview = c.post(
        "/api/v1/plantilla-comida/aplicar",
        json={"plantilla_id": pid, "fecha": fecha},
        headers=_h(),
    )
    assert preview.status_code == 200
    assert preview.json()["entradas"][0]["kcal"] == 389.0
    assert c.get(f"/api/v1/diario?fecha={fecha}", headers=_h()).json()["has_data"] is False
    # Inexistente → 404; vacía → 400.
    assert (
        c.post(
            "/api/v1/plantilla-comida/aplicar",
            json={"plantilla_id": 999, "fecha": fecha},
            headers=_h(),
        ).status_code
        == 404
    )
    assert (
        c.post(
            "/api/v1/plantilla-comida/guardar", json={"nombre": "X", "entradas": []}, headers=_h()
        ).status_code
        == 400
    )


def test_api_b2_rutas_en_gate_y_auth(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    # Sin token → 401 en todas las B2.
    assert c.get("/api/v1/diario?fecha=2026-09-07").status_code == 401
    assert c.get("/api/v1/alimentos").status_code == 401
    assert c.get("/api/v1/plantillas-comida").status_code == 401
    assert c.post("/api/v1/diario", json={}).status_code == 401
    # Fecha ausente → 400 con token.
    assert c.get("/api/v1/diario", headers=_h()).status_code == 400
    assert c.delete("/api/v1/diario", headers=_h()).status_code == 400


def test_api_defensive_cuerpo_invalido_y_lote(tmp_path, monkeypatch):
    """Ramas defensivas de todos los POST/DELETE B1+B2: 413, JSON roto,
    no-dict, item no-dict, lote excesivo, fecha inválida en DELETE."""
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    posts = [
        "/api/v1/sesion",
        "/api/v1/diario",
        "/api/v1/alimento",
        "/api/v1/plantilla/guardar",
        "/api/v1/plantilla/aplicar",
        "/api/v1/plantilla-comida/guardar",
        "/api/v1/plantilla-comida/aplicar",
        "/api/v1/ejercicio",
        "/api/v1/undo",
    ]
    # 413 con cuerpo mínimo (límite temporal).
    monkeypatch.setattr(appmod, "MAX_BODY_BYTES", 5)
    for path in posts:
        r = c.post(path, json={"fecha": _fecha()}, headers=_h())
        assert r.status_code == 413, path
    monkeypatch.setattr(appmod, "MAX_BODY_BYTES", 1024 * 1024)
    # JSON roto y no-dict.
    for path in posts:
        r = c.post(path, content=b"{no json", headers={**_h(), "Content-Type": "application/json"})
        assert r.status_code == 400, path
        r = c.post(path, json=[1, 2], headers=_h())
        assert r.status_code == 400, path
    # Item no-dict en listas.
    fecha = _fecha()
    assert (
        c.post(
            "/api/v1/diario",
            json={"fecha": fecha, "entradas": ["Avena"]},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/sesion",
            json={"fecha": fecha, "sets": ["Press"]},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla-comida/guardar",
            json={"nombre": "X", "entradas": ["Avena"]},
            headers=_h(),
        ).status_code
        == 400
    )
    # Lote > 100.
    big_food = {"fecha": fecha, "entradas": [{"alimento": "Avena", "cantidad_g": 10}] * 101}
    assert c.post("/api/v1/diario", json=big_food, headers=_h()).status_code == 400
    big_sets = {"fecha": fecha, "sets": [_sets()[0]] * 101}
    assert c.post("/api/v1/sesion", json=big_sets, headers=_h()).status_code == 400
    # plantilla_id booleano no es entero válido.
    assert (
        c.post(
            "/api/v1/plantilla/aplicar", json={"plantilla_id": True, "fecha": fecha}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla-comida/aplicar",
            json={"plantilla_id": True, "fecha": fecha},
            headers=_h(),
        ).status_code
        == 400
    )
    # undo con cuerpo roto / no-dict / fecha no-str.
    assert (
        c.post(
            "/api/v1/undo", content=b"{no", headers={**_h(), "Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert c.post("/api/v1/undo", json=[1], headers=_h()).status_code == 400
    assert c.post("/api/v1/undo", json={"fecha": 7}, headers=_h()).status_code == 400
    # DELETE con fecha inválida.
    assert c.delete("/api/v1/diario?fecha=ayer", headers=_h()).status_code == 400
    assert c.delete("/api/v1/sesion?fecha=ayer", headers=_h()).status_code == 400
    # Nombres y categorías sobredimensionados.
    long_name = "x" * 201
    assert (
        c.post(
            "/api/v1/alimento",
            json={"nombre": long_name, "kcal": 1},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post("/api/v1/alimento", json={"nombre": "X", "categoria": 7}, headers=_h()).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/ejercicio", json={"ejercicio": "X", "grupo_muscular": "Y"}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/plantilla-comida/guardar",
            json={"nombre": long_name, "entradas": [{"alimento": "Avena", "cantidad_g": 1}]},
            headers=_h(),
        ).status_code
        == 400
    )
    # GET diario con fecha inválida.
    assert c.get("/api/v1/diario?fecha=ayer", headers=_h()).status_code == 400


# --- Rueda de sugerencia ------------------------------------------------------------


def _monday(n=1):
    """Lunes de hace n semanas (fechas fijas, deterministas)."""
    today = datetime.date.today()
    return (today - datetime.timedelta(days=today.weekday() + 7 * n)).strftime("%Y-%m-%d")


def _plus(fecha, days):
    d = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()
    return (d + datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def _split_db(monkeypatch, tmp_path):
    from src.database import set_active_split
    from src.models import SplitInput, SplitItemInput
    from src.split_service import save_split

    db = _auth_food(monkeypatch, tmp_path)
    items = [
        SplitItemInput(dia="LUNES", ejercicio="Press"),
        SplitItemInput(dia="MARTES", ejercicio="Remo"),
    ]
    result = save_split(db, SplitInput(nombre="PPL", items=items))
    set_active_split(db, result.id)
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE training_splits SET created_at = '2026-08-01 10:00:00' WHERE id = ?",
        (result.id,),
    )
    conn.commit()
    conn.close()
    return db


def test_api_sugerencia_deuda_y_pesos(tmp_path, monkeypatch):
    from src.training_service import save_session

    db = _split_db(monkeypatch, tmp_path)
    c = _client()
    mon = _monday()
    tue = _plus(mon, 1)
    save_session(db, _plus(mon, -4), [{"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2}])
    # Lunes faltado: el martes sugiere LUNES con pendiente y últimos pesos.
    r = c.get(f"/api/v1/sugerencia?fecha={tue}", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["tipo"] == "rutina"
    assert data["slot_dia"] == "LUNES"
    assert data["pendiente_desde"] == mon
    assert data["ejercicios"] == ["Press"]
    assert data["explicacion"]
    # Sin historial de Press: en blanco (no inventa).
    assert data["sets"][0]["kg"] is None


def test_api_sugerencia_con_historial_y_descanso(tmp_path, monkeypatch):
    from src.training_service import save_session

    db = _split_db(monkeypatch, tmp_path)
    c = _client()
    mon = _monday()
    save_session(db, _plus(mon, -7), [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    save_session(db, _plus(mon, -4), [{"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2}])
    save_session(db, mon, [{"ejercicio": "Press", "kg": 82, "reps": 8, "rir": 1}])
    r = c.get(f"/api/v1/sugerencia?fecha={_plus(mon, 1)}", headers=_h())
    data = r.json()
    assert data["slot_dia"] == "MARTES"
    assert data["sets"][0]["kg"] == 60
    assert data["sets"][0]["fuente_fecha"] == _plus(mon, -4)
    # Tras hacer el martes, el miércoles de calendario descansa en la rueda.
    save_session(db, _plus(mon, 1), [{"ejercicio": "Remo", "kg": 62, "reps": 10, "rir": 2}])
    r = c.get(f"/api/v1/sugerencia?fecha={_plus(mon, 2)}", headers=_h())
    assert r.json()["tipo"] == "descanso"


def test_api_sugerencia_nada_auth_y_gate(tmp_path, monkeypatch):
    _split_db(monkeypatch, tmp_path)
    c = _client()
    assert c.get("/api/v1/sugerencia").status_code == 401
    assert c.get("/api/v1/sugerencia?fecha=ayer", headers=_h()).status_code == 400
    assert c.get("/api/v1/sugerencia", headers=_h()).status_code == 400


def test_api_ejercicio_ultimo_posicional_y_auth(tmp_path, monkeypatch):
    from src.training_service import save_session

    db = _auth(monkeypatch, tmp_path)
    c = _client()
    # Sin auth → 401; auth ok:
    assert c.get("/api/v1/ejercicio/ultimo?ejercicio=Press").status_code == 401
    hoy = _fecha()
    save_session(
        db,
        _fecha(-3),
        [
            {"ejercicio": "Remo", "kg": 60, "reps": 10, "rir": 2},
            {"ejercicio": "Press", "kg": 79, "reps": 8, "rir": 1.5},
            {"ejercicio": "Press", "kg": 78, "reps": 8, "rir": 1.5},
        ],
    )
    r = c.get(f"/api/v1/ejercicio/ultimo?ejercicio=Press&fecha={hoy}", headers=_h())
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 1
    assert data["ejercicio"] == "Press"
    assert [s["pos"] for s in data["series"]] == [1, 2]
    assert [s["kg"] for s in data["series"]] == [79, 78]
    # Excluye el propio día y el futuro: con fecha del historial no ve nada posterior.
    r = c.get("/api/v1/ejercicio/ultimo?ejercicio=Press&fecha=2020-01-01", headers=_h())
    assert r.json()["series"] == []
    # HIIT vale sin estar en el catálogo (sin historial → vacío, 200).
    r = c.get(f"/api/v1/ejercicio/ultimo?ejercicio=HIIT&fecha={hoy}", headers=_h())
    assert r.status_code == 200
    assert r.json()["series"] == []
    assert c.get("/api/v1/ejercicio/ultimo?ejercicio=&fecha=x", headers=_h()).status_code == 400
    assert c.get("/api/v1/ejercicio/ultimo", headers=_h()).status_code == 400
    assert (
        c.get("/api/v1/ejercicio/ultimo?ejercicio=Press&fecha=ayer", headers=_h()).status_code
        == 400
    )
    assert c.get("/api/v1/ejercicio/ultimo?ejercicio=Inexistente", headers=_h()).status_code == 400


# --- B3: cardio ------------------------------------------------------------------


def _seed_cardio_day(db, fecha="2026-09-07"):
    import sqlite3
    from datetime import UTC, datetime

    noon = int(datetime(2026, 9, 7, 12, 0, tzinfo=UTC).timestamp() * 1000)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('cardio-1', 'EXERCISE_SESSION', ?, ?, ?, 1, "
        "'{\"value\": {\"title\": \"Cinta\"}}', 'x', 'x')",
        (noon, noon + 30 * 60000, noon),
    )
    conn.execute(
        "INSERT INTO health_records (hc_id, record_type, start_epoch_ms, end_epoch_ms, "
        "last_modified_epoch_ms, payload_schema_version, value_json, received_at, updated_at) "
        "VALUES ('steps-1', 'STEPS', ?, ?, ?, 1, '{\"value\": {\"count\": 5}}', 'x', 'x')",
        (noon, noon + 60000, noon),
    )
    conn.commit()
    conn.close()


def test_api_cardio_dia_vacio_y_con_sesion(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    c = _client()
    empty = c.get("/api/v1/cardio?fecha=2026-09-07", headers=_h())
    assert empty.json() == {
        "schema_version": 1,
        "fecha": "2026-09-07",
        "count": 0,
        "sesiones": [],
    }
    _seed_cardio_day(db)
    data = c.get("/api/v1/cardio?fecha=2026-09-07", headers=_h()).json()
    assert data["count"] == 1
    sesion = data["sesiones"][0]
    assert sesion["hc_id"] == "cardio-1"
    assert sesion["titulo"] == "Cinta"
    assert sesion["duracion_min"] == 30.0
    assert sesion["velocidad_kmh"] is None
    # Solo EXERCISE_SESSION (STEPS no aparece).
    assert c.get("/api/v1/cardio", headers=_h()).status_code == 400
    assert c.get("/api/v1/cardio?fecha=ayer", headers=_h()).status_code == 400
    assert c.get("/api/v1/cardio").status_code == 401


def test_api_cardio_anotacion_upsert_y_borrado(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    _seed_cardio_day(db)
    c = _client()
    r = c.post(
        "/api/v1/cardio/anotacion",
        json={
            "hc_id": "cardio-1",
            "velocidad_kmh": 10.5,
            "inclinacion_pct": 1.0,
            "notas": "series",
        },
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json() == {"schema_version": 1, "hc_id": "cardio-1", "deleted": False}
    sesion = c.get("/api/v1/cardio?fecha=2026-09-07", headers=_h()).json()["sesiones"][0]
    assert (sesion["velocidad_kmh"], sesion["inclinacion_pct"], sesion["notas"]) == (
        10.5,
        1.0,
        "series",
    )
    # Todo vacío = borrar.
    r = c.post("/api/v1/cardio/anotacion", json={"hc_id": "cardio-1"}, headers=_h())
    assert r.json()["deleted"] is True
    sesion = c.get("/api/v1/cardio?fecha=2026-09-07", headers=_h()).json()["sesiones"][0]
    assert sesion["velocidad_kmh"] is None
    # hc inexistente → 400; tipo no-sesión → 400; no numérico → 400.
    assert (
        c.post(
            "/api/v1/cardio/anotacion", json={"hc_id": "nope", "velocidad_kmh": 9}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/cardio/anotacion", json={"hc_id": "steps-1", "velocidad_kmh": 9}, headers=_h()
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/cardio/anotacion",
            json={"hc_id": "cardio-1", "velocidad_kmh": "rapido"},
            headers=_h(),
        ).status_code
        == 400
    )
    assert c.post("/api/v1/cardio/anotacion", json={}, headers=_h()).status_code == 400
    assert c.post("/api/v1/cardio/anotacion", json={}, headers={}).status_code == 401


# --- B4: fechas con datos ------------------------------------------------------------


def test_api_fechas_por_vista(tmp_path, monkeypatch):
    _auth_food(monkeypatch, tmp_path)
    c = _client()
    train_fecha, food_fecha = "2026-09-05", "2026-09-06"
    c.post("/api/v1/sesion", json={"fecha": train_fecha, "sets": _sets()}, headers=_h())
    c.post(
        "/api/v1/diario",
        json={"fecha": food_fecha, "entradas": [{"alimento": "Avena", "cantidad_g": 50}]},
        headers=_h(),
    )
    assert c.get("/api/v1/fechas?vista=entrenamiento", headers=_h()).json() == {
        "schema_version": 1,
        "vista": "entrenamiento",
        "fechas": [train_fecha],
    }
    assert c.get("/api/v1/fechas?vista=alimentacion", headers=_h()).json()["fechas"] == [food_fecha]
    assert c.get("/api/v1/fechas?vista=todas", headers=_h()).json()["fechas"] == [
        train_fecha,
        food_fecha,
    ]
    assert c.get("/api/v1/fechas", headers=_h()).json()["vista"] == "entrenamiento"
    assert c.get("/api/v1/fechas?vista=otra", headers=_h()).status_code == 400
    assert c.get("/api/v1/fechas?vista=entrenamiento").status_code == 401


# --- HIIT: velocidad + dificultad en vez de kg/reps/rir --------------------------------


def test_api_sesion_hiit_roundtrip(tmp_path, monkeypatch):
    db = _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    # Separación estricta: sesión HIIT pura (nunca mixta con fuerza).
    body = {
        "fecha": fecha,
        "sets": [
            {"ejercicio": "HIIT", "velocidad_kmh": 12.34, "dificultad": 7.5},
        ],
    }
    r = c.post("/api/v1/sesion", json=body, headers=_h())
    assert r.status_code == 200
    assert r.json()["saved_count"] == 1
    data = c.get(f"/api/v1/sesion?fecha={fecha}", headers=_h()).json()
    hiit = next(s for s in data["sets"] if s["ejercicio"] == "HIIT")
    assert hiit["kg"] is None
    assert hiit["reps"] is None
    assert hiit["rir"] is None
    assert hiit["rm"] is None
    assert hiit["velocidad_kmh"] == 12.3
    assert hiit["dificultad"] == 7.5
    import sqlite3

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT kg, reps, rir, velocidad_kmh, dificultad FROM training_sets WHERE ejercicio='HIIT'"
    ).fetchone()
    conn.close()
    assert row == (None, None, None, 12.3, 7.5)


def test_api_sesion_hiit_400(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    c = _client()
    fecha = _fecha()
    # Con pesos.
    assert (
        c.post(
            "/api/v1/sesion",
            json={
                "fecha": fecha,
                "sets": [{"ejercicio": "HIIT", "kg": 10, "velocidad_kmh": 10, "dificultad": 5}],
            },
            headers=_h(),
        ).status_code
        == 400
    )
    # Sin velocidad / sin dificultad / dificultad negativa.
    assert (
        c.post(
            "/api/v1/sesion",
            json={"fecha": fecha, "sets": [{"ejercicio": "HIIT", "dificultad": 5}]},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/sesion",
            json={"fecha": fecha, "sets": [{"ejercicio": "HIIT", "velocidad_kmh": 10}]},
            headers=_h(),
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/sesion",
            json={
                "fecha": fecha,
                "sets": [{"ejercicio": "HIIT", "velocidad_kmh": 10, "dificultad": -1}],
            },
            headers=_h(),
        ).status_code
        == 400
    )
    # Mixta fuerza + HIIT: separación estricta.
    assert (
        c.post(
            "/api/v1/sesion",
            json={
                "fecha": fecha,
                "sets": [
                    {"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1},
                    {"ejercicio": "HIIT", "velocidad_kmh": 10, "dificultad": 5},
                ],
            },
            headers=_h(),
        ).status_code
        == 400
    )
