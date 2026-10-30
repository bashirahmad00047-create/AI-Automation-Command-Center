import unittest
import json
import base64
import time
from app import app
from models import db, WhatsAppMessage, LoginAttempt, User, Organization
from limiter import login_limiter
from whatsapp_service import WhatsAppService
from sqlalchemy import inspect as _sa_inspect, text as _sa_text
from unittest.mock import patch, MagicMock

class TestE2EConversationsAIAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["RATELIMIT_ENABLED"] = True

    def setUp(self):
        self.app = app
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        login_limiter.reset()

        # Database tables and column guarantee
        db.create_all()
        _insp = _sa_inspect(db.engine)
        if "whatsapp_messages" in _insp.get_table_names():
            _wam_cols = {c["name"] for c in _insp.get_columns("whatsapp_messages")}
            with db.engine.connect() as _c_conn:
                if "audio_data" not in _wam_cols:
                    _c_conn.execute(_sa_text("ALTER TABLE whatsapp_messages ADD COLUMN audio_data BLOB;"))
                    _c_conn.commit()

        # Ensure demo org exists
        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="Bashir Mobile & Telecom",
                slug="bashir-telecom",
                plan_tier="enterprise",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

    def tearDown(self):
        login_limiter.reset()
        self.app_context.pop()

    def test_e2e_conversation_list_rendering(self):
        """E2E Test: Ingest messages and verify /api/v1/whatsapp/messages returns conversations with real names and audio flags."""
        fake_ogg = b"OggS\x00\x02" + b"\x00" * 4000
        b64_ogg = base64.b64encode(fake_ogg).decode("ascii")

        # 1. Direct 1-to-1 contact message
        msg1 = WhatsAppMessage(
            organization_id=self.org.id,
            whatsapp_message_id="wam_e2e_001",
            direction="inbound",
            sender="923209350858",
            recipient="system",
            message_type="text",
            body="Salam bhai, battery replacement kitne ki hai?",
            raw_payload_json=json.dumps({
                "senderData": {"senderName": "Tariq Mahmood", "chatName": "Tariq Mahmood"},
                "senderName": "Tariq Mahmood"
            })
        )
        # 2. Group chat message
        msg2 = WhatsAppMessage(
            organization_id=self.org.id,
            whatsapp_message_id="wam_e2e_002",
            direction="inbound",
            sender="120363025544332211@g.us",
            recipient="system",
            message_type="audio",
            body="🎤 Voice Note",
            media_url=f"data:audio/ogg;base64,{b64_ogg}",
            raw_payload_json=json.dumps({
                "senderData": {"chatId": "120363025544332211@g.us", "chatName": "Mobile Wholesalers Karachi", "senderName": "Hamza Ali"},
                "chatName": "Mobile Wholesalers Karachi",
                "audio_duration": 4.2
            })
        )
        db.session.add(msg1)
        db.session.add(msg2)
        db.session.commit()

        # Log in as admin to access messages endpoint
        with self.client.session_transaction() as sess:
            sess["user_id"] = "usr-master-admin"
            sess["role"] = "admin"
            sess["is_super_admin"] = True
            sess["is_enterprise_bypass"] = True
            sess["org_id"] = self.org.id
            sess["active_org_id"] = self.org.id

        res = self.client.get("/api/v1/whatsapp/messages")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        messages = data.get("messages", [])
        self.assertGreaterEqual(len(messages), 2)
        
        # Verify sender and chat names are populated (not generic fallback)
        chat_names = [m.get("chat_name") or m.get("sender_name") for m in messages if m.get("chat_name") or m.get("sender_name")]
        self.assertIn("Mobile Wholesalers Karachi", chat_names)

    def test_e2e_text_to_text_ai_reply(self):
        """E2E Test: Verify text inquiry produces authentic Pakistani mobile shopkeeper response starting with Assalam-o-Alaikum."""
        customer_msg = "Salam bhai, iPhone 12 ka original panel display kitne ka milega?"
        reply = WhatsAppService.generate_ai_auto_response(
            organization_id=self.org.id,
            message_body=customer_msg,
            sender_phone="+923001234567"
        )
        self.assertIsNotNone(reply)
        reply_body = reply.get("reply_body", "")
        self.assertTrue(reply_body.startswith("Assalam-o-Alaikum"))
        lower_reply = reply_body.lower()
        self.assertTrue(
            any(k in lower_reply for k in ("panel", "screen", "display", "repair", "model", "dukan", "mobile"))
        )

    def test_e2e_voice_to_voice_ai_reply_pipeline(self):
        """E2E Test: Inbound voice note transcribes speech, generates shopkeeper reply, and synthesizes audio."""
        fake_audio_bytes = b"OggS\x00\x02" + b"\x00" * 4000
        clean_transcript = "Bhai Infinix Note 12 ki battery mil jayegi aur warranty kitni hogi?"

        with patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes), \
             patch.object(WhatsAppService, "_transcribe_audio", return_value=clean_transcript), \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_audio_bytes, "voice_reply.mp3", "audio/mp4")), \
             patch.object(WhatsAppService, "send_green_api_file") as mock_send_file, \
             patch.object(WhatsAppService, "send_green_api_message") as mock_send_msg:

            mock_send_file.return_value = {"status": "sent", "idMessage": "wam_out_voice_123"}
            mock_send_msg.return_value = {"status": "sent", "idMessage": "wam_out_msg_123"}

            incoming_voice_payload = {
                "typeWebhook": "incomingMessageReceived",
                "instanceData": {"idInstance": 123456},
                "senderData": {
                    "chatId": "923111222333@s.whatsapp.net",
                    "sender": "923111222333@s.whatsapp.net",
                    "senderName": "Zubair Khan"
                },
                "messageData": {
                    "typeMessage": "audioMessage",
                    "fileMessageData": {
                        "downloadUrl": "http://127.0.0.1:3001/mock_audio.ogg",
                        "mimeType": "audio/ogg; codecs=opus",
                        "fileName": "voice.oga"
                    }
                }
            }

            res = self.client.post(
                "/api/v1/webhooks/whatsapp",
                json=incoming_voice_payload,
                headers={"Content-Type": "application/json"}
            )
            self.assertIn(res.status_code, (200, 202))
            self.assertTrue(mock_send_file.called or mock_send_msg.called)

    def test_e2e_5_attempt_login_rate_limiting(self):
        """E2E Test: 5 login attempts within 60s per IP/username allowed, 6th strictly returns 429."""
        login_limiter.reset()
        ip = "198.51.100.42"
        email = "rate_limit_e2e@example.com"

        for i in range(1, 6):
            res = self.client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": f"bad_pwd_{i}"},
                headers={"X-Forwarded-For": ip}
            )
            self.assertEqual(res.status_code, 401, f"Attempt {i} should be 401")

        res6 = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "bad_pwd_6"},
            headers={"X-Forwarded-For": ip}
        )
        self.assertEqual(res6.status_code, 429)
        self.assertEqual(res6.get_json().get("code"), "TOO_MANY_REQUESTS")

    def test_e2e_otp_security_and_rate_limiting(self):
        """E2E Test: OTP verification invalidates on max attempts and enforces rate limiting."""
        from limiter import limiter
        limiter.reset()
        ip = "192.0.2.77"

        # 1. Request OTP for master admin
        req_res = self.client.post(
            "/api/v1/auth/request-otp",
            json={"email": "bashirahmad00047@gmail.com"},
            headers={"X-Forwarded-For": ip}
        )
        self.assertEqual(req_res.status_code, 200)
        self.assertEqual(req_res.get_json().get("status"), "success")

        # 2. Try invalid OTPs until lockout
        for attempt in range(1, 5):
            ver_res = self.client.post(
                "/api/v1/auth/verify-otp",
                json={"email": "bashirahmad00047@gmail.com", "otp": f"99999{attempt}"},
                headers={"X-Forwarded-For": ip}
            )
            self.assertEqual(ver_res.status_code, 400)

        # 5th failed attempt should trigger lockout (429)
        ver_res5 = self.client.post(
            "/api/v1/auth/verify-otp",
            json={"email": "bashirahmad00047@gmail.com", "otp": "999995"},
            headers={"X-Forwarded-For": ip}
        )
        self.assertEqual(ver_res5.status_code, 429)

    def test_conditional_messaging_strictly_separates_voice_and_text(self):
        """Verifies conditional messaging: Inbound voice -> OGG Opus PTT voice reply; Inbound text -> Text reply."""
        fake_audio = b"OggS\x00\x02" + b"\x00" * 4000
        sample_transcript = "Bhai screen repair kitne time mein hogi?"

        # Case 1: Inbound VOICE -> Replies with OGG Opus PTT voice note (send_green_api_file), NOT text message
        with patch.object(WhatsAppService, "_download_media", return_value=fake_audio), \
             patch.object(WhatsAppService, "_transcribe_audio", return_value=sample_transcript), \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_audio, "voice_reply.oga", "audio/ogg; codecs=opus")), \
             patch.object(WhatsAppService, "send_green_api_file") as mock_voice_file, \
             patch.object(WhatsAppService, "send_green_api_message") as mock_text_msg:

            mock_voice_file.return_value = {"status": "sent", "idMessage": "wam_ptt_001"}

            voice_payload = {
                "typeWebhook": "incomingMessageReceived",
                "senderData": {"chatId": "923001234567@s.whatsapp.net", "sender": "923001234567@s.whatsapp.net"},
                "messageData": {
                    "typeMessage": "audioMessage",
                    "fileMessageData": {"downloadUrl": "http://example.com/audio.oga", "mimeType": "audio/ogg; codecs=opus"}
                }
            }
            res = self.client.post("/api/v1/webhooks/whatsapp", json=voice_payload)
            self.assertIn(res.status_code, (200, 202))
            # Must call voice file dispatch with ptt=True and audio/ogg
            self.assertTrue(mock_voice_file.called)
            kwargs = mock_voice_file.call_args.kwargs
            self.assertTrue(kwargs.get("ptt"))
            self.assertEqual(kwargs.get("mime_type"), "audio/ogg; codecs=opus")
            # Must NOT call text message dispatch
            self.assertFalse(mock_text_msg.called)

        # Case 2: Inbound TEXT -> Replies with TEXT (send_green_api_message), NOT voice note
        with patch.object(WhatsAppService, "generate_spoken_audio") as mock_tts, \
             patch.object(WhatsAppService, "send_green_api_file") as mock_voice_file2, \
             patch.object(WhatsAppService, "send_green_api_message") as mock_text_msg2:

            mock_text_msg2.return_value = {"status": "sent", "idMessage": "wam_txt_001"}

            text_payload = {
                "typeWebhook": "incomingMessageReceived",
                "senderData": {"chatId": "923001234567@s.whatsapp.net", "sender": "923001234567@s.whatsapp.net"},
                "messageData": {
                    "typeMessage": "textMessage",
                    "textMessageData": {"textMessage": "Salam, display repair rate batayein"}
                }
            }
            res = self.client.post("/api/v1/webhooks/whatsapp", json=text_payload)
            self.assertIn(res.status_code, (200, 202))
            # Must call text message dispatch
            self.assertTrue(mock_text_msg2.called)
            # Must NOT call voice file dispatch or TTS synthesis
            self.assertFalse(mock_voice_file2.called)
            self.assertFalse(mock_tts.called)

    def test_environment_variables_security_not_leaked(self):
        """Verifies environment variables and secrets are never exposed in configuration APIs."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = "usr-master-admin"
            sess["role"] = "admin"
            sess["is_super_admin"] = True
            sess["org_id"] = self.org.id

        res = self.client.get("/api/v1/whatsapp/config")
        self.assertEqual(res.status_code, 200)
        config_data = res.get_json()

        # Sensitive credentials must never be in responses
        dumped_str = json.dumps(config_data)
        # Verify actual credentials and secrets are never leaked
        for secret_val in ("bashir@12.", "sk-", "gsk_", "AIzaSy", "bashflow-absolute"):
            self.assertNotIn(secret_val, dumped_str)
        # Verify no raw password or key fields exist in response
        self.assertNotIn("admin_password", dumped_str.lower())
        self.assertNotIn("secret_key", dumped_str.lower())

if __name__ == "__main__":
    unittest.main()
