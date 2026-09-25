"""Persistencia de bienestar: sesiones de respiracion (spec 006)."""

from datetime import datetime

from src.db_connection import read_connection, transaction

_BREATHING_COLUMNS = (
    "client_session_id",
    "fecha",
    "start_epoch_ms",
    "end_epoch_ms",
    "time_zone_offset_minutes",
    "duracion_planeada_sec",
    "duracion_real_sec",
    "inhale_s",
    "hold_in_s",
    "exhale_s",
    "hold_out_s",
    "ramp_sec",
    "end_inhale_s",
    "end_hold_in_s",
    "end_exhale_s",
    "end_hold_out_s",
    "ciclos_completados",
    "bpm_medio",
    "completada",
    "origen",
    "created_at",
)


def insert_breathing_session(db_path: str, row: dict) -> int:
    """Inserta una sesión de respiración (B5.0). Duplicado → IntegrityError."""
    values = dict(row)
    values["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = ", ".join(_BREATHING_COLUMNS)
    placeholders = ", ".join("?" for _ in _BREATHING_COLUMNS)
    with transaction(db_path) as conn:
        cur = conn.execute(
            f"INSERT INTO breathing_sessions ({cols}) VALUES ({placeholders})",
            tuple(values[c] for c in _BREATHING_COLUMNS),
        )
        row_id = cur.lastrowid
        if row_id is None:
            raise RuntimeError("No se pudo guardar la sesión de respiración.")
        return row_id


def find_breathing_session(db_path: str, client_session_id: str) -> dict | None:
    with read_connection(db_path) as conn:
        r = conn.execute(
            f"SELECT {', '.join(_BREATHING_COLUMNS)} FROM breathing_sessions "
            "WHERE client_session_id = ?",
            (client_session_id,),
        ).fetchone()
    return dict(r) if r is not None else None


def get_breathing_sessions_by_fecha(db_path: str, fecha: str) -> list[dict]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_BREATHING_COLUMNS)} FROM breathing_sessions "
            "WHERE fecha = ? ORDER BY start_epoch_ms",
            (fecha,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_breathing_session(db_path: str, client_session_id: str) -> int:
    with transaction(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM breathing_sessions WHERE client_session_id = ?",
            (client_session_id,),
        )
        return cur.rowcount
