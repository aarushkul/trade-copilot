#!/usr/bin/env bash
# Start Trade Copilot. Opens the dashboard in your browser automatically.
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv — run once:"
  echo "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "Already running → ${URL}"
  open "${URL}"
  exit 0
fi

echo "Starting Trade Copilot…"
echo "  Dashboard: ${URL}"
echo "  Stop: click Stop on the dashboard, or press Ctrl+C here"
echo ""

(sleep 2 && open "${URL}") &
.venv/bin/python run.py --feed auto --port "${PORT}"
