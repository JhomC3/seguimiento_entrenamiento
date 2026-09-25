"""Persistencia de splits de entrenamiento (spec 006)."""

import os
import sqlite3
from datetime import datetime

from config import MUSCLE_CATEGORIES
from src.db_common import _resync_sequence
from src.db_connection import read_connection, transaction
from src.db_training import get_exercise_valid_counts
from src.models import SPLIT_DAYS, NotFoundError

# ---------------------------------------------------------------------------
# Splits de entrenamiento
# ---------------------------------------------------------------------------


def get_split_catalog(db_path: str) -> list[dict]:
    """Catálogo completo de ejercicios (grupo muscular + categoría) para el board."""
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT ejercicio, grupo_muscular, categoria FROM ejercicios "
            "ORDER BY grupo_muscular, ejercicio"
        ).fetchall()
    return [{"ejercicio": r[0], "grupo_muscular": r[1], "categoria": r[2] or ""} for r in rows]


def get_dashboard_catalog(
    db_path: str, fecha_min: str | None = None, fecha_max: str | None = None
) -> list[dict]:
    """Catálogo agrupado por grupo muscular para el panel izquierdo del dashboard.

    Orden dinámico compartido: ejercicios con más series válidas primero,
    desempate estable por catálogo. Si se pasa ventana (fecha_min/max), el
    conteo respeta esa ventana; si no, usa todo el histórico.

    El orden de los grupos sigue el de la tabla ``MUSCLE_CATEGORIES``.
    """
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT ejercicio, grupo_muscular, categoria "
            "FROM ejercicios "
            "WHERE grupo_muscular IS NOT NULL AND grupo_muscular != '' "
            "ORDER BY grupo_muscular, ejercicio"
        ).fetchall()
    if not rows:
        return []
    cat_order: dict[str, int] = {}
    for cat_idx, cat in enumerate(MUSCLE_CATEGORIES):
        for muscle in cat.get("muscles", []):
            cat_order[muscle] = cat_idx
    # Conteos para orden dinámico compartido
    counts = get_exercise_valid_counts(db_path, fecha_min, fecha_max)
    # Orden estable del catálogo para desempate
    catalog_order = [r[0] for r in rows]
    groups: dict[str, list[dict]] = {}
    for ejercicio, grupo, categoria in rows:
        groups.setdefault(grupo, []).append({"name": ejercicio, "category": categoria or ""})
    # Ordena ejercicios dentro de cada grupo por datos
    for grupo, exs in list(groups.items()):
        groups[grupo] = sorted(
            exs,
            key=lambda ex: (
                -counts.get(ex["name"], 0),
                catalog_order.index(ex["name"]) if ex["name"] in catalog_order else 999,
            ),
        )
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: (cat_order.get(kv[0], 999), kv[0]),
    )
    return [{"name": g, "exercises": exs} for g, exs in sorted_groups]


def get_splits_summary(db_path: str) -> list[dict]:
    """Lista de splits con resumen comparativo (series, días activos, grupos).

    Orden: split actual primero, luego por updated_at/nombre.
    """
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT s.id, s.nombre, s.updated_at, COALESCE(s.activo, 0), "
            "COUNT(i.id) AS series, "
            "COUNT(DISTINCT i.dia) AS active_days, "
            "GROUP_CONCAT(DISTINCT i.grupo_muscular) AS groups "
            "FROM training_splits s "
            "LEFT JOIN training_split_items i ON i.split_id = s.id "
            "GROUP BY s.id ORDER BY COALESCE(s.activo, 0) DESC, s.updated_at DESC, s.nombre"
        ).fetchall()
    return [
        {
            "id": r[0],
            "nombre": r[1],
            "updated_at": r[2],
            "activo": int(r[3] or 0),
            "series": int(r[4] or 0),
            "active_days": int(r[5] or 0),
            "groups": [g for g in (r[6] or "").split(",") if g],
        }
        for r in rows
    ]


def find_split_by_nombre(db_path: str, nombre: str) -> int | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM training_splits WHERE LOWER(nombre) = LOWER(?)", (nombre,)
        ).fetchone()
        return row[0] if row else None


def get_split(db_path: str, split_id: int) -> dict | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, nombre, created_at, updated_at, COALESCE(activo, 0) "
            "FROM training_splits WHERE id = ?",
            (split_id,),
        ).fetchone()
        if not row:
            return None
        item_rows = conn.execute(
            "SELECT id, dia, orden, item_type, ejercicio, grupo_muscular "
            "FROM training_split_items WHERE split_id = ?",
            (split_id,),
        ).fetchall()
    day_index = {day: idx for idx, day in enumerate(SPLIT_DAYS)}
    items = [
        {
            "id": r[0],
            "dia": r[1],
            "orden": r[2],
            "item_type": r[3],
            "ejercicio": r[4],
            "grupo_muscular": r[5],
        }
        for r in item_rows
    ]
    items.sort(key=lambda it: (day_index.get(it["dia"], 99), it["orden"]))
    return {
        "id": row[0],
        "nombre": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "activo": int(row[4] or 0),
        "items": items,
    }


