import os
import sqlite3
from datetime import datetime

import pandas as pd

from config import MUSCLE_CATEGORIES

def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

def _backfill_categories(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, grupo_muscular FROM ejercicios WHERE categoria IS NULL").fetchall()
    if not rows:
        return
    muscle_to_cat = {}
    for cat in MUSCLE_CATEGORIES:
        for muscle in cat["muscles"]:
            muscle_to_cat[muscle.strip().lower()] = cat["name"]
    for row_id, grupo in rows:
        cat = muscle_to_cat.get(str(grupo).strip().lower())
        if cat:
            conn.execute("UPDATE ejercicios SET categoria = ? WHERE id = ?", (cat, row_id))

def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ejercicios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grupo_muscular TEXT NOT NULL,
                ejercicio TEXT NOT NULL UNIQUE,
                categoria TEXT,
                origen TEXT NOT NULL DEFAULT 'google'
            );
            CREATE TABLE IF NOT EXISTS training_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                semana INTEGER NOT NULL,
                dia TEXT NOT NULL,
                fecha TEXT,
                set_orden INTEGER NOT NULL,
                ejercicio TEXT NOT NULL,
                reps REAL,
                kg REAL,
                rir REAL,
                origen TEXT NOT NULL DEFAULT 'google'
            );
            CREATE INDEX IF NOT EXISTS idx_training_semana ON training_sets(semana);
            CREATE INDEX IF NOT EXISTS idx_training_ejercicio ON training_sets(ejercicio);
            CREATE TABLE IF NOT EXISTS plantillas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                clasificacion TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS plantilla_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plantilla_id INTEGER NOT NULL,
                set_orden INTEGER NOT NULL,
                ejercicio TEXT NOT NULL,
                FOREIGN KEY (plantilla_id) REFERENCES plantillas(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_plantilla_sets ON plantilla_sets(plantilla_id);
        """)
        conn.commit()
        if "origen" not in _table_columns(conn, "training_sets"):
            conn.execute("ALTER TABLE training_sets ADD COLUMN origen TEXT NOT NULL DEFAULT 'google'")
        ejercicios_cols = _table_columns(conn, "ejercicios")
        if "categoria" not in ejercicios_cols:
            conn.execute("ALTER TABLE ejercicios ADD COLUMN categoria TEXT")
        if "origen" not in ejercicios_cols:
            conn.execute("ALTER TABLE ejercicios ADD COLUMN origen TEXT NOT NULL DEFAULT 'google'")
        plantillas_cols = _table_columns(conn, "plantillas")
        if "orden" not in plantillas_cols:
            conn.execute("ALTER TABLE plantillas ADD COLUMN orden INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        _backfill_categories(conn)
        conn.commit()
    finally:
        conn.close()

def backup_db(db_path: str) -> str:
    import shutil
    backups_dir = os.path.join(os.path.dirname(db_path) or ".", "backups")
    os.makedirs(backups_dir, exist_ok=True)
    dest = os.path.join(backups_dir, f"gym-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
    shutil.copy2(db_path, dest)
    return dest

def load_ejercicios(db_path: str, df: pd.DataFrame) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
                (row["grupo_muscular"], row["ejercicio"]),
            )
        conn.commit()
    finally:
        conn.close()

def load_training_data(db_path: str, df: pd.DataFrame) -> None:
    df = df.copy()
    df["origen"] = "google"
    conn = sqlite3.connect(db_path)
    try:
        df.to_sql("training_sets", conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()

def get_categories(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT categoria, grupo_muscular FROM ejercicios "
            "WHERE categoria IS NOT NULL AND categoria != '' ORDER BY grupo_muscular"
        ).fetchall()
    finally:
        conn.close()
    by_cat: dict[str, list[str]] = {}
    for cat, muscle in rows:
        by_cat.setdefault(cat, []).append(muscle)
    order = {cat["name"]: idx for idx, cat in enumerate(MUSCLE_CATEGORIES)}
    cats = sorted(by_cat.items(), key=lambda kv: order.get(kv[0], 99))
    return [{"name": name, "muscles": muscles} for name, muscles in cats]

def get_exercises_catalog(db_path: str) -> list[str]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT ejercicio FROM ejercicios ORDER BY ejercicio"
        ).fetchall()]
    finally:
        conn.close()

def insert_exercise(db_path: str, ejercicio: str, grupo_muscular: str, categoria: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio, categoria, origen) "
            "VALUES (?, ?, ?, 'manual')",
            (grupo_muscular, ejercicio, categoria),
        )
        conn.commit()
    finally:
        conn.close()

def _parse_fecha(fecha: str) -> datetime:
    return datetime.strptime(fecha, "%d/%m/%y")

def get_sets_by_fecha(db_path: str, fecha: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT ejercicio, set_orden, reps, kg, rir, origen
            FROM training_sets
            WHERE fecha = ?
            ORDER BY set_orden
        """, (fecha,)).fetchall()
    finally:
        conn.close()
    return [
        {"ejercicio": r[0], "set_orden": r[1], "reps": r[2], "kg": r[3], "rir": r[4], "origen": r[5]}
        for r in rows
    ]

def delete_session_by_fecha(db_path: str, fecha: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha,))
        return cur.rowcount
    finally:
        conn.close()

