#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes tailwindcss@3.4.17 \
  --content "templates/**/*.html,static/js/**/*.js" \
  -i static/css/input.css -o static/css/tailwind.css --minify
