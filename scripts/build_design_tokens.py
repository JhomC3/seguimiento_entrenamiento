#!/usr/bin/env python3
"""Regenera static/css/tokens.css desde static/design-tokens.json.

Uso:
    python scripts/build_design_tokens.py          # escribe tokens.css
    python scripts/build_design_tokens.py --check  # error si hay drift
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

from src.design_tokens import read_tokens, render_css

ROOT = Path(__file__).resolve().parents[1]
TOKENS_CSS = ROOT / "static" / "css" / "tokens.css"


def main() -> int:
    tokens = read_tokens()
    rendered = render_css(tokens)
    if "--check" in sys.argv:
        current = TOKENS_CSS.read_text(encoding="utf-8") if TOKENS_CSS.exists() else ""
        if current != rendered:
            print(
                "error: static/css/tokens.css está desactualizado; "
                "ejecuta: python scripts/build_design_tokens.py",
                file=sys.stderr,
            )
            return 1
        print("tokens.css up to date")
        return 0
    TOKENS_CSS.write_text(rendered, encoding="utf-8")
    print(f"escribió {TOKENS_CSS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
