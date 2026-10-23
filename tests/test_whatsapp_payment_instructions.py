import json
import os
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, User, Membership, EcommerceOrder, Lead, SystemSetting
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
        """Verifies default custom accounts template for JazzCash, EasyPaisa, and Bank Transfer IBAN."""
        pay_info = WhatsAppService.generate_payment_instructions(
            organization_id=self.org.id,
            order_number="ORD-TEST-101",
            amount=3500.0,
            currency="PKR",
            customer_phone="03001234567"
        )

        self.assertIn("jazzcash", pay_info)
        self.assertEqual(pay_info["jazzcash"]["account_number"], "[Aapka JazzCash Number]")
        self.assertEqual(pay_info["jazzcash"]["account_title"], "[Aapka Naam]")

        self.assertIn("easypaisa", pay_info)
        self.assertEqual(pay_info["easypaisa"]["account_number"], "[Aapka EasyPaisa Number]")
        self.assertEqual(pay_info["easypaisa"]["account_title"], "[Aapka Naam]")

        self.assertIn("bank_transfer", pay_info)
        self.assertEqual(pay_info["bank_transfer"]["bank_name"], "[Bank Name]")
        self.assertEqual(pay_info["bank_transfer"]["account_title"], "[Account Title]")
        self.assertEqual(pay_info["bank_transfer"]["iban"], "[Aapka IBAN Number]")

        fmt = pay_info["formatted_text"]
        self.assertIn("[Aapka JazzCash Number]", fmt)
        self.assertIn("[Aapka EasyPaisa Number]", fmt)
        self.assertIn("[Aapka IBAN Number]", fmt)
        self.assertIn("[Bank Name]", fmt)
        self.assertIn("[Account Title]", fmt)
        self.assertIn("ORD-TEST-101", fmt)

    def test_generate_payment_instructions_with_configured_settings(self):
        """Verifies custom settings override the default template when configured."""
        with patch.object(WhatsAppService, "_get_tenant_or_global_setting") as mock_get:
            def mock_setting_lookup(key, org_id):
                mapping = {
                    "JAZZCASH_ACCOUNT_NUMBER": "03009998877",
                    "JAZZCASH_ACCOUNT_TITLE": "Muhammad Ali",
                    "EASYPAISA_ACCOUNT_NUMBER": "03451112233",
                    "EASYPAISA_ACCOUNT_TITLE": "Muhammad Ali",
                    "BANK_NAME": "HBL Pakistan",
                    "BANK_ACCOUNT_TITLE": "Ali Enterprises",
                    "BANK_ACCOUNT_NUMBER": "0011223344",
                    "BANK_IBAN": "PK12HABB000011223344"
                }
                return mapping.get(key)
            mock_get.side_effect = mock_setting_lookup

            pay_info = WhatsAppService.generate_payment_instructions(
                organization_id=self.org.id,
                order_number="ORD-CUSTOM-001",
                amount=5000.0
            )

            self.assertEqual(pay_info["jazzcash"]["account_number"], "03009998877")
            self.assertEqual(pay_info["easypaisa"]["account_number"], "03451112233")
            self.assertEqual(pay_info["bank_transfer"]["iban"], "PK12HABB000011223344")
            self.assertIn("03009998877", pay_info["formatted_text"])
            self.assertIn("PK12HABB000011223344", pay_info["formatted_text"])

    def test_handle_payment_query_detection(self):
        """Verifies detection of payment inquiry query and generation of structured payment details."""
        res = WhatsAppService.handle_payment_query_or_deal_closure(
            organization_id=self.org.id,
            sender_phone="923001234567",
            message_text="Aapke payment options kya hain? JazzCash ya bank IBAN bhej dein",
            sender_name="Ahmed"
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertEqual(res["trigger_type"], "payment_inquiry")
        self.assertIn("[Aapka JazzCash Number]", res["message"])
        self.assertIn("[Aapka EasyPaisa Number]", res["message"])
        self.assertIn("[Aapka IBAN Number]", res["message"])

    def test_handle_deal_closure_detection(self):
        """Verifies detection of deal completion query and auto-dispatch of payment instructions."""
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
        self.assertIn("[Aapka IBAN Number]", res["message"])
        self.assertIn("[Aapka JazzCash Number]", res["message"])

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
        self.assertIn("[Aapka JazzCash Number]", sent_body)
        self.assertIn("[Aapka IBAN Number]", sent_body)

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
        self.assertIn("[Aapka EasyPaisa Number]", sent_body)

    def test_api_get_ecommerce_payment_methods(self):
        """Verifies GET /api/v1/ecommerce/payment-methods returns configured payment options."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        resp = self.client.get("/api/v1/ecommerce/payment-methods")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        methods = data["payment_methods"]
        self.assertEqual(methods["jazzcash"]["account_number"], "[Aapka JazzCash Number]")
        self.assertEqual(methods["easypaisa"]["account_number"], "[Aapka EasyPaisa Number]")
        self.assertEqual(methods["bank_transfer"]["iban"], "[Aapka IBAN Number]")

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
        self.assertIn("[Aapka IBAN Number]", call_kwargs["message_text"])


if __name__ == "__main__":
    unittest.main()
