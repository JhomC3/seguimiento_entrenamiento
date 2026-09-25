"""Persistencia de entrenamiento: catalogo, sets y plantillas (spec 006)."""

import os
import sqlite3
from datetime import datetime

import pandas as pd

from config import MUSCLE_CATEGORIES
from src.db_common import _resync_sequence
from src.db_connection import read_connection, transaction
from src.migrations.runner import run_migrations


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    run_migrations(db_path)


def backup_db(db_path: str, *, keep: int = 30) -> str:
    from src.backup_utils import copy_db, prune_backups

    backups_dir = os.path.join(os.path.dirname(db_path) or ".", "backups")
    os.makedirs(backups_dir, exist_ok=True)
    dest = os.path.join(backups_dir, f"lifestyle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
    copy_db(db_path, dest)
    prune_backups(backups_dir, keep)
    return dest


def load_ejercicios(db_path: str, df: pd.DataFrame) -> None:
    """Test-support API: seed de ejercicios desde un DataFrame (tests de charts/DB)."""
    with transaction(db_path) as conn:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
                (row["grupo_muscular"], row["ejercicio"]),
            )


def load_training_data(db_path: str, df: pd.DataFrame) -> None:
    """Test-support API: seed de training_sets desde un DataFrame (tests de charts/DB)."""
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


def get_exercise_valid_counts(
    db_path: str, fecha_min: str | None = None, fecha_max: str | None = None
) -> dict[str, int]:
    """Cuenta series válidas (kg y reps no nulos) por ejercicio, opcionalmente acotado a ventana.

    Usado por el orden dinámico compartido entre catálogo y panel.
    """
    if not os.path.exists(db_path):
        return {}
    clauses = ["kg IS NOT NULL", "reps IS NOT NULL"]
    params: list[str] = []
    if fecha_min is not None:
        clauses.append("fecha >= ?")
        params.append(fecha_min)
    if fecha_max is not None:
        clauses.append("fecha <= ?")
        params.append(fecha_max)
    with read_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT ejercicio, COUNT(*) FROM training_sets WHERE {' AND '.join(clauses)} GROUP BY ejercicio",
            params,
        ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def sort_exercises_by_data(counts: dict[str, int], catalog_order: list[str]) -> list[str]:
    """Ordena ejercicios por datos válidos DESC, desempate estable por catálogo.

    Más datos primero, cero al final, empate por orden original del catálogo.
    Función pura compartida entre catálogo y panel.
    """
    order_index = {name: idx for idx, name in enumerate(catalog_order)}
    all_names = set(catalog_order) | set(counts.keys())
    return sorted(all_names, key=lambda n: (-counts.get(n, 0), order_index.get(n, 999), n.lower()))


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
            SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg, velocidad_kmh,
                   dificultad, origen
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
            "descanso_seg": r[5],
            "velocidad_kmh": r[6],
            "dificultad": r[7],
            "origen": r[8],
        }
        for r in rows
    ]


def get_daily_data_dates(db_path: str, vista: str | None = None) -> set[str]:
    """Días con datos de registro para el navegador del Diario (variant="daily").

    ``vista="entrenamiento"``: solo ``training_sets``.
    ``vista="alimentacion"``: solo ``diario_alimentacion``.
    Cualquier otro valor (incluido ``None``): unión de ambos (compatibilidad).
    El Dashboard sigue usando ``fechas_con_datos`` (solo entrenamiento).
    """
    if vista == "entrenamiento":
        sql = "SELECT DISTINCT fecha FROM training_sets WHERE fecha IS NOT NULL"
    elif vista == "alimentacion":
        sql = "SELECT DISTINCT fecha FROM diario_alimentacion WHERE fecha IS NOT NULL"
    else:
        sql = (
            "SELECT DISTINCT fecha FROM training_sets WHERE fecha IS NOT NULL "
            "UNION "
            "SELECT DISTINCT fecha FROM diario_alimentacion WHERE fecha IS NOT NULL"
        )
    with read_connection(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return {str(r[0]) for r in rows}


def get_sets_for_window(
    db_path: str,
    fecha_min: str | None,
    fecha_max: str | None,
    ejercicios: list[str],
) -> list[dict]:
    """Batch para acordeón Día+ejercicio: series dentro de ventana, sin filtrar kg/reps nulos.

    Solo excluye filas sin fecha/ejercicio estructuralmente inexistentes.
    Mostrará '—' si falta valor; no filtra por kg/reps/rir NULL.
    """
    if not ejercicios:
        return []
    clauses = ["fecha IS NOT NULL", "ejercicio IS NOT NULL", "ejercicio != ''"]
    params: list[str] = []
    if fecha_min is not None:
        clauses.append("fecha >= ?")
        params.append(fecha_min)
    if fecha_max is not None:
        clauses.append("fecha <= ?")
        params.append(fecha_max)
    uniq = list(dict.fromkeys(e.strip() for e in ejercicios if e.strip()))
    if not uniq:
        return []
    placeholders = ",".join("?" for _ in uniq)
    clauses.append(f"LOWER(ejercicio) IN ({placeholders})")
    params.extend(e.lower() for e in uniq)
    with read_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT fecha, ejercicio, set_orden, reps, kg, rir, descanso_seg, velocidad_kmh, dificultad "
            f"FROM training_sets WHERE {' AND '.join(clauses)} "
            f"ORDER BY fecha DESC, ejercicio, set_orden",
            params,
        ).fetchall()
    return [
        {
            "fecha": r[0],
            "ejercicio": r[1],
            "set_orden": r[2],
            "reps": r[3],
            "kg": r[4],
            "rir": r[5],
            "descanso_seg": r[6],
            "velocidad_kmh": r[7],
            "dificultad": r[8],
        }
        for r in rows
    ]


