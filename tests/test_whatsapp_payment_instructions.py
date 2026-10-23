import json
import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, User, Membership, EcommerceOrder, Lead
from whatsapp_service import WhatsAppService


class TestWhatsAppPaymentInstructions(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Cloud Commerce",
                slug="opsflow-commerce",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        self.user = User.query.filter_by(email="pay_admin@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-pay-admin",
                email="pay_admin@opsflow.io",
                full_name="Payment Admin",
                is_active=True
            )
            self.user.set_password("SecurePass123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-pay-admin",
                user_id=self.user.id,
                organization_id=self.org.id,
                role="admin"
            )
            db.session.add(mem)
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_generate_payment_instructions_default_details(self):
        """Verifies default active JazzCash (03209350858 / Bashir Uddin) and Render checkout base URL."""
        pay_info = WhatsAppService.generate_payment_instructions(
            organization_id=self.org.id,
            order_number="ORD-TEST-101",
            amount=3500.0,
            currency="PKR",
            customer_phone="03001234567"
        )

        self.assertIn("jazzcash", pay_info)
        self.assertEqual(pay_info["jazzcash"]["account_number"], "03209350858")
        self.assertEqual(pay_info["jazzcash"]["account_title"], "Bashir Uddin")

        # Verify EasyPaisa and Meezan Bank are completely removed
        self.assertIsNone(pay_info["easypaisa"])
        self.assertIsNone(pay_info["bank_transfer"])

        # Verify Render base URL
        self.assertIn("https://ai-automation-command-center-4.onrender.com", pay_info["card_payment_link"])

        fmt = pay_info["formatted_text"]
        self.assertIn("03209350858", fmt)
        self.assertIn("Bashir Uddin", fmt)
        self.assertIn("https://ai-automation-command-center-4.onrender.com", fmt)
        self.assertIn("ORD-TEST-101", fmt)

        # Confirm no placeholders or removed methods exist in formatted auto-reply
        self.assertNotIn("EasyPaisa", fmt)
        self.assertNotIn("Meezan Bank", fmt)
        self.assertNotIn("[Aapka", fmt)

    def test_handle_payment_query_detection(self):
        """Verifies detection of payment inquiry query and generation of structured JazzCash payment details."""
        res = WhatsAppService.handle_payment_query_or_deal_closure(
            organization_id=self.org.id,
            sender_phone="923001234567",
            message_text="Aapke payment options kya hain? JazzCash bhej dein",
            sender_name="Ahmed"
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["trigger_type"], "payment_inquiry")
        self.assertIn("03209350858", res["message"])
        self.assertIn("Bashir Uddin", res["message"])
        self.assertNotIn("EasyPaisa", res["message"])
        self.assertNotIn("Meezan Bank", res["message"])
        self.assertNotIn("[Aapka", res["message"])

    def test_handle_deal_closure_detection(self):
        """Verifies detection of deal completion query and auto-dispatch of JazzCash payment instructions."""
        res = WhatsAppService.handle_payment_query_or_deal_closure(
            organization_id=self.org.id,
            sender_phone="923007654321",
            message_text="Deal done, parcel bhej do",
            sender_name="Kamran"
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["trigger_type"], "deal_closed")
        self.assertIn("Deal Confirmed", res["message"])
        self.assertIn("03209350858", res["message"])
        self.assertIn("Bashir Uddin", res["message"])
        self.assertNotIn("EasyPaisa", res["message"])
        self.assertNotIn("Meezan Bank", res["message"])

    @patch("whatsapp_service.WhatsAppService.send_message")
    def test_inbound_auto_response_payment_query_dispatches_and_captures_lead(self, mock_send):
        """Verifies inbound auto-responder triggers payment dispatch and records CRM Lead."""
        mock_send.return_value = {"success": True, "message_id": "test-msg-123"}

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}):
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923331122334",
                message_body="Can you please share your payment method details?",
                sender_name="Zubair Khan"
            )

        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "payment_instructions_dispatched")
        self.assertEqual(res["trigger_type"], "payment_inquiry")
        mock_send.assert_called_once()
        sent_body = mock_send.call_args[1]["message_text"]
        self.assertIn("03209350858", sent_body)
        self.assertIn("Bashir Uddin", sent_body)
        self.assertNotIn("EasyPaisa", sent_body)
        self.assertNotIn("Meezan Bank", sent_body)

        # Verify CRM Lead ingestion
        lead = Lead.query.filter(
            Lead.organization_id == self.org.id,
            Lead.phone == "923331122334"
        ).first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.name, "Zubair Khan")
        self.assertEqual(lead.intent, "payment_or_deal_closure")

    @patch("whatsapp_service.WhatsAppService.send_message")
    def test_inbound_auto_response_deal_closure_dispatches(self, mock_send):
        """Verifies inbound auto-responder triggers payment dispatch on deal closure."""
        mock_send.return_value = {"success": True, "message_id": "test-msg-456"}

        with patch.dict(os.environ, {"AI_AUTO_REPLY_ENABLED": "true"}):
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923335566778",
                message_body="Done deal, packing shuru karein",
                sender_name="Babar"
            )

        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "payment_instructions_dispatched")
        self.assertEqual(res["trigger_type"], "deal_closed")
        mock_send.assert_called_once()
        sent_body = mock_send.call_args[1]["message_text"]
        self.assertIn("Deal Confirmed", sent_body)
        self.assertIn("03209350858", sent_body)
        self.assertIn("Bashir Uddin", sent_body)

    def test_api_get_ecommerce_payment_methods(self):
        """Verifies GET /api/v1/ecommerce/payment-methods returns active JazzCash options."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        resp = self.client.get("/api/v1/ecommerce/payment-methods")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        methods = data["payment_methods"]
        self.assertEqual(methods["jazzcash"]["account_number"], "03209350858")
        self.assertEqual(methods["jazzcash"]["account_title"], "Bashir Uddin")
        self.assertIsNone(methods["easypaisa"])
        self.assertIsNone(methods["bank_transfer"])

    @patch("whatsapp_service.WhatsAppService.send_message")
    def test_api_send_order_payment_instructions(self, mock_send):
        """Verifies POST /api/v1/ecommerce/orders/<order_id>/send-payment-instructions dispatches WhatsApp message."""
        mock_send.return_value = {"success": True, "message_id": "api-msg-789"}

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        order = EcommerceOrder(
            organization_id=self.org.id,
            order_number="ORD-PAY-999",
            customer_phone="923219876543",
            customer_name="Tariq",
            total_amount=12000.0,
            currency="PKR"
        )
        db.session.add(order)
        db.session.commit()

        resp = self.client.post(f"/api/v1/ecommerce/orders/{order.id}/send-payment-instructions")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["order_number"], "ORD-PAY-999")
        self.assertEqual(data["recipient"], "923219876543")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs["to_phone"], "923219876543")
        self.assertIn("03209350858", call_kwargs["message_text"])
        self.assertIn("Bashir Uddin", call_kwargs["message_text"])
        self.assertNotIn("EasyPaisa", call_kwargs["message_text"])
        self.assertNotIn("Meezan Bank", call_kwargs["message_text"])


if __name__ == "__main__":
    unittest.main()
