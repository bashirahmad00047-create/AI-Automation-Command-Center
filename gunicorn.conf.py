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
    print("[Gunicorn Startup] Initializing WhatsApp Baileys Bridge...", flush=True)
    try:
        from wa_bridge_manager import ensure_wa_bridge_running
        ready = ensure_wa_bridge_running(timeout_seconds=5.0)
        if ready:
            print("[Gunicorn Startup] WhatsApp Baileys Bridge verified online on port 3001.", flush=True)
        else:
            print("[Gunicorn Startup] WhatsApp Baileys Bridge starting in background.", flush=True)
    except Exception as e:
        print(f"[Gunicorn Startup] Bridge startup notice: {e}", flush=True)
