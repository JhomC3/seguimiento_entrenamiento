"""Static asset versioning and date navigator window bounds."""

import datetime

import pytest

from src.dashboard_service import build_date_navigator
from src.database import init_db, insert_exercise
from src.static_assets import static_url

CYCLE_START = datetime.date(2026, 5, 4)
TODAY = datetime.date(2026, 8, 14)


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "gym.db")
    init_db(path)
    insert_exercise(path, "Press", "Pectoral", "EMPUJE")
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as appmod

    db_path = str(tmp_path / "gym.db")
    init_db(db_path)
    monkeypatch.setattr(appmod, "DB_PATH", db_path)
    return TestClient(appmod.app)


def test_static_url_fingerprinted_deterministic():
    url1 = static_url("css/app.css")
    url2 = static_url("css/app.css")
    assert url1 == url2
    assert url1.startswith("/static/css/app.css?v=")
    assert len(url1.split("v=")[1]) >= 12


def test_versioned_static_asset_is_immutable(client):
    response = client.get(static_url("css/app.css"))
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unversioned_static_asset_is_no_cache(client):
    response = client.get("/static/css/app.css")
    assert response.headers["cache-control"] == "no-cache"


def test_stale_digest_is_no_cache(client):
    response = client.get("/static/css/app.css?v=deadbeef0000")
    assert response.headers["cache-control"] == "no-cache"


def test_missing_static_file_never_immutable(client):
    response = client.get("/static/css/nope.css?v=" + "0" * 12)
    assert response.headers["cache-control"] == "no-cache"


def test_navigator_has_a_bounded_selected_window(db):
    vm = build_date_navigator(db, "2026-08-14", CYCLE_START, TODAY)
    assert len(vm.dates) <= 31
    assert any(day.selected for day in vm.dates)
    selected = next(d for d in vm.dates if d.selected)
    assert selected.iso == "2026-08-14"


def test_navigator_window_centered_on_selection(db):
    vm = build_date_navigator(db, "2026-08-10", CYCLE_START, TODAY)
    assert len(vm.dates) == 31
    assert vm.dates[0].iso == "2026-07-26"
    assert vm.dates[-1].iso == "2026-08-25"


def test_navigator_window_clamped_to_cycle_start(db):
    vm = build_date_navigator(db, "2026-05-06", CYCLE_START, TODAY)
    assert vm.dates[0].iso == "2026-05-04"
    assert len(vm.dates) <= 31


def test_navigator_day_shows_week_before_date(db):
    vm = build_date_navigator(db, "2026-08-27", CYCLE_START, TODAY, granularity="day")
    # 27-08-26 is S17 (cycle 2026-05-04)
    target = next(d for d in vm.dates if d.iso == "2026-08-27")
    assert target.label == "S17 \u00b7 27-08-26"
    assert target.label.count("\u00b7") == 1
    assert target.aria_label == "Semana 17 \u00b7 27 de agosto de 2026"
    # All day labels must be S<n> · DD-MM-YY
    for d in vm.dates:
        assert " \u00b7 " in d.label
        assert d.label.startswith("S")
        # two digits for day/month/year
        assert len(d.label.split(" \u00b7 ")[1].split("-")) == 3
        assert len(d.label.split(" \u00b7 ")[1].split("-")[0]) == 2  # DD
        assert d.aria_label.startswith("Semana")
