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
        WhatsAppService.clear_recent_replied_trigger_ids()
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        WhatsAppService.clear_recent_replied_trigger_ids()
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

    def test_automation_rule_reply_prevents_duplicate_auto_response(self):
        """Verifies that an automation rule WhatsApp reply prevents duplicate auto-reply."""
        engine_res_with_wa = {
            "status": "completed",
            "event_name": "whatsapp.message",
            "executed_rules": [
                {
                    "rule_id": "rule-auto-reply-01",
                    "rule_name": "Welcome Lead WhatsApp",
                    "matched": True,
                    "status": "success",
                    "action_results": [
                        {
                            "type": "whatsapp_message",
                            "status": "success",
                            "output": {"idMessage": "wamid.rule_sent_01"}
                        }
                    ]
                }
            ]
        }
        self.assertTrue(WhatsAppService.engine_dispatched_reply(engine_res_with_wa))

        # When passed to handle_inbound_auto_response, it skips
        res = WhatsAppService.handle_inbound_auto_response(
            organization_id=self.org.id,
            sender_phone="923001112233",
            message_body="Pricing please",
            message_id="wamid.rule_check_01",
            engine_res=engine_res_with_wa
        )
        self.assertIsNotNone(res)
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "rule_replied")

    def test_automation_rule_without_whatsapp_allows_auto_response(self):
        """Verifies that non-WhatsApp rule actions do not prevent AI auto-reply."""
        engine_res_non_wa = {
            "status": "completed",
            "event_name": "whatsapp.message",
            "executed_rules": [
                {
                    "rule_id": "rule-log-only",
                    "rule_name": "Audit Logging",
                    "matched": True,
                    "status": "success",
                    "action_results": [
                        {
                            "type": "log_entry",
                            "status": "success",
                            "output": {"logged": True}
                        }
                    ]
                }
            ]
        }
        self.assertFalse(WhatsAppService.engine_dispatched_reply(engine_res_non_wa))

    def test_green_api_webhook_skips_auto_responder_when_rule_already_replied(self):
        """Verifies that Green-API webhook skips handle_inbound_auto_response when engine dispatched a reply."""
        engine_mock = MagicMock()
        engine_mock.ingest_event.return_value = {
            "status": "completed",
            "event_name": "whatsapp.message",
            "executed_rules": [
                {
                    "rule_id": "rule-wa-01",
                    "status": "success",
                    "action_results": [
                        {
                            "type": "whatsapp_message",
                            "status": "success",
                            "output": {"sent": True}
                        }
                    ]
                }
            ]
        }

        webhook_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {"idInstance": 7103, "wid": "923001234567@c.us"},
            "timestamp": 1713000000,
            "idMessage": "wamid.green_rule_guard_01",
            "senderData": {
                "chatId": "923009998877@c.us",
                "chatName": "Zain",
                "sender": "923009998877@c.us",
                "senderName": "Zain"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {"textMessage": "I need help with my account."}
            }
        }

        with patch("api_v1.get_engine", return_value=engine_mock):
            with patch.object(WhatsAppService, "handle_inbound_auto_response") as mock_auto:
                resp = self.client.post("/api/v1/webhooks/whatsapp/green-api", json=webhook_payload)
                self.assertEqual(resp.status_code, 200)
                mock_auto.assert_not_called()

    def test_both_gemini_and_groq_fail_returns_canned_fallback_with_honest_badges(self):
        """Verifies that when both Gemini and Groq fail, honest non-AI system fallback metadata is returned."""
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Can you help me reset my server configuration?",
                    sender_name="Ali",
                    sender_phone="923005556677"
                )
                self.assertIsNotNone(res)
                self.assertFalse(res["is_gemini"])
                self.assertFalse(res["is_groq"])
                self.assertFalse(res["is_ai_generated"])
                self.assertTrue(
                    "Ji bilkul" in res["reply_body"]
                    or "specialist" in res["reply_body"]
                    or "incident" in res["reply_body"]
                )

    def test_get_groq_api_key_case_and_whitespace_tolerant(self):
        """Verifies get_groq_api_key resolves key even with lowercase or surrounding whitespace in env."""
        with patch.dict(os.environ, {"groq_api_key": "gsk_lower_case_123"}, clear=False):
            key = WhatsAppService.get_groq_api_key()
            self.assertEqual(key, "gsk_lower_case_123")

        with patch.dict(os.environ, {"GROQ_API_KEY ": "gsk_trailing_space_456"}, clear=False):
            key = WhatsAppService.get_groq_api_key()
            self.assertEqual(key, "gsk_trailing_space_456")

    def test_get_groq_api_key_from_render_secret_file(self):
        """Verifies get_groq_api_key reads from Render secret file mounted at /etc/secrets/GROQ_API_KEY."""
        orig_exists = os.path.exists
        orig_isfile = os.path.isfile

        def fake_exists(p):
            p_norm = os.path.normpath(str(p)).replace("\\", "/")
            if "etc/secrets" in p_norm:
                return True
            return orig_exists(p)

        def fake_isfile(p):
            p_norm = os.path.normpath(str(p)).replace("\\", "/")
            if "etc/secrets/GROQ_API_KEY" in p_norm or "etc/secrets/groq_api_key" in p_norm:
                return True
            return orig_isfile(p)

        with patch("whatsapp_service.os.path.exists", side_effect=fake_exists):
            with patch("whatsapp_service.os.path.isfile", side_effect=fake_isfile):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__.return_value.read.return_value = "gsk_render_secret_mount_789"
                    with patch.dict(os.environ, {"GROQ_API_KEY": "", "GROQ_KEY": ""}):
                        with patch.object(WhatsAppService, "_get_tenant_or_global_setting", return_value=None):
                            key = WhatsAppService.get_groq_api_key()
                            self.assertEqual(key, "gsk_render_secret_mount_789")

    def test_end_to_end_groq_http_dispatch_on_gemini_429(self):
        """Verifies full end-to-end HTTP request reaches https://api.groq.com/openai/v1/chat/completions when Gemini returns 429."""
        groq_json_response = {
            "choices": [
                {
                    "message": {
                        "content": "Live Groq LPU answer delivered via HTTP REST completions endpoint."
                    }
                }
            ]
        }

        mock_gemini_429 = MagicMock()
        mock_gemini_429.status_code = 429
        mock_gemini_429.text = '{"error": {"code": 429, "message": "Resource has been exhausted."}}'

        mock_groq_200 = MagicMock()
        mock_groq_200.status_code = 200
        mock_groq_200.json.return_value = groq_json_response

        def mock_post(url, *args, **kwargs):
            if "generativelanguage" in url:
                return mock_gemini_429
            elif "api.groq.com" in url:
                return mock_groq_200
            return MagicMock(status_code=404)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaMock429", "GROQ_API_KEY": "gsk_valid_live_key"}):
            with patch("requests.post", side_effect=mock_post) as mock_req:
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Tell me about automated recovery",
                    sender_name="Hamza",
                    sender_phone="923009988776"
                )
                self.assertIsNotNone(res)
                self.assertTrue(res["is_groq"])
                self.assertFalse(res["is_gemini"])
                self.assertEqual(res["reply_body"], "Live Groq LPU answer delivered via HTTP REST completions endpoint.")

                # Verify actual HTTP call to Groq endpoint was executed
                groq_calls = [c for c in mock_req.call_args_list if "api.groq.com" in str(c)]
                self.assertGreaterEqual(len(groq_calls), 1)
                groq_call = groq_calls[0]
                self.assertIn("https://api.groq.com/openai/v1/chat/completions", groq_call[0])
                headers = groq_call[1].get("headers", {})
                self.assertEqual(headers.get("Authorization"), "Bearer gsk_valid_live_key")

    def test_groq_diagnostics_and_last_error_recorded(self):
        """Verifies Groq failure records _last_groq_error and diagnostics."""
        mock_fail = MagicMock()
        mock_fail.status_code = 503
        mock_fail.text = "Service Unavailable"

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_key"}):
            with patch("requests.post", return_value=mock_fail):
                res = WhatsAppService.call_groq_ai("test message")
                self.assertIsNone(res)
                last_err = WhatsAppService.get_last_groq_error()
                self.assertIsNotNone(last_err)
                self.assertIn("503", last_err)
                diags = WhatsAppService.get_last_groq_diagnostics()
                self.assertGreater(len(diags), 0)


    def test_in_flight_concurrent_debouncing(self):
        """Verifies that when an AI response is actively in-flight for a customer, concurrent triggers are debounced."""
        sender_phone = "923007770001"
        clean_phone = WhatsAppService.format_phone_number(sender_phone)
        WhatsAppService.clear_in_flight_phones()

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with WhatsAppService._in_flight_phones_lock:
            WhatsAppService._in_flight_phones.add(clean_phone)

        try:
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=sender_phone,
                message_body="Rapid second message",
                sender_name="Fast Sender"
            )
            self.assertIsNotNone(res)
            self.assertTrue(res.get("skipped"))
            self.assertEqual(res.get("reason"), "in_flight_debounce")
        finally:
            WhatsAppService.clear_in_flight_phones()

    def test_self_reply_loop_prevention(self):
        """Verifies messages originating from our own instance WID/phone are safely ignored to avoid loops."""
        own_wid = "923209350858"
        with patch.object(WhatsAppService, "get_config", return_value={"green_api_wid": f"{own_wid}@c.us"}):
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=own_wid,
                message_body="Echo message from ourselves",
                sender_name="Self"
            )
            self.assertIsNone(res)

    def test_broadcast_and_status_ignored(self):
        """Verifies status stories, broadcasts, and newsletter messages are safely ignored."""
        for invalid_sender in ["status@broadcast", "12036300112233@g.us", "newsletter@newsletter"]:
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone=invalid_sender,
                message_body="Status or broadcast update",
                sender_name="Broadcast"
            )
            self.assertIsNone(res)

    def test_media_message_graceful_handling(self):
        """Verifies image, document, voice, and sticker messages receive courteous responses without calling LLMs."""
        with patch.object(WhatsAppService, "call_gemini_ai") as mock_gemini:
            with patch.object(WhatsAppService, "call_groq_ai") as mock_groq:
                # 1. Image message
                res_img = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="[Image message]",
                    sender_name="Customer",
                    sender_phone="923001234567"
                )
                self.assertIsNotNone(res_img)
                self.assertEqual(res_img["mode"], "media_handler")
                self.assertIn("image receive", res_img["reply_body"].lower())

                # 2. Document message
                res_doc = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="[Document: invoice.pdf]",
                    sender_name="Customer",
                    sender_phone="923001234567"
                )
                self.assertIsNotNone(res_doc)
                self.assertEqual(res_doc["mode"], "media_handler")
                self.assertIn("document", res_doc["reply_body"].lower())

                # 3. Voice note
                res_voice = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="[voiceMessage]",
                    sender_name="Customer",
                    sender_phone="923001234567"
                )
                self.assertIsNotNone(res_voice)
                self.assertEqual(res_voice["mode"], "media_handler")
                self.assertIn("voice note", res_voice["reply_body"].lower())

                mock_gemini.assert_not_called()
                mock_groq.assert_not_called()

    def test_multilingual_roman_urdu_fallback(self):
        """Verifies Roman Urdu fallback matching when both LLMs are offline."""
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                res = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Ap ki pricing aur service kya hai?",
                    sender_name="Customer",
                    sender_phone="923001234567"
                )
                self.assertIsNotNone(res)
                self.assertIn("Shukriya", res["reply_body"])

    def test_verified_business_knowledge_base_grounding(self):
        """Verifies that get_verified_business_knowledge_base derives facts directly from codebase configuration."""
        kb = WhatsAppService.get_verified_business_knowledge_base(self.org.id)
        # Pricing facts
        self.assertIn("$29/mo", kb)
        self.assertIn("PKR 7,500/mo", kb)
        self.assertIn("$99/mo", kb)
        self.assertIn("PKR 25,000/mo", kb)
        self.assertIn("$499/mo", kb)
        self.assertIn("PKR 125,000/mo", kb)
        # Trial facts
        self.assertIn("2-Day Free Trial", kb)
        self.assertIn("48 hours", kb)
        # Payment gateways
        self.assertIn("Stripe", kb)
        self.assertIn("JazzCash", kb)
        # Integrations
        self.assertIn("Slack", kb)
        self.assertIn("Webhooks", kb)
        # Anti-hallucination guardrails
        self.assertIn("DO NOT invent numbers", kb)
        self.assertIn("requires confirmation", kb)

    def test_call_groq_ai_prompt_contains_verified_facts_and_guardrails(self):
        """Verifies that call_groq_ai injects verified knowledge base and grounding into the system prompt."""
        captured_messages = []

        def mock_post(url, headers=None, json=None, timeout=None):
            if "chat/completions" in url:
                captured_messages.extend(json.get("messages", []))
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "choices": [{"message": {"content": "OpsFlow Cloud automation services."}}]
                }
                return mock_resp
            mock_404 = MagicMock()
            mock_404.status_code = 404
            return mock_404

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_mock_key", "GROQ_MODEL": "llama-3.3-70b-versatile"}):
            with patch("requests.post", side_effect=mock_post):
                reply = WhatsAppService.call_groq_ai(
                    user_message="Tell me about your plans and trial",
                    organization_id=self.org.id
                )
                self.assertIsNotNone(reply)
                self.assertGreater(len(captured_messages), 0)
                sys_msg = next((m["content"] for m in captured_messages if m["role"] == "system"), "")
                self.assertIn("PKR 7,500/mo", sys_msg)
                self.assertIn("2-Day Free Trial", sys_msg)
                self.assertIn("JazzCash", sys_msg)
                self.assertIn("GROUNDING & ANTI-HALLUCINATION GUARDRAILS", sys_msg)

    def test_unknown_pricing_and_unsupported_integrations_guardrails(self):
        """Verifies guardrails instruct the model to state facts need confirmation for unverified details."""
        kb = WhatsAppService.get_verified_business_knowledge_base(self.org.id)
        # Verify unknown pricing guardrail exists
        self.assertIn("custom enterprise pricing", kb)
        self.assertIn("requires confirmation from our sales specialist or account team", kb)
        # Verify unsupported payment method guardrail exists
        self.assertIn("PayPal, EasyPaisa", kb)
        self.assertIn("requires confirmation from our billing department", kb)
        # Verify unsupported integration guardrail exists
        self.assertIn("Salesforce, HubSpot, Jira, Zapier app, Telegram", kb)
        self.assertIn("confirm enterprise integration feasibility", kb)

    def test_normal_contextual_replies_multilingual_english_and_roman_urdu(self):
        """Verifies normal contextual customer inquiries in Roman Urdu and English."""
        # 1. Normal contextual Roman Urdu reply via mock LLM
        with patch.object(WhatsAppService, "call_gemini_ai", return_value="Ji bilkul! OpsFlow Cloud aap ke business ki IT workflows automate karta hai."):
            res_urdu = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="Ap kia service da raha hai?",
                sender_name="Customer Urdu"
            )
            self.assertEqual(res_urdu["mode"], "gemini_ai")
            self.assertIn("OpsFlow Cloud aap ke business", res_urdu["reply_body"])

        # 2. Normal contextual English reply via mock LLM
        with patch.object(WhatsAppService, "call_gemini_ai", return_value="OpsFlow Cloud provides end-to-end IT incident orchestration and multi-agent automation."):
            res_en = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="What does OpsFlow Cloud do?",
                sender_name="Customer English"
            )
            self.assertEqual(res_en["mode"], "gemini_ai")
            self.assertIn("IT incident orchestration", res_en["reply_body"])

        # 3. Multilingual clean fallback for general greeting when LLMs are offline
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(WhatsAppService, "call_groq_ai", return_value=None):
                # English greeting fallback
                res_fallback_en = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Hello, good morning!",
                    sender_name="Customer English"
                )
                self.assertIn("How can I assist you", res_fallback_en["reply_body"])

                # Roman Urdu greeting fallback
                res_fallback_urdu = WhatsAppService.generate_ai_auto_response(
                    organization_id=self.org.id,
                    message_body="Kia hal hai aap ka?",
                    sender_name="Customer Urdu"
                )
                self.assertIn("main aapki kya madad kar sakta hoon", res_fallback_urdu["reply_body"])


if __name__ == "__main__":
    unittest.main()
