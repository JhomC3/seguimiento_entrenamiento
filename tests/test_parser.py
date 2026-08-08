import pandas as pd
import pytest

from src.parser import parse_alimentos, parse_ciclo, parse_ejercicios, parse_float

SAMPLE_EJERCICIOS_CSV = """,,
,Pectoral,Press Convergente
,Pectoral,Press Mancuernas
,Triceps,Katana
,Biceps,Curl Bayesian
,Espalda,Remo Prono
"""

SAMPLE_CICLO_CSV_DATA = [
    ["", "", "", "Semana", "1", "", "", "Semana", "2", "", ""],
    ["", "", "", "Ejercicio", "Rep", "Kg", "RIR", "Ejercicio", "Rep", "Kg", "RIR"],
    ["", "LUNES", "", "4/5/26", "", "", "", "11/5/26", "", "", ""],
    ["", "", "1", "Press Convergente", "6", "85", "1", "Press Convergente", "6", "90", "1"],
    ["", "", "2", "Press Convergente", "6", "85", "0.4", "Press Convergente", "6", "90", "0.5"],
    ["", "", "3", "Press Mancuernas", "7", "30", "1", "Press Mancuernas", "7", "30", "1"],
    ["", "MARTES", "", "5/5/26", "", "", "", "12/5/26", "", "", ""],
    ["", "", "4", "Curl Bayesian", "7", "13", "1", "Curl Bayesian", "6", "14", "0.8"],
]
SAMPLE_CICLO_CSV = "\n".join([",".join(row) for row in SAMPLE_CICLO_CSV_DATA]) + "\n"


def test_parse_ejercicios_returns_dataframe():
    df = parse_ejercicios(SAMPLE_EJERCICIOS_CSV)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["grupo_muscular", "ejercicio"]
    assert len(df) == 5


def test_parse_ejercicios_content():
    df = parse_ejercicios(SAMPLE_EJERCICIOS_CSV)
    assert df.iloc[0]["grupo_muscular"] == "Pectoral"
    assert df.iloc[0]["ejercicio"] == "Press Convergente"
    assert df.iloc[3]["grupo_muscular"] == "Biceps"
    assert df.iloc[3]["ejercicio"] == "Curl Bayesian"


def test_parse_float():
    assert parse_float("6") == 6.0
    assert parse_float("6.5") == 6.5
    assert parse_float("6,5") == 6.5
    assert parse_float("6 5") == 6.0
    assert parse_float("---") is None
    assert parse_float(None) is None


def test_parse_ciclo_returns_dataframe():
    df = parse_ciclo(SAMPLE_CICLO_CSV)
    assert isinstance(df, pd.DataFrame)
    required_cols = ["semana", "dia", "fecha", "set_orden", "ejercicio", "reps", "kg", "rir"]
    for col in required_cols:
        assert col in df.columns
    # Check values for week 1 Lunes set 1
    row_1 = df[(df["semana"] == 1) & (df["dia"] == "LUNES") & (df["set_orden"] == 1)].iloc[0]
    assert row_1["ejercicio"] == "Press Convergente"
    assert row_1["reps"] == 6.0
    assert row_1["kg"] == 85.0
    assert row_1["rir"] == 1.0
    assert row_1["fecha"] == "4/5/26"

    # Check values for week 2 Lunes set 1
    row_2 = df[(df["semana"] == 2) & (df["dia"] == "LUNES") & (df["set_orden"] == 1)].iloc[0]
    assert row_2["ejercicio"] == "Press Convergente"
    assert row_2["reps"] == 6.0
    assert row_2["kg"] == 90.0
    assert row_2["rir"] == 1.0
    assert row_2["fecha"] == "11/5/26"

    assert len(df[df["semana"] == 1]) == 4
    assert len(df[df["semana"] == 2]) == 4


SAMPLE_ALIMENTOS_CSV = """Alimento,Categoría,cantidad,Calorías (kcal),Carbohidratos (g),Fibra (g),Proteína (g),Grasa (g),Hierro (mg),Calcio (mg),Vitamina C (mg),Vitamina A
Avena,Cereal,100,389,68,"10,0",17,"6,9","4,2",54,0,0
Huevo,Animal,100,143,1,0,13,10,2,50,0,300
"""

ALIMENTO_COLUMNS = [
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
]


def test_parse_alimentos_columns():
    df = parse_alimentos(SAMPLE_ALIMENTOS_CSV)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ALIMENTO_COLUMNS
    assert len(df) == 2


def test_parse_alimentos_values():
    df = parse_alimentos(SAMPLE_ALIMENTOS_CSV)
    avena = df[df["nombre"] == "Avena"].iloc[0]
    assert avena["categoria"] == "Cereal"
    assert avena["kcal"] == 389.0
    assert avena["carbohidratos"] == 68.0
    assert avena["fibra"] == 10.0
    assert avena["proteina"] == 17.0
    assert avena["grasa"] == 6.9
    assert avena["hierro"] == 4.2
    assert avena["calcio"] == 54.0
    assert avena["vitamina_c"] == 0.0
    assert avena["vitamina_a"] == 0.0


def test_parse_alimentos_strips_names_and_categories():
    csv_text = SAMPLE_ALIMENTOS_CSV.replace("Avena,Cereal,", "  Avena  ,  Cereal  ,")
    df = parse_alimentos(csv_text)
    assert df.iloc[0]["nombre"] == "Avena"
    assert df.iloc[0]["categoria"] == "Cereal"


def test_parse_alimentos_rejects_non_100g_base():
    csv_text = SAMPLE_ALIMENTOS_CSV.replace("Avena,Cereal,100,", "Avena,Cereal,50,")
    with pytest.raises(ValueError):
        parse_alimentos(csv_text)


def test_parse_alimentos_rejects_missing_nutrients():
    csv_text = SAMPLE_ALIMENTOS_CSV.replace("389,68", "389,")
    with pytest.raises(ValueError):
        parse_alimentos(csv_text)


def test_parse_alimentos_drops_empty_rows():
    csv_text = SAMPLE_ALIMENTOS_CSV + "\n\n\n"
    df = parse_alimentos(csv_text)
    assert len(df) == 2
