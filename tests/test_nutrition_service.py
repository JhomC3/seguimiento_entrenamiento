"""Tests del servicio de dominio nutricional y sus modelos."""

import pytest

from src.database import (
    find_alimento,
    get_diario_by_fecha,
    get_plantillas_alimentacion,
    init_db,
    insert_alimento,
    insert_plantilla_alimentacion,
)
from src.models import (
    AlimentoInput,
    ConflictError,
    NotFoundError,
    NutritionEntryInput,
    ValidationError,
)
from src.nutrition_service import (
    NUTRIENT_FIELDS,
    apply_meal_template,
    calculate_nutrients,
    create_alimento,
    delete_diary,
    diary_totals,
    entries_from_form,
    objetivos_diarios,
    save_diary,
    save_meal_template,
)


def _catalog_avena() -> dict:
    return {
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
        "magnesio": 177.0,
        "zinc": 4.0,
        "potasio": 429.0,
        "sodio": 2.0,
        "vitamina_d": 0.0,
        "vitamina_e": 1.0,
        "vitamina_k": 2.0,
        "folato": 56.0,
        "vitamina_b12": 0.0,
        "vitamina_b6": 0.12,
        "yodo": 0.0,
        "selenio": 34.0,
    }


class TestModels:
    def test_nutrition_entry_input(self):
        entry = NutritionEntryInput(alimento="Avena", cantidad_g="120")
        assert entry.alimento == "Avena"
        assert entry.cantidad_g == "120"

    def test_alimento_input_defaults(self):
        alimento = AlimentoInput(nombre="Avena")
        assert alimento.categoria == ""
        assert alimento.kcal == 0.0
        assert alimento.vitamina_a == 0.0
        assert len(NUTRIENT_FIELDS) == 21


class TestCalculation:
    def test_sheet_round_half_up(self):
        from src.nutrition_service import _sheet_round

        assert _sheet_round("2.5") == 3.0
        assert _sheet_round("2.4") == 2.0
        assert _sheet_round("1.5") == 2.0

    def test_calculate_avena_120g_matches_sheet(self):
        # 389*1.2=466.8->467, 68*1.2=81.6->82, 10*1.2=12, 17*1.2=20.4->20,
        # 6.9*1.2=8.28->8, 4.2*1.2=5.04->5, 54*1.2=64.8->65
        result = calculate_nutrients(_catalog_avena(), 120.0)
        assert result["kcal"] == 467.0
        assert result["carbohidratos"] == 82.0
        assert result["fibra"] == 12.0
        assert result["proteina"] == 20.0
        assert result["grasa"] == 8.0
        assert result["hierro"] == 5.0
        assert result["calcio"] == 65.0
        assert result["vitamina_c"] == 0.0
        assert result["vitamina_a"] == 0.0

    def test_each_nutrient_rounded_independently_half_up(self):
        food = _catalog_avena()
        result = calculate_nutrients(food, 5.0)  # fibra 10*0.05 = 0.5 -> 1
        assert result["fibra"] == 1.0
        assert result["grasa"] == 0.0  # 6.9*0.05=0.345 -> 0

    def test_kcal_comes_from_catalog_not_macros(self):
        food = _catalog_avena()
        food["kcal"] = 999.0
        result = calculate_nutrients(food, 100.0)
        assert result["kcal"] == 999.0


class TestFormParsing:
    def test_skips_empty_rows(self):
        entries = entries_from_form(["", "Avena"], ["", "120"])
        assert len(entries) == 1
        assert entries[0].alimento == "Avena"
        assert entries[0].cantidad_g == "120"

    def test_skips_all_empty(self):
        assert entries_from_form([], []) == []

    def test_partial_row_without_cantidad_raises(self):
        with pytest.raises(ValidationError):
            entries_from_form(["Avena"], [""])

    def test_partial_row_without_alimento_raises(self):
        with pytest.raises(ValidationError):
            entries_from_form([""], ["120"])

    def test_non_numeric_cantidad_raises(self):
        with pytest.raises(ValidationError):
            entries_from_form(["Avena"], ["abc"])

    def test_zero_cantidad_raises(self):
        with pytest.raises(ValidationError):
            entries_from_form(["Avena"], ["0"])


