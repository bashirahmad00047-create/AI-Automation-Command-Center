# -*- coding: utf-8 -*-
"""Unit and integration tests verifying inbound auto-response triggers send_green_api_message with the exact generated response body."""

from __future__ import annotations

import os
import sys
import json
import time
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from limiter import limiter
from models import Organization, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestInboundDispatchExactResponse(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.app.config["RATELIMIT_ENABLED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        # Seed test organization
        self.org_id = "org-enterprise-default"
        self.org = db.session.get(Organization, self.org_id)
        if not self.org:
            self.org = Organization(
                id=self.org_id,
                name="Acme Global Enterprise",
                slug="acme-global",
                plan_tier="enterprise",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        # Ensure auto-responder is enabled with 0 cooldown for instant replies
        WhatsAppService.save_auto_responder_config(
            organization_id=self.org_id,
            enabled=True,
            cooldown_minutes=0,
            auto_lead_capture=True
        )

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_gemini_response_dispatched_with_exact_body(self):
        """Verifies inbound Urdu inquiry triggers send_green_api_message with the exact generated Gemini AI response."""
        expected_ai_reply = "ہم جدید کلاؤڈ آٹومیشن، لاجسٹکس مانیٹرنگ اور سمارٹ ورک فلو کے حل فراہم کرتے ہیں۔"
        inbound_text = "آپ کونسی سروس دے رہے ہیں"
        test_phone = "923001234567"
        msg_id = "wamid.exact_body_test_001"

        with patch.object(WhatsAppService, "call_gemini_ai", return_value=expected_ai_reply) as mock_gemini:
            with patch.object(WhatsAppService, "send_green_api_message") as mock_dispatch:
                mock_dispatch.return_value = {
                    "success": True,
                    "status": "sent",
                    "provider": "green_api",
                    "whatsapp_message_id": "3EB0TEST_MESSAGE_ID_101",
                    "recipient": test_phone,
                    "message_type": "text"
                }

                result = WhatsAppService.handle_inbound_auto_response(
                    organization_id=self.org_id,
                    sender_phone=test_phone,
                    message_body=inbound_text,
                    sender_name="Mubi",
                    message_id=msg_id,
                    message_timestamp=time.time()
                )

                # 1. Verify Gemini AI was called with customer's inbound message
                self.assertTrue(mock_gemini.called)
                self.assertEqual(mock_gemini.call_count, 1)

                # 2. Verify send_green_api_message was called explicitly
                self.assertTrue(mock_dispatch.called)
                self.assertEqual(mock_dispatch.call_count, 1)

                # 3. Verify exact arguments passed to send_green_api_message
                kwargs = mock_dispatch.call_args[1]
                self.assertEqual(kwargs.get("to_phone"), test_phone)
                self.assertEqual(kwargs.get("message_text"), expected_ai_reply)
                self.assertEqual(kwargs.get("quoted_message_id"), msg_id)

                # 4. Verify result object contains exact reply body
                self.assertIsNotNone(result)
                self.assertTrue(result["success"])
                self.assertEqual(result["reply_body"], expected_ai_reply)
                self.assertEqual(result["is_gemini"], True)
                self.assertEqual(result["is_ai_generated"], True)

    def test_credential_loading_from_environment_and_database(self):
        """Verifies Gemini API key and Green-API credentials resolve seamlessly across env and DB settings."""
        test_gemini_val = "AIzaSyTestGeminiKeyMock1234567890"

        # Test A: Loading Gemini key via os.environ (case-insensitive)
        with patch.dict(os.environ, {"GEMINI_API_KEY": test_gemini_val}):
            resolved_key = WhatsAppService.get_gemini_api_key(self.org_id)
            self.assertEqual(resolved_key, test_gemini_val)

        # Test B: Loading Gemini key via SystemSetting in Database
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing env var
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            SystemSetting.set_val("GEMINI_API_KEY", test_gemini_val, is_secret=True)

            resolved_db_key = WhatsAppService.get_gemini_api_key(self.org_id)
            self.assertEqual(resolved_db_key, test_gemini_val)

        # Test C: Loading Green-API config
        conf = WhatsAppService.get_config(self.org_id)
        self.assertIsNotNone(conf.get("green_api_id_instance"))
        self.assertIsNotNone(conf.get("green_api_token_instance"))
        self.assertTrue(len(str(conf.get("green_api_id_instance"))) >= 5)

    def test_empty_message_body_does_not_return_early(self):
        """Verifies an empty or whitespace message body does not drop or return early, but triggers response dispatch."""
        test_phone = "923009998877"
        msg_id = "wamid.empty_body_test_002"

        with patch.object(WhatsAppService, "send_green_api_message") as mock_dispatch:
            mock_dispatch.return_value = {
                "success": True,
                "status": "sent",
                "provider": "green_api",
                "whatsapp_message_id": "3EB0EMPTY_TEST_ID",
                "recipient": test_phone,
                "message_type": "text"
            }

            result = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org_id,
                sender_phone=test_phone,
                message_body="   ",  # whitespace body
                sender_name="Whitespace Sender",
                message_id=msg_id,
                message_timestamp=time.time()
            )

            # Must not return None / early exit
            self.assertIsNotNone(result)
            self.assertTrue(result["success"])
            self.assertTrue(mock_dispatch.called)
            dispatched_text = mock_dispatch.call_args[1]["message_text"]
            self.assertTrue(len(dispatched_text) > 0)
            self.assertEqual(result["reply_body"], dispatched_text)

    def test_system_fallback_matches_dispatched_body(self):
        """Verifies that even when AI key is absent, the fallback reply text matches the dispatched body exactly."""
        inbound_text = "آپ کونسی سروس دے رہے ہیں"
        test_phone = "923005554433"
        msg_id = "wamid.fallback_test_003"

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value=None):
            with patch.object(WhatsAppService, "get_groq_api_key", return_value=None):
                with patch.object(WhatsAppService, "get_openai_api_key", return_value=None):
                    with patch.object(WhatsAppService, "send_green_api_message") as mock_dispatch:
                        mock_dispatch.return_value = {
                            "success": True,
                            "status": "sent",
                            "provider": "green_api",
                            "whatsapp_message_id": "3EB0FALLBACK_TEST_ID",
                            "recipient": test_phone,
                            "message_type": "text"
                        }

                        result = WhatsAppService.handle_inbound_auto_response(
                            organization_id=self.org_id,
                            sender_phone=test_phone,
                            message_body=inbound_text,
                            sender_name="Mubi",
                            message_id=msg_id,
                            message_timestamp=time.time()
                        )

                        self.assertIsNotNone(result)
                        self.assertTrue(result["success"])
                        self.assertTrue(mock_dispatch.called)

                        # Dispatched text MUST match result['reply_body']
                        dispatched_text = mock_dispatch.call_args[1]["message_text"]
                        self.assertEqual(result["reply_body"], dispatched_text)
                        self.assertIn("OpsFlow Cloud", dispatched_text)


if __name__ == "__main__":
    unittest.main()
