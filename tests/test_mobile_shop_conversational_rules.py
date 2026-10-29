import unittest
import os
from unittest.mock import patch
from app import create_app
from database import db
from whatsapp_service import WhatsAppService


class TestMobileShopConversationalRules(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_casual_greeting_starts_with_assalam_o_alaikum(self):
        """Casual greeting like 'Kaisa ho AP sir' starts naturally with Assalam-o-Alaikum."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Kaisa ho AP sir",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        print("\n[Greeting Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum!"))
        self.assertIn("Alhamdulillah main theek hoon Bashir bhai", reply)
        self.assertIn("Bataiye, dukan ke liye kis cheez ki maloomat chahiye ya koi mobile repair/stock ka masla hai?", reply)
        self.assertNotIn("BashFlow Cloud", reply)
        self.assertNotIn("Enterprise", reply)

    def test_salam_greeting_starts_with_assalam_o_alaikum(self):
        """'Salam' returns friendly conversational shop assistant reply starting with Assalam-o-Alaikum."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Salam",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        print("\n[Salam Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum!"))
        self.assertIn("Alhamdulillah main theek hoon Bashir bhai", reply)

    def test_general_inquiry_starts_with_assalam_o_alaikum(self):
        """General inquiry starts with Assalam-o-Alaikum and introduces Bashir Mobile & Telecom."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="bhai dukan khuli hai?",
            lang_fmt="roman_urdu",
            sender_name="Hamza"
        )
        print("\n[General Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("Bashir Mobile & Telecom", reply)

    def test_mobile_repair_question_no_software_packages(self):
        """Repair questions return repair details starting with Assalam-o-Alaikum, NOT software pricing packages."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Display screen aur battery repair ka kitna rate hai?",
            lang_fmt="roman_urdu",
            sender_name="Ali"
        )
        print("\n[Repair Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("display screen", reply.lower())
        self.assertIn("battery", reply.lower())
        self.assertNotIn("$29", reply)
        self.assertNotIn("$99", reply)
        self.assertNotIn("Starter Plan", reply)
        self.assertNotIn("BashFlow Cloud", reply)

    def test_accessories_question(self):
        """Accessories questions return accessories stock details."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Original fast charger aur airpods dastiyab hain?",
            lang_fmt="roman_urdu",
            sender_name="Hamza"
        )
        print("\n[Accessories Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("charger", reply.lower())
        self.assertIn("airpod", reply.lower())
        self.assertNotIn("BashFlow Cloud", reply)

    def test_phone_stock_and_rate_question(self):
        """Phone stock/rate questions discuss phones, NOT software packages."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="iPhone 13 PTA approved available hai price kya hai?",
            lang_fmt="roman_urdu",
            sender_name="Kashif"
        )
        print("\n[Stock Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("iphone", reply.lower())
        self.assertNotIn("$29", reply)
        self.assertNotIn("BashFlow Cloud", reply)

    def test_imei_tracking_question(self):
        """IMEI questions return 15-digit IMEI tracking details."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="IMEI number kaise save hoga mobile ka",
            lang_fmt="roman_urdu"
        )
        print("\n[IMEI Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("imei", reply.lower())
        self.assertIn("15-digit", reply.lower())
        self.assertNotIn("BashFlow Cloud", reply)

    def test_jazzcash_question(self):
        """JazzCash questions provide account 03209350858 and title Bashir Uddin."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="JazzCash par payment karni hai",
            lang_fmt="roman_urdu"
        )
        print("\n[JazzCash Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("03209350858", reply)
        self.assertIn("Bashir Uddin", reply)

    def test_software_pricing_only_when_explicitly_asked(self):
        """Software pricing packages are ONLY returned when customer explicitly asks about software/bot plans."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Dukan ke liye WhatsApp software bot package aur rate batao",
            lang_fmt="roman_urdu"
        )
        print("\n[Software Price Reply]:", reply)
        self.assertTrue(reply.startswith("Assalam-o-Alaikum"))
        self.assertIn("Starter Plan", reply)
        self.assertIn("Professional Plan", reply)
        self.assertIn("03209350858", reply)

    def test_modality_matching_voice_inbound_triggers_voice_reply(self):
        """Inbound voice note triggers audio reply with ptt=True."""
        dummy_mp3 = b"ID3\x03\x00\x00\x00\x00\x00#SyntheticAudioReply"
        with patch.object(WhatsAppService, "generate_spoken_audio", return_value=(dummy_mp3, "voice_reply.mp3", "audio/mpeg")), \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": True, "whatsapp_message_id": "wamid.voice123"}) as mock_send_file, \
             patch.object(WhatsAppService, "send_green_api_message") as mock_send_text:
            
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="923209350858",
                chat_id="923209350858@c.us",
                message_body="[Voice note]",
                is_voice=True
            )
            self.assertIsNotNone(res)
            mock_send_file.assert_called_once()
            self.assertTrue(mock_send_file.call_args[1].get("ptt"))
            mock_send_text.assert_not_called()

    def test_modality_matching_text_inbound_triggers_text_reply(self):
        """Inbound text message triggers standard text reply (no unsolicited voice note)."""
        with patch.object(WhatsAppService, "generate_spoken_audio") as mock_audio, \
             patch.object(WhatsAppService, "send_green_api_file") as mock_send_file, \
             patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "whatsapp_message_id": "wamid.txt123"}) as mock_send_text:
            
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="923209350858",
                chat_id="923209350858@c.us",
                message_body="Display screen repair kitne ki hai?",
                is_voice=False
            )
            self.assertIsNotNone(res)
            mock_send_text.assert_called_once()
            mock_send_file.assert_not_called()
            mock_audio.assert_not_called()

    def test_permanent_secret_key_persistence(self):
        """Flask session secret key uses persistent production secret key without random regeneration."""
        expected_key = os.environ.get("SECRET_KEY", "bashflow-absolute-permanent-production-secret-key-2026")
        self.assertEqual(self.app.secret_key, expected_key)
        self.assertTrue(self.app.config.get("SESSION_PERMANENT"))
        self.assertEqual(self.app.config.get("PERMANENT_SESSION_LIFETIME").days, 365)


if __name__ == "__main__":
    unittest.main()
