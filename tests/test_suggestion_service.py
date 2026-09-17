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
    # El descanso nunca se hereda: cronómetros de cero.
    assert press.descanso_seg is None
    curl = next(x for x in s.sets if x.ejercicio == "Curl")
    assert (curl.kg, curl.reps, curl.fuente_fecha) == (None, None, None)
    assert curl.descanso_seg is None


def test_sugerencia_no_hereda_descanso(tmp_path):
    """Con descanso guardado en el historial, la sugerencia lo trae vacío."""
    import sqlite3

    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press"]})
    old = _plus(_monday(3), 0)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, "
        "descanso_seg, origen) VALUES (1, 'LUNES', ?, 1, 'Press', 8, 80, 1, 120, 'manual')",
        (old,),
    )
    conn.commit()
    conn.close()
    s = resolve_suggestion(db, _monday())
    assert s.tipo == "rutina"
    assert s.sets[0].kg == 80
    assert s.sets[0].descanso_seg is None


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
    # El descanso nunca se hereda.
    assert s.sets[0].descanso_seg is None


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


def test_split_manda_series_posicionales(tmp_path):
    """Press x3 en el split → 3 filas con serie1=79, serie2=78, serie3=77."""
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Press", "Press"]})
    old = _plus(_monday(3), 0)
    _train(
        db,
        old,
        ("Press", 79, 8, 1.5),
        ("Press", 78, 8, 1.5),
        ("Press", 77, 7, 2),
    )
    s = resolve_suggestion(db, _monday())
    assert s.tipo == "rutina"
    assert [x.kg for x in s.sets] == [79, 78, 77]
    assert [x.fuente_fecha for x in s.sets] == [old, old, old]


def test_split_replica_ultima_si_faltan_series(tmp_path):
    """Split x3 con historial de 1 serie → replica la última (79,79,79)."""
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Press", "Press"]})
    old = _plus(_monday(3), 0)
    _train(db, old, ("Press", 79, 8, 1.5))
    s = resolve_suggestion(db, _monday())
    assert [x.kg for x in s.sets] == [79, 79, 79]


def test_ordinal_ignora_orden_global(tmp_path):
    """Remo primero y Press después: Press serie1 sigue siendo 79."""
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Press"]})
    old = _plus(_monday(3), 0)
    _train(db, old, ("Remo", 60, 10, 2), ("Press", 79, 8, 1.5), ("Press", 78, 8, 1.5))
    s = resolve_suggestion(db, _monday())
    assert [x.kg for x in s.sets] == [79, 78]


def test_mayoria_tres_de_cuatro_avanza(tmp_path):
    """3/4 series (>= 2/3) dan el slot por cumplido: la rueda avanza."""
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Remo", "Curl", "Sentadilla"]})
    mon = _monday()
    tue = _plus(mon, 1)
    _train(db, _plus(mon, -4), ("Sentadilla", 100, 5, 2))
    _train(
        db,
        mon,
        ("Press", 80, 8, 1),
        ("Remo", 60, 10, 2),
        ("Curl", 20, 10, 1),
    )
    s = resolve_suggestion(db, tue)
    assert s.slot_dia != "LUNES"


def test_mitad_no_avanza(tmp_path):
    """1/2 (< 2/3) no cubre: el martes sigue tocando LUNES."""
    db = _db(tmp_path)
    _split(db, {"LUNES": ["Press", "Remo"]})
    mon = _monday()
    tue = _plus(mon, 1)
    _train(db, _plus(mon, -4), ("Sentadilla", 100, 5, 2))
    _train(db, mon, ("Press", 80, 8, 1))
    s = resolve_suggestion(db, tue)
    assert s.slot_dia == "LUNES"
    assert s.pendiente_desde == mon


def test_cobertura_bordes():
    """Ramas límite del cómputo por series (sin DB)."""
    from src.suggestion_service import _coverage_ratio, _slot_covered

    assert _coverage_ratio([], []) == 1.0
    assert _coverage_ratio(["Press"], []) == 0.0
    assert _slot_covered([], []) is True
    assert _slot_covered(["Press"], []) is False
    rows = [{"ejercicio": "Press"}, {"ejercicio": "  "}, {"ejercicio": None}]
    assert _coverage_ratio(["Press", "Press"], rows) == 0.5
    assert _slot_covered(["Press", "Press"], rows) is False
