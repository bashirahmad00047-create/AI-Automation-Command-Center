import unittest
import json
import base64
from app import app
from models import db, WhatsAppMessage
from whatsapp_service import WhatsAppService

class TestWaContactGroupAndAudioDuration(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        self.app_context.pop()

    def test_group_jid_subject_and_sender_name_extraction(self):
        payload = {
            "typeWebhook": "incomingMessageReceived",
            "remoteJid": "120363025544332211@g.us",
            "chatId": "120363025544332211@g.us",
            "groupSubject": "Mobile Repair Karachi Group",
            "from_phone": "923209350858",
            "senderName": "Bashir Ahmed",
            "senderData": {
                "chatId": "120363025544332211@g.us",
                "sender": "923209350858",
                "chatName": "Mobile Repair Karachi Group",
                "senderName": "Bashir Ahmed"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {"textMessage": "Assalam-o-Alaikum, repair update?"}
            }
        }
        events = WhatsAppService.parse_green_api_payload(payload)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["chat_id"], "120363025544332211@g.us")
        self.assertEqual(ev["chat_name"], "Mobile Repair Karachi Group")
        self.assertEqual(ev["sender_name"], "Bashir Ahmed")

    def test_voice_note_duration_extraction_and_headers(self):
        # Create a mock base64 audio payload
        fake_audio = b"ID3" + b"\x00" * 32000 # ~2 seconds at 128kbps
        b64_audio = base64.b64encode(fake_audio).decode("ascii")

        payload = {
            "typeWebhook": "incomingMessageReceived",
            "remoteJid": "923209350858@s.whatsapp.net",
            "from_phone": "923209350858",
            "senderName": "Tariq Mobile",
            "is_voice": True,
            "duration": 5.4,
            "seconds": 5.4,
            "audio_base64": b64_audio,
            "messageData": {
                "typeMessage": "voiceMessage",
                "fileMessageData": {
                    "duration": 5.4,
                    "audioBase64": b64_audio,
                    "mimeType": "audio/ogg"
                }
            }
        }
        events = WhatsAppService.parse_green_api_payload(payload)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["duration"], 5.4)
        self.assertEqual(ev["audio_duration"], 5.4)
        self.assertEqual(ev["is_audio"], True)

        # Ingest into DB and verify to_dict returns chat_name and duration
        msg = WhatsAppMessage(
            organization_id="org-enterprise-default",
            whatsapp_message_id="test_vn_dur_001",
            sender="923209350858",
            recipient="system",
            direction="inbound",
            message_type="audio",
            body="🎤 Voice message",
            media_url=f"data:audio/ogg;base64,{b64_audio}",
            raw_payload_json=json.dumps(payload)
        )
        db.session.add(msg)
        db.session.commit()

        d = msg.to_dict()
        self.assertEqual(d["duration"], 5.4)
        self.assertEqual(d["audio_duration"], 5.4)
        self.assertEqual(d["is_audio"], True)

        # Verify streaming media endpoint sets Content-Duration and X-Content-Duration
        resp = self.client.get(f"/api/whatsapp/media/{msg.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Content-Duration", resp.headers)
        self.assertEqual(resp.headers.get("Content-Duration"), "5.4")
        self.assertEqual(resp.headers.get("X-Content-Duration"), "5.4")

        # Cleanup
        db.session.delete(msg)
        db.session.commit()

if __name__ == "__main__":
    unittest.main()
