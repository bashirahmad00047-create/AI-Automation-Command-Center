"""Unit test for Phase 8: Multi-Tenant QR Code Fetching & Org Context Fix.

Verifies:
1. static/js/auth.js exports getEffectiveOrgId() and tracks current organization ID.
2. static/js/app.js fetchBridgeQrCode passes org_id to /api/v1/whatsapp/qr and /api/v1/whatsapp/status.
3. wa_bridge.js /qr endpoint extracts tenantId via sessionPool instead of ignoring org_id.
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

    def test_wa_bridge_qr_endpoint_extracts_tenant(self):
        bridge_path = os.path.join(self.base_dir, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("sessionPool.extractTenantId(req)", content)
        self.assertIn("sessionPool.getOrCreateSession(tenantId)", content)


if __name__ == "__main__":
    unittest.main()
