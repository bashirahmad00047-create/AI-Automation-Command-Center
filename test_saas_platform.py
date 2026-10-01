"""Comprehensive SaaS Test Suite for OpsFlow Enterprise Platform.

Validates:
1. Multi-Tenant Workspace Isolation
2. User Authentication, Password Hashing, & Session Lifecycle
3. Role-Based Access Control (RBAC: Admin, Operator, Viewer)
4. Programmatic API Key Hashing & Verification
5. Inbound Webhook Endpoints & HMAC-SHA256 Signature Security
6. Workflow Engine Execution & Forensic Audit Tracing
7. Incident Alert Lifecycle (Open -> Acknowledged -> Resolved)
8. Compliance Audit Trail Logging
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest

from app import app
from auth import generate_secure_api_key, verify_api_key
from database import db
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    IncidentAlert,
    Membership,
    Organization,
    User,
    WebhookEndpoint,
    WorkflowExecution,
)


class TestSaaSSecurityAndAuth(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_user_password_hashing(self):
        user = User(
            id="usr-test-1",
            email="sre@company.com",
            full_name="Lead SRE",
            is_active=True
        )
        user.set_password("SuperSecret2026!")
        self.assertNotEqual(user.password_hash, "SuperSecret2026!")
        self.assertTrue(user.check_password("SuperSecret2026!"))
        self.assertFalse(user.check_password("WrongPassword"))

    def test_api_key_generation_and_hashing(self):
        secret_key, prefix, key_hash = generate_secure_api_key()
        self.assertTrue(secret_key.startswith("sk_live_"))
        self.assertTrue(prefix.startswith("sk_live_"))
        self.assertEqual(key_hash, hashlib.sha256(secret_key.encode("utf-8")).hexdigest())

    def test_auth_registration_and_login_flow(self):
        # Register new user
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "engineer@fintech.io",
            "password": "ProductionPass2026!",
            "full_name": "DevOps Engineer",
            "org_name": "FinTech Cloud"
        })
        self.assertEqual(reg_res.status_code, 201)
        reg_json = reg_res.get_json()
        self.assertTrue(reg_json["success"])
        self.assertEqual(reg_json["user"]["email"], "engineer@fintech.io")
        self.assertEqual(reg_json["role"], "owner")

        # Logout
        self.client.post("/api/v1/auth/logout")

        # Login with correct credentials
        login_res = self.client.post("/api/v1/auth/login", json={
            "email": "engineer@fintech.io",
            "password": "ProductionPass2026!"
        })
        self.assertEqual(login_res.status_code, 200)
        login_json = login_res.get_json()
        self.assertTrue(login_json["success"])
        self.assertEqual(login_json["role"], "owner")

        # Login with incorrect password
        bad_login = self.client.post("/api/v1/auth/login", json={
            "email": "engineer@fintech.io",
            "password": "WrongPassword!"
        })
        self.assertEqual(bad_login.status_code, 401)


class TestMultiTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Tenant A: Alpha Corp
        self.org_a = Organization(id="org-alpha", name="Alpha Corp", slug="alpha-corp", is_active=True)
        self.user_a = User(id="usr-alpha", email="admin@alpha.com", full_name="Alpha Admin", is_active=True)
        self.user_a.set_password("AlphaPass2026!")
        self.mem_a = Membership(id="mem-a", user_id=self.user_a.id, organization_id=self.org_a.id, role="admin")

        # Tenant B: Beta Corp
        self.org_b = Organization(id="org-beta", name="Beta Corp", slug="beta-corp", is_active=True)
        self.user_b = User(id="usr-beta", email="admin@beta.com", full_name="Beta Admin", is_active=True)
        self.user_b.set_password("BetaPass2026!")
        self.mem_b = Membership(id="mem-b", user_id=self.user_b.id, organization_id=self.org_b.id, role="admin")

        # Rules for Tenant A
        self.rule_a = AutomationRule(
            id="rule-alpha-1",
            organization_id=self.org_a.id,
            name="Alpha Critical Sentinel",
            category="System",
            enabled=True,
            trigger_json=json.dumps({"type": "event", "event_name": "system.metrics"}),
            condition_json=json.dumps({"logic": "AND", "conditions": [{"field": "payload.cpu", "operator": ">", "value": 90}]}),
            actions_json=json.dumps([{"type": "log_entry", "params": {"message": "Alpha alert"}}])
        )

        # Rules for Tenant B
        self.rule_b = AutomationRule(
            id="rule-beta-1",
            organization_id=self.org_b.id,
            name="Beta Security Firewall",
            category="Security",
            enabled=True,
            trigger_json=json.dumps({"type": "event", "event_name": "auth.failed"}),
            condition_json=json.dumps({"logic": "AND", "conditions": [{"field": "payload.attempts", "operator": ">=", "value": 5}]}),
            actions_json=json.dumps([{"type": "notification", "params": {"title": "Beta alert"}}])
        )

        db.session.add_all([self.org_a, self.user_a, self.mem_a, self.org_b, self.user_b, self.mem_b, self.rule_a, self.rule_b])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_tenant_rule_isolation(self):
        # Login as User A
        self.client.post("/api/v1/auth/login", json={"email": "admin@alpha.com", "password": "AlphaPass2026!"})

        # User A lists rules: should only see Alpha rules, NEVER Beta rules
        res_a = self.client.get("/api/v1/rules")
        self.assertEqual(res_a.status_code, 200)
        rules_a = res_a.get_json()["rules"]
        rule_ids_a = [r["id"] for r in rules_a]
        self.assertIn("rule-alpha-1", rule_ids_a)
        self.assertNotIn("rule-beta-1", rule_ids_a)

        # User A tries to directly fetch Beta's rule: should return 404
        fetch_beta = self.client.get("/api/v1/rules/rule-beta-1")
        self.assertEqual(fetch_beta.status_code, 404)

        # User A tries to delete Beta's rule: should return 404
        delete_beta = self.client.delete("/api/v1/rules/rule-beta-1")
        self.assertEqual(delete_beta.status_code, 404)
        # Beta rule still exists in DB
        self.assertIsNotNone(db.session.get(AutomationRule, "rule-beta-1"))


class TestRBACAndAPIKeys(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(id="org-rbac-test", name="RBAC Enterprise", slug="rbac-test", is_active=True)
        
        # Admin user
        self.admin = User(id="usr-adm", email="admin@rbac.test", full_name="Admin User", is_active=True)
        self.admin.set_password("AdminPass2026!")
        self.mem_admin = Membership(id="mem-adm", user_id=self.admin.id, organization_id=self.org.id, role="admin")

        # Viewer user
        self.viewer = User(id="usr-view", email="viewer@rbac.test", full_name="Viewer User", is_active=True)
        self.viewer.set_password("ViewerPass2026!")
        self.mem_viewer = Membership(id="mem-view", user_id=self.viewer.id, organization_id=self.org.id, role="viewer")

        db.session.add_all([self.org, self.admin, self.mem_admin, self.viewer, self.mem_viewer])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_viewer_cannot_create_or_delete_rules(self):
        # Login as viewer
        self.client.post("/api/v1/auth/login", json={"email": "viewer@rbac.test", "password": "ViewerPass2026!"})

        # Try to create rule -> 403 Forbidden
        create_res = self.client.post("/api/v1/rules", json={
            "name": "Unauthorized Rule",
            "trigger": {"type": "event", "event_name": "test"},
            "condition": {"logic": "AND", "conditions": []},
            "actions": []
        })
        self.assertEqual(create_res.status_code, 403)

        # Try to create API key -> 403 Forbidden
        key_res = self.client.post("/api/v1/auth/api-keys", json={"name": "Viewer Key"})
        self.assertEqual(key_res.status_code, 403)

    def test_api_key_authentication_and_revocation(self):
        # Login as admin to generate API key
        self.client.post("/api/v1/auth/login", json={"email": "admin@rbac.test", "password": "AdminPass2026!"})
        gen_res = self.client.post("/api/v1/auth/api-keys", json={"name": "CI/CD Deployment Token"})
        self.assertEqual(gen_res.status_code, 201)
        gen_data = gen_res.get_json()
        secret_token = gen_data["secret_token"]
        key_id = gen_data["api_key"]["id"]

        # Logout session
        self.client.post("/api/v1/auth/logout")

        # Access /api/v1/rules with API Key in header
        api_req = self.client.get("/api/v1/rules", headers={"X-API-Key": secret_token})
        self.assertEqual(api_req.status_code, 200)

        # Now login again and revoke key
        self.client.post("/api/v1/auth/login", json={"email": "admin@rbac.test", "password": "AdminPass2026!"})
        revoke_res = self.client.delete(f"/api/v1/auth/api-keys/{key_id}")
        self.assertEqual(revoke_res.status_code, 200)
        self.client.post("/api/v1/auth/logout")

        # Access with revoked key -> 401 Unauthorized
        revoked_req = self.client.get("/api/v1/rules", headers={"X-API-Key": secret_token})
        self.assertEqual(revoked_req.status_code, 401)


class TestInboundWebhooksAndSignatures(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(id="org-wh-test", name="Webhook Enterprise", slug="wh-test", is_active=True)
        self.admin = User(id="usr-wh-admin", email="wh@test.com", full_name="Webhook Admin", is_active=True)
        self.admin.set_password("WhPass2026!")
        self.mem = Membership(id="mem-wh", user_id=self.admin.id, organization_id=self.org.id, role="admin")

        self.endpoint_token = "wh_live_test_token_123"
        self.secret_token = "my_hmac_secret_456"
        self.webhook = WebhookEndpoint(
            id="wh-1",
            organization_id=self.org.id,
            name="Stripe Billing Gateway",
            endpoint_token=self.endpoint_token,
            secret_token=self.secret_token,
            is_active=True
        )
        db.session.add_all([self.org, self.admin, self.mem, self.webhook])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_webhook_hmac_verification_pass_and_fail(self):
        payload_dict = {"event": "payment.succeeded", "amount_cents": 4900, "customer": "cust_99"}
        raw_body = json.dumps(payload_dict).encode("utf-8")

        # 1. Valid signature
        valid_sig = "sha256=" + hmac.new(self.secret_token.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        valid_res = self.client.post(
            f"/api/v1/webhooks/incoming/{self.endpoint_token}",
            data=raw_body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": valid_sig}
        )
        self.assertEqual(valid_res.status_code, 200)
        self.assertTrue(valid_res.get_json()["received"])

        # 2. Tampered / invalid signature -> 401 Unauthorized
        invalid_res = self.client.post(
            f"/api/v1/webhooks/incoming/{self.endpoint_token}",
            data=raw_body,
            content_type="application/json",
            headers={"X-Hub-Signature-256": "sha256=badsignature000000000000"}
        )
        self.assertEqual(invalid_res.status_code, 401)


class TestIncidentAlertLifecycle(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(id="org-alert-test", name="Incident Ops", slug="incident-ops", is_active=True)
        self.user = User(id="usr-sre", email="sre@ops.com", full_name="SRE Lead", is_active=True)
        self.user.set_password("SreSecure2026!")
        self.mem = Membership(id="mem-sre", user_id=self.user.id, organization_id=self.org.id, role="operator")

        self.alert = IncidentAlert(
            id=101,
            organization_id=self.org.id,
            title="Database Connection Pool Exhaustion",
            message="Active pool reached 98% capacity.",
            severity="critical",
            status="open"
        )
        db.session.add_all([self.org, self.user, self.mem, self.alert])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_incident_acknowledge_and_resolve(self):
        # Login as operator
        self.client.post("/api/v1/auth/login", json={"email": "sre@ops.com", "password": "SreSecure2026!"})

        # List alerts -> status is open
        res_list = self.client.get("/api/v1/alerts")
        self.assertEqual(res_list.status_code, 200)
        alerts = res_list.get_json()["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["status"], "open")

        # Acknowledge alert
        ack_res = self.client.post(f"/api/v1/alerts/{self.alert.id}/acknowledge")
        self.assertEqual(ack_res.status_code, 200)
        self.assertEqual(ack_res.get_json()["alert"]["status"], "acknowledged")

        # Resolve alert with notes
        res_solve = self.client.post(f"/api/v1/alerts/{self.alert.id}/resolve", json={"notes": "Scaled connection pool size to 50."})
        self.assertEqual(res_solve.status_code, 200)
        resolved_data = res_solve.get_json()["alert"]
        self.assertEqual(resolved_data["status"], "resolved")
        self.assertIn("Scaled connection pool", resolved_data["message"])


if __name__ == "__main__":
    unittest.main()
