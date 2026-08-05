import pytest

from src.database import init_db, insert_exercise, get_plantillas, get_plantilla, reorder_plantillas
from src.template_service import (
    apply_template_rows,
    classify_template,
    delete_plantilla,
    edit_template,
    save_template,
)
from src.training_service import save_session


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "gym.db")
    init_db(path)
    insert_exercise(path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(path, "Fondos", "Triceps", "EMPUJE")
    insert_exercise(path, "Jalon", "Espalda", "TIRON")
    insert_exercise(path, "Curl", "Biceps", "TIRON")
    insert_exercise(path, "Sentadilla", "Cuadriceps", "PIERNA")
    insert_exercise(path, "Crunch", "Abdomen", "CORE")
    return path


def test_classify_empuje(db):
    assert classify_template(db, ["Press", "Fondos"]) == "EMPUJE"


def test_classify_jalon(db):
    assert classify_template(db, ["Jalon", "Curl"]) == "JALON"


def test_classify_pierna(db):
    assert classify_template(db, ["Sentadilla"]) == "PIERNA"


def test_classify_torso(db):
    assert classify_template(db, ["Press", "Curl"]) == "TORSO"


def test_classify_full_body_con_empuje(db):
    assert classify_template(db, ["Press", "Sentadilla"]) == "FULL BODY"


def test_classify_full_body_con_jalon(db):
    assert classify_template(db, ["Curl", "Sentadilla"]) == "FULL BODY"


def test_classify_solo_core(db):
    assert classify_template(db, ["Crunch"]) == "CORE"


def test_classify_core_neutral(db):
    assert classify_template(db, ["Press", "Crunch"]) == "EMPUJE"


def test_classify_vacio(db):
    assert classify_template(db, []) == "SIN CLASIFICAR"


def test_classify_ejercicio_desconocido(db):
    assert classify_template(db, ["No Existe"]) == "SIN CLASIFICAR"


def test_save_template_crea_y_clasifica(db):
    result = save_template(db, "Mi Empuje", ["Press", "Press", "Fondos", ""])
    assert result["clasificacion"] == "EMPUJE"
    assert result["updated"] is False
    plantillas = get_plantillas(db)
    assert len(plantillas) == 1
    assert plantillas[0]["ejercicios"] == ["Press", "Fondos"]


def test_save_template_mismo_nombre_actualiza(db):
    save_template(db, "Mi Empuje", ["Press"])
    result = save_template(db, "mi empuje", ["Jalon"])
    assert result["updated"] is True
    plantillas = get_plantillas(db)
    assert len(plantillas) == 1
    assert plantillas[0]["ejercicios"] == ["Jalon"]
    assert plantillas[0]["clasificacion"] == "JALON"


def test_save_template_sin_nombre_rechaza(db):
    with pytest.raises(ValueError):
        save_template(db, "  ", ["Press"])


def test_save_template_sin_ejercicios_rechaza(db):
    with pytest.raises(ValueError):
        save_template(db, "Vacia", [])


def test_edit_template_renombra_y_clasifica(db):
    pid = save_template(db, "Antes", ["Press"])["id"]
    edit_template(db, pid, "Despues", ["Press", "Curl"])
    plantilla = get_plantilla(db, pid)
    assert plantilla["nombre"] == "Despues"
    assert plantilla["clasificacion"] == "TORSO"
    assert plantilla["ejercicios"] == ["Press", "Curl"]


def test_edit_template_nombre_duplicado_rechaza(db):
    save_template(db, "A", ["Press"])
    pid = save_template(db, "B", ["Curl"])["id"]
    with pytest.raises(ValueError):
        edit_template(db, pid, "A", ["Curl"])


def test_delete_template(db):
    pid = save_template(db, "A", ["Press"])["id"]
    delete_plantilla(db, pid)
    assert get_plantilla(db, pid) is None
    assert get_plantillas(db) == []


def test_apply_template_usa_ultimo_realizado(db):
    save_session(db, "2026-01-10", [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    save_session(db, "2026-01-12", [
        {"ejercicio": "Press", "kg": 85, "reps": 6, "rir": 2},
        {"ejercicio": "Press", "kg": 85, "reps": 5, "rir": 3},
    ])
    save_session(db, "2026-01-13", [{"ejercicio": "Curl", "kg": 20, "reps": 10, "rir": 0}])
    pid = save_template(db, "T", ["Press", "Curl"])["id"]
    rows = apply_template_rows(db, pid)
    assert len(rows) == 3
    assert rows[0] == {"ejercicio": "Press", "kg": 85, "reps": 6, "rir": 2}
    assert rows[1] == {"ejercicio": "Press", "kg": 85, "reps": 5, "rir": 3}
    assert rows[2] == {"ejercicio": "Curl", "kg": 20, "reps": 10, "rir": 0}


def test_apply_template_ultimo_realizado_cada_ejercicio(db):
    save_session(db, "2026-02-10", [{"ejercicio": "Press", "kg": 100, "reps": 5, "rir": 1}])
    save_session(db, "2026-02-11", [{"ejercicio": "Curl", "kg": 18, "reps": 12, "rir": 1}])
    save_session(db, "2026-02-12", [{"ejercicio": "Press", "kg": 102, "reps": 5, "rir": 2}])
    pid = save_template(db, "T", ["Curl", "Press"])["id"]
    rows = apply_template_rows(db, pid)
    assert [r["kg"] for r in rows] == [18, 102]


def test_apply_template_sin_historial_deja_fila_vacia(db):
    pid = save_template(db, "T", ["Press", "Fondos"])["id"]
    rows = apply_template_rows(db, pid)
    assert rows == [
        {"ejercicio": "Press", "kg": "", "reps": "", "rir": ""},
        {"ejercicio": "Fondos", "kg": "", "reps": "", "rir": ""},
    ]


def test_apply_template_inexistente_rechaza(db):
    with pytest.raises(ValueError):
        apply_template_rows(db, 999)


def test_plantillas_se_crean_en_orden_de_insercion(db):
    save_template(db, "B", ["Press"])
    save_template(db, "A", ["Curl"])
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["B", "A"]


def test_reorder_plantillas(db):
    pid_a = save_template(db, "A", ["Press"])["id"]
    pid_b = save_template(db, "B", ["Curl"])["id"]
    reorder_plantillas(db, [pid_b, pid_a])
    nombres = [p["nombre"] for p in get_plantillas(db)]
    assert nombres == ["B", "A"]
