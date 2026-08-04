SHEET_ID = "11njHN7oxzwS0N7DUbQ-RfhzA_pTgPaWz"

GIDS = {
    "ciclo_16": "1274647924",
    "volumen_ciclo_16": "1325327429",
    "ejercicios": "2123755988",
}

def get_csv_url(gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"

DB_PATH = "data/gym.db"
