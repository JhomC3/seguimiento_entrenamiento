import os
import sqlite3
from datetime import datetime

import pandas as pd

from config import MUSCLE_CATEGORIES
from src.db_connection import read_connection, transaction
from src.migrations.runner import run_migrations


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    run_migrations(db_path)


def backup_db(db_path: str, *, keep: int = 30) -> str:
    import shutil

    from src.backup_utils import prune_backups

    backups_dir = os.path.join(os.path.dirname(db_path) or ".", "backups")
    os.makedirs(backups_dir, exist_ok=True)
    dest = os.path.join(backups_dir, f"gym-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
    shutil.copy2(db_path, dest)
    prune_backups(backups_dir, keep)
    return dest


def load_ejercicios(db_path: str, df: pd.DataFrame) -> None:
    with transaction(db_path) as conn:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
                (row["grupo_muscular"], row["ejercicio"]),
            )


def load_training_data(db_path: str, df: pd.DataFrame) -> None:
    df = df.copy()
    df["origen"] = "google"
    with transaction(db_path) as conn:
        df.to_sql("training_sets", conn, if_exists="append", index=False)


def get_categories(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT categoria, grupo_muscular FROM ejercicios "
            "WHERE categoria IS NOT NULL AND categoria != '' ORDER BY grupo_muscular"
        ).fetchall()
    by_cat: dict[str, list[str]] = {}
    for cat, muscle in rows:
        by_cat.setdefault(cat, []).append(muscle)
    order = {cat["name"]: idx for idx, cat in enumerate(MUSCLE_CATEGORIES)}
    cats = sorted(by_cat.items(), key=lambda kv: order.get(kv[0], 99))
    return [{"name": name, "muscles": muscles} for name, muscles in cats]


def get_exercises_catalog(db_path: str) -> list[str]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT ejercicio FROM ejercicios ORDER BY ejercicio"
            ).fetchall()
        ]


def insert_exercise(db_path: str, ejercicio: str, grupo_muscular: str, categoria: str) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio, categoria, origen) "
            "VALUES (?, ?, ?, 'manual')",
            (grupo_muscular, ejercicio, categoria),
        )


def get_sets_by_fecha(db_path: str, fecha: str) -> list[dict]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ejercicio, set_orden, reps, kg, rir, origen
            FROM training_sets
            WHERE fecha = ?
            ORDER BY set_orden
        """,
            (fecha,),
        ).fetchall()
    return [
        {
            "ejercicio": r[0],
            "set_orden": r[1],
            "reps": r[2],
            "kg": r[3],
            "rir": r[4],
            "origen": r[5],
        }
        for r in rows
    ]


def delete_session_by_fecha(db_path: str, fecha: str) -> int:
    with transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha,))
        return cur.rowcount


def get_training_sessions(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT semana, dia, fecha,
                   COUNT(DISTINCT ejercicio) AS n_ejercicios,
                   COUNT(*) AS n_series,
                   SUM(CASE WHEN origen = 'manual' THEN 1 ELSE 0 END) AS manual_sets,
                   SUM(CASE WHEN origen = 'google' THEN 1 ELSE 0 END) AS google_sets
            FROM training_sets
            WHERE fecha IS NOT NULL
            GROUP BY semana, dia, fecha
            ORDER BY fecha DESC
        """).fetchall()
    return [
        {
            "semana": r[0],
            "dia": r[1],
            "fecha": r[2],
            "n_ejercicios": r[3],
            "n_series": r[4],
            "manual_sets": r[5] or 0,
            "google_sets": r[6] or 0,
        }
        for r in rows
    ]


