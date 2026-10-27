#!/usr/bin/env bash
set -e

PORT="${PORT:-5000}"
export PORT
export WA_BRIDGE_PORT="${WA_BRIDGE_PORT:-3001}"
export BRIDGE_PORT="${BRIDGE_PORT:-3001}"
export PYTHON_WEBHOOK_URL="${PYTHON_WEBHOOK_URL:-http://127.0.0.1:${PORT}/api/v1/webhooks/whatsapp}"

echo "=== [1/4] Running npm install ==="
npm install

echo "=== [2/4] Initializing Database Schema ==="
python init_db.py || echo "init_db note: continuing..."

echo "=== [3/4] Starting WhatsApp Baileys bridge on port 3001 in background ==="
node wa_bridge.js &
WA_BRIDGE_PID=$!
echo "WhatsApp Baileys bridge running with PID: $WA_BRIDGE_PID on port $WA_BRIDGE_PORT"

echo "=== [4/4] Starting Gunicorn server ==="
exec gunicorn app:app --bind 0.0.0.0:"$PORT" --workers "${WEB_CONCURRENCY:-2}" --timeout "${WEBHOOK_TIMEOUT_SECONDS:-120}"
