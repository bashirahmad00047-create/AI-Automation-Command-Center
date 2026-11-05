"""Database backup and persistence utilities for OpsFlow SaaS."""

import datetime
import io
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from typing import Optional

logger = logging.getLogger("backup_targeted")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_sync_loop_started = False
_sync_lock = threading.Lock()


def restore_sqlite_from_backup_if_needed(
    db_path: Optional[str] = None,
    backup_candidates: Optional[list] = None
) -> bool:
    """Restores SQLite database file on container boot if primary DB file is missing
    or empty, preventing loss of orders, leads, and WhatsApp sessions across Render redeploys.
    Restores to both project root and instance/ folders to guarantee complete compatibility.
    """
    raw_db_url = os.environ.get("DATABASE_URL", "").strip()
    if raw_db_url and not raw_db_url.startswith("sqlite"):
        # External PostgreSQL is active, no SQLite restore needed
        return False

    candidates = backup_candidates or [
        os.path.join(BASE_DIR, "opsflow_saas_online_backup.db"),
        os.path.join(BASE_DIR, "opsflow_saas_backup.db"),
    ]

    target_paths = [db_path] if db_path else [
        os.path.join(BASE_DIR, "opsflow_saas.db"),
        os.path.join(BASE_DIR, "instance", "opsflow_saas.db"),
    ]

    restored_any = False
    for target_db in target_paths:
        target_dir = os.path.dirname(target_db)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        current_size = os.path.getsize(target_db) if os.path.exists(target_db) else 0
        if current_size < 100000:
            for bpath in candidates:
                if os.path.exists(bpath) and os.path.getsize(bpath) > 100000:
                    try:
                        shutil.copy2(bpath, target_db)
                        logger.info(f"[SQLite Restore] Successfully restored database from '{bpath}' ({os.path.getsize(target_db)} bytes) -> '{target_db}'")
                        restored_any = True
                        break
                    except Exception as e:
                        logger.warning(f"[SQLite Restore] Failed copying '{bpath}' to '{target_db}': {e}")

    # Immediately unpack WhatsApp session credentials from restored DB so restored=True on boot
    try:
        from wa_bridge_manager import restore_wa_session_from_db
        restore_wa_session_from_db()
    except Exception as _wa_err:
        logger.debug(f"[SQLite Restore] Post-restore WhatsApp session unpack note: {_wa_err}")

    return restored_any


def sync_sqlite_snapshot(
    db_path: Optional[str] = None,
    backup_path: Optional[str] = None
) -> bool:
    """Performs an atomic, thread-safe SQLite online backup using the SQLite Backup API.
    Safely captures the active database and WAL state into the backup file without locking readers/writers.
    """
    raw_db_url = os.environ.get("DATABASE_URL", "").strip()
    if raw_db_url and not raw_db_url.startswith("sqlite"):
        return False

    dest_path = backup_path or os.path.join(BASE_DIR, "opsflow_saas_online_backup.db")

    if db_path:
        source_candidates = [db_path]
    else:
        source_candidates = [
            os.path.join(BASE_DIR, "instance", "opsflow_saas.db"),
            os.path.join(BASE_DIR, "opsflow_saas.db"),
        ]

    # Select the largest existing active SQLite database
    valid_sources = [p for p in source_candidates if os.path.exists(p) and os.path.getsize(p) >= 10000]
    if not valid_sources:
        return False

    source_path = max(valid_sources, key=lambda p: os.path.getsize(p))

    try:
        src = sqlite3.connect(source_path, timeout=10.0)
        dst = sqlite3.connect(dest_path, timeout=10.0)
        with dst:
            src.backup(dst, pages=100, sleep=0.01)
            try:
                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 15000000:
                    dst.execute("VACUUM")
            except Exception:
                pass
        dst.close()
        src.close()
        logger.debug(f"[SQLite Snapshot] Successfully synced snapshot from '{source_path}' to '{dest_path}'")
        return True
    except Exception as e:
        logger.warning(f"[SQLite Snapshot] Error syncing snapshot: {e}")
        return False


def start_periodic_sqlite_snapshot_sync(interval_seconds: int = 60):
    """Spawns a background daemon thread that periodically checkpoints SQLite data
    into opsflow_saas_online_backup.db.
    """
    global _sync_loop_started
    with _sync_lock:
        if _sync_loop_started:
            return
        _sync_loop_started = True

    def _loop():
        time.sleep(10)  # Initial grace period after startup
        while True:
            try:
                sync_sqlite_snapshot()
            except Exception as _e:
                logger.debug(f"[Periodic Sync] Exception: {_e}")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="SQLite-Snapshot-Sync")
    t.start()
    logger.info(f"[SQLite Snapshot] Background periodic snapshot sync started (interval: {interval_seconds}s)")


def run_targeted_cleanup_backup():
    from app import app
    from models import db, AutomationRule, WorkflowExecution, ExecutionStep, AuditLog

    with app.app_context():
        all_rules = AutomationRule.query.all()
        test_artifacts = [r for r in all_rules if not (r.id.startswith('template-') or r.id.startswith('blueprint-'))]

        backup_data = {
            "rules": [],
            "executions": [],
            "steps": [],
            "audits": []
        }

        rule_ids = set()
        for r in test_artifacts:
            backup_data["rules"].append(r.to_dict() if hasattr(r, 'to_dict') else {c.name: getattr(r, c.name) for c in r.__table__.columns})
            rule_ids.add(r.id)

        for r_id in rule_ids:
            execs = WorkflowExecution.query.filter_by(rule_id=r_id).all()
            for ex in execs:
                backup_data["executions"].append({c.name: getattr(ex, c.name) for c in ex.__table__.columns})
                steps = ExecutionStep.query.filter_by(execution_id=ex.id).all()
                for st in steps:
                    backup_data["steps"].append({c.name: getattr(st, c.name) for c in st.__table__.columns})

            audits = AuditLog.query.filter_by(resource_id=r_id).all()
            for au in audits:
                backup_data["audits"].append({c.name: getattr(au, c.name) for c in au.__table__.columns})

        def default_serializer(obj):
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            return str(obj)

        backup_path = os.path.join(os.getcwd(), 'targeted_cleanup_backup.json')
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, default=default_serializer, indent=2)

        print(f"Backup created at: {backup_path}")
        print(f"Backed up Rules: {len(backup_data['rules'])}")
        print(f"Backed up Executions: {len(backup_data['executions'])}")
        print(f"Backed up Steps: {len(backup_data['steps'])}")
        print(f"Backed up Audits: {len(backup_data['audits'])}")


if __name__ == "__main__":
    run_targeted_cleanup_backup()
