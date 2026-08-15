"""Design token pipeline: static/design-tokens.json is the only palette source.

Rules enforced here:
- tokens.json has the required sections and well-formed color values;
- static/css/tokens.css is byte-identical to the generator output;
- src/charts.py consumes colors only through the typed helpers (no hex literals);
- templates no longer link palette.css nor carry inline <style> blocks.
"""

import json
import re
from pathlib import Path

from src.design_tokens import color, palette, read_tokens, render_css

ROOT = Path(__file__).resolve().parents[1]

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
RGBA_RE = re.compile(r"^rgba?\([^)]*\)$")

BURGUNDY_SCALE = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}


def _walk(obj, prefix=""):
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _walk(value, path)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                yield f"{path}.{i}", item
        else:
            yield path, value


def test_tokens_json_has_required_sections():
    tokens = json.loads((ROOT / "static" / "design-tokens.json").read_text(encoding="utf-8"))
    assert set(tokens) >= {"surfaces", "burgundy", "focus", "semantics", "chart"}
    assert set(tokens["surfaces"]) >= {"matte", "neutral"}
    assert set(tokens["burgundy"]) >= BURGUNDY_SCALE
    assert set(tokens["surfaces"]["matte"]) >= {"900", "950"}
    assert "ring" in tokens["focus"]
    assert {"success", "danger"} <= set(tokens["semantics"])
    assert set(tokens["chart"]) >= {"background", "axes", "grid", "text", "primary", "hover", "exercise"}


def test_tokens_values_are_colors_or_effects():
    tokens = read_tokens()
    for path, value in _walk(tokens):
        if not isinstance(value, str) or path.startswith(("schema_version", "glow.")):
            continue
        assert HEX_RE.match(value) or RGBA_RE.match(value), (path, value)


def test_tokens_css_is_generator_output():
    actual = (ROOT / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    assert render_css(read_tokens()) == actual


def test_chart_colours_use_canonical_tokens():
    from src.charts import EXERCISE_PALETTE, chart_color

    assert chart_color("primary") == color("burgundy.400")
    assert chart_color("axes") == color("chart.axes")
    assert EXERCISE_PALETTE == palette("chart.exercise")
    assert len(EXERCISE_PALETTE) >= 5


def test_charts_module_has_no_handwritten_hex():
    source = (ROOT / "src" / "charts.py").read_text(encoding="utf-8")
    assert re.findall(r"#[0-9a-fA-F]{6}\b", source) == []


def test_base_html_no_palette_css():
    html = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "palette.css" not in html


def test_index_html_no_inline_style_block():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "<style" not in html


def test_unknown_token_path_raises():
    import pytest

    with pytest.raises(KeyError):
        color("no.such.token")
    with pytest.raises(KeyError):
        palette("chart.no.such")
