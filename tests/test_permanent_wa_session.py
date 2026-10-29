"""Unit tests for Permanent WhatsApp Baileys QR Session Persistence.

Verifies:
1. WASessionStore table & ORM model.
2. Compressed database backup of Baileys credentials.
3. Clean restoration of credentials on container / filesystem wipe.
4. HTTP endpoints for session sync (/whatsapp/session-state, /session-backup, /session-restore).
5. Guard on /whatsapp/bridge-qr preventing re-scan / re-generation when connected.
6. Explicit /whatsapp/bridge-disconnect endpoint clearing session.
"""

from unittest.mock import patch, MagicMock
import json
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

        # Ensure minimal valid creds.json exists for test environment
        self.auth_dir = resolve_auth_dir()
        os.makedirs(self.auth_dir, exist_ok=True)
        creds_file = os.path.join(self.auth_dir, "creds.json")
        if not os.path.exists(creds_file) or os.path.getsize(creds_file) < 20:
            with open(creds_file, "w", encoding="utf-8") as f:
                json.dump({"me": {"id": "923209350858:1@s.whatsapp.net", "name": "BashFlow"}, "account": {}}, f)

    def tearDown(self):
        self.app_context.pop()

    def test_01_backup_and_db_persistence(self):
        """Verify that existing Baileys auth files are persisted into DB wa_session_store."""
        success = backup_wa_session_to_db()
        self.assertTrue(success, "backup_wa_session_to_db should succeed when credentials exist")

        row = WASessionStore.query.filter_by(id=1).first()
        self.assertIsNotNone(row, "DB wa_session_store row with id=1 should exist")
        self.assertGreater(len(row.zip_b64), 50, "zip_b64 payload should contain compressed data")
        self.assertGreater(row.file_count, 0, "file_count should be greater than 0")

        d = row.to_dict()
        self.assertTrue(d["has_session"])
        self.assertGreater(d["size_bytes"], 50)

    def test_02_restore_from_db_on_wiped_filesystem(self):
        """Simulate a container redeploy / wipe: auth directory is completely empty."""
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

    def test_03_api_session_endpoints(self):
        """Verify the session sync REST endpoints."""
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

    @patch("requests.get")
    def test_04_bridge_qr_guarded_when_connected(self, mock_get):
        """Verify that when bridge is connected, /whatsapp/bridge-qr never re-generates QR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "connected",
            "connected": True,
            "user": {"id": "923209350858:1@s.whatsapp.net"}
        }
        mock_get.return_value = mock_resp

        resp = self.client.get("/api/v1/whatsapp/bridge-qr")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("connected"))
        self.assertEqual(data.get("status"), "connected")
        self.assertIsNone(data.get("qrUrl"))

    @patch("requests.post")
    def test_05_bridge_disconnect(self, mock_post):
        """Verify explicit disconnect unlinks and cleans DB session."""
        backup_wa_session_to_db()
        self.assertIsNotNone(WASessionStore.query.filter_by(id=1).first())

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true}'
        mock_resp.json.return_value = {"success": True}
        mock_post.return_value = mock_resp

        resp = self.client.post("/api/v1/whatsapp/bridge-disconnect")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        # Check DB session was cleared
        self.assertIsNone(WASessionStore.query.filter_by(id=1).first())


if __name__ == "__main__":
    unittest.main()
