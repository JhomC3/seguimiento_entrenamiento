import pandas as pd
import pytest

from src.parser import parse_alimentos, parse_ciclo, parse_diario, parse_ejercicios, parse_float

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
    assert row_1["fecha"] == "2026-05-04"

    # Check values for week 2 Lunes set 1
    row_2 = df[(df["semana"] == 2) & (df["dia"] == "LUNES") & (df["set_orden"] == 1)].iloc[0]
    assert row_2["ejercicio"] == "Press Convergente"
    assert row_2["reps"] == 6.0
    assert row_2["kg"] == 90.0
    assert row_2["rir"] == 1.0
    assert row_2["fecha"] == "2026-05-11"

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


def test_parse_alimentos_normalizes_non_100_base():
    csv_text = (
        "Alimento,Categoría,cantidad,Calorías (kcal),Carbohidratos (g),Fibra (g),"
        "Proteína (g),Grasa (g),Hierro (mg),Calcio (mg),Vitamina C (mg),Vitamina A\n"
        "Arepa,Procesado,1,69,12,2,2,1,0,10,0,0\n"
        'Queso Doble Crema,Lácteo,23,"80,5",1,0,5,7,0,276,0,130\n'
    )
    df = parse_alimentos(csv_text)
    arepa = df[df["nombre"] == "Arepa"].iloc[0]
    assert arepa["kcal"] == 6900.0
    assert arepa["carbohidratos"] == 1200.0
    queso = df[df["nombre"] == "Queso Doble Crema"].iloc[0]
    assert queso["kcal"] == 350.0
    assert queso["calcio"] == 1200.0


def test_parse_alimentos_rejects_missing_nutrients():
    csv_text = SAMPLE_ALIMENTOS_CSV.replace("389,68", "389,")
    with pytest.raises(ValueError):
        parse_alimentos(csv_text)


def test_parse_alimentos_drops_empty_rows():
    csv_text = SAMPLE_ALIMENTOS_CSV + "\n\n\n"
    df = parse_alimentos(csv_text)
    assert len(df) == 2


DIARIO_COLUMNS = [
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
]

