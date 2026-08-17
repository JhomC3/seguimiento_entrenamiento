#!/usr/bin/env python3
"""Importación única desde Google Sheets hacia SQLite.

Uso: uv run python scripts/import_google_sheets.py

Reemplaza en una sola transacción todas las filas con origen='google'.
Los registros manuales nunca se tocan.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DB_PATH
from src.database import backup_db, init_db
from src.db_connection import connect_db, read_connection
from src.fetcher import fetch_sheet_csv
from src.parser import parse_ciclo, parse_ejercicios


def import_training_tables(db_path: str, df_ejercicios, df_ciclo) -> dict:
    """Reemplazo atómico de las filas origen='google' con backup previo.

    Los registros manuales nunca se tocan. Devuelve totales (series, ejercicios).
    """
    if df_ejercicios.empty or df_ciclo.empty:
        raise ValueError("no se descargaron datos válidos")
    backup_db(db_path)
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM training_sets WHERE origen = 'google'")
            conn.executemany(
                "INSERT OR IGNORE INTO ejercicios (grupo_muscular, ejercicio) VALUES (?, ?)",
                [(r.grupo_muscular, r.ejercicio) for r in df_ejercicios.itertuples()],
            )
            conn.executemany(
                "INSERT INTO training_sets (semana, dia, fecha, set_orden, ejercicio, reps, kg, rir, origen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'google')",
                [
                    (r.semana, r.dia, r.fecha, r.set_orden, r.ejercicio, r.reps, r.kg, r.rir)
                    for r in df_ciclo.itertuples()
                ],
            )
    finally:
        conn.close()
    with read_connection(db_path) as conn:
        return {
            "total": conn.execute("SELECT COUNT(*) FROM training_sets").fetchone()[0],
            "ejercicios": conn.execute("SELECT COUNT(*) FROM ejercicios").fetchone()[0],
        }


def main() -> int:
    print("Descargando Google Sheets...")
    csv_ejercicios = fetch_sheet_csv("ejercicios")
    csv_ciclo = fetch_sheet_csv("ciclo_16")
    df_ejercicios = parse_ejercicios(csv_ejercicios)
    df_ciclo = parse_ciclo(csv_ciclo)

    if df_ejercicios.empty or df_ciclo.empty:
        print("ERROR: no se descargaron datos válidos. Abortando.")
        return 1

    print(f"Descargado: {len(df_ejercicios)} ejercicios, {len(df_ciclo)} series")

    init_db(DB_PATH)
    totals = import_training_tables(DB_PATH, df_ejercicios, df_ciclo)

    print("Importación completada. Estado de la DB:")
    with read_connection(DB_PATH) as conn:
        for origen, count in conn.execute(
            "SELECT origen, COUNT(*) FROM training_sets GROUP BY origen"
        ).fetchall():
            print(f"  {origen}: {count} series")
    print(f"  ejercicios: {totals['ejercicios']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
