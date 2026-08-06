import pandas as pd

from src.parser import parse_ciclo, parse_ejercicios, parse_float

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
