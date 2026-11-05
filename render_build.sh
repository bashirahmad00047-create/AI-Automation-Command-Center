#!/usr/bin/env bash
set -e

PYTHON_BIN="python"
if ! command -v python &> /dev/null; then
    PYTHON_BIN="python3"
fi

echo "=== [1/4] Installing Python Dependencies ==="
$PYTHON_BIN -m pip install -r requirements.txt

echo "=== [2/4] Ensuring Node.js & npm Environment ==="
$PYTHON_BIN install_node.py

echo "=== [3/4] Initializing Database Schema & Persistence ==="
$PYTHON_BIN -c "from backup_targeted import restore_sqlite_from_backup_if_needed; restore_sqlite_from_backup_if_needed()" || true
$PYTHON_BIN init_db.py || true

echo "=== [4/4] Render Build Completed Successfully ==="
