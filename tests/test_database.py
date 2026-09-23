import sqlite3

import pandas as pd

from src.database import (
    init_db,
    insert_plantilla,
    insert_plantilla_alimentacion,
    load_ejercicios,
    load_training_data,
)


def test_init_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t[0] for t in tables]
    assert "ejercicios" in table_names
    assert "training_sets" in table_names
    assert "plantillas" in table_names
    assert "plantilla_sets" in table_names
    conn.close()


def test_init_db_creates_new_columns(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    sets_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()]
    ej_cols = [r[1] for r in conn.execute("PRAGMA table_info(ejercicios)").fetchall()]
    conn.close()
    assert "origen" in sets_cols
    assert "categoria" in ej_cols
    assert "origen" in ej_cols


def test_init_db_preserves_existing_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) VALUES (1, 'LUNES', '2026-05-04', 1, 'Press', 6, 85, 1, 'manual')"
    )
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 1


def test_init_db_migrates_old_schema(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE
        );
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana INTEGER NOT NULL,
            dia TEXT NOT NULL,
            fecha TEXT,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            reps REAL,
            kg REAL,
            rir REAL
        );
        INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (1, 'LUNES', '2026-05-04', 1, 'Press', 6, 85, 1);
    """)
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    sets_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()]
    ej_cols = [r[1] for r in conn.execute("PRAGMA table_info(ejercicios)").fetchall()]
    set_origen = conn.execute("SELECT origen FROM training_sets").fetchone()[0]
    cat = conn.execute("SELECT categoria FROM ejercicios").fetchone()[0]
    conn.close()
    assert "origen" in sets_cols
    assert "categoria" in ej_cols
    assert set_origen == "google"
    assert cat == "EMPUJE"


def test_init_db_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert count == 0


def test_migrations_recorded_in_schema_migrations(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    versions = sorted(
        r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
    )
    conn.close()
    assert versions == [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]


def test_migrates_intermediate_state_without_orden(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE,
            categoria TEXT,
            origen TEXT NOT NULL DEFAULT 'google'
        );
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana INTEGER NOT NULL,
            dia TEXT NOT NULL,
            fecha TEXT,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            reps REAL,
            kg REAL,
            rir REAL,
            origen TEXT NOT NULL DEFAULT 'google'
        );
        CREATE TABLE plantillas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            clasificacion TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE plantilla_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plantilla_id INTEGER NOT NULL,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            FOREIGN KEY (plantilla_id) REFERENCES plantillas(id) ON DELETE CASCADE
        );
        INSERT INTO plantillas (nombre, clasificacion, created_at, updated_at)
        VALUES ('Mi Empuje', '', '2026-01-01', '2026-01-01');
        INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (1, 1, 'Press');
    """)
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(plantillas)").fetchall()]
    orden = conn.execute("SELECT orden FROM plantillas").fetchone()[0]
    conn.close()
    assert "orden" in cols
    assert orden == 0


