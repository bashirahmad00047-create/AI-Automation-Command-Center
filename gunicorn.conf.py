import logging
import os
import shutil
import subprocess
import sys
import threading
import time

logger = logging.getLogger("gunicorn.config")

# Bind configuration: Render assigns PORT dynamically
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "120"))


def on_starting(server):
    """Gunicorn master process startup hook.
    Ensures Node.js dependencies are present and spawns `node wa_bridge.js`
    as a background subprocess when starting on Render.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_script = os.path.join(root_dir, "wa_bridge.js")

    print("[Gunicorn Startup] Initializing WhatsApp Baileys Bridge...", flush=True)

    try:
        from install_node import ensure_node_installed, install_npm_packages
        ensure_node_installed()
        install_npm_packages()
    except Exception as e:
        print(f"[Gunicorn Startup] install_node notice: {e}", flush=True)

    if os.path.exists(bridge_script):
        node_bin = shutil.which("node") or "node"

        # Check if already running on port 3001
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", 3001)) == 0:
                print("[Gunicorn Startup] WhatsApp bridge already active on port 3001.", flush=True)
                s.close()
                return
            s.close()
        except Exception:
            pass

        env = os.environ.copy()
        env["PORT"] = "3001"
        env["WA_BRIDGE_PORT"] = "3001"
        env["PYTHON_WEBHOOK_URL"] = env.get(
            "PYTHON_WEBHOOK_URL",
            f"http://127.0.0.1:{os.environ.get('PORT', '5000')}/api/v1/webhooks/whatsapp"
        )
        try:
            log_file = open(os.path.join(root_dir, "wa_bridge.log"), "a", encoding="utf-8")
            proc = subprocess.Popen(
                [node_bin, bridge_script],
                cwd=root_dir,
                env=env,
                stdout=log_file,
                stderr=log_file
            )
            print(f"[Gunicorn Startup] node wa_bridge.js spawned (PID: {proc.pid}) on port 3001.", flush=True)
        except Exception as spawn_err:
            print(f"[Gunicorn Startup] Failed to spawn wa_bridge.js: {spawn_err}", flush=True)
