"""Focused test suite for WhatsApp Gemini/Groq AI Auto-Replies and 429 Fallback.

Verifies:
1. Auto-responder triggers when only GROQ_API_KEY is configured (Gemini absent) without premature suppression.
2. get_groq_api_key cleanly strips single and double quotes from env or config.
3. Secondary Groq AI fallback in app.py's get_gemini_ai_response when Gemini fails.
4. Duplicate webhook delivery suppression (in-memory + DB deduplication).
5. System canned fallback is never labeled as genuine AI (is_ai_generated: False, response_source: 'system_fallback').
6. Multi-turn conversation history is retrieved and injected into AI prompts.
7. Gemini HTTP 429 (RESOURCE_EXHAUSTED) immediately falls back to Groq LPU inference.
8. GeminiAIProvider in ai_provider.py falls back to Groq when Gemini fails or key missing.
9. WhatsAppService.save_auto_responder_config properly persists Groq API key and model.
10. API endpoint POST /api/v1/whatsapp/auto-responder accepts and persists groq_api_key and groq_model.
"""

from __future__ import annotations

import datetime
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app, get_gemini_ai_response
from database import db
from models import Organization, User, Membership, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestWhatsAppGeminiGroqAI(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {
            "GREEN_API_ID_INSTANCE": "",
            "GREEN_API_TOKEN_INSTANCE": "",
            "WHATSAPP_SIMULATOR_FALLBACK": "true"
        })
        self.env_patcher.start()

        self.app = create_app("testing")
        self.app.config["RATELIMIT_ENABLED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(
            id="org-pk-test",
            name="Pak Cloud Automations",
            slug="pak-cloud",
            plan_tier="enterprise",
            is_active=True
        )
        db.session.add(self.org)

        self.user = User(
            id="usr-pk-tester",
            email="tester@pakcloud.pk",
            full_name="Tester Khan",
            is_active=True
        )
        self.user.set_password("CloudSecret2026!")
        db.session.add(self.user)

        self.member = Membership(
            id="mem-pk-1",
            organization_id=self.org.id,
            user_id=self.user.id,
            role="owner"
        )
        db.session.add(self.member)
        db.session.commit()

        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "tester@pakcloud.pk",
            "password": "CloudSecret2026!"
        })
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.env_patcher.stop()

    def test_groq_auto_response_triggers_when_only_groq_key_present(self):
        """Verifies auto-response is NOT prematurely suppressed when Gemini is absent but Groq is present."""
        sender_phone = "923007778899"
        groq_reply = "Welcome to OpsFlow Cloud! I am your AI assistant powered by Groq LPU."

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=False,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value=None):
            with patch.object(WhatsAppService, "get_groq_api_key", return_value="gsk_mock_valid_key"):
                with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
                    with patch.object(WhatsAppService, "call_groq_ai", return_value=groq_reply):
                        res = WhatsAppService.handle_inbound_auto_response(
                            organization_id=self.org.id,
                            sender_phone=sender_phone,
                            message_body="Hello, I want to know about your platform.",
                            sender_name="Bilal",
                            message_id="wamid.groq_trigger_01"
                        )

                        self.assertIsNotNone(res)
                        self.assertTrue(res["success"])
                        self.assertEqual(res["reply_body"], groq_reply)

    def test_get_groq_api_key_strips_quotes(self):
        """Verifies get_groq_api_key cleanly strips single and double quotes from env or config."""
        with patch.dict(os.environ, {"GROQ_API_KEY": '"gsk_quoted_key_123"'}):
            key = WhatsAppService.get_groq_api_key()
            self.assertEqual(key, "gsk_quoted_key_123")

        with patch.dict(os.environ, {"GROQ_API_KEY": "'gsk_single_quoted_456'"}):
            key = WhatsAppService.get_groq_api_key()
            self.assertEqual(key, "gsk_single_quoted_456")

    def test_app_get_gemini_ai_response_falls_back_to_groq(self):
        """Verifies get_gemini_ai_response in app.py falls back to Groq AI when Gemini fails."""
        groq_resp = "This response was generated by Groq secondary AI fallback."
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=groq_resp):
                reply = get_gemini_ai_response("Test query for fallback")
                self.assertEqual(reply, groq_resp)

    def test_duplicate_webhook_reply_suppression(self):
        """Verifies duplicate webhook deliveries for the same message ID do not produce duplicate auto-replies."""
        sender_phone = "923004443322"
        wamid = "wamid.dup_webhook_01"

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value="First AI reply to customer"):
            res1 = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=sender_phone,
                message_body="Can I get pricing for Pro?",
                sender_name="Tariq",
                message_id=wamid
            )
            self.assertIsNotNone(res1)
            self.assertTrue(res1["success"])
            self.assertFalse(res1.get("duplicate", False))

            res2 = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=sender_phone,
                message_body="Can I get pricing for Pro?",
                sender_name="Tariq",
                message_id=wamid
            )
            self.assertIsNotNone(res2)
            self.assertTrue(res2.get("duplicate", False))

            outbound_count = WhatsAppMessage.query.filter(
                WhatsAppMessage.organization_id == self.org.id,
                WhatsAppMessage.direction == "outbound"
            ).count()
            self.assertEqual(outbound_count, 1)

    def test_canned_fallback_never_labeled_as_ai(self):
        """Verifies system canned fallback is never labeled as an AI-generated reply."""
        sender_phone = "923008889900"
        wamid = "wamid.canned_test_01"

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id=self.org.id,
                    sender_phone=sender_phone,
                    message_body="Can you help me with something?",
                    sender_name="Zahid",
                    message_id=wamid
                )
                self.assertIsNotNone(res)
                self.assertTrue(res["success"])

                out_msg = WhatsAppMessage.query.filter(
                    WhatsAppMessage.organization_id == self.org.id,
                    WhatsAppMessage.direction == "outbound",
                    WhatsAppMessage.recipient == sender_phone
                ).first()
                self.assertIsNotNone(out_msg)
                payload = json.loads(out_msg.raw_payload_json)
                self.assertFalse(payload.get("is_ai_generated"))
                self.assertFalse(payload.get("is_gemini_response"))
                self.assertFalse(payload.get("is_groq_response"))
                self.assertEqual(payload.get("response_source"), "system_fallback")

    def test_conversation_history_retrieved_and_injected(self):
        """Verifies multi-turn conversation history is retrieved and passed to AI providers."""
        customer_phone = "923001239876"

        msg1 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=customer_phone,
            recipient="system",
            direction="inbound",
            body="Do you support Stripe?",
            status="received",
            whatsapp_message_id="wamid.hist_01"
        )
        msg1.created_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=10)
        msg2 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender="system",
            recipient=customer_phone,
            direction="outbound",
            body="Yes, we support Stripe and JazzCash.",
            status="sent",
            whatsapp_message_id="wamid.hist_02"
        )
        msg2.created_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=5)
        db.session.commit()

        history = WhatsAppService.get_conversation_history(customer_phone, organization_id=self.org.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "Customer")
        self.assertEqual(history[0]["content"], "Do you support Stripe?")
        self.assertEqual(history[1]["role"], "Assistant")
        self.assertEqual(history[1]["content"], "Yes, we support Stripe and JazzCash.")

        with patch.object(WhatsAppService, "call_gemini_ai") as mock_gemini:
            mock_gemini.return_value = "Yes, JazzCash PKR is available on Starter."
            WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="Can I pay with JazzCash in Pakistan?",
                sender_name="Customer",
                sender_phone=customer_phone
            )
            mock_gemini.assert_called_once()
            called_kwargs = mock_gemini.call_args[1]
            self.assertIn("conversation_history", called_kwargs)
            self.assertEqual(len(called_kwargs["conversation_history"]), 2)

    def test_gemini_429_falls_back_to_groq(self):
        """Verifies that when Gemini returns HTTP 429 (quota exceeded), system immediately falls back to Groq."""
        sender_phone = "923001230011"
        groq_expected = "Groq LPU response after Gemini 429 quota exhaustion."

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        mock_429_resp = MagicMock()
        mock_429_resp.status_code = 429
        mock_429_resp.text = '{"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}'

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="AIzaMockGeminiKey"):
            with patch("requests.post", return_value=mock_429_resp):
                with patch.object(WhatsAppService, "call_groq_ai", return_value=groq_expected) as mock_groq:
                    res = WhatsAppService.generate_ai_auto_response(
                        organization_id=self.org.id,
                        message_body="Can you explain your enterprise SLA?",
                        sender_name="Danyal",
                        sender_phone=sender_phone
                    )
                    self.assertIsNotNone(res)
                    self.assertEqual(res["reply_body"], groq_expected)
                    self.assertTrue(res["is_groq"])
                    self.assertFalse(res["is_gemini"])
                    self.assertTrue(res["is_ai_generated"])
                    self.assertEqual(res["mode"], "groq_ai")
                    mock_groq.assert_called_once()

    def test_gemini_ai_provider_groq_fallback(self):
        """Verifies GeminiAIProvider falls back to Groq when Gemini fails or has no key."""
        from ai_provider import GeminiAIProvider, GroqAIProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "gsk_valid_key"}):
            gemini_prov = GeminiAIProvider()
            with patch.object(GroqAIProvider, "generate_draft_response", return_value="Groq draft reply"):
                draft = gemini_prov.generate_draft_response(
                    name="Usman",
                    company="Tech Corp",
                    intent="lead_inquiry",
                    message="Interested in cloud"
                )
                self.assertEqual(draft, "Groq draft reply")

            with patch.object(GroqAIProvider, "generate_text", return_value="Groq generated text"):
                text = gemini_prov.generate_text("Explain auto-healing")
                self.assertEqual(text, "Groq generated text")

    def test_save_auto_responder_config_persists_groq_settings(self):
        """Verifies save_auto_responder_config properly persists and returns Groq API key and model."""
        saved = WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            groq_api_key="gsk_new_test_key_789",
            groq_model="llama-3.1-8b-instant"
        )
        self.assertTrue(saved["groq_api_key_configured"])
        self.assertEqual(saved["groq_model"], "llama-3.1-8b-instant")

        retrieved_key = WhatsAppService.get_groq_api_key(organization_id=self.org.id)
        self.assertEqual(retrieved_key, "gsk_new_test_key_789")

    def test_api_endpoint_persists_groq_settings(self):
        """Verifies POST /api/v1/whatsapp/auto-responder endpoint accepts and persists groq settings."""
        resp = self.client.post("/api/v1/whatsapp/auto-responder", json={
            "enabled": True,
            "groq_api_key": "gsk_api_endpoint_test_key",
            "groq_model": "llama-3.3-70b-versatile"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["config"]["groq_api_key_configured"])
        self.assertEqual(data["config"]["groq_model"], "llama-3.3-70b-versatile")

        retrieved = WhatsAppService.get_groq_api_key(organization_id=self.org.id)
        self.assertEqual(retrieved, "gsk_api_endpoint_test_key")


if __name__ == "__main__":
    unittest.main()
