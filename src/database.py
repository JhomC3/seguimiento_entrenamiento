import os
import sqlite3
from datetime import datetime

import pandas as pd

from config import MUSCLE_CATEGORIES
from src.db_connection import read_connection, transaction
from src.migrations.runner import run_migrations
from src.models import SPLIT_DAYS


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
            SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg, origen
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
            "origen": r[6],
        }
        for r in rows
    ]


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
            f"SELECT fecha, ejercicio, set_orden, reps, kg, rir, descanso_seg "
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
            SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg, origen
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
            "origen": r[6],
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


def _resync_sequence(conn, table: str) -> None:
    """Re-sincroniza sqlite_sequence tras restaurar ids explícitos.

    `table` proviene únicamente de constantes del módulo (nunca de input).
    """
    row = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
    conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (row[0], table))


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
            "SELECT ejercicio, set_orden, reps, kg, rir, descanso_seg FROM training_sets "
            "WHERE LOWER(ejercicio) = LOWER(?) AND fecha = ? ORDER BY set_orden",
            (ejercicio, latest[0]),
        ).fetchall()
    return [
        {
            "ejercicio": r[0],
            "set_orden": r[1],
            "reps": r[2],
            "kg": r[3],
            "rir": r[4],
            "descanso_seg": r[5],
        }
        for r in set_rows
    ]


# ---------------------------------------------------------------------------
# Alimentación: catálogo y diario
# ---------------------------------------------------------------------------

_DIARIO_NUTRIENT_COLUMNS = (
    "kcal",
    "carbohidratos",
    "fibra",
    "proteina",
    "grasa",
    "hierro",
    "calcio",
    "vitamina_c",
    "vitamina_a",
)


def get_alimentos_catalog(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT nombre, categoria, kcal, carbohidratos, fibra, proteina, grasa, "
            "hierro, calcio, vitamina_c, vitamina_a "
            "FROM alimentos ORDER BY nombre"
        ).fetchall()
    cols = ("nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS)
    return [dict(zip(cols, r)) for r in rows]


def find_alimento(db_path: str, nombre: str) -> dict | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT nombre, categoria, kcal, carbohidratos, fibra, proteina, grasa, "
            "hierro, calcio, vitamina_c, vitamina_a "
            "FROM alimentos WHERE LOWER(nombre) = LOWER(?)",
            (nombre.strip(),),
        ).fetchone()
    if row is None:
        return None
    cols = ("nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS)
    return dict(zip(cols, row))


def insert_alimento(db_path: str, food: dict) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO alimentos (nombre, categoria, kcal, carbohidratos, fibra, "
            "proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, origen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual')",
            (
                food["nombre"],
                food.get("categoria", ""),
                *(food[col] for col in _DIARIO_NUTRIENT_COLUMNS),
            ),
        )


def get_diario_by_fecha(db_path: str, fecha: str) -> list[dict]:
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT orden, alimento, cantidad_g, kcal, carbohidratos, fibra, proteina, "
            "grasa, hierro, calcio, vitamina_c, vitamina_a, origen "
            "FROM diario_alimentacion WHERE fecha = ? ORDER BY orden",
            (fecha,),
        ).fetchall()
    cols = ("orden", "alimento", "cantidad_g", *_DIARIO_NUTRIENT_COLUMNS, "origen")
    return [dict(zip(cols, r)) for r in rows]


def get_diario_dates(db_path: str) -> list[str]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT fecha FROM diario_alimentacion ORDER BY fecha"
            ).fetchall()
        ]


def _diario_row_values(conn, fecha: str, rows: list[dict]) -> list[tuple]:
    values = []
    for idx, r in enumerate(rows, start=1):
        cantidad = r["cantidad_g"]
        cantidad_g = float(cantidad) if cantidad is not None else None
        values.append(
            (
                fecha,
                int(r.get("orden") or idx),
                str(r["alimento"]).strip(),
                cantidad_g,
                *(float(r[col]) for col in _DIARIO_NUTRIENT_COLUMNS),
                str(r.get("origen") or "manual"),
            )
        )
    return values


