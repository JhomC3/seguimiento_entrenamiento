import pytest

import config
from src import fetcher
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


def test_nutrition_sheet_constants():
    assert config.NUTRITION_SHEET_ID == "1-qKcqrZRrINdT4Sdw_ItYvn2DtchNvj0Ehb-Nzafxrg"
    assert config.NUTRITION_GIDS == {
        "diario": "368323682",
        "alimentos": "1540384299",
    }


def test_get_csv_url_defaults_to_training_sheet():
    url = config.get_csv_url("1274647924")
    assert f"/d/{config.SHEET_ID}/export?format=csv&gid=1274647924" in url


def test_get_csv_url_accepts_other_sheet_id():
    url = config.get_csv_url("368323682", sheet_id=config.NUTRITION_SHEET_ID)
    assert f"/d/{config.NUTRITION_SHEET_ID}/export?format=csv&gid=368323682" in url


def test_fetch_nutrition_sheet_forwards_nutrition_url(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "x,y\n1,2"

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=30):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    text = fetch_sheet_csv("diario", gids=config.NUTRITION_GIDS, sheet_id=config.NUTRITION_SHEET_ID)
    assert captured["url"] == config.get_csv_url(
        config.NUTRITION_GIDS["diario"], sheet_id=config.NUTRITION_SHEET_ID
    )
    assert text == "x,y\n1,2"


def test_fetch_unknown_sheet_in_custom_map_raises():
    with pytest.raises(ValueError):
        fetch_sheet_csv("diario", gids={"alimentos": "1540384299"})
