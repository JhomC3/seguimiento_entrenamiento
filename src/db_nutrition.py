"""Persistencia de nutricion: alimentos, diario, parametros y plantillas (spec 006)."""

import os
from datetime import datetime

from src.db_connection import read_connection, transaction

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
    "magnesio",
    "zinc",
    "potasio",
    "sodio",
    "vitamina_d",
    "vitamina_e",
    "vitamina_k",
    "folato",
    "vitamina_b12",
    "vitamina_b6",
    "yodo",
    "selenio",
)


def get_alimentos_catalog(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    select = ", ".join(["nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS])
    with read_connection(db_path) as conn:
        rows = conn.execute(f"SELECT {select} FROM alimentos ORDER BY nombre").fetchall()
    cols = ("nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS)
    return [dict(zip(cols, r)) for r in rows]


def find_alimento(db_path: str, nombre: str) -> dict | None:
    select = ", ".join(["nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS])
    with read_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT {select} FROM alimentos WHERE LOWER(nombre) = LOWER(?)",
            (nombre.strip(),),
        ).fetchone()
    if row is None:
        return None
    cols = ("nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS)
    return dict(zip(cols, row))


def insert_alimento(db_path: str, food: dict) -> None:
    cols = ", ".join(["nombre", "categoria", *_DIARIO_NUTRIENT_COLUMNS, "origen"])
    placeholders = ", ".join(["?"] * (len(_DIARIO_NUTRIENT_COLUMNS) + 2) + ["'manual'"])
    with transaction(db_path) as conn:
        conn.execute(
            f"INSERT INTO alimentos ({cols}) VALUES ({placeholders})",
            (
                food["nombre"],
                food.get("categoria", ""),
                *(food.get(col, 0.0) for col in _DIARIO_NUTRIENT_COLUMNS),
            ),
        )


def get_diario_by_fecha(db_path: str, fecha: str) -> list[dict]:
    select = ", ".join(["orden", "alimento", "cantidad_g", *_DIARIO_NUTRIENT_COLUMNS, "origen"])
    with read_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT {select} FROM diario_alimentacion WHERE fecha = ? ORDER BY orden",
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
                *(float(r.get(col, 0.0) or 0.0) for col in _DIARIO_NUTRIENT_COLUMNS),
                str(r.get("origen") or "manual"),
            )
        )
    return values


def replace_diario_by_fecha(db_path: str, fecha: str, rows: list[dict]) -> None:
    cols = ", ".join(
        ["fecha", "orden", "alimento", "cantidad_g", *_DIARIO_NUTRIENT_COLUMNS, "origen"]
    )
    placeholders = ", ".join(["?"] * (len(_DIARIO_NUTRIENT_COLUMNS) + 5))
    with transaction(db_path) as conn:
        conn.execute("DELETE FROM diario_alimentacion WHERE fecha = ?", (fecha,))
        conn.executemany(
            f"INSERT INTO diario_alimentacion ({cols}) VALUES ({placeholders})",
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
    "magnesio_objetivo",
    "zinc_objetivo",
    "potasio_objetivo",
    "sodio_objetivo",
    "vitamina_d_objetivo",
    "vitamina_e_objetivo",
    "vitamina_k_objetivo",
    "folato_objetivo",
    "vitamina_b12_objetivo",
    "vitamina_b6_objetivo",
    "yodo_objetivo",
    "selenio_objetivo",
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
                   calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo,
                   magnesio_objetivo, zinc_objetivo, potasio_objetivo,
                   sodio_objetivo, vitamina_d_objetivo, vitamina_e_objetivo,
                   vitamina_k_objetivo, folato_objetivo, vitamina_b12_objetivo,
                   vitamina_b6_objetivo, yodo_objetivo, selenio_objetivo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fecha) DO UPDATE SET
                    peso_kg = excluded.peso_kg,
                    factor_proteina = excluded.factor_proteina,
                    factor_grasa = excluded.factor_grasa,
                    kcal_objetivo = excluded.kcal_objetivo,
                    fibra_objetivo = excluded.fibra_objetivo,
                    hierro_objetivo = excluded.hierro_objetivo,
                    calcio_objetivo = excluded.calcio_objetivo,
                    vitamina_c_objetivo = excluded.vitamina_c_objetivo,
                    vitamina_a_objetivo = excluded.vitamina_a_objetivo,
                    magnesio_objetivo = excluded.magnesio_objetivo,
                    zinc_objetivo = excluded.zinc_objetivo,
                    potasio_objetivo = excluded.potasio_objetivo,
                    sodio_objetivo = excluded.sodio_objetivo,
                    vitamina_d_objetivo = excluded.vitamina_d_objetivo,
                    vitamina_e_objetivo = excluded.vitamina_e_objetivo,
                    vitamina_k_objetivo = excluded.vitamina_k_objetivo,
                    folato_objetivo = excluded.folato_objetivo,
                    vitamina_b12_objetivo = excluded.vitamina_b12_objetivo,
                    vitamina_b6_objetivo = excluded.vitamina_b6_objetivo,
                    yodo_objetivo = excluded.yodo_objetivo,
                    selenio_objetivo = excluded.selenio_objetivo""",
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
