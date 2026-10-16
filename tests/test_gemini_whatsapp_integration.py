"""Focused test suite for Gemini AI WhatsApp Integration & Plain Text Outbound Verification.

Verifies:
1. Incoming Green-API webhook triggers the auto-responder.
2. Configured Gemini AI provider is called and its response is dispatched as pure plain text without 'AI Answer:' or canned wrappers.
3. Fallback when Gemini is unavailable contains NO echoing of the user's incoming message and NO canned templates.
4. Uses simulated/mock dispatching only (zero messages sent to real customers).
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, User, Membership, WhatsAppMessage, SystemSetting
import whatsapp_service
from whatsapp_service import WhatsAppService


class TestGeminiWhatsAppIntegration(unittest.TestCase):
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

        # Seed test organization
        self.org = Organization(
            id="org-pk-enterprise",
            name="Pak Enterprise Automations",
            slug="pak-enterprise",
            plan_tier="enterprise",
            is_active=True
        )
        db.session.add(self.org)

        # Seed admin user
        self.user = User(
            id="usr-pk-admin",
            email="admin@pakenterprise.pk",
            full_name="Tariq Mansoor",
            is_active=True
        )
        self.user.set_password("PakSecret2026!")
        db.session.add(self.user)
        db.session.commit()

        # Seed membership
        membership = Membership(
            id="mem-pk-1",
            user_id=self.user.id,
            organization_id=self.org.id,
            role="owner"
        )
        db.session.add(membership)
        db.session.commit()

        # Ensure simulator mode is active so no live network calls go to real WhatsApp users
        SystemSetting.set_val("WHATSAPP_SIMULATOR_FALLBACK", "true", is_secret=False)
        SystemSetting.set_val("GREEN_API_ID_INSTANCE", "", is_secret=False)
        SystemSetting.set_val("GREEN_API_TOKEN_INSTANCE", "", is_secret=False)

    def tearDown(self):
        self.env_patcher.stop()
        db.session.remove()
        try:
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_gemini_response_sent_as_pure_plain_text(self):
        """Verifies Gemini AI response is dispatched as pure plain text without 'AI Answer:' or canned wrappers."""
        mocked_gemini_reply = "Hello! Our enterprise plan includes dedicated SLA, unlimited automations, and custom integrations at $499/month."

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=mocked_gemini_reply):
            result = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body="Can you tell me about enterprise plan pricing?",
                sender_name="Ali Khan",
                sender_phone="923001112233"
            )

            # 1. Output must be pure plain text
            self.assertEqual(result["reply_body"], mocked_gemini_reply)
            self.assertEqual(result["mode"], "gemini_ai")

            # 2. Must NOT contain canned wrappers or 'AI Answer:'
            self.assertNotIn("AI Answer:", result["reply_body"])
            self.assertNotIn("We have received your", result["reply_body"])
            self.assertNotIn("Thank you for contacting", result["reply_body"])
            self.assertNotIn("Sincerely,", result["reply_body"])

    def test_green_api_inbound_webhook_dispatches_pure_gemini_response(self):
        """Incoming Green-API webhook calls Gemini and saves pure plain text response to database."""
        mocked_gemini_reply = "Thank you for asking! We provide 24/7 dedicated engineering support for your fleet operations."

        webhook_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": 7103998877,
                "wid": "7103998877@c.us",
                "typeInstance": "whatsapp"
            },
            "timestamp": 1713500000,
            "idMessage": "BAE5TESTMESSAGE001",
            "senderData": {
                "chatId": "923009876543@c.us",
                "chatName": "Zainab Bibi",
                "sender": "923009876543@c.us",
                "senderName": "Zainab Bibi"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "What are your support hours for enterprise fleet?"
                }
            }
        }

        # Enable auto responder for the organization
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=mocked_gemini_reply):
            resp = self.client.post(
                f"/api/v1/webhooks/whatsapp/green-api?org_id={self.org.id}",
                json=webhook_payload
            )
            self.assertEqual(resp.status_code, 200)

            # Query outbound message from database
            outbound_msg = WhatsAppMessage.query.filter_by(
                organization_id=self.org.id,
                direction="outbound"
            ).order_by(WhatsAppMessage.created_at.desc()).first()

            self.assertIsNotNone(outbound_msg)
            # Confirms message was sent with exact Gemini text
            self.assertEqual(outbound_msg.body, mocked_gemini_reply)

            # Confirms no canned wrappers or echoing
            self.assertNotIn("AI Answer:", outbound_msg.body)
            self.assertNotIn("We have received your", outbound_msg.body)
            self.assertNotIn("What are your support hours", outbound_msg.body)

    def test_fallback_does_not_echo_user_message_or_use_canned_template(self):
        """When Gemini AI is offline, fallback returns direct sentence without echoing the user's message."""
        user_incoming = "Urgent: We have an API issue and 500 error spikes on payments."

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            result = WhatsAppService.generate_ai_auto_response(
                organization_id=self.org.id,
                message_body=user_incoming,
                sender_name="CTO Client",
                sender_phone="923005551122"
            )

            reply = result["reply_body"]

            # Must NOT echo user's message
            self.assertNotIn(user_incoming, reply)
            self.assertNotIn("500 error spikes", reply)
            self.assertNotIn("payments", reply)

            # Must NOT have canned template wrappers
            self.assertNotIn("AI Answer:", reply)
            self.assertNotIn("We have received your message regarding", reply)
            self.assertNotIn("We have received your inquiry regarding", reply)
            self.assertNotIn("We have received your support request regarding", reply)

            # Must be a clean, direct sentence
            self.assertTrue(len(reply) > 20)

    def test_gemini_model_configuration_and_fallbacks(self):
        """Verifies configured Gemini model is resolved from settings and defaults safely."""
        # 1. Default model
        default_model = WhatsAppService.get_gemini_model_name()
        self.assertEqual(default_model, "gemini-1.5-flash")

        # 2. Configured custom model in SystemSetting
        SystemSetting.set_val("GEMINI_MODEL", "gemini-1.5-pro", is_secret=False)
        custom_model = WhatsAppService.get_gemini_model_name()
        self.assertEqual(custom_model, "gemini-1.5-pro")

        # 3. Clean up
        SystemSetting.set_val("GEMINI_MODEL", "", is_secret=False)

    def test_regression_successful_gemini_response_sent_as_natural_plain_text(self):
        """Regression test: Proves that a successful Gemini response is sent as natural plain text without prefixes or canned wrappers, and recorded as gemini_ai."""
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        natural_gemini_response = (
            "Hello! We offer automated incident workflows, multi-channel alerting, and AI-driven WhatsApp support. "
            "Our Starter plan is $49/mo, Pro is $149/mo, and Enterprise includes dedicated SLA and custom automations."
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=natural_gemini_response):
            result = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923007654321",
                message_body="What service and pricing do you offer",
                sender_name="Prospective Customer",
                message_id="wamid.test_gemini_success_101"
            )

            self.assertIsNotNone(result)
            self.assertTrue(result["success"])
            self.assertEqual(result["reply_body"], natural_gemini_response)

            # Query the database record for outbound WhatsApp message
            outbound_msg = WhatsAppMessage.query.filter_by(
                organization_id=self.org.id,
                direction="outbound"
            ).order_by(WhatsAppMessage.created_at.desc()).first()

            self.assertIsNotNone(outbound_msg)
            # Body must match exactly the natural Gemini plain text
            self.assertEqual(outbound_msg.body, natural_gemini_response)
            # Must NOT contain canned wrappers, boilerplate, or prefixes
            self.assertNotIn("AI Answer:", outbound_msg.body)
            self.assertNotIn("A solutions specialist is reviewing", outbound_msg.body)
            self.assertNotIn("We have received your", outbound_msg.body)

            # Payload metadata must verify it is genuinely a Gemini response
            meta = json.loads(outbound_msg.raw_payload_json or "{}")
            self.assertTrue(meta.get("is_gemini_response"))
            self.assertEqual(meta.get("response_source"), "gemini_ai")

    def test_regression_ai_failure_logged_clearly_and_not_falsely_presented_as_gemini(self):
        """Regression test: Proves that an AI failure is logged clearly with WARNING level rather than falsely presented as a Gemini answer."""
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        incoming_query = "What service and pricing do you offer"

        # Simulate Gemini AI failure (returning None due to offline/missing key/quota error)
        with patch.object(WhatsAppService, "call_gemini_ai", return_value=None):
            with patch.object(whatsapp_service.logger, "warning") as mock_logger_warn:
                result = WhatsAppService.handle_inbound_auto_response(
                    organization_id=self.org.id,
                    sender_phone="923008889999",
                    message_body=incoming_query,
                    sender_name="Prospective Customer",
                    message_id="wamid.test_gemini_fail_202"
                )

                self.assertIsNotNone(result)
                self.assertTrue(result["success"])

                # Check log messages: MUST clearly log that Gemini AI was unavailable/failed
                warn_calls = [str(c.args[0]) for c in mock_logger_warn.call_args_list if c.args]
                log_text = " ".join(warn_calls)
                self.assertIn("Gemini AI generation was unavailable or failed", log_text)
                self.assertIn("rather than presenting as Gemini answer", log_text)

                # Check outbound message body in DB
                outbound_msg = WhatsAppMessage.query.filter_by(
                    organization_id=self.org.id,
                    direction="outbound"
                ).order_by(WhatsAppMessage.created_at.desc()).first()

                self.assertIsNotNone(outbound_msg)
                # It sends the clean service fallback, NOT falsely claiming to be a Gemini answer
                self.assertEqual(
                    outbound_msg.body,
                    "A solutions specialist is reviewing your inquiry and will follow up with tailored details and pricing."
                )
                self.assertNotIn("AI Answer:", outbound_msg.body)
                self.assertNotIn(incoming_query, outbound_msg.body)

                # Payload metadata must NOT falsely present this as a Gemini response
                meta = json.loads(outbound_msg.raw_payload_json or "{}")
                self.assertFalse(meta.get("is_gemini_response", False))
                self.assertEqual(meta.get("response_source"), "system_fallback")
                self.assertNotEqual(meta.get("response_source"), "gemini_ai")


if __name__ == "__main__":
    unittest.main()