def replace_diario_by_fecha(db_path: str, fecha: str, rows: list[dict]) -> None:
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM diario_alimentacion WHERE fecha = ?", (fecha,))
        conn.executemany(
            "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
            "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, "
            "vitamina_a, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _diario_row_values(conn, fecha, rows),
        )


def restore_diario_rows(db_path: str, fecha: str, rows: list[dict]) -> None:
    replace_diario_by_fecha(db_path, fecha, rows)


def delete_diario_by_fecha(db_path: str, fecha: str) -> int:
    with transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM diario_alimentacion WHERE fecha = ?", (fecha,))
        return cur.rowcount


_PARAMETROS_COLUMNS = (
    "peso_kg",
    "factor_proteina",
    "factor_grasa",
    "kcal_objetivo",
    "fibra_objetivo",
    "hierro_objetivo",
    "calcio_objetivo",
    "vitamina_c_objetivo",
    "vitamina_a_objetivo",
)


def get_parametros_diarios(db_path: str, fecha: str) -> dict | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT {', '.join(_PARAMETROS_COLUMNS)} FROM parametros_diarios WHERE fecha = ?",
            (fecha,),
        ).fetchone()
    if row is None:
        return None
    return dict(zip(_PARAMETROS_COLUMNS, row))


def save_parametros_diarios(db_path: str, fecha: str, params: dict) -> None:
    """UPSERT de los parámetros del día; solo se actualizan los campos presentes.

    ON CONFLICT preserva el rowid (INSERT OR REPLACE lo cambiaba) y los campos
    no enviados conservan su valor previo.
    """
    current = get_parametros_diarios(db_path, fecha) or {}
    merged = {**current, **params}
    with transaction(db_path) as conn:
        conn.execute(
            """INSERT INTO parametros_diarios (fecha, peso_kg, factor_proteina,
                   factor_grasa, kcal_objetivo, fibra_objetivo, hierro_objetivo,
                   calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fecha) DO UPDATE SET
                   peso_kg = excluded.peso_kg,
                   factor_proteina = excluded.factor_proteina,
                   factor_grasa = excluded.factor_grasa,
                   kcal_objetivo = excluded.kcal_objetivo,
                   fibra_objetivo = excluded.fibra_objetivo,
                   hierro_objetivo = excluded.hierro_objetivo,
                   calcio_objetivo = excluded.calcio_objetivo,
                   vitamina_c_objetivo = excluded.vitamina_c_objetivo,
                   vitamina_a_objetivo = excluded.vitamina_a_objetivo""",
            (
                fecha,
                *[float(merged.get(col, 0.0)) for col in _PARAMETROS_COLUMNS],
            ),
        )


def delete_parametros_diarios(db_path: str, fecha: str) -> None:
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM parametros_diarios WHERE fecha = ?", (fecha,))


# ---------------------------------------------------------------------------
# Plantillas de alimentación
# ---------------------------------------------------------------------------


def get_plantillas_alimentacion(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, nombre FROM plantillas_alimentacion ORDER BY orden, nombre"
        ).fetchall()
        alimentos_rows = conn.execute(
            "SELECT plantilla_id, alimento, cantidad_g FROM plantilla_alimentos "
            "ORDER BY plantilla_id, orden"
        ).fetchall()
    by_id: dict[int, dict] = {}
    for pid, nombre in rows:
        by_id[pid] = {"id": pid, "nombre": nombre, "alimentos": []}
    for pid, alimento, cantidad_g in alimentos_rows:
        if pid in by_id:
            by_id[pid]["alimentos"].append({"alimento": alimento, "cantidad_g": cantidad_g})
    return list(by_id.values())


def find_plantilla_alimentacion_by_nombre(db_path: str, nombre: str) -> int | None:
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM plantillas_alimentacion WHERE LOWER(nombre) = LOWER(?)",
            (nombre.strip(),),
        ).fetchone()
        return row[0] if row else None


