#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/Scripts/activate" ]]; then
  # Git Bash on Windows
  # shellcheck disable=SC1091
  source ".venv/Scripts/activate"
elif [[ -f ".venv/bin/activate" ]]; then
  # Linux/macOS
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

if ! command -v uvicorn >/dev/null 2>&1; then
  echo "uvicorn was not found. Create/activate .venv and install backend requirements first." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found. Install Node.js before launching the frontend." >&2
  exit 1
fi
if [[ ! -d "frontend/node_modules" ]]; then
  echo "frontend/node_modules is missing. Run 'npm install' from frontend/ first." >&2
  exit 1
fi

LOG_FILE="${TMPDIR:-/tmp}/trustfeed-demo-api.log"
uvicorn backend.api.app.main:app --reload --port 8000 >"$LOG_FILE" 2>&1 &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cat <<'BANNER'
============================================================
  _____              _   _____               _
 |_   _|            | | |  ___|             | |
   | |_ __ _   _ ___| |_| |__ ___  ___ _ __ | |
   | | '__| | | / __| __|  __/ _ \/ _ \ '_ \| |
   | | |  | |_| \__ \ |_| | |  __/  __/ | | |_|
   \_/_|   \__,_|___/\__\_|  \___|\___|_| |_(_)

          TrustFeed Demo Environment Live
============================================================
Frontend: http://localhost:5173
Backend:  http://localhost:8000
API docs: http://localhost:8000/docs
BANNER
echo "Backend log: $LOG_FILE"
echo "Press Ctrl+C to stop the frontend and backend."

cd "$ROOT_DIR/frontend"
npm run dev -- --host 127.0.0.1
