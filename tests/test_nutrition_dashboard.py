"""Tests de view models y servicios de presentación nutricional."""

from src.dashboard_service import (
    build_nutrition_date_navigator,
    build_nutrition_editor,
)
from src.database import init_db, insert_alimento, replace_diario_by_fecha


def _seed(db: str) -> None:
    init_db(db)
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
    replace_diario_by_fecha(
        db,
        "2025-04-24",
        [
            {
                "alimento": "Avena",
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
                "origen": "google",
            }
        ],
    )
    replace_diario_by_fecha(
        db,
        "2025-04-25",
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
                "origen": "google",
            }
        ],
    )


def test_build_editor_with_data(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_editor(db, "2025-04-24")
    assert vm.fecha_iso == "2025-04-24"
    assert vm.has_data is True
    assert len(vm.rows) == 1
    row = vm.rows[0]
    assert row.alimento == "Avena"
    assert row.cantidad_g == 120.0
    assert row.kcal == 467.0
    assert row.grasa == 8.0
    assert vm.totals["kcal"] == 467.0
    assert vm.totals["proteina"] == 20.0
    assert vm.catalog == ["Avena"]
    assert vm.error is None
    assert vm.success is None


def test_build_editor_empty_day(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_editor(db, "2025-04-26")
    assert vm.has_data is False
    assert vm.rows == []
    assert all(vm.totals[f] == 0.0 for f in ("kcal", "carbohidratos", "fibra", "proteina", "grasa"))


def test_build_editor_future_date_is_editable(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_editor(db, "2030-01-01")
    assert vm.fecha_iso == "2030-01-01"
    assert vm.has_data is False
    assert not hasattr(vm, "readonly")


def test_build_editor_passes_error_and_success(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_editor(db, "2025-04-24", error="boom", success="ok")
    assert vm.error == "boom"
    assert vm.success == "ok"


def test_build_editor_objetivo_y_consumido(tmp_path):
    from src.database import save_parametros_diarios

    db = str(tmp_path / "g.db")
    _seed(db)
    save_parametros_diarios(
        db,
        "2025-04-24",
        {
            "peso_kg": 69.0,
            "factor_proteina": 1.5,
            "factor_grasa": 1.1,
            "kcal_objetivo": 2750.0,
            "fibra_objetivo": 38.0,
            "hierro_objetivo": 8.0,
            "calcio_objetivo": 1000.0,
            "vitamina_c_objetivo": 90.0,
            "vitamina_a_objetivo": 900.0,
        },
    )
    vm = build_nutrition_editor(db, "2025-04-24")
    assert vm.objetivo["proteina"] == 104.0
    assert vm.objetivo["grasa"] == 76.0
    assert vm.objetivo["carbohidratos"] == 413.0
    assert vm.objetivo["kcal"] == 2750.0
    assert vm.objetivo["fibra"] == 38.0
    assert vm.consumido["kcal"] == 467.0
    assert vm.consumido["proteina"] == 20.0
    assert vm.consumido["cantidad_g"] == 120.0
    assert vm.parametros["peso_kg"] == 69.0
    assert vm.parametros["factor_proteina"] == 1.5


def test_build_editor_defaults_params_on_empty_day(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_editor(db, "2025-04-26")
    assert vm.parametros["peso_kg"] == 70.0
    assert vm.parametros["factor_proteina"] == 1.5
    assert vm.parametros["factor_grasa"] == 1.1
    assert vm.parametros["kcal_objetivo"] == 2300.0
    assert vm.objetivo["proteina"] == 105.0
    assert vm.consumido["cantidad_g"] == 0.0
    assert vm.consumido["kcal"] == 0.0


def test_build_navigator_sorted_dates_and_selected(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_date_navigator(db, "2025-04-24")
    assert vm.selected_iso == "2025-04-24"
    assert vm.available_dates == ["2025-04-24", "2025-04-25"]
    assert vm.previous_iso == "2025-04-23"
    assert vm.next_iso == "2025-04-25"
    assert vm.today_iso


def test_build_navigator_falls_back_to_today_for_bad_date(tmp_path):
    from datetime import date

    db = str(tmp_path / "g.db")
    _seed(db)
    vm = build_nutrition_date_navigator(db, "basura", today=date(2025, 4, 30))
    assert vm.selected_iso == "2025-04-30"


def test_build_navigator_empty_db(tmp_path):
    from datetime import date

    db = str(tmp_path / "g.db")
    init_db(db)
    vm = build_nutrition_date_navigator(db, "2025-04-24", today=date(2025, 4, 30))
    assert vm.available_dates == []
    assert vm.previous_iso == "2025-04-23"
    assert vm.next_iso == "2025-04-25"
