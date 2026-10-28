"""WhatsApp Baileys Bridge Process Manager.

Ensures that the Node.js Baileys bridge is running on port 3001.
If port 3001 is unreachable, installs missing node dependencies (npm install)
and spawns `node wa_bridge.js` using subprocess.Popen, waiting up to 5 seconds
for port 3001 to come online.
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

logger = logging.getLogger("wa_bridge_manager")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

import base64, json, zipfile, io
from sqlalchemy import text

def _restore_wa_auth_from_db(root_dir):
    try:
        from app import app
        from database import db
        auth_dir = os.path.join(root_dir, "auth_info_baileys")
        creds_file = os.path.join(auth_dir, "creds.json")
        if os.path.exists(creds_file):
            return
        with app.app_context():
            db.session.execute(text("CREATE TABLE IF NOT EXISTS wa_session_store (id INT PRIMARY KEY, zip_b64 TEXT)"))
            db.session.commit()
            row = db.session.execute(text("SELECT zip_b64 FROM wa_session_store WHERE id = 1")).fetchone()
            if row and row[0]:
                os.makedirs(auth_dir, exist_ok=True)
                zf = zipfile.ZipFile(io.BytesIO(base64.b64decode(row[0])))
                zf.extractall(auth_dir)
                logger.info("[WA Bridge] Restored permanent WhatsApp session from Database!")
    except Exception as e:
        logger.warning(f"[WA Bridge] DB session restore skipped: {e}")

def _start_wa_auth_backup_loop(root_dir):
    def _loop():
        last_mtime = 0
        auth_dir = os.path.join(root_dir, "auth_info_baileys")
        while True:
            time.sleep(10)
            try:
                creds_file = os.path.join(auth_dir, "creds.json")
                if not os.path.exists(creds_file):
                    continue
                mtime = os.path.getmtime(creds_file)
                if mtime == last_mtime:
                    continue
                last_mtime = mtime
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in os.listdir(auth_dir):
                        fpath = os.path.join(auth_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, arcname=fname)
                b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
                from app import app
                from database import db
                with app.app_context():
                    db.session.execute(text("CREATE TABLE IF NOT EXISTS wa_session_store (id INT PRIMARY KEY, zip_b64 TEXT)"))
                    db.session.execute(text("DELETE FROM wa_session_store WHERE id = 1"))
                    db.session.execute(text("INSERT INTO wa_session_store (id, zip_b64) VALUES (1, :d)"), {"d": b64_data})
                    db.session.commit()
            except Exception:
                pass
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
_bridge_proc = None
_bridge_proc_lock = threading.Lock()


def is_port_reachable(host: str = "127.0.0.1", port: int = 3001, timeout: float = 0.5) -> bool:
    """Checks whether the specified TCP host and port are accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def ensure_wa_bridge_running(timeout_seconds: float = 5.0, port: int = 3001) -> bool:
    """Checks if port 3001 is reachable; if not, automatically runs `npm install`
    (if node_modules is missing) and spawns `node wa_bridge.js` using subprocess.Popen,
    waiting up to `timeout_seconds` (default: 5s) for port 3001 to come online.
    """
    global _bridge_proc

    # 1. Quick check if port is already responsive
    if is_port_reachable("127.0.0.1", port, timeout=0.3):
        return True

    with _bridge_proc_lock:
        # Re-check under lock in case another thread just spawned it
        if is_port_reachable("127.0.0.1", port, timeout=0.3):
            return True

        # If a subprocess was already launched and is still running, avoid duplicate spawns
        if _bridge_proc is not None and _bridge_proc.poll() is None:
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                if is_port_reachable("127.0.0.1", port, timeout=0.25):
                    return True
                time.sleep(0.25)
            return is_port_reachable("127.0.0.1", port, timeout=0.3)

        root_dir = os.path.dirname(os.path.abspath(__file__))
        _restore_wa_auth_from_db(root_dir); _start_wa_auth_backup_loop(root_dir); bridge_script = os.path.join(root_dir, "wa_bridge.js")
        if not os.path.exists(bridge_script):
            logger.error(f"[WA Bridge] Script not found at {bridge_script}")
            return False

        # 2. Check and provision Node.js & npm packages if node_modules missing
        node_modules = os.path.join(root_dir, "node_modules")
        baileys_dir = os.path.join(node_modules, "@whiskeysockets", "baileys")
        qrcode_dir = os.path.join(node_modules, "qrcode")
        if not (os.path.exists(node_modules) and os.path.exists(baileys_dir) and os.path.exists(qrcode_dir)):
            logger.info("[WA Bridge] node_modules missing or incomplete. Running npm install...")
            try:
                from install_node import ensure_node_installed, install_npm_packages
                ensure_node_installed()
                install_npm_packages()
            except Exception as setup_err:
                logger.warning(f"[WA Bridge] install_node note: {setup_err}")

        # 3. Locate Node executable
        node_bin = (
            shutil.which("node")
            or os.path.join(os.path.dirname(sys.executable), "node")
            or os.path.join(root_dir, ".node", "bin", "node")
            or "node"
        )

        env = os.environ.copy()
        env["PORT"] = str(port)
        env["WA_BRIDGE_PORT"] = str(port)
        env["PYTHON_WEBHOOK_URL"] = env.get(
            "PYTHON_WEBHOOK_URL",
            f"http://127.0.0.1:{os.environ.get('PORT', '5000')}/api/v1/webhooks/whatsapp"
        )

        # 4. Spawn node wa_bridge.js as detached persistent process
        try:
            log_path = os.path.join(root_dir, "wa_bridge.log")
            with open(log_path, "a", encoding="utf-8") as log_out:
                popen_kwargs = {
                    "cwd": root_dir,
                    "env": env,
                    "stdout": log_out,
                    "stderr": log_out,
                }
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    )
                else:
                    popen_kwargs["start_new_session"] = True

                _bridge_proc = subprocess.Popen(
                    [node_bin, bridge_script],
                    **popen_kwargs
                )
            logger.info(f"[WA Bridge] Subprocess spawned (PID: {_bridge_proc.pid}) on port {port}")
        except Exception as spawn_err:
            logger.error(f"[WA Bridge] Failed to spawn {bridge_script}: {spawn_err}")
            return False

        # 5. Wait up to timeout_seconds for port 3001 to become reachable
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if is_port_reachable("127.0.0.1", port, timeout=0.25):
                elapsed = time.time() - start_time
                logger.info(f"[WA Bridge] Port {port} came online successfully in {elapsed:.2f}s!")
                return True
            time.sleep(0.25)

        # Final check
        online = is_port_reachable("127.0.0.1", port, timeout=0.3)
        if online:
            logger.info(f"[WA Bridge] Port {port} is online!")
        else:
            logger.warning(f"[WA Bridge] Port {port} did not respond within {timeout_seconds}s timeout.")
        return online

