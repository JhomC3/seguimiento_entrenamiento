"""Rueda de rutina sugerida: split activo + historial (sin saltar entrenos)."""

import datetime

import pytest

from src.database import init_db, insert_exercise, set_active_split
from src.models import SplitInput, SplitItemInput, ValidationError
from src.split_service import save_split
from src.suggestion_service import resolve_suggestion
from src.training_service import save_session


def _db(tmp_path):
    db = str(tmp_path / "sugg.db")
    init_db(db)
    for ej, grupo, cat in (
        ("Press", "Pectoral", "EMPUJE"),
        ("Remo", "Espalda", "TIRON"),
        ("Sentadilla", "Cuadriceps", "PIERNA"),
        ("Pullover", "Espalda", "TIRON"),
        ("Curl", "Biceps", "TIRON"),
    ):
        insert_exercise(db, ej, grupo, cat)
    return db


def _split(db, days):
    """days: {dia: [ejercicios]}. Lo activa y devuelve su id.

    Con created_at antedatado: la rueda mira atrás desde la creación y el
    escenario (semana pasada) debe quedar dentro del plan.
    """
    import sqlite3

    items = [SplitItemInput(dia=dia, ejercicio=ej) for dia, ejs in days.items() for ej in ejs]
    result = save_split(db, SplitInput(nombre="PPL", items=items))
    set_active_split(db, result.id)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE training_splits SET created_at = '2026-08-01 10:00:00' WHERE id = ?",
        (result.id,),
    )
    conn.commit()
    conn.close()
    return result.id


def _train(db, fecha, *sets):
    save_session(
        db,
        fecha,
        [{"ejercicio": e, "kg": kg, "reps": reps, "rir": rir} for e, kg, reps, rir in sets],
    )


def _monday(n=1):
    """Lunes de hace n semanas (fechas fijas, deterministas)."""
    today = datetime.date.today()
    return (today - datetime.timedelta(days=today.weekday() + 7 * n)).strftime("%Y-%m-%d")


def _plus(fecha, days):
    d = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()
    return (d + datetime.timedelta(days=days)).strftime("%Y-%m-%d")


DAYS = {"LUNES": ["Press"], "MARTES": ["Remo"], "JUEVES": ["Sentadilla"]}


def test_fecha_invalida(tmp_path):
    with pytest.raises(ValidationError):
        resolve_suggestion(_db(tmp_path), "ayer")


def test_dia_con_datos_no_sugiere(tmp_path):
    db = _db(tmp_path)
    _split(db, DAYS)
    mon = _monday()
    _train(db, mon, ("Press", 80, 8, 1))
    s = resolve_suggestion(db, mon)
    assert s.tipo == "nada"


def test_en_racha_sugiere_calendario(tmp_path):
    db = _db(tmp_path)
    _split(db, DAYS)
    mon = _monday()
    thu_prev = _plus(mon, -4)
    _train(db, thu_prev, ("Sentadilla", 100, 5, 2))
    tue = _plus(mon, 1)
    s = resolve_suggestion(db, tue)
    # Lunes cumplido (jue pasado + vie/sáb/dom descanso): martes = MARTES.
    _train(db, mon, ("Press", 80, 8, 1))
    s = resolve_suggestion(db, tue)
    assert s.tipo == "rutina"
    assert s.slot_dia == "MARTES"
    assert s.ejercicios == ["Remo"]
    assert s.pendiente_desde is None
    assert "martes" in s.explicacion


def test_falta_congela_y_corre(tmp_path):
    db = _db(tmp_path)
    _split(db, DAYS)
    mon = _monday()
    tue = _plus(mon, 1)
    _train(db, _plus(mon, -4), ("Sentadilla", 100, 5, 2))
    # Lunes faltado: el martes sigue tocando LUNES.
    s = resolve_suggestion(db, tue)
    assert s.tipo == "rutina"
    assert s.slot_dia == "LUNES"
    assert s.pendiente_desde == mon


def test_ejemplo_usuario_pierna_corre_y_jueves_descansa(tmp_path):
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press"], "MARTES": ["Sentadilla"], "JUEVES": ["Remo"]})
    mon = _monday()
    tue, wed, thu = _plus(mon, 1), _plus(mon, 2), _plus(mon, 3)
    _train(db, _plus(mon, -4), ("Remo", 60, 10, 2))
    # Lunes faltado → martes toca LUNES (Press).
    assert resolve_suggestion(db, tue).slot_dia == "LUNES"
    _train(db, tue, ("Press", 80, 8, 1))
    # Miércoles: toca MARTES aunque el calendario diga descanso.
    s = resolve_suggestion(db, wed)
    assert s.slot_dia == "MARTES"
    assert s.ejercicios == ["Sentadilla"]
    _train(db, wed, ("Sentadilla", 100, 5, 2))
    # Jueves: NO es fullbody/Remo, es descanso corrido.
    s = resolve_suggestion(db, thu)
    assert s.tipo == "descanso"


def test_no_coincide_mantiene_deuda(tmp_path):
    db = _db(tmp_path)
    _split(db, DAYS)
    mon = _monday()
    tue = _plus(mon, 1)
    _train(db, _plus(mon, -4), ("Sentadilla", 100, 5, 2))
    # Tocaba Press el lunes e hizo Remo: el martes sigue LUNES.
    _train(db, mon, ("Remo", 60, 10, 2))
    s = resolve_suggestion(db, tue)
    assert s.slot_dia == "LUNES"
    assert s.pendiente_desde == mon


def test_pesos_ultima_vez_y_sin_historial(tmp_path):
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Curl"]})
    old = _plus(_monday(3), 0)
    _train(db, old, ("Press", 80, 8, 1))
    mon = _monday()
    s = resolve_suggestion(db, mon)
    assert s.slot_dia == "LUNES"
    press = next(x for x in s.sets if x.ejercicio == "Press")
    assert (press.kg, press.reps, press.rir, press.fuente_fecha) == (80, 8, 1, old)
    curl = next(x for x in s.sets if x.ejercicio == "Curl")
    assert (curl.kg, curl.reps, curl.fuente_fecha) == (None, None, None)


def test_sin_split_repite_ultimo_dia_tal_cual(tmp_path):
    db = _db(tmp_path)
    last = _plus(_monday(2), 3)
    _train(db, last, ("Pullover", 40, 12, 2))
    s = resolve_suggestion(db, _monday())
    assert s.tipo == "rutina"
    assert s.split_id is None
    # Pullover se mantiene (no se "corrige" a otro ejercicio de espalda).
    assert s.ejercicios == ["Pullover"]
    assert s.sets[0].kg == 40
    assert s.sets[0].fuente_fecha == last


def test_sin_split_ni_historial_nada(tmp_path):
    db = _db(tmp_path)
    s = resolve_suggestion(db, _monday())
    assert s.tipo == "nada"


def test_split_activo_inexistente_repite(tmp_path):
    import sqlite3

    db = _db(tmp_path)
    sid = _split(db, DAYS)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM training_splits WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    last = _plus(_monday(2), 3)
    _train(db, last, ("Press", 80, 8, 1))
    s = resolve_suggestion(db, _monday())
    assert s.tipo == "rutina"
    assert s.split_id is None
    assert s.ejercicios == ["Press"]
