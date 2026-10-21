"""Focused test suite for Automatic Language-Matched Replies in OpsFlow Cloud WhatsApp AI Responder.

Verifies:
1. Detects customer language as Pashto (Arabic script), Roman Pashto, Urdu (Arabic script), Roman Urdu, or English.
2. Directs Google Gemini AI and Groq LPU with explicit language directives.
3. Fallback responses (when AI is offline) match the customer's detected language naturally.
4. Short follow-up messages preserve language context from conversation history.
5. Media receipts (images, documents, voice notes) are language-matched.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestWhatsAppLanguageMatchedReplies(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-pk-test").first()
        if not self.org:
            self.org = Organization(id="org-pk-test", name="OpsFlow Cloud PK", slug="opsflow-pk")
            db.session.add(self.org)
            db.session.commit()

        WhatsAppService.clear_recent_replied_trigger_ids()

    def tearDown(self):
        WhatsAppService.clear_recent_replied_trigger_ids()
        db.session.rollback()
        self.ctx.pop()

    # -------------------------------------------------------------
    # 1. Language Detection Unit Tests
    # -------------------------------------------------------------

    def test_detect_language_pashto_arabic_script(self):
        """Verifies Pashto written in Arabic script is accurately detected."""
        samples = [
            "سلام وروره څنګه یاست؟ د OpsFlow قیمت څومره دی؟",
            "ډېره مننه وروره، نرخ څه دی؟",
            "زه غواړم د خپل کاروبار لپاره واټس اپ راکړه پکار دی",
            "ښه ده وروره مننه، مرسته پکار ده"
        ]
        for s in samples:
            res = WhatsAppService.detect_language(s)
            self.assertEqual(res["language"], "pashto", f"Failed for: {s}")
            self.assertEqual(res["script"], "arabic", f"Failed for: {s}")
            self.assertEqual(res["format"], "pashto_arabic", f"Failed for: {s}")
            self.assertGreaterEqual(res["confidence"], 0.7)

    def test_detect_language_roman_pashto(self):
        """Verifies Roman Pashto (Latin script) is accurately detected."""
        samples = [
            "sanga ye rora OpsFlow pakar de",
            "Dera manana staso da maraste na",
            "sa hal de rora tsomra qimat de?",
            "pa kher raghle rora, kawale sham demo wagram",
            "khushala ose rora, taso sara packages shta?",
            "staso sales team na tapos kawom"
        ]
        for s in samples:
            res = WhatsAppService.detect_language(s)
            self.assertEqual(res["language"], "pashto", f"Failed for: {s}")
            self.assertEqual(res["script"], "latin", f"Failed for: {s}")
            self.assertEqual(res["format"], "roman_pashto", f"Failed for: {s}")
            self.assertGreaterEqual(res["confidence"], 0.7)

    def test_detect_language_urdu_arabic_script(self):
        """Verifies Urdu in Arabic/Nastaliq script is accurately detected."""
        samples = [
            "السلام علیکم، مجھے پیکج کی قیمت معلوم کرنی ہے",
            "آپ کا بہت بہت شکریہ، مجھے سپورٹ چاہیئے",
            "کیا حال ہے بھائی؟ کیا آپ کا سسٹم واٹس ایپ کے ساتھ کنیکٹ ہوتا ہے؟",
            "ہمیں کمپنی کے لیے آٹومیشن چاہیے، رابطہ کریں"
        ]
        for s in samples:
            res = WhatsAppService.detect_language(s)
            self.assertEqual(res["language"], "urdu", f"Failed for: {s}")
            self.assertEqual(res["script"], "arabic", f"Failed for: {s}")
            self.assertEqual(res["format"], "urdu_arabic", f"Failed for: {s}")
            self.assertGreaterEqual(res["confidence"], 0.65)

    def test_detect_language_roman_urdu(self):
        """Verifies Roman Urdu (Latin script) is accurately detected."""
        samples = [
            "kya haal hai mujhe pricing chahiye",
            "aap kaise hain madad karein",
            "kia price hai trial mil sakta hai kya?",
            "batao bhai kitna kharcha hoga monthly?",
            "shukriya mujhe package detail send karein"
        ]
        for s in samples:
            res = WhatsAppService.detect_language(s)
            self.assertEqual(res["language"], "urdu", f"Failed for: {s}")
            self.assertEqual(res["script"], "latin", f"Failed for: {s}")
            self.assertEqual(res["format"], "roman_urdu", f"Failed for: {s}")
            self.assertGreaterEqual(res["confidence"], 0.7)

    def test_detect_language_english(self):
        """Verifies English messages are accurately detected."""
        samples = [
            "Hello, what are your monthly subscription plans?",
            "Can you help me integrate WhatsApp with our CRM?",
            "Hi there, is the free trial currently available?",
            "We need an automated response workflow for our sales team."
        ]
        for s in samples:
            res = WhatsAppService.detect_language(s)
            self.assertEqual(res["language"], "english", f"Failed for: {s}")
            self.assertEqual(res["script"], "latin", f"Failed for: {s}")
            self.assertEqual(res["format"], "english", f"Failed for: {s}")

    def test_detect_language_conversation_history_continuity(self):
        """Verifies short/ambiguous messages preserve language context from conversation history."""
        # Customer was speaking Roman Pashto previously
        history = [
            {"role": "Customer", "content": "sanga ye rora da packages tsomra de"},
            {"role": "Assistant", "content": "Salam! Pa kher raghle, zamung Pro plan PKR 4,999 de."},
        ]
        # Follow-up short message
        res = WhatsAppService.detect_language("ok", conversation_history=history)
        self.assertEqual(res["format"], "roman_pashto")

        # Customer was speaking Urdu Arabic script previously
        history_urdu = [
            {"role": "Customer", "content": "مجھے پیکج کی تفصیل بتائیں"},
            {"role": "Assistant", "content": "السلام علیکم! ہمارے پاس تین پلانز ہیں۔"},
        ]
        res_urdu = WhatsAppService.detect_language("شکریہ", conversation_history=history_urdu)
        self.assertEqual(res_urdu["format"], "urdu_arabic")

    # -------------------------------------------------------------
    # 2. AI Prompt Directive Construction Tests
    # -------------------------------------------------------------

    def test_get_language_prompt_directive(self):
        """Verifies language directives provide unequivocal instructions for Gemini/Groq."""
        pashto_ar_dir = WhatsAppService.get_language_prompt_directive(
            {"format": "pashto_arabic"}, "څنګه یاست"
        )
        self.assertIn("STRICT PASHTO ARABIC SCRIPT", pashto_ar_dir)
        self.assertIn("پښتو", pashto_ar_dir)

        roman_pashto_dir = WhatsAppService.get_language_prompt_directive(
            {"format": "roman_pashto"}, "sanga ye rora"
        )
        self.assertIn("STRICT ROMAN PASHTO", roman_pashto_dir)
        self.assertIn("Latin script Pashto", roman_pashto_dir)

        urdu_ar_dir = WhatsAppService.get_language_prompt_directive(
            {"format": "urdu_arabic"}, "آپ کیسے ہیں"
        )
        self.assertIn("STRICT URDU ARABIC/NASTALIQ SCRIPT", urdu_ar_dir)
        self.assertIn("اردو", urdu_ar_dir)

        roman_urdu_dir = WhatsAppService.get_language_prompt_directive(
            {"format": "roman_urdu"}, "aap kaise hain"
        )
        self.assertIn("STRICT ROMAN URDU", roman_urdu_dir)

        en_dir = WhatsAppService.get_language_prompt_directive(
            {"format": "english"}, "Hello there"
        )
        self.assertIn("ENGLISH", en_dir)

    # -------------------------------------------------------------
    # 3. Model Prompt Integration Tests (Gemini & Groq)
    # -------------------------------------------------------------

    @patch("whatsapp_service.requests.post")
    def test_call_gemini_ai_injects_language_directive(self, mock_post):
        """Verifies call_gemini_ai embeds the appropriate language requirement in the model prompt."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "سلام! د OpsFlow Cloud بیه هره میاشت مناسبه ده."}]
                }
            }]
        }
        mock_post.return_value = mock_resp

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_gemini_key"):
            reply = WhatsAppService.call_gemini_ai(
                "سلام وروره، د OpsFlow Cloud بیه څومره ده؟",
                organization_id=self.org.id
            )
            self.assertIsNotNone(reply)
            self.assertIn("OpsFlow", reply)

            # Check that prompt sent to Gemini REST contains strict Pashto directive
            self.assertTrue(mock_post.called)
            sent_payload = mock_post.call_args[1]["json"]
            sent_text = sent_payload["contents"][0]["parts"][0]["text"]
            self.assertIn("STRICT PASHTO ARABIC SCRIPT", sent_text)
            self.assertIn("پښتو", sent_text)

    @patch("whatsapp_service.requests.post")
    def test_call_groq_ai_injects_language_directive(self, mock_post):
        """Verifies call_groq_ai embeds the appropriate language requirement in Groq's user prompt."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": "Salam! Sanga ye? OpsFlow Cloud pakar de no zamaung team ba madad waki."}
            }]
        }
        mock_post.return_value = mock_resp

        with patch.object(WhatsAppService, "get_groq_api_key", return_value="fake_groq_key"):
            reply = WhatsAppService.call_groq_ai(
                "sanga ye rora OpsFlow pakar de",
                organization_id=self.org.id
            )
            self.assertIsNotNone(reply)

            # Check that prompt sent to Groq contains strict Roman Pashto directive
            self.assertTrue(mock_post.called)
            sent_payload = mock_post.call_args[1]["json"]
            user_msg = [m for m in sent_payload["messages"] if m["role"] == "user"][0]["content"]
            self.assertIn("STRICT ROMAN PASHTO", user_msg)

    # -------------------------------------------------------------
    # 4. Fallback Auto-Response Generation (Offline AI Fallback)
    # -------------------------------------------------------------

    def test_fallback_auto_response_pashto_arabic(self):
        """Verifies offline fallback generates natural Pashto in Arabic script for Pashto inquiries."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="سلام وروره، د قیمت په اړه معلومات راکړئ"
                )
                self.assertEqual(res["detected_language"], "pashto")
                self.assertEqual(res["detected_script"], "arabic")
                self.assertEqual(res["language_format"], "pashto_arabic")
                # Must contain authentic Pashto text
                self.assertIn("مننه", res["reply_body"])
                self.assertIn("OpsFlow Cloud", res["reply_body"])
                # Must NOT contain English boilerplate
                self.assertNotIn("A solutions specialist", res["reply_body"])

    def test_fallback_auto_response_roman_pashto(self):
        """Verifies offline fallback generates natural Roman Pashto for Roman Pashto inquiries."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="sanga ye rora OpsFlow pakar de tsomra qimat de"
                )
                self.assertEqual(res["detected_language"], "pashto")
                self.assertEqual(res["detected_script"], "latin")
                self.assertEqual(res["language_format"], "roman_pashto")
                # Must contain authentic Roman Pashto text
                self.assertIn("manana", res["reply_body"].lower())
                self.assertIn("OpsFlow Cloud", res["reply_body"])
                self.assertNotIn("solutions specialist", res["reply_body"])

    def test_fallback_auto_response_urdu_arabic(self):
        """Verifies offline fallback generates natural Urdu in Arabic script for Urdu inquiries."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="السلام علیکم، کیا مجھے پیکیجز کی تفصیل مل سکتی ہے؟"
                )
                self.assertEqual(res["detected_language"], "urdu")
                self.assertEqual(res["detected_script"], "arabic")
                self.assertEqual(res["language_format"], "urdu_arabic")
                self.assertIn("شکریہ", res["reply_body"])
                self.assertIn("OpsFlow Cloud", res["reply_body"])

    def test_fallback_auto_response_roman_urdu(self):
        """Verifies offline fallback generates natural Roman Urdu for Roman Urdu inquiries."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="kya haal hai mujhe pricing chahiye"
                )
                self.assertEqual(res["detected_language"], "urdu")
                self.assertEqual(res["detected_script"], "latin")
                self.assertEqual(res["language_format"], "roman_urdu")
                self.assertIn("Shukriya", res["reply_body"])
                self.assertIn("OpsFlow Cloud", res["reply_body"])

    def test_fallback_auto_response_english(self):
        """Verifies offline fallback generates professional English for English inquiries."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Can you provide pricing details for WhatsApp integration?"
                )
                self.assertEqual(res["detected_language"], "english")
                self.assertEqual(res["detected_script"], "latin")
                self.assertEqual(res["language_format"], "english")
                self.assertIn("specialist", res["reply_body"].lower())

    # -------------------------------------------------------------
    # 5. Media Receipt Language Matching
    # -------------------------------------------------------------

    def test_media_receipt_language_matched(self):
        """Verifies image and document receipt responses are language-matched based on conversation context."""
        # Pashto Arabic script context
        history_pashto = [
            {"role": "Customer", "content": "سلام وروره، دا بل ما درلیږلی دی"}
        ]
        with patch.object(WhatsAppService, "get_conversation_history", return_value=history_pashto):
            res = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="[Image]",
                sender_phone="923001234567"
            )
            self.assertEqual(res["language_format"], "pashto_arabic")
            self.assertIn("انځور", res["reply_body"])

        # Roman Pashto context
        history_roman_pashto = [
            {"role": "Customer", "content": "sanga ye rora da screenshot gora"}
        ]
        with patch.object(WhatsAppService, "get_conversation_history", return_value=history_roman_pashto):
            res_rp = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="[Image]",
                sender_phone="923001234568"
            )
            self.assertEqual(res_rp["language_format"], "roman_pashto")
            self.assertIn("manana", res_rp["reply_body"].lower())
