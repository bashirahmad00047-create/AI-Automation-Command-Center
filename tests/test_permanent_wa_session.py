"""Unit tests for Permanent WhatsApp Baileys QR Session Persistence.

Verifies:
1. WASessionStore table & ORM model.
2. Compressed database backup of Baileys credentials.
3. Clean restoration of credentials on container / filesystem wipe.
4. HTTP endpoints for session sync (/whatsapp/session-state, /session-backup, /session-restore).
5. Guard on /whatsapp/bridge-qr preventing re-scan / re-generation when connected.
6. Explicit /whatsapp/bridge-disconnect endpoint clearing session.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
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
                json.dump({"registered": True, "me": {"id": "923209350858:1@s.whatsapp.net", "name": "BashFlow"}, "noiseKey": {"private": "dGVzdF9wcml2", "public": "dGVzdF9wdWI="}, "signedIdentityKey": {"private": "dGVzdF9pZF9wcml2", "public": "dGVzdF9pZF9wdWI="}, "signedPreKey": {"keyPair": {"private": "dGVzdF9wcmVfcHJpdg==", "public": "dGVzdF9wcmVfcHVi"}, "signature": "dGVzdF9zaWc="}, "account": {}}, f)

        # Set up authenticated session for client
        with self.client.session_transaction() as sess:
            sess["user_id"] = "usr-admin-primary"
            sess["is_super_admin"] = True
            sess["user_email"] = "admin@opsflow.io"
            sess["active_org_id"] = "org-enterprise-default"

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

    def test_06_unauthenticated_creds_never_overwrite_db(self):
        """CRITICAL: Unlinked / unauthenticated QR keypair must NEVER overwrite DB permanent session."""
        from wa_bridge_manager import is_authenticated_session, backup_wa_session_to_db
        # 1. Ensure authenticated session is saved in DB
        backup_wa_session_to_db()
        saved_before = WASessionStore.query.filter_by(id=1).first()
        self.assertIsNotNone(saved_before)
        orig_zip = saved_before.zip_b64

        # 2. Create unauthenticated temp directory (registered: False, no user jid)
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_dir = os.path.join(tmpdir, "baileys_auth")
            os.makedirs(auth_dir, exist_ok=True)
            with open(os.path.join(auth_dir, "creds.json"), "w", encoding="utf-8") as f:
                json.dump({"registered": False, "noiseKey": {"private": "abc", "public": "def"}}, f)

            # Verification: is_authenticated_session must return False
            self.assertFalse(is_authenticated_session(auth_dir))

            # Backup attempt on unauthenticated creds MUST return False
            success = backup_wa_session_to_db(tmpdir)
            self.assertFalse(success, "backup_wa_session_to_db must refuse to backup unauthenticated creds")

        # 3. Verify original session in DB was preserved intact
        saved_after = WASessionStore.query.filter_by(id=1).first()
        self.assertEqual(saved_after.zip_b64, orig_zip, "DB session must remain untouched")

    def test_07_restore_overwrites_unauthenticated_local_creds(self):
        """When local folder has unauthenticated creds, restore MUST overwrite them with DB session."""
        from wa_bridge_manager import is_authenticated_session, restore_wa_session_from_db
        # Ensure authenticated session in DB
        backup_wa_session_to_db()

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_dir = os.path.join(tmpdir, "baileys_auth")
            os.makedirs(auth_dir, exist_ok=True)
            creds_path = os.path.join(auth_dir, "creds.json")
            # Write unauthenticated placeholder
            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump({"registered": False, "dummy": True}, f)

            self.assertFalse(is_authenticated_session(auth_dir))

            # Restoration must detect local creds are unauthenticated and restore from DB
            restored = restore_wa_session_from_db(tmpdir)
            self.assertTrue(restored, "Restoration must succeed")
            self.assertTrue(is_authenticated_session(auth_dir), "Restored creds must be authenticated")

    def test_08_extract_phone_from_creds(self):
        """Verify phone number is cleanly extracted from credentials."""
        from wa_bridge_manager import extract_phone_from_creds
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_dir = os.path.join(tmpdir, "baileys_auth")
            os.makedirs(auth_dir, exist_ok=True)
            with open(os.path.join(auth_dir, "creds.json"), "w", encoding="utf-8") as f:
                json.dump({"me": {"id": "923001234567:5@s.whatsapp.net", "name": "Test"}}, f)

            phone = extract_phone_from_creds(auth_dir)
            self.assertEqual(phone, "923001234567")

    def test_09_multitier_tenant_fallback(self):
        """Verify resilient multi-tier fallback restores session even with custom tenant."""
        from wa_bridge_manager import restore_wa_session_from_db, is_authenticated_session
        backup_wa_session_to_db(tenant_id="default")

        with tempfile.TemporaryDirectory() as tmpdir:
            restored = restore_wa_session_from_db(tmpdir, tenant_id="tenant-custom-tenant-99")
            self.assertTrue(restored, "Should fallback to available DB session")
            target_auth = os.path.join(tmpdir, "baileys_auth")
            self.assertTrue(is_authenticated_session(target_auth))


if __name__ == "__main__":
    unittest.main()
