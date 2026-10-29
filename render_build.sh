#!/usr/bin/env bash
set -e

echo "=== [1/4] Installing Python Dependencies ==="
pip install -r requirements.txt

echo "=== [2/4] Ensuring Node.js & npm Environment ==="
python install_node.py

echo "=== [3/4] Initializing Database Schema ==="
python init_db.py || true

echo "=== [4/4] Render Build Completed Successfully ==="
