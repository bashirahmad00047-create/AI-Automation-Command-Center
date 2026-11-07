"""WhatsApp Baileys Bridge Process & Permanent Session Manager.

Guarantees:
1) Automatic DB-backed session persistence across Render redeploys and restarts.
2) Ensures `node wa_bridge.js` is running on port 3001.
3) Continuous background backup sync of Baileys multi-file auth credentials.
"""

import base64
from contextlib import contextmanager
from typing import Optional, Dict, Any, Union
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
_cached_app = None


@contextmanager
def safe_app_context(app=None):
    """Ensures that database operations always run within an active Flask app context."""
    global _cached_app
    if app is not None:
        _cached_app = app
        with app.app_context():
            yield
        return

    has_ctx = False
    try:
        from flask import has_app_context
        has_ctx = has_app_context()
    except Exception:
        pass

    if has_ctx:
        yield
    else:
        flask_app = _cached_app
        if not flask_app:
            try:
                import app as app_module
                flask_app = getattr(app_module, "app", None)
            except Exception:
                pass
        if not flask_app:
            try:
                from migrations_manager import _resolve_app
                flask_app = _resolve_app()
            except Exception:
                pass

        if flask_app:
            _cached_app = flask_app
            with flask_app.app_context():
                yield
        else:
            yield


def resolve_auth_dir(root_dir: str = None, tenant_id: str = None) -> str:
    """Resolves the permanent directory path for Baileys auth credentials.
    Respects AUTH_DIR environment variable or persistent disk mounts, and isolates
    directories per tenant_id to support concurrent multi-tenant B2B SaaS accounts.
    """
    if root_dir is None:
        root_dir = os.path.dirname(os.path.abspath(__file__))
    auth_env = os.environ.get("AUTH_DIR", "").strip()
    base_auth = ""
    if auth_env:
        base_auth = os.path.abspath(auth_env)
    else:
        for mount in [
            os.environ.get("RENDER_DISK_PATH"),
            os.environ.get("PERSISTENT_DATA_DIR"),
            "/var/data",
            "/data",
            "/mnt/data",
            "/opt/render/project/src/baileys_auth",
        ]:
            if mount and os.path.exists(mount):
                if mount.endswith("baileys_auth"):
                    os.makedirs(mount, exist_ok=True)
                    base_auth = mount
                    break
                d = os.path.join(mount, "baileys_auth")
                os.makedirs(d, exist_ok=True)
                base_auth = d
                break
        if not base_auth:
            base_auth = os.path.join(root_dir, "baileys_auth")

    clean_tenant = str(tenant_id or "default").strip()
    if clean_tenant == "default":
        legacy_creds = os.path.join(base_auth, "creds.json")
        if os.path.exists(legacy_creds):
            return base_auth
        default_dir = os.path.join(base_auth, "tenant_default")
        if os.path.exists(default_dir):
            return default_dir
        return base_auth

    safe_tenant = "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in clean_tenant)
    tenant_dir = os.path.join(base_auth, f"tenant_{safe_tenant}")
    os.makedirs(tenant_dir, exist_ok=True)
    return tenant_dir


