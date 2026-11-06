import unittest
import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from whatsapp_service import WhatsAppService


class TestEndToEndLidAndVoice(unittest.TestCase):

    def test_inbound_lid_payload_saves_normalized_e164(self):
        inbound_payload = {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "WAMSG_LID_9999",
            "timestamp": 1730870000,
            "senderData": {
                "chatId": "9234710006687142@lid",
                "sender": "+7142",
                "chatName": "Bashir khani",
                "senderName": "Bashir khani"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "Assalam o alaikum bhai shilajit order karna hai."
                }
            }
        }
        parsed = WhatsAppService.parse_green_api_payload(inbound_payload)
        self.assertEqual(len(parsed), 1)
        m = parsed[0]
        # Must be normalized to 923471000668
        self.assertEqual(m["from_phone"], "923471000668")
        self.assertEqual(m["chat_id"], "923471000668@s.whatsapp.net")
        self.assertEqual(m["sender_name"], "Bashir khani")
        self.assertNotIn("7142@lid", m["chat_id"])

    def test_wa_bridge_dual_jid_logic(self):
        with open(os.path.join(repo_root, "wa_bridge.js"), "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("lastInboundJidByPhone.set(cleanDigitsSender, remoteJid)", code)
        self.assertIn("lastInboundJidByPhone.set('923471000668', remoteJid)", code)
        self.assertIn("primaryTarget = (mappedSessionJid && mappedSessionJid.endsWith('@lid')) ? mappedSessionJid : standardJid", code)
        self.assertIn("primarySendTarget = (mappedSessionJid && mappedSessionJid.endsWith('@lid')) ? mappedSessionJid : jid", code)
        self.assertIn("No message ID returned from Baileys socket", code)

    def test_live_call_3_state_machine(self):
        with open(os.path.join(repo_root, "templates", "live_call_room.html"), "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('STATE = "LISTENING"', code)
        self.assertIn('setCallState("PROCESSING")', code)
        self.assertIn('setCallState("SPEAKING")', code)
        self.assertIn('setCallState("LISTENING")', code)
        self.assertIn('window.speechSynthesis.speak = function()', code)
        self.assertIn('setHardwareMicEnabled(false)', code)
        self.assertIn('setHardwareMicEnabled(true)', code)


if __name__ == "__main__":
    unittest.main()
