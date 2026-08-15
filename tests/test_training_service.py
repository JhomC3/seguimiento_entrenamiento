import sqlite3
from datetime import date, timedelta

import pytest

from src.database import get_sets_by_fecha, init_db
from src.models import TrainingSetInput
from src.training_service import (
    calculate_cycle_week,
    day_from_date,
    fecha_display,
    fecha_to_db,
    parse_cycle_start,
    save_session,
    sets_from_form,
    validate_sets,
)

CYCLE = parse_cycle_start()


def _seed_catalog(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press')")
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_catalog(db_path)
    return db_path


def test_calculate_cycle_week():
    # Ciclo actual: inicia lunes 04/05/2026; semanas alineadas a lunes-domingo.
    assert calculate_cycle_week(date(2026, 5, 4), CYCLE) == 1  # lunes, inicio del ciclo
    assert calculate_cycle_week(date(2026, 5, 10), CYCLE) == 1  # domingo
    assert calculate_cycle_week(date(2026, 5, 11), CYCLE) == 2  # lunes siguiente
    assert calculate_cycle_week(date(2026, 5, 17), CYCLE) == 2  # domingo
    assert calculate_cycle_week(date(2026, 5, 18), CYCLE) == 3
    assert calculate_cycle_week(date(2026, 8, 7), CYCLE) == 14  # hoy
    assert calculate_cycle_week(date(2026, 1, 1), CYCLE) == 1  # antes del ciclo -> 1


def test_calculate_cycle_week_ancla_al_lunes_de_la_semana_calendario():
    # Si el ciclo iniciara a mitad de semana (miércoles 06/05/2026),
    # la semana 1 cubre la semana calendario lun-dom (04/05 al 10/05).
    start = date(2026, 5, 6)
    assert calculate_cycle_week(date(2026, 5, 4), start) == 1  # lunes previo al inicio
    assert calculate_cycle_week(date(2026, 5, 6), start) == 1  # inicio (miércoles)
    assert calculate_cycle_week(date(2026, 5, 10), start) == 1  # domingo
    assert calculate_cycle_week(date(2026, 5, 11), start) == 2  # lunes siguiente
    assert calculate_cycle_week(date(2026, 5, 12), start) == 2


def test_day_from_date():
    assert day_from_date(date(2026, 2, 10)) == "MARTES"
    assert day_from_date(date(2026, 2, 16)) == "LUNES"
    assert day_from_date(date(2026, 2, 22)) == "DOMINGO"


def test_save_session_basic(db):
    result = save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=2),
        ],
    )
    assert result.semana == 1
    assert result.dia == "MARTES"
    assert result.fecha == "2026-02-10"
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen FROM training_sets"
    ).fetchone()
    conn.close()
    assert row == (1, "MARTES", "2026-02-10", 1, "Press", 8.0, 80.0, 2.0, "manual")


def test_save_session_multiple_sets(db):
    save_session(
        db,
        "2026-05-13",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=2),
            TrainingSetInput(ejercicio="Press", kg=75, reps=10, rir=0),
        ],
    )
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT semana, set_orden, reps, rir FROM training_sets ORDER BY set_orden"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == (2, 1, 8.0, 2.0)
    assert rows[1] == (2, 2, 10.0, 0.0)


def test_insert_invalid_kg_rejected(db):
    with pytest.raises(ValueError):
        save_session(db, "2026-02-10", [TrainingSetInput(ejercicio="Press", kg=0, reps=8, rir=0)])


def test_insert_invalid_reps_rejected(db):
    with pytest.raises(ValueError):
        save_session(db, "2026-02-10", [TrainingSetInput(ejercicio="Press", kg=80, reps=-1, rir=0)])


def test_insert_unknown_exercise_rejected(db):
    with pytest.raises(ValueError):
        save_session(
            db, "2026-02-10", [TrainingSetInput(ejercicio="No Existe", kg=80, reps=8, rir=0)]
        )


def test_insert_negative_rir_accepted_hasta_minimo(db):
    save_session(db, "2026-02-10", [TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=-1)])
    rows = get_sets_by_fecha(db, "2026-02-10")
    assert rows[0]["rir"] == -1.0


def test_save_zero_rir_accepted(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=0),
        ],
    )
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT rir FROM training_sets").fetchone()
    conn.close()
    assert row == (0.0,)


def test_insert_empty_rir_rejected(db):
    with pytest.raises(ValueError):
        save_session(
            db,
            "2026-02-10",
            [
                TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=None),
            ],
        )


def test_insert_zero_kg_rejected(db):
    with pytest.raises(ValueError):
        save_session(
            db,
            "2026-02-10",
            [
                TrainingSetInput(ejercicio="Press", kg=0, reps=8, rir=0),
            ],
        )