def get_session_sets(db_path: str, semana: int, dia: str, fecha: str) -> list[dict]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ejercicio, set_orden, reps, kg, rir, origen
            FROM training_sets
            WHERE semana = ? AND dia = ? AND fecha = ?
            ORDER BY set_orden
        """,
            (semana, dia, fecha),
        ).fetchall()
    return [
        {
            "ejercicio": r[0],
            "set_orden": r[1],
            "reps": r[2],
            "kg": r[3],
            "rir": r[4],
            "origen": r[5],
        }
        for r in rows
    ]


def delete_session(db_path: str, semana: int, dia: str, fecha: str) -> int:
    with transaction(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM training_sets WHERE semana = ? AND dia = ? AND fecha = ?",
            (semana, dia, fecha),
        )
        return cur.rowcount


def _plantilla_sets(conn: sqlite3.Connection, plantilla_id: int) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT ejercicio FROM plantilla_sets WHERE plantilla_id = ? ORDER BY set_orden",
            (plantilla_id,),
        ).fetchall()
    ]


def get_plantillas(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, nombre, clasificacion, updated_at FROM plantillas ORDER BY orden, nombre"
        ).fetchall()
        return [
            {
                "id": r[0],
                "nombre": r[1],
                "clasificacion": r[2],
                "updated_at": r[3],
                "ejercicios": _plantilla_sets(conn, r[0]),
            }
            for r in rows
        ]


def get_plantilla(db_path: str, plantilla_id: int) -> dict | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, nombre, clasificacion, updated_at FROM plantillas WHERE id = ?",
            (plantilla_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "nombre": row[1],
            "clasificacion": row[2],
            "updated_at": row[3],
            "ejercicios": _plantilla_sets(conn, row[0]),
        }


def find_plantilla_by_nombre(db_path: str, nombre: str) -> int | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM plantillas WHERE LOWER(nombre) = LOWER(?)", (nombre,)
        ).fetchone()
        return row[0] if row else None


def insert_plantilla(db_path: str, nombre: str, clasificacion: str, ejercicios: list[str]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        max_row = conn.execute("SELECT COALESCE(MAX(orden), 0) FROM plantillas").fetchone()
        orden = (max_row[0] or 0) + 1
        cur = conn.execute(
            "INSERT INTO plantillas (nombre, clasificacion, created_at, updated_at, orden) "
            "VALUES (?, ?, ?, ?, ?)",
            (nombre, clasificacion, now, now, orden),
        )
        pid = cur.lastrowid
        if pid is None:
            raise RuntimeError("No se pudo crear el entreno.")
        for idx, ej in enumerate(ejercicios, start=1):
            conn.execute(
                "INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (?, ?, ?)",
                (pid, idx, ej),
            )
        return pid


def update_plantilla(
    db_path: str, plantilla_id: int, nombre: str, clasificacion: str, ejercicios: list[str]
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE plantillas SET nombre = ?, clasificacion = ?, updated_at = ? WHERE id = ?",
            (nombre, clasificacion, now, plantilla_id),
        )
        conn.execute("DELETE FROM plantilla_sets WHERE plantilla_id = ?", (plantilla_id,))
        for idx, ej in enumerate(ejercicios, start=1):
            conn.execute(
                "INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (?, ?, ?)",
                (plantilla_id, idx, ej),
            )


def delete_plantilla(db_path: str, plantilla_id: int) -> None:
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM plantilla_sets WHERE plantilla_id = ?", (plantilla_id,))
        conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))


def reorder_plantillas(db_path: str, ordered_ids: list[int]) -> None:
    with transaction(db_path) as conn:
        for pos, pid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE plantillas SET orden = ? WHERE id = ?", (pos, pid))


def snapshot_entrenos(db_path: str) -> list:
    with read_connection(db_path) as conn:
        plantillas = conn.execute(
            "SELECT id, nombre, clasificacion, created_at, updated_at, orden FROM plantillas ORDER BY id"
        ).fetchall()
        sets = conn.execute(
            "SELECT plantilla_id, set_orden, ejercicio FROM plantilla_sets ORDER BY plantilla_id, set_orden"
        ).fetchall()
    return [plantillas, sets]


def restore_entrenos(db_path: str, snapshot: list) -> None:
    plantillas, sets = snapshot[0], snapshot[1]
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM plantilla_sets")
        conn.execute("DELETE FROM plantillas")
        for r in plantillas:
            conn.execute(
                "INSERT INTO plantillas (id, nombre, clasificacion, created_at, updated_at, orden) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r[0], r[1], r[2], r[3], r[4], r[5]),
            )
        for r in sets:
            conn.execute(
                "INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (?, ?, ?)",
                (r[0], r[1], r[2]),
            )
        max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM plantillas").fetchone()[0]
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'plantillas'", (max_id,))


def get_ejercicio_categoria(db_path: str) -> dict[str, str]:
    if not os.path.exists(db_path):
        return {}
    with read_connection(db_path) as conn:
        return {
            str(r[0]).strip().lower(): (r[1] or "").upper()
            for r in conn.execute(
                "SELECT ejercicio, categoria FROM ejercicios WHERE categoria IS NOT NULL AND categoria != ''"
            )
        }


def get_last_session_sets(db_path: str, ejercicio: str) -> list[dict]:
    with read_connection(db_path) as conn:
        latest = conn.execute(
            "SELECT fecha FROM training_sets WHERE LOWER(ejercicio) = LOWER(?) "
            "AND fecha IS NOT NULL ORDER BY fecha DESC LIMIT 1",
            (ejercicio,),
        ).fetchone()
        if latest is None:
            return []
        set_rows = conn.execute(
            "SELECT ejercicio, set_orden, reps, kg, rir FROM training_sets "
            "WHERE LOWER(ejercicio) = LOWER(?) AND fecha = ? ORDER BY set_orden",
            (ejercicio, latest[0]),
        ).fetchall()
    return [
        {"ejercicio": r[0], "set_orden": r[1], "reps": r[2], "kg": r[3], "rir": r[4]}
        for r in set_rows
    ]
