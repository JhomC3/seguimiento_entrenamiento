#!/usr/bin/env python3
"""Importación de las hojas de alimentación (diario y alimentos) hacia SQLite.

Uso: uv run python scripts/import_nutrition.py

Reemplaza en una sola transacción todas las filas con origen='google' de
`alimentos` y `diario_alimentacion`. Los registros manuales nunca se tocan.
Se crea un backup antes del reemplazo destructivo.
"""

import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from src.database import backup_db, init_db
from src.fetcher import fetch_sheet_csv
from src.nutrition_service import MICRO_DRI_TARGETS, NUTRIENT_FIELDS, calculate_nutrients
from src.parser import parse_alimentos, parse_diario

_ALIMENTOS_COLUMNS = (
    "nombre",
    "categoria",
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

_DIARIO_COLUMNS = (
    "fecha",
    "orden",
    "alimento",
    "cantidad_g",
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


def main() -> int:
    db_path = config.DB_PATH
    print("Descargando Google Sheets de alimentación...")
    try:
        csv_alimentos = fetch_sheet_csv(
            "alimentos", gids=config.NUTRITION_GIDS, sheet_id=config.NUTRITION_SHEET_ID
        )
        csv_diario = fetch_sheet_csv(
            "diario", gids=config.NUTRITION_GIDS, sheet_id=config.NUTRITION_SHEET_ID
        )
        df_alimentos = parse_alimentos(csv_alimentos)
        diario = parse_diario(csv_diario)
        df_diario = diario.df
    except Exception as exc:
        print(f"ERROR: no se pudieron descargar/parsear las hojas. Abortando. ({exc})")
        return 1

    if df_alimentos.empty or df_diario.empty:
        print("ERROR: no se descargaron datos válidos. Abortando.")
        return 1

    print(f"Descargado: {len(df_alimentos)} alimentos, {len(df_diario)} entradas del diario")

    # Guarda anti-corrupción: ningún alimento real supera ~900 kcal/100 g (el
    # aceite puro ronda 884). Por encima hay un error de escala en la hoja
    # (p. ej. valores por unidad o por lote, como la Arepa a 6900). Se avisa
    # y se conserva la fila para no bloquear la importación; la curaduría
    # vive en las migraciones y en POST /alimento/nuevo (que sí rechaza).
    for rec in df_alimentos.to_dict(orient="records"):
        try:
            kcal = float(rec.get("kcal", 0.0))
        except (TypeError, ValueError):
            kcal = 0.0
        if kcal > 900.0:
            print(
                f"AVISO: '{rec.get('nombre')}' trae {kcal:g} kcal/100 g "
                "(implausible, posible error de escala en la hoja)."
            )

    # El consumido se recalcula desde el catálogo (fuente autoritativa); la hoja
    # puede traer valores desactualizados.
    catalog = {
        r["nombre"]: {k: r[k] for k in NUTRIENT_FIELDS}
        for r in df_alimentos.to_dict(orient="records")
    }
    missing_foods: set[str] = set()
    diario_rows = []
    for rec in df_diario.to_dict(orient="records"):
        row = dict(rec)
        cantidad = row.get("cantidad_g")
        if cantidad is None or (isinstance(cantidad, float) and math.isnan(cantidad)):
            row["cantidad_g"] = None
        elif cantidad > 0:
            food = catalog.get(row["alimento"])
            if food is not None:
                row.update(calculate_nutrients(food, cantidad))
            else:
                missing_foods.add(row["alimento"])
        # La hoja solo trae los 9 nutrientes clásicos: los nuevos (v019)
        # entran en 0.0 hasta que la hoja o el catálogo los curen.
        for key in NUTRIENT_FIELDS:
            row.setdefault(key, 0.0)
        diario_rows.append(row)
    if missing_foods:
        print(
            "AVISO: alimentos del diario fuera del catálogo "
            f"(se conservan los valores de la hoja): {sorted(missing_foods)}"
        )

    init_db(db_path)
    backup_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM diario_alimentacion WHERE origen = 'google'")
            conn.execute("DELETE FROM alimentos WHERE origen = 'google'")
            conn.executemany(
                "INSERT OR IGNORE INTO alimentos (nombre, categoria, kcal, carbohidratos, "
                "fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, "
                "magnesio, zinc, potasio, sodio, vitamina_d, vitamina_e, vitamina_k, "
                "folato, vitamina_b12, vitamina_b6, yodo, selenio, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [
                    tuple(r[col] for col in _ALIMENTOS_COLUMNS)
                    for r in df_alimentos.to_dict(orient="records")
                ],
            )
            conn.executemany(
                "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
                "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, "
                "vitamina_a, magnesio, zinc, potasio, sodio, vitamina_d, vitamina_e, "
                "vitamina_k, folato, vitamina_b12, vitamina_b6, yodo, selenio, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [tuple(r[col] for col in _DIARIO_COLUMNS) for r in diario_rows],
            )
            conn.executemany(
                """INSERT INTO parametros_diarios (fecha, peso_kg, factor_proteina,
                       factor_grasa, kcal_objetivo, fibra_objetivo, hierro_objetivo,
                       calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo,
                       magnesio_objetivo, zinc_objetivo, potasio_objetivo,
                       sodio_objetivo, vitamina_d_objetivo, vitamina_e_objetivo,
                       vitamina_k_objetivo, folato_objetivo, vitamina_b12_objetivo,
                       vitamina_b6_objetivo, yodo_objetivo, selenio_objetivo)
                   VALUES (?, 70, 1.5, 1.1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                [
                    (
                        p["fecha"],
                        p["kcal_objetivo"],
                        *[p.get(col, 0.0) or MICRO_DRI_TARGETS[col] for col in MICRO_DRI_TARGETS],
                    )
                    for p in diario.params
                ],
            )
        with conn:
            alim_total = conn.execute("SELECT COUNT(*) FROM alimentos").fetchone()[0]
            alim_manual = conn.execute(
                "SELECT COUNT(*) FROM alimentos WHERE origen = 'manual'"
            ).fetchone()[0]
            diario_total = conn.execute("SELECT COUNT(*) FROM diario_alimentacion").fetchone()[0]
            diario_google = conn.execute(
                "SELECT COUNT(*) FROM diario_alimentacion WHERE origen = 'google'"
            ).fetchone()[0]
    finally:
        conn.close()

    print("Importación completada. Estado de la DB:")
    print(f"  alimentos: {alim_total} ({alim_manual} manuales)")
    print(f"  diario_alimentacion: {diario_total} ({diario_google} google)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