def test_transaction_rolls_back_on_failure(db):
    with pytest.raises(ValueError):
        save_session(
            db,
            "2026-02-10",
            [
                TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
                TrainingSetInput(ejercicio="No Existe", kg=80, reps=8, rir=0),
            ],
        )
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0


def test_validate_sets_empty(db):
    with pytest.raises(ValueError):
        validate_sets(db, [])


def test_validate_sets_accepts_negative_rir_hasta_minimo(db):
    sets = validate_sets(
        db,
        [TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=-2)],
    )
    assert sets[0].rir == -2.0


def test_validate_sets_accepts_decimal_reps(db):
    sets = validate_sets(
        db,
        [TrainingSetInput(ejercicio="Press", kg=80, reps=4.5, rir=0)],
    )
    assert sets[0].reps == 4.5


def test_validate_sets_rejects_rir_below_minimo(db):
    with pytest.raises(ValueError):
        validate_sets(
            db,
            [TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=-6)],
        )


def test_sets_from_form_parses_negative_rir():
    sets = sets_from_form(["Press"], ["80"], ["5"], ["-1"])
    assert sets[0].rir == "-1"


def test_sets_from_form_parses_descanso():
    sets = sets_from_form(["Press"], ["80"], ["5"], ["0"], descansos=["90"])
    assert sets[0].descanso_seg == "90"


def test_save_session_persists_descanso(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=0, descanso_seg=90),
            TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=2),
        ],
    )
    rows = get_sets_by_fecha(db, "2026-02-10")
    assert rows[0]["descanso_seg"] == 90.0
    assert rows[1]["descanso_seg"] is None


def test_validate_sets_cleans_descanso(db):
    sets = validate_sets(
        db,
        [TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=0, descanso_seg="75")],
    )
    assert sets[0].descanso_seg == 75.0


def test_validate_sets_accepts_empty_descanso(db):
    sets = validate_sets(
        db,
        [TrainingSetInput(ejercicio="Press", kg=80, reps=5, rir=0, descanso_seg="")],
    )
    assert sets[0].descanso_seg is None



def test_get_sets_by_fecha(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
        ],
    )
    rows = get_sets_by_fecha(db, "2026-02-10")
    assert len(rows) == 1
    assert rows[0]["ejercicio"] == "Press"
    assert rows[0]["origen"] == "manual"


def test_fecha_to_db_devuelve_iso():
    assert fecha_to_db(date(2026, 8, 6)) == "2026-08-06"


def test_fecha_display():
    assert fecha_display("2026-08-06") == "6/8/26"


def test_save_session_replaces_rows(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
        ],
    )
    result = save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=90, reps=6, rir=2),
            TrainingSetInput(ejercicio="Press", kg=85, reps=8, rir=0),
        ],
    )
    assert result.semana == 1
    assert result.dia == "MARTES"
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT set_orden, ejercicio, kg, reps, rir, origen FROM training_sets ORDER BY set_orden"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == (1, "Press", 90.0, 6.0, 2.0, "manual")
    assert rows[1] == (2, "Press", 85.0, 8.0, 0.0, "manual")


def test_save_session_empty_deletes(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
        ],
    )
    save_session(db, "2026-02-10", [])
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0


def test_save_session_invalid_keeps_data(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
        ],
    )
    with pytest.raises(ValueError):
        save_session(
            db,
            "2026-02-10",
            [
                TrainingSetInput(ejercicio="No Existe", kg=80, reps=8, rir=0),
            ],
        )
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 1


def test_save_session_replaces_google_rows_by_fecha(db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
        "VALUES (1, 'MARTES', '2026-02-10', 1, 'Press', 8, 80, 1, 'google')"
    )
    conn.commit()
    conn.close()
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=95, reps=5, rir=2),
        ],
    )
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT kg, origen FROM training_sets").fetchall()
    conn.close()
    assert rows == [(95.0, "manual")]


def test_save_session_filters_empty_rows(db):
    save_session(
        db,
        "2026-02-10",
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
            TrainingSetInput(ejercicio="", kg="", reps="", rir=""),
            TrainingSetInput(ejercicio="", kg="", reps="", rir=""),
        ],
    )
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT set_orden, kg FROM training_sets").fetchall()
    conn.close()
    assert rows == [(1, 80.0)]


def test_save_session_allows_future_date(db):
    futuro = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    save_session(
        db,
        futuro,
        [
            TrainingSetInput(ejercicio="Press", kg=80, reps=8, rir=1),
        ],
    )
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 1
