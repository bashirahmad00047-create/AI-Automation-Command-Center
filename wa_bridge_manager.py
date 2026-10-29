"""WhatsApp Baileys Bridge Process & Permanent Session Manager.

Guarantees:
1) Automatic DB-backed session persistence across Render redeploys and restarts.
2) Ensures `node wa_bridge.js` is running on port 3001.
3) Continuous background backup sync of Baileys multi-file auth credentials.
"""

import base64
from contextlib import contextmanager
import datetime
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

logger = logging.getLogger("wa_bridge_manager")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

_backup_loop_started = False
_backup_lock = threading.Lock()
_bridge_proc = None
_bridge_proc_lock = threading.Lock()


@contextmanager
def safe_app_context():
    """Ensures that database operations always run within an active Flask app context."""
    has_ctx = False
    try:
        from flask import has_app_context
        has_ctx = has_app_context()
    except Exception:
        pass

    if has_ctx:
        yield
    else:
        app = None
        try:
            from migrations_manager import _resolve_app
            app = _resolve_app()
        except Exception:
            pass
        if not app:
            try:
                from app import app as _flask_app
                app = _flask_app
            except Exception:
                pass
        if app:
            with app.app_context():
                yield
        else:
            yield


def resolve_auth_dir(root_dir: str = None) -> str:
    """Resolves the permanent directory path for Baileys auth credentials.
    Respects AUTH_DIR environment variable or persistent disk mounts.
    """
    if root_dir is None:
        root_dir = os.path.dirname(os.path.abspath(__file__))
    auth_env = os.environ.get("AUTH_DIR", "").strip()
    if auth_env:
        return os.path.abspath(auth_env)
    for mount in [os.environ.get("RENDER_DISK_PATH"), os.environ.get("PERSISTENT_DATA_DIR"), "/var/data", "/data"]:
        if mount and os.path.exists(mount):
            d = os.path.join(mount, "baileys_auth")
            os.makedirs(d, exist_ok=True)
            return d
    return os.path.join(root_dir, "baileys_auth")


