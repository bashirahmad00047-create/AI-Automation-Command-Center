"""Unit tests for Permanent WhatsApp Baileys QR Session Persistence.

Verifies:
1. WASessionStore table & ORM model.
2. Compressed database backup of Baileys credentials.
3. Clean restoration of credentials on container / filesystem wipe.
4. HTTP endpoints for session sync (/whatsapp/session-state, /session-backup, /session-restore).
"""

import os
import shutil
import tempfile
import unittest
from app import app
from database import db
from models import WASessionStore
from wa_bridge_manager import (
    backup_wa_session_to_db,
    restore_wa_session_from_db,
    clear_wa_session_in_db,
    resolve_auth_dir,
)


class TestPermanentWASession(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        self.app_context.pop()

    def test_01_backup_and_db_persistence(self):
        """Verify that existing Baileys auth files are persisted into DB wa_session_store."""
        success = backup_wa_session_to_db()
        self.assertTrue(success, "backup_wa_session_to_db should succeed when credentials exist")

        row = WASessionStore.query.filter_by(id=1).first()
        self.assertIsNotNone(row, "DB wa_session_store row with id=1 should exist")
        self.assertGreater(len(row.zip_b64), 100, "zip_b64 payload should contain compressed data")
        self.assertGreater(row.file_count, 0, "file_count should be greater than 0")

        d = row.to_dict()
        self.assertTrue(d["has_session"])
        self.assertGreater(d["size_bytes"], 100)

    def test_02_restore_from_db_on_wiped_filesystem(self):
        """Simulate a container redeploy / wipe: auth directory is completely empty."""
        # Ensure session is backed up first
        backup_wa_session_to_db()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_auth = os.path.join(tmpdir, "baileys_auth")
            self.assertFalse(os.path.exists(target_auth))

            # Run restoration targeting the clean temporary directory
            restored = restore_wa_session_from_db(tmpdir)
            self.assertTrue(restored, "Restoration from DB should succeed")
            self.assertTrue(os.path.exists(target_auth), "Auth directory should be recreated")

            creds_file = os.path.join(target_auth, "creds.json")
            self.assertTrue(os.path.exists(creds_file), "creds.json should be restored")
            self.assertGreater(os.path.getsize(creds_file), 20, "creds.json should contain valid data")

            # Check file count in restored directory
            restored_count = len(os.listdir(target_auth))
            self.assertGreater(restored_count, 10, "Multiple Baileys session files should be restored")

    def test_03_api_session_endpoints(self):
        """Verify the session sync REST endpoints."""
        # Ensure session exists in DB
        backup_wa_session_to_db()

        # 1. GET /api/v1/whatsapp/session-state
        resp = self.client.get("/api/v1/whatsapp/session-state")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("has_saved_session"))
        self.assertGreater(data.get("file_count", 0), 0)

        # 2. POST /api/v1/whatsapp/session-backup
        resp2 = self.client.post("/api/v1/whatsapp/session-backup")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertTrue(data2.get("success"))

        # 3. GET /api/v1/whatsapp/session-restore
        resp3 = self.client.get("/api/v1/whatsapp/session-restore")
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.get_json()
        self.assertTrue(data3.get("success"))
        self.assertTrue(data3.get("restored"))


if __name__ == "__main__":
    unittest.main()
