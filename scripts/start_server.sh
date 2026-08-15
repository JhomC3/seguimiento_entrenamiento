#!/bin/bash
# Arranca el servidor del dashboard con el token de HealthSync persistente.
#
# - La primera vez genera el token (data/hc_sync_token) y lo imprime. La app
#   debug lo consume en build-time (BuildConfig.DEFAULT_SYNC_TOKEN), así que no
#   hay que copiarlo al teléfono salvo que recompiles el APK.
# - Los reinicios siguientes reutilizan el MISMO token: el teléfono no se toca.
# - Genera y persiste el secreto CSRF (data/csrf_secret, no se imprime) y activa
#   el modo LAN sync-only: en la LAN solo se sirve POST /sync/health-connect.
# - Logs de acceso SIN buffer (PYTHONUNBUFFERED) para ver las peticiones en vivo.
set -euo pipefail
cd "$(dirname "$0")/.."

umask 077

TOKEN_FILE="data/hc_sync_token"
if [ ! -f "$TOKEN_FILE" ]; then
    TOKEN=$(openssl rand -hex 32)
    printf '%s' "$TOKEN" > "$TOKEN_FILE"
    echo "=== Token nuevo generado (recompila el APK debug para que la app lo use): ==="
    echo "$TOKEN"
    echo "========================================================================"
fi

SECRET_FILE="data/csrf_secret"
if [ ! -f "$SECRET_FILE" ]; then
    openssl rand -hex 48 > "$SECRET_FILE"
    echo "=== Secreto CSRF nuevo generado en $SECRET_FILE (no se imprime). ==="
fi
if [ ! -s "$SECRET_FILE" ]; then
    echo "error: $SECRET_FILE está vacío; bórralo para regenerarlo." >&2
    exit 1
fi

exec env PYTHONUNBUFFERED=1 \
    HC_SYNC_TOKEN="$(cat "$TOKEN_FILE")" \
    GYM_CSRF_SECRET="$(cat "$SECRET_FILE")" \
    GYM_LAN_SYNC_ONLY=1 \
    uv run uvicorn app:app --host 0.0.0.0 --port 8000 --access-log
