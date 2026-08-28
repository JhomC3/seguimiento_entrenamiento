"""Failure-set signal: derived flag used for analysis (sets at/to failure)."""

from src.metrics_engine import RM_FACTOR, is_failure_set, rm_ajustado


def test_rm_ajustado_escalar():
    assert rm_ajustado(90, 7, 1.2) == 90 * (1 + 0.0333 * (7 + 1.2))


def test_factor_constante():
    assert RM_FACTOR == 0.0333


def test_editor_js_usa_misma_constante_rm():
    from pathlib import Path

    src = Path("static/js/editor.js").read_text()
    assert "0.0333" in src


def test_is_failure_set():
    assert not is_failure_set(5.0, 0.0)  # sin reserva, pero completada
    assert is_failure_set(4.5, None)  # rep parcial (reps decimal)
    assert is_failure_set(5.0, -1.0)  # forzada
    assert not is_failure_set(5.0, 2.0)  # con reserva
    assert not is_failure_set(5.0, None)  # sin datos de RIR


def test_rm_ajustado_con_rir_negativo_sigue_positivo():
    # RIR negativo (forzadas) nunca hace negativo el RM estimado.
    assert rm_ajustado(100, 10, -5) > 0
    # -0.5 equivale a media repetición fallida; -1, a ninguna parte adicional.
    assert rm_ajustado(100, 10, -0.5) > rm_ajustado(100, 10, -1)
    assert rm_ajustado(100, 10, -1) == rm_ajustado(100, 10, 0)


def test_pfr_timeline_cuenta_sets_fallo(tmp_path):
    import sqlite3

    from src.metrics_engine import calculate_pfr_timeline

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE ejercicios (id INTEGER PRIMARY KEY, grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE, categoria TEXT, origen TEXT NOT NULL DEFAULT 'google');
        CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER NOT NULL, dia TEXT NOT NULL,
            fecha TEXT, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, reps REAL, kg REAL,
            rir REAL, descanso_seg REAL, origen TEXT NOT NULL DEFAULT 'google');
        INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (1, 'LUNES', '2026-05-04', 1, 'Press', 8, 80, 2),
               (1, 'LUNES', '2026-05-04', 2, 'Press', 5, 80, 0),
               (1, 'LUNES', '2026-05-04', 3, 'Press', 4.5, 80, -1);
        """
    )
    conn.close()
    tl = calculate_pfr_timeline(db)
    day = tl[tl["fecha_dt"] == "2026-05-04"]
    assert int(day.iloc[0]["sets_fallo"]) == 1  # solo la serie parcial


def test_pfr_timeline_filtra_por_categoria(tmp_path):
    import sqlite3

    from src.metrics_engine import calculate_pfr_timeline

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE ejercicios (id INTEGER PRIMARY KEY, grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE, categoria TEXT, origen TEXT NOT NULL DEFAULT 'google');
        CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER NOT NULL, dia TEXT NOT NULL,
            fecha TEXT, set_orden INTEGER NOT NULL, ejercicio TEXT NOT NULL, reps REAL, kg REAL,
            rir REAL, descanso_seg REAL, origen TEXT NOT NULL DEFAULT 'google');
        INSERT INTO ejercicios (grupo_muscular, ejercicio, categoria)
        VALUES ('Pectoral', 'Press', 'Empuje'), ('Espalda', 'Remo', 'Tiron');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (1, 'LUNES', '2026-05-04', 1, 'Press', 8, 80, 2),
               (1, 'LUNES', '2026-05-04', 1, 'Remo', 8, 70, 2);
        """
    )
    conn.close()
    tl = calculate_pfr_timeline(db, "category", "Empuje")
    day = tl[tl["fecha_dt"] == "2026-05-04"]
    assert int(day.iloc[0]["sets_totales"]) == 1  # solo Press
    assert tl["sets_totales"].sum() == 1
