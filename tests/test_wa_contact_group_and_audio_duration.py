import unittest
import json
import base64
from app import app, socketio
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
                    "mimeType": "audio/mp3"
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
            media_url=f"data:audio/mp3;base64,{b64_audio}",
            raw_payload_json=json.dumps(payload)
        )
        db.session.add(msg)
        db.session.commit()

        d = msg.to_dict()
        self.assertEqual(d["duration"], 5.4)
        self.assertEqual(d["audio_duration"], 5.4)
        self.assertEqual(d["is_audio"], True)

        # Verify streaming media endpoint sets Content-Duration, X-Content-Duration, and Accept-Ranges
        resp = self.client.get(f"/api/whatsapp/media/{msg.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Content-Duration", resp.headers)
        self.assertEqual(resp.headers.get("Content-Duration"), "5.4")
        self.assertEqual(resp.headers.get("X-Content-Duration"), "5.4")
        self.assertEqual(resp.headers.get("Content-Type"), "audio/mp3")
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")

        # Cleanup
        db.session.delete(msg)
        db.session.commit()

    def test_audio_stream_ogg_format_headers(self):
        # Mock OGG Opus audio starting with OggS
        fake_ogg = b"OggS" + b"\x00" * 16000
        b64_ogg = base64.b64encode(fake_ogg).decode("ascii")

        msg = WhatsAppMessage(
            organization_id="org-enterprise-default",
            whatsapp_message_id="test_vn_ogg_002",
            sender="923209350858",
            recipient="system",
            direction="inbound",
            message_type="audio",
            body="🎤 OGG voice note",
            media_url=f"data:audio/ogg;base64,{b64_ogg}"
        )
        db.session.add(msg)
        db.session.commit()

        resp = self.client.get(f"/api/whatsapp/media/{msg.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "audio/ogg")
        self.assertIn("Content-Duration", resp.headers)
        self.assertIn("X-Content-Duration", resp.headers)
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")

        db.session.delete(msg)
        db.session.commit()

    def test_socketio_realtime_broadcast(self):
        if socketio:
            s_client = socketio.test_client(self.app)
            self.assertTrue(s_client.is_connected())

            rec = WhatsAppService.record_message(
                organization_id="org-enterprise-default",
                sender="923209350858",
                recipient="system",
                direction="inbound",
                body="Testing real-time broadcast",
                message_type="text",
                whatsapp_message_id="test_realtime_msg_001"
            )

            received = s_client.get_received()
            event_names = [e.get("name") for e in received]
            self.assertTrue("new_whatsapp_message" in event_names or "whatsapp_message" in event_names)

            db.session.delete(rec)
            db.session.commit()
            s_client.disconnect()

if __name__ == "__main__":
    unittest.main()
