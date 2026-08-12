import os
from pathlib import Path

DB_PATH: str = os.environ.get("GYM_DB_PATH", "data/gym.db")

# Shared secret for POST /sync/health-connect (X-Sync-Token). If empty, the
# endpoint answers 503 "not configured". See docs/architecture/health-sync-contract.md.
# El env gana; si no está, se lee del archivo persistente (data/hc_sync_token,
# gitignored) para que un reinicio del servidor no pierda el token.
SYNC_TOKEN_FILE: Path = Path("data/hc_sync_token")


def _token_from_file() -> str:
    try:
        return SYNC_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


HC_SYNC_TOKEN: str = os.environ.get("HC_SYNC_TOKEN", "") or _token_from_file()

CICLO_START: str = "04/05/2026"

CICLO_NUMERO: int = 1

SHEET_ID: str = "11njHN7oxzwS0N7DUbQ-RfhzA_pTgPaWz"

GIDS: dict[str, str] = {
    "ciclo_16": "1274647924",
    "volumen_ciclo_16": "1325327429",
    "ejercicios": "2123755988",
}

NUTRITION_SHEET_ID: str = "1-qKcqrZRrINdT4Sdw_ItYvn2DtchNvj0Ehb-Nzafxrg"

NUTRITION_GIDS: dict[str, str] = {
    "diario": "368323682",
    "alimentos": "1540384299",
}


def get_csv_url(gid: str, sheet_id: str = SHEET_ID) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


MUSCLE_CATEGORIES: list[dict[str, str | list[str]]] = [
    {"name": "EMPUJE", "muscles": ["Pectoral", "Hombro", "Triceps"]},
    {"name": "TIRON", "muscles": ["Espalda", "Biceps"]},
    {"name": "PIERNA", "muscles": ["Cuadriceps", "Isquio", "Gluteo", "Gemelos", "Aductor"]},
    {"name": "CORE", "muscles": ["Abdomen"]},
]
