"""Coverage-boundary tests for defensive branches in services and runner."""

import pytest

from src.dashboard_service import (
    build_date_navigator,
    chart_html,
    get_ejercicios_por_grupo,
    get_filters,
    translate_error,
)
from src.database import init_db
from src.migrations.runner import current_version, pending_migrations
from src.models import ConflictError, NotFoundError, ValidationError
from src.training_service import parse_cycle_start


def test_get_filters_returns_empty_on_missing_db(tmp_path):
    ejercicios, grupos = get_filters(str(tmp_path / "no.db"))
    assert ejercicios == []
    assert grupos == []


def test_get_filters_returns_empty_on_corrupt_db(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite file at all")
    ejercicios, grupos = get_filters(str(bad))
    assert ejercicios == []
    assert grupos == []


def test_get_ejercicios_por_grupo_empty_on_missing_db(tmp_path):
    assert get_ejercicios_por_grupo(str(tmp_path / "no.db"), "Pectoral") == []


def test_fechas_con_datos_skips_malformed(tmp_path):
    from src.dashboard_service import fechas_con_datos
    from src.db_connection import connect_db

    db = str(tmp_path / "gym.db")
    init_db(db)
    conn = connect_db(db)
    conn.execute(
        "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio) "
        "VALUES (1, 'LUNES', 'no-es-fecha', 1, 'Press')"
    )
    conn.commit()
    conn.close()
    assert fechas_con_datos(db) == set()


def test_build_date_navigator_malformed_date_raises(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    with pytest.raises(ValidationError):
        build_date_navigator(
            db, "bad-date", parse_cycle_start(), __import__("datetime").date.today()
        )


def test_chart_html_empty_db_shows_sin_datos(tmp_path):
    db = str(tmp_path / "gym.db")
    init_db(db)
    html = chart_html(db, "systemic")
    assert "Sin datos" in html


def test_translate_error_maps_domain_and_unexpected():
    msg, status = translate_error(ValidationError("mala fecha"))
    assert status == 400
    assert msg == "mala fecha"
    msg, status = translate_error(NotFoundError("no existe"))
    assert status == 400
    msg, status = translate_error(ConflictError("duplicado"))
    assert status == 400
    msg, status = translate_error(RuntimeError("boom"))
    assert status == 500
    assert msg == "Ocurrió un error inesperado."


def test_pending_and_current_version(tmp_path):
    db = str(tmp_path / "gym.db")
    pending = pending_migrations(db)
    assert {m.VERSION for m in pending} == {1, 2, 3}
    assert current_version(db) == 0
    init_db(db)
    assert pending_migrations(db) == []
    assert current_version(db) == 3


def test_corrupt_db_returns_empty_filters_not_crash(tmp_path):
    bad = tmp_path / "bad2.db"
    bad.write_bytes(b"garbage")
    assert get_filters(str(bad)) == ([], [])
