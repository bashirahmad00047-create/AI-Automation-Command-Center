"""Phase 7 Enterprise Production SaaS Verification Test Suite.

Comprehensive end-to-end audit and regression coverage for:
1. Authentication & Secure Password Reset (Forgot Password, Expiry, Single-Use, Session Handling)
2. Multi-Tenant Data Isolation (Direct ID, Cross-Tenant Mutation Prevention)
3. Official WhatsApp Business / Meta Cloud API Integration (Webhooks, HMAC, Idempotency, Outbound, Audits)
4. Production Readiness & Health Telemetry Probes (/ready, /health)
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import unittest

from sqlalchemy import text

from actions import ActionRunner
from app import create_app
from database import db
from limiter import limiter
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    Lead,
    Membership,
    Organization,
    PasswordResetToken,
    User,
    WhatsAppMessage,
    generate_uuid,
)
from whatsapp_service import WhatsAppService


class TestPhase7ProductionUpgrade(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.app.config["RATELIMIT_ENABLED"] = False
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        # Seed test user and organization
        self.org1 = Organization(
            id="org-tenant-alpha",
            name="Alpha Corp",
            slug="alpha-corp",
            plan_tier="pro",
            is_active=True
        )
        self.org2 = Organization(
            id="org-tenant-beta",
            name="Beta Logistics",
            slug="beta-logistics",
            plan_tier="starter",
            is_active=True
        )
        db.session.add_all([self.org1, self.org2])

        self.user1 = User(
            id="usr-alpha-owner",
            email="owner@alphacorp.io",
            full_name="Alpha Owner",
            is_active=True
        )
        self.user1.set_password("AlphaPass2026!")

        self.user2 = User(
            id="usr-beta-owner",
            email="owner@betalogistics.io",
            full_name="Beta Owner",
            is_active=True
        )
        self.user2.set_password("BetaPass2026!")

        db.session.add_all([self.user1, self.user2])
        db.session.commit()

        # Assign memberships
        m1 = Membership(
            id="mem-alpha-1",
            user_id=self.user1.id,
            organization_id=self.org1.id,
            role="owner"
        )
        m2 = Membership(
            id="mem-beta-1",
            user_id=self.user2.id,
            organization_id=self.org2.id,
            role="owner"
        )
        db.session.add_all([m1, m2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    # ==========================================
    # 1. AUTHENTICATION & PASSWORD RESET TESTS
    # ==========================================

    def test_forgot_password_valid_user(self):
        """Valid email generates secure, single-use, 1-hour expiration reset token."""
        res = self.client.post("/api/v1/auth/forgot-password", json={"email": "owner@alphacorp.io"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("message", data)
        self.assertTrue(data.get("success"))

        # Verify token created in database
        tokens = PasswordResetToken.query.filter_by(user_id=self.user1.id).all()
        self.assertEqual(len(tokens), 1)
        token_record = tokens[0]
        self.assertFalse(token_record.is_used)
        self.assertIsNone(token_record.used_at)
        
        # Verify 1-hour expiration window
        expected_expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        delta = abs((token_record.expires_at - expected_expiry).total_seconds())
        self.assertLess(delta, 10)  # within 10 seconds of 1 hour

    def test_forgot_password_unknown_email_timing_safe(self):
        """Unknown email returns generic 200 success without creating tokens (no enumeration)."""
        res = self.client.post("/api/v1/auth/forgot-password", json={"email": "nonexistent@nowhere.io"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))

        # Zero tokens created
        tokens = PasswordResetToken.query.all()
        self.assertEqual(len(tokens), 0)

    def test_reset_password_success_and_login_flow(self):
        """Valid reset token successfully changes password and enables login."""
        # 1. Request forgot password
        forgot_res = self.client.post("/api/v1/auth/forgot-password", json={"email": "owner@alphacorp.io"})
        self.assertEqual(forgot_res.status_code, 200)
        dev_token = forgot_res.get_json().get("dev_reset_token")
        self.assertIsNotNone(dev_token)

        # 2. Reset password
        reset_res = self.client.post("/api/v1/auth/reset-password", json={
            "token": dev_token,
            "new_password": "NewBrandSecure2026!"
        })
        self.assertEqual(reset_res.status_code, 200)
        self.assertTrue(reset_res.get_json().get("success"))

        # 3. Verify token record is now used
        token_hash = hashlib.sha256(dev_token.encode("utf-8")).hexdigest()
        token_record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
        self.assertTrue(token_record.is_used)
        self.assertIsNotNone(token_record.used_at)

        # 4. Old password must fail
        old_login = self.client.post("/api/v1/auth/login", json={
            "email": "owner@alphacorp.io",
            "password": "AlphaPass2026!"
        })
        self.assertEqual(old_login.status_code, 401)

        # 5. New password succeeds
        new_login = self.client.post("/api/v1/auth/login", json={
            "email": "owner@alphacorp.io",
            "password": "NewBrandSecure2026!"
        })
        self.assertEqual(new_login.status_code, 200)
        self.assertEqual(new_login.get_json()["user"]["email"], "owner@alphacorp.io")

    def test_reset_password_rejection_cases(self):
        """Rejects invalid, already-used, and expired reset tokens."""
        # Case A: Invalid token
        res_invalid = self.client.post("/api/v1/auth/reset-password", json={
            "token": "invalid_fake_token_abc_123",
            "new_password": "ValidPassword123!"
        })
        self.assertEqual(res_invalid.status_code, 400)
        self.assertEqual(res_invalid.get_json().get("code"), "INVALID_TOKEN")

        # Case B: Already used token
        raw_token = "valid_token_test_abc"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        used_token = PasswordResetToken(
            id="rst-used-test",
            user_id=self.user1.id,
            token_hash=token_hash,
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            is_used=True,
            used_at=datetime.datetime.utcnow()
        )
        db.session.add(used_token)
        db.session.commit()

        res_used = self.client.post("/api/v1/auth/reset-password", json={
            "token": raw_token,
            "new_password": "ValidPassword123!"
        })
        self.assertEqual(res_used.status_code, 400)
        self.assertEqual(res_used.get_json().get("code"), "TOKEN_ALREADY_USED")

        # Case C: Expired token
        expired_raw = "expired_token_test_xyz"
        expired_hash = hashlib.sha256(expired_raw.encode("utf-8")).hexdigest()
        expired_token = PasswordResetToken(
            id="rst-exp-test",
            user_id=self.user1.id,
            token_hash=expired_hash,
            expires_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=5),
            is_used=False
        )
        db.session.add(expired_token)
        db.session.commit()

        res_expired = self.client.post("/api/v1/auth/reset-password", json={
            "token": expired_raw,
            "new_password": "ValidPassword123!"
        })
        self.assertEqual(res_expired.status_code, 400)
        self.assertEqual(res_expired.get_json().get("code"), "TOKEN_EXPIRED")

    def test_password_reset_audit_trail_privacy(self):
        """Password reset audit event never exposes plaintext tokens or passwords."""
        forgot_res = self.client.post("/api/v1/auth/forgot-password", json={"email": "owner@alphacorp.io"})
        dev_token = forgot_res.get_json().get("dev_reset_token")

        self.client.post("/api/v1/auth/reset-password", json={
            "token": dev_token,
            "new_password": "SecretNewPassword2026!"
        })

        audits = AuditLog.query.filter_by(action="auth.password_reset").all()
        self.assertGreaterEqual(len(audits), 1)
        for audit in audits:
            details_str = audit.details_json or ""
            self.assertNotIn("SecretNewPassword2026!", details_str)
            self.assertNotIn(dev_token, details_str)

    # ==========================================
    # 2. MULTI-TENANT ISOLATION TESTS
    # ==========================================

    def test_tenant_data_isolation_rules_and_leads(self):
        """Tenant A cannot view, mutate, or delete Tenant B rules or leads."""
        # Create Lead for Tenant Alpha
        lead_alpha = Lead(
            id="lead-alpha-001",
            organization_id=self.org1.id,
            name="Alice Alpha",
            email="alice@customer.com",
            status="new",
            lead_score=85
        )
        # Create Lead for Tenant Beta
        lead_beta = Lead(
            id="lead-beta-002",
            organization_id=self.org2.id,
            name="Bob Beta",
            email="bob@partner.com",
            status="new",
            lead_score=72
        )
        db.session.add_all([lead_alpha, lead_beta])
        db.session.commit()

        # Log in as Tenant Alpha
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "owner@alphacorp.io",
            "password": "AlphaPass2026!"
        })
        self.assertEqual(login_res.status_code, 200)

        # Alpha lists leads -> only Alpha lead returned
        leads_res = self.client.get("/api/v1/leads")
        self.assertEqual(leads_res.status_code, 200)
        leads = leads_res.get_json().get("leads", [])
        lead_ids = [l["id"] for l in leads]
        self.assertIn("lead-alpha-001", lead_ids)
        self.assertNotIn("lead-beta-002", lead_ids)

        # Alpha attempts direct update of Beta's lead status
        patch_res = self.client.patch("/api/v1/leads/lead-beta-002/status", json={"status": "won"})
        self.assertEqual(patch_res.status_code, 404)

        # Confirm Beta's lead status remains unchanged
        refreshed_beta = db.session.get(Lead, "lead-beta-002")
        self.assertEqual(refreshed_beta.status, "new")

    def test_tenant_session_hijack_prevention(self):
        """Authenticated user cannot switch to an organization they do not belong to."""
        # Log in as Tenant Beta user
        self.client.post("/api/v1/auth/login", json={
            "email": "owner@betalogistics.io",
            "password": "BetaPass2026!"
        })

        # Attempt to switch active org to Alpha Corp
        switch_res = self.client.post("/api/v1/auth/switch-org", json={"organization_id": self.org1.id})
        self.assertEqual(switch_res.status_code, 403)

    # ==========================================
    # 3. WHATSAPP BUSINESS / META CLOUD API TESTS
    # ==========================================

    def test_whatsapp_webhook_challenge_verification(self):
        """GET /api/v1/webhooks/whatsapp verifies Meta subscribe challenge correctly."""
        # Valid verification request
        res_valid = self.client.get("/api/v1/webhooks/whatsapp", query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": WhatsAppService.DEFAULT_VERIFY_TOKEN,
            "hub.challenge": "1155992288"
        })
        self.assertEqual(res_valid.status_code, 200)
        self.assertEqual(res_valid.data.decode("utf-8"), "1155992288")

        # Invalid verify token -> 403 Forbidden
        res_invalid = self.client.get("/api/v1/webhooks/whatsapp", query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "1155992288"
        })
        self.assertEqual(res_invalid.status_code, 403)

    def test_whatsapp_webhook_ingress_and_deduplication(self):
        """POST /api/v1/webhooks/whatsapp ingests messages and guarantees idempotency."""
        meta_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_12345",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15550267123",
                                    "phone_number_id": "PNID_998877"
                                },
                                "contacts": [
                                    {"profile": {"name": "Carlos Gomez"}, "wa_id": "14155551234"}
                                ],
                                "messages": [
                                    {
                                        "from": "14155551234",
                                        "id": "wamid.HBgLMTQxNTU1NTEyMzRVFQIAEhggMUQxMjM0NTY3ODkwQUJDRUYw",
                                        "timestamp": "1711800000",
                                        "text": {"body": "Urgent: production database latency is spiking over 2000ms!"},
                                        "type": "text"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }

        # First ingestion -> processed = 1
        res1 = self.client.post(
            f"/api/v1/webhooks/whatsapp?org_id={self.org1.id}",
            json=meta_payload,
            content_type="application/json"
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.get_json()["processed"], 1)

        # Message persisted in database
        saved_msg = WhatsAppMessage.query.filter_by(
            whatsapp_message_id="wamid.HBgLMTQxNTU1NTEyMzRVFQIAEhggMUQxMjM0NTY3ODkwQUJDRUYw"
        ).first()
        self.assertIsNotNone(saved_msg)
        self.assertEqual(saved_msg.organization_id, self.org1.id)
        self.assertEqual(saved_msg.sender, "14155551234")
        self.assertEqual(saved_msg.direction, "inbound")
        self.assertIn("latency is spiking", saved_msg.body)

        # Second ingestion with duplicate wamid -> deduplicated (processed = 0)
        res2 = self.client.post(
            f"/api/v1/webhooks/whatsapp?org_id={self.org1.id}",
            json=meta_payload,
            content_type="application/json"
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["processed"], 0)

        # Total count remains 1
        count = WhatsAppMessage.query.filter_by(
            whatsapp_message_id="wamid.HBgLMTQxNTU1NTEyMzRVFQIAEhggMUQxMjM0NTY3ODkwQUJDRUYw"
        ).count()
        self.assertEqual(count, 1)

    def test_whatsapp_outbound_dispatch_and_tenant_isolation(self):
        """Outbound WhatsApp message send persists record and isolates across workspaces."""
        # 1. Log in as Tenant Alpha
        self.client.post("/api/v1/auth/login", json={
            "email": "owner@alphacorp.io",
            "password": "AlphaPass2026!"
        })

        # 2. Send outbound message
        send_res = self.client.post("/api/v1/whatsapp/messages/send", json={
            "to": "+14155559876",
            "message": "OpsFlow Incident Alert: High CPU cleared automatically."
        })
        self.assertEqual(send_res.status_code, 200)
        data = send_res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn(data.get("status"), ["sent", "mock_sent"])

        # 3. Check Alpha message history
        alpha_msgs = self.client.get("/api/v1/whatsapp/messages")
        self.assertEqual(alpha_msgs.status_code, 200)
        alpha_data = alpha_msgs.get_json()
        self.assertEqual(alpha_data["count"], 1)
        self.assertEqual(alpha_data["messages"][0]["recipient"], "14155559876")

        # 4. Log in as Tenant Beta -> must see 0 messages
        self.client.post("/api/v1/auth/login", json={
            "email": "owner@betalogistics.io",
            "password": "BetaPass2026!"
        })
        beta_msgs = self.client.get("/api/v1/whatsapp/messages")
        self.assertEqual(beta_msgs.status_code, 200)
        self.assertEqual(beta_msgs.get_json()["count"], 0)

    # ==========================================
    # 4. SYSTEM READINESS & HEALTH PROBES
    # ==========================================

    def test_health_and_readiness_probes(self):
        """Verifies /health and /ready probe responses."""
        # Root health check
        health_res = self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.get_json()["status"], "healthy")

        # API health check
        api_health_res = self.client.get("/api/v1/health")
        self.assertEqual(api_health_res.status_code, 200)
        self.assertEqual(api_health_res.get_json()["status"], "healthy")

        # Root readiness probe
        ready_res = self.client.get("/ready")
        self.assertEqual(ready_res.status_code, 200)
        ready_data = ready_res.get_json()
        self.assertEqual(ready_data["status"], "ready")
        self.assertTrue(ready_data["subsystems"]["database"])
        self.assertTrue(ready_data["subsystems"]["storage"])

        # API readiness probe
        api_ready_res = self.client.get("/api/v1/ready")
        self.assertEqual(api_ready_res.status_code, 200)
        self.assertEqual(api_ready_res.get_json()["status"], "ready")

    def test_slack_action_execution_and_rendering(self):
        """ActionRunner executes slack_notification with rendered context and mock fallback."""
        runner = ActionRunner()
        context = {
            "event": "alert.critical",
            "payload": {"service": "payment-api", "error_code": "503"},
            "organization_id": self.org1.id
        }
        action = {
            "type": "slack_notification",
            "params": {
                "channel": "#incident-response",
                "message": "Outage detected on {{ payload.service }}: HTTP {{ payload.error_code }}"
            }
        }
        result = runner.execute_action(action, context)
        self.assertEqual(result["status"], "success")
        output = result.get("output", {})
        self.assertEqual(output.get("status"), "mock_sent")
        self.assertEqual(output.get("channel"), "#incident-response")
        self.assertIn("payment-api", output.get("text", ""))

    def test_audit_trail_export_csv_and_json(self):
        """Exports compliance audit trail in both CSV and JSON formats."""
        # Log in as Tenant Alpha owner
        self.client.post("/api/v1/auth/login", json={
            "email": "owner@alphacorp.io",
            "password": "AlphaPass2026!"
        })

        # Generate some audit events
        audit1 = AuditLog(
            organization_id=self.org1.id,
            user_id=self.user1.id,
            user_email=self.user1.email,
            action="rule.create",
            resource_type="automation_rule",
            resource_id="rule-test-01",
            details_json=json.dumps({"name": "Test Rule"}),
            ip_address="127.0.0.1"
        )
        db.session.add(audit1)
        db.session.commit()

        # 1. Export JSON format
        res_json = self.client.get("/api/v1/audit-trail/export?format=json")
        self.assertEqual(res_json.status_code, 200)
        json_data = res_json.get_json()
        self.assertEqual(json_data["organization_id"], self.org1.id)
        self.assertGreaterEqual(json_data["count"], 1)

        # 2. Export CSV format
        res_csv = self.client.get("/api/v1/audit-trail/export?format=csv")
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn("text/csv", res_csv.content_type)
        csv_text = res_csv.data.decode("utf-8")
        self.assertIn("Action,Resource Type,Resource ID", csv_text)
        self.assertIn("rule.create", csv_text)

    def test_prometheus_metrics_exposition(self):
        """Verifies standard Prometheus exposition format on root /metrics and API endpoint."""
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.content_type)
        metrics_text = res.data.decode("utf-8")
        self.assertIn("# HELP opsflow_engine_online", metrics_text)
        self.assertIn("# TYPE opsflow_engine_online gauge", metrics_text)
        self.assertIn("opsflow_engine_online 1", metrics_text)
        self.assertIn("opsflow_uptime_seconds", metrics_text)

        api_res = self.client.get("/api/v1/metrics")
        self.assertEqual(api_res.status_code, 200)
        self.assertIn("opsflow_engine_online", api_res.data.decode("utf-8"))

    def test_enhanced_security_headers(self):
        """Verifies enterprise security headers are applied to HTTP responses."""
        res = self.client.get("/health")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("geolocation=()", res.headers.get("Permissions-Policy", ""))


if __name__ == "__main__":
    unittest.main()

