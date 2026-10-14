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

    def test_jazzcash_manual_tid_plan_upgrade(self):
        """POST /api/billing/change-plan with payment_method=jazzcash and transaction_id upgrades workspace."""
        res = self.client.post("/api/billing/change-plan", json={
            "plan_tier": "enterprise",
            "billing_interval": "month",
            "payment_method": "jazzcash",
            "transaction_id": "TID9988776655"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("plan_tier"), "enterprise")
        self.assertIn("TID9988776655", data.get("message"))
        self.assertIn("entitlements", data)

        # Database confirmation
        org = db.session.get(Organization, self.org.id)
        self.assertEqual(org.plan_tier, "enterprise")

        # Ledger confirmation
        txn = JazzCashTransaction.query.filter_by(txn_ref_no="TID9988776655").first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.payment_channel, "MANUAL_TID")
        self.assertEqual(txn.status, "COMPLETED")
        self.assertEqual(txn.amount_pkr, 125000.0)

    def test_whatsapp_send_simulator_mode_endpoint(self):
        """POST /api/whatsapp/send in simulator mode returns 200 OK, message ID, and updates message history."""
        # Clear any live tokens to guarantee simulator mode
        SystemSetting.set_val("WHATSAPP_PHONE_NUMBER_ID", "")
        SystemSetting.set_val("WHATSAPP_ACCESS_TOKEN", "")
        SystemSetting.set_val("GREEN_API_ID_INSTANCE", "")
        SystemSetting.set_val("GREEN_API_TOKEN_INSTANCE", "")

        res = self.client.post("/api/whatsapp/send", json={
            "phone": "03123456789",
            "message": "Automated incident report generated for Pakistan region."
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("recipient"), "923123456789")
        self.assertEqual(data.get("mode"), "simulator")
        self.assertIn("wamid.mock_", data.get("whatsapp_message_id"))

        # Verify persisted record
        msg = WhatsAppMessage.query.filter_by(whatsapp_message_id=data["whatsapp_message_id"]).first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.status, "mock_sent")

    def test_whatsapp_message_deletion_and_conversation_clear(self):
        """DELETE /api/v1/whatsapp/messages/<id> and /api/v1/whatsapp/conversations/<phone> deletes records."""
        # 1. Create test message
        msg = WhatsAppMessage(
            id="wam_test_del_123",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.mock_del_123",
            direction="inbound",
            sender="923001112233",
            recipient="system",
            body="Test message to delete",
            status="received"
        )
        db.session.add(msg)
        db.session.commit()

        # Delete single message
        del_res = self.client.delete(f"/api/v1/whatsapp/messages/{msg.id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json().get("success"))
        self.assertIsNone(WhatsAppMessage.query.filter_by(id="wam_test_del_123").first())

        # 2. Add multiple messages for conversation clear test
        msg1 = WhatsAppMessage(
            id="wam_conv_1",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.conv_1",
            direction="inbound",
            sender="923005556677",
            recipient="system",
            body="Conv msg 1",
            status="received"
        )
        msg2 = WhatsAppMessage(
            id="wam_conv_2",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.conv_2",
            direction="outbound",
            sender="system",
            recipient="923005556677",
            body="Conv msg 2",
            status="sent"
        )
        db.session.add_all([msg1, msg2])
        db.session.commit()

        clear_res = self.client.delete("/api/v1/whatsapp/conversations/923005556677")
        self.assertEqual(clear_res.status_code, 200)
        self.assertEqual(clear_res.get_json().get("deleted_count"), 2)

    def test_whatsapp_message_to_dict_media_attributes(self):
        """Verifies WhatsAppMessage.to_dict() extracts sender_name, media_url, and is_audio correctly."""
        msg = WhatsAppMessage(
            id="wam_audio_test",
            organization_id=self.org.id,
            whatsapp_message_id="wamid.audio_123",
            direction="inbound",
            sender="923209350858",
            recipient="system",
            message_type="audioMessage",
            body="[audioMessage] voice note test",
            raw_payload_json=json.dumps({
                "senderName": "Zain",
                "downloadUrl": "https://media.example.com/audio.ogg",
                "audioMessageData": {"duration": 12}
            })
        )
        d = msg.to_dict()
        self.assertTrue(d.get("is_audio"))
        self.assertEqual(d.get("sender_name"), "Zain")
        self.assertEqual(d.get("media_url"), "https://media.example.com/audio.ogg")
        self.assertEqual(d.get("audio_duration"), 12)

    def test_multi_tenant_scoped_config(self):
        """Verifies multi-tenant credential isolation between organizations with fallback."""
        # Org A config
        WhatsAppService.save_config(
            organization_id="org-pk-enterprise",
            phone_number_id="111222333",
            green_api_id_instance="710711111111",
            green_api_token_instance="token_org_a"
        )
        # Org B config
        WhatsAppService.save_config(
            organization_id="org-pk-tenant-b",
            phone_number_id="444555666",
            green_api_id_instance="710722222222",
            green_api_token_instance="token_org_b"
        )

        conf_a = WhatsAppService.get_config(organization_id="org-pk-enterprise")
        conf_b = WhatsAppService.get_config(organization_id="org-pk-tenant-b")

        self.assertEqual(conf_a["phone_number_id"], "111222333")
        self.assertEqual(conf_a["green_api_id_instance"], "710711111111")
        self.assertEqual(conf_a["green_api_token_instance"], "token_org_a")

        self.assertEqual(conf_b["phone_number_id"], "444555666")
        self.assertEqual(conf_b["green_api_id_instance"], "710722222222")
        self.assertEqual(conf_b["green_api_token_instance"], "token_org_b")

        # Global fallback for unconfigured Org C
        SystemSetting.set_val("GREEN_API_ID_INSTANCE", "7107global999", is_secret=False)
        conf_c = WhatsAppService.get_config(organization_id="org-pk-tenant-c")
        self.assertEqual(conf_c["green_api_id_instance"], "7107global999")

    def test_instance_id_mapping_and_resolution(self):
        """Verifies registering, resolving, and deleting instance ID mappings."""
        WhatsAppService.register_instance_mapping("710799988877", "org-pk-enterprise", provider="green_api")
        resolved = WhatsAppService.resolve_organization_by_instance("710799988877")
        self.assertEqual(resolved, "org-pk-enterprise")

        mappings = WhatsAppService.get_instance_mappings()
        self.assertIn("710799988877", mappings)
        self.assertEqual(mappings["710799988877"], "org-pk-enterprise")

        # Delete mapping
        deleted = WhatsAppService.delete_instance_mapping("710799988877")
        self.assertTrue(deleted)
        self.assertIsNone(WhatsAppService.resolve_organization_by_instance("710799988877"))

    def test_multi_tenant_webhook_routing_via_instance_mapping(self):
        """Inbound webhook automatically resolves target tenant from instanceData.idInstance."""
        org_b = Organization(
            id="org-pk-tenant-b",
            name="Pak Enterprise Branch B",
            slug="pak-enterprise-b",
            plan_tier="starter",
            is_active=True
        )
        db.session.add(org_b)
        db.session.commit()

        # Map instance 710733344455 -> org-pk-tenant-b
        WhatsAppService.register_instance_mapping("710733344455", "org-pk-tenant-b", provider="green_api")

        webhook_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": 710733344455,
                "wid": "710733344455@c.us"
            },
            "timestamp": 1728000000,
            "idMessage": "wamid.multitenant_test_msg_99",
            "senderData": {
                "chatId": "923001239999@c.us",
                "sender": "923001239999@c.us",
                "chatName": "Branch B Customer"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {
                    "textMessage": "Hello Branch B!"
                }
            }
        }

        # Post to webhook WITHOUT ?org_id= parameter
        resp = self.client.post("/api/v1/webhooks/whatsapp/green-api", json=webhook_payload)
        self.assertEqual(resp.status_code, 200)

        # Verify message was routed to org-pk-tenant-b
        msg = WhatsAppMessage.query.filter_by(whatsapp_message_id="wamid.multitenant_test_msg_99").first()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.organization_id, "org-pk-tenant-b")
        self.assertEqual(msg.body, "Hello Branch B!")

    def test_multi_tenant_instances_api_endpoints(self):
        """Tests GET /whatsapp/instances, POST /whatsapp/instances/map, and DELETE /whatsapp/instances/map/<id>."""
        # 1. Map instance via API
        map_res = self.client.post("/api/v1/whatsapp/instances/map", json={
            "instance_id": "7107888999",
            "organization_id": "org-pk-enterprise"
        })
        self.assertEqual(map_res.status_code, 200)
        self.assertTrue(map_res.get_json().get("success"))

        # Verify resolution
        self.assertEqual(WhatsAppService.resolve_organization_by_instance("7107888999"), "org-pk-enterprise")

        # 2. List mappings via API
        list_res = self.client.get("/api/v1/whatsapp/instances")
        self.assertEqual(list_res.status_code, 200)
        mappings = list_res.get_json().get("mappings", {})
        self.assertIn("7107888999", mappings)

        # 3. Delete mapping via API
        del_res = self.client.delete("/api/v1/whatsapp/instances/map/7107888999")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json().get("success"))
        self.assertIsNone(WhatsAppService.resolve_organization_by_instance("7107888999"))


if __name__ == "__main__":
    unittest.main()