def get_training_sessions(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT semana, dia, fecha,
                   COUNT(DISTINCT ejercicio) AS n_ejercicios,
                   COUNT(*) AS n_series,
                   SUM(CASE WHEN origen = 'manual' THEN 1 ELSE 0 END) AS manual_sets,
                   SUM(CASE WHEN origen = 'google' THEN 1 ELSE 0 END) AS google_sets
            FROM training_sets
            GROUP BY semana, dia, fecha
        """).fetchall()
    finally:
        conn.close()
    sessions = []
    for r in rows:
        try:
            fecha_dt = _parse_fecha(r[2])
        except ValueError:
            continue
        sessions.append({
            "semana": r[0],
            "dia": r[1],
            "fecha": r[2],
            "fecha_dt": fecha_dt,
            "n_ejercicios": r[3],
            "n_series": r[4],
            "manual_sets": r[5] or 0,
            "google_sets": r[6] or 0,
        })
    sessions.sort(key=lambda s: s["fecha_dt"], reverse=True)
    return sessions

def get_session_sets(db_path: str, semana: int, dia: str, fecha: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT ejercicio, set_orden, reps, kg, rir, origen
            FROM training_sets
            WHERE semana = ? AND dia = ? AND fecha = ?
            ORDER BY set_orden
        """, (semana, dia, fecha)).fetchall()
    finally:
        conn.close()
    return [
        {"ejercicio": r[0], "set_orden": r[1], "reps": r[2], "kg": r[3], "rir": r[4], "origen": r[5]}
        for r in rows
    ]

def delete_session(db_path: str, semana: int, dia: str, fecha: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM training_sets WHERE semana = ? AND dia = ? AND fecha = ?",
                (semana, dia, fecha),
            )
        return cur.rowcount
    finally:
        conn.close()

def _plantilla_sets(conn: sqlite3.Connection, plantilla_id: int) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT ejercicio FROM plantilla_sets WHERE plantilla_id = ? ORDER BY set_orden",
        (plantilla_id,),
    ).fetchall()]

def get_plantillas(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
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
    finally:
        conn.close()

def get_plantilla(db_path: str, plantilla_id: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
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
    finally:
        conn.close()

def find_plantilla_by_nombre(db_path: str, nombre: str) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM plantillas WHERE LOWER(nombre) = LOWER(?)", (nombre,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def insert_plantilla(db_path: str, nombre: str, clasificacion: str, ejercicios: list[str]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            max_row = conn.execute("SELECT COALESCE(MAX(orden), 0) FROM plantillas").fetchone()
            orden = (max_row[0] or 0) + 1
            cur = conn.execute(
                "INSERT INTO plantillas (nombre, clasificacion, created_at, updated_at, orden) "
                "VALUES (?, ?, ?, ?, ?)",
                (nombre, clasificacion, now, now, orden),
            )
            pid = cur.lastrowid
            for idx, ej in enumerate(ejercicios, start=1):
                conn.execute(
                    "INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (?, ?, ?)",
                    (pid, idx, ej),
                )
        return pid
    finally:
        conn.close()

def update_plantilla(db_path: str, plantilla_id: int, nombre: str, clasificacion: str, ejercicios: list[str]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
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
    finally:
        conn.close()

def delete_plantilla(db_path: str, plantilla_id: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM plantilla_sets WHERE plantilla_id = ?", (plantilla_id,))
            conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))
    finally:
        conn.close()

def reorder_plantillas(db_path: str, ordered_ids: list[int]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for pos, pid in enumerate(ordered_ids, start=1):
                conn.execute("UPDATE plantillas SET orden = ? WHERE id = ?", (pos, pid))
    finally:
        conn.close()

def snapshot_entrenos(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        plantillas = conn.execute(
            "SELECT id, nombre, clasificacion, created_at, updated_at, orden FROM plantillas ORDER BY id"
        ).fetchall()
        sets = conn.execute(
            "SELECT plantilla_id, set_orden, ejercicio FROM plantilla_sets ORDER BY plantilla_id, set_orden"
        ).fetchall()
    finally:
        conn.close()
    return [plantillas, sets]

def restore_entrenos(db_path: str, snapshot: list) -> None:
    plantillas, sets = snapshot[0], snapshot[1]
    conn = sqlite3.connect(db_path)
    try:
        with conn:
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
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = 'plantillas'", (max_id,)
            )
    finally:
        conn.close()

def get_ejercicio_categoria(db_path: str) -> dict[str, str]:
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path)
    try:
        return {
            str(r[0]).strip().lower(): (r[1] or "").upper()
            for r in conn.execute("SELECT ejercicio, categoria FROM ejercicios WHERE categoria IS NOT NULL AND categoria != ''")
        }
    finally:
        conn.close()

def get_last_session_sets(db_path: str, ejercicio: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT fecha FROM training_sets WHERE LOWER(ejercicio) = LOWER(?) AND fecha IS NOT NULL",
            (ejercicio,),
        ).fetchall()
    finally:
        conn.close()
    latest: str | None = None
    latest_dt = None
    for (f,) in rows:
        try:
            dt = _parse_fecha(f)
        except ValueError:
            continue
        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
            latest = f
    if latest is None:
        return []
    conn = sqlite3.connect(db_path)
    try:
        set_rows = conn.execute(
            "SELECT ejercicio, set_orden, reps, kg, rir FROM training_sets "
            "WHERE LOWER(ejercicio) = LOWER(?) AND fecha = ? ORDER BY set_orden",
            (ejercicio, latest),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"ejercicio": r[0], "set_orden": r[1], "reps": r[2], "kg": r[3], "rir": r[4]}
        for r in set_rows
    ]
