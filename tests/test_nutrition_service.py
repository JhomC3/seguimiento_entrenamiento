"""Tests del servicio de dominio nutricional y sus modelos."""

import pytest

from src.database import (
    find_alimento,
    get_diario_by_fecha,
    init_db,
    insert_alimento,
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
    calculate_nutrients,
    create_alimento,
    delete_diary,
    diary_totals,
    entries_from_form,
    save_diary,
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
        assert len(NUTRIENT_FIELDS) == 9


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
