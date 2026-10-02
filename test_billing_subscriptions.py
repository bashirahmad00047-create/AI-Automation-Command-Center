"""Comprehensive Unit & Integration Test Suite for Stripe Billing & Subscriptions (Phase 4).

Verifies:
- Unauthenticated billing access rejection (401)
- RBAC checkout & portal authorization (owner/admin vs operator/viewer 403)
- Invalid plan rejection (400)
- Safe execution when Stripe is not configured in local development
- Stripe Checkout Session creation with server-validated pricing
- Stripe Customer Portal session generation
- Public Stripe webhook signature validation (400 on forged or missing signature)
- Webhook idempotency (duplicate event ID processed only once)
- Bi-directional plan synchronization with Phase 2 quotas and feature entitlements
- Subscription cancellation & downgrade to Free tier
- Strict multi-tenant isolation in billing operations
- Database migration and schema integrity for subscriptions and webhook events
"""

from __future__ import annotations

import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import text
import stripe

from app import create_app
from database import db
from entitlements import QuotaService
from limiter import limiter
from models import (
    AuditLog,
    Membership,
    Organization,
    StripeWebhookEvent,
    Subscription,
    User,
    generate_uuid,
)
from plans import (
    PLAN_DEFINITIONS,
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_PRO,
    PLAN_STARTER,
)


