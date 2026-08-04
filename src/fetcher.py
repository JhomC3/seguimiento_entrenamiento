import requests
from config import GIDS, get_csv_url

def fetch_sheet_csv(sheet_name: str) -> str:
    """Descarga una hoja de Google Sheets como texto CSV."""
    if sheet_name not in GIDS:
        raise ValueError(f"Hoja desconocida: {sheet_name}. Opciones: {list(GIDS.keys())}")
    url = get_csv_url(GIDS[sheet_name])
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text
