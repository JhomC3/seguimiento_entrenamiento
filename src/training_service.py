import sqlite3
from datetime import date, datetime

from config import CICLO_START
from src.database import get_exercises_catalog, get_session_sets, get_training_sessions

DIA_MAP = {
    "Monday": "LUNES",
    "Tuesday": "MARTES",
    "Wednesday": "MIERCOLES",
    "Thursday": "JUEVES",
    "Friday": "VIERNES",
    "Saturday": "SABADO",
    "Sunday": "DOMINGO",
}

def parse_cycle_start(value: str = CICLO_START) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()

def calculate_cycle_week(fecha: date, cycle_start: date) -> int:
    return max(1, (fecha - cycle_start).days // 7 + 1)

def day_from_date(fecha: date) -> str:
    return DIA_MAP[fecha.strftime("%A")]

def fecha_to_db(fecha: date) -> str:
    return f"{fecha.day}/{fecha.month}/{fecha.year % 100:02d}"

def fecha_from_db(fecha: str) -> date:
    return datetime.strptime(fecha, "%d/%m/%y").date()

def parse_form_date(fecha_iso: str) -> date:
    return datetime.strptime(fecha_iso, "%Y-%m-%d").date()

def _validate_number(value, field: str, allow_none: bool = False) -> float | None:
    if value is None or str(value).strip() == "":
        if allow_none:
            return None
        raise ValueError(f"El campo {field} es obligatorio.")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"El campo {field} debe ser numérico.")
    if num <= 0 or num != num or num in (float("inf"), float("-inf")):
        raise ValueError(f"El campo {field} debe ser un número positivo.")
    return num

def validate_sets(db_path: str, sets: list[dict]) -> list[dict]:
    if not sets:
        raise ValueError("Debes registrar al menos una serie.")
    catalog = {name.lower() for name in get_exercises_catalog(db_path)}
    cleaned = []
    for raw in sets:
        ejercicio = str(raw.get("ejercicio", "")).strip()
        if not ejercicio:
            raise ValueError("Debes seleccionar un ejercicio.")
        if ejercicio.lower() not in catalog:
            raise ValueError(f"El ejercicio '{ejercicio}' no existe en el catálogo.")
        kg = _validate_number(raw.get("kg"), "peso (kg)")
        reps = _validate_number(raw.get("reps"), "repeticiones")
        rir = _validate_number(raw.get("rir"), "RIR", allow_none=True)
        if rir is not None and rir < 0:
            raise ValueError("El RIR no puede ser negativo.")
        cleaned.append({
            "ejercicio": ejercicio,
            "kg": kg,
            "reps": reps,
            "rir": rir,
        })
    return cleaned

def _insert_sets(conn: sqlite3.Connection, semana: int, dia: str, fecha: str, sets: list[dict]) -> None:
    for idx, s in enumerate(sets, start=1):
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
            (semana, dia, fecha, idx, s["ejercicio"], s["reps"], s["kg"], s["rir"]),
        )

def insert_manual_session(db_path: str, fecha_iso: str, sets: list[dict]) -> dict:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, sets)
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            _insert_sets(conn, semana, dia, fecha_db, cleaned)
    finally:
        conn.close()
    return {"semana": semana, "dia": dia, "fecha": fecha_db}

def update_session(db_path: str, old_semana: int, old_dia: str, old_fecha: str, fecha_iso: str, sets: list[dict]) -> dict:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, sets)
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "DELETE FROM training_sets WHERE semana = ? AND dia = ? AND fecha = ?",
                (old_semana, old_dia, old_fecha),
            )
            _insert_sets(conn, semana, dia, fecha_db, cleaned)
    finally:
        conn.close()
    return {"semana": semana, "dia": dia, "fecha": fecha_db}

def save_session(db_path: str, fecha_iso: str, sets: list[dict]) -> dict:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, sets) if sets else []
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha_db,))
            for idx, s in enumerate(cleaned, start=1):
                conn.execute(
                    "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
                    (semana, dia, fecha_db, idx, s["ejercicio"], s["reps"], s["kg"], s["rir"]),
                )
    finally:
        conn.close()
    return {"semana": semana, "dia": dia, "fecha": fecha_db}

def get_sessions_page(db_path: str, page: int = 1, limit: int = 20) -> tuple[list[dict], int, int]:
    sessions = get_training_sessions(db_path)
    total = len(sessions)
    offset = (page - 1) * limit
    return sessions[offset:offset + limit], total, page

def get_session_detail(db_path: str, semana: int, dia: str, fecha: str) -> list[dict]:
    sets = get_session_sets(db_path, semana, dia, fecha)
    for s in sets:
        kg = s["kg"]
        reps = s["reps"]
        rir = s["rir"] or 0
        s["rm"] = round(kg * (1 + 0.0333 * reps), 1) if kg and reps else None
        s["rm_ajustado"] = round(kg * (1 + 0.0333 * (reps + 1 + rir)), 1) if kg and reps else None
    return sets
