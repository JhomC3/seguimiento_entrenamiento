"""Tests de integración de las rutas del gestor de splits (CSRF, OOB, undo)."""

import re

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
    # Página COMPLETA (extiende base.html): no puede ser un fragmento sin <head>.
    assert r.text.lstrip().startswith("<!DOCTYPE html>")
    assert "<html" in r.text and "<body" in r.text and "app.js" in r.text
    assert "Gestor de splits" in r.text
    assert "Press" in r.text
    assert "Curl" in r.text
    assert 'data-item-type="hiit"' in r.text
    assert 'id="splits-section"' in r.text
    # Sin split: estado vacío con CTA de creación.
    assert "Todavía no hay splits guardados" in r.text
    assert 'data-action="split-new"' in r.text
    # Sin contenedor estrecho: la página usa todo el ancho.
    assert "max-w-7xl" not in r.text
    # Catálogo (aside) aparece antes que la sección de splits en el DOM.
    assert r.text.index('class="splits-catalog-col"') < r.text.index('id="splits-section"')
    # El título del catálogo ya no existe como cabecera visible.
    assert "Catálogo de ejercicios" not in r.text


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


def test_splits_page_resumen_por_tarjeta_v4(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, ("Press", "Pectoral", "EMPUJE"), ("Curl", "Biceps", "TIRON"))
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    _guardar(
        client, dias=("LUNES", "MARTES"), tipos=("ejercicio", "hiit"), ejercicios=("Press", "HIIT")
    )
    r = client.get("/splits?abrir=1")
    assert r.status_code == 200
    # Sin conteos auxiliares ni panel ledger semanal.
    assert "Días activos" not in r.text
    assert "Ejercicios distintos" not in r.text
    assert 'id="split-summary-panel"' not in r.text
    assert 'id="split-summary-week"' not in r.text
    assert 'id="split-summary-days"' not in r.text
    # Resumen jerárquico por día dentro de cada tarjeta (grupos colapsables).
    assert 'class="split-day-summary"' in r.text
    # Sin fila de total en el resumen del día (el total vive en el header de la
    # tarjeta); los grupos son toggles aria-expanded con cuerpo oculto.
    assert '<p class="split-summary-row split-summary-total">' not in r.text
    assert 'class="split-summary-group-toggle"' in r.text
    assert 'aria-expanded="false"' in r.text
    assert "split-summary-group-body" in r.text
    # Las tarjetas de día tienen scrolls internos y el board su propio scroll.
    assert 'class="split-day-items"' in r.text
    assert 'class="split-board-scroll"' in r.text
    # Mini-encabezados de sección: Resumen y Ejercicios en cada tarjeta.
    assert r.text.count("split-day-section-label") == 14
    # Resumen semanal en la cabecera junto al nombre (strip sin fecha).
    assert 'class="split-summary-strip"' in r.text
    assert "actualizado" not in r.text
    assert re.search(r"\d{2}/\d{2} \d{2}:\d{2}", r.text) is None
    assert ">2</strong> series" in r.text
    assert "Pectoral <strong>1</strong>" in r.text
    assert r.text.count('<span class="split-summary-strip-sep">·</span>') == 2
    # Acciones como iconos agrupados (lápiz/guardar/papelera), con Guardar
    # deshabilitado en un split guardado.
    assert 'class="split-item-actions"' in r.text
    assert r.text.count('class="split-action-btn"') == 3
    assert 'aria-label="Editar el split"' in r.text
    assert 'aria-label="Guardar el split"' in r.text
    assert 'aria-label="Eliminar el split"' in r.text
    assert re.search(r'data-action="split-save" class="split-action-btn"\s+disabled', r.text)
    # Handle de copia de día + botón de borrar día con aria-label (ahora en el
    # label de Ejercicios, no en el header del día).
    assert 'class="split-day-copy-btn"' in r.text
    assert 'aria-label="Copiar el día Lunes al día seleccionado"' in r.text
    assert 'class="split-item-remove"' in r.text
    assert 'aria-label="Borrar todos los ejercicios del Lunes"' in r.text
    # Límite expuesto por item para el guard client-side.
    assert 'data-max-items="300"' in r.text


