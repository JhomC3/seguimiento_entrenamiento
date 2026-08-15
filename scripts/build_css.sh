#!/usr/bin/env bash
# Compila Tailwind con el binario local bloqueado (npm ci). Los tokens deben
# estar al día antes de compilar.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python scripts/build_design_tokens.py --check

if [ ! -x node_modules/.bin/tailwindcss ]; then
    echo "error: tooling no instalado; ejecuta: npm ci" >&2
    exit 1
fi

node_modules/.bin/tailwindcss \
  --content "templates/**/*.html,static/js/**/*.js" \
  -i static/css/input.css -o static/css/tailwind.css --minify