def insert_plantilla_alimentacion(db_path: str, nombre: str, rows: list[dict]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        max_row = conn.execute(
            "SELECT COALESCE(MAX(orden), 0) FROM plantillas_alimentacion"
        ).fetchone()
        orden = (max_row[0] or 0) + 1
        cur = conn.execute(
            "INSERT INTO plantillas_alimentacion (nombre, created_at, updated_at, orden) "
            "VALUES (?, ?, ?, ?)",
            (nombre, now, now, orden),
        )
        pid = cur.lastrowid
        if pid is None:
            raise RuntimeError("No se pudo crear la plantilla de alimentación.")
        for idx, r in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO plantilla_alimentos (plantilla_id, orden, alimento, cantidad_g) "
                "VALUES (?, ?, ?, ?)",
                (pid, idx, r["alimento"], r["cantidad_g"]),
            )
        return pid


def update_plantilla_alimentacion_rows(db_path: str, plantilla_id: int, rows: list[dict]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE plantillas_alimentacion SET updated_at = ? WHERE id = ?",
            (now, plantilla_id),
        )
        conn.execute("DELETE FROM plantilla_alimentos WHERE plantilla_id = ?", (plantilla_id,))
        for idx, r in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO plantilla_alimentos (plantilla_id, orden, alimento, cantidad_g) "
                "VALUES (?, ?, ?, ?)",
                (plantilla_id, idx, r["alimento"], r["cantidad_g"]),
            )


def delete_plantilla_alimentacion(db_path: str, plantilla_id: int) -> None:
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM plantilla_alimentos WHERE plantilla_id = ?", (plantilla_id,))
        conn.execute("DELETE FROM plantillas_alimentacion WHERE id = ?", (plantilla_id,))


def reorder_plantillas_alimentacion(db_path: str, ordered_ids: list[int]) -> None:
    with transaction(db_path) as conn:
        for pos, pid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE plantillas_alimentacion SET orden = ? WHERE id = ?", (pos, pid))


def get_prev_diary_date(db_path: str, fecha: str) -> str | None:
    """Última fecha con datos anterior a `fecha` (para prefill)."""
    with read_connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(fecha) FROM diario_alimentacion WHERE fecha < ?", (fecha,)
        ).fetchone()
        return row[0] if row and row[0] else None


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
    """Lista de splits con resumen comparativo (series, días activos, grupos)."""
    if not os.path.exists(db_path):
        return []
    with read_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT s.id, s.nombre, s.updated_at, "
            "COUNT(i.id) AS series, "
            "COUNT(DISTINCT i.dia) AS active_days, "
            "GROUP_CONCAT(DISTINCT i.grupo_muscular) AS groups "
            "FROM training_splits s "
            "LEFT JOIN training_split_items i ON i.split_id = s.id "
            "GROUP BY s.id ORDER BY s.updated_at DESC, s.nombre"
        ).fetchall()
    return [
        {
            "id": r[0],
            "nombre": r[1],
            "updated_at": r[2],
            "series": int(r[3] or 0),
            "active_days": int(r[4] or 0),
            "groups": [g for g in (r[5] or "").split(",") if g],
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
            "SELECT id, nombre, created_at, updated_at FROM training_splits WHERE id = ?",
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
        "items": items,
    }


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
        splits = conn.execute(
            "SELECT id, nombre, created_at, updated_at FROM training_splits ORDER BY id"
        ).fetchall()
        items = conn.execute(
            "SELECT id, split_id, dia, orden, item_type, ejercicio, grupo_muscular "
            "FROM training_split_items ORDER BY split_id, dia, orden"
        ).fetchall()
    return [splits, items]


def restore_splits(db_path: str, snapshot: list) -> None:
    """Restaura splits e items desde un snapshot del journal (ver mutation_service)."""
    splits, items = snapshot[0], snapshot[1]

    def val(r, idx: int, key: str):
        """Fila sqlite3.Row (legado en memoria) o dict (journal persistido)."""
        return r[key] if isinstance(r, dict) else r[idx]

    with transaction(db_path) as conn:
        conn.execute("DELETE FROM training_split_items")
        conn.execute("DELETE FROM training_splits")
        for r in splits:
            conn.execute(
                "INSERT INTO training_splits (id, nombre, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                tuple(
                    val(r, i, k) for i, k in enumerate(("id", "nombre", "created_at", "updated_at"))
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
