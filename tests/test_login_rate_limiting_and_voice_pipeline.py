import unittest
import json
import base64
import time
from app import app
from models import db, WhatsAppMessage, LoginAttempt, User
from limiter import login_limiter
from whatsapp_service import WhatsAppService
from sqlalchemy import inspect as _sa_inspect, text as _sa_text

class TestLoginRateLimitingAndVoicePipeline(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["RATELIMIT_ENABLED"] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        login_limiter.reset()

        # Ensure database tables and columns exist
        db.create_all()
        _insp = _sa_inspect(db.engine)
        if "whatsapp_messages" in _insp.get_table_names():
            _wam_cols = {c["name"] for c in _insp.get_columns("whatsapp_messages")}
            with db.engine.connect() as _c_conn:
                if "audio_data" not in _wam_cols:
                    _c_conn.execute(_sa_text("ALTER TABLE whatsapp_messages ADD COLUMN audio_data BLOB;"))
                    _c_conn.commit()

    def tearDown(self):
        login_limiter.reset()
        self.app_context.pop()

    def test_login_rate_limit_strictly_blocks_on_6th_attempt(self):
        """Verify that 5 failed login attempts are allowed, and the 6th attempt strictly returns HTTP 429."""
        login_limiter.reset()
        ip = "192.168.1.100"
        test_email = "brute_force_tester@example.com"

        # Attempts 1 through 5 should return 401 (invalid credentials)
        for i in range(1, 6):
            res = self.client.post(
                "/api/v1/auth/login",
                json={"email": test_email, "password": f"wrongpass{i}"},
                headers={"X-Forwarded-For": ip}
            )
            self.assertEqual(
                res.status_code, 401,
                f"Attempt {i} expected 401, got {res.status_code}"
            )

        # 6th attempt within the same minute should be rate limited with HTTP 429
        res6 = self.client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "wrongpass6"},
            headers={"X-Forwarded-For": ip}
        )
        self.assertEqual(res6.status_code, 429)
        data6 = res6.get_json()
        self.assertEqual(data6.get("code"), "TOO_MANY_REQUESTS")
        self.assertIn("Too many login attempts", data6.get("error", ""))
        self.assertTrue(res6.headers.get("Retry-After") is not None)

    def test_top_level_login_endpoint_rate_limiting(self):
        """Verify that the top-level /login endpoint respects the 5 login attempts/min limit."""
        login_limiter.reset()
        ip = "10.0.0.50"
        test_email = "user_test_top_level@example.com"

        for i in range(1, 6):
            res = self.client.post(
                "/login",
                json={"email": test_email, "password": f"badpass{i}"},
                headers={"X-Forwarded-For": ip}
            )
            self.assertEqual(res.status_code, 401)

        res6 = self.client.post(
            "/login",
            json={"email": test_email, "password": "badpass6"},
            headers={"X-Forwarded-For": ip}
        )
        self.assertEqual(res6.status_code, 429)

    def test_login_attempt_db_persistence(self):
        """Verify that LoginAttempt records are persisted in the database."""
        login_limiter.reset()
        ip = "172.16.0.22"
        test_email = "audit_check_user@example.com"

        self.client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "wrongpassword"},
            headers={"X-Forwarded-For": ip, "User-Agent": "PyTest-Client"}
        )

        attempt = LoginAttempt.query.filter_by(ip_address=ip, username=test_email).first()
        self.assertIsNotNone(attempt)
        self.assertFalse(attempt.success)
        self.assertEqual(attempt.username, test_email)

    def test_voice_note_no_hardcoded_canned_fallback(self):
        """Verify that _transcribe_audio does NOT return the hardcoded canned string when STT is absent."""
        fake_audio = b"OggS\x00\x02" + b"\x00" * 500
        transcript = WhatsAppService._transcribe_audio(fake_audio, organization_id="test_org")
        self.assertIsNone(transcript)
        
        canned_phrase = "Assalam-o-Alaikum! Maine aapka voice note sun liya hai"
        self.assertNotEqual(transcript, canned_phrase)

    def test_streaming_audio_headers_and_accept_ranges(self):
        """Verify that /api/whatsapp/media/<id> serves valid headers (audio/ogg, Accept-Ranges, Content-Length)."""
        fake_ogg = b"OggS\x00\x02" + b"\x00" * 48000
        b64_ogg = base64.b64encode(fake_ogg).decode("ascii")

        wam = WhatsAppMessage(
            organization_id="org-enterprise-default",
            whatsapp_message_id="wam_test_streaming_audio_001",
            direction="inbound",
            sender="923001234567",
            recipient="system",
            message_type="audio",
            media_url=f"data:audio/ogg;base64,{b64_ogg}",
            raw_payload_json=json.dumps({"audio_duration": 3.5})
        )
        db.session.add(wam)
        db.session.commit()

        res = self.client.get(f"/api/whatsapp/media/{wam.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "audio/ogg")
        self.assertEqual(res.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(int(res.headers.get("Content-Length", 0)), len(fake_ogg))
        self.assertIn("Content-Duration", res.headers)

        # Range request test (HTTP 206)
        res_range = self.client.get(
            f"/api/whatsapp/media/{wam.id}",
            headers={"Range": "bytes=0-1023"}
        )
        self.assertEqual(res_range.status_code, 206)
        self.assertEqual(res_range.headers.get("Content-Length"), "1024")
        self.assertIn("bytes 0-1023/", res_range.headers.get("Content-Range", ""))

if __name__ == "__main__":
    unittest.main()
