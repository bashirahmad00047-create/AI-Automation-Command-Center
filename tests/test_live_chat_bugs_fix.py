import unittest
import json
from app import create_app, db
from models import WhatsAppMessage, Organization
from whatsapp_service import WhatsAppService

class TestLiveChatBugsFix(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.org = Organization.query.first()
        if not self.org:
            self.org = Organization(id="org-test-live", name="BashFlow Cloud")
            db.session.add(self.org)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_dynamic_fallback_answers_services_in_roman_urdu(self):
        """Verifies that asking about services in Roman Urdu directly explains BashFlow Cloud instead of generic static fallback."""
        res = WhatsAppService.generate_ai_auto_response(
            organization_id=self.org.id,
            message_body="APNI service k bat e batawo",
            sender_name="Ali Khan",
            sender_phone="923456789012"
        )
        reply = res.get("reply_body", "")
        # Must not contain obsolete static canned fallback
        self.assertNotIn("A solutions specialist is reviewing", reply)
        self.assertNotIn("We received your voice note", reply)
        # Must explain BashFlow Cloud features
        self.assertTrue(any(word in reply for word in ("BashFlow Cloud", "Enterprise AI", "WhatsApp AI", "Auto-Responder", "Voice Note", "CRM")))

    def test_dynamic_fallback_for_voice_notes(self):
        """Verifies voice note acknowledgement introduces BashFlow Cloud instead of generic static fallback."""
        res = WhatsAppService.generate_ai_auto_response(
            organization_id=self.org.id,
            message_body="[Voice note]",
            sender_name="Ahmed",
            sender_phone="923456789012"
        )
        reply = res.get("reply_body", "")
        self.assertNotIn("We received your voice note, thank you! Our team will listen", reply)
        self.assertTrue("BashFlow Cloud" in reply)

    def test_models_media_url_db_text_and_to_dict(self):
        """Verifies WhatsAppMessage.media_url is db.Text and correctly returned in to_dict()."""
        large_base64 = "data:audio/ogg;base64," + ("A" * 1500)
        msg = WhatsAppMessage(
            organization_id=self.org.id,
            whatsapp_message_id="wamid.test_media_url_001",
            sender="923001234567",
            recipient="system",
            message_type="audio",
            body="🎤 Test voice note transcript",
            media_url=large_base64
        )
        db.session.add(msg)
        db.session.commit()

        fetched = WhatsAppMessage.query.filter_by(whatsapp_message_id="wamid.test_media_url_001").first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.media_url, large_base64)
        m_dict = fetched.to_dict()
        self.assertEqual(m_dict.get("media_url"), large_base64)
        self.assertTrue(m_dict.get("is_audio"))

    def test_app_js_has_blob_converter_for_audio(self):
        """Verifies static/js/app.js converts base64 audio URLs into ObjectURL blobs for smooth playback."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()
        self.assertIn("function getAudioBlobUrl", app_js)
        self.assertIn("URL.createObjectURL(blob)", app_js)
        self.assertIn("getAudioBlobUrl(safeMediaUrl)", app_js)

if __name__ == '__main__':
    unittest.main()
