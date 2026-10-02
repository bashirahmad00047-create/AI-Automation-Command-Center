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

from sqlalchemy import text
from app import create_app
from auth import generate_secure_api_key, verify_api_key
from database import db
from entitlements import (
    PlanEntitlements,
    QuotaService,
    check_ai_provider_entitlement,
    check_feature_entitlement,
    check_resource_quota,
    get_org_entitlements,
)
from limiter import limiter
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    IncidentAlert,
    Lead,
    Membership,
    Organization,
    SystemEvent,
    User,
    WebhookEndpoint,
    WorkflowExecution,
)
from plans import (
    PLAN_DEFINITIONS,
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_PRO,
    PLAN_STARTER,
    get_plan,
    list_plans,
)


class TestSaaSSecurityAndAuth(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
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
        self.app = create_app("testing")
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
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
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
        self.app = create_app("testing")
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
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
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
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

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
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
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
        self.assertEqual(invalid_res.get_json()["code"], "UNAUTHORIZED")

        # 3. Missing signature header when secret is configured -> 401 Unauthorized
        missing_res = self.client.post(
            f"/api/v1/webhooks/incoming/{self.endpoint_token}",
            data=raw_body,
            content_type="application/json"
        )
        self.assertEqual(missing_res.status_code, 401)
        self.assertEqual(missing_res.get_json()["code"], "UNAUTHORIZED")

    def test_webhook_rate_limiting_returns_429(self):
        self.app.config["WEBHOOK_RATE_LIMIT"] = 3
        payload_dict = {"event": "payment.succeeded", "amount_cents": 1000}
        raw_body = json.dumps(payload_dict).encode("utf-8")
        valid_sig = "sha256=" + hmac.new(self.secret_token.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        headers = {"X-Hub-Signature-256": valid_sig}

        # 3 requests succeed
        for _ in range(3):
            res = self.client.post(
                f"/api/v1/webhooks/incoming/{self.endpoint_token}",
                data=raw_body,
                content_type="application/json",
                headers=headers
            )
            self.assertEqual(res.status_code, 200)

        # 4th request exceeds rate limit -> 429
        throttled = self.client.post(
            f"/api/v1/webhooks/incoming/{self.endpoint_token}",
            data=raw_body,
            content_type="application/json",
            headers=headers
        )
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(throttled.get_json()["code"], "TOO_MANY_REQUESTS")
        self.assertIn("Retry-After", throttled.headers)


class TestIncidentAlertLifecycle(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
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
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
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


class TestCRMLeadsAndAutomation(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(id="org-crm-test", name="CRM Enterprise", slug="crm-test", is_active=True)
        self.admin = User(id="usr-crm-admin", email="sales@crm.test", full_name="Sales Director", is_active=True)
        self.admin.set_password("SalesPass2026!")
        self.mem = Membership(id="mem-crm", user_id=self.admin.id, organization_id=self.org.id, role="admin")
        db.session.add_all([self.org, self.admin, self.mem])
        db.session.commit()

        # Login
        self.client.post("/api/v1/auth/login", json={"email": "sales@crm.test", "password": "SalesPass2026!"})

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_lead_ingestion_and_scoring(self):
        res = self.client.post("/api/v1/events/ingest", json={
            "event": "lead.created",
            "name": "Marcus Vance",
            "email": "marcus@enterprise-cloud.io",
            "message": "We have an urgent enterprise requirement with a $75,000 budget for 250 seats.",
            "phone": "+1-800-555-0199"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "completed")

        # Verify Lead in CRM API
        leads_res = self.client.get("/api/v1/leads")
        self.assertEqual(leads_res.status_code, 200)
        leads = leads_res.get_json()["leads"]
        self.assertGreaterEqual(len(leads), 1)
        lead = next(l for l in leads if l["email"] == "marcus@enterprise-cloud.io")
        self.assertGreaterEqual(lead["lead_score"], 60)
        self.assertEqual(lead["route_department"], "Sales")

    def test_lead_status_patching_and_filtering(self):
        lead = Lead(
            id="lead-status-test",
            organization_id=self.org.id,
            name="Alice Walker",
            email="alice@cloudcorp.com",
            message="Looking for integration support.",
            intent="support_request",
            lead_score=50,
            urgency_score=40,
            route_department="Support",
            status="new"
        )
        db.session.add(lead)
        db.session.commit()

        # Patch status to qualified
        patch_res = self.client.patch(f"/api/v1/leads/{lead.id}/status", json={"status": "qualified"})
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.get_json()["lead"]["status"], "qualified")

        # Filter by status
        filter_res = self.client.get("/api/v1/leads?status=qualified")
        self.assertEqual(filter_res.status_code, 200)
        self.assertTrue(any(l["id"] == lead.id for l in filter_res.get_json()["leads"]))

    def test_lead_deletion(self):
        lead = Lead(
            id="lead-del-test",
            organization_id=self.org.id,
            name="Delete Candidate",
            email="del@spam.com",
            message="Spam inquiry",
            status="archived"
        )
        db.session.add(lead)
        db.session.commit()

        del_res = self.client.delete(f"/api/v1/leads/{lead.id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["success"])

        # Ensure deleted from DB
        get_res = self.client.get(f"/api/v1/leads/{lead.id}")
        self.assertEqual(get_res.status_code, 404)


class TestWorkflowAdvancedFeatures(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization(id="org-wf-test", name="Workflow Enterprise", slug="wf-test", is_active=True)
        self.admin = User(id="usr-wf-admin", email="admin@wf.test", full_name="Ops Admin", is_active=True)
        self.admin.set_password("AdminPass2026!")
        self.mem = Membership(id="mem-wf", user_id=self.admin.id, organization_id=self.org.id, role="admin")
        db.session.add_all([self.org, self.admin, self.mem])
        db.session.commit()

        self.client.post("/api/v1/auth/login", json={"email": "admin@wf.test", "password": "AdminPass2026!"})

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_workflow_duplication(self):
        rule = AutomationRule(
            id="rule-to-clone",
            organization_id=self.org.id,
            name="Original Production Pipeline",
            category="DevOps",
            priority=80,
            enabled=True,
            trigger_json='{"type": "event", "event_name": "deploy.pipeline"}',
            condition_json='{"logic": "AND", "conditions": []}',
            actions_json='[{"type": "notification", "params": {"title": "Deploy Alert"}}]'
        )
        db.session.add(rule)
        db.session.commit()

        clone_res = self.client.post(f"/api/v1/workflows/{rule.id}/duplicate")
        self.assertEqual(clone_res.status_code, 201)
        cloned = clone_res.get_json()["workflow"]
        self.assertEqual(cloned["name"], "Original Production Pipeline (Copy)")
        self.assertFalse(cloned["enabled"])

    def test_workflow_dry_run_simulation_mode(self):
        rule = AutomationRule(
            id="rule-simulation-test",
            organization_id=self.org.id,
            name="Simulation Test Rule",
            category="System",
            priority=90,
            enabled=True,
            trigger_json='{"type": "event", "event_name": "system.metrics"}',
            condition_json='{"logic": "AND", "conditions": [{"field": "payload.cpu_percent", "operator": ">", "value": 80}]}',
            actions_json='[{"type": "notification", "params": {"title": "Dry Run Alert"}}]'
        )
        db.session.add(rule)
        db.session.commit()

        initial_exec_count = WorkflowExecution.query.count()

        # Execute in dry-run mode
        exec_res = self.client.post(f"/api/v1/workflows/{rule.id}/execute", json={
            "dry_run": True,
            "payload": {"cpu_percent": 92.0, "host": "srv-prod-sim"}
        })
        self.assertEqual(exec_res.status_code, 200)
        data = exec_res.get_json()
        self.assertTrue(data["is_dry_run"])
        self.assertEqual(data["status"], "success")

        # Verify zero persistent side effects in database
        self.assertEqual(WorkflowExecution.query.count(), initial_exec_count)

    def test_real_database_analytics_summary(self):
        analytics_res = self.client.get("/api/v1/analytics")
        self.assertEqual(analytics_res.status_code, 200)
        analytics = analytics_res.get_json()["analytics"]
        self.assertIn("total_executions", analytics)
        self.assertIn("success_rate", analytics)
        self.assertIn("total_leads", analytics)
        self.assertIn("department_routing", analytics)

    def test_cloud_health_probe(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["engine_online"])
        self.assertIn("database", data)


class TestTopLevelAuthAndSession(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_top_level_register_and_login_flow(self):
        # 1. GET /register
        get_reg = self.client.get("/register")
        self.assertEqual(get_reg.status_code, 200)

        # 2. POST /register
        reg_res = self.client.post("/register", json={
            "email": "sarah.connor@cyberdyne.io",
            "password": "Resistance2026!",
            "full_name": "Sarah Connor",
            "org_name": "Cyberdyne Systems"
        })
        self.assertEqual(reg_res.status_code, 201)
        data = reg_res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["email"], "sarah.connor@cyberdyne.io")
        self.assertEqual(data["role"], "owner")

        # 3. GET /login
        get_log = self.client.get("/login")
        self.assertEqual(get_log.status_code, 200)

        # 4. POST /login with correct password
        log_res = self.client.post("/login", json={
            "email": "sarah.connor@cyberdyne.io",
            "password": "Resistance2026!"
        })
        self.assertEqual(log_res.status_code, 200)
        self.assertTrue(log_res.get_json()["success"])

        # 5. POST /login with incorrect password
        bad_log = self.client.post("/login", json={
            "email": "sarah.connor@cyberdyne.io",
            "password": "WrongPassword!"
        })
        self.assertEqual(bad_log.status_code, 401)
        self.assertEqual(bad_log.get_json()["code"], "UNAUTHORIZED")

    def test_auth_rate_limiting_on_login(self):
        self.app.config["LOGIN_RATE_LIMIT"] = 2
        for _ in range(2):
            self.client.post("/login", json={"email": "nobody@test.com", "password": "wrong"})
        third = self.client.post("/login", json={"email": "nobody@test.com", "password": "wrong"})
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.get_json()["code"], "TOO_MANY_REQUESTS")
        self.assertIn("Retry-After", third.headers)


class TestLegacyRouteProtection(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        self.org = Organization(id="org-legacy-test", name="Legacy Org", slug="legacy-org", is_active=True)
        self.user = User(id="usr-legacy-admin", email="legacy_admin@test.com", full_name="Legacy Admin", is_active=True)
        self.user.set_password("AdminSecure2026!")
        self.mem = Membership(id="mem-legacy", user_id=self.user.id, organization_id=self.org.id, role="admin")

        secret_key, prefix, key_hash = generate_secure_api_key()
        self.raw_api_key = secret_key
        self.api_key = ApiKey(
            id="key-legacy",
            organization_id=self.org.id,
            user_id=self.user.id,
            name="Legacy Test Key",
            key_prefix=prefix,
            key_hash=key_hash,
            permissions="*"
        )
        db.session.add_all([self.org, self.user, self.mem, self.api_key])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_unauthenticated_nlp_analyze_rejected(self):
        res = self.client.post("/api/nlp/analyze", json={"text": "CPU overload"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_unauthenticated_v1_nlp_analyze_rejected(self):
        res = self.client.post("/api/v1/nlp/analyze", json={"text": "CPU overload"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_unauthenticated_legacy_routes_rejected(self):
        self.assertEqual(self.client.get("/api/rules").status_code, 401)
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.get("/api/telemetry").status_code, 401)
        self.assertEqual(self.client.post("/api/engine/toggle", json={"online": True}).status_code, 401)
        self.assertEqual(self.client.get("/api/logs").status_code, 401)
        self.assertEqual(self.client.get("/api/leads").status_code, 401)
        self.assertEqual(self.client.get("/api/analytics").status_code, 401)

    def test_authenticated_legacy_routes_work(self):
        # 1. Authenticated via session login
        self.client.post("/login", json={"email": "legacy_admin@test.com", "password": "AdminSecure2026!"})
        res_rules = self.client.get("/api/rules")
        self.assertEqual(res_rules.status_code, 200)
        self.assertIn("rules", res_rules.get_json())

        res_nlp = self.client.post("/api/nlp/analyze", json={"text": "Critical CPU spike 98%", "dry_run": True})
        self.assertEqual(res_nlp.status_code, 200)

        res_status = self.client.get("/api/status")
        self.assertEqual(res_status.status_code, 200)

        # 2. Authenticated via API Key
        self.client.post("/api/v1/auth/logout")
        res_key = self.client.get("/api/rules", headers={"X-API-Key": self.raw_api_key})
        self.assertEqual(res_key.status_code, 200)


class TestErrorSecurityAndDataProtection(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        self.org = Organization(id="org-sec-test", name="Security Org", slug="sec-org", is_active=True)
        self.user = User(id="usr-sec", email="sec@test.com", full_name="Sec Officer", is_active=True)
        self.user.set_password("SecPassword2026!")
        self.mem = Membership(id="mem-sec", user_id=self.user.id, organization_id=self.org.id, role="admin")

        secret_key, prefix, key_hash = generate_secure_api_key()
        self.raw_api_key = secret_key
        self.api_key = ApiKey(
            id="key-sec",
            organization_id=self.org.id,
            user_id=self.user.id,
            name="Security Key",
            key_prefix=prefix,
            key_hash=key_hash,
            permissions="*"
        )
        self.wh = WebhookEndpoint(
            id="wh-sec",
            organization_id=self.org.id,
            name="Sec WH",
            endpoint_token="wh_sec_token_999",
            secret_token="ultra_secret_hmac_key_999"
        )
        db.session.add_all([self.org, self.user, self.mem, self.api_key, self.wh])
        db.session.commit()

        self.client.post("/login", json={"email": "sec@test.com", "password": "SecPassword2026!"})

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_error_security_does_not_leak_passwords_hashes_or_secrets(self):
        # 1. User profile serialization does NOT expose password or password_hash
        me_res = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_res.status_code, 200)
        user_dict = me_res.get_json()["user"]
        self.assertNotIn("password", user_dict)
        self.assertNotIn("password_hash", user_dict)

        # 2. API Key listing does NOT expose key_hash or full raw secret
        keys_res = self.client.get("/api/v1/api-keys")
        self.assertEqual(keys_res.status_code, 200)
        keys = keys_res.get_json()["api_keys"]
        self.assertTrue(len(keys) >= 1)
        for k in keys:
            self.assertNotIn("key_hash", k)
            self.assertNotIn("secret_key", k)
            self.assertNotIn(self.raw_api_key, json.dumps(k))

        # 3. Webhook listing does NOT expose secret_token
        wh_res = self.client.get("/api/v1/webhooks")
        self.assertEqual(wh_res.status_code, 200)
        whs = wh_res.get_json()["webhooks"]
        for w in whs:
            self.assertNotIn("secret_token", w)
            self.assertNotIn("ultra_secret_hmac_key_999", json.dumps(w))
            self.assertTrue(w["secret_configured"])

    def test_error_security_400_and_500_sanitize_tracebacks_and_internals(self):
        bad_req = self.client.post("/api/rules", json="invalid-json-not-dict", content_type="application/json")
        self.assertIn(bad_req.status_code, [400])
        body_str = bad_req.get_data(as_text=True)
        self.assertNotIn("Traceback", body_str)
        self.assertNotIn("sqlite", body_str.lower())
        self.assertNotIn("psycopg2", body_str.lower())


class TestPlanEntitlementsAndQuotaEnforcement(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

        # Seed test organization with Starter plan
        self.org = Organization(
            id="org-starter-quota",
            name="Starter Automation Labs",
            slug="starter-quota-labs",
            plan_tier=PLAN_STARTER,
            max_rules=2,
            max_monthly_events=2,
            is_active=True
        )
        self.user = User(
            id="usr-quota-admin",
            email="admin@starterlabs.io",
            full_name="Quota Admin",
            is_active=True
        )
        self.user.set_password("AdminQuotaPass2026!")

        self.viewer = User(
            id="usr-quota-viewer",
            email="viewer@starterlabs.io",
            full_name="Quota Viewer",
            is_active=True
        )
        self.viewer.set_password("ViewerQuotaPass2026!")

        self.mem_owner = Membership(
            id="mem-quota-owner",
            user_id=self.user.id,
            organization_id=self.org.id,
            role="owner"
        )
        self.mem_viewer = Membership(
            id="mem-quota-viewer",
            user_id=self.viewer.id,
            organization_id=self.org.id,
            role="viewer"
        )

        db.session.add_all([self.org, self.user, self.viewer, self.mem_owner, self.mem_viewer])
        db.session.commit()

        # Log in as owner/admin
        self.client.post("/login", json={"email": "admin@starterlabs.io", "password": "AdminQuotaPass2026!"})

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_plan_matrix_specifications(self):
        """Verifies centralized plan configurations for Free, Starter, Pro, and Enterprise."""
        # 1. Plan definitions exist
        for tier in [PLAN_FREE, PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE]:
            self.assertIn(tier, PLAN_DEFINITIONS)
            p = PLAN_DEFINITIONS[tier]
            self.assertIn("max_rules", p["quotas"])
            self.assertIn("monthly_events", p["quotas"])
            self.assertIn("allowed_ai_providers", p)
            self.assertIn("features", p)

        # 2. Free vs Pro vs Enterprise progression
        self.assertTrue(PLAN_DEFINITIONS[PLAN_FREE]["quotas"]["max_rules"] < PLAN_DEFINITIONS[PLAN_STARTER]["quotas"]["max_rules"])
        self.assertTrue(PLAN_DEFINITIONS[PLAN_STARTER]["quotas"]["max_rules"] < PLAN_DEFINITIONS[PLAN_PRO]["quotas"]["max_rules"])
        self.assertTrue(PLAN_DEFINITIONS[PLAN_PRO]["quotas"]["max_rules"] < PLAN_DEFINITIONS[PLAN_ENTERPRISE]["quotas"]["max_rules"])

        # 3. Public GET /api/v1/plans endpoint
        res = self.client.get("/api/v1/plans")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 4)
        tiers = [p["tier"] for p in data["plans"]]
        self.assertIn("free", tiers)
        self.assertIn("starter", tiers)
        self.assertIn("pro", tiers)
        self.assertIn("enterprise", tiers)

    def test_quotas_and_entitlements_inspection(self):
        """Validates GET /api/v1/plan and GET /api/v1/quotas returning live usage & percentage calculations."""
        res = self.client.get("/api/v1/quotas")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        entitlements = data["entitlements"]
        self.assertEqual(entitlements["plan_tier"], PLAN_STARTER)
        self.assertEqual(entitlements["quotas"]["rules"]["limit"], 2)
        self.assertEqual(entitlements["quotas"]["rules"]["current"], 0)
        self.assertEqual(entitlements["quotas"]["rules"]["remaining"], 2)
        self.assertFalse(entitlements["quotas"]["rules"]["is_exceeded"])

    def test_rules_quota_enforcement_blocks_creation_duplication_and_templates(self):
        """Verifies rule creation, duplication, and template installation are blocked when quota is exhausted."""
        rule_payload_1 = {
            "name": "Auto Incident Triage",
            "event_trigger": "server.alert",
            "actions": [{"action": "log", "params": {"message": "Incident logged"}}]
        }
        rule_payload_2 = {
            "name": "Lead Ingestion Piper",
            "event_trigger": "lead.created",
            "actions": [{"action": "log", "params": {"message": "Lead saved"}}]
        }

        # 1. Create first rule -> 201
        res1 = self.client.post("/api/v1/rules", json=rule_payload_1)
        self.assertEqual(res1.status_code, 201)
        rule_id_1 = res1.get_json()["rule"]["id"]

        # 2. Create second rule -> 201 (reaches limit of 2)
        res2 = self.client.post("/api/v1/rules", json=rule_payload_2)
        self.assertEqual(res2.status_code, 201)

        # 3. Create 3rd rule via /api/v1/rules -> 403 PLAN_LIMIT_EXCEEDED
        res3 = self.client.post("/api/v1/rules", json={"name": "Third Rule", "event_trigger": "test"})
        self.assertEqual(res3.status_code, 403)
        self.assertIn(res3.get_json()["code"], ["PLAN_LIMIT_EXCEEDED", "QUOTA_EXCEEDED"])

        # 4. Duplicate rule -> 403 PLAN_LIMIT_EXCEEDED
        res_dup = self.client.post(f"/api/v1/rules/{rule_id_1}/duplicate")
        self.assertEqual(res_dup.status_code, 403)
        self.assertIn(res_dup.get_json()["code"], ["PLAN_LIMIT_EXCEEDED", "QUOTA_EXCEEDED"])

        # 5. Install template -> 403 PLAN_LIMIT_EXCEEDED
        res_tmpl = self.client.post("/api/v1/templates/tmpl-incident-escalation/install")
        self.assertEqual(res_tmpl.status_code, 403)
        self.assertIn(res_tmpl.get_json()["code"], ["PLAN_LIMIT_EXCEEDED", "QUOTA_EXCEEDED"])

        # 6. Legacy create rule -> 403 PLAN_LIMIT_EXCEEDED
        res_leg = self.client.post("/api/rules", json={"name": "Legacy Blocked Rule"})
        self.assertEqual(res_leg.status_code, 403)
        self.assertIn(res_leg.get_json()["code"], ["PLAN_LIMIT_EXCEEDED", "QUOTA_EXCEEDED"])

        # 7. Legacy install preset -> 403 PLAN_LIMIT_EXCEEDED
        res_leg_preset = self.client.post("/api/presets/install", json={"preset_id": "template-ai-lead-qualification"})
        self.assertEqual(res_leg_preset.status_code, 403)
        self.assertIn(res_leg_preset.get_json()["code"], ["PLAN_LIMIT_EXCEEDED", "QUOTA_EXCEEDED"])

    def test_monthly_event_quota_enforcement_and_dry_run_immunity(self):
        """Verifies event ingestion pauses at quota while dry-run simulations remain allowed."""
        # 1. Ingest event 1 -> 200
        res1 = self.client.post("/api/v1/events", json={"event_name": "system.ping", "payload": {"host": "web-1"}})
        self.assertEqual(res1.status_code, 200)

        # 2. Ingest event 2 -> 200
        res2 = self.client.post("/api/v1/events", json={"event_name": "system.ping", "payload": {"host": "web-2"}})
        self.assertEqual(res2.status_code, 200)

        # 3. Ingest event 3 (exceeds limit 2) -> 429 QUOTA_EXCEEDED
        res3 = self.client.post("/api/v1/events", json={"event_name": "system.ping", "payload": {"host": "web-3"}})
        self.assertEqual(res3.status_code, 429)
        self.assertIn(res3.get_json()["code"], ["QUOTA_EXCEEDED", "PLAN_LIMIT_EXCEEDED"])

        # 4. Dry-run events bypass monthly quota check
        res_dry = self.client.post("/api/v1/events", json={
            "event_name": "system.ping",
            "payload": {"host": "web-dry"},
            "dry_run": True
        })
        self.assertEqual(res_dry.status_code, 200)
        self.assertTrue(res_dry.get_json()["dry_run"])

        # 5. Legacy dispatch also respects event quota -> 429
        res_leg = self.client.post("/api/events/dispatch", json={"event_name": "legacy.event", "payload": {}})
        self.assertEqual(res_leg.status_code, 429)
        self.assertIn(res_leg.get_json()["code"], ["QUOTA_EXCEEDED", "PLAN_LIMIT_EXCEEDED"])

        # 6. Inbound Webhook also pauses when monthly quota is reached -> 429
        wh_res = self.client.post("/api/v1/webhooks", json={"name": "Quota WH", "secret_token": "wh_quota_secret_key"})
        self.assertEqual(wh_res.status_code, 201)
        endpoint_token = wh_res.get_json()["webhook"]["endpoint_token"]

        raw_data = json.dumps({"data": "test"}).encode("utf-8")
        sig = "sha256=" + hmac.new(b"wh_quota_secret_key", raw_data, hashlib.sha256).hexdigest()

        wh_ingest = self.client.post(
            f"/api/v1/webhooks/incoming/{endpoint_token}",
            data=raw_data,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig}
        )
        self.assertEqual(wh_ingest.status_code, 429)
        self.assertIn(wh_ingest.get_json()["code"], ["QUOTA_EXCEEDED", "PLAN_LIMIT_EXCEEDED"])

    def test_api_key_and_webhook_quotas(self):
        """Verifies API key and webhook creation enforce plan limits."""
        # Starter plan allows max 2 API keys
        res_k1 = self.client.post("/api/v1/api-keys", json={"name": "Key 1"})
        self.assertEqual(res_k1.status_code, 201)

        res_k2 = self.client.post("/api/v1/api-keys", json={"name": "Key 2"})
        self.assertEqual(res_k2.status_code, 201)

        res_k3 = self.client.post("/api/v1/api-keys", json={"name": "Key 3"})
        self.assertEqual(res_k3.status_code, 403)
        self.assertEqual(res_k3.get_json()["code"], "QUOTA_EXCEEDED")

        # Starter plan allows max 2 webhooks
        res_w1 = self.client.post("/api/v1/webhooks", json={"name": "WH 1"})
        self.assertEqual(res_w1.status_code, 201)

        res_w2 = self.client.post("/api/v1/webhooks", json={"name": "WH 2"})
        self.assertEqual(res_w2.status_code, 201)

        res_w3 = self.client.post("/api/v1/webhooks", json={"name": "WH 3"})
        self.assertEqual(res_w3.status_code, 403)
        self.assertEqual(res_w3.get_json()["code"], "QUOTA_EXCEEDED")

    def test_ai_provider_entitlement_gating(self):
        """Verifies Starter cannot switch to cloud AI; Pro gets Gemini; Enterprise gets OpenAI."""
        # 1. Starter cannot use Google Gemini
        res_gemini = self.client.post("/api/v1/ai/provider", json={"provider": "google_gemini"})
        self.assertEqual(res_gemini.status_code, 403)
        self.assertEqual(res_gemini.get_json()["code"], "FEATURE_NOT_ENTITLED")

        # 2. Starter cannot use OpenAI
        res_openai = self.client.post("/api/v1/ai/provider", json={"provider": "openai"})
        self.assertEqual(res_openai.status_code, 403)
        self.assertEqual(res_openai.get_json()["code"], "FEATURE_NOT_ENTITLED")

        # 3. Local deterministic provider is permitted
        res_local = self.client.post("/api/v1/ai/provider", json={"provider": "local_deterministic"})
        self.assertEqual(res_local.status_code, 200)

        # 4. Upgrade to Pro -> Gemini permitted, OpenAI still blocked
        up_res = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "pro"})
        self.assertEqual(up_res.status_code, 200)

        res_gemini_pro = self.client.post("/api/v1/ai/provider", json={"provider": "google_gemini"})
        self.assertEqual(res_gemini_pro.status_code, 200)

        res_openai_pro = self.client.post("/api/v1/ai/provider", json={"provider": "openai"})
        self.assertEqual(res_openai_pro.status_code, 403)

        # 5. Upgrade to Enterprise -> OpenAI permitted
        up_ent = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "enterprise"})
        self.assertEqual(up_ent.status_code, 200)

        res_openai_ent = self.client.post("/api/v1/ai/provider", json={"provider": "openai"})
        self.assertEqual(res_openai_ent.status_code, 200)

    def test_feature_gating_audit_trail_and_export(self):
        """Verifies feature flags gate compliance audit trail and rule exports."""
        # 1. Starter plan cannot access audit trail
        res_audit = self.client.get("/api/v1/audit-trail")
        self.assertEqual(res_audit.status_code, 403)
        self.assertEqual(res_audit.get_json()["code"], "FEATURE_NOT_ENTITLED")

        # 2. Starter plan cannot access legacy export
        res_exp_leg = self.client.get("/api/export")
        self.assertEqual(res_exp_leg.status_code, 403)
        self.assertEqual(res_exp_leg.get_json()["code"], "FEATURE_NOT_ENTITLED")

        # 3. Starter plan cannot access modern export
        res_exp_v1 = self.client.get("/api/v1/rules/export")
        self.assertEqual(res_exp_v1.status_code, 403)
        self.assertEqual(res_exp_v1.get_json()["code"], "FEATURE_NOT_ENTITLED")

        # 4. Upgrade to Pro -> all granted
        self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "pro"})

        res_audit_pro = self.client.get("/api/v1/audit-trail")
        self.assertEqual(res_audit_pro.status_code, 200)

        res_exp_leg_pro = self.client.get("/api/export")
        self.assertEqual(res_exp_leg_pro.status_code, 200)

        res_exp_v1_pro = self.client.get("/api/v1/rules/export")
        self.assertEqual(res_exp_v1_pro.status_code, 200)

    def test_plan_upgrade_flow_and_rbac(self):
        """Verifies upgrading unlocks quotas and only owners/admins can perform upgrades."""
        # Fill quota
        self.client.post("/api/v1/rules", json={"name": "R1", "event_trigger": "e1"})
        self.client.post("/api/v1/rules", json={"name": "R2", "event_trigger": "e2"})
        res_blocked = self.client.post("/api/v1/rules", json={"name": "R3", "event_trigger": "e3"})
        self.assertEqual(res_blocked.status_code, 403)

        # Non-admin viewer cannot upgrade
        self.client.post("/api/v1/auth/logout")
        res_vlog = self.client.post("/api/v1/auth/login", json={"email": "viewer@starterlabs.io", "password": "ViewerQuotaPass2026!"})
        self.assertEqual(res_vlog.status_code, 200)
        res_viewer_up = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "pro"})
        self.assertEqual(res_viewer_up.status_code, 403)

        # Owner upgrades to Pro
        self.client.post("/api/v1/auth/logout")
        res_alog = self.client.post("/api/v1/auth/login", json={"email": "admin@starterlabs.io", "password": "AdminQuotaPass2026!"})
        self.assertEqual(res_alog.status_code, 200)
        res_up = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "pro"})
        self.assertEqual(res_up.status_code, 200)
        self.assertEqual(res_up.get_json()["organization"]["plan_tier"], "pro")

        # R3 creation now succeeds
        res_allowed = self.client.post("/api/v1/rules", json={"name": "R3", "event_trigger": "e3"})
        self.assertEqual(res_allowed.status_code, 201)

        # Audit log exists for upgrade
        audit = AuditLog.query.filter_by(action="plan.upgrade").first()
        self.assertIsNotNone(audit)
        self.assertIn("pro", audit.details_json)

        # Invalid plan returns 400
        res_invalid = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "nonexistent_tier"})
        self.assertEqual(res_invalid.status_code, 400)
        self.assertEqual(res_invalid.get_json()["code"], "VALIDATION_ERROR")

    def test_central_quota_service_api(self):
        """Verifies QuotaService / PlanEntitlements answers all 6 quota questions directly."""
        # 1. What plan does this organization have?
        plan = QuotaService.get_plan(self.org)
        self.assertEqual(plan["tier"], PLAN_STARTER)

        # 2. Is this feature enabled?
        self.assertFalse(QuotaService.is_feature_enabled(self.org, "audit_trail"))
        self.assertTrue(QuotaService.is_feature_enabled(self.org, "basic_telemetry"))

        # 3. How many rules may this organization have?
        self.assertEqual(QuotaService.get_max_rules(self.org), 2)

        # 4. How many monthly events has this organization consumed?
        self.assertEqual(QuotaService.get_monthly_events_count(self.org), 0)

        # 5. Is another rule/workflow allowed?
        allowed_rule, violation_rule = QuotaService.is_rule_allowed(self.org)
        self.assertTrue(allowed_rule)
        self.assertIsNone(violation_rule)

        # 6. Is another event allowed?
        allowed_evt, violation_evt = QuotaService.is_event_allowed(self.org)
        self.assertTrue(allowed_evt)
        self.assertIsNone(violation_evt)


if __name__ == "__main__":
    unittest.main()
