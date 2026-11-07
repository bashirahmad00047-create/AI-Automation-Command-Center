#!/usr/bin/env bash
set -e

PORT="${PORT:-10000}"
export PORT
export PYTHON_PORT="$PORT"
export WA_BRIDGE_PORT="${WA_BRIDGE_PORT:-3001}"
export BRIDGE_PORT="${BRIDGE_PORT:-3001}"
export PYTHON_WEBHOOK_URL="${PYTHON_WEBHOOK_URL:-http://127.0.0.1:${PORT}/api/v1/webhooks/whatsapp}"
export WA_BRIDGE_INTERNAL="1"
export GUNICORN_STARTED="1"
export NODE_OPTIONS="--max-old-space-size=256"

# Detect Python binary
PYTHON_BIN="python"
if ! command -v python &> /dev/null; then
    PYTHON_BIN="python3"
fi

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

# 0. If external DATABASE_URL is not set, restore SQLite database from online backup snapshot
echo "[start.sh] Checking SQLite database persistence..."
$PYTHON_BIN -c "from backup_targeted import restore_sqlite_from_backup_if_needed; res = restore_sqlite_from_backup_if_needed(); print('[start.sh] SQLite auto-restore completed:', res)" || true

# 1. Synchronously restore WhatsApp Baileys credentials from Database BEFORE starting bridge!
echo "[start.sh] Synchronously restoring WhatsApp credentials from Database into $AUTH_DIR..."
SKIP_WA_BRIDGE_INIT="1" $PYTHON_BIN -c "from wa_bridge_manager import restore_wa_session_from_db; res = restore_wa_session_from_db(); print('[start.sh] Permanent session restored from DB:', res)" || true

# 2. Supervised Node.js Watchdog with OOM crash recovery (Audit Area 14)
# If the Baileys bridge crashes due to OOM during heavy audio transcoding or memory pressure,
# the watchdog detects termination and auto-restarts the bridge process instantly.
bridge_watchdog() {
    echo "[watchdog] Launching Node.js WhatsApp Baileys bridge supervisor..."
    while true; do
        START_TIME=$(date +%s)
        echo "[watchdog] Spawning wa_bridge.js process (max heap: 256MB)..."
        node --max-old-space-size=256 wa_bridge.js >> wa_bridge.log 2>&1 &
        BRIDGE_PID=$!
        echo "[watchdog] Baileys bridge started with PID $BRIDGE_PID"

        # Supervise bridge process
        while kill -0 "$BRIDGE_PID" 2>/dev/null; do
            sleep 4
        done

        # Process exited or crashed (e.g. OOM during audio transcoding)
        wait "$BRIDGE_PID" 2>/dev/null || true
        END_TIME=$(date +%s)
        RUNTIME=$((END_TIME - START_TIME))
        echo "[watchdog] WARNING: wa_bridge.js (PID $BRIDGE_PID) terminated after ${RUNTIME}s (possible OOM or socket fault)"

        # Prevent thrashing if immediate failure occurs
        if [ "$RUNTIME" -lt 3 ]; then
            echo "[watchdog] Rapid exit detected. Throttling 2 seconds..."
            sleep 2
        fi
        echo "[watchdog] Auto-restarting Baileys bridge process instantly..."
    done
}

# Run watchdog in background
bridge_watchdog &
echo "[start.sh] WhatsApp Baileys bridge watchdog active."

# 3. Start Gunicorn with multi-worker & multi-thread configuration for high concurrency without database locking
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-8}"
WORKER_TMP=""
if [ -d "/dev/shm" ]; then
    WORKER_TMP="--worker-tmp-dir /dev/shm"
fi

echo "=== Starting Gunicorn on 0.0.0.0:${PORT:-10000} (Workers: ${GUNICORN_WORKERS}, Threads: ${GUNICORN_THREADS}, Worker Class: gthread) ==="
exec gunicorn app:app \
    --bind 0.0.0.0:"${PORT:-10000}" \
    --workers "${GUNICORN_WORKERS}" \
    --threads "${GUNICORN_THREADS}" \
    --worker-class gthread \
    ${WORKER_TMP} \
    --timeout 120 \
    --keep-alive 5
