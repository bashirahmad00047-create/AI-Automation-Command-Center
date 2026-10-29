#!/usr/bin/env bash
set -e

PORT="${PORT:-10000}"
export PORT
export WA_BRIDGE_PORT="${WA_BRIDGE_PORT:-3001}"
export BRIDGE_PORT="${BRIDGE_PORT:-3001}"
export PYTHON_WEBHOOK_URL="${PYTHON_WEBHOOK_URL:-http://127.0.0.1:${PORT}/api/v1/webhooks/whatsapp}"
export WA_BRIDGE_INTERNAL="1"
export GUNICORN_STARTED="1"
export NODE_OPTIONS="--max-old-space-size=192"

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

# 1. Start WhatsApp Baileys bridge in background with 192MB max heap to protect Render 512MB RAM
(
    sleep 2
    while true; do
        node --max-old-space-size=192 wa_bridge.js >> wa_bridge.log 2>&1 || true
        sleep 3
    done
) &
echo "[start.sh] WhatsApp Baileys bridge supervisor queued in background."

# 2. Run session restore in background after Gunicorn binds
(
    sleep 3
    python -c "from wa_bridge_manager import restore_wa_session_from_db; restore_wa_session_from_db()" >> wa_bridge.log 2>&1 || true
) &
echo "[start.sh] Background DB session restore queued."

# 3. IMMEDIATELY start Gunicorn with 1 worker and 4 threads to stay strictly under Render 512MB RAM
echo "=== Starting Gunicorn immediately on 0.0.0.0:${PORT:-10000} ==="
exec gunicorn app:app --bind 0.0.0.0:"${PORT:-10000}" --workers 1 --threads 4 --timeout 120
