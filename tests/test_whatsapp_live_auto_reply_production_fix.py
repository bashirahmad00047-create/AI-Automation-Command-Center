import os
import time
import unittest
from unittest.mock import patch

from app import create_app
from database import db
from models import Organization, WhatsAppMessage, SystemSetting
from whatsapp_service import WhatsAppService


class TestWhatsAppLiveAutoReplyProductionFix(unittest.TestCase):
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
        db.session.rollback()
        self.ctx.pop()

    def test_instance_resolution_7017278160(self):
        """Instance ID 7017278160 resolves directly to org-enterprise-default."""
        resolved = WhatsAppService.resolve_organization_by_instance("7017278160")
        self.assertEqual(resolved, "org-enterprise-default")

    def test_own_number_matching_does_not_suppress_jazzcash_or_admin_phone(self):
        """Messages from 03209350858 are NOT suppressed even when JAZZCASH_NUMBER is configured."""
        with patch.dict(os.environ, {
            "JAZZCASH_NUMBER": "03209350858",
            "ADMIN_PHONE": "03209350858",
            "GREEN_API_WID": "923471000668@c.us",
            "AI_AUTO_REPLY_ENABLED": "true"
        }):
            SystemSetting.set_val("GREEN_API_WID", "923471000668@c.us")

            with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id="org-enterprise-default",
                    sender_phone="03209350858",
                    message_body="سلام وروره، د کلاوډ پکیج قیمت څومره دی؟",
                    sender_name="Khan",
                    message_id="msg_pashto_test_101"
                )
                self.assertIsNotNone(res)
                mock_send.assert_called_once()
                sent_args = mock_send.call_args[1]
                self.assertEqual(sent_args["to_phone"], "923209350858")
                self.assertTrue(any(ord(c) >= 0x0600 and ord(c) <= 0x06FF for c in sent_args["message_text"]))

    def test_own_number_suppression_strictly_blocks_real_bot_wid(self):
        """Messages where sender equals bot's actual GREEN_API_WID are suppressed to prevent loops."""
        with patch.dict(os.environ, {
            "GREEN_API_WID": "923471000668@c.us",
            "AI_AUTO_REPLY_ENABLED": "true"
        }):
            SystemSetting.set_val("GREEN_API_WID", "923471000668@c.us")
            with patch.object(WhatsAppService, "send_message") as mock_send:
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id="org-enterprise-default",
                    sender_phone="923471000668",
                    message_body="Bot self-echo message",
                    message_id="msg_bot_echo_102"
                )
                self.assertIsNone(res)
                mock_send.assert_not_called()

    def test_suffix_collision_does_not_suppress_genuine_customer(self):
        """Customer phone sharing last 9 digits with instance or billing number is NOT suppressed."""
        with patch.dict(os.environ, {
            "GREEN_API_ID_INSTANCE": "7017278160",
            "GREEN_API_WID": "923471000668@c.us",
            "AI_AUTO_REPLY_ENABLED": "true"
        }):
            SystemSetting.set_val("GREEN_API_WID", "923471000668@c.us")
            with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
                res = WhatsAppService.handle_inbound_auto_response(
                    organization_id="org-enterprise-default",
                    sender_phone="923337278160",
                    message_body="Can I get pricing details please?",
                    sender_name="Customer",
                    message_id="msg_cust_suffix_103"
                )
                self.assertIsNotNone(res)
                mock_send.assert_called_once()

    def test_env_fallback_for_ai_auto_reply_enabled(self):
        """When database setting is empty, os.environ AI_AUTO_REPLY_ENABLED=true enables responder."""
        SystemSetting.set_val("AI_AUTO_REPLY_ENABLED", "")
        SystemSetting.set_val("ORG_org-enterprise-default_AI_AUTO_REPLY_ENABLED", "")

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}):
            auto_conf = WhatsAppService.get_auto_responder_config(organization_id="org-enterprise-default")
            self.assertTrue(auto_conf["enabled"])

    def test_green_api_webhook_ingress_routes_7017278160_to_org_enterprise_default(self):
        """Green-API webhook POST with instance 7017278160 maps to org-enterprise-default and triggers reply."""
        webhook_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": 7017278160,
                "wid": "923471000668@c.us",
                "typeInstance": "whatsapp"
            },
            "timestamp": int(time.time()),
            "idMessage": "3EB0TESTINGWEBHOOK7017",
            "senderData": {
                "chatId": "923001234567@c.us",
                "sender": "923001234567@c.us",
                "chatName": "Ahmad",
                "senderName": "Ahmad"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "سلام وروره، پکیج څه قیمت لري؟"
                }
            }
        }

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}):
            SystemSetting.set_val("ORG_org-enterprise-default_AI_AUTO_REPLY_ENABLED", "true")

            with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
                resp = self.client.post("/api/v1/webhooks/whatsapp/green-api", json=webhook_payload)
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data.get("status"), "ok")
                self.assertEqual(data.get("processed"), 1)

                # Verify message was persisted to db under org-enterprise-default
                inbound_msg = WhatsAppMessage.query.filter_by(whatsapp_message_id="3EB0TESTINGWEBHOOK7017").first()
                self.assertIsNotNone(inbound_msg)
                self.assertEqual(inbound_msg.organization_id, "org-enterprise-default")
                self.assertEqual(inbound_msg.direction, "inbound")

                # Verify auto-reply was dispatched to customer
                mock_send.assert_called_once()
                call_args = mock_send.call_args[1]
                self.assertEqual(call_args["to_phone"], "923001234567")


if __name__ == "__main__":
    unittest.main()
