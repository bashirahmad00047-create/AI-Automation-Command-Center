"""Test suite for WhatsApp Quoted Messages & Sync Login Fixes.

Verifies:
1. extract_message_body_and_quote handles quotedMessage, extendedTextMessage quotes, media captions, and never returns '[quotedMessage]'.
2. parse_green_api_payload parses quotedMessage and saves GREEN_API_WID to SystemSettings.
3. sync_last_incoming_messages never triggers AI auto-response during history synchronization (prevents login message storm).
4. Cooldown debounce works when cooldown_minutes > 0 even when AI is enabled.
5. Inbound messages from instance GREEN_API_WID are suppressed (self-reply loop prevention).
"""

import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestWhatsAppQuotedMessagesAndSync(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-pk-test").first()
        if not self.org:
            self.org = Organization(id="org-pk-test", name="Test Org PK", slug="test-org-pk")
            db.session.add(self.org)
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_extract_message_body_and_quote_full(self):
        """Verifies quoted message with both reply text and quoted text is formatted cleanly."""
        payload = {
            "typeMessage": "quotedMessage",
            "extendedTextMessageData": {
                "text": "Yes, we have 5 units in stock."
            },
            "quotedMessage": {
                "typeMessage": "textMessage",
                "textMessage": "Is the Pro tier available?"
            }
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(extracted, "Yes, we have 5 units in stock.\n\n> Quoted: Is the Pro tier available?")

    def test_extract_message_body_and_quote_only_quote(self):
        """Verifies quoted message with only quoted text returns quote marker."""
        payload = {
            "typeMessage": "quotedMessage",
            "quotedMessage": {
                "textMessage": "Original query about pricing"
            }
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(extracted, "> Quoted: Original query about pricing")

    def test_extract_message_body_and_quote_empty_fallback(self):
        """Verifies empty quotedMessage never returns raw '[quotedMessage]'."""
        payload = {
            "typeMessage": "quotedMessage"
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(extracted, "Quoted message")
        self.assertNotIn("[quotedMessage]", extracted)

    def test_extract_message_body_and_quote_media(self):
        """Verifies image and document quotes are formatted nicely."""
        payload_img = {
            "typeMessage": "imageMessage",
            "fileMessageData": {
                "caption": "Payment receipt screenshot"
            }
        }
        self.assertEqual(WhatsAppService.extract_message_body_and_quote(payload_img), "[Image] Payment receipt screenshot")

        payload_doc = {
            "typeMessage": "documentMessage",
            "fileMessageData": {
                "fileName": "invoice_102.pdf"
            }
        }
        self.assertEqual(WhatsAppService.extract_message_body_and_quote(payload_doc), "[Document: invoice_102.pdf]")

    def test_extract_message_body_and_quote_nested_text_message_data(self):
        """Verifies quoted text inside quotedMessage.textMessageData.textMessage is cleanly extracted."""
        payload = {
            "typeMessage": "quotedMessage",
            "extendedTextMessageData": {
                "text": "Certainly, we can deliver tomorrow morning."
            },
            "quotedMessage": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "Can you deliver tomorrow?"
                }
            }
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(
            extracted,
            "Certainly, we can deliver tomorrow morning.\n\n> Quoted: Can you deliver tomorrow?"
        )

    def test_extract_message_body_and_quote_stanza_id_lookup_from_db(self):
        """Verifies that when payload only gives stanzaId, quoted text is resolved from local WhatsAppMessage DB."""
        # Seed the original message in DB
        orig_msg = WhatsAppMessage(
            id="msg_seed_101",
            organization_id=self.org.id,
            whatsapp_message_id="3EB0_ORIGINAL_STANZA_101",
            sender="923001112233",
            recipient="system",
            direction="inbound",
            body="What are the payment options for OpsFlow Cloud?",
            status="received"
        )
        db.session.add(orig_msg)
        db.session.commit()

        # Incoming webhook payload with only stanzaId (standard Green-API Scenario A)
        payload = {
            "typeMessage": "quotedMessage",
            "extendedTextMessageData": {
                "text": "We accept Bank Transfer, JazzCash, and Credit Card.",
                "stanzaId": "3EB0_ORIGINAL_STANZA_101",
                "participant": "923001112233@c.us"
            }
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(
            extracted,
            "We accept Bank Transfer, JazzCash, and Credit Card.\n\n> Quoted: What are the payment options for OpsFlow Cloud?"
        )

    def test_extract_message_body_and_quote_clean_fallback_when_unavailable(self):
        """Verifies that if quoted text is completely unavailable, a clean fallback is used without blank text."""
        payload = {
            "typeMessage": "quotedMessage",
            "extendedTextMessageData": {
                "text": "I agree to the quote terms.",
                "stanzaId": "NONEXISTENT_STANZA_999"
            }
        }
        extracted = WhatsAppService.extract_message_body_and_quote(payload)
        self.assertEqual(extracted, "I agree to the quote terms.\n\n> Quoted: Quoted message")
        self.assertNotIn("> Quoted: \n", extracted)
        self.assertFalse(extracted.endswith("> Quoted:"))

    def test_parse_green_api_payload_quoted_and_persists_wid(self):
        """Verifies parse_green_api_payload extracts clean quotes and persists instance WID."""
        webhook_data = {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "msg_quote_001",
            "timestamp": 1700000000,
            "instanceData": {
                "idInstance": 710722761603,
                "wid": "923209350858@c.us"
            },
            "senderData": {
                "chatId": "923001234567@c.us",
                "senderName": "Customer Ali"
            },
            "messageData": {
                "typeMessage": "quotedMessage",
                "extendedTextMessageData": {
                    "text": "Can I pay via JazzCash?"
                },
                "quotedMessage": {
                    "textMessage": "Monthly subscription is PKR 4,999."
                }
            }
        }
        msgs = WhatsAppService.parse_green_api_payload(webhook_data)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["body"], "Can I pay via JazzCash?\n\n> Quoted: Monthly subscription is PKR 4,999.")
        self.assertEqual(msgs[0]["from_phone"], "923001234567")
        self.assertNotIn("[quotedMessage]", msgs[0]["body"])

        # Check that GREEN_API_WID was persisted in SystemSetting
        wid = SystemSetting.get_val("GREEN_API_WID")
        self.assertEqual(wid, "923209350858@c.us")

    def test_sync_last_incoming_messages_never_triggers_auto_response(self):
        """Verifies sync_last_incoming_messages ingests messages into ledger without triggering AI auto-replies."""
        fake_journal = [
            {
                "idMessage": "journal_msg_001",
                "chatId": "923009876543@c.us",
                "senderName": "Past Customer",
                "typeMessage": "textMessage",
                "textMessage": "What are your business hours?"
            },
            {
                "idMessage": "journal_msg_002",
                "chatId": "923009876543@c.us",
                "senderName": "Past Customer",
                "typeMessage": "quotedMessage",
                "extendedTextMessageData": {
                    "text": "And do you accept bank transfer?"
                },
                "quotedMessage": {
                    "textMessage": "What are your business hours?"
                }
            }
        ]

        with patch.object(WhatsAppService, "fetch_last_incoming_messages", return_value=fake_journal):
            with patch.object(WhatsAppService, "handle_inbound_auto_response") as mock_auto_resp:
                res = WhatsAppService.sync_last_incoming_messages(
                    organization_id=self.org.id,
                    minutes=1440,
                    max_messages=10
                )
                self.assertTrue(res["success"])
                self.assertEqual(res["new_messages_ingested"], 2)
                # Ensure handle_inbound_auto_response was NEVER called during sync
                mock_auto_resp.assert_not_called()

        # Verify messages are in DB with clean bodies
        m2 = WhatsAppMessage.query.filter_by(whatsapp_message_id="journal_msg_002").first()
        self.assertIsNotNone(m2)
        self.assertEqual(m2.body, "And do you accept bank transfer?\n\n> Quoted: What are your business hours?")

    def test_cooldown_debounce_active_when_cooldown_positive(self):
        """Verifies cooldown debounces consecutive AI auto-replies when cooldown_minutes > 0."""
        sender = "923115554433"

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=10
        )

        # Mock an outbound message recently sent to this sender
        recent_outbound = WhatsAppMessage(
            organization_id=self.org.id,
            sender="923209350858",
            recipient=sender,
            direction="outbound",
            body="Recent outbound message to customer",
            status="sent"
        )
        db.session.add(recent_outbound)
        db.session.commit()

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value=None), patch.object(WhatsAppService, "get_groq_api_key", return_value=None):
            with patch.object(WhatsAppService, "generate_ai_auto_response") as mock_gen:
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id=self.org.id,
                    sender_phone=sender,
                    message_body="Hello again!",
                    sender_name="Frequent User",
                    message_id="msg_debounce_001"
                )
                self.assertIsNone(res)
                mock_gen.assert_not_called()

    def test_self_reply_loop_prevention_with_persisted_wid(self):
        """Verifies inbound messages from the instance's own WID are ignored."""
        SystemSetting.set_val("GREEN_API_WID", "923209350858@c.us")

        with patch.object(WhatsAppService, "generate_ai_auto_response") as mock_gen:
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="OpsFlow Cloud login confirmation",
                sender_name="OpsFlow",
                message_id="msg_self_001"
            )
            self.assertIsNone(res)
            mock_gen.assert_not_called()

    def test_stale_message_timestamp_ignored_for_auto_reply(self):
        """Verifies messages older than 15 minutes are ignored for auto-reply on polling/login."""
        import time
        stale_time = time.time() - 3600  # 1 hour ago

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake_gemini_key"):
            with patch.object(WhatsAppService, "generate_ai_auto_response") as mock_gen:
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id=self.org.id,
                    sender_phone="923009998877",
                    message_body="Where are you located?",
                    sender_name="Old Customer",
                    message_id="msg_stale_001",
                    message_timestamp=stale_time
                )
                self.assertIsNone(res)
                mock_gen.assert_not_called()

    def test_fresh_message_timestamp_allowed_for_auto_reply(self):
        """Verifies fresh incoming messages (under 15 mins) trigger auto-reply normally."""
        import time
        fresh_time = time.time() - 10  # 10 seconds ago

        WhatsAppService.save_auto_responder_config(
            organization_id=self.org.id,
            enabled=True,
            cooldown_minutes=0
        )

        with patch.object(WhatsAppService, "call_gemini_ai", return_value="We are located in Islamabad."):
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923009998877",
                message_body="Where are you located?",
                sender_name="New Customer",
                message_id="msg_fresh_001",
                message_timestamp=fresh_time
            )
            self.assertIsNotNone(res)
            self.assertTrue(res.get("success"))


if __name__ == "__main__":
    unittest.main()
