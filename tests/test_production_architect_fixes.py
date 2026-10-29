import unittest
import base64
from app import create_app
from database import db
from models import WhatsAppMessage, User, Organization


class ProductionArchitectFixesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_session_configuration_and_secret_key(self):
        """Permanent sessions configured with 365 days lifetime and deterministic secret key."""
        self.assertTrue(self.app.config.get("SESSION_PERMANENT"))
        self.assertEqual(self.app.config.get("PERMANENT_SESSION_LIFETIME").days, 365)
        self.assertEqual(self.app.config.get("SESSION_COOKIE_SAMESITE"), "Lax")
        self.assertTrue(self.app.config.get("SESSION_COOKIE_HTTPONLY"))
        self.assertTrue(self.app.config.get("SESSION_REFRESH_EACH_REQUEST"))
        import os
        expected_secret = os.environ.get("SECRET_KEY", "bashflow-absolute-permanent-production-secret-key-2026")
        self.assertEqual(self.app.secret_key, expected_secret)

    def test_streaming_audio_endpoint_and_range_support(self):
        """Dedicated media streaming route serves raw bytes with Accept-Ranges and 206 Partial Content."""
        # 1. Create a sample audio message
        dummy_audio = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00DummyOggAudioPayloadForTestingPurposes"
        b64_audio = base64.b64encode(dummy_audio).decode("ascii")
        data_uri = f"data:audio/ogg;base64,{b64_audio}"

        msg = WhatsAppMessage(
            id="wam_test_streaming_123",
            organization_id="org-enterprise-default",
            whatsapp_message_id="wamid.test_stream_001",
            sender="923001234567",
            recipient="system",
            message_type="audio",
            body="🎤 Voice message",
            media_url=data_uri,
            status="received"
        )
        db.session.add(msg)
        db.session.commit()

        # 2. Test full GET /api/whatsapp/media/<message_id>
        resp = self.client.get(f"/api/whatsapp/media/{msg.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(resp.headers.get("Cache-Control"), "public, max-age=86400")
        self.assertEqual(resp.headers.get("Content-Type"), "audio/ogg")
        self.assertEqual(int(resp.headers.get("Content-Length")), len(dummy_audio))
        self.assertEqual(resp.data, dummy_audio)

        # 3. Test HTTP 206 Partial Content Range request (used by Chromium to read duration)
        range_resp = self.client.get(
            f"/api/whatsapp/media/{msg.id}",
            headers={"Range": "bytes=0-15"}
        )
        self.assertEqual(range_resp.status_code, 206)
        self.assertEqual(range_resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(range_resp.headers.get("Content-Range"), f"bytes 0-15/{len(dummy_audio)}")
        self.assertEqual(int(range_resp.headers.get("Content-Length")), 16)
        self.assertEqual(range_resp.data, dummy_audio[0:16])

    def test_polling_routes_never_return_401_with_valid_session(self):
        """Active dashboard sessions polling /api/* or /whatsapp/* auto-refresh cleanly."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "test-user-id"
            sess["is_super_admin"] = True
            sess["user_email"] = "Bashirahmad00047@gmail.com"

        resp = self.client.get("/api/whatsapp/bridge-status")
        # Bridge status endpoint should NOT return 401 Unauthorized
        self.assertNotEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
