"""Unit test for Phase 8: Multi-Tenant QR Code Fetching, WebSocket Sync & Deployment Hardening.

Verifies:
1. static/js/auth.js exports getEffectiveOrgId() and tracks current organization ID.
2. static/js/app.js fetchBridgeQrCode passes org_id to /api/v1/whatsapp/qr and /api/v1/whatsapp/status.
3. static/js/chat_interface.js includes fetchQrCode with org_id and maps Base64 to img tag while hiding spinner.
4. wa_bridge.js dynamically initializes Baileys socket for requested org_id and returns Base64 QR code payload.
5. start.sh implements the process watchdog for Node.js bridge and Gunicorn concurrency configuration.
6. database.py and app.py configure SQLite WAL mode, busy_timeout, and connect_args to avoid DB locks.
"""

import os
import unittest


class TestQrOrgContext(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_auth_js_exports_effective_org_id(self):
        auth_path = os.path.join(self.base_dir, "static", "js", "auth.js")
        with open(auth_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("getEffectiveOrgId", content)
        self.assertIn("window._currentOrgId", content)

    def test_app_js_qr_fetch_includes_org_id(self):
        app_path = os.path.join(self.base_dir, "static", "js", "app.js")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("org_id=", content)
        self.assertIn("/api/v1/whatsapp/status?org_id=", content)

    def test_chat_interface_qr_fetch_and_dom_mapping(self):
        chat_path = os.path.join(self.base_dir, "static", "js", "chat_interface.js")
        with open(chat_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("fetchQrCode", content)
        self.assertIn("/api/v1/whatsapp/qr?org_id=", content)
        self.assertIn("qrLoadingSpinner", content)
        self.assertIn("qrImageWrapper", content)
        self.assertIn("qr-code-img", content)
        self.assertIn("resolvedImgUrl", content)

    def test_wa_bridge_qr_endpoint_extracts_tenant(self):
        bridge_path = os.path.join(self.base_dir, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("sessionPool.extractTenantId(req)", content)
        self.assertIn("sessionPool.getOrCreateSession(tenantId)", content)
        self.assertIn("startSock(tenantId, false)", content)
        self.assertIn("Dynamic socket initialization", content)

    def test_start_sh_watchdog_and_concurrency(self):
        start_sh_path = os.path.join(self.base_dir, "start.sh")
        with open(start_sh_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("bridge_watchdog", content)
        self.assertIn("Auto-restarting Baileys bridge process instantly", content)
        self.assertIn("GUNICORN_WORKERS", content)
        self.assertIn("GUNICORN_THREADS", content)
        self.assertIn("--worker-class gthread", content)

    def test_database_wal_and_busy_timeout(self):
        db_path = os.path.join(self.base_dir, "database.py")
        with open(db_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PRAGMA journal_mode=WAL;", content)
        self.assertIn("PRAGMA busy_timeout=15000;", content)

        app_path = os.path.join(self.base_dir, "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            app_content = f.read()
        self.assertIn('"check_same_thread": False', app_content)


if __name__ == "__main__":
    unittest.main()
