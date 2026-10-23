import json
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
        WhatsAppService.clear_recent_replied_trigger_ids()
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

    def test_download_media_normalizes_chat_id_without_suffix(self):
        """Verifies _download_media appends @c.us if phone number lacks JID suffix."""
        fake_audio_bytes = b"\x00\x01\x02\x03\x04"
        with patch.object(WhatsAppService, "get_http_session") as mock_session_cls, \
             patch.object(WhatsAppService, "get_config", return_value={"green_api_id_instance": "7107", "green_api_token_instance": "tok"}):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            post_resp = MagicMock()
            post_resp.status_code = 200
            post_resp.json.return_value = {"downloadUrl": "https://storage.test/audio.oga"}
            mock_session.post.return_value = post_resp

            get_resp = MagicMock()
            get_resp.status_code = 200
            get_resp.content = fake_audio_bytes
            mock_session.get.return_value = get_resp

            WhatsAppService._download_media(
                chat_id="923209350858",
                message_id="ACC3E4FAB4E94FCAC55545FB2E679464"
            )
            # Verify the POST json body chatId has @c.us appended
            post_call = mock_session.post.call_args
            self.assertEqual(post_call[1]["json"]["chatId"], "923209350858@c.us")

    def test_whatsapp_message_to_dict_extracts_media_url_from_various_payload_keys(self):
        """Verifies WhatsAppMessage.to_dict correctly populates media_url from download_url or raw data."""
        msg1 = WhatsAppMessage(
            id="wam_test_001",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.001",
            message_type="audioMessage",
            body="[Voice note]",
            raw_payload_json=json.dumps({"download_url": "https://media.test/audio1.oga"})
        )
        self.assertEqual(msg1.to_dict()["media_url"], "https://media.test/audio1.oga")
        self.assertTrue(msg1.to_dict()["is_audio"])

        msg2 = WhatsAppMessage(
            id="wam_test_002",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.002",
            message_type="audioMessage",
            body="[Voice note]",
            raw_payload_json=json.dumps({
                "raw": {
                    "messageData": {
                        "fileMessageData": {
                            "downloadUrl": "https://media.test/audio2.oga"
                        }
                    }
                }
            })
        )
        self.assertEqual(msg2.to_dict()["media_url"], "https://media.test/audio2.oga")

    def test_transcribe_audio_uses_groq_whisper_fallback(self):
        """Verifies _transcribe_audio falls back to Groq Whisper when Gemini key is not configured."""
        fake_audio = b"\x00" * 100
        with patch.object(WhatsAppService, "get_gemini_api_key", return_value=None), \
             patch.object(WhatsAppService, "get_groq_api_key", return_value="gsk_test_key"), \
             patch("requests.post") as mock_groq_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "السلام علیکم، پکیج قیمت څه ده؟"}
            mock_groq_post.return_value = mock_resp

            transcript = WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id)
            self.assertEqual(transcript, "السلام علیکم، پکیج قیمت څه ده؟")
            mock_groq_post.assert_called_once()
            call_kwargs = mock_groq_post.call_args[1]
            self.assertEqual(call_kwargs["data"]["model"], "whisper-large-v3")


    def test_generate_spoken_audio_synthesizes_mp3_when_available(self):
        """Verifies generate_spoken_audio returns audio bytes and audio/mpeg when TTS engine is available."""
        fake_audio_bytes = b"ID3\x03\x00\x00\x00\x00\x00" + (b"\x00" * 200)
        with patch("gtts.gTTS") as mock_gtts_cls:
            mock_instance = MagicMock()
            def fake_write(fp):
                fp.write(fake_audio_bytes)
            mock_instance.write_to_fp.side_effect = fake_write
            mock_gtts_cls.return_value = mock_instance

            res = WhatsAppService.generate_spoken_audio("Hello, your order is ready.", language="english")
            self.assertIsNotNone(res)
            audio_bytes, fn, mime = res
            self.assertEqual(audio_bytes, fake_audio_bytes)
            self.assertEqual(fn, "voice_reply.mp3")
            self.assertEqual(mime, "audio/mpeg")

    def test_generate_spoken_audio_returns_none_when_unconfigured(self):
        """Verifies generate_spoken_audio returns None when no TTS provider is available."""
        with patch.dict("sys.modules", {"gtts": None}), \
             patch.object(WhatsAppService, "_get_tenant_or_global_setting", return_value=None), \
             patch.dict(os.environ, {}, clear=True):
            res = WhatsAppService.generate_spoken_audio("Test reply without TTS", language="english")
            self.assertIsNone(res)

    def test_send_green_api_file_uploads_and_dispatches_by_url(self):
        """Verifies send_green_api_file calls uploadFile, sendFileByUrl, and records outbound message."""
        fake_audio_bytes = b"\xFF\xFB\x90\x44" * 50
        with patch.object(WhatsAppService, "get_config", return_value={
            "green_api_id_instance": "710722761603",
            "green_api_token_instance": "mock_token_123",
            "green_api_host": "https://7107.api.greenapi.com"
        }), patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            # 1. uploadFile mock response
            mock_up_resp = MagicMock()
            mock_up_resp.status_code = 200
            mock_up_resp.text = json.dumps({"urlFile": "https://storage.greenapi.com/reply.mp3"})
            mock_up_resp.json.return_value = {"urlFile": "https://storage.greenapi.com/reply.mp3"}

            # 2. sendFileByUrl mock response
            mock_send_resp = MagicMock()
            mock_send_resp.status_code = 200
            mock_send_resp.text = json.dumps({"idMessage": "GREEN_OUT_AUDIO_001"})
            mock_send_resp.json.return_value = {"idMessage": "GREEN_OUT_AUDIO_001"}

            mock_session.post.side_effect = [mock_up_resp, mock_send_resp]

            result = WhatsAppService.send_green_api_file(
                organization_id=self.org.id,
                to_phone="923209350858",
                file_bytes=fake_audio_bytes,
                filename="voice_reply.mp3",
                mime_type="audio/mpeg",
                caption="Here is your audio answer",
                quoted_message_id="INBOUND_9001"
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["whatsapp_message_id"], "GREEN_OUT_AUDIO_001")
            self.assertEqual(result["url_file"], "https://storage.greenapi.com/reply.mp3")

            # Check DB ledger
            db_msg = WhatsAppMessage.query.filter_by(whatsapp_message_id="GREEN_OUT_AUDIO_001").first()
            self.assertIsNotNone(db_msg)
            self.assertEqual(db_msg.direction, "outbound")
            self.assertEqual(db_msg.body, "Here is your audio answer")
            self.assertTrue(db_msg.to_dict()["is_audio"])

    def test_handle_inbound_auto_response_dispatches_voice_audio_reply(self):
        """Verifies handle_inbound_auto_response generates and sends spoken audio when inbound is voice."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        fake_audio = b"dummy_spoken_audio_bytes"
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_gemini_key"), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                "reply_body": "Thank you for reaching out! We can assist you with that.",
                "intent": "general_inquiry",
                "lead_score": 10,
                "language": "english"
             }), patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_audio, "voice_reply.mp3", "audio/mpeg")), \
             patch.object(WhatsAppService, "get_active_provider", return_value="green_api"), \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": True, "whatsapp_message_id": "AUDIO_OUT_100"}) as mock_send_file:

            WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="Can you tell me about OpsFlow Cloud features?",
                message_id="VOICE_INBOUND_TRIGGER_1",
                is_voice=True
            )

            mock_send_file.assert_called_once()
            call_kwargs = mock_send_file.call_args[1]
            self.assertEqual(call_kwargs["file_bytes"], fake_audio)
            self.assertEqual(call_kwargs["filename"], "voice_reply.mp3")

    def test_handle_inbound_auto_response_falls_back_to_text_when_tts_unsupported(self):
        """Verifies handle_inbound_auto_response smoothly falls back to text when TTS is unconfigured."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_gemini_key"), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                "reply_body": "Here is our pricing list.",
                "intent": "pricing",
                "lead_score": 20,
                "language": "english"
             }), patch.object(WhatsAppService, "generate_spoken_audio", return_value=None), \
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "TEXT_OUT_100"}) as mock_send_msg:

            WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="What is the pricing?",
                message_id="VOICE_INBOUND_TRIGGER_2",
                is_voice=True
            )

            mock_send_msg.assert_called_once()
            call_kwargs = mock_send_msg.call_args[1]
            self.assertEqual(call_kwargs["message_text"], "Here is our pricing list.")


    def test_send_green_api_file_fails_safely_without_recording_success(self):
        """Verifies send_green_api_file returns failure and does not record an outbound success message when Green API fails."""
        fake_audio_bytes = b"\xFF\xFB\x90\x44" * 20
        with patch.object(WhatsAppService, "get_config", return_value={
            "green_api_id_instance": "710722761603",
            "green_api_token_instance": "mock_token_123",
            "green_api_host": "https://7107.api.greenapi.com"
        }), patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            # Simulate 500 error on uploadFile
            mock_up_resp = MagicMock()
            mock_up_resp.status_code = 500
            mock_up_resp.text = "Internal Server Error"
            mock_session.post.return_value = mock_up_resp

            result = WhatsAppService.send_green_api_file(
                organization_id=self.org.id,
                to_phone="923209350858",
                file_bytes=fake_audio_bytes,
                filename="voice_reply.mp3"
            )

            self.assertFalse(result["success"])
            self.assertEqual(result["status"], "failed")
            # Verify no outbound audioMessage record was stored in the database
            rec = WhatsAppMessage.query.filter_by(
                organization_id=self.org.id,
                direction="outbound",
                message_type="audioMessage"
            ).first()
            self.assertIsNone(rec)

    def test_handle_inbound_auto_response_falls_back_to_text_when_audio_send_fails(self):
        """Verifies handle_inbound_auto_response falls back to sending text reply if audio upload fails."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        fake_audio = b"dummy_audio"
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_gemini_key"), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                "reply_body": "Fallback text response due to audio failure.",
                "intent": "general_inquiry",
                "lead_score": 10,
                "language": "english"
             }), patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_audio, "voice_reply.mp3", "audio/mpeg")), \
             patch.object(WhatsAppService, "get_active_provider", return_value="green_api"), \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": False, "status": "failed"}) as mock_send_file, \
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "FALLBACK_TEXT_001"}) as mock_send_msg:

            WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="Can you help me?",
                message_id="VOICE_INBOUND_TRIGGER_FAIL_AUDIO",
                is_voice=True
            )

            mock_send_file.assert_called_once()
            mock_send_msg.assert_called_once()
            self.assertEqual(mock_send_msg.call_args[1]["message_text"], "Fallback text response due to audio failure.")


    def test_transcribe_audio_uses_openai_whisper_primary(self):
        """Verifies _transcribe_audio calls OpenAI Whisper API (whisper-1) when OPENAI_API_KEY is configured."""
        fake_audio = b"\x00" * 100
        with patch.object(WhatsAppService, "get_openai_api_key", return_value="sk-test-openai-key"), \
             patch("requests.post") as mock_openai_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "Salam, OpsFlow Cloud demo chaheye."}
            mock_openai_post.return_value = mock_resp

            transcript = WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id)
            self.assertEqual(transcript, "Salam, OpsFlow Cloud demo chaheye.")
            mock_openai_post.assert_called_once()
            call_url = mock_openai_post.call_args[0][0]
            self.assertEqual(call_url, "https://api.openai.com/v1/audio/transcriptions")
            call_data = mock_openai_post.call_args[1]["data"]
            self.assertEqual(call_data["model"], "whisper-1")

    def test_handle_inbound_auto_response_downloads_and_transcribes_incoming_voice_note(self):
        """Verifies handle_inbound_auto_response downloads audio from download_url and transcribes it to text."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        fake_audio_bytes = b"OggS" + b"\x00" * 80
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_key"), \
             patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes) as mock_dl, \
             patch.object(WhatsAppService, "_transcribe_audio", return_value="What are your service packages?") as mock_tr, \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                 "reply_body": "We offer Enterprise and Startup packages.",
                 "intent": "pricing",
                 "lead_score": 30,
                 "language": "english"
             }) as mock_gen, \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=None), \
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "TXT_OUT_999"}):

            WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="[Voice note]",
                message_id="VOICE_INBOUND_999",
                is_voice=True,
                download_url="https://do-media.com/test_audio.oga"
            )

            mock_dl.assert_called_once_with(
                chat_id="923209350858",
                message_id="VOICE_INBOUND_999",
                download_url="https://do-media.com/test_audio.oga",
                organization_id=self.org.id
            )
            mock_tr.assert_called_once_with(fake_audio_bytes, organization_id=self.org.id)
            mock_gen.assert_called_once()
            # The AI generation should have received the transcribed text!
            self.assertEqual(mock_gen.call_args[1]["message_body"], "What are your service packages?")


if __name__ == "__main__":
    unittest.main()