# Fila 1: porcentajes (resumen). Fila 2: encabezados. Fila 3: porcentajes.
# Fila 4: objetivo. Fila 5: totales. Filas 6+: alimentos.
# El primer bloque (24/4/2025) usa orden Fibra/Proteína/Grasa;
# el segundo (25/4/2025) usa orden Proteína/Grasa/Fibra.
SAMPLE_DIARIO_ROWS = [
    [
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
    [
        "",
        "24/4/2025",
        "Cantidad",
        "Calorías (kcal)",
        "Carbohidratos (g)",
        "Fibra (g)",
        "Proteína (g)",
        "Grasa (g)",
        "Hierro (mg)",
        "Calcio (mg)",
        "Vitamina C (mg)",
        "Vitamina A",
        "",
        "25/4/2025",
        "Cantidad",
        "Calorías (kcal)",
        "Carbohidratos (g)",
        "Proteína (g)",
        "Grasa (g)",
        "Fibra (g)",
        "Hierro (mg)",
        "Calcio (mg)",
        "Vitamina C (mg)",
        "Vitamina A",
        "",
    ],
    [
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
    [
        "",
        "",
        "",
        "2300",
        "375",
        "38",
        "90",
        "72",
        "8",
        "1000",
        "90",
        "900",
        "",
        "",
        "",
        "2300",
        "375",
        "38",
        "90",
        "72",
        "8",
        "1000",
        "90",
        "900",
        "",
    ],
    [
        "",
        "",
        "",
        "1326",
        "210",
        "31",
        "44",
        "88",
        "18",
        "593",
        "60",
        "894",
        "",
        "",
        "1195",
        "221",
        "36",
        "53",
        "107",
        "44",
        "607",
        "76",
        "467",
        "",
    ],
    [
        "",
        "Avena",
        "120 g",
        "467",
        "82",
        "12",
        "20",
        "8",
        "5",
        "65",
        "0",
        "0",
        "",
        "Avena",
        "150 g",
        "584",
        "102",
        "26",
        "10",
        "15",
        "6",
        "81",
        "0",
        "0",
        "",
    ],
    [
        "",
        "Huevo",
        "100 g",
        "143",
        "1",
        "0",
        "13",
        "10",
        "2",
        "50",
        "0",
        "300",
        "",
        "Huevo",
        "104 g",
        "149",
        "1",
        "13",
        "10",
        "0",
        "2",
        "52",
        "0",
        "0",
        "",
    ],
    [
        "",
        "Semillas de Chía",
        " g",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
    [
        "",
        "Tomate de Arbol",
        "100 g",
        "42",
        "10",
        "3",
        "2",
        "1",
        "1",
        "10",
        "30",
        "200",
        "",
        "Manzana Verde",
        "90 g",
        "47",
        "12",
        "0",
        "0",
        "2",
        "0",
        "5",
        "4",
        "3",
        "",
    ],
]
SAMPLE_DIARIO_CSV = "\n".join([",".join(row) for row in SAMPLE_DIARIO_ROWS]) + "\n"


def test_parse_diario_columns():
    result = parse_diario(SAMPLE_DIARIO_CSV)
    df = result.df
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == DIARIO_COLUMNS


def test_parse_diario_orders_columns_by_block_header():
    # El bloque 1 usa Fibra/Proteína/Grasa y el bloque 2 Proteína/Grasa/Fibra.
    df = parse_diario(SAMPLE_DIARIO_CSV).df
    avena_1 = df[(df["fecha"] == "2025-04-24") & (df["alimento"] == "Avena")].iloc[0]
    assert avena_1["fibra"] == 12.0
    assert avena_1["proteina"] == 20.0
    assert avena_1["grasa"] == 8.0
    avena_2 = df[(df["fecha"] == "2025-04-25") & (df["alimento"] == "Avena")].iloc[0]
    assert avena_2["fibra"] == 15.0
    assert avena_2["proteina"] == 26.0
    assert avena_2["grasa"] == 10.0


def test_parse_diario_values_and_iso_dates():
    df = parse_diario(SAMPLE_DIARIO_CSV).df
    huevo_1 = df[(df["fecha"] == "2025-04-24") & (df["alimento"] == "Huevo")].iloc[0]
    assert huevo_1["cantidad_g"] == 100.0
    assert huevo_1["kcal"] == 143.0
    assert huevo_1["calcio"] == 50.0
    assert huevo_1["vitamina_a"] == 300.0
    tomate = df[(df["fecha"] == "2025-04-24") & (df["alimento"] == "Tomate de Arbol")].iloc[0]
    assert tomate["vitamina_c"] == 30.0


def test_parse_diario_skips_summary_rows():
    df = parse_diario(SAMPLE_DIARIO_CSV).df
    assert not df["alimento"].str.contains("Cantidad|Calorías|Fibra", case=False).any()


def test_parse_diario_keeps_placeholder_rows():
    df = parse_diario(SAMPLE_DIARIO_CSV).df
    row = df[df["alimento"] == "Semillas de Chía"].iloc[0]
    assert pd.isna(row["cantidad_g"])
    assert row["kcal"] == 0.0
    assert row["fibra"] == 0.0


def test_parse_diario_orders_entries_by_fecha():
    df = parse_diario(SAMPLE_DIARIO_CSV).df
    for fecha, group in df.groupby("fecha"):
        assert list(group["orden"]) == list(range(1, len(group) + 1))


def test_parse_diario_skips_truncated_edge_rows():
    # Al borde del rango exportado, la última fila puede quedar cortada a
    # media anchura (caso real del bloque final). Se descarta, no se importa
    # con ceros ni se aborta el parseo.
    truncated = SAMPLE_DIARIO_ROWS[5][:8]
    rows = [list(r) for r in SAMPLE_DIARIO_ROWS[:6]]
    rows[5] = truncated
    df = parse_diario("\n".join([",".join(r) for r in rows]) + "\n").df
    assert not (df["alimento"] == "Avena").any()
    assert df.empty


def test_parse_diario_treats_empty_cell_as_zero():
    # La hoja trata celdas en blanco como 0 en sus fórmulas (caso real: kcal
    # olvidada de Papa, fila sin macros de Aceite de Oliva).
    broken = list(SAMPLE_DIARIO_ROWS[5])
    broken[3] = ""
    rows = [list(r) for r in SAMPLE_DIARIO_ROWS[:6]]
    rows[5] = broken
    df = parse_diario("\n".join([",".join(r) for r in rows]) + "\n").df
    avena = df[(df["fecha"] == "2025-04-24") & (df["alimento"] == "Avena")].iloc[0]
    assert avena["kcal"] == 0.0
    assert avena["fibra"] == 12.0


def test_parse_diario_dedups_identical_blocks():
    # Caso real: el 8/8/2026 está copiado 126 veces en la hoja con bloques
    # idénticos. Solo se importa una copia de cada bloque por fecha.
    rows = [list(r) for r in SAMPLE_DIARIO_ROWS]
    b1_header = rows[1][:13]
    rows[1] = b1_header + b1_header + b1_header
    for i in (2, 3, 4, 5, 6, 7, 8):
        rows[i] = rows[i][:13] * 3
    df = parse_diario("\n".join([",".join(r) for r in rows]) + "\n").df
    day = df[df["fecha"] == "2025-04-24"]
    assert day["alimento"].str.contains("Avena").sum() == 1
    assert list(day["orden"]) == [1, 2, 3, 4]


def test_parse_diario_concatenates_different_blocks_same_date():
    # Dos bloques con la misma fecha pero contenido distinto no son duplicados:
    # sus entradas se concatenan en orden.
    header = list(SAMPLE_DIARIO_ROWS[1])
    avena_row = list(SAMPLE_DIARIO_ROWS[5])
    extra_header = [
        "",
        "24/4/2025",
        "Cantidad",
        "Calorías (kcal)",
        "Carbohidratos (g)",
        "Fibra (g)",
        "Proteína (g)",
        "Grasa (g)",
        "Hierro (mg)",
        "Calcio (mg)",
        "Vitamina C (mg)",
        "Vitamina A",
        "",
    ]
    extra_avena = ["", "Avena", "80 g", "311", "55", "8", "13", "5", "3", "43", "0", "0", ""]
    rows = [list(r) for r in SAMPLE_DIARIO_ROWS]
    rows[1] = header + extra_header
    rows[5] = avena_row + extra_avena
    maxlen = max(len(r) for r in rows)
    rows = [r + [""] * (maxlen - len(r)) for r in rows]
    df = parse_diario("\n".join([",".join(r) for r in rows]) + "\n").df
    day = df[df["fecha"] == "2025-04-24"]
    avenas = day[day["alimento"].str.contains("Avena")]
    assert len(avenas) == 2
    assert list(avenas["orden"]) == [1, 2]
    assert list(day["orden"]) == [1, 2, 3, 4, 5]


def test_parse_diario_extracts_params_per_date():
    result = parse_diario(SAMPLE_DIARIO_CSV)
    by_date = {p["fecha"]: p for p in result.params}
    assert by_date["2025-04-24"] == {
        "fecha": "2025-04-24",
        "kcal_objetivo": 2300.0,
        "fibra_objetivo": 38.0,
        "hierro_objetivo": 8.0,
        "calcio_objetivo": 1000.0,
        "vitamina_c_objetivo": 90.0,
        "vitamina_a_objetivo": 900.0,
    }
    assert by_date["2025-04-25"]["kcal_objetivo"] == 2300.0
