#!/usr/bin/env python3
"""Importación única desde Google Sheets hacia SQLite.

Uso: uv run python scripts/import_google_sheets.py

Reemplaza en una sola transacción todas las filas con origen='google'.
Los registros manuales nunca se tocan.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fetcher import fetch_sheet_csv
from src.parser import parse_ejercicios, parse_ciclo
from src.database import init_db
from config import DB_PATH

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
    conn = sqlite3.connect(DB_PATH)
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
        with conn:
            totals = conn.execute("SELECT origen, COUNT(*) FROM training_sets GROUP BY origen").fetchall()
            ejercicios_count = conn.execute("SELECT COUNT(*) FROM ejercicios").fetchone()[0]
    finally:
        conn.close()

    print("Importación completada. Estado de la DB:")
    for origen, count in totals:
        print(f"  {origen}: {count} series")
    print(f"  ejercicios: {ejercicios_count}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
