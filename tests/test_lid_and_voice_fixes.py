import unittest
import os
import sys

# Ensure repository root is in sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from whatsapp_service import WhatsAppService


class TestLidAndVoiceFixes(unittest.TestCase):

    def test_lid_and_short_number_resolution(self):
        # 1. 7142 directly maps to 923471000668
        phone_7142 = WhatsAppService.resolve_contact_phone("7142", sender_name="Bashir khani")
        self.assertEqual(phone_7142, "923471000668")

        phone_lid = WhatsAppService.resolve_contact_phone("1234567142@lid", sender_name="Bashir khani")
        self.assertEqual(phone_lid, "923471000668")

        phone_bashir = WhatsAppService.resolve_contact_phone("unknown", sender_name="Bashir khani")
        self.assertEqual(phone_bashir, "923471000668")

        # 2. format_phone_number
        self.assertEqual(WhatsAppService.format_phone_number("7142"), "923471000668")
        self.assertEqual(WhatsAppService.format_phone_number("1234567142@lid"), "923471000668")

        # 3. format_phone_display
        self.assertEqual(WhatsAppService.format_phone_display("7142"), "+92 347 1000668")
        self.assertEqual(WhatsAppService.format_phone_display("1234567142@lid"), "+92 347 1000668")

    def test_parse_green_api_payload_lid_mapping(self):
        # Simulating inbound message from ...7142@lid with pushName "Bashir khani"
        payload = {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "test_msg_lid_001",
            "timestamp": 1700000000,
            "senderData": {
                "chatId": "283746197142@lid",
                "sender": "7142",
                "chatName": "Bashir khani",
                "senderName": "Bashir khani"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "Shilajit ke baare mein batayein."
                }
            },
            "remoteJid": "283746197142@lid"
        }

        parsed_list = WhatsAppService.parse_green_api_payload(payload)
        self.assertEqual(len(parsed_list), 1)
        msg = parsed_list[0]

        # Crucial asserts: from_phone MUST be 923471000668, chat_id MUST be 923471000668@s.whatsapp.net
        self.assertEqual(msg["from_phone"], "923471000668")
        self.assertEqual(msg["chat_id"], "923471000668@s.whatsapp.net")
        self.assertEqual(msg["sender_name"], "Bashir khani")
        self.assertEqual(msg["body"], "Shilajit ke baare mein batayein.")

    def test_live_call_room_audio_singleton_present(self):
        call_html_path = os.path.join(repo_root, "templates", "live_call_room.html")
        with open(call_html_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("window.currentAiAudio = null", html)
        self.assertIn("window.isAiSpeaking = false", html)
        self.assertIn("stopIncomingAiAudio()", html)
        self.assertIn("setTimeout", html)
        self.assertIn("350", html)

    def test_wa_bridge_lid_resolution_present(self):
        bridge_path = os.path.join(repo_root, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("resolveLidToPhone", js)
        self.assertIn("923471000668", js)
        self.assertIn("resolve-lid", js)


if __name__ == "__main__":
    unittest.main()
