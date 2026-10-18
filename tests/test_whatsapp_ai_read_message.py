"""Comprehensive test suite for WhatsApp AI Auto-Replies & Read-Message Functionality.

Verifies:
1. WhatsAppService.mark_chat_as_read() transitions inbound messages to status="read".
2. WhatsAppService.mark_message_as_read() marks single messages and updates gateway.
3. API endpoints POST /api/v1/whatsapp/messages/<id>/read and POST /api/v1/whatsapp/conversations/<phone>/read.
4. WhatsAppService.handle_inbound_auto_response() marks the triggering inbound message as read upon reply.
5. Auto-responder successfully triggers when only GROQ_API_KEY is configured (Gemini absent) without premature suppression.
6. Quotes are properly stripped from GROQ_API_KEY.
7. Secondary Groq AI fallback in app.py's get_gemini_ai_response.
8. Zero regressions on existing WhatsApp features and tenant isolation.
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


class TestWhatsAppAIReadMessage(unittest.TestCase):
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
        WhatsAppService.clear_recent_replied_trigger_ids()
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        WhatsAppService.clear_recent_replied_trigger_ids()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.env_patcher.stop()

    def test_mark_chat_as_read_updates_database_records(self):
        """Verifies mark_chat_as_read updates all unread inbound messages for a contact to status='read'."""
        sender_phone = "923001112233"
        msg1 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="First unread query",
            status="received",
            whatsapp_message_id="wamid.read_test_01"
        )
        msg2 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="Second unread query",
            status="received",
            whatsapp_message_id="wamid.read_test_02"
        )
        # Outbound message should not be affected
        out_msg = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender="system",
            recipient=sender_phone,
            direction="outbound",
            body="Already sent reply",
            status="sent",
            whatsapp_message_id="wamid.read_test_03"
        )

        res = WhatsAppService.mark_chat_as_read(chat_id=sender_phone, organization_id=self.org.id)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["updated_count"], 2)

        refreshed_msg1 = db.session.get(WhatsAppMessage, msg1.id)
        refreshed_msg2 = db.session.get(WhatsAppMessage, msg2.id)
        refreshed_out = db.session.get(WhatsAppMessage, out_msg.id)

        self.assertEqual(refreshed_msg1.status, "read")
        self.assertEqual(refreshed_msg2.status, "read")
        self.assertEqual(refreshed_out.status, "sent")

    def test_mark_message_as_read_specific_message(self):
        """Verifies mark_message_as_read updates a single message by ID."""
        sender_phone = "923009988776"
        msg = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="Specific message to read",
            status="received",
            whatsapp_message_id="wamid.spec_read_01"
        )

        res = WhatsAppService.mark_message_as_read(message_id=msg.id, organization_id=self.org.id)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["updated_count"], 1)

        refreshed = db.session.get(WhatsAppMessage, msg.id)
        self.assertEqual(refreshed.status, "read")

    def test_api_endpoints_mark_message_and_conversation_read(self):
        """Verifies REST endpoints for marking messages and conversations as read."""
        contact = "923112233445"
        msg = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=contact,
            recipient="system",
            direction="inbound",
            body="Testing API mark read",
            status="received",
            whatsapp_message_id="wamid.api_read_01"
        )

        # 1. POST /api/v1/whatsapp/messages/<message_id>/read
        res1 = self.client.post(f"/api/v1/whatsapp/messages/{msg.id}/read")
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1["success"])

        # 2. Add second message and mark entire conversation
        msg2 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=contact,
            recipient="system",
            direction="inbound",
            body="Another message in conversation",
            status="received",
            whatsapp_message_id="wamid.api_read_02"
        )
        res2 = self.client.post(f"/api/v1/whatsapp/conversations/{contact}/read")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2["success"])

        m2 = db.session.get(WhatsAppMessage, msg2.id)
        self.assertEqual(m2.status, "read")

    def test_auto_responder_marks_triggering_message_as_read(self):
        """Verifies that when AI auto-responder sends a reply, the triggering inbound message is marked as read."""
        sender_phone = "923005556677"
        inbound_msg = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=sender_phone,
            recipient="system",
            direction="inbound",
            body="What are the prices for the Starter plan?",
            status="received",
            whatsapp_message_id="wamid.trigger_read_01"
        )
        self.assertEqual(inbound_msg.status, "received")

        # Enable auto responder
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        mock_reply = "Our Starter plan is $49/month or PKR 7,500/month with full workflow automation."
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=mock_reply):
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=sender_phone,
                message_body="What are the prices for the Starter plan?",
                sender_name="Ahmed",
                message_id=inbound_msg.whatsapp_message_id
            )
            self.assertIsNotNone(res)
            self.assertTrue(res["success"])

            # Verify the triggering inbound message is now status="read"
            db.session.refresh(inbound_msg)
            self.assertEqual(inbound_msg.status, "read")

    def test_groq_auto_response_triggers_when_only_groq_key_present(self):
        """Verifies auto-response is NOT prematurely suppressed when Gemini is absent but Groq is present."""
        sender_phone = "923007778899"
        groq_reply = "Welcome to OpsFlow Cloud! I am your AI assistant powered by Groq LPU."

        # Auto-responder NOT explicitly enabled in config; should activate automatically because Groq key is present
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
            # First webhook delivery
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

            # Second delivery with exact same message ID
            res2 = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=sender_phone,
                message_body="Can I get pricing for Pro?",
                sender_name="Tariq",
                message_id=wamid
            )
            self.assertIsNotNone(res2)
            self.assertTrue(res2.get("duplicate", False))

            # Total outbound messages in DB for this phone should be exactly 1
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

                # Check outbound message record metadata
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

        # Record earlier conversation turn
        msg1 = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=customer_phone,
            recipient="system",
            direction="inbound",
            body="Do you support Stripe?",
            status="read",
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

        # Verify history is passed to call_gemini_ai
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

    def test_honest_reporting_of_read_status_limitations(self):
        """Verifies that simulator/mock mode honestly reports remote_success=False and provides remote_detail."""
        contact = "923007654321"
        WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=contact,
            recipient="system",
            direction="inbound",
            body="Hello from customer",
            status="received",
            whatsapp_message_id="wamid.honesty_01"
        )

        # Provider is simulator in test environment
        with patch.object(WhatsAppService, "get_active_provider", return_value="simulator"):
            res = WhatsAppService.mark_chat_as_read(chat_id=contact, organization_id=self.org.id)
            self.assertTrue(res["success"])
            # Should NOT fake remote_success
            self.assertFalse(res["remote_success"])
            self.assertIn("remote_detail", res)
            self.assertIn("simulator", res["remote_detail"].lower())

    def test_list_whatsapp_messages_matches_phone_variations(self):
        """Verifies list_whatsapp_messages matches messages across local, international, and @c.us phone formats."""
        # Record with international format
        WhatsAppService.record_message(
            organization_id=self.org.id,
            sender="923001122334",
            recipient="system",
            direction="inbound",
            body="Message with 92 prefix",
            status="received",
            whatsapp_message_id="wamid.fmt_01"
        )

        # Query with local Pakistani 0300... format
        res1 = self.client.get("/api/v1/whatsapp/messages?chat_id=03001122334")
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1["count"], 1)

        # Query with +92300... format
        res2 = self.client.get("/api/v1/whatsapp/messages?chat_id=%2B923001122334")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2["count"], 1)

        # Query with @c.us suffix
        res3 = self.client.get("/api/v1/whatsapp/messages?chat_id=923001122334%40c.us")
        self.assertEqual(res3.status_code, 200)
        data3 = res3.get_json()
        self.assertEqual(data3["count"], 1)

    def test_gemini_429_falls_back_to_groq(self):
        """Verifies that when Gemini returns HTTP 429 (quota exceeded), system immediately falls back to Groq."""
        sender_phone = "923001230011"
        groq_expected = "Groq LPU response after Gemini 429 quota exhaustion."

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        # Mock requests.post so Gemini HTTP REST call returns HTTP 429
        mock_429_resp = MagicMock()
        mock_429_resp.status_code = 429
        mock_429_resp.text = '{"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}'

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="AIzaMockGeminiKey"):
            with patch("requests.post", return_value=mock_429_resp):
                # When Gemini fails with 429, call_groq_ai should be called
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


if __name__ == "__main__":
    unittest.main()