def test_migrates_old_schema_keeps_rows_and_indexes(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE ejercicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_muscular TEXT NOT NULL,
            ejercicio TEXT NOT NULL UNIQUE
        );
        CREATE TABLE training_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana INTEGER NOT NULL,
            dia TEXT NOT NULL,
            fecha TEXT,
            set_orden INTEGER NOT NULL,
            ejercicio TEXT NOT NULL,
            reps REAL,
            kg REAL,
            rir REAL
        );
        INSERT INTO ejercicios (grupo_muscular, ejercicio) VALUES ('Pectoral', 'Press');
        INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir)
        VALUES (1, 'LUNES', '2026-05-04', 1, 'Press', 6, 85, 1);
    """)
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    indexes = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }
    n_rows = conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0]
    conn.close()
    assert {"idx_training_semana", "idx_training_ejercicio", "idx_plantilla_sets"} <= indexes
    assert n_rows == 1


def test_backup_only_when_pending_migrations(tmp_path):
    db_path = str(tmp_path / "test.db")
    from src.migrations.runner import run_migrations

    run_migrations(db_path)
    backups_dir = tmp_path / "backups"
    assert not backups_dir.exists()
    run_migrations(db_path)
    assert not backups_dir.exists()
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE schema_migrations")
    conn.commit()
    conn.close()
    run_migrations(db_path)
    assert backups_dir.exists()
    assert len(list(backups_dir.iterdir())) == 1


def test_backup_prune_mantiene_ultimos_30(tmp_path):
    from src.database import backup_db

    db = str(tmp_path / "g.db")
    init_db(db)
    (tmp_path / "backups").mkdir(exist_ok=True)
    for i in range(35):
        (tmp_path / "backups" / f"lifestyle-20260804-{100000 + i:06d}.db").touch()
    backup_db(db)
    backups = sorted(p.name for p in (tmp_path / "backups").glob("lifestyle-*.db"))
    assert len(backups) == 30


def test_v005_recomputa_semanas_desde_fecha(tmp_path):
    from src.db_connection import connect_db, read_connection
    from src.migrations import v005_recompute_semana

    db = str(tmp_path / "legacy.db")
    with connect_db(db) as conn:
        conn.execute(
            "CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER, dia TEXT, "
            "fecha TEXT, set_orden INTEGER, ejercicio TEXT, reps REAL, kg REAL, rir REAL)"
        )
        rows = [
            (25, "MIERCOLES", "29/7/26"),
            (26, "MARTES", "4/8/26"),
            (26, "JUEVES", "6/8/26"),
            (26, "VIERNES", "7/8/26"),
            (1, "LUNES", "4/5/26"),
            (13, "VIERNES", "1/8/26"),
            (7, "LUNES", None),
            (9, "MIERCOLES", "2026-08-07"),
        ]
        for semana, dia, fecha in rows:
            conn.execute(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
                "VALUES (?, ?, ?, 1, 'Press', 90, 7, 1)",
                (semana, dia, fecha),
            )
    with connect_db(db) as conn:
        v005_recompute_semana.migrate(conn)
    with read_connection(db) as conn:
        result = [r[1] for r in conn.execute("SELECT id, semana FROM training_sets ORDER BY id")]
    assert result == [13, 14, 14, 14, 1, 13, 7, 14]


def test_v005_recompute_idempotente(tmp_path):
    from src.db_connection import connect_db, read_connection
    from src.migrations import v005_recompute_semana

    db = str(tmp_path / "legacy.db")
    with connect_db(db) as conn:
        conn.execute(
            "CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER, dia TEXT, "
            "fecha TEXT, set_orden INTEGER, ejercicio TEXT, reps REAL, kg REAL, rir REAL)"
        )
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir) "
            "VALUES (26, 'VIERNES', '7/8/26', 1, 'Press', 90, 7, 1)"
        )
    with connect_db(db) as conn:
        v005_recompute_semana.migrate(conn)
        v005_recompute_semana.migrate(conn)
    with read_connection(db) as conn:
        assert conn.execute("SELECT semana FROM training_sets").fetchone()[0] == 14


def test_v007_creates_nutrition_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = [
        t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    assert "alimentos" in tables
    assert "diario_alimentacion" in tables
    assert "ejercicios" in tables
    assert "training_sets" in tables
    assert "plantillas" in tables
    assert "plantilla_sets" in tables

    alim_cols = [r[1] for r in conn.execute("PRAGMA table_info(alimentos)").fetchall()]
    assert alim_cols == [
        "id",
        "nombre",
        "categoria",
        "kcal",
        "carbohidratos",
        "fibra",
        "proteina",
        "grasa",
        "hierro",
        "calcio",
        "vitamina_c",
        "vitamina_a",
        "origen",
        "magnesio",
        "zinc",
        "potasio",
        "sodio",
        "vitamina_d",
        "vitamina_e",
        "vitamina_k",
        "folato",
        "vitamina_b12",
        "vitamina_b6",
        "yodo",
        "selenio",
    ]
    diario_cols = [r[1] for r in conn.execute("PRAGMA table_info(diario_alimentacion)").fetchall()]
    assert diario_cols == [
        "id",
        "fecha",
        "orden",
        "alimento",
        "cantidad_g",
        "kcal",
        "carbohidratos",
        "fibra",
        "proteina",
        "grasa",
        "hierro",
        "calcio",
        "vitamina_c",
        "vitamina_a",
        "origen",
        "magnesio",
        "zinc",
        "potasio",
        "sodio",
        "vitamina_d",
        "vitamina_e",
        "vitamina_k",
        "folato",
        "vitamina_b12",
        "vitamina_b6",
        "yodo",
        "selenio",
    ]
    indexes = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    ]
    assert "idx_diario_alimentacion_fecha_orden" in indexes
    conn.close()


def test_v007_nutrition_origin_defaults_to_google(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO alimentos (nombre, kcal, carbohidratos, fibra, proteina, grasa, "
        "hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('Avena', 389, 68, 10, 17, 6.9, 4.2, 54, 0, 0)"
    )
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
        "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2025-04-24', 1, 'Avena', 120, 467, 82, 12, 20, 8, 5, 65, 0, 0)"
    )
    assert conn.execute("SELECT origen FROM alimentos").fetchone()[0] == "google"
    assert conn.execute("SELECT origen FROM diario_alimentacion").fetchone()[0] == "google"
    conn.close()


def test_v009_creates_meal_templates(tmp_path):
    from src.db_connection import connect_db

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = connect_db(db_path)
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "plantillas_alimentacion" in tables
    assert "plantilla_alimentos" in tables
    cols = [r[1] for r in conn.execute("PRAGMA table_info(plantillas_alimentacion)").fetchall()]
    assert "nombre" in cols and "orden" in cols
    alim_cols = [r[1] for r in conn.execute("PRAGMA table_info(plantilla_alimentos)").fetchall()]
    assert "plantilla_id" in alim_cols and "cantidad_g" in alim_cols
    # FK CASCADE (connect_db activa foreign_keys)
    conn.execute(
        "INSERT INTO plantillas_alimentacion (nombre, created_at, updated_at, orden) "
        "VALUES ('Desayuno', '', '', 1)"
    )
    pid = conn.execute("SELECT id FROM plantillas_alimentacion").fetchone()[0]
    conn.execute(
        "INSERT INTO plantilla_alimentos (plantilla_id, orden, alimento, cantidad_g) "
        "VALUES (?, 1, 'Avena', 120)",
        (pid,),
    )
    conn.commit()
    conn.execute("DELETE FROM plantillas_alimentacion WHERE id = ?", (pid,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM plantilla_alimentos").fetchone()[0] == 0
    max_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    conn.close()
    assert max_version == 21


def test_v021_is_latest_schema_version(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    max_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    conn.close()
    assert max_version == 21


def test_v007_migration_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 7").fetchone()[0]
    conn.close()
    assert count == 1


def _insert_alimento(conn, nombre="Avena", **overrides):
    base = {
        "nombre": nombre,
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
    }
    base.update(overrides)
    cols = ",".join(base)
    conn.execute(
        f"INSERT INTO alimentos ({cols}) VALUES ({','.join('?' * len(base))})",
        list(base.values()),
    )


def _insert_diario(conn, fecha, orden, alimento="Avena", **overrides):
    base = {
        "fecha": fecha,
        "orden": orden,
        "alimento": alimento,
        "cantidad_g": 120.0,
        "kcal": 467.0,
        "carbohidratos": 82.0,
        "fibra": 12.0,
        "proteina": 20.0,
        "grasa": 8.0,
        "hierro": 5.0,
        "calcio": 65.0,
        "vitamina_c": 0.0,
        "vitamina_a": 0.0,
    }
    base.update(overrides)
    cols = ",".join(base)
    conn.execute(
        f"INSERT INTO diario_alimentacion ({cols}) VALUES ({','.join('?' * len(base))})",
        list(base.values()),
    )


def test_get_alimentos_catalog_sorted(tmp_path):
    from src.database import get_alimentos_catalog

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_alimento(conn, "Zanahoria", categoria="Vegetal")
    _insert_alimento(conn, "Avena")
    conn.commit()
    conn.close()
    catalog = get_alimentos_catalog(db_path)
    assert [a["nombre"] for a in catalog] == ["Avena", "Zanahoria"]
    assert catalog[0]["kcal"] == 389.0
    assert catalog[0]["fibra"] == 10.0
    assert "origen" not in catalog[0]


def test_find_alimento_case_insensitive(tmp_path):
    from src.database import find_alimento

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_alimento(conn, "Avena")
    conn.commit()
    conn.close()
    found = find_alimento(db_path, "avena")
    assert found is not None
    assert found["nombre"] == "Avena"
    assert found["grasa"] == 6.9
    assert find_alimento(db_path, "No Existe") is None


def test_replace_diario_by_fecha_only_touches_date(tmp_path):
    from src.database import get_diario_by_fecha, replace_diario_by_fecha

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_diario(conn, "2025-04-24", 1)
    _insert_diario(conn, "2025-04-25", 1, alimento="Huevo", kcal=143.0)
    conn.commit()
    conn.close()

    replace_diario_by_fecha(
        db_path,
        "2025-04-24",
        [
            {
                "alimento": "Huevo",
                "cantidad_g": 100.0,
                "kcal": 143.0,
                "carbohidratos": 1.0,
                "fibra": 0.0,
                "proteina": 13.0,
                "grasa": 10.0,
                "hierro": 2.0,
                "calcio": 50.0,
                "vitamina_c": 0.0,
                "vitamina_a": 300.0,
            },
            {
                "alimento": "Banano",
                "cantidad_g": 120.0,
                "kcal": 107.0,
                "carbohidratos": 27.0,
                "fibra": 3.0,
                "proteina": 1.0,
                "grasa": 0.0,
                "hierro": 0.0,
                "calcio": 6.0,
                "vitamina_c": 10.0,
                "vitamina_a": 4.0,
            },
        ],
    )
    day = get_diario_by_fecha(db_path, "2025-04-24")
    assert [r["alimento"] for r in day] == ["Huevo", "Banano"]
    assert [r["orden"] for r in day] == [1, 2]
    other = get_diario_by_fecha(db_path, "2025-04-25")
    assert other[0]["alimento"] == "Huevo"
    assert other[0]["origen"] == "google"


def test_get_diario_dates_sorted_iso(tmp_path):
    from src.database import get_diario_dates

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_diario(conn, "2025-04-24", 1)
    _insert_diario(conn, "2025-04-25", 1, alimento="Huevo")
    _insert_diario(conn, "2025-04-21", 1, alimento="Banano")
    conn.commit()
    conn.close()
    assert get_diario_dates(db_path) == ["2025-04-21", "2025-04-24", "2025-04-25"]


def test_delete_diario_by_fecha(tmp_path):
    from src.database import delete_diario_by_fecha, get_diario_by_fecha

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_diario(conn, "2025-04-24", 1)
    _insert_diario(conn, "2025-04-25", 1, alimento="Huevo")
    conn.commit()
    conn.close()
    assert delete_diario_by_fecha(db_path, "2025-04-24") == 1
    assert get_diario_by_fecha(db_path, "2025-04-24") == []
    assert len(get_diario_by_fecha(db_path, "2025-04-25")) == 1


def test_restore_diario_rows_preserves_orden_and_origen(tmp_path):
    from src.database import get_diario_by_fecha, replace_diario_by_fecha, restore_diario_rows

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    _insert_diario(conn, "2025-04-24", 1)
    _insert_diario(conn, "2025-04-24", 2, alimento="Huevo", kcal=143.0, origen="google")
    conn.commit()
    conn.close()
    snapshot = get_diario_by_fecha(db_path, "2025-04-24")
    replace_diario_by_fecha(
        db_path,
        "2025-04-24",
        [
            {
                "alimento": "Banano",
                "cantidad_g": 90.0,
                "kcal": 47.0,
                "carbohidratos": 12.0,
                "fibra": 0.0,
                "proteina": 0.0,
                "grasa": 2.0,
                "hierro": 0.0,
                "calcio": 5.0,
                "vitamina_c": 4.0,
                "vitamina_a": 3.0,
            },
        ],
    )
    restore_diario_rows(db_path, "2025-04-24", snapshot)
    restored = get_diario_by_fecha(db_path, "2025-04-24")
    assert [(r["alimento"], r["orden"], r["origen"]) for r in restored] == [
        ("Avena", 1, "google"),
        ("Huevo", 2, "google"),
    ]
    assert restored[1]["kcal"] == 143.0


def test_v006_convierte_fechas_a_iso(tmp_path):
    from src.db_connection import connect_db, read_connection
    from src.migrations import v006_iso_dates

    db = str(tmp_path / "legacy.db")
    with connect_db(db) as conn:
        conn.execute(
            "CREATE TABLE training_sets (id INTEGER PRIMARY KEY, semana INTEGER, dia TEXT, fecha TEXT, set_orden INTEGER, ejercicio TEXT, reps REAL, kg REAL, rir REAL)"
        )
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (1, 'LUNES', '6/8/26', 1, 'Press', 90, 7, 1.2)"
        )
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (2, 'MARTES', '10/02/2026', 1, 'Press', 90, 7, 1.2)"
        )
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, kg, reps, rir) VALUES (3, 'MIERCOLES', 'basura', 1, 'Press', 90, 7, 1.2)"
        )
    v006_iso_dates.migrate(connect_db(db))
    with read_connection(db) as conn:
        fechas = [r[0] for r in conn.execute("SELECT fecha FROM training_sets ORDER BY id")]
    assert fechas == ["2026-08-06", "2026-02-10", None]


def test_v008_creates_parametros_diarios_and_nullable_qty(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    diario_cols = [r[1] for r in conn.execute("PRAGMA table_info(diario_alimentacion)").fetchall()]
    not_null = {
        r[1] for r in conn.execute("PRAGMA table_info(diario_alimentacion)").fetchall() if r[3] == 1
    }
    assert "cantidad_g" in diario_cols
    assert "cantidad_g" not in not_null
    params = [r[1] for r in conn.execute("PRAGMA table_info(parametros_diarios)").fetchall()]
    for col in (
        "peso_kg",
        "factor_proteina",
        "factor_grasa",
        "kcal_objetivo",
        "fibra_objetivo",
        "hierro_objetivo",
        "calcio_objetivo",
        "vitamina_c_objetivo",
        "vitamina_a_objetivo",
    ):
        assert col in params
    max_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    conn.close()
    assert max_version == 21


def test_v008_preserves_diario_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
        "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2025-04-24', 1, 'Avena', 120, 467, 82, 12, 20, 8, 5, 65, 0, 0)"
    )
    conn.commit()
    conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT fecha, orden, alimento, cantidad_g, kcal FROM diario_alimentacion"
    ).fetchone()
    conn.close()
    assert row == ("2025-04-24", 1, "Avena", 120.0, 467.0)


def test_v008_params_defaults(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO parametros_diarios (fecha) VALUES ('2025-04-24')")
    row = conn.execute(
        "SELECT peso_kg, factor_proteina, factor_grasa, kcal_objetivo "
        "FROM parametros_diarios WHERE fecha = '2025-04-24'"
    ).fetchone()
    conn.close()
    assert row == (70.0, 1.5, 1.1, 2300.0)


def test_get_save_parametros_diarios(tmp_path):
    from src.database import get_parametros_diarios, save_parametros_diarios

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    assert get_parametros_diarios(db_path, "2025-04-24") is None
    save_parametros_diarios(
        db_path,
        "2025-04-24",
        {
            "peso_kg": 69.0,
            "factor_proteina": 1.4,
            "factor_grasa": 1.1,
            "kcal_objetivo": 2750.0,
            "fibra_objetivo": 38.0,
            "hierro_objetivo": 8.0,
            "calcio_objetivo": 1000.0,
            "vitamina_c_objetivo": 90.0,
            "vitamina_a_objetivo": 900.0,
        },
    )
    params = get_parametros_diarios(db_path, "2025-04-24")
    assert params["peso_kg"] == 69.0
    assert params["factor_proteina"] == 1.4
    assert params["kcal_objetivo"] == 2750.0
    # UPSERT: guardar de nuevo actualiza, no duplica
    save_parametros_diarios(db_path, "2025-04-24", {"peso_kg": 70.0})
    params = get_parametros_diarios(db_path, "2025-04-24")
    assert params["peso_kg"] == 70.0
    assert params["factor_proteina"] == 1.4


def test_v018_backfill_micro_objetivos_y_curaduria(tmp_path):
    from src.migrations import v018_nutrition_micro_targets

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO parametros_diarios (fecha) VALUES ('2025-04-24')")
    conn.execute(
        "INSERT INTO alimentos (nombre, categoria, kcal, carbohidratos, fibra, "
        "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, origen) VALUES "
        "('Arepa', 'Procesado', 6900, 1440, 150, 280, 50, 9, 1530, 0, 1710, 'google'),"
        "('Huevo', 'Animal', 143, 0.7, 0, 12.6, 9.6, 1.7, 50, 0, 0, 'google')"
    )
    conn.execute(
        "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
        "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a) "
        "VALUES ('2025-04-24', 1, 'Bocadillo de guayaba (ICBF)', 50, 0, 0, 0, 0, 0, 0, 0, 0, 0),"
        "('2025-04-24', 2, 'Yuca cocinada', 100, 0, 0, 0, 0, 0, 0, 0, 0, 0)"
    )
    conn.commit()
    v018_nutrition_micro_targets.migrate(conn)
    conn.commit()
    params = conn.execute(
        "SELECT fibra_objetivo, hierro_objetivo, calcio_objetivo, "
        "vitamina_c_objetivo, vitamina_a_objetivo "
        "FROM parametros_diarios WHERE fecha = '2025-04-24'"
    ).fetchone()
    assert params == (38.0, 8.0, 1000.0, 90.0, 900.0)
    arepa = conn.execute(
        "SELECT kcal, carbohidratos, vitamina_a, origen FROM alimentos WHERE nombre = 'Arepa'"
    ).fetchone()
    assert arepa == (69.0, 14.4, 17.1, "manual")
    huevo = conn.execute(
        "SELECT vitamina_a, origen FROM alimentos WHERE nombre = 'Huevo'"
    ).fetchone()
    assert huevo == (160.0, "manual")
    huerfanos = {
        r[0]
        for r in conn.execute(
            "SELECT nombre FROM alimentos WHERE nombre IN "
            "('Bocadillo de guayaba (ICBF)', 'Yuca cocinada')"
        ).fetchall()
    }
    assert huerfanos == {"Bocadillo de guayaba (ICBF)", "Yuca cocinada"}
    # Idempotente: segunda pasada no cambia nada.
    v018_nutrition_micro_targets.migrate(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM alimentos WHERE nombre = 'Arepa'").fetchone()[0] == 1
    conn.close()


def test_v018_respeta_objetivos_no_cero(tmp_path):
    from src.migrations import v018_nutrition_micro_targets

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO parametros_diarios (fecha, fibra_objetivo) VALUES ('2025-04-24', 25.0)"
    )
    conn.commit()
    v018_nutrition_micro_targets.migrate(conn)
    conn.commit()
    row = conn.execute(
        "SELECT fibra_objetivo, hierro_objetivo FROM parametros_diarios WHERE fecha = '2025-04-24'"
    ).fetchone()
    conn.close()
    assert row == (25.0, 8.0)


def test_v020_rellena_dri_en_cero_y_respeta_no_cero(tmp_path):
    from src.migrations import v020_dri_ceros

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO parametros_diarios (fecha) VALUES ('2025-04-24')")
    conn.execute(
        "INSERT INTO parametros_diarios (fecha, fibra_objetivo, potasio_objetivo) "
        "VALUES ('2025-04-25', 25.0, 0.0)"
    )
    conn.commit()
    v020_dri_ceros.migrate(conn)
    conn.commit()
    cols = (
        "fibra_objetivo, hierro_objetivo, calcio_objetivo, vitamina_c_objetivo, "
        "vitamina_a_objetivo, magnesio_objetivo, zinc_objetivo, potasio_objetivo, "
        "sodio_objetivo, vitamina_d_objetivo, vitamina_e_objetivo, vitamina_k_objetivo, "
        "folato_objetivo, vitamina_b12_objetivo, vitamina_b6_objetivo, yodo_objetivo, "
        "selenio_objetivo"
    )
    row = conn.execute(
        f"SELECT {cols} FROM parametros_diarios WHERE fecha = '2025-04-24'"
    ).fetchone()
    assert row == (
        38.0,
        8.0,
        1000.0,
        90.0,
        900.0,
        420.0,
        11.0,
        3400.0,
        1500.0,
        15.0,
        15.0,
        120.0,
        400.0,
        2.4,
        1.3,
        150.0,
        55.0,
    )
    custom = conn.execute(
        "SELECT fibra_objetivo, potasio_objetivo FROM parametros_diarios WHERE fecha = '2025-04-25'"
    ).fetchone()
    assert custom == (25.0, 3400.0)
    # Idempotente: segunda pasada no cambia nada.
    v020_dri_ceros.migrate(conn)
    conn.commit()
    assert (
        conn.execute("SELECT COUNT(*) FROM parametros_diarios WHERE fibra_objetivo = 0").fetchone()[
            0
        ]
        == 0
    )
    conn.close()


def test_replace_diario_accepts_null_cantidad(tmp_path):
    from src.database import get_diario_by_fecha, replace_diario_by_fecha

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    replace_diario_by_fecha(
        db_path,
        "2025-04-24",
        [
            {
                "alimento": "Nueces",
                "cantidad_g": None,
                "kcal": 0.0,
                "carbohidratos": 0.0,
                "fibra": 0.0,
                "proteina": 0.0,
                "grasa": 0.0,
                "hierro": 0.0,
                "calcio": 0.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
                "origen": "google",
            }
        ],
    )
    rows = get_diario_by_fecha(db_path, "2025-04-24")
    assert rows[0]["alimento"] == "Nueces"
    assert rows[0]["cantidad_g"] is None


def test_plantillas_alimentacion_crud(tmp_path):
    from src.database import (
        delete_plantilla_alimentacion,
        get_plantillas_alimentacion,
        insert_plantilla_alimentacion,
        reorder_plantillas_alimentacion,
        update_plantilla_alimentacion_rows,
    )

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    pid1 = insert_plantilla_alimentacion(
        db_path, "Desayuno", [{"alimento": "Avena", "cantidad_g": 120.0}]
    )
    pid2 = insert_plantilla_alimentacion(
        db_path, "Cena", [{"alimento": "Lentejas", "cantidad_g": 125.0}]
    )
    plantillas = get_plantillas_alimentacion(db_path)
    assert [p["nombre"] for p in plantillas] == ["Desayuno", "Cena"]  # por orden de inserción
    assert plantillas[0]["alimentos"] == [{"alimento": "Avena", "cantidad_g": 120.0}]

    update_plantilla_alimentacion_rows(db_path, pid1, [{"alimento": "Avena", "cantidad_g": 150.0}])
    assert get_plantillas_alimentacion(db_path)[0]["alimentos"][0]["cantidad_g"] == 150.0

    reorder_plantillas_alimentacion(db_path, [pid1, pid2])
    assert [p["nombre"] for p in get_plantillas_alimentacion(db_path)] == ["Desayuno", "Cena"]

    delete_plantilla_alimentacion(db_path, pid2)
    assert [p["nombre"] for p in get_plantillas_alimentacion(db_path)] == ["Desayuno"]


def test_load_ejercicios(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    df = pd.DataFrame(
        {
            "grupo_muscular": ["Pectoral", "Triceps"],
            "ejercicio": ["Press Convergente", "Katana"],
        }
    )
    load_ejercicios(db_path, df)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT grupo_muscular, ejercicio FROM ejercicios").fetchall()
    assert len(rows) == 2
    assert rows[0] == ("Pectoral", "Press Convergente")
    assert rows[1] == ("Triceps", "Katana")
    conn.close()


def test_load_training_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    df = pd.DataFrame(
        {
            "semana": [1, 1],
            "dia": ["LUNES", "LUNES"],
            "fecha": ["2026-05-04", "2026-05-04"],
            "set_orden": [1, 2],
            "ejercicio": ["Press Convergente", "Press Convergente"],
            "reps": [6.0, 6.0],
            "kg": [85.0, 85.0],
            "rir": [1.0, 0.5],
        }
    )
    load_training_data(db_path, df)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT semana, dia, reps, kg, rir FROM training_sets").fetchall()
    origens = conn.execute("SELECT DISTINCT origen FROM training_sets").fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, "LUNES", 6.0, 85.0, 1.0)
    assert origens == [("google",)]
    conn.close()


def test_v010_health_records_schema(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(health_records)").fetchall()}
    assert {
        "hc_id",
        "record_type",
        "start_epoch_ms",
        "end_epoch_ms",
        "last_modified_epoch_ms",
        "data_origin_package",
        "payload_schema_version",
        "value_json",
        "device_id",
        "received_at",
        "updated_at",
        "deleted_at",
    } <= cols
    max_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert max_version == 21
    pk_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(health_records)").fetchall() if r[5] == 1
    }
    assert pk_cols == {"hc_id"}
    index_cols = {
        (r[2], r[1])
        for r in conn.execute("PRAGMA index_info(idx_health_records_type_start)").fetchall()
    }
    assert ("record_type", 1) in index_cols
    assert ("start_epoch_ms", 2) in index_cols
    conn.close()


def test_v011_descanso_seg_column(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(training_sets)").fetchall()]
    assert "descanso_seg" in cols
    conn.close()


def test_v012_cardio_annotations_schema(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = {
        t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "cardio_annotations" in tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cardio_annotations)").fetchall()}
    assert {
        "id",
        "hc_id",
        "velocidad_kmh",
        "inclinacion_pct",
        "notas",
        "created_at",
        "updated_at",
    } <= cols
    fk = conn.execute("PRAGMA foreign_key_list(cardio_annotations)").fetchall()
    assert any(f[2] == "health_records" and f[3] == "hc_id" for f in fk)
    conn.close()


def test_save_parametros_preserva_rowid(tmp_path):
    from src.database import save_parametros_diarios
    from src.db_connection import read_connection

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    save_parametros_diarios(db_path, "2026-08-14", {"peso_kg": 80.0})
    with read_connection(db_path) as conn:
        rowid_1 = conn.execute(
            "SELECT rowid FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
    save_parametros_diarios(db_path, "2026-08-14", {"kcal_objetivo": 2400.0})
    with read_connection(db_path) as conn:
        rowid_2 = conn.execute(
            "SELECT rowid FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
        peso = conn.execute(
            "SELECT peso_kg FROM parametros_diarios WHERE fecha = ?", ("2026-08-14",)
        ).fetchone()[0]
    assert rowid_1 == rowid_2
    assert peso == 80.0


def test_get_plantillas_una_sola_consulta(tmp_path, monkeypatch):
    """Sin N+1: 1 query de plantillas + 1 de sets (≤2 ejecuciones)."""
    import src.database as dbmod

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_plantilla(db_path, "A", "EMPUJE", ["Press", "Press Militar"])
    insert_plantilla(db_path, "B", "JALON", ["Remo"])

    executions = []

    class CountingConn:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def execute(self, *args, **kwargs):
            executions.append(args[0] if args else "")
            return self._inner.execute(*args, **kwargs)

    class CountingCM:
        def __init__(self, cm):
            self._cm = cm

        def __enter__(self):
            return CountingConn(self._cm.__enter__())

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    original = dbmod.read_connection
    monkeypatch.setattr(
        dbmod,
        "read_connection",
        lambda path: CountingCM(original(path)),
    )
    result = dbmod.get_plantillas(db_path)
    assert len(result) == 2
    assert [p["nombre"] for p in result] == ["A", "B"]
    assert executions and len(executions) <= 2, executions


def test_get_plantillas_alimentacion_una_sola_consulta(tmp_path, monkeypatch):
    """Sin N+1: 1 query de plantillas + 1 de alimentos (≤2 ejecuciones)."""
    import src.database as dbmod

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_plantilla_alimentacion(db_path, "Comida A", [{"alimento": "Avena", "cantidad_g": 100}])
    insert_plantilla_alimentacion(db_path, "Comida B", [{"alimento": "Pollo", "cantidad_g": 150}])

    executions = []

    class CountingConn:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def execute(self, *args, **kwargs):
            executions.append(args[0] if args else "")
            return self._inner.execute(*args, **kwargs)

    class CountingCM:
        def __init__(self, cm):
            self._cm = cm

        def __enter__(self):
            return CountingConn(self._cm.__enter__())

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    original = dbmod.read_connection
    monkeypatch.setattr(
        dbmod,
        "read_connection",
        lambda path: CountingCM(original(path)),
    )
    result = dbmod.get_plantillas_alimentacion(db_path)
    assert len(result) == 2
    assert executions and len(executions) <= 2, executions


def test_restore_entrenos_resecuencia_ids(tmp_path):
    from src.database import delete_plantilla, restore_entrenos, snapshot_entrenos

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_plantilla(db_path, "A", "EMPUJE", ["Press"])
    snapshot = snapshot_entrenos(db_path)
    delete_plantilla(db_path, pid)
    restore_entrenos(db_path, snapshot)
    pid2 = insert_plantilla(db_path, "B", "JALON", ["Remo"])
    assert pid2 > pid


# ---------------------------------------------------------------------------
# Splits de entrenamiento
# ---------------------------------------------------------------------------


def test_insert_get_split_conserva_orden_por_dia(tmp_path):
    from src.database import get_split, insert_split

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(
        db_path,
        "Push Pull Legs",
        [
            ("LUNES", "ejercicio", "Press", "Pectoral"),
            ("LUNES", "ejercicio", "Press", "Pectoral"),
            ("LUNES", "hiit", "HIIT", "HIIT"),
            ("MARTES", "ejercicio", "Curl", "Biceps"),
        ],
    )
    split = get_split(db_path, pid)
    assert split["nombre"] == "Push Pull Legs"
    dias = [i["dia"] for i in split["items"]]
    assert dias == ["LUNES", "LUNES", "LUNES", "MARTES"]
    lun_ord = [i["orden"] for i in split["items"] if i["dia"] == "LUNES"]
    assert lun_ord == [1, 2, 3]
    assert split["items"][2]["item_type"] == "hiit"


def test_update_split_reemplaza_items_y_renumera(tmp_path):
    from src.database import get_split, insert_split, update_split

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(db_path, "A", [("LUNES", "ejercicio", "Press", "Pectoral")])
    update_split(
        db_path,
        pid,
        "A v2",
        [("VIERNES", "ejercicio", "Curl", "Biceps"), ("VIERNES", "hiit", "HIIT", "HIIT")],
    )
    split = get_split(db_path, pid)
    assert split["nombre"] == "A v2"
    assert len(split["items"]) == 2
    assert [i["orden"] for i in split["items"]] == [1, 2]


def test_delete_split_borra_items_en_cascada(tmp_path):
    from src.database import delete_split, get_split, insert_split

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(db_path, "A", [("LUNES", "ejercicio", "Press", "Pectoral")])
    assert get_split(db_path, pid) is not None
    delete_split(db_path, pid)
    assert get_split(db_path, pid) is None
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM training_split_items WHERE split_id = ?", (pid,)
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_find_split_by_nombre_case_insensitive(tmp_path):
    from src.database import find_split_by_nombre, insert_split

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(db_path, "Push Pull Legs", [])
    assert find_split_by_nombre(db_path, "push pull legs") == pid
    assert find_split_by_nombre(db_path, "PUSH PULL LEGS") == pid
    assert find_split_by_nombre(db_path, "otro") is None


def test_get_splits_summary_conteos(tmp_path):
    from src.database import get_splits_summary, insert_split

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid_a = insert_split(
        db_path,
        "A",
        [
            ("LUNES", "ejercicio", "Press", "Pectoral"),
            ("LUNES", "ejercicio", "Press", "Pectoral"),
            ("MARTES", "hiit", "HIIT", "HIIT"),
        ],
    )
    insert_split(db_path, "B", [("LUNES", "ejercicio", "Curl", "Biceps")])
    summary = get_splits_summary(db_path)
    by_id = {s["id"]: s for s in summary}
    a = by_id[pid_a]
    assert a["series"] == 3
    assert a["active_days"] == 2
    assert set(a["groups"]) == {"Pectoral", "HIIT"}


def test_get_split_catalog_con_grupo(tmp_path):
    from src.database import get_split_catalog, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "Curl", "Biceps", "TIRON")
    catalog = get_split_catalog(db_path)
    by_name = {c["ejercicio"]: c for c in catalog}
    assert by_name["Press"]["grupo_muscular"] == "Pectoral"
    assert by_name["Curl"]["categoria"] == "TIRON"


def test_snapshot_restore_splits_idempotente(tmp_path):
    from src.database import (
        delete_split,
        get_split,
        insert_split,
        restore_splits,
        snapshot_splits,
    )

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(
        db_path,
        "A",
        [("LUNES", "ejercicio", "Press", "Pectoral"), ("MARTES", "hiit", "HIIT", "HIIT")],
    )
    snapshot = snapshot_splits(db_path)
    delete_split(db_path, pid)
    restore_splits(db_path, snapshot)
    restored = get_split(db_path, pid)
    assert restored is not None
    assert len(restored["items"]) == 2
    assert restored["items"][1]["ejercicio"] == "HIIT"


def test_restore_splits_resecuencia_ids(tmp_path):
    from src.database import (
        delete_split,
        insert_split,
        restore_splits,
        snapshot_splits,
    )

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    pid = insert_split(db_path, "A", [])
    snapshot = snapshot_splits(db_path)
    delete_split(db_path, pid)
    restore_splits(db_path, snapshot)
    pid2 = insert_split(db_path, "B", [])
    assert pid2 > pid


# ---------------------------------------------------------------------------
# get_dashboard_catalog tests
# ---------------------------------------------------------------------------


def test_dashboard_catalog_empty_db(tmp_path):
    from src.database import get_dashboard_catalog, init_db

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    assert get_dashboard_catalog(db_path) == []


def test_dashboard_catalog_missing_file(tmp_path):
    from src.database import get_dashboard_catalog

    assert get_dashboard_catalog(str(tmp_path / "nonexistent.db")) == []


def test_dashboard_catalog_single_group(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "Press Mancuernas", "Pectoral", "EMPUJE")
    catalog = get_dashboard_catalog(db_path)
    assert len(catalog) == 1
    assert catalog[0]["name"] == "Pectoral"
    exercises = catalog[0]["exercises"]
    assert len(exercises) == 2
    assert [e["name"] for e in exercises] == ["Press", "Press Mancuernas"]
    assert all(e["category"] == "EMPUJE" for e in exercises)


def test_dashboard_catalog_multiple_groups_deterministic_order(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Curl", "Biceps", "TIRON")
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "Sentadilla", "Cuadriceps", "PIERNA")
    catalog = get_dashboard_catalog(db_path)
    group_names = [g["name"] for g in catalog]
    # MUSCLE_CATEGORIES order: EMPUJE(Pectoral), TIRON(Biceps), PIERNA(Cuadriceps)
    assert group_names == ["Pectoral", "Biceps", "Cuadriceps"]


def test_dashboard_catalog_group_not_in_category_comes_last(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Curl", "Biceps", "TIRON")
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "Jump", "CardioVirtual", "CARDIO")
    catalog = get_dashboard_catalog(db_path)
    group_names = [g["name"] for g in catalog]
    assert group_names == ["Pectoral", "Biceps", "CardioVirtual"]


def test_dashboard_catalog_no_duplicate_exercises(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    # INSERT OR IGNORE: duplicate silently ignored
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    catalog = get_dashboard_catalog(db_path)
    assert len(catalog) == 1
    assert len(catalog[0]["exercises"]) == 1


def test_dashboard_catalog_empty_group_not_shown(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    # Insert exercise then check: no group without exercises appears
    insert_exercise(db_path, "Press", "Pectoral", "EMPUJE")
    catalog = get_dashboard_catalog(db_path)
    for group in catalog:
        assert len(group["exercises"]) > 0, f"Grupo {group['name']} no debería estar vacío"


def test_dashboard_catalog_groups_exercises_alphabetical(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Z Press", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "A Curl", "Pectoral", "EMPUJE")
    insert_exercise(db_path, "M Fly", "Pectoral", "EMPUJE")
    catalog = get_dashboard_catalog(db_path)
    exercises = catalog[0]["exercises"]
    assert [e["name"] for e in exercises] == ["A Curl", "M Fly", "Z Press"]


def test_dashboard_catalog_category_empty_string(tmp_path):
    from src.database import get_dashboard_catalog, init_db, insert_exercise

    db_path = str(tmp_path / "db.sqlite")
    init_db(db_path)
    insert_exercise(db_path, "Press", "Pectoral", "")
    catalog = get_dashboard_catalog(db_path)
    assert catalog[0]["exercises"][0]["category"] == ""


def test_get_daily_data_dates_union_entrenamiento_y_alimentacion(tmp_path):
    from src.database import (
        get_daily_data_dates,
        insert_exercise,
        replace_diario_by_fecha,
    )
    from src.training_service import save_session

    db = str(tmp_path / "gym.db")
    init_db(db)
    insert_exercise(db, "Press", "Pectoral", "EMPUJE")
    save_session(db, "2026-08-10", [{"ejercicio": "Press", "kg": 80, "reps": 8, "rir": 1}])
    replace_diario_by_fecha(
        db,
        "2026-08-11",
        [
            {
                "alimento": "Avena",
                "cantidad_g": 100.0,
                "kcal": 389.0,
                "carbohidratos": 68.0,
                "fibra": 10.0,
                "proteina": 17.0,
                "grasa": 6.9,
                "hierro": 4.2,
                "calcio": 54.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
            }
        ],
    )
    save_session(
        db,
        "2026-08-12",
        [{"ejercicio": "Press", "kg": 82, "reps": 8, "rir": 1}],
    )
    replace_diario_by_fecha(
        db,
        "2026-08-12",
        [
            {
                "alimento": "Avena",
                "cantidad_g": 80.0,
                "kcal": 311.0,
                "carbohidratos": 54.0,
                "fibra": 8.0,
                "proteina": 14.0,
                "grasa": 5.5,
                "hierro": 3.4,
                "calcio": 43.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
            }
        ],
    )
    assert get_daily_data_dates(db) == {"2026-08-10", "2026-08-11", "2026-08-12"}
    # Día sin ningún dato no aparece.
    assert "2026-08-13" not in get_daily_data_dates(db)
    # Filtrado por vista: entrenamiento solo training_sets, alimentación solo diario.
    assert get_daily_data_dates(db, "entrenamiento") == {"2026-08-10", "2026-08-12"}
    assert get_daily_data_dates(db, "alimentacion") == {"2026-08-11", "2026-08-12"}