def delete_session_by_fecha(db_path: str, fecha: str) -> int:
    with transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM training_sets WHERE fecha = ?", (fecha,))
        return cur.rowcount


def get_session_sets(db_path: str, semana: int, dia: str, fecha: str) -> list[dict]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg, velocidad_kmh,
                   dificultad, origen
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
            "descanso_seg": r[5],
            "velocidad_kmh": r[6],
            "dificultad": r[7],
            "origen": r[8],
        }
        for r in rows
    ]


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
        sets_rows = conn.execute(
            "SELECT plantilla_id, set_orden, ejercicio FROM plantilla_sets "
            "ORDER BY plantilla_id, set_orden"
        ).fetchall()
    by_id: dict[int, dict] = {}
    for r in rows:
        by_id[r[0]] = {
            "id": r[0],
            "nombre": r[1],
            "clasificacion": r[2],
            "updated_at": r[3],
            "ejercicios": [],
        }
    for pid, _ord, ejercicio in sets_rows:
        if pid in by_id:
            by_id[pid]["ejercicios"].append(ejercicio)
    return list(by_id.values())


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

    def val(r, idx: int, key: str):
        """Fila sqlite3.Row (legado en memoria) o dict (journal persistido)."""
        return r[key] if isinstance(r, dict) else r[idx]

    with transaction(db_path) as conn:
        conn.execute("DELETE FROM plantilla_sets")
        conn.execute("DELETE FROM plantillas")
        for r in plantillas:
            conn.execute(
                "INSERT INTO plantillas (id, nombre, clasificacion, created_at, updated_at, orden) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                tuple(
                    val(r, i, k)
                    for i, k in enumerate(
                        ("id", "nombre", "clasificacion", "created_at", "updated_at", "orden")
                    )
                ),
            )
        for r in sets:
            conn.execute(
                "INSERT INTO plantilla_sets (plantilla_id, set_orden, ejercicio) VALUES (?, ?, ?)",
                tuple(
                    val(r, i, k) for i, k in enumerate(("plantilla_id", "set_orden", "ejercicio"))
                ),
            )
        _resync_sequence(conn, "plantillas")


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


def get_last_exercise_series(db_path: str, ejercicio: str, before_fecha: str | None = None) -> dict:
    """Últimas series de un ejercicio con ordinal propio (1..M).

    El ordinal es posicional por ejercicio: ignora en qué posición global
    (set_orden) quedó ese día entre otros ejercicios. Si `before_fecha`
    se pasa (YYYY-MM-DD), solo mira fechas estrictamente anteriores
    (evita eco del propio día y filtraciones de futuro al sugerir pasado).
    Devuelve {"fuente_fecha": str|None, "series": [...]}, series ordenadas
    por set_orden con "pos" 1-indexed.
    """
    name = str(ejercicio or "").strip()
    if not name:
        return {"fuente_fecha": None, "series": []}
    with read_connection(db_path) as conn:
        if before_fecha is not None:
            latest = conn.execute(
                "SELECT fecha FROM training_sets WHERE LOWER(ejercicio) = LOWER(?) "
                "AND fecha IS NOT NULL AND fecha < ? ORDER BY fecha DESC LIMIT 1",
                (name, str(before_fecha)),
            ).fetchone()
        else:
            latest = conn.execute(
                "SELECT fecha FROM training_sets WHERE LOWER(ejercicio) = LOWER(?) "
                "AND fecha IS NOT NULL ORDER BY fecha DESC LIMIT 1",
                (name,),
            ).fetchone()
        if latest is None:
            return {"fuente_fecha": None, "series": []}
        fuente = str(latest[0])
        set_rows = conn.execute(
            "SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg, velocidad_kmh, dificultad FROM training_sets "
            "WHERE LOWER(ejercicio) = LOWER(?) AND fecha = ? ORDER BY set_orden",
            (name, fuente),
        ).fetchall()
    series = [
        {
            "ejercicio": r[0],
            "set_orden": r[1],
            "pos": i + 1,
            "reps": r[2],
            "kg": r[3],
            "rir": r[4],
            "descanso_seg": r[5],
            "velocidad_kmh": r[6],
            "dificultad": r[7],
        }
        for i, r in enumerate(set_rows)
    ]
    return {"fuente_fecha": fuente, "series": series}