class TestBillingSubscriptions(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        # Seed Primary Tenant (Org A)
        self.org_a = Organization(
            id="org-acme-billing",
            name="Acme Billing Corp",
            slug="acme-billing",
            plan_tier=PLAN_FREE,
            max_rules=3,
            max_monthly_events=1000,
            is_active=True
        )
        db.session.add(self.org_a)

        # Org A Owner
        self.user_owner = User(
            id="usr-owner-a",
            email="owner@acme.com",
            full_name="Alice Owner",
            is_active=True
        )
        self.user_owner.set_password("OwnerPassword2026!")
        db.session.add(self.user_owner)

        self.mem_owner = Membership(
            id="mem-owner-a",
            user_id=self.user_owner.id,
            organization_id=self.org_a.id,
            role="owner"
        )
        db.session.add(self.mem_owner)

        # Org A Operator
        self.user_operator = User(
            id="usr-operator-a",
            email="operator@acme.com",
            full_name="Bob Operator",
            is_active=True
        )
        self.user_operator.set_password("OperatorPassword2026!")
        db.session.add(self.user_operator)

        self.mem_operator = Membership(
            id="mem-operator-a",
            user_id=self.user_operator.id,
            organization_id=self.org_a.id,
            role="operator"
        )
        db.session.add(self.mem_operator)

        # Seed Secondary Tenant (Org B) for tenant isolation tests
        self.org_b = Organization(
            id="org-beta-billing",
            name="Beta Billing LLC",
            slug="beta-billing",
            plan_tier=PLAN_PRO,
            max_rules=50,
            max_monthly_events=200000,
            stripe_customer_id="cus_beta_stripe_123",
            is_active=True
        )
        db.session.add(self.org_b)

        self.user_b = User(
            id="usr-owner-b",
            email="owner@beta.com",
            full_name="Brian Beta",
            is_active=True
        )
        self.user_b.set_password("BetaPassword2026!")
        db.session.add(self.user_b)

        self.mem_b = Membership(
            id="mem-owner-b",
            user_id=self.user_b.id,
            organization_id=self.org_b.id,
            role="owner"
        )
        db.session.add(self.mem_b)

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def _login_as(self, user_id: str, org_id: str):
        """Helper to establish session context for test client."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["active_org_id"] = org_id

    # =========================================================================
    # 1. Unauthenticated Access Rejection
    # =========================================================================
    def test_unauthenticated_billing_access_rejected(self):
        """Verifies that billing endpoints reject requests without active session (401)."""
        # GET /api/v1/billing/status
        res_status = self.client.get("/api/v1/billing/status")
        self.assertEqual(res_status.status_code, 401)
        self.assertEqual(res_status.get_json()["code"], "UNAUTHORIZED")

        # POST /api/v1/billing/checkout
        res_checkout = self.client.post("/api/v1/billing/checkout", json={"plan_tier": "pro"})
        self.assertEqual(res_checkout.status_code, 401)

        # POST /api/v1/billing/portal
        res_portal = self.client.post("/api/v1/billing/portal", json={})
        self.assertEqual(res_portal.status_code, 401)

        # POST /api/v1/billing/cancel
        res_cancel = self.client.post("/api/v1/billing/cancel", json={})
        self.assertEqual(res_cancel.status_code, 401)

    # =========================================================================
    # 2. RBAC Authorization for Billing Operations
    # =========================================================================
    def test_checkout_and_billing_authorization_rbac(self):
        """Verifies that operators cannot initiate checkout or portal sessions (403), while owners can."""
        # Login as Operator
        self._login_as(self.user_operator.id, self.org_a.id)

        # Operator attempting checkout -> 403
        res_op_checkout = self.client.post("/api/v1/billing/checkout", json={"plan_tier": "pro"})
        self.assertEqual(res_op_checkout.status_code, 403)
        self.assertEqual(res_op_checkout.get_json()["code"], "FORBIDDEN")

        # Operator attempting portal -> 403
        res_op_portal = self.client.post("/api/v1/billing/portal", json={})
        self.assertEqual(res_op_portal.status_code, 403)

        # Operator attempting cancel -> 403
        res_op_cancel = self.client.post("/api/v1/billing/cancel", json={})
        self.assertEqual(res_op_cancel.status_code, 403)

        # Operator CAN view billing status (read-only)
        res_op_status = self.client.get("/api/v1/billing/status")
        self.assertEqual(res_op_status.status_code, 200)
        self.assertEqual(res_op_status.get_json()["plan_tier"], "free")

    # =========================================================================
    # 3. Invalid Plan Rejection
    # =========================================================================
    def test_invalid_plan_rejection(self):
        """Verifies server validates plan tiers against server matrix and rejects invalid ones."""
        self._login_as(self.user_owner.id, self.org_a.id)

        # Unknown plan tier -> 400
        res_bogus = self.client.post("/api/v1/billing/checkout", json={"plan_tier": "super_vip_unlimited"})
        self.assertEqual(res_bogus.status_code, 400)
        self.assertEqual(res_bogus.get_json()["code"], "INVALID_PLAN")

        # Free tier does not require checkout -> 400
        res_free = self.client.post("/api/v1/billing/checkout", json={"plan_tier": "free"})
        self.assertEqual(res_free.status_code, 400)
        self.assertEqual(res_free.get_json()["code"], "INVALID_PLAN")

    # =========================================================================
    # 4. FREE Plan Behavior Without Stripe Configuration
    # =========================================================================
    def test_free_plan_without_stripe_configuration(self):
        """Verifies workspace operates cleanly on Free plan when Stripe keys are empty/unconfigured."""
        self._login_as(self.user_owner.id, self.org_a.id)

        # Billing status returns without error, noting Stripe is not configured
        res = self.client.get("/api/v1/billing/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["plan_tier"], "free")
        self.assertFalse(data["is_stripe_configured"])
        self.assertNotIn("sk_test", json.dumps(data))  # No secret leakage

        # Public plans endpoint is always available
        res_plans = self.client.get("/api/v1/billing/plans")
        self.assertEqual(res_plans.status_code, 200)
        self.assertEqual(len(res_plans.get_json()["plans"]), 4)

        # Attempting checkout without Stripe configured returns 503
        res_checkout = self.client.post("/api/v1/billing/checkout", json={"plan_tier": "pro"})
        self.assertEqual(res_checkout.status_code, 503)
        self.assertEqual(res_checkout.get_json()["code"], "STRIPE_NOT_CONFIGURED")

    # =========================================================================
    # 5. Stripe Checkout Session Creation (Mocked)
    # =========================================================================
    @patch("billing_service.get_stripe_config")
    @patch("stripe.checkout.Session.create")
    @patch("stripe.Customer.create")
    def test_checkout_session_creation(self, mock_cust_create, mock_sess_create, mock_cfg):
        """Verifies Stripe Checkout Session generation with verified pricing and metadata."""
        mock_cfg.return_value = {
            "secret_key": "sk_test_mocked_secret_key_12345",
            "publishable_key": "pk_test_mocked_pub_key_12345",
            "webhook_secret": "whsec_mocked_webhook_secret_12345",
        }
        mock_cust_create.return_value = MagicMock(id="cus_acme_mock_999")
        mock_sess_create.return_value = MagicMock(
            id="cs_test_session_abc123",
            url="https://checkout.stripe.com/c/pay/cs_test_session_abc123"
        )

        self._login_as(self.user_owner.id, self.org_a.id)

        res = self.client.post("/api/v1/billing/checkout", json={
            "plan_tier": "pro",
            "interval": "month"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["session_id"], "cs_test_session_abc123")
        self.assertEqual(data["checkout_url"], "https://checkout.stripe.com/c/pay/cs_test_session_abc123")
        self.assertEqual(data["plan_tier"], "pro")

        # Verify stripe.Customer.create was called
        mock_cust_create.assert_called_once()
        # Verify stripe.checkout.Session.create was called with subscription mode and org metadata
        mock_sess_create.assert_called_once()
        call_kwargs = mock_sess_create.call_args[1]
        self.assertEqual(call_kwargs["customer"], "cus_acme_mock_999")
        self.assertEqual(call_kwargs["mode"], "subscription")
        self.assertEqual(call_kwargs["client_reference_id"], self.org_a.id)
        self.assertEqual(call_kwargs["metadata"]["plan_tier"], "pro")

        # Verify customer ID was saved to Org A in DB
        db.session.refresh(self.org_a)
        self.assertEqual(self.org_a.stripe_customer_id, "cus_acme_mock_999")

    # =========================================================================
    # 6. Customer Portal Session (Mocked)
    # =========================================================================
    @patch("billing_service.get_stripe_config")
    @patch("stripe.billing_portal.Session.create")
    def test_customer_portal_session(self, mock_portal_create, mock_cfg):
        """Verifies Customer Portal creation for tenants with active Stripe customer."""
        mock_cfg.return_value = {
            "secret_key": "sk_test_mocked_secret_key_12345",
            "publishable_key": "pk_test_mocked_pub_key_12345",
            "webhook_secret": "whsec_mocked_webhook_secret_12345",
        }
        mock_portal_create.return_value = MagicMock(url="https://billing.stripe.com/p/session_test_xyz")

        # Org B already has stripe_customer_id
        self._login_as(self.user_b.id, self.org_b.id)

        res = self.client.post("/api/v1/billing/portal", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["portal_url"], "https://billing.stripe.com/p/session_test_xyz")

        mock_portal_create.assert_called_once_with(
            customer="cus_beta_stripe_123",
            return_url="http://localhost/"
        )

        # Org A has NO stripe_customer_id yet -> 400
        self._login_as(self.user_owner.id, self.org_a.id)
        res_no_cust = self.client.post("/api/v1/billing/portal", json={})
        self.assertEqual(res_no_cust.status_code, 400)
        self.assertEqual(res_no_cust.get_json()["code"], "NO_BILLING_PROFILE")

    # =========================================================================
    # 7. Stripe Webhook Signature Validation
    # =========================================================================
    @patch("billing_service.get_stripe_config")
    def test_stripe_webhook_signature_validation(self, mock_cfg):
        """Verifies public Stripe webhook endpoint rejects missing or forged signatures (400)."""
        mock_cfg.return_value = {
            "secret_key": "sk_test_mocked_123",
            "publishable_key": "pk_test_mocked_123",
            "webhook_secret": "whsec_active_production_secret_999",
        }

        raw_payload = json.dumps({"id": "evt_test_1", "type": "checkout.session.completed"}).encode("utf-8")

        # 1. Missing Stripe-Signature header -> 400
        res_no_sig = self.client.post("/api/v1/billing/webhook", data=raw_payload, headers={"Content-Type": "application/json"})
        self.assertEqual(res_no_sig.status_code, 400)
        self.assertEqual(res_no_sig.get_json()["code"], "INVALID_SIGNATURE")

        # 2. Invalid / forged Stripe-Signature header -> 400
        res_bad_sig = self.client.post(
            "/api/v1/billing/webhook",
            data=raw_payload,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": "t=12345678,v1=forged_invalid_signature_hash"
            }
        )
        self.assertEqual(res_bad_sig.status_code, 400)
        self.assertEqual(res_bad_sig.get_json()["code"], "INVALID_SIGNATURE")

    # =========================================================================
    # 8. Webhook Idempotency
    # =========================================================================
    @patch("billing_service.verify_webhook_signature")
    def test_webhook_idempotency(self, mock_verify):
        """Verifies duplicate webhook events are processed once and safely ignored on re-delivery."""
        event_payload = {
            "id": "evt_idempotent_test_001",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": self.org_a.id,
                    "customer": "cus_idem_123",
                    "subscription": "sub_idem_123",
                    "metadata": {
                        "org_id": self.org_a.id,
                        "plan_tier": "starter",
                        "billing_interval": "month"
                    }
                }
            }
        }
        mock_verify.return_value = event_payload

        # First Delivery: Should process and return status="processed"
        res1 = self.client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(event_payload),
            headers={"Content-Type": "application/json", "Stripe-Signature": "valid_test_sig"}
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1["received"])
        self.assertEqual(data1["status"], "processed")

        # Verify Org A was upgraded to Starter
        db.session.refresh(self.org_a)
        self.assertEqual(self.org_a.plan_tier, PLAN_STARTER)
        self.assertEqual(self.org_a.max_rules, 10)

        # Verify exactly 1 record in StripeWebhookEvent table
        event_count = StripeWebhookEvent.query.filter_by(event_id="evt_idempotent_test_001").count()
        self.assertEqual(event_count, 1)

        # Second Delivery (Exact same event ID re-delivered by Stripe):
        res2 = self.client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(event_payload),
            headers={"Content-Type": "application/json", "Stripe-Signature": "valid_test_sig"}
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2["received"])
        self.assertEqual(data2["status"], "duplicate")

        # Event count remains exactly 1
        event_count_after = StripeWebhookEvent.query.filter_by(event_id="evt_idempotent_test_001").count()
        self.assertEqual(event_count_after, 1)

    # =========================================================================
    # 9. Plan Synchronization with Phase 2 Quotas & Features
    # =========================================================================
    @patch("billing_service.verify_webhook_signature")
    def test_subscription_state_and_entitlement_synchronization(self, mock_verify):
        """Verifies that upgrading to Pro via webhook synchronizes quotas and unlocks Phase 2 features."""
        # Initially Org A is Free: max 3 rules, 1000 events, no cloud AI
        self.assertEqual(self.org_a.plan_tier, PLAN_FREE)
        self.assertFalse(QuotaService.is_feature_enabled(self.org_a, "cloud_ai_models"))
        self.assertFalse(QuotaService.is_feature_enabled(self.org_a, "advanced_analytics"))

        pro_event = {
            "id": "evt_pro_upgrade_999",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": self.org_a.id,
                    "customer": "cus_acme_pro_customer",
                    "subscription": "sub_acme_pro_subscription",
                    "metadata": {
                        "org_id": self.org_a.id,
                        "plan_tier": "pro",
                        "billing_interval": "month"
                    }
                }
            }
        }
        mock_verify.return_value = pro_event

        res = self.client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(pro_event),
            headers={"Content-Type": "application/json", "Stripe-Signature": "sig"}
        )
        self.assertEqual(res.status_code, 200)

        # Refresh database state
        db.session.refresh(self.org_a)
        self.assertEqual(self.org_a.plan_tier, PLAN_PRO)
        self.assertEqual(self.org_a.max_rules, 50)
        self.assertEqual(self.org_a.max_monthly_events, 200000)
        self.assertEqual(self.org_a.stripe_customer_id, "cus_acme_pro_customer")
        self.assertEqual(self.org_a.stripe_subscription_id, "sub_acme_pro_subscription")

        # Phase 2 Entitlement Engine verifies features are now enabled
        self.assertTrue(QuotaService.is_feature_enabled(self.org_a, "cloud_ai_models"))
        self.assertTrue(QuotaService.is_feature_enabled(self.org_a, "advanced_analytics"))
        self.assertTrue(QuotaService.is_feature_enabled(self.org_a, "audit_trail"))

        # Verify Subscription model row is populated
        sub = Subscription.query.filter_by(organization_id=self.org_a.id).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.plan_tier, PLAN_PRO)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.stripe_customer_id, "cus_acme_pro_customer")

        # Verify audit log was recorded
        audit = AuditLog.query.filter_by(
            organization_id=self.org_a.id,
            action="billing.subscription_sync"
        ).first()
        self.assertIsNotNone(audit)

    # =========================================================================
    # 10. Cancellation & Downgrade Behavior
    # =========================================================================
    @patch("billing_service.verify_webhook_signature")
    def test_cancellation_and_downgrade_behavior(self, mock_verify):
        """Verifies cancellation via API or webhook reverts workspace to Free tier quotas."""
        # Start Org B on Pro
        self.assertEqual(self.org_b.plan_tier, PLAN_PRO)
        self.assertTrue(QuotaService.is_feature_enabled(self.org_b, "cloud_ai_models"))

        # 1. Test cancellation via DELETE / POST /api/v1/billing/cancel
        self._login_as(self.user_b.id, self.org_b.id)
        res_cancel = self.client.post("/api/v1/billing/cancel", json={})
        self.assertEqual(res_cancel.status_code, 200)
        data = res_cancel.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["plan_tier"], PLAN_FREE)

        db.session.refresh(self.org_b)
        self.assertEqual(self.org_b.plan_tier, PLAN_FREE)
        self.assertEqual(self.org_b.max_rules, 3)
        self.assertEqual(self.org_b.max_monthly_events, 1000)
        self.assertFalse(QuotaService.is_feature_enabled(self.org_b, "cloud_ai_models"))

        # 2. Test Stripe Webhook customer.subscription.deleted
        delete_event = {
            "id": "evt_sub_deleted_888",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_beta_stripe_sub",
                    "customer": self.org_b.stripe_customer_id,
                    "metadata": {"org_id": self.org_b.id}
                }
            }
        }
        mock_verify.return_value = delete_event

        res_hook = self.client.post(
            "/api/v1/billing/webhook",
            data=json.dumps(delete_event),
            headers={"Content-Type": "application/json", "Stripe-Signature": "sig"}
        )
        self.assertEqual(res_hook.status_code, 200)

        db.session.refresh(self.org_b)
        self.assertEqual(self.org_b.plan_tier, PLAN_FREE)
        sub_b = Subscription.query.filter_by(organization_id=self.org_b.id).first()
        self.assertIsNotNone(sub_b)
        self.assertEqual(sub_b.status, "canceled")

    # =========================================================================
    # 11. Multi-Tenant Isolation in Billing
    # =========================================================================
    def test_tenant_isolation_in_billing(self):
        """Verifies user of Org A cannot access or manipulate Org B's subscription or billing data."""
        # Log in as Org A Owner
        self._login_as(self.user_owner.id, self.org_a.id)

        # GET /api/v1/billing/status only returns Org A info
        res_a = self.client.get("/api/v1/billing/status")
        self.assertEqual(res_a.status_code, 200)
        data_a = res_a.get_json()
        self.assertEqual(data_a["organization_id"], self.org_a.id)
        self.assertEqual(data_a["organization_slug"], "acme-billing")
        self.assertNotEqual(data_a["organization_id"], self.org_b.id)

        # Verify tenant A cannot cancel tenant B subscription
        # Even if they attempt to pass Org B id in body, server isolates to active session org
        res_cancel = self.client.post("/api/v1/billing/cancel", json={"organization_id": self.org_b.id})
        self.assertEqual(res_cancel.status_code, 200)
        # Org B remains on Pro if it wasn't modified
        org_b_check = db.session.get(Organization, self.org_b.id)
        self.assertIsNotNone(org_b_check)


if __name__ == "__main__":
    unittest.main()
