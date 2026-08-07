import os

DB_PATH: str = os.environ.get("GYM_DB_PATH", "data/gym.db")

CICLO_START: str = "04/05/2026"

CICLO_NUMERO: int = 1

SHEET_ID: str = "11njHN7oxzwS0N7DUbQ-RfhzA_pTgPaWz"

GIDS: dict[str, str] = {
    "ciclo_16": "1274647924",
    "volumen_ciclo_16": "1325327429",
    "ejercicios": "2123755988",
}


def get_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"


MUSCLE_CATEGORIES: list[dict[str, str | list[str]]] = [
    {"name": "EMPUJE", "muscles": ["Pectoral", "Hombro", "Triceps"]},
    {"name": "TIRON", "muscles": ["Espalda", "Biceps"]},
    {"name": "PIERNA", "muscles": ["Cuadriceps", "Isquio", "Gluteo", "Gemelos", "Aductor"]},
    {"name": "CORE", "muscles": ["Abdomen"]},
]
