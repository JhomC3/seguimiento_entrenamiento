#!/bin/bash
# Arranca el servidor del dashboard con el token de HealthSync persistente.
#
# - La primera vez genera el token (data/hc_sync_token) y lo imprime: cópialo
#   en la app del teléfono (HealthSync → destino → token).
# - Los reinicios siguientes reutilizan el MISMO token: el teléfono no se toca.
# - Logs de acceso SIN buffer (PYTHONUNBUFFERED) para ver las peticiones en vivo.
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN_FILE="data/hc_sync_token"
if [ ! -f "$TOKEN_FILE" ]; then
    TOKEN=$(openssl rand -hex 32)
    printf '%s' "$TOKEN" > "$TOKEN_FILE"
    echo "=== Token nuevo generado (cópialo en la app del teléfono): ==="
    echo "$TOKEN"
    echo "================================================================="
fi

exec env PYTHONUNBUFFERED=1 HC_SYNC_TOKEN="$(cat "$TOKEN_FILE")" \
    uv run uvicorn app:app --host 0.0.0.0 --port 8000 --access-log
