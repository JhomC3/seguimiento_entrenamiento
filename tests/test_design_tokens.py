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
    assert set(tokens["chart"]) >= {
        "background",
        "axes",
        "grid",
        "text",
        "primary",
        "hover",
        "exercise",
    }


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


# ---------------------------------------------------------------------------
# WCAG 2.x contrast (fórmula del anexo A del forense 2026-08-14)
# ---------------------------------------------------------------------------


def _linearize_channel(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(value: str) -> tuple[float, float, float, float]:
    """Devuelve (r, g, b, alpha) para '#rrggbb', '#rrggbbaa' o 'rgba(r, g, b, a)'."""
    value = value.strip()
    if value.startswith("#"):
        hexv = value[1:]
        if len(hexv) == 6:
            hexv += "ff"
        r, g, b, a = (int(hexv[i : i + 2], 16) for i in (0, 2, 4, 6))
        return r, g, b, a / 255.0
    if value.startswith("rgba("):
        parts = [p.strip() for p in value[5:-1].split(",")]
        return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    if value.startswith("rgb("):
        parts = [p.strip() for p in value[4:-1].split(",")]
        return float(parts[0]), float(parts[1]), float(parts[2]), 1.0
    raise ValueError(f"color no soportado: {value}")


def _composited_luminance(fg: str, bg: str) -> float:
    """Luminancia relativa WCAG de fg compuesto (con su alpha) sobre bg."""
    fr, fg_c, fb, fa = _rgb(fg)
    br, bg_c, bb, _ = _rgb(bg)
    cr = fa * fr + (1 - fa) * br
    cg = fa * fg_c + (1 - fa) * bg_c
    cb = fa * fb + (1 - fa) * bb
    return (
        0.2126 * _linearize_channel(cr)
        + 0.7152 * _linearize_channel(cg)
        + 0.0722 * _linearize_channel(cb)
    )


def wcag_contrast(fg: str, bg: str) -> float:
    l1 = _composited_luminance(fg, bg)
    l2 = _composited_luminance(bg, bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# Tokens usados como texto visible: deben cumplir AA (≥ 4.5:1) sobre los dos
# fondos oscuros del tema (matte-950 y neutral-900).
TEXT_TOKENS = (
    "surfaces.neutral.100",
    "surfaces.neutral.200",
    "surfaces.neutral.300",
    "surfaces.neutral.400",
    "burgundy.300",
    "burgundy.400",
    "semantics.success.text",
    "semantics.danger.text",
    "chart.text",
    "chart.hover.text",
)


def test_semantic_text_tokens_meet_wcag_aa_over_matte_950():
    for path in TEXT_TOKENS:
        ratio = wcag_contrast(color(path), "#0a0a0a")
        assert ratio >= 4.5, f"{path}: {ratio:.2f}:1 sobre matte-950"


def test_semantic_text_tokens_meet_wcag_aa_over_neutral_900():
    for path in TEXT_TOKENS:
        ratio = wcag_contrast(color(path), "#171717")
        assert ratio >= 4.5, f"{path}: {ratio:.2f}:1 sobre neutral-900"


def test_no_low_contrast_neutral_text_in_templates():
    """text-neutral-500/600 y placeholder-neutral-600 fallan AA (2.3–4.2:1):
    no pueden usarse como texto visible en ningún template."""
    for path in sorted((ROOT / "templates").rglob("*.html")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert "text-neutral-500" not in line, f"{path}:{i}"
            assert "text-neutral-600" not in line, f"{path}:{i}"
            assert "placeholder-neutral-600" not in line, f"{path}:{i}"


def test_no_micro_font_sizes_in_templates():
    """El forense exige ≥ 12 px para texto visible (hallazgo 2.3)."""
    for path in sorted((ROOT / "templates").rglob("*.html")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for size in ("8px", "9px", "10px", "11px"):
                assert f"text-[{size}]" not in line, f"{path}:{i}"


def test_no_micro_font_sizes_in_handwritten_css():
    for name in (
        "cascade.css",
        "components.css",
        "date-navigator.css",
        "session-editor.css",
        "templates.css",
        "theme.css",
    ):
        src = (ROOT / "static" / "css" / name).read_text(encoding="utf-8")
        assert not re.search(r"font-size:\s*(?:8|9|10|11)px", src), name
