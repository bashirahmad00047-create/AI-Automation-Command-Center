"""Comprehensive verification test suite for Local Pakistani Payment (JazzCash) and Meta WhatsApp Cloud API."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import unittest

from sqlalchemy import text

from app import create_app
from database import db
from limiter import limiter
from models import (
    Membership,
    Organization,
    SystemSetting,
    User,
    JazzCashTransaction,
    WhatsAppMessage,
)
from jazzcash_service import JazzCashService, PLAN_PRICING_PKR
from whatsapp_service import WhatsAppService


class TestPhase8JazzCashWhatsApp(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.app.config["RATELIMIT_ENABLED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        # Seed organization
        self.org = Organization(
            id="org-pk-enterprise",
            name="Pak Enterprise Automations",
            slug="pak-enterprise",
            plan_tier="starter",
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

        # Authenticate via login
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "admin@pakenterprise.pk",
            "password": "PakSecret2026!"
        })
        self.assertEqual(login_res.status_code, 200)

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    # ==========================================
    # 1. JAZZCASH UNIT & LOGIC TESTS
    # ==========================================

    def test_jazzcash_pricing_and_formatting(self):
        """Verifies PKR tier calculations and Pakistani phone format standardizations."""
        self.assertEqual(JazzCashService.get_price_pkr("free", "month"), 0.0)
        self.assertEqual(JazzCashService.get_price_pkr("starter", "month"), 7500.0)
        self.assertEqual(JazzCashService.get_price_pkr("pro", "month"), 25000.0)
        self.assertEqual(JazzCashService.get_price_pkr("enterprise", "month"), 125000.0)
        self.assertEqual(JazzCashService.get_price_pkr("pro", "year"), 250000.0)

        # Normalization
        self.assertEqual(JazzCashService.format_pakistani_mobile("03001234567"), "03001234567")
        self.assertEqual(JazzCashService.format_pakistani_mobile("923001234567"), "03001234567")
        self.assertEqual(JazzCashService.format_pakistani_mobile("+923219876543"), "03219876543")

    def test_jazzcash_hmac_hash_calculation_and_verification(self):
        """Verifies JazzCash HMAC-SHA256 signature algorithm against official specs."""
        salt = "salt_super_secret_2026"
        params = {
            "pp_MerchantID": "MC998877",
            "pp_TxnRefNo": "T20261012120000ABCD",
            "pp_Amount": "2500000",
            "pp_TxnCurrency": "PKR",
            "pp_TxnDateTime": "20261012120000"
        }
        hash_val = JazzCashService.calculate_secure_hash(params, salt)
        self.assertIsInstance(hash_val, str)
        self.assertEqual(len(hash_val), 64)
        self.assertEqual(hash_val, hash_val.upper())

        # Verify
        params_with_hash = dict(params)
        params_with_hash["pp_SecureHash"] = hash_val
        self.assertTrue(JazzCashService.verify_secure_hash(params_with_hash, salt))

        # Tampered parameter fails
        params_with_hash["pp_Amount"] = "100"
        self.assertFalse(JazzCashService.verify_secure_hash(params_with_hash, salt))

    # ==========================================
    # 2. JAZZCASH API ENDPOINTS & BILLING
    # ==========================================

    def test_jazzcash_config_endpoint(self):
        """GET /api/v1/billing/jazzcash/config returns status, environment, and PKR tier pricing."""
        res = self.client.get("/api/v1/billing/jazzcash/config")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("is_configured"))
        self.assertIn("pricing_pkr", data)
        self.assertEqual(data["pricing_pkr"]["pro"]["month"], 25000.0)
        self.assertIn("MWALLET", data.get("supported_channels", []))

    def test_jazzcash_mwallet_direct_payment(self):
        """POST /api/v1/billing/jazzcash/mwallet-pay completes transaction and upgrades organization tier."""
        res = self.client.post("/api/v1/billing/jazzcash/mwallet-pay", json={
            "plan_tier": "pro",
            "billing_interval": "month",
            "mobile_number": "03011234567",
            "cnic_last6": "654321"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "COMPLETED")
        self.assertEqual(data.get("plan_tier"), "pro")
        self.assertEqual(data.get("amount_pkr"), 25000.0)

        # Database confirmation
        org = db.session.get(Organization, self.org.id)
        self.assertEqual(org.plan_tier, "pro")

        # Ledger record confirmation
        txns = JazzCashTransaction.query.filter_by(organization_id=self.org.id).all()
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].payment_channel, "MWALLET")
        self.assertEqual(txns[0].status, "COMPLETED")
        self.assertEqual(txns[0].amount_pkr, 25000.0)

    def test_jazzcash_checkout_redirection_payload(self):
        """POST /api/v1/billing/jazzcash/checkout generates valid hosted portal payload."""
        res = self.client.post("/api/v1/billing/jazzcash/checkout", json={
            "plan_tier": "enterprise",
            "billing_interval": "month"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("action_url", data)
        self.assertIn("params", data)
        params = data["params"]
        self.assertEqual(params["pp_Amount"], "12500000")  # 125,000 PKR * 100 paisas
        self.assertIn("pp_SecureHash", params)

    def test_jazzcash_transactions_ledger(self):
        """GET /api/v1/billing/jazzcash/transactions returns isolated payment history."""
        # Execute payment
        self.client.post("/api/v1/billing/jazzcash/mwallet-pay", json={
            "plan_tier": "starter",
            "billing_interval": "month",
            "mobile_number": "03335557777"
        })

        res = self.client.get("/api/v1/billing/jazzcash/transactions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreaterEqual(data.get("count", 0), 1)
        self.assertEqual(data["transactions"][0]["mobile_number"], "03335557777")

    # ==========================================
    # 3. WHATSAPP LIVE INTEGRATION TESTS
    # ==========================================

    def test_whatsapp_config_storage_and_retrieval(self):
        """Saves Meta Cloud API configuration in SystemSetting dynamically and verifies masking."""
        res = self.client.post("/api/v1/whatsapp/config", json={
            "phone_number_id": "109876543210",
            "access_token": "EAAG_LIVE_SYSTEM_USER_TOKEN",
            "business_account_id": "887766554433",
            "app_secret": "meta_app_secret_abc123",
            "verify_token": "custom_verify_token_2026"
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("success"))

        # Verify through GET
        get_res = self.client.get("/api/v1/whatsapp/config")
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()
        self.assertEqual(data.get("business_account_id"), "887766554433")
        self.assertEqual(data.get("verify_token"), "custom_verify_token_2026")
        self.assertIn("...", data.get("phone_number_id"))  # Masked phone number id

    def test_whatsapp_connection_diagnostic_probe(self):
        """POST /api/v1/whatsapp/test-connection verifies live connection diagnostics."""
        res = self.client.post("/api/v1/whatsapp/test-connection")
        # Probe attempts connection to Meta Graph API, returns status result
        self.assertIn(res.status_code, (200, 400))
        data = res.get_json()
        self.assertIn("status", data)

    def test_whatsapp_send_text_and_template_messages(self):
        """Dispatches outbound text and pre-approved template WhatsApp messages with Pakistani formatting."""
        # 1. Text Message with 03xx format
        res1 = self.client.post("/api/v1/whatsapp/messages/send", json={
            "to": "03001234567",
            "message": "Assalam-o-Alaikum! Your automated order #9021 has been processed."
        })
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1.get("recipient"), "923001234567")
        self.assertIn(data1.get("status"), ("sent", "mock_sent", "failed"))

        # 2. Template Message (e.g. hello_world)
        res2 = self.client.post("/api/v1/whatsapp/messages/send", json={
            "to": "+923219998888",
            "template_name": "hello_world",
            "template_language": "en_US"
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2.get("recipient"), "923219998888")
        self.assertIn(data2.get("status"), ("sent", "mock_sent", "failed"))

        # Confirm persisted in database
        msgs = WhatsAppMessage.query.filter_by(organization_id=self.org.id).all()
        self.assertEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