def get_active_split_id(db_path: str) -> int | None:
    """Id del split actual, o None si no hay ninguno marcado."""
    if not os.path.exists(db_path):
        return None
    with read_connection(db_path) as conn:
        try:
            row = conn.execute(
                "SELECT id FROM training_splits WHERE COALESCE(activo, 0) = 1 LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return int(row[0]) if row else None


def set_active_split(db_path: str, split_id: int) -> None:
    """Marca un split como actual (único). Idempotente. Una sola transacción."""
    with transaction(db_path) as conn:
        row = conn.execute("SELECT id FROM training_splits WHERE id = ?", (split_id,)).fetchone()
        if not row:
            raise NotFoundError("El split no existe.")
        conn.execute("UPDATE training_splits SET activo = 0 WHERE COALESCE(activo, 0) = 1")
        conn.execute("UPDATE training_splits SET activo = 1 WHERE id = ?", (split_id,))


def _insert_split_items(conn, split_id: int, items: list[tuple[str, str, str, str]]) -> None:
    """Inserta items renumerando `orden` por día desde 1 (orden visual recibido)."""
    counters: dict[str, int] = {}
    for dia, item_type, ejercicio, grupo in items:
        counters[dia] = counters.get(dia, 0) + 1
        conn.execute(
            "INSERT INTO training_split_items "
            "(split_id, dia, orden, item_type, ejercicio, grupo_muscular) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (split_id, dia, counters[dia], item_type, ejercicio, grupo),
        )


def insert_split(db_path: str, nombre: str, items: list[tuple[str, str, str, str]]) -> int:
    """Crea un split. `items` son tuplas (dia, item_type, ejercicio, grupo_muscular)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO training_splits (nombre, created_at, updated_at) VALUES (?, ?, ?)",
            (nombre, now, now),
        )
        pid = cur.lastrowid
        if pid is None:
            raise RuntimeError("No se pudo crear el split.")
        _insert_split_items(conn, pid, items)
        return pid


def update_split(
    db_path: str, split_id: int, nombre: str, items: list[tuple[str, str, str, str]]
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE training_splits SET nombre = ?, updated_at = ? WHERE id = ?",
            (nombre, now, split_id),
        )
        conn.execute("DELETE FROM training_split_items WHERE split_id = ?", (split_id,))
        _insert_split_items(conn, split_id, items)


def delete_split(db_path: str, split_id: int) -> None:
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM training_splits WHERE id = ?", (split_id,))


def snapshot_splits(db_path: str) -> list:
    with read_connection(db_path) as conn:
        try:
            splits = conn.execute(
                "SELECT id, nombre, created_at, updated_at, COALESCE(activo, 0) AS activo "
                "FROM training_splits ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            splits = conn.execute(
                "SELECT id, nombre, created_at, updated_at FROM training_splits ORDER BY id"
            ).fetchall()
        items = conn.execute(
            "SELECT id, split_id, dia, orden, item_type, ejercicio, grupo_muscular "
            "FROM training_split_items ORDER BY split_id, dia, orden"
        ).fetchall()
    return [splits, items]


def restore_splits(db_path: str, snapshot: list) -> None:
    """Restaura splits e items desde un snapshot del journal (ver mutation_service).

    Acepta snapshots previos a v016 (sin ``activo``): restaura con activo 0.
    """
    splits, items = snapshot[0], snapshot[1]

    def val(r, idx: int, key: str, default=0):
        """Fila sqlite3.Row (legado en memoria) o dict (journal persistido)."""
        if isinstance(r, dict):
            return r.get(key, default)
        try:
            return r[idx]
        except IndexError:
            return default

    with transaction(db_path) as conn:
        conn.execute("DELETE FROM training_split_items")
        conn.execute("DELETE FROM training_splits")
        for r in splits:
            conn.execute(
                "INSERT INTO training_splits (id, nombre, created_at, updated_at, activo) "
                "VALUES (?, ?, ?, ?, ?)",
                tuple(
                    val(r, i, k)
                    for i, k in enumerate(("id", "nombre", "created_at", "updated_at", "activo"))
                ),
            )
        for r in items:
            conn.execute(
                "INSERT INTO training_split_items "
                "(id, split_id, dia, orden, item_type, ejercicio, grupo_muscular) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                tuple(
                    val(r, i, k)
                    for i, k in enumerate(
                        (
                            "id",
                            "split_id",
                            "dia",
                            "orden",
                            "item_type",
                            "ejercicio",
                            "grupo_muscular",
                        )
                    )
                ),
            )
        _resync_sequence(conn, "training_splits")
        _resync_sequence(conn, "training_split_items")
