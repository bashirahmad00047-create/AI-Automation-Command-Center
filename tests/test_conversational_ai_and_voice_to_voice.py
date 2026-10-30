import unittest
import base64
from unittest.mock import patch
from app import create_app
from database import db
from models import WhatsAppMessage, Organization
from whatsapp_service import WhatsAppService


class TestConversationalAIAndVoiceToVoice(unittest.TestCase):
    """Verifies that:
    1. 'Kai\'s ho ap' returns a real conversational response (not mobile shop greeting).
    2. General topics return natural conversation without mobile shop restrictions.
    3. Inbound voice notes trigger an outbound audioMessage (ptt: true) with media_url.
    4. Incoming call events are cleanly logged and processed.
    """

    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Ensure default organization exists
        org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not org:
            org = Organization(
                id="org-enterprise-default",
                name="BashFlow Enterprise",
                slug="default",
                plan_tier="enterprise"
            )
            db.session.add(org)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_1_kaise_ho_ap_returns_conversational_answer_not_mobile_shop(self):
        """Verifies 'Kai's ho ap' returns a natural conversational answer without mobile shop greeting."""
        prompts = ["Kai's ho ap", "Kaise ho ap", "Kaisa ho aap"]
        for p in prompts:
            fallback = WhatsAppService.generate_smart_conversational_fallback(
                message_body=p,
                lang_fmt="roman_urdu",
                sender_name="Bashir"
            )
            # Must be a warm, natural answer
            self.assertTrue(
                "main bilkul theek hoon" in fallback.lower() or "theek hoon" in fallback.lower(),
                f"Expected natural health response for '{p}', got: {fallback}"
            )
            # Must NOT mention mobile shop, repair, or telecom
            self.assertNotIn("bashir mobile", fallback.lower())
            self.assertNotIn("telecom", fallback.lower())
            self.assertNotIn("kis mobile ya repair", fallback.lower())
            self.assertNotIn("dukan ke liye", fallback.lower())

    def test_2_general_topic_inquiry_has_no_mobile_shop_restriction(self):
        """Verifies asking a general question receives general conversational assistance without mobile shop templates."""
        prompt = "Weather kaisa hai aaj aur AI kya cheez hai?"
        fallback = WhatsAppService.generate_smart_conversational_fallback(
            message_body=prompt,
            lang_fmt="roman_urdu",
            sender_name="Ali"
        )
        self.assertNotIn("bashir mobile", fallback.lower())
        self.assertNotIn("kis mobile ya repair", fallback.lower())
        self.assertNotIn("imei", fallback.lower())
        self.assertNotIn("dukan ke liye", fallback.lower())

    def test_3_inbound_voice_note_triggers_outbound_ptt_audio_with_media_url(self):
        """Verifies sending a voice note returns an outbound audioMessage (ptt: true) with media_url populated."""
        dummy_ogg = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00SampleSpokenAudioBytesForPTTTest"
        b64_ogg = base64.b64encode(dummy_ogg).decode("ascii")
        inbound_data_uri = f"data:audio/ogg;base64,{b64_ogg}"

        with patch.object(WhatsAppService, "generate_spoken_audio", return_value=(dummy_ogg, "voice_reply.oga", "audio/ogg; codecs=opus")), \
             patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "status": "sent"}), \
             patch.object(WhatsAppService, "send_green_api_file") as mock_send_file:

            def side_effect_send_file(**kwargs):
                f_bytes = kwargs.get("file_bytes")
                clean_b64 = base64.b64encode(f_bytes).decode("ascii") if f_bytes else ""
                media_url = kwargs.get("media_url") or f"data:audio/ogg;base64,{clean_b64}"
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
                    "message_record_id": rec.id,
                    "ptt": kwargs.get("ptt", True)
                }

            mock_send_file.side_effect = side_effect_send_file

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="923001234567",
                sender_name="Customer",
                message_body="[Voice note]",
                is_voice=True,
                download_url=inbound_data_uri,
                audio_bytes=dummy_ogg
            )

            self.assertIsNotNone(res)
            self.assertTrue(mock_send_file.called)
            call_kwargs = mock_send_file.call_args[1]
            self.assertTrue(call_kwargs.get("ptt"))
            self.assertTrue(call_kwargs.get("media_url", "").startswith("data:audio/"))

            # Verify outbound record in database
            outbound_msg = WhatsAppMessage.query.filter_by(
                direction="outbound",
                message_type="audio"
            ).order_by(WhatsAppMessage.created_at.desc()).first()
            self.assertIsNotNone(outbound_msg)
            self.assertIsNotNone(outbound_msg.media_url)
            self.assertTrue(outbound_msg.media_url.startswith("data:audio/"))

    def test_4_incoming_call_event_logged_to_dashboard(self):
        """Verifies incoming WhatsApp voice call webhook event is logged as a call in the messages database."""
        call_payload = {
            "typeWebhook": "incomingCallReceived",
            "idMessage": "call_test_123456",
            "timestamp": 1730300000,
            "chatId": "923001234567@s.whatsapp.net",
            "from_phone": "923001234567",
            "caller": "923001234567@s.whatsapp.net",
            "callId": "test_call_id_999",
            "status": "missed_call",
            "body": "📞 Incoming WhatsApp Voice Call (Auto-responded with AI voice note)"
        }

        parsed = WhatsAppService.parse_green_api_payload(call_payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["message_type"], "call")
        self.assertEqual(parsed[0]["from_phone"], "923001234567")

        rec = WhatsAppService.record_message(
            organization_id="org-enterprise-default",
            sender=parsed[0]["from_phone"],
            recipient="system",
            direction="inbound",
            body=parsed[0]["body"],
            message_type="call",
            status="missed_call",
            whatsapp_message_id=parsed[0]["message_id"]
        )
        self.assertIsNotNone(rec.id)
        self.assertEqual(rec.message_type, "call")


if __name__ == "__main__":
    unittest.main()
