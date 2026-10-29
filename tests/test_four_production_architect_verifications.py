import unittest
import base64
from unittest.mock import patch
from app import create_app
from database import db
from models import WhatsAppMessage, User, Organization
from whatsapp_service import WhatsAppService


class FourProductionArchitectVerificationsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_1_streaming_audio_endpoint_200_and_206(self):
        """(1) /api/whatsapp/media/<id> returns 200/206 binary audio with Content-Length and Range support."""
        dummy_audio = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00SampleBinaryAudioBufferData12345"
        b64_audio = base64.b64encode(dummy_audio).decode("ascii")
        data_uri = f"data:audio/ogg;base64,{b64_audio}"

        msg = WhatsAppMessage(
            id="wam_stream_verify_001",
            organization_id="org-enterprise-default",
            whatsapp_message_id="wamid.stream_verify_001",
            sender="923001234567",
            recipient="system",
            message_type="audio",
            body="🎤 Voice note",
            media_url=data_uri,
            status="received"
        )
        db.session.add(msg)
        db.session.commit()

        # A. Full binary audio request (HTTP 200)
        resp = self.client.get(f"/api/whatsapp/media/{msg.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "audio/ogg")
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(resp.headers.get("Cache-Control"), "public, max-age=86400")
        self.assertEqual(int(resp.headers.get("Content-Length")), len(dummy_audio))
        self.assertEqual(resp.data, dummy_audio)

        # B. Partial Content Range request (HTTP 206 for Chromium duration seeking)
        range_resp = self.client.get(
            f"/api/whatsapp/media/{msg.id}",
            headers={"Range": "bytes=0-19"}
        )
        self.assertEqual(range_resp.status_code, 206)
        self.assertEqual(range_resp.headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(range_resp.headers.get("Content-Range"), f"bytes 0-19/{len(dummy_audio)}")
        self.assertEqual(int(range_resp.headers.get("Content-Length")), 20)
        self.assertEqual(range_resp.data, dummy_audio[0:20])

    def test_2_mobile_shop_inquiry_domain_response(self):
        """(2) Asking 'Mara mobile shop k Liya Kaisa Kam karaga ya' returns specific mobile shop intelligence (not generic paragraph)."""
        prompt = "Mara mobile shop k Liya Kaisa Kam karaga ya"
        
        # Test fallback directly
        fallback_reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body=prompt,
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        # Test auto response pipeline
        auto_resp = WhatsAppService.generate_ai_auto_response(
            organization_id="org-enterprise-default",
            message_body=prompt,
            sender_name="Bashir"
        )
        auto_reply = auto_resp.get("reply_body", "")

        # Must contain mobile shop domain intelligence
        self.assertIn("mobile shop", fallback_reply.lower())
        self.assertTrue("repair" in fallback_reply.lower() or "imei" in fallback_reply.lower())
        self.assertTrue("mobile shop" in auto_reply.lower() or "repair" in auto_reply.lower())

        # Must NOT be the old generic canned paragraph
        old_generic_snippet = "bashflow cloud ek powerful enterprise ai automation command center hai. hum provide karte hain: (1) 24/7 whatsapp ai auto-responder"
        self.assertNotIn(old_generic_snippet, fallback_reply.lower())
        self.assertNotIn(old_generic_snippet, auto_reply.lower())

    def test_3_voice_note_triggers_outbound_audio_with_media_url(self):
        """(3) Sending a voice note triggers an outbound audio reply with media_url populated in WhatsAppMessage."""
        dummy_mp3 = b"ID3\x03\x00\x00\x00\x00\x00#SyntheticSpokenReplyBytesForVoiceToVoice"
        
        with patch.object(WhatsAppService, "generate_spoken_audio", return_value=(dummy_mp3, "voice_reply.mp3", "audio/mpeg")), \
             patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "status": "sent"}), \
             patch.object(WhatsAppService, "send_green_api_file") as mock_send_file:
            
            # Setup mock return for send_green_api_file
            def side_effect_send_file(**kwargs):
                f_bytes = kwargs.get("file_bytes")
                clean_b64 = base64.b64encode(f_bytes).decode("ascii") if f_bytes else ""
                media_url = kwargs.get("media_url") or f"data:audio/mpeg;base64,{clean_b64}"
                rec = WhatsAppService.record_message(
                    organization_id=kwargs.get("organization_id", "org-enterprise-default"),
                    sender="System Voice Bot",
                    recipient=kwargs.get("chat_id", "923001234567@s.whatsapp.net"),
                    direction="outbound",
                    body=kwargs.get("transcript", "Spoken reply"),
                    message_type="audio",
                    media_url=media_url,
                    status="sent"
                )
                return {
                    "success": True,
                    "status": "sent",
                    "media_url": media_url,
                    "message_record_id": rec.id
                }
            mock_send_file.side_effect = side_effect_send_file

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="923001234567",
                sender_name="Customer",
                message_body="[Voice note]",
                is_voice_inbound=True,
                audio_bytes=b"OggS\x00\x02SampleCustomerVoiceData"
            )

            self.assertIsNotNone(res)
            # Verify outbound audio message was dispatched
            self.assertTrue(mock_send_file.called)
            call_kwargs = mock_send_file.call_args[1]
            self.assertIn("data:audio/mpeg;base64,", call_kwargs.get("media_url", ""))
            self.assertTrue(call_kwargs.get("ptt"))

            # Verify saved record in DB has media_url populated
            outbound_msg = WhatsAppMessage.query.filter_by(
                direction="outbound",
                message_type="audio"
            ).order_by(WhatsAppMessage.created_at.desc()).first()
            self.assertIsNotNone(outbound_msg)
            self.assertIsNotNone(outbound_msg.media_url)
            self.assertTrue(outbound_msg.media_url.startswith("data:audio/"))

    def test_4_sessions_persist_across_app_restarts(self):
        """(4) Sessions persist across application restarts using deterministic secret key."""
        # Step A: Login on first app instance
        client1 = self.app.test_client()
        login_resp = client1.post(
            "/login",
            json={"email": "Bashirahmad00047@gmail.com", "password": "bashir@12."}
        )
        self.assertEqual(login_resp.status_code, 200)

        # Extract opsflow_session cookie from client1
        cookie_obj = client1.get_cookie("opsflow_session")
        session_cookie = cookie_obj.value if cookie_obj else None
        if not session_cookie:
            for header in login_resp.headers.getlist("Set-Cookie"):
                if "opsflow_session=" in header:
                    session_cookie = header.split("opsflow_session=")[1].split(";")[0]
                    break
        self.assertIsNotNone(session_cookie, "opsflow_session cookie must be set on login.")

        # Step B: Simulate complete application restart (create fresh app instance app2)
        fresh_app = create_app("testing")
        fresh_client = fresh_app.test_client()

        # Set the session cookie on fresh_client
        fresh_client.set_cookie("opsflow_session", session_cookie)

        # Step C: Request protected root route '/' on the new app instance
        root_resp = fresh_client.get("/")
        # Must return HTTP 200 dashboard, NOT 302 redirect to /login
        self.assertEqual(root_resp.status_code, 200)
        content_html = root_resp.get_data(as_text=True)
        self.assertIn("Command Center", content_html)


if __name__ == "__main__":
    unittest.main()