def restore_wa_session_from_db(root_dir: str = None) -> bool:
    """Restores the WhatsApp Baileys credentials from the database into the auth dir
    if local credentials are missing or corrupted.
    """
    auth_dir = resolve_auth_dir(root_dir)
    creds_file = os.path.join(auth_dir, "creds.json")

    # If valid creds.json already exists, no need to overwrite
    if os.path.exists(creds_file) and os.path.getsize(creds_file) > 20:
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                json.load(f)
            return True
        except Exception:
            logger.warning("[WA Bridge] Existing creds.json is invalid JSON. Restoring from DB backup...")

    try:
        with safe_app_context():
            from database import db
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS wa_session_store (
                        id INT PRIMARY KEY,
                        zip_b64 TEXT NOT NULL,
                        file_count INT DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()
                row = conn.execute(text("SELECT zip_b64 FROM wa_session_store WHERE id = 1")).fetchone()
                if row and row[0]:
                    os.makedirs(auth_dir, exist_ok=True)
                    raw_bytes = base64.b64decode(row[0])
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        zf.extractall(auth_dir)
                    extracted_count = len(os.listdir(auth_dir))
                    logger.info(f"[WA Bridge] Restored {extracted_count} permanent session files from DB into {auth_dir}!")
                    return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Database session restore skipped: {e}")
    return False


def backup_wa_session_to_db(root_dir: str = None) -> bool:
    """Compresses all files in the Baileys auth folder and persists them as a Base64
    zip in the database (wa_session_store table) so the QR session survives redeployments.
    """
    auth_dir = resolve_auth_dir(root_dir)
    creds_file = os.path.join(auth_dir, "creds.json")

    if not os.path.exists(creds_file) or os.path.getsize(creds_file) < 20:
        return False

    try:
        with open(creds_file, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception:
        return False

    try:
        buf = io.BytesIO()
        file_count = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(auth_dir):
                fpath = os.path.join(auth_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=fname)
                    file_count += 1

        if file_count == 0:
            return False

        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

        with safe_app_context():
            from database import db
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS wa_session_store (
                        id INT PRIMARY KEY,
                        zip_b64 TEXT NOT NULL,
                        file_count INT DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("DELETE FROM wa_session_store WHERE id = 1"))
                conn.execute(
                    text("INSERT INTO wa_session_store (id, zip_b64, file_count, updated_at) VALUES (1, :d, :fc, :ua)"),
                    {"d": b64_data, "fc": file_count, "ua": datetime.datetime.utcnow()}
                )
                conn.commit()

        logger.info(f"[WA Bridge] Backed up WhatsApp session to Database ({file_count} files, {len(b64_data)} bytes)")
        return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Failed to backup session to DB: {e}")
        return False


def clear_wa_session_in_db() -> bool:
    """Clears the session from the database when a user explicitly logs out or unlinks device."""
    try:
        with safe_app_context():
            from database import db
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("DELETE FROM wa_session_store WHERE id = 1"))
                conn.commit()
            logger.info("[WA Bridge] Cleared WhatsApp session from Database.")
            return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Error clearing session from DB: {e}")
        return False


def start_wa_session_auto_backup(root_dir: str = None):
    """Spawns a background thread that periodically monitors the Baileys auth folder
    and persists changes to the database whenever credentials update.
    """
    global _backup_loop_started
    with _backup_lock:
        if _backup_loop_started:
            return
        _backup_loop_started = True

    auth_dir = resolve_auth_dir(root_dir)

    def _loop():
        last_signature = None
        while True:
            time.sleep(12)
            try:
                if not os.path.exists(auth_dir):
                    continue
                files = [f for f in os.listdir(auth_dir) if os.path.isfile(os.path.join(auth_dir, f))]
                if not files:
                    continue
                creds_path = os.path.join(auth_dir, "creds.json")
                if not os.path.exists(creds_path):
                    continue

                max_mtime = max(os.path.getmtime(os.path.join(auth_dir, f)) for f in files)
                current_signature = (len(files), max_mtime)

                if current_signature != last_signature:
                    success = backup_wa_session_to_db(root_dir)
                    if success:
                        last_signature = current_signature
            except Exception:
                pass

    t = threading.Thread(target=_loop, daemon=True, name="WASessionBackupThread")
    t.start()
    logger.info("[WA Bridge] Background WhatsApp session backup daemon started.")


def is_port_reachable(host: str = "127.0.0.1", port: int = 3001, timeout: float = 0.5) -> bool:
    """Checks whether the specified TCP host and port are accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def ensure_wa_bridge_running(timeout_seconds: float = 5.0, port: int = 3001) -> bool:
    """Guarantees session restoration, background backup thread execution,
    and checks if port 3001 is reachable; if not, spawns `node wa_bridge.js`.
    """
    global _bridge_proc
    root_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Unconditionally ensure DB session restore and start background backup thread
    try:
        restore_wa_session_from_db(root_dir)
    except Exception as r_err:
        logger.warning(f"[WA Bridge] restore_wa_session_from_db notice: {r_err}")

    try:
        start_wa_session_auto_backup(root_dir)
    except Exception as b_err:
        logger.warning(f"[WA Bridge] start_wa_session_auto_backup notice: {b_err}")

    # 2. Check if port is already responsive
    if is_port_reachable("127.0.0.1", port, timeout=0.3):
        return True

    with _bridge_proc_lock:
        if is_port_reachable("127.0.0.1", port, timeout=0.3):
            return True

        if _bridge_proc is not None and _bridge_proc.poll() is None:
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                if is_port_reachable("127.0.0.1", port, timeout=0.25):
                    return True
                time.sleep(0.25)
            return is_port_reachable("127.0.0.1", port, timeout=0.3)

        bridge_script = os.path.join(root_dir, "wa_bridge.js")
        if not os.path.exists(bridge_script):
            logger.error(f"[WA Bridge] Script not found at {bridge_script}")
            return False

        # 3. Check and provision Node.js & npm packages if node_modules missing
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

        # 4. Locate Node executable
        node_bin = (
            shutil.which("node")
            or os.path.join(os.path.dirname(sys.executable), "node")
            or os.path.join(root_dir, ".node", "bin", "node")
            or "node"
        )

        env = os.environ.copy()
        env["PORT"] = str(port)
        env["WA_BRIDGE_PORT"] = str(port)
        env["AUTH_DIR"] = resolve_auth_dir(root_dir)
        env["PYTHON_WEBHOOK_URL"] = env.get(
            "PYTHON_WEBHOOK_URL",
            f"http://127.0.0.1:{os.environ.get('PORT', '5000')}/api/v1/webhooks/whatsapp"
        )

        # 5. Spawn node wa_bridge.js as detached persistent process
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

        # 6. Wait up to timeout_seconds for port 3001 to become reachable
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if is_port_reachable("127.0.0.1", port, timeout=0.25):
                elapsed = time.time() - start_time
                logger.info(f"[WA Bridge] Port {port} came online successfully in {elapsed:.2f}s!")
                return True
            time.sleep(0.25)

        online = is_port_reachable("127.0.0.1", port, timeout=0.3)
        if online:
            logger.info(f"[WA Bridge] Port {port} is online!")
        else:
            logger.warning(f"[WA Bridge] Port {port} did not respond within {timeout_seconds}s timeout.")
        return online
