import logging
import os
import shutil
import subprocess
import sys
import threading
import time

logger = logging.getLogger("gunicorn.config")

# Bind configuration
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "120"))


def on_starting(server):
    """Gunicorn master process startup hook.
    Ensures Node.js dependencies are installed and spawns `node wa_bridge.js`
    as a background subprocess when starting on Render.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_script = os.path.join(root_dir, "wa_bridge.js")
    node_modules_dir = os.path.join(root_dir, "node_modules")
    package_json = os.path.join(root_dir, "package.json")

    print("[Gunicorn Startup] Checking WhatsApp Baileys Bridge dependencies...", flush=True)

    # 1. Install npm packages if node_modules does not exist
    if os.path.exists(package_json) and not os.path.exists(node_modules_dir):
        npm_bin = shutil.which("npm") or "npm"
        print(f"[Gunicorn Startup] Running {npm_bin} install in {root_dir}...", flush=True)
        try:
            subprocess.run([npm_bin, "install"], cwd=root_dir, check=True, timeout=180)
            print("[Gunicorn Startup] npm packages installed successfully.", flush=True)
        except Exception as npm_err:
            print(f"[Gunicorn Startup] npm install error: {npm_err}", flush=True)

    # 2. Spawn node wa_bridge.js as background subprocess
    if os.path.exists(bridge_script):
        node_bin = shutil.which("node") or "node"
        env = os.environ.copy()
        env["PORT"] = "3001"
        env["PYTHON_WEBHOOK_URL"] = env.get(
            "PYTHON_WEBHOOK_URL",
            f"http://localhost:{os.environ.get('PORT', '5000')}/api/v1/webhooks/whatsapp"
        )
        try:
            proc = subprocess.Popen(
                [node_bin, bridge_script],
                cwd=root_dir,
                env=env
            )
            print(f"[Gunicorn Startup] node wa_bridge.js spawned successfully (PID: {proc.pid}) on port 3001.", flush=True)
        except Exception as spawn_err:
            print(f"[Gunicorn Startup] Failed to spawn wa_bridge.js: {spawn_err}", flush=True)
