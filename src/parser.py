import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


def _iso_or_null(value) -> str | None:
    """Convierte fecha legacy 'd/m/yy' (o 'd/m/YYYY') a ISO; None si no parsea."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_ejercicios(csv_text: str) -> pd.DataFrame:
    """Parsea la hoja 'ejercicios' -> DataFrame con columnas [grupo_muscular, ejercicio]."""
    df = pd.read_csv(io.StringIO(csv_text), header=None)
    # De los datos descargados sabemos que la columna 1 es el grupo muscular y la columna 2 es el ejercicio.
    df = df[[1, 2]].copy()
    df.columns = ["grupo_muscular", "ejercicio"]
    # Limpiar espacios
    df["grupo_muscular"] = df["grupo_muscular"].astype(str).str.strip()
    df["ejercicio"] = df["ejercicio"].astype(str).str.strip()

    # Eliminar filas vacías o nulas
    df = df.dropna(subset=["grupo_muscular", "ejercicio"])
    df = df[df["grupo_muscular"] != "nan"]
    df = df[df["ejercicio"] != "nan"]
    df = df[df["grupo_muscular"] != ""]
    df = df[df["ejercicio"] != ""]

    df = df.reset_index(drop=True)
    return df


DAY_NAMES = {"LUNES", "MARTES", "MIERCOLES", "VIERNES", "SABADO"}


def parse_float(val) -> float | None:
    if pd.isna(val):
        return None
    val_str = str(val).strip().replace(",", ".")
    # Limpiar posibles caracteres extraños
    if val_str == "" or val_str == "---" or val_str == "-":
        return None
    try:
        # Algunos valores pueden ser como "6 5" o similar. Intentar procesar o limpiar.
        # Si contiene espacio, tomamos el primer término o evaluamos.
        if " " in val_str:
            val_str = val_str.split(" ")[0]
        return float(val_str)
    except ValueError:
        return None


def parse_ciclo(csv_text: str) -> pd.DataFrame:
    """Parsea la hoja 'ciclo_16' -> DataFrame con columnas:
    [semana, dia, fecha, set_orden, ejercicio, reps, kg, rir]
    """
    df_raw = pd.read_csv(io.StringIO(csv_text), header=None)

    # Identificar semanas
    # En la fila 0, las semanas se listan cada 5 columnas partiendo de la col 3.
    # Vamos a crear una lista de semanas basada en las columnas disponibles.
    week_columns = []  # Tuplas de (numero_semana, indice_columna_ejercicio)
    current_week = 1
    col_idx = 3
    while col_idx < df_raw.shape[1]:
        week_columns.append((current_week, col_idx))
        current_week += 1
        col_idx += 4

    records = []
    current_day = None
    dates_per_week: dict[int, str] = {}  # {semana_num: fecha}

    for row_idx in range(2, len(df_raw)):
        row = df_raw.iloc[row_idx]

        # Validar si es una fila de día
        cell_1 = str(row.iloc[1]).strip().upper() if pd.notna(row.iloc[1]) else ""
        if cell_1 in DAY_NAMES:
            current_day = cell_1
            # Extraer fechas de esta fila para cada semana
            dates_per_week = {}
            for week_num, col_ej in week_columns:
                if col_ej < len(row):
                    date_val = row.iloc[col_ej]
                    if pd.notna(date_val) and str(date_val).strip() != "":
                        dates_per_week[week_num] = str(date_val).strip()
            continue

        # Si no hay día activo, ignoramos filas iniciales
        if not current_day:
            continue

        # Validar si es una fila de set (la col 2 contiene el número de set)
        cell_2 = row.iloc[2]
        if pd.isna(cell_2):
            continue

        try:
            set_orden = int(float(str(cell_2).strip()))
        except ValueError:
            # No es una fila de set válida
            continue

        # Extraer registros para cada semana
        for week_num, col_ej in week_columns:
            if col_ej >= len(row):
                continue

            ejercicio = row.iloc[col_ej]
            if (
                pd.isna(ejercicio)
                or str(ejercicio).strip() == ""
                or str(ejercicio).strip() == "nan"
            ):
                continue

            # Las columnas relativas al ejercicio son:
            # col_ej: ejercicio
            # col_ej + 1: reps
            # col_ej + 2: kg
            # col_ej + 3: rir
            reps_val = row.iloc[col_ej + 1] if col_ej + 1 < len(row) else None
            kg_val = row.iloc[col_ej + 2] if col_ej + 2 < len(row) else None
            rir_val = row.iloc[col_ej + 3] if col_ej + 3 < len(row) else None

            reps = parse_float(reps_val)
            kg = parse_float(kg_val)
            rir = parse_float(rir_val)

            records.append(
                {
                    "semana": week_num,
                    "dia": current_day,
                    "fecha": _iso_or_null(dates_per_week.get(week_num)),
                    "set_orden": set_orden,
                    "ejercicio": str(ejercicio).strip(),
                    "reps": reps,
                    "kg": kg,
                    "rir": rir,
                }
            )

    return pd.DataFrame(records)


ALIMENTOS_NUTRIENT_COLUMNS: list[str] = [
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

_ALIMENTOS_HEADER_MAP: dict[str, str | None] = {
    "Alimento": "nombre",
    "Categoría": "categoria",
    "cantidad": None,
    "Calorías (kcal)": "kcal",
    "Carbohidratos (g)": "carbohidratos",
    "Fibra (g)": "fibra",
    "Proteína (g)": "proteina",
    "Grasa (g)": "grasa",
    "Hierro (mg)": "hierro",
    "Calcio (mg)": "calcio",
    "Vitamina C (mg)": "vitamina_c",
    "Vitamina A": "vitamina_a",
}


def parse_alimentos(csv_text: str) -> pd.DataFrame:
    """Parsea la hoja 'alimentos' -> DataFrame con columnas
    [nombre, categoria, kcal, carbohidratos, fibra, proteina, grasa,
    hierro, calcio, vitamina_c, vitamina_a] (valores por 100 g).
    """
    df_raw = pd.read_csv(io.StringIO(csv_text))
    missing = [h for h in _ALIMENTOS_HEADER_MAP if h not in df_raw.columns]
    if missing:
        raise ValueError(f"Encabezados de 'alimentos' faltantes: {missing}")

    records: list[dict] = []
    for _, row in df_raw.iterrows():
        nombre = str(row["Alimento"]).strip()
        if not nombre or nombre == "nan":
            continue
        base = parse_float(row["cantidad"])
        if base is None or base <= 0:
            raise ValueError(f"Alimento '{nombre}': cantidad base {base!r} no válida")
        record: dict = {"nombre": nombre, "categoria": str(row["Categoría"]).strip()}
        for header, field in _ALIMENTOS_HEADER_MAP.items():
            if field not in ALIMENTOS_NUTRIENT_COLUMNS:
                continue
            value = parse_float(row[header])
            if value is None:
                raise ValueError(f"Alimento '{nombre}': nutriente '{header}' no parseable")
            # Normalización a valores por 100 g: la hoja mezcla bases (1 = unidad,
            # 23 = porción); el contrato del catálogo es siempre per-100g.
            record[field] = round(value * 100.0 / base, 2)
        records.append(record)

    return pd.DataFrame(records, columns=["nombre", "categoria", *ALIMENTOS_NUTRIENT_COLUMNS])


DIARIO_COLUMN_ORDER: list[str] = [
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

_DIARIO_LABEL_MAP: dict[str, str] = {
    "Cantidad": "cantidad_g",
    "Calorias": "kcal",
    "Carbohidratos": "carbohidratos",
    "Fibra": "fibra",
    "Proteina": "proteina",
    "Grasa": "grasa",
    "Hierro": "hierro",
    "Calcio": "calcio",
    "Vitamina C": "vitamina_c",
    "Vitamina A": "vitamina_a",
}


def _normalize_label(value) -> str:
    text = str(value).strip()
    text = re.split(r"\s*\(", text)[0].strip()
    accents = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
    }
    return "".join(accents.get(c, c) for c in text)


def _is_date_cell(value) -> bool:
    return bool(re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", str(value).strip()))


def _diario_date_to_iso(value: str) -> str | None:
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date().strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_grams(value) -> float | None:
    if pd.isna(value):
        return None
    match = re.match(r"^\s*([\d]+(?:[.,]\d+)?)\s*[gG]", str(value).strip())
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


@dataclass
class DiarioParse:
    """Resultado del parseo del diario: filas de alimentos + parámetros por fecha."""

    df: pd.DataFrame
    params: list[dict]


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if idx < len(row) else ""


def _block_signature(rows: list, block: dict, header_idx: int) -> tuple:
    """Firma de un bloque para deduplicar días copiados en la hoja.

    Incluye la fila de objetivo y las filas de alimentos (valores ordenados por
    etiqueta, no por posición, para que el orden de columnas no importe).
    """
    target = rows[header_idx + 2] if len(rows) > header_idx + 2 else []
    labels = block["labels"]
    fields = (
        "Calorias",
        "Carbohidratos",
        "Fibra",
        "Proteina",
        "Grasa",
        "Hierro",
        "Calcio",
        "Vitamina C",
        "Vitamina A",
    )
    parts: list = [_cell(target, block["start"] + labels[f]) if f in labels else "" for f in fields]
    food_rows = []
    for row in rows[header_idx + 4 :]:
        alimento = _cell(row, block["start"])
        if not alimento or alimento == "nan":
            continue
        cantidad = _cell(row, block["start"] + labels["Cantidad"]) if "Cantidad" in labels else ""
        nutrients = [_cell(row, block["start"] + labels[f]) if f in labels else "" for f in fields]
        food_rows.append((alimento, cantidad, *nutrients))
    return (block["fecha_iso"], tuple(parts), tuple(food_rows))


def parse_diario(csv_text: str) -> DiarioParse:
    """Parsea la hoja 'diario' -> DiarioParse.

    - `df`: columnas [fecha, orden, alimento, cantidad_g, kcal, carbohidratos,
      fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a].
    - `params`: por fecha única, los objetivos importables de la hoja
      (kcal_objetivo, fibra/hierro/calcio/vitC/vitA objetivo).

    El mapeo de nutrientes se deriva de las etiquetas del encabezado de cada
    bloque. Los bloques con la misma fecha y el mismo contenido (días copiados,
    p. ej. 8/8/2026 ×126) se importan una sola vez. Las filas con alimento pero
    sin cantidad se conservan como placeholder (cantidad_g None, nutrientes 0).
    Las filas truncadas al borde del rango exportado se descartan.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))

    header_idx: int | None = None
    date_cols: list[tuple[int, str]] = []
    for idx in range(min(6, len(rows))):
        row = rows[idx]
        found_dates = [(j, c) for j, c in enumerate(row) if _is_date_cell(c)]
        has_cantidad = any(_normalize_label(c) == "Cantidad" for c in row)
        if found_dates and has_cantidad:
            header_idx = idx
            date_cols = found_dates
            break
    if header_idx is None or not date_cols:
        raise ValueError("No se encontró la fila de encabezados del diario (fechas + Cantidad)")

    header_row = rows[header_idx]
    blocks: list[dict] = []
    for i, (col, raw_date) in enumerate(date_cols):
        end = date_cols[i + 1][0] if i + 1 < len(date_cols) else len(header_row)
        iso = _diario_date_to_iso(raw_date)
        if iso is None:
            raise ValueError(f"Fecha del diario no parseable: {raw_date!r}")
        labels = {_normalize_label(header_row[col + offset]): offset for offset in range(end - col)}
        missing = [lbl for lbl in _DIARIO_LABEL_MAP if lbl not in labels]
        if missing:
            raise ValueError(f"Bloque del diario {raw_date}: etiquetas faltantes {missing}")
        blocks.append({"fecha_iso": iso, "start": col, "end": end, "labels": labels})

    seen_signatures: set[tuple] = set()
    params: list[dict] = []
    for block in blocks:
        sig = _block_signature(rows, block, header_idx)
        if sig in seen_signatures:
            block["skip"] = True
            continue
        seen_signatures.add(sig)
        target = rows[header_idx + 2] if len(rows) > header_idx + 2 else []
        labels = block["labels"]
        if "Calorias" in labels:
            kcal = parse_float(_cell(target, block["start"] + labels["Calorias"]))
            if kcal is not None:
                entry: dict = {"fecha": block["fecha_iso"], "kcal_objetivo": kcal}
                for label, field in (
                    ("Fibra", "fibra_objetivo"),
                    ("Hierro", "hierro_objetivo"),
                    ("Calcio", "calcio_objetivo"),
                    ("Vitamina C", "vitamina_c_objetivo"),
                    ("Vitamina A", "vitamina_a_objetivo"),
                ):
                    entry[field] = (
                        parse_float(_cell(target, block["start"] + labels[label]))
                        if label in labels
                        else 0.0
                    )
                params.append(entry)

    records: list[dict] = []
    order_per_date: dict[str, int] = {}
    for row in rows[header_idx + 1 :]:
        for block in blocks:
            if block.get("skip"):
                continue
            start, end = block["start"], block["end"]
            if start >= len(row):
                continue
            alimento = str(row[start]).strip()
            if not alimento or alimento == "nan":
                continue
            cantidad_idx = start + block["labels"]["Cantidad"]
            cantidad_g = _parse_grams(row[cantidad_idx]) if cantidad_idx < len(row) else None
            max_col = max(start + off for off in block["labels"].values())
            if len(row) <= max_col:
                # Fila truncada al borde del rango exportado: se descarta.
                continue
            record: dict = {
                "fecha": block["fecha_iso"],
                "alimento": alimento,
                "cantidad_g": cantidad_g,
            }
            for label, field in _DIARIO_LABEL_MAP.items():
                col = start + block["labels"][label]
                value = parse_float(row[col]) if col < len(row) else None
                if value is None:
                    # La hoja trata las celdas en blanco como 0 (p. ej. una fila
                    # de Aceite de Oliva sin macros o una kcal olvidada).
                    value = 0.0
                record[field] = value
            if cantidad_g is None or cantidad_g <= 0:
                # Placeholder: alimento sin cantidad, nutrientes en 0.
                record["cantidad_g"] = None
                for field in ALIMENTOS_NUTRIENT_COLUMNS:
                    record[field] = 0.0
            order_per_date[block["fecha_iso"]] = order_per_date.get(block["fecha_iso"], 0) + 1
            record["orden"] = order_per_date[block["fecha_iso"]]
            records.append(record)

    return DiarioParse(
        df=pd.DataFrame(records, columns=DIARIO_COLUMN_ORDER),
        params=params,
    )
