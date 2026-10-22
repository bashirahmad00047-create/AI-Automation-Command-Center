import os
import time
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestWhatsAppWebhookIngressVoiceFix(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Cloud Enterprise",
                slug="opsflow-enterprise",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_voice_note_webhook_parses_fast_without_blocking_media_download(self):
        """Verifies voice note payloads are parsed cleanly with download_url and '[Voice note]' without blocking on network."""
        voice_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": 710722761603,
                "wid": "923471000668@c.us",
                "typeInstance": "whatsapp"
            },
            "timestamp": int(time.time()),
            "idMessage": "AUDIO_MSG_INGRESS_9001",
            "senderData": {
                "chatId": "923209350858@c.us",
                "chatName": "Ahmad",
                "sender": "923209350858@c.us",
                "senderName": "Ahmad"
            },
            "messageData": {
                "typeMessage": "audioMessage",
                "fileMessageData": {
                    "downloadUrl": "https://do-media-7107.fra1.digitaloceanspaces.com/test_audio.oga",
                    "caption": "",
                    "fileName": "audio.oga",
                    "mimeType": "audio/ogg; codecs=opus"
                }
            }
        }

        # parse_green_api_payload should complete in < 10ms with zero network calls
        t0 = time.time()
        messages = WhatsAppService.parse_green_api_payload(voice_payload)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.1)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["message_id"], "AUDIO_MSG_INGRESS_9001")
        self.assertEqual(messages[0]["message_type"], "audioMessage")
        self.assertEqual(messages[0]["body"], "[Voice note]")
        self.assertEqual(messages[0]["download_url"], "https://do-media-7107.fra1.digitaloceanspaces.com/test_audio.oga")

    def test_voice_note_webhook_ingress_persists_record_immediately(self):
        """Verifies green-api webhook endpoint persists voice note immediately and returns HTTP 200."""
        voice_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": 710722761603,
                "wid": "923471000668@c.us",
                "typeInstance": "whatsapp"
            },
            "timestamp": int(time.time()),
            "idMessage": "AUDIO_MSG_INGRESS_9002",
            "senderData": {
                "chatId": "923209350858@c.us",
                "chatName": "Ahmad",
                "sender": "923209350858@c.us",
                "senderName": "Ahmad"
            },
            "messageData": {
                "typeMessage": "audioMessage",
                "fileMessageData": {
                    "downloadUrl": "https://do-media-7107.fra1.digitaloceanspaces.com/test_audio.oga",
                    "caption": "",
                    "fileName": "audio.oga",
                    "mimeType": "audio/ogg; codecs=opus"
                }
            }
        }

        with patch.object(WhatsAppService, "handle_inbound_auto_response") as mock_auto:
            resp = self.client.post("/api/v1/webhooks/whatsapp/green-api", json=voice_payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["processed"], 1)

            # Check persisted in DB
            rec = WhatsAppMessage.query.filter_by(whatsapp_message_id="AUDIO_MSG_INGRESS_9002").first()
            self.assertIsNotNone(rec)
            self.assertEqual(rec.direction, "inbound")
            self.assertEqual(rec.body, "[Voice note]")
            self.assertEqual(rec.message_type, "audioMessage")

    def test_idempotency_does_not_permanently_block_unpersisted_messages(self):
        """Verifies is_duplicate_message does not permanently block an ID if it was never persisted in the database."""
        test_id = "FAILED_TRANSACTION_MSG_001"
        WhatsAppService._processed_message_ids.pop(test_id, None)

        # First check sets in-flight
        is_dup1 = WhatsAppService.is_duplicate_message(test_id)
        self.assertFalse(is_dup1)

        # Simulated crash before DB commit: record was NOT saved
        rec = WhatsAppMessage.query.filter_by(whatsapp_message_id=test_id).first()
        self.assertIsNone(rec)

        # Advance timestamp past in-flight window (35 seconds later)
        WhatsAppService._processed_message_ids[test_id] = time.time() - 35

        # Retry should NOT be blocked because it is not in the database
        is_dup2 = WhatsAppService.is_duplicate_message(test_id)
        self.assertFalse(is_dup2)

    def test_direct_media_download_uses_direct_url(self):
        """Verifies _download_media downloads directly when direct download_url is given."""
        fake_audio_bytes = b"\x00\x01\x02\x03\x04"
        with patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = fake_audio_bytes
            mock_session.get.return_value = mock_resp

            result = WhatsAppService._download_media(
                chat_id="923209350858@c.us",
                message_id="ACC3E4FAB4E94FCAC55545FB2E679464",
                download_url="https://do-media-7107.fra1.digitaloceanspaces.com/test.oga"
            )
            self.assertEqual(result, fake_audio_bytes)
            mock_session.get.assert_called_once()
            mock_session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
