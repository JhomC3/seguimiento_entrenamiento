import pytest
from src.fetcher import fetch_sheet_csv

def test_fetch_ejercicios_returns_csv_string():
    """Verifica que podemos descargar la hoja 'ejercicios' y contiene datos esperados."""
    csv_text = fetch_sheet_csv("ejercicios")
    assert isinstance(csv_text, str)
    assert len(csv_text) > 0
    assert "Press Convergente" in csv_text

def test_fetch_ciclo_returns_csv_string():
    csv_text = fetch_sheet_csv("ciclo_16")
    assert "Semana" in csv_text
    assert "LUNES" in csv_text

def test_fetch_invalid_sheet_raises_error():
    with pytest.raises(ValueError):
        fetch_sheet_csv("invalid_sheet_name")
