import math
import sqlite3
from datetime import date, datetime, timedelta

from config import CICLO_START
from src.database import get_exercises_catalog, get_session_sets, get_training_sessions
from src.db_connection import transaction
from src.models import Session, TrainingSet, TrainingSetInput, ValidationError

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
    """Semana del ciclo con semanas alineadas a lunes-domingo.

    La semana 1 es la semana calendario (lun-dom) que contiene el inicio del
    ciclo; las fechas anteriores al inicio se truncan a la semana 1.
    """
    monday = cycle_start - timedelta(days=cycle_start.weekday())
    return max(1, (fecha - monday).days // 7 + 1)


def day_from_date(fecha: date) -> str:
    return DIA_MAP[fecha.strftime("%A")]


def fecha_to_db(fecha: date) -> str:
    return f"{fecha.day}/{fecha.month}/{fecha.year % 100:02d}"


def fecha_from_db(fecha: str) -> date:
    return datetime.strptime(fecha, "%d/%m/%y").date()


def parse_form_date(fecha_iso: str) -> date:
    try:
        return datetime.strptime(fecha_iso, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"Fecha inválida: '{fecha_iso}'.")


def _validate_number(value, field: str, *, allow_zero: bool = False) -> float:
    if value is None or str(value).strip() == "":
        raise ValidationError(f"El campo {field} es obligatorio.")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"El campo {field} debe ser numérico.")
    if (
        math.isnan(num)
        or num in (float("inf"), float("-inf"))
        or num < 0
        or (num == 0 and not allow_zero)
    ):
        raise ValidationError(f"El campo {field} debe ser un número positivo.")
    return num


def sets_from_form(
    ejercicios: list[str], kgs: list[str], reps: list[str], rirs: list[str]
) -> list[TrainingSetInput]:
    """Adapter: parallel form arrays -> typed set inputs."""
    sets = []
    for i, ejercicio in enumerate(ejercicios):
        sets.append(
            TrainingSetInput(
                ejercicio=ejercicio,
                kg=kgs[i] if i < len(kgs) else "",
                reps=reps[i] if i < len(reps) else "",
                rir=rirs[i] if i < len(rirs) else "",
            )
        )
    return sets


def _coerce_set(raw) -> TrainingSetInput:
    """Internal adapter: accepts TrainingSetInput or dict rows (undo stack, DB rows)."""
    if isinstance(raw, TrainingSetInput):
        return raw
    if isinstance(raw, dict):
        return TrainingSetInput(
            ejercicio=str(raw.get("ejercicio", "")),
            kg=raw.get("kg", ""),
            reps=raw.get("reps", ""),
            rir=raw.get("rir", ""),
        )
    raise ValidationError("Serie inválida.")


def validate_sets(db_path: str, sets: list[TrainingSetInput]) -> list[TrainingSetInput]:
    if not sets:
        raise ValidationError("Debes registrar al menos una serie.")
    catalog = {name.lower() for name in get_exercises_catalog(db_path)}
    cleaned = []
    for raw in sets:
        raw = _coerce_set(raw)
        ejercicio = str(raw.ejercicio).strip()
        if not ejercicio:
            raise ValidationError("Debes seleccionar un ejercicio.")
        if ejercicio.lower() not in catalog:
            raise ValidationError(f"El ejercicio '{ejercicio}' no existe en el catálogo.")
        kg = _validate_number(raw.kg, "peso (kg)")
        reps = _validate_number(raw.reps, "repeticiones")
        rir = _validate_number(raw.rir, "RIR", allow_zero=True)
        cleaned.append(TrainingSetInput(ejercicio=ejercicio, kg=kg, reps=reps, rir=rir))
    return cleaned


def _insert_sets(
    conn: sqlite3.Connection, semana: int, dia: str, fecha: str, sets: list[TrainingSetInput]
) -> None:
    for idx, s in enumerate(sets, start=1):
        conn.execute(
            "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
            (semana, dia, fecha, idx, s.ejercicio, s.reps, s.kg, s.rir),
        )


def _session_from_meta(semana: int, dia: str, fecha_db: str) -> Session:
    return Session(semana=semana, dia=dia, fecha=fecha_db)


def insert_manual_session(db_path: str, fecha_iso: str, sets: list[TrainingSetInput]) -> Session:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, sets)
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    with transaction(db_path) as conn:
        _insert_sets(conn, semana, dia, fecha_db, cleaned)
    return _session_from_meta(semana, dia, fecha_db)


def update_session(
    db_path: str,
    old_semana: int,
    old_dia: str,
    old_fecha: str,
    fecha_iso: str,
    sets: list[TrainingSetInput],
) -> Session:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, sets)
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    with transaction(db_path) as conn:
        conn.execute(
            "DELETE FROM training_sets WHERE semana = ? AND dia = ? AND fecha = ?",
            (old_semana, old_dia, old_fecha),
        )
        _insert_sets(conn, semana, dia, fecha_db, cleaned)
    return _session_from_meta(semana, dia, fecha_db)


def _is_empty_row(s) -> bool:
    s = _coerce_set(s)
    return not any(str(getattr(s, k, "")).strip() for k in ("ejercicio", "kg", "reps", "rir"))


def save_session(db_path: str, fecha_iso: str, sets: list[TrainingSetInput]) -> Session:
    fecha = parse_form_date(fecha_iso)
    cycle_start = parse_cycle_start()
    cleaned = validate_sets(db_path, [s for s in sets if not _is_empty_row(s)]) if sets else []
    semana = calculate_cycle_week(fecha, cycle_start)
    dia = day_from_date(fecha)
    fecha_db = fecha_to_db(fecha)
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha_db,))
        for idx, s in enumerate(cleaned, start=1):
            conn.execute(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
                (semana, dia, fecha_db, idx, s.ejercicio, s.reps, s.kg, s.rir),
            )
    return _session_from_meta(semana, dia, fecha_db)


def get_sessions_page(db_path: str, page: int = 1, limit: int = 20) -> tuple[list[dict], int, int]:
    sessions = get_training_sessions(db_path)
    total = len(sessions)
    offset = (page - 1) * limit
    return sessions[offset : offset + limit], total, page


def get_session_detail(db_path: str, semana: int, dia: str, fecha: str) -> list[TrainingSet]:
    sets = get_session_sets(db_path, semana, dia, fecha)
    result = []
    for s in sets:
        kg = s["kg"]
        reps = s["reps"]
        s["rir"] or 0
        round(kg * (1 + 0.0333 * reps), 1) if kg and reps else None
        result.append(
            TrainingSet(
                ejercicio=s["ejercicio"],
                set_orden=s["set_orden"],
                reps=s["reps"],
                kg=s["kg"],
                rir=s["rir"],
                origen=s["origen"],
            )
        )
    return result
