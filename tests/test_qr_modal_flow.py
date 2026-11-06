import os
import unittest
from unittest.mock import patch, MagicMock

class TestQrModalFlow(unittest.TestCase):
    def setUp(self):
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_index_html_qr_modal_and_bindings(self):
        index_path = os.path.join(self.repo_dir, "templates", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Check modal structure and elements
        self.assertIn('id="linkWhatsAppQrModal"', html)
        self.assertIn('id="waQrCodeBox"', html)
        self.assertIn('width: 240px; height: 240px;', html)
        self.assertIn('id="qr-code-img"', html)
        self.assertIn('id="bridgeQrImage"', html)
        self.assertIn('id="qr-code-canvas"', html)
        self.assertIn('id="qrLoadingSpinner"', html)

        # Check button IDs and classes
        self.assertIn('id="btn-link-qr"', html)
        self.assertIn('id="btn-qr-relink"', html)
        self.assertIn('btn-qr-sync', html)

        # Check early head functions
        self.assertIn("function openQrModal", html)
        self.assertIn("window.openQrModal = openQrModal", html)
        self.assertIn("function closeQrModal", html)
        self.assertIn("window.closeQrModal = closeQrModal", html)

    def test_single_clean_qr_element_and_no_overlap(self):
        index_path = os.path.join(self.repo_dir, "templates", "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Check that qr-code-img starts with display: none and no broken src="" attribute
        self.assertIn('<img id="qr-code-img" class="qr-code-img" alt="" style="display: none;', html)
        self.assertNotIn('<img id="qr-code-img" class="qr-code-img" src=""', html)

        app_js_path = os.path.join(self.repo_dir, "static", "js", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check that canvas mode removes img src and hides img
        self.assertIn("img.removeAttribute('src')", code)
        self.assertIn("primaryImg.style.display = 'block'", code)
        self.assertIn("qrCanvas.style.display = 'none'", code)

    def test_app_js_qr_functions_and_polling(self):
        app_js_path = os.path.join(self.repo_dir, "static", "js", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check openQrModal & closeQrModal
        self.assertIn("async function openQrModal", code)
        self.assertIn("window.openQrModal = openQrModal;", code)
        self.assertIn("window.openLinkWhatsAppQrModal = openQrModal;", code)
        self.assertIn("function closeQrModal", code)
        self.assertIn("window.closeQrModal = closeQrModal;", code)
        self.assertIn("window.closeLinkWhatsAppQrModal = closeQrModal;", code)

        # Check 3-second polling loop
        self.assertIn("3000", code)
        self.assertIn("waBridgeQrPollTimer = setInterval", code)

        # Check safe element retrieval
        self.assertIn("document.getElementById('qr-code-img')", code)
        self.assertIn("document.getElementById('bridgeQrImage')", code)

        # Check button event bindings
        self.assertIn("#btn-link-qr", code)
        self.assertIn("#btn-qr-relink", code)
        self.assertIn(".btn-qr-sync", code)

    def test_wa_bridge_qr_and_reconnect(self):
        bridge_path = os.path.join(self.repo_dir, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("['/qr', '/api/qr', '/wa/qr', '/reconnect', '/api/reconnect', '/wa/reconnect']", code)
        self.assertIn("isForceRefresh", code)
        self.assertIn("destroyOldSocket()", code)
        self.assertIn("startWhatsAppBridge()", code)
        self.assertIn("qr_image", code)

    def test_flask_api_whatsapp_qr_endpoint(self):
        from app import app
        client = app.test_client()

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"success": true, "status": "qr_ready", "connected": false, "qr": "2@mockqr", "qr_image": "data:image/png;base64,mock"}'
            mock_resp.json.return_value = {
                "success": True,
                "status": "qr_ready",
                "connected": False,
                "qr": "2@mockqr",
                "qr_image": "data:image/png;base64,mock"
            }
            mock_get.return_value = mock_resp

            # Test standard /api/v1/whatsapp/qr
            resp = client.get("/api/v1/whatsapp/qr")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("connected"))
            self.assertEqual(data.get("qr"), "2@mockqr")
            self.assertEqual(data.get("qr_image"), "data:image/png;base64,mock")

            # Test force_refresh=true
            resp_refresh = client.get("/api/v1/whatsapp/qr?force_refresh=true")
            self.assertEqual(resp_refresh.status_code, 200)
            data_refresh = resp_refresh.get_json()
            self.assertTrue(data_refresh.get("success"))

if __name__ == "__main__":
    unittest.main()
