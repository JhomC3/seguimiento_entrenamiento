#!/usr/bin/env bash
# Lighthouse determinista: DB desechable bajo .tmp/lighthouse, uvicorn
# loopback, 3 muestras bloqueadas, reportes bajo .tmp y trap de limpieza.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p .tmp/lighthouse
LH_DIR="$(pwd)/.tmp/lighthouse"
SERVER_PID=""
cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

DB_PATH="$LH_DIR/lifestyle.db"
rm -f "$DB_PATH"
uv run python - "$DB_PATH" <<'PY'
import sys
sys.path.insert(0, ".")
from src.database import init_db, insert_exercise
from src.models import TrainingSetInput
from src.training_service import save_session
db = sys.argv[1]
init_db(db)
insert_exercise(db, "Press", "Pectoral", "EMPUJE")
insert_exercise(db, "Curl", "Biceps", "EMPUJE")
save_session(db, "2026-08-10", [TrainingSetInput("Press", 80, 8, 1)])
save_session(db, "2026-08-12", [TrainingSetInput("Press", 82, 8, 1)])
print("DB lista:", db)
PY

CHROME_PATH="$(uv run python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY
)"
echo "chrome: $CHROME_PATH"
if [ ! -x "$CHROME_PATH" ]; then
    echo "error: chromium de Playwright no instalado; ejecuta: uv run playwright install chromium" >&2
    exit 1
fi

uv run uvicorn app:app --host 127.0.0.1 --port 8765 &
SERVER_PID=$!

for _ in $(seq 1 100); do
    if curl -s -o /dev/null http://127.0.0.1:8765/; then
        break
    fi
    sleep 0.2
done

CHROME_PATH="$CHROME_PATH" npx lhci --config lighthouserc.cjs collect
CHROME_PATH="$CHROME_PATH" npx lhci --config lighthouserc.cjs assert
CHROME_PATH="$CHROME_PATH" npx lhci --config lighthouserc.cjs upload
