import os

DB_PATH = os.environ.get("GYM_DB_PATH", "data/gym.db")

CICLO_START = "10/02/2026"

SHEET_ID = "11njHN7oxzwS0N7DUbQ-RfhzA_pTgPaWz"

GIDS = {
    "ciclo_16": "1274647924",
    "volumen_ciclo_16": "1325327429",
    "ejercicios": "2123755988",
}

def get_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"

MUSCLE_CATEGORIES = [
    {"name": "EMPUJE", "muscles": ["Pectoral", "Hombro", "Triceps"]},
    {"name": "TIRON", "muscles": ["Espalda", "Biceps"]},
    {"name": "PIERNA", "muscles": ["Cuadriceps", "Isquio", "Gluteo", "Gemelos", "Aductor"]},
    {"name": "CORE", "muscles": ["Abdomen"]},
]
