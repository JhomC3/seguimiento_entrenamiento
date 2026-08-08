#!/usr/bin/env python3
"""Importación de las hojas de alimentación (diario y alimentos) hacia SQLite.

Uso: uv run python scripts/import_nutrition.py

Reemplaza en una sola transacción todas las filas con origen='google' de
`alimentos` y `diario_alimentacion`. Los registros manuales nunca se tocan.
Se crea un backup antes del reemplazo destructivo.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from src.database import backup_db, init_db
from src.fetcher import fetch_sheet_csv
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
        df_diario = parse_diario(csv_diario)
    except Exception as exc:
        print(f"ERROR: no se pudieron descargar/parsear las hojas. Abortando. ({exc})")
        return 1

    if df_alimentos.empty or df_diario.empty:
        print("ERROR: no se descargaron datos válidos. Abortando.")
        return 1

    print(f"Descargado: {len(df_alimentos)} alimentos, {len(df_diario)} entradas del diario")

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
                [
                    tuple(r[col] for col in _DIARIO_COLUMNS)
                    for r in df_diario.to_dict(orient="records")
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