class TestSaveDiary:
    def test_save_computes_from_catalog_and_orders(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        insert_alimento(db, _catalog_avena())
        save_diary(
            db,
            "2025-04-24",
            [NutritionEntryInput("Avena", "120"), NutritionEntryInput("Avena", "100")],
        )
        rows = get_diario_by_fecha(db, "2025-04-24")
        assert [r["orden"] for r in rows] == [1, 2]
        assert rows[0]["kcal"] == 467.0
        assert rows[1]["kcal"] == 389.0
        assert rows[0]["origen"] == "manual"

    def test_save_unknown_alimento_raises(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        with pytest.raises(NotFoundError):
            save_diary(db, "2025-04-24", [NutritionEntryInput("No Existe", "120")])

    def test_save_invalid_fecha_raises(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        with pytest.raises(ValidationError):
            save_diary(db, "24/4/2025", [NutritionEntryInput("Avena", "120")])

    def test_save_replaces_previous_day(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        insert_alimento(db, _catalog_avena())
        save_diary(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
        save_diary(db, "2025-04-24", [NutritionEntryInput("Avena", "100")])
        rows = get_diario_by_fecha(db, "2025-04-24")
        assert len(rows) == 1
        assert rows[0]["cantidad_g"] == 100.0

    def test_delete_diary(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        insert_alimento(db, _catalog_avena())
        save_diary(db, "2025-04-24", [NutritionEntryInput("Avena", "120")])
        delete_diary(db, "2025-04-24")
        assert get_diario_by_fecha(db, "2025-04-24") == []


class TestCreateAlimento:
    def test_create_alimento_manual(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        create_alimento(db, AlimentoInput(nombre="Avena", categoria="Cereal", kcal=389.0))
        found = find_alimento(db, "avena")
        assert found is not None
        assert found["nombre"] == "Avena"
        assert found["kcal"] == 389.0

    def test_create_duplicate_raises_conflict(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        create_alimento(db, AlimentoInput(nombre="Avena", kcal=1.0))
        with pytest.raises(ConflictError):
            create_alimento(db, AlimentoInput(nombre="avena", kcal=2.0))

    def test_create_alimento_rechaza_kcal_implausible(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        with pytest.raises(ValidationError):
            create_alimento(db, AlimentoInput(nombre="Arepa", kcal=6900.0))
        assert find_alimento(db, "Arepa") is None

    def test_micro_dri_targets_son_dri_hombre_adulto(self):
        from src.nutrition_service import MICRO_DRI_TARGETS, MICRO_UL, NUTRIENT_UNITS

        assert MICRO_DRI_TARGETS["fibra_objetivo"] == 38.0
        assert MICRO_DRI_TARGETS["hierro_objetivo"] == 8.0
        assert MICRO_DRI_TARGETS["calcio_objetivo"] == 1000.0
        assert MICRO_DRI_TARGETS["vitamina_c_objetivo"] == 90.0
        assert MICRO_DRI_TARGETS["vitamina_a_objetivo"] == 900.0
        assert MICRO_DRI_TARGETS["magnesio_objetivo"] == 420.0
        assert MICRO_DRI_TARGETS["zinc_objetivo"] == 11.0
        assert MICRO_DRI_TARGETS["potasio_objetivo"] == 3400.0
        assert MICRO_DRI_TARGETS["sodio_objetivo"] == 1500.0
        assert MICRO_DRI_TARGETS["vitamina_d_objetivo"] == 15.0
        assert MICRO_DRI_TARGETS["vitamina_b12_objetivo"] == 2.4
        assert MICRO_DRI_TARGETS["yodo_objetivo"] == 150.0
        assert MICRO_DRI_TARGETS["selenio_objetivo"] == 55.0
        assert MICRO_UL["vitamina_a"] == 3000.0
        assert MICRO_UL["sodio"] == 2300.0
        assert MICRO_UL["fibra"] is None
        assert MICRO_UL["potasio"] is None
        assert NUTRIENT_UNITS["vitamina_a"] == "mcg"
        assert NUTRIENT_UNITS["vitamina_d"] == "mcg"
        assert NUTRIENT_UNITS["magnesio"] == "mg"


class TestTargetFormulas:
    def _params(self, **over):
        params = {
            "peso_kg": 69.0,
            "factor_proteina": 1.5,
            "factor_grasa": 1.1,
            "kcal_objetivo": 2750.0,
            "fibra_objetivo": 38.0,
            "hierro_objetivo": 8.0,
            "calcio_objetivo": 1000.0,
            "vitamina_c_objetivo": 90.0,
            "vitamina_a_objetivo": 900.0,
        }
        params.update(over)
        return params

    def test_objetivos_diarios_formula_dictada(self):
        target = objetivos_diarios(self._params())
        assert target["proteina"] == 104.0  # round_half_up(69 * 1.5)
        assert target["grasa"] == 76.0  # round_half_up(69 * 1.1)
        assert target["kcal"] == 2750.0
        # round_half_up((2750 - 4*104 - 9*76) / 4) = round_half_up(412.5) = 413
        assert target["carbohidratos"] == 413.0
        assert target["fibra"] == 38.0
        assert target["hierro"] == 8.0
        assert target["calcio"] == 1000.0
        assert target["vitamina_c"] == 90.0
        assert target["vitamina_a"] == 900.0

    def test_objetivos_diarios_redondeo_half_up(self):
        target = objetivos_diarios(self._params(peso_kg=1.0, kcal_objetivo=2.0))
        # 1*1.5 = 1.5 -> 2 (half-up); 1*1.1 = 1.1 -> 1
        assert target["proteina"] == 2.0
        assert target["grasa"] == 1.0

    def test_objetivos_carb_from_atwater_residual(self):
        # carb = (kcal - 4*prot - 9*grasa) / 4
        target = objetivos_diarios(
            self._params(peso_kg=60.0, factor_grasa=1.2, kcal_objetivo=2300.0)
        )
        assert target["proteina"] == 90.0
        assert target["grasa"] == 72.0
        # (2300 - 360 - 648) / 4 = 323
        assert target["carbohidratos"] == 323.0


class TestMealTemplates:
    def test_save_meal_template_upserts_by_name(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        insert_alimento(db, _catalog_avena())
        save_meal_template(db, "Desayuno", [{"alimento": "Avena", "cantidad_g": 120.0}])
        save_meal_template(db, "Desayuno", [{"alimento": "Avena", "cantidad_g": 150.0}])
        plantillas = get_plantillas_alimentacion(db)
        assert len(plantillas) == 1
        assert plantillas[0]["alimentos"][0]["cantidad_g"] == 150.0

    def test_save_meal_template_valida_nombre_y_filas(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        with pytest.raises(ValidationError):
            save_meal_template(db, "  ", [{"alimento": "Avena", "cantidad_g": 100.0}])
        with pytest.raises(ValidationError):
            save_meal_template(db, "X", [{"alimento": "", "cantidad_g": 100.0}])

    def test_apply_meal_template_computes_nutrients(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        insert_alimento(db, _catalog_avena())
        pid = insert_plantilla_alimentacion(
            db, "Desayuno", [{"alimento": "Avena", "cantidad_g": 120.0}]
        )
        rows = apply_meal_template(db, pid)
        assert rows[0]["alimento"] == "Avena"
        assert rows[0]["cantidad_g"] == 120.0
        assert rows[0]["kcal"] == 467.0
        assert rows[0]["proteina"] == 20.0

    def test_apply_meal_template_unknown_food_zeroes(self, tmp_path):
        db = str(tmp_path / "g.db")
        init_db(db)
        pid = insert_plantilla_alimentacion(
            db, "X", [{"alimento": "No Existe", "cantidad_g": 100.0}]
        )
        rows = apply_meal_template(db, pid)
        assert rows[0]["kcal"] == 0.0


class TestTotals:
    def test_diary_totals_sums_entries(self):
        rows = [
            {
                "kcal": 467.0,
                "carbohidratos": 82.0,
                "fibra": 12.0,
                "proteina": 20.0,
                "grasa": 8.0,
                "hierro": 5.0,
                "calcio": 65.0,
                "vitamina_c": 0.0,
                "vitamina_a": 0.0,
            },
            {
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
        ]
        totals = diary_totals(rows)
        assert totals["kcal"] == 610.0
        assert totals["proteina"] == 33.0
        assert totals["vitamina_a"] == 300.0

    def test_diary_totals_empty(self):
        totals = diary_totals([])
        assert all(totals[f] == 0.0 for f in NUTRIENT_FIELDS)
