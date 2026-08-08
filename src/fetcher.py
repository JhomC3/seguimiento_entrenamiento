import requests

from config import GIDS, SHEET_ID, get_csv_url


def fetch_sheet_csv(
    sheet_name: str,
    *,
    gids: dict[str, str] = GIDS,
    sheet_id: str = SHEET_ID,
) -> str:
    """Descarga una hoja de Google Sheets como texto CSV.

    Por defecto descarga hojas del spreadsheet de entrenamiento; alimentación
    pasa explícitamente `gids=NUTRITION_GIDS` y `sheet_id=NUTRITION_SHEET_ID`.
    """
    if sheet_name not in gids:
        raise ValueError(f"Hoja desconocida: {sheet_name}. Opciones: {list(gids.keys())}")
    url = get_csv_url(gids[sheet_name], sheet_id=sheet_id)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    # Google sirve UTF-8 sin charset en el header: requests.text lo decodificaría
    # como Latin-1 (mojibake en tildes). Decodificar los bytes explícitamente.
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return response.content.decode("latin-1")
