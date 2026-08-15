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
from src.nutrition_service import NUTRIENT_FIELDS, calculate_nutrients
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
                "fibra, proteina, grasa, hierro, calcio, vitamina_c, vitamina_a, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [
                    tuple(r[col] for col in _ALIMENTOS_COLUMNS)
                    for r in df_alimentos.to_dict(orient="records")
                ],
            )
            conn.executemany(
                "INSERT INTO diario_alimentacion (fecha, orden, alimento, cantidad_g, kcal, "
                "carbohidratos, fibra, proteina, grasa, hierro, calcio, vitamina_c, "
                "vitamina_a, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [tuple(r[col] for col in _DIARIO_COLUMNS) for r in diario_rows],
            )
            conn.executemany(
                """INSERT INTO parametros_diarios (fecha, peso_kg, factor_proteina,
                       factor_grasa, kcal_objetivo, fibra_objetivo, hierro_objetivo,
                       calcio_objetivo, vitamina_c_objetivo, vitamina_a_objetivo)
                   VALUES (?, 70, 1.5, 1.1, ?, ?, ?, ?, ?, ?)
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
                [
                    (
                        p["fecha"],
                        p["kcal_objetivo"],
                        p.get("fibra_objetivo", 0.0),
                        p.get("hierro_objetivo", 0.0),
                        p.get("calcio_objetivo", 0.0),
                        p.get("vitamina_c_objetivo", 0.0),
                        p.get("vitamina_a_objetivo", 0.0),
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
