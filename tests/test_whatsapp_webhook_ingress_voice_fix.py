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

    def test_transcribe_audio_uses_groq_distil_whisper_primary(self):
        """Verifies _transcribe_audio uses Groq Whisper API (distil-whisper-large-v3) as primary for sub-second STT."""
        fake_audio = b"\x00" * 100
        with patch.object(WhatsAppService, "get_groq_api_key", return_value="gsk_test_key"), \
             patch("requests.post") as mock_groq_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "Aap ki subscription details kya hain?"}
            mock_groq_post.return_value = mock_resp

            transcript = WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id)
            self.assertEqual(transcript, "Aap ki subscription details kya hain?")
            mock_groq_post.assert_called_once()
            call_url = mock_groq_post.call_args[0][0]
            self.assertEqual(call_url, "https://api.groq.com/openai/v1/audio/transcriptions")
            call_kwargs = mock_groq_post.call_args[1]
            self.assertEqual(call_kwargs["data"]["model"], "distil-whisper-large-v3")

    def test_transcribe_audio_uses_groq_whisper_fallback(self):
        """Verifies _transcribe_audio falls back to Groq whisper-large-v3 when distil model fails."""
        fake_audio = b"\x00" * 100
        with patch.object(WhatsAppService, "get_groq_api_key", return_value="gsk_test_key"), \
             patch("requests.post") as mock_groq_post:
            fail_resp = MagicMock()
            fail_resp.status_code = 503
            ok_resp = MagicMock()
            ok_resp.status_code = 200
            ok_resp.json.return_value = {"text": "السلام علیکم، پکیج قیمت څه ده؟"}
            mock_groq_post.side_effect = [fail_resp, ok_resp]

            transcript = WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id)
            self.assertEqual(transcript, "السلام علیکم، پکیج قیمت څه ده؟")
            self.assertEqual(mock_groq_post.call_count, 2)
            first_call_model = mock_groq_post.call_args_list[0][1]["data"]["model"]
            second_call_model = mock_groq_post.call_args_list[1][1]["data"]["model"]
            self.assertEqual(first_call_model, "distil-whisper-large-v3")
            self.assertEqual(second_call_model, "whisper-large-v3")


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
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "TXT_OUT_100"}), \
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
        """Verifies _transcribe_audio calls OpenAI Whisper API (whisper-1) when Groq is unconfigured and OPENAI_API_KEY is set."""
        fake_audio = b"\x00" * 100
        with patch.object(WhatsAppService, "get_groq_api_key", return_value=None), \
             patch.object(WhatsAppService, "get_openai_api_key", return_value="sk-test-openai-key"), \
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
                download_url="https://do-media.com/test_audio.oga",
                sync_transcribe=True
            )

            mock_dl.assert_called_once_with(
                chat_id="923209350858",
                message_id="VOICE_INBOUND_999",
                download_url="https://do-media.com/test_audio.oga",
                organization_id=self.org.id
            )
            mock_tr.assert_called_once_with(fake_audio_bytes, organization_id=self.org.id, timeout=3.0)
            mock_gen.assert_called_once()
            # The AI generation should have received the transcribed text!
            self.assertEqual(mock_gen.call_args[1]["message_body"], "What are your service packages?")



    def test_voice_note_direct_ai_response_with_oga_audio_and_text(self):
        """Verifies voice notes are transcribed, routed directly to AI responder, and replied with both Urdu .oga audio and text."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        fake_audio_bytes = b"OggS" + b"\x00" * 80
        fake_oga_reply = b"OggS" + b"\x01" * 80

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_key"), \
             patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes) as mock_dl, \
             patch.object(WhatsAppService, "_transcribe_audio", return_value="Aap kaun si service de rahe hain?") as mock_tr, \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                 "reply_body": "Hum OpsFlow Cloud automation, WhatsApp integration, aur alert routing services faraham karte hain.",
                 "intent": "lead_inquiry",
                 "lead_score": 85,
                 "language_format": "roman_urdu"
             }) as mock_gen, \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_oga_reply, "voice_reply.oga", "audio/ogg; codecs=opus")) as mock_tts, \
             patch.object(WhatsAppService, "get_active_provider", return_value="green_api"), \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": True, "whatsapp_message_id": "AUDIO_MSG_123"}) as mock_send_file, \
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "TXT_MSG_123"}) as mock_send_text:

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="[Voice note]",
                message_id="VOICE_INBOUND_DIRECT_001",
                is_voice=True,
                download_url="https://do-media-7107.fra1.digitaloceanspaces.com/voice.oga"
            )

            # 1. Download & transcription were called directly
            mock_dl.assert_called_once()
            mock_tr.assert_called_once()

            # 2. AI generation was called directly with the transcribed question
            mock_gen.assert_called_once()
            self.assertEqual(mock_gen.call_args[1]["message_body"], "Aap kaun si service de rahe hain?")

            # 3. TTS converted answer into Urdu .oga audio
            mock_tts.assert_called_once()
            self.assertEqual(mock_tts.call_args[1]["language"], "ur")
            self.assertEqual(mock_tts.call_args[1]["output_format"], "oga")

            # 4. Both Green-API audio (.oga) and text replies were dispatched
            mock_send_file.assert_called_once()
            self.assertEqual(mock_send_file.call_args[1]["filename"], "voice_reply.oga")
            mock_send_text.assert_called_once()
            self.assertIn("OpsFlow Cloud automation", mock_send_text.call_args[1]["message_text"])

            # 5. Generic static acknowledgment was NOT sent
            self.assertNotIn("Aap ka voice message moosool ho gaya hai", res["reply_body"])
            self.assertIn("OpsFlow Cloud automation", res["reply_body"])

    def test_async_transcribe_and_logs_text_to_crm_dashboard(self):
        """Verifies asynchronous audio transcription updates WhatsAppMessage and logs text to CRM Lead dashboard."""
        fake_audio_bytes = b"OggS" + b"\x00" * 60
        transcript_text = "Mujhe enterprise automation package ki details chaheye."

        # Create inbound WhatsAppMessage record
        inbound_msg = WhatsAppMessage(
            organization_id=self.org.id,
            whatsapp_message_id="ASYNC_VOICE_MSG_777",
            sender="923209350858",
            recipient="bot",
            direction="inbound",
            message_type="audioMessage",
            body="[Voice note]",
            status="received"
        )
        db.session.add(inbound_msg)

        # Create existing Lead in CRM dashboard
        from models import Lead
        lead = Lead(
            organization_id=self.org.id,
            name="Ahmad Khan",
            phone="923209350858",
            message="[Voice note]",
            intent="lead_inquiry"
        )
        db.session.add(lead)
        db.session.commit()

        with patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes),              patch.object(WhatsAppService, "_transcribe_audio", return_value=transcript_text):

            t = WhatsAppService.async_transcribe_and_log_crm(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_id="ASYNC_VOICE_MSG_777",
                download_url="https://do-media.com/test.oga",
                sender_name="Ahmad Khan",
                app_obj=self.app,
                dispatch_follow_up=False
            )
            # Wait for background thread to complete
            t.join(timeout=4.0)

            # Check that WhatsAppMessage was updated with transcript
            db.session.expire_all()
            updated_msg = WhatsAppMessage.query.filter_by(whatsapp_message_id="ASYNC_VOICE_MSG_777").first()
            self.assertEqual(updated_msg.body, transcript_text)

            # Check that CRM Lead was updated with transcript
            updated_lead = Lead.query.filter_by(phone="923209350858").first()
            self.assertIn(transcript_text, updated_lead.message)

    def test_transcribe_audio_strict_3_second_timeout(self):
        """Verifies _transcribe_audio passes strict 3-second timeout to OpenAI and Groq APIs."""
        fake_audio = b"OggS" + b"\x00" * 40
        with patch.object(WhatsAppService, "get_groq_api_key", return_value="fake_groq"), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"text": "Test transcript"}

            WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id, timeout=3.0)
            mock_post.assert_called_once()
            call_timeout = mock_post.call_args[1].get("timeout")
            self.assertLessEqual(call_timeout, 3.0)
            self.assertEqual(mock_post.call_args[1]["data"]["model"], "distil-whisper-large-v3")

    def test_transcribe_audio_strict_3_second_timeout_openai(self):
        """Verifies _transcribe_audio passes strict 3-second timeout to OpenAI when Groq not set."""
        fake_audio = b"OggS" + b"\x00" * 40
        with patch.object(WhatsAppService, "get_groq_api_key", return_value=None), \
             patch.object(WhatsAppService, "get_openai_api_key", return_value="fake_openai"), \
             patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"text": "Test transcript"}

            WhatsAppService._transcribe_audio(fake_audio, organization_id=self.org.id, timeout=3.0)
            mock_post.assert_called_once()
            call_timeout = mock_post.call_args[1].get("timeout")
            self.assertLessEqual(call_timeout, 3.0)

    def test_is_audio_message_detects_all_voice_and_oga_variants(self):
        """Verifies is_audio_message detects .oga URLs, audioMessage, ptt, and voice note bodies."""
        self.assertTrue(WhatsAppService.is_audio_message("audioMessage", "[Voice note]", None))
        self.assertTrue(WhatsAppService.is_audio_message("fileMessage", None, "https://storage.com/audio.oga"))
        self.assertTrue(WhatsAppService.is_audio_message(None, "[voice note]", None))
        self.assertTrue(WhatsAppService.is_audio_message("ptt", None, None))
        self.assertFalse(WhatsAppService.is_audio_message("textMessage", "Hello there", None))


    def test_async_transcribe_dispatches_follow_up_ai_reply(self):
        """Verifies asynchronous audio transcription dispatches contextual AI follow-up reply."""
        fake_audio_bytes = b"OggS" + b"\x00" * 60
        transcript_text = "What is the price of OpsFlow Cloud?"

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_key"), \
             patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes), \
             patch.object(WhatsAppService, "_transcribe_audio", return_value=transcript_text), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={"reply_body": "Starter is $29/mo."}) as mock_gen, \
             patch.object(WhatsAppService, "send_message") as mock_send:

            t = WhatsAppService.async_transcribe_and_log_crm(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_id="ASYNC_VOICE_MSG_888",
                download_url="https://do-media.com/test.oga",
                sender_name="Ahmad Khan",
                app_obj=self.app,
                dispatch_follow_up=True
            )
            t.join(timeout=4.0)
            mock_send.assert_called_once_with(
                organization_id=self.org.id,
                to_phone="923209350858",
                message_text="Starter is $29/mo."
            )

    def test_send_green_api_file_supports_two_arg_calling(self):
        """Verifies send_green_api_file works when called as send_green_api_file(to_phone, file_bytes)."""
        fake_audio_bytes = b"OggS\x00" * 20
        with patch.object(WhatsAppService, "get_config", return_value={
            "green_api_id_instance": "710722761603",
            "green_api_token_instance": "mock_token_123",
            "green_api_host": "https://7107.api.greenapi.com"
        }), patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            mock_up_resp = MagicMock()
            mock_up_resp.status_code = 200
            mock_up_resp.text = json.dumps({"urlFile": "https://storage.greenapi.com/reply.oga"})
            mock_up_resp.json.return_value = {"urlFile": "https://storage.greenapi.com/reply.oga"}

            mock_send_resp = MagicMock()
            mock_send_resp.status_code = 200
            mock_send_resp.text = json.dumps({"idMessage": "GREEN_OUT_2_ARG_001"})
            mock_send_resp.json.return_value = {"idMessage": "GREEN_OUT_2_ARG_001"}

            mock_session.post.side_effect = [mock_up_resp, mock_send_resp]

            result = WhatsAppService.send_green_api_file(
                "923209350858",
                fake_audio_bytes,
                filename="voice_reply.oga",
                mime_type="audio/ogg; codecs=opus"
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["recipient"], "923209350858")
            self.assertEqual(result["whatsapp_message_id"], "GREEN_OUT_2_ARG_001")

    def test_send_green_api_preserves_group_chat_ids(self):
        """Verifies Green-API message and file dispatching preserve @g.us group chat IDs."""
        fake_audio_bytes = b"OggS\x00" * 20
        group_id = "120363024848@g.us"
        with patch.object(WhatsAppService, "get_config", return_value={
            "green_api_id_instance": "710722761603",
            "green_api_token_instance": "mock_token_123",
            "green_api_host": "https://7107.api.greenapi.com"
        }), patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            # 1. Test message dispatch
            mock_msg_resp = MagicMock()
            mock_msg_resp.status_code = 200
            mock_msg_resp.text = json.dumps({"idMessage": "GROUP_MSG_001"})
            mock_msg_resp.json.return_value = {"idMessage": "GROUP_MSG_001"}
            mock_session.post.return_value = mock_msg_resp

            msg_res = WhatsAppService.send_green_api_message(
                to_phone=group_id,
                message_text="Hello team"
            )
            self.assertTrue(msg_res["success"])
            call_payload = mock_session.post.call_args[1]["json"]
            self.assertEqual(call_payload["chatId"], group_id)

    def test_generate_spoken_audio_cleans_markdown_and_prioritizes_openai(self):
        """Verifies generate_spoken_audio strips Markdown formatting and prioritizes OpenAI TTS when key is set."""
        fake_opus = b"OggS\x01\x02\x03"
        with patch.object(WhatsAppService, "get_openai_api_key", return_value="sk-test-openai"), \
             patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = fake_opus
            mock_resp.iter_content.return_value = [fake_opus]
            mock_post.return_value = mock_resp

            raw_markdown = "**OpsFlow Cloud** automation, *WhatsApp* alerts, and [packages] are ready!"
            res = WhatsAppService.generate_spoken_audio(raw_markdown, language="ur", output_format="oga")
            self.assertIsNotNone(res)
            audio_bytes, fn, mime = res
            self.assertEqual(audio_bytes, fake_opus)
            self.assertEqual(fn, "voice_reply.oga")
            self.assertEqual(mime, "audio/ogg; codecs=opus")

            # Assert cleaned text was sent to OpenAI
            mock_post.assert_called_once()
            called_json = mock_post.call_args[1]["json"]
            self.assertNotIn("**", called_json["input"])
            self.assertNotIn("*", called_json["input"])
            self.assertEqual(called_json["response_format"], "opus")

    def test_handle_inbound_auto_response_graceful_when_dispatch_empty(self):
        """Verifies handle_inbound_auto_response handles None dispatch result gracefully without raising AttributeError."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_key"), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={"reply_body": "Sample reply", "intent": "general_inquiry"}), \
             patch.object(WhatsAppService, "send_message", return_value=None):

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="Can you help me?",
                message_id="TEST_GRACEFUL_DISPATCH_001"
            )
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])

    def test_voice_note_text_dispatched_instantly_even_if_tts_raises_exception(self):
        """Verifies that if TTS audio synthesis raises an unexpected exception, the Gemini AI text reply is GUARANTEED to dispatch instantly without failing."""
        WhatsAppService.clear_recent_replied_trigger_ids()
        fake_audio_bytes = b"OggS\x00" * 40
        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}), \
             patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_key"), \
             patch.object(WhatsAppService, "_download_media", return_value=fake_audio_bytes), \
             patch.object(WhatsAppService, "_transcribe_audio", return_value="Aap ki support timings kya hain?"), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={
                 "reply_body": "Hum 24/7 technical support faraham karte hain.",
                 "intent": "support_inquiry"
             }), \
             patch.object(WhatsAppService, "generate_spoken_audio", side_effect=RuntimeError("TTS engine crashed")), \
             patch.object(WhatsAppService, "send_message", return_value={"success": True, "whatsapp_message_id": "TXT_GUARANTEED_123"}) as mock_send_text:

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="[Voice note]",
                message_id="VOICE_TTS_FAIL_GUARANTEE_001",
                is_voice=True
            )

            # Text response is GUARANTEED to be dispatched instantly via Green-API
            mock_send_text.assert_called_once_with(
                organization_id=self.org.id,
                to_phone="923209350858",
                message_text="Hum 24/7 technical support faraham karte hain."
            )
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            self.assertEqual(res["reply_body"], "Hum 24/7 technical support faraham karte hain.")

    def test_generate_spoken_audio_uses_edge_neural_hd_voice(self):
        """Verifies generate_spoken_audio uses Microsoft Edge Neural HD human voice when enabled."""
        fake_edge_audio = b"\xff\xf3\x84\xc4" + b"\x00" * 300
        with patch.object(WhatsAppService, "get_openai_api_key", return_value=None), \
             patch.object(WhatsAppService, "_synthesize_edge_tts", return_value=fake_edge_audio) as mock_edge:
            try:
                WhatsAppService._force_test_edge_tts = True
                res = WhatsAppService.generate_spoken_audio(
                    "Aap ka khush amdeed. Hum aap ki poori madad karenge.",
                    language="urdu",
                    output_format="oga"
                )
                self.assertIsNotNone(res)
                audio_bytes, fn, mime = res
                self.assertEqual(audio_bytes, fake_edge_audio)
                mock_edge.assert_called_once()
                self.assertEqual(mock_edge.call_args[1]["language"], "urdu")
            finally:
                WhatsAppService._force_test_edge_tts = False

    def test_verify_green_api_instance_credentials(self):
        """Verifies Green-API instance credentials validation and authorized status reporting."""
        with patch.object(WhatsAppService, "get_config", return_value={
            "green_api_id_instance": "710722761603",
            "green_api_token_instance": "30cf60_mock_token",
            "green_api_host": "https://7107.api.greenapi.com"
        }), patch.object(WhatsAppService, "get_http_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = json.dumps({"stateInstance": "authorized"})
            mock_resp.json.return_value = {"stateInstance": "authorized"}
            mock_session.get.return_value = mock_resp

            status_res = WhatsAppService.test_green_api_connection(organization_id=self.org.id)
            self.assertTrue(status_res["success"])
            self.assertEqual(status_res["status"], "authorized")
            self.assertEqual(status_res["id_instance"], "710722761603")
            self.assertIn("ONLINE and AUTHORIZED", status_res["message"])

    def test_generate_spoken_audio_uses_openai_tts_1_hd_streaming_nova_and_onyx(self):
        """Verifies OpenAI HD TTS uses model tts-1-hd, streaming bytes, and defaults to nova with onyx override support."""
        fake_stream_chunks = [b"OggS\x01\x00", b"\x02\x03chunk2", b"\x04\x05chunk3"]
        combined_expected = b"".join(fake_stream_chunks)

        with patch.object(WhatsAppService, "get_openai_api_key", return_value="sk-test-openai-key"), \
             patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.iter_content.return_value = fake_stream_chunks
            mock_post.return_value = mock_resp

            # Default voice is nova
            res = WhatsAppService.generate_spoken_audio(
                "Aap ka hukum sar ankhon par, hum tayyar hain.",
                language="urdu",
                output_format="oga"
            )
            self.assertIsNotNone(res)
            audio_bytes, fn, mime = res
            self.assertEqual(audio_bytes, combined_expected)
            self.assertEqual(fn, "voice_reply.oga")
            self.assertEqual(mime, "audio/ogg; codecs=opus")

            payload = mock_post.call_args[1]["json"]
            self.assertEqual(payload["model"], "tts-1-hd")
            self.assertEqual(payload["voice"], "nova")
            self.assertEqual(payload["response_format"], "opus")
            self.assertTrue(mock_post.call_args[1]["stream"])

        # Test onyx voice override via environment variable
        with patch.object(WhatsAppService, "get_openai_api_key", return_value="sk-test-openai-key"), \
             patch.dict(os.environ, {"OPENAI_TTS_VOICE": "onyx"}), \
             patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.iter_content.return_value = fake_stream_chunks
            mock_post.return_value = mock_resp

            res2 = WhatsAppService.generate_spoken_audio(
                "Hum aap ki khidmat ke liye hazir hain.",
                language="urdu",
                output_format="oga"
            )
            self.assertIsNotNone(res2)
            payload2 = mock_post.call_args[1]["json"]
            self.assertEqual(payload2["voice"], "onyx")

    def test_call_gemini_ai_direct_model_without_list_models_delay(self):
        """Verifies call_gemini_ai directly invokes fast target models without blocking on list_models()."""
        mock_genai = MagicMock()
        mock_model_inst = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "OpsFlow Cloud CRM aur automation services faraham karta hai."
        mock_model_inst.generate_content.return_value = mock_resp
        mock_genai.GenerativeModel.return_value = mock_model_inst

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="AIzaSyMockKey"), \
             patch.object(WhatsAppService, "get_gemini_model_name", return_value="gemini-1.5-flash"), \
             patch.dict("sys.modules", {"google.generativeai": mock_genai}):

            reply = WhatsAppService.call_gemini_ai(
                user_message="Aap kaun si service de rahe hain?",
                organization_id=self.org.id
            )

            self.assertEqual(reply, "OpsFlow Cloud CRM aur automation services faraham karta hai.")
            mock_genai.configure.assert_called_with(api_key="AIzaSyMockKey")
            # Verify list_models() is NOT called, ensuring fast sub-second execution
            self.assertFalse(mock_genai.list_models.called)
            mock_genai.GenerativeModel.assert_called_with("gemini-1.5-flash")

if __name__ == "__main__":
    unittest.main()

