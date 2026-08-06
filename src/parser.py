import io

import pandas as pd


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
                    "fecha": dates_per_week.get(week_num),
                    "set_orden": set_orden,
                    "ejercicio": str(ejercicio).strip(),
                    "reps": reps,
                    "kg": kg,
                    "rir": rir,
                }
            )

    return pd.DataFrame(records)
