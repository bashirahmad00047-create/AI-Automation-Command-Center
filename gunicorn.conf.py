import logging
import os
import threading

logger = logging.getLogger("gunicorn.config")

# Bind configuration: Render assigns PORT dynamically (e.g. 10000)
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "120"))


def on_starting(server):
    """Gunicorn master process startup hook.
    Ensures Node.js dependencies are present and spawns `node wa_bridge.js`
    in a non-blocking background daemon thread so Gunicorn workers bind instantly.
    """
    print("[Gunicorn Startup] Master process online. Spawning WhatsApp bridge supervisor non-blocking...", flush=True)

    def _bg_init():
        try:
            from wa_bridge_manager import ensure_wa_bridge_running
            ready = ensure_wa_bridge_running(timeout_seconds=2.0)
            if ready:
                print("[Gunicorn Background] WhatsApp Baileys Bridge online on port 3001.", flush=True)
            else:
                print("[Gunicorn Background] WhatsApp Baileys Bridge supervisor running.", flush=True)
        except Exception as e:
            print(f"[Gunicorn Background] Bridge supervisor notice: {e}", flush=True)

    threading.Thread(target=_bg_init, daemon=True, name="GunicornBridgeSupervisor").start()
