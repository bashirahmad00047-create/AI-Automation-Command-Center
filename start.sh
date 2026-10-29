#!/usr/bin/env bash
set -e

PORT="${PORT:-5000}"
export PORT
export WA_BRIDGE_PORT="${WA_BRIDGE_PORT:-3001}"
export BRIDGE_PORT="${BRIDGE_PORT:-3001}"
export PYTHON_WEBHOOK_URL="${PYTHON_WEBHOOK_URL:-http://127.0.0.1:${PORT}/api/v1/webhooks/whatsapp}"

# Ensure node is in PATH if installed in local project directory
if [ -d "$(pwd)/.node/node-v20.18.0-linux-x64/bin" ]; then
    export PATH="$(pwd)/.node/node-v20.18.0-linux-x64/bin:$PATH"
elif [ -d "$(pwd)/.node/bin" ]; then
    export PATH="$(pwd)/.node/bin:$PATH"
fi

# Configure Baileys multi-file auth persistence directory
if [ -z "$AUTH_DIR" ]; then
    if [ -d "/var/data" ]; then
        export AUTH_DIR="/var/data/baileys_auth"
    elif [ -d "/data" ]; then
        export AUTH_DIR="/data/baileys_auth"
    elif [ -n "$RENDER_DISK_PATH" ] && [ -d "$RENDER_DISK_PATH" ]; then
        export AUTH_DIR="${RENDER_DISK_PATH}/baileys_auth"
    else
        export AUTH_DIR="$(pwd)/baileys_auth"
    fi
fi
export AUTH_DIR
mkdir -p "$AUTH_DIR" 2>/dev/null || true

# 1. Start WhatsApp Baileys bridge in a detached background loop (non-blocking)
(
    if [ ! -d "node_modules/@whiskeysockets/baileys" ] || [ ! -d "node_modules/qrcode" ]; then
        npm install --omit=dev --no-audit --no-fund 2>/dev/null || true
    fi
    while true; do
        node wa_bridge.js 2>&1 || echo "[Bridge Supervisor] wa_bridge.js exited ($?)."
        sleep 2
    done
) &
WA_BRIDGE_SUPERVISOR_PID=$!
echo "WhatsApp Baileys bridge supervisor running in background (PID: $WA_BRIDGE_SUPERVISOR_PID)"

# 2. Asynchronously run DB initialization & permanent session restore in background (non-blocking)
(
    python init_db.py 2>/dev/null || true
    python -c "from wa_bridge_manager import restore_wa_session_from_db; restore_wa_session_from_db()" 2>/dev/null || true
) &

# 3. IMMEDIATELY start Gunicorn so Flask binds to 0.0.0.0:$PORT within <1s for Render health check
echo "=== Starting Gunicorn immediately on 0.0.0.0:$PORT ==="
exec gunicorn app:app --bind 0.0.0.0:"$PORT" --workers "${WEB_CONCURRENCY:-2}" --timeout "${WEBHOOK_TIMEOUT_SECONDS:-120}"
