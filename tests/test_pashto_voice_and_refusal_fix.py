import unittest
from unittest.mock import MagicMock, patch
import json
from app import create_app
from database import db
from models import Organization, WhatsAppMessage
from whatsapp_service import WhatsAppService


class TestPashtoVoiceAndRefusalFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.app_context.pop()

    def setUp(self):
        self.org = Organization.query.filter_by(id="org-pashto-test").first()
        if not self.org:
            self.org = Organization(id="org-pashto-test", name="OpsFlow Cloud", slug="opsflow-pashto-test")
            db.session.add(self.org)
            db.session.commit()
        with WhatsAppService._media_cache_lock:
            WhatsAppService._downloaded_media_cache.clear()
            WhatsAppService._transcription_cache.clear()

    def test_is_valid_audio_buffer(self):
        """Verifies is_valid_audio_buffer rejects JSON, HTML, errors, and short buffers."""
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(None))
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(b""))
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(b"too short"))
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(b'{"error": "file not found", "status": 404}'))
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(b'<html><body>502 Bad Gateway</body></html>'))
        self.assertFalse(WhatsAppService.is_valid_audio_buffer(b'<!DOCTYPE html><html>error page</html>'))
        
        # Valid audio byte streams
        ogg_bytes = b"OggS\x00\x02" + (b"\x00" * 100)
        mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00" + (b"\x00" * 100)
        self.assertTrue(WhatsAppService.is_valid_audio_buffer(ogg_bytes))
        self.assertTrue(WhatsAppService.is_valid_audio_buffer(mp3_bytes))

    def test_is_prompt_echo_or_refusal(self):
        """Verifies _is_prompt_echo_or_refusal flags prompt echoes and refusals."""
        self.assertTrue(WhatsAppService._is_prompt_echo_or_refusal(
            "Provide an accurate, verbatim transcription of this WhatsApp voice message. If spoken in Pashto, transcribe accurately in Urdu"
        ))
        self.assertTrue(WhatsAppService._is_prompt_echo_or_refusal("If spoken in Pashto, transcribe accurately in Urdu"))
        self.assertTrue(WhatsAppService._is_prompt_echo_or_refusal("Output ONLY the transcribed speech text without introductory"))
        self.assertTrue(WhatsAppService._is_prompt_echo_or_refusal("I cannot provide Pashto-to-Urdu transcription service."))
        self.assertTrue(WhatsAppService._is_prompt_echo_or_refusal("Unable to transcribe this audio."))
        
        # Real customer speech should NOT be flagged
        self.assertFalse(WhatsAppService._is_prompt_echo_or_refusal("Salam, mujhe aap ke software ke rates janne hain"))
        self.assertFalse(WhatsAppService._is_prompt_echo_or_refusal("سلام زه غواړم ستاسو د پیکیج معلومات واخلم"))
        self.assertFalse(WhatsAppService._is_prompt_echo_or_refusal("Humara order kab tak pohnchega?"))

    def test_transcribe_audio_filters_prompt_echo_from_groq(self):
        """Verifies that if Groq returns an echo of the transcription prompt, it is rejected and not returned."""
        valid_audio = b"OggS\x00\x02" + (b"\x00" * 200)
        with patch.object(WhatsAppService, "get_groq_api_key", return_value="gsk_test"), \
             patch("requests.post") as mock_post:
            
            # Groq returns prompt echo on first try, then a clean fallback or None
            echo_resp = MagicMock()
            echo_resp.status_code = 200
            echo_resp.json.return_value = {
                "text": "Provide an accurate, verbatim transcription of this WhatsApp voice message. If spoken in Pashto, transcribe accurately in Urdu"
            }
            
            second_resp = MagicMock()
            second_resp.status_code = 200
            second_resp.json.return_value = {
                "text": "Salam, mujhay pricing batayein."
            }
            mock_post.side_effect = [echo_resp, second_resp]

            transcript = WhatsAppService._transcribe_audio(valid_audio, organization_id=self.org.id)
            self.assertEqual(transcript, "Salam, mujhay pricing batayein.")

    def test_auto_responder_guards_against_echoed_prompt(self):
        """Verifies AI Auto-Responder does not refuse Pashto-to-Urdu transcription service when receiving prompt echo."""
        prompt_echo = "Provide an accurate, verbatim transcription of this WhatsApp voice message. If spoken in Pashto, transcribe accurately in Urdu"
        
        res = WhatsAppService.generate_ai_auto_response(
            organization_id=self.org.id,
            message_body=prompt_echo,
            sender_phone="+923001234567"
        )
        self.assertNotIn("transcription service", res["reply_body"].lower())
        self.assertNotIn("cannot transcribe", res["reply_body"].lower())
        self.assertIn("voice note", res["reply_body"].lower())


if __name__ == "__main__":
    unittest.main()