def test_splits_page_layout_y_editmode(tmp_path, monkeypatch):
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    client = _client()
    # Sin split: layout de dos columnas, estado vacío.
    r = client.get("/splits")
    assert r.status_code == 200
    assert 'class="splits-layout"' in r.text
    assert 'class="splits-catalog-col"' in r.text
    assert 'class="splits-editor-col"' in r.text
    assert "splits-empty" in r.text
    # Split guardado: los items se renderizan en modo visualización.
    _guardar(client)
    r = client.get("/splits?abrir=1")
    assert r.status_code == 200
    assert 'data-editmode="0"' in r.text
    assert 'data-action="split-edit"' in r.text
    # "Editar" vive en las acciones del toolbar de cada item.
    assert 'data-action="split-edit-open"' not in r.text
    assert 'class="split-item-actions"' in r.text
    assert re.search(r'data-action="split-save" class="split-action-btn"\s+disabled', r.text)
    # El input de nombre se oculta en modo visualización.
    assert "split-name-input" in r.text


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
    # El item re-renderizado refleja el split guardado (modo visualización).
    assert "split-accordion-item" in r.text
    assert 'data-editmode="0"' in r.text
    assert "Split guardado." in r.text
    assert get_split(db, 1) is not None


def test_split_nuevo_fragmento(tmp_path, monkeypatch):
    db = _setup_db(tmp_path, ("Press", "Pectoral", "EMPUJE"))
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/split/nuevo")
    assert r.status_code == 200
    # Item nuevo sin persistir, en modo edición, con board vacío de 7 días.
    assert "split-item-nuevo" in r.text
    assert 'data-split-id=""' in r.text
    assert 'data-editmode="1"' in r.text
    assert 'data-action="split-save"' in r.text
    # Guardar de un item nuevo NO está deshabilitado (aunque no haya cambios).
    assert 'data-action="split-save" class="split-action-btn" disabled=""' not in r.text
    assert r.text.count('<div class="split-day-zone"') == 7
    assert 'data-day="LUNES"' in r.text
    assert 'class="split-day-summary"' in r.text
    assert 'class="split-day-items"' in r.text
    # Resumen semanal en la cabecera: 0 series.
    assert 'class="split-summary-strip"' in r.text
    assert ">0</strong> series" in r.text


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
    assert 'id="splits-section" hx-swap-oob="outerHTML"' in r.text
    assert get_split(db, 1) is None
    r = client.post("/split/eliminar/1")
    assert r.status_code == 400


def test_split_nuevo_sin_board_fragmento_viejo(tmp_path, monkeypatch):
    """La ruta GET /split/{id} fue retirada (los boards viven en la sección)."""
    db = _setup_db(tmp_path)
    monkeypatch.setattr(appmod, "DB_PATH", db)
    r = _client().get("/split/999")
    assert r.status_code == 404


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
    assert "Todavía no hay splits guardados" in r.text
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
    """El DnD de items es SortableJS con forceFallback (sin DnD nativo paralelo
    a nivel document). La regla central: pull:'clone' SOLO en el catálogo."""
    from pathlib import Path

    src = Path("static/js/splits.js").read_text(encoding="utf-8")
    assert "document.addEventListener('dragstart'" not in src
    assert "document.addEventListener('dragend'" not in src
    assert "document.addEventListener('dragover'" not in src
    assert "forceFallback: true" in src
    assert "fallbackClass: 'split-fallback'" in src
    # pull:'clone' únicamente dentro de buildCatalogSortable.
    catalog = src[
        src.index("function buildCatalogSortable") : src.index("function initCatalogSortables")
    ]
    assert catalog.count("pull: 'clone'") == 1
    assert src.count("pull: 'clone'") == 1
    assert "Sortable.create" in src
    assert "sortable-ghost" in src
    assert "sortable-chosen" in src