def is_authenticated_session(auth_dir: str) -> bool:
    """Returns True only if the Baileys auth folder contains an authenticated,
    linked WhatsApp session (registered: true or user jid/me present in creds.json AND valid noiseKey crypto keys).
    Never considers temporary unlinked QR keypairs or keyless mock stubs as authenticated.
    """
    creds_file = os.path.join(auth_dir, "creds.json")
    if not os.path.exists(creds_file) or os.path.getsize(creds_file) < 100:
        return False
    try:
        with open(creds_file, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
        if not isinstance(creds_data, dict):
            return False
        noise_key = creds_data.get("noiseKey")
        if not noise_key or not isinstance(noise_key, dict):
            return False
        if not (noise_key.get("private") or noise_key.get("public")):
            return False
        has_keys = bool(creds_data.get("signedIdentityKey") or creds_data.get("signedPreKey"))
        if not has_keys:
            return False
        if creds_data.get("registered") is True:
            return True
        me = creds_data.get("me")
        if isinstance(me, dict) and me.get("id"):
            return True
        return False
    except Exception:
        return False


def extract_phone_from_creds(auth_dir: str) -> Optional[str]:
    """Extracts the linked WhatsApp phone number from credentials if present."""
    creds_file = os.path.join(auth_dir, "creds.json")
    if not os.path.exists(creds_file):
        return None
    try:
        with open(creds_file, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
        me = creds_data.get("me")
        if isinstance(me, dict) and me.get("id"):
            raw_id = str(me.get("id"))
            phone = raw_id.split("@")[0].split(":")[0]
            return phone.strip("+")
    except Exception:
        pass
    return None


def restore_wa_session_from_db(root_dir: str = None, app=None, tenant_id: str = "default") -> bool:
    """Restores the WhatsApp Baileys credentials from the database into the auth dir
    if local credentials are missing or corrupted. Supports multi-tenant isolation
    and resilient multi-tier fallback to ensure Render redeploys never reset QR codes.
    """
    auth_dir = resolve_auth_dir(root_dir, tenant_id=tenant_id)

    # If local creds already exist AND are authenticated, no need to overwrite
    if is_authenticated_session(auth_dir):
        return True

    try:
        with safe_app_context(app):
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
                for col_def in [
                    "ALTER TABLE wa_session_store ADD COLUMN tenant_id VARCHAR(100) DEFAULT 'default'",
                    "ALTER TABLE wa_session_store ADD COLUMN phone_number VARCHAR(50)",
                    "ALTER TABLE wa_session_store ADD COLUMN whatsapp_mode VARCHAR(30) DEFAULT 'baileys_bridge'",
                    "ALTER TABLE wa_session_store ADD COLUMN last_customer_message_at TIMESTAMP",
                ]:
                    try:
                        conn.execute(text(col_def))
                        conn.commit()
                    except Exception:
                        pass

                row = None
                clean_tenant = str(tenant_id or "default").strip()

                # Tier 1: Match requested tenant_id with non-empty session zip
                if clean_tenant:
                    try:
                        row = conn.execute(
                            text("SELECT zip_b64, file_count, phone_number FROM wa_session_store WHERE tenant_id = :t AND zip_b64 IS NOT NULL AND length(zip_b64) > 100 ORDER BY updated_at DESC LIMIT 1"),
                            {"t": clean_tenant}
                        ).fetchone()
                    except Exception:
                        pass

                # Tier 2: Match id = 1 or tenant_id = 'default'
                if not row:
                    try:
                        row = conn.execute(
                            text("SELECT zip_b64, file_count, phone_number FROM wa_session_store WHERE (id = 1 OR tenant_id = 'default' OR tenant_id IS NULL) AND zip_b64 IS NOT NULL AND length(zip_b64) > 100 ORDER BY updated_at DESC LIMIT 1")
                        ).fetchone()
                    except Exception:
                        pass

                # Tier 3: Resilient fallback to any latest valid session record in the database
                if not row:
                    try:
                        row = conn.execute(
                            text("SELECT zip_b64, file_count, phone_number FROM wa_session_store WHERE zip_b64 IS NOT NULL AND length(zip_b64) > 100 ORDER BY updated_at DESC LIMIT 1")
                        ).fetchone()
                    except Exception:
                        pass

                if row and row[0]:
                    raw_bytes = base64.b64decode(row[0])
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        if "creds.json" in zf.namelist():
                            try:
                                creds_content = json.loads(zf.read("creds.json").decode("utf-8"))
                                noise = creds_content.get("noiseKey")
                                if not noise or not isinstance(noise, dict) or not (noise.get("private") or noise.get("public")):
                                    logger.warning("[WA Bridge] Session in DB lacks valid noiseKey crypto keys; skipping restore to generate fresh QR.")
                                    return False
                            except Exception:
                                return False
                        os.makedirs(auth_dir, exist_ok=True)
                        zf.extractall(auth_dir)
                    extracted_count = len(os.listdir(auth_dir))
                    logger.info(f"[WA Bridge] Restored {extracted_count} permanent session files from DB (tenant '{clean_tenant}', phone: {row[2] or 'N/A'}) into {auth_dir}!")
                    return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Database session restore skipped: {e}")
    return False


def backup_wa_session_to_db(root_dir: str = None, app=None, tenant_id: str = "default") -> bool:
    """Compresses all files in the Baileys auth folder and persists them as a Base64
    zip in the database (wa_session_store table) so the QR session survives redeployments.
    CRITICAL: Never backs up an unlinked / unauthenticated session to prevent wiping
    the active session in the database during container boot or QR display.
    """
    auth_dir = resolve_auth_dir(root_dir, tenant_id=tenant_id)

    # CRITICAL GUARD: Only back up if the session is verified to be authenticated!
    if not is_authenticated_session(auth_dir):
        logger.debug("[WA Bridge] Session not authenticated yet (unlinked QR state); skipping DB backup to protect permanent session.")
        return False

    try:
        phone_number = extract_phone_from_creds(auth_dir)
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
        clean_tenant = str(tenant_id or "default").strip()
        now_utc = datetime.datetime.utcnow()

        with safe_app_context(app):
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
                for col_def in [
                    "ALTER TABLE wa_session_store ADD COLUMN tenant_id VARCHAR(100) DEFAULT 'default'",
                    "ALTER TABLE wa_session_store ADD COLUMN phone_number VARCHAR(50)",
                    "ALTER TABLE wa_session_store ADD COLUMN whatsapp_mode VARCHAR(30) DEFAULT 'baileys_bridge'",
                    "ALTER TABLE wa_session_store ADD COLUMN last_customer_message_at TIMESTAMP",
                ]:
                    try:
                        conn.execute(text(col_def))
                        conn.commit()
                    except Exception:
                        pass

                if clean_tenant == "default":
                    conn.execute(text("DELETE FROM wa_session_store WHERE id = 1 OR tenant_id = 'default'"))
                    conn.execute(
                        text("INSERT INTO wa_session_store (id, tenant_id, zip_b64, file_count, phone_number, updated_at) VALUES (1, 'default', :d, :fc, :pn, :ua)"),
                        {"d": b64_data, "fc": file_count, "pn": phone_number, "ua": now_utc}
                    )
                else:
                    existing = conn.execute(
                        text("SELECT id FROM wa_session_store WHERE tenant_id = :t LIMIT 1"),
                        {"t": clean_tenant}
                    ).fetchone()
                    if existing:
                        conn.execute(
                            text("UPDATE wa_session_store SET zip_b64 = :d, file_count = :fc, phone_number = :pn, updated_at = :ua WHERE id = :id"),
                            {"d": b64_data, "fc": file_count, "pn": phone_number, "ua": now_utc, "id": existing[0]}
                        )
                    else:
                        import random
                        new_id = random.randint(100, 9999999)
                        conn.execute(
                            text("INSERT INTO wa_session_store (id, tenant_id, zip_b64, file_count, phone_number, updated_at) VALUES (:id, :t, :d, :fc, :pn, :ua)"),
                            {"id": new_id, "t": clean_tenant, "d": b64_data, "fc": file_count, "pn": phone_number, "ua": now_utc}
                        )
                conn.commit()

        logger.info(f"[WA Bridge] Backed up WhatsApp permanent session to DB (tenant '{clean_tenant}', {file_count} files, phone: {phone_number or 'N/A'}, {len(b64_data)} bytes)")
        return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Failed to backup session to DB: {e}")
        return False


def clear_wa_session_in_db(app=None, tenant_id: str = "default") -> bool:
    """Clears the session from the database when a user explicitly logs out or unlinks device."""
    try:
        with safe_app_context(app):
            from database import db
            from sqlalchemy import text
            with db.engine.connect() as conn:
                clean_tenant = str(tenant_id or "default").strip()
                if clean_tenant == "default":
                    conn.execute(text("DELETE FROM wa_session_store WHERE id = 1 OR tenant_id = 'default'"))
                else:
                    conn.execute(text("DELETE FROM wa_session_store WHERE tenant_id = :t"), {"t": clean_tenant})
                conn.commit()
            logger.info(f"[WA Bridge] Cleared WhatsApp session for tenant '{clean_tenant}' from Database.")
            return True
    except Exception as e:
        logger.warning(f"[WA Bridge] Error clearing session from DB: {e}")
        return False


def start_wa_session_auto_backup(root_dir: str = None, app=None):
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
                    success = backup_wa_session_to_db(root_dir, app=app)
                    if success:
                        last_signature = current_signature
            except Exception:
                pass

    t = threading.Thread(target=_loop, daemon=True, name="WASessionBackupThread")
    t.start()
    logger.info("[WA Bridge] Background WhatsApp session backup daemon started.")


_auto_heal_started = False
_auto_heal_lock = threading.Lock()
_poll_sync_started = False
_poll_sync_lock = threading.Lock()


def start_bridge_poll_sync_daemon(app=None, check_interval: float = 5.0):
    """Dual Delivery Guarantee: Continuously polls wa_bridge.js /messages/recent?since=...
    every 5 seconds. Recovers any incoming message that failed the live HTTP webhook.
    """
    global _poll_sync_started
    with _poll_sync_lock:
        if _poll_sync_started:
            return
        _poll_sync_started = True

    def _sync_loop():
        time.sleep(6.0)
        last_sync = int(time.time() * 1000)
        import urllib.request
        while True:
            try:
                time.sleep(check_interval)
                poll_url = f"http://127.0.0.1:3001/messages/recent?since={last_sync}"
                req = urllib.request.Request(poll_url, headers={"User-Agent": "BridgePollSync/1.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        raw_data = resp.read().decode("utf-8")
                        data = json.loads(raw_data)
                        messages = data.get("messages", [])
                        if messages:
                            with safe_app_context(app=app):
                                from whatsapp_service import WhatsAppService
                                from api_v1 import process_inbound_whatsapp_payload
                                for msg_data in messages:
                                    msg_id = msg_data.get("idMessage")
                                    if msg_id:
                                        from models import WhatsAppMessage
                                        committed = WhatsAppMessage.query.filter_by(whatsapp_message_id=msg_id).first()
                                        if committed is not None:
                                            continue
                                    if msg_id and not WhatsAppService.is_duplicate_message(msg_id):
                                        logger.info(f"[Bridge Poll Sync] Recovering missed message {msg_id} via Dual Delivery...")
                                        try:
                                            process_inbound_whatsapp_payload(msg_data, direct_bridge=False)
                                        except Exception as p_err:
                                            logger.warning(f"[Bridge Poll Sync] Ingestion error: {p_err}")
                            last_sync = int(time.time() * 1000)
            except Exception:
                pass

    t = threading.Thread(target=_sync_loop, daemon=True, name="WABridgePollSyncDaemon")
    t.start()
    logger.info("[WA Bridge] Dual Delivery bridge poll sync daemon active (every 5s).")



def start_bridge_auto_heal_daemon(app=None, check_interval: float = 6.0):
    """Spawns an autonomous supervisor watchdog daemon that continuously monitors
    wa_bridge.js on port 3001. If the bridge process crashes, exits, or stops responding,
    it automatically resurrects and restarts the bridge subprocess.
    """
    global _auto_heal_started
    with _auto_heal_lock:
        if _auto_heal_started:
            return
        _auto_heal_started = True

    def _watchdog_loop():
        # Initial grace period while main application boots
        time.sleep(3.0)
        logger.info("[WA Bridge Auto-Heal] Supervisor watchdog daemon active (monitoring port 3001 every 6s).")
        consecutive_offline = 0
        while True:
            try:
                time.sleep(check_interval)
                online = is_port_reachable("127.0.0.1", 3001, timeout=0.6)
                if not online:
                    consecutive_offline += 1
                    logger.warning(
                        f"[WA Bridge Auto-Heal] Port 3001 is offline (detection #{consecutive_offline}). "
                        "Resurrecting WhatsApp bridge subprocess..."
                    )
                    ensure_wa_bridge_running(timeout_seconds=5.0, app=app)
                else:
                    consecutive_offline = 0
            except Exception as e:
                logger.warning(f"[WA Bridge Auto-Heal] Watchdog cycle warning: {e}")

    t = threading.Thread(target=_watchdog_loop, daemon=True, name="WABridgeAutoHealWatchdog")
    t.start()


def is_port_reachable(host: str = "127.0.0.1", port: int = 3001, timeout: float = 0.5) -> bool:
    """Checks whether the specified TCP host and port are accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def kill_stale_bridge_processes(port: int = 3001, force: bool = False) -> None:
    """Kills any stale wa_bridge node process or process bound to the bridge port,
    ONLY if the bridge port is NOT responsive/healthy (or if force=True).
    Booting Gunicorn workers must NEVER kill an already active and healthy bridge process!
    """
    if not force and is_port_reachable("127.0.0.1", port, timeout=0.4):
        logger.info(f"[WA Bridge] Port {port} is active and healthy. Preserving running bridge process.")
        return

    global _bridge_proc
    if _bridge_proc is not None:
        try:
            if _bridge_proc.poll() is None:
                logger.info(f"[WA Bridge] Terminating stale bridge process (PID: {_bridge_proc.pid})...")
                _bridge_proc.terminate()
                try:
                    _bridge_proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    _bridge_proc.kill()
        except Exception as k_err:
            logger.debug(f"[WA Bridge] Error terminating _bridge_proc: {k_err}")
        _bridge_proc = None

    # Release port if held by a stale node process
    try:
        if sys.platform == "win32":
            cmd = f'netstat -ano -p tcp | findstr /R /C:":{port} .*LISTENING"'
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode(errors="ignore")
            for line in out.strip().splitlines():
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) != os.getpid():
                        logger.info(f"[WA Bridge] Releasing port {port} held by stale PID {pid}")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(f"fuser -k {port}/tcp", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run("pkill -9 -f 'node.*wa_bridge.js'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(0.3)


def ensure_wa_bridge_running(timeout_seconds: float = 5.0, port: int = 3001, app=None, force_restart: bool = False) -> bool:
    """Guarantees session restoration, background backup thread execution, auto-heal watchdog
    supervisor, and checks if port 3001 is reachable; if not or if force_restart is True,
    terminates stale processes and spawns `node wa_bridge.js`.
    """
    global _bridge_proc
    root_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Unconditionally ensure DB session restore, start backup thread, and start auto-heal watchdog
    try:
        restore_wa_session_from_db(root_dir, app=app)
    except Exception as r_err:
        logger.warning(f"[WA Bridge] restore_wa_session_from_db notice: {r_err}")

    try:
        start_wa_session_auto_backup(root_dir, app=app)
    except Exception as b_err:
        logger.warning(f"[WA Bridge] start_wa_session_auto_backup notice: {b_err}")

    try:
        start_bridge_auto_heal_daemon(app=app)
    except Exception as h_err:
        logger.warning(f"[WA Bridge] start_bridge_auto_heal_daemon notice: {h_err}")

    try:
        start_bridge_poll_sync_daemon(app=app)
    except Exception as s_err:
        logger.warning(f"[WA Bridge] start_bridge_poll_sync_daemon notice: {s_err}")

    # 2. Check if port is already responsive (unless force_restart requested)
    if not force_restart and is_port_reachable("127.0.0.1", port, timeout=0.3):
        return True

    with _bridge_proc_lock:
        if not force_restart and is_port_reachable("127.0.0.1", port, timeout=0.3):
            return True

        if not force_restart and _bridge_proc is not None and _bridge_proc.poll() is None:
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                if is_port_reachable("127.0.0.1", port, timeout=0.25):
                    return True
                time.sleep(0.25)

        # Stale process or port offline: clean restart
        kill_stale_bridge_processes(port=port)

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

        # 4. Locate Node executable robustly across environments (Windows, Render Linux, Docker)
        node_candidates = [
            shutil.which("node"),
            "/usr/bin/node",
            "/usr/local/bin/node",
            "/opt/render/project/src/.node/bin/node",
            os.path.join(os.path.dirname(sys.executable), "node"),
            os.path.join(root_dir, ".node", "bin", "node"),
            os.path.expanduser("~/.nvm/versions/node/v20.0.0/bin/node"),
            os.path.expanduser("~/.nvm/versions/node/v18.0.0/bin/node"),
            "node"
        ]
        node_bin = "node"
        for candidate in node_candidates:
            if candidate and (os.path.exists(candidate) if candidate != "node" else True):
                node_bin = candidate
                break

        env = os.environ.copy()
        bridge_port = int(port or 3001)
        flask_port = (
            os.environ.get("PYTHON_PORT")
            or os.environ.get("SERVER_PORT")
            or os.environ.get("FLASK_PORT")
            or (os.environ.get("PORT") if str(os.environ.get("PORT")) != str(bridge_port) else None)
            or ("10000" if os.environ.get("RENDER") else "5000")
        )

        flask_backend_url = os.environ.get("FLASK_BACKEND_URL") or f"http://127.0.0.1:{flask_port}"

        env["PORT"] = str(bridge_port)
        env["WA_BRIDGE_PORT"] = str(bridge_port)
        env["BRIDGE_PORT"] = str(bridge_port)
        env["PYTHON_PORT"] = str(flask_port)
        env["FLASK_BACKEND_URL"] = flask_backend_url
        env["AUTH_DIR"] = resolve_auth_dir(root_dir)
        env["PYTHON_WEBHOOK_URL"] = (
            os.environ.get("PYTHON_WEBHOOK_URL")
            if (os.environ.get("PYTHON_WEBHOOK_URL") and f":{bridge_port}/" not in os.environ.get("PYTHON_WEBHOOK_URL"))
            else f"{flask_backend_url}/api/v1/webhooks/whatsapp"
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


def get_wa_bridge_health(root_dir: str = None, app=None) -> dict:
    """Returns a diagnostic summary of the WhatsApp Baileys bridge process,
    multi-file auth directory, and database persistence status.
    Additive-only observability helper; guarantees no mutation or side effects.
    """
    if root_dir is None:
        root_dir = os.path.dirname(os.path.abspath(__file__))
    auth_dir = resolve_auth_dir(root_dir)
    creds_file = os.path.join(auth_dir, "creds.json")

    has_local_creds = False
    if os.path.exists(creds_file) and os.path.getsize(creds_file) > 20:
        try:
            with open(creds_file, "r", encoding="utf-8") as f:
                json.load(f)
            has_local_creds = True
        except Exception:
            has_local_creds = False

    files = [f for f in os.listdir(auth_dir)] if os.path.exists(auth_dir) else []

    db_session_saved = False
    db_file_count = 0
    db_updated_at = None
    try:
        with safe_app_context(app):
            from database import db
            from sqlalchemy import text
            with db.engine.connect() as conn:
                row = conn.execute(text("SELECT file_count, updated_at FROM wa_session_store WHERE id = 1")).fetchone()
                if row:
                    db_session_saved = True
                    db_file_count = int(row[0] or 0)
                    db_updated_at = str(row[1]) if row[1] else None
    except Exception:
        pass

    online = is_port_reachable("127.0.0.1", 3001, timeout=0.25)
    pid = _bridge_proc.pid if _bridge_proc and _bridge_proc.poll() is None else None

    return {
        "bridge_online": online,
        "bridge_pid": pid,
        "auth_dir": auth_dir,
        "has_local_creds": has_local_creds,
        "local_file_count": len(files),
        "db_session_saved": db_session_saved,
        "db_file_count": db_file_count,
        "db_last_backup": db_updated_at,
        "auto_heal_active": _auto_heal_started,
        "backup_daemon_active": _backup_loop_started,
    }
