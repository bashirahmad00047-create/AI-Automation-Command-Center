"""Production Automation Execution & AI Workflow Integration Test Suite (Phase 6).

Comprehensive Focused Test Suite Covering User Requirements (Items 1-10):
1. test_focused_01_workflow_trigger_to_execution
2. test_focused_02_webhook_to_workflow
3. test_focused_03_tenant_isolation_during_execution
4. test_focused_04_invalid_api_key_rejection
5. test_focused_05_quota_enforcement_and_audit
6. test_focused_06_ai_provider_success_and_fallback
7. test_focused_07_crm_lead_automation
8. test_focused_08_incident_automation
9. test_focused_09_execution_history_and_forensics
10. test_focused_10_failure_handling_and_dlq
"""

import datetime
import hashlib
import hmac
import json
import os
import time
import unittest

import app as flask_app_module
from ai_provider import get_ai_provider, LocalDeterministicAIProvider, GeminiAIProvider
from database import db
from entitlements import QuotaService
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    Lead,
    Membership,
    Organization,
    User,
    WebhookEndpoint,
    WorkflowExecution,
)


class TestProductionAutomationPhase6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app_module.app.config["TESTING"] = True
        flask_app_module.app.config["RATELIMIT_ENABLED"] = False
        cls.client = flask_app_module.app.test_client()
        with flask_app_module.app.app_context():
            from init_db import init_and_seed_database
            init_and_seed_database()

    def setUp(self):
        from limiter import limiter
        limiter.reset()
        self.app_ctx = flask_app_module.app.app_context()
        self.app_ctx.push()

        # Login as Sarah Lin (admin@opsflow.io) for Acme Global
        self.client.post("/api/v1/auth/login", json={
            "email": "admin@opsflow.io",
            "password": "AdminSecure2026!"
        })

    def tearDown(self):
        db.session.rollback()
        self.app_ctx.pop()

    # =========================================================================
    # 1. Workflow Trigger -> Execution
    # =========================================================================
    def test_focused_01_workflow_trigger_to_execution(self):
        """1. Trigger -> Rule matching -> Conditions -> Action -> Execution record -> Audit trail."""
        rule_payload = {
            "name": "Production Latency Sentinel",
            "category": "System",
            "priority": 85,
            "trigger": {"type": "event", "event_name": "server.latency_spike"},
            "condition": {
                "logic": "AND",
                "conditions": [
                    {"field": "payload.latency_ms", "operator": ">=", "value": 300}
                ]
            },
            "actions": [
                {
                    "type": "notification",
                    "params": {
                        "title": "High Latency Alert ({{ payload.latency_ms }}ms)",
                        "message": "Latency alert on {{ payload.region }}.",
                        "severity": "warning"
                    }
                },
                {
                    "type": "log_entry",
                    "params": {
                        "level": "WARNING",
                        "message": "Latency spike observed: {{ payload.latency_ms }}ms"
                    }
                }
            ]
        }

        create_res = self.client.post("/api/v1/rules", json=rule_payload)
        self.assertEqual(create_res.status_code, 201)
        created_rule = create_res.get_json()["rule"]
        rule_id = created_rule["id"]

        # Ingest matching event
        event_res = self.client.post("/api/v1/events", json={
            "event": "server.latency_spike",
            "payload": {
                "latency_ms": 450,
                "region": "us-east-1"
            }
        })
        self.assertEqual(event_res.status_code, 200)
        data = event_res.get_json()
        executed_rules = data["result"]["executed_rules"]
        matched_rule = next((r for r in executed_rules if r["rule_id"] == rule_id), None)
        self.assertIsNotNone(matched_rule)
        self.assertTrue(matched_rule["matched"])
        self.assertEqual(matched_rule["status"], "success")

        # Verify execution record is persisted in real database
        exec_res = self.client.get(f"/api/v1/executions?rule_id={rule_id}")
        self.assertEqual(exec_res.status_code, 200)
        executions = exec_res.get_json()["executions"]
        self.assertGreaterEqual(len(executions), 1)
        self.assertEqual(executions[0]["rule_id"], rule_id)
        self.assertEqual(executions[0]["status"], "SUCCESS")

        # Verify audit log event
        audit_res = self.client.get("/api/v1/audit")
        self.assertEqual(audit_res.status_code, 200)
        actions = [a.get("action") or a.get("event") for a in audit_res.get_json()["audit_trail"]]
        self.assertIn("workflow.create", actions)

    # =========================================================================
    # 2. Webhook -> Workflow
    # =========================================================================
    def test_focused_02_webhook_to_workflow(self):
        """2. Webhook -> Correct tenant -> Matching workflow -> Action execution -> Execution history."""
        # Create webhook endpoint in Acme Global
        wh_create = self.client.post("/api/v1/webhooks", json={
            "name": "Datadog Integration Webhook",
            "secret_token": "phase6-hmac-secret-key-2026"
        })
        self.assertEqual(wh_create.status_code, 201)
        wh_data = wh_create.get_json()["webhook"]
        endpoint_token = wh_data["endpoint_token"]

        # Post valid HMAC-SHA256 payload to public webhook receiver
        unauth_client = flask_app_module.app.test_client()
        payload = json.dumps({"event": "system.metrics", "cpu_percent": 95.0, "host": "prod-k8s-node-99"}).encode("utf-8")
        sig = "sha256=" + hmac.new(b"phase6-hmac-secret-key-2026", payload, hashlib.sha256).hexdigest()

        wh_post = unauth_client.post(
            f"/api/v1/webhooks/incoming/{endpoint_token}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig
            }
        )
        self.assertEqual(wh_post.status_code, 200)
        self.assertTrue(wh_post.get_json()["received"])

        # Invalid HMAC signature is rejected with 401
        bad_sig_post = unauth_client.post(
            f"/api/v1/webhooks/incoming/{endpoint_token}",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid_hash_signature"
            }
        )
        self.assertEqual(bad_sig_post.status_code, 401)
        self.assertEqual(bad_sig_post.get_json()["code"], "UNAUTHORIZED")

        # Missing HMAC signature is rejected with 401
        missing_sig_post = unauth_client.post(
            f"/api/v1/webhooks/incoming/{endpoint_token}",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(missing_sig_post.status_code, 401)

    # =========================================================================
    # 3. Tenant Isolation During Execution
    # =========================================================================
    def test_focused_03_tenant_isolation_during_execution(self):
        """3. Customer A cannot access Customer B's workflows, executions, leads, or webhooks."""
        org_acme = Organization.query.filter_by(slug="acme-global").first()
        org_apex = Organization.query.filter_by(slug="apex-health").first()
        self.assertIsNotNone(org_acme)
        self.assertIsNotNone(org_apex)

        # Login as Apex Health admin (Customer B)
        apex_client = flask_app_module.app.test_client()
        login_res = apex_client.post("/api/v1/auth/login", json={
            "email": "admin@apexhealth.internal",
            "password": "HealthTech2026!"
        })
        self.assertEqual(login_res.status_code, 200)

        # 1. Apex cannot view or delete Acme's workflows
        acme_rule = AutomationRule.query.filter_by(organization_id=org_acme.id).first()
        if acme_rule:
            cross_get = apex_client.get(f"/api/v1/rules/{acme_rule.id}")
            self.assertEqual(cross_get.status_code, 404)

            cross_del = apex_client.delete(f"/api/v1/rules/{acme_rule.id}")
            self.assertEqual(cross_del.status_code, 404)

            # 2. Apex cannot trigger Acme's workflows
            cross_run = apex_client.post(f"/api/v1/rules/{acme_rule.id}/run", json={"payload": {}})
            self.assertEqual(cross_run.status_code, 404)

        # 3. Apex cannot view Acme's execution logs
        acme_exec = WorkflowExecution.query.filter_by(organization_id=org_acme.id).first()
        if acme_exec:
            cross_exec = apex_client.get(f"/api/v1/executions/{acme_exec.id}")
            self.assertEqual(cross_exec.status_code, 404)

        # 4. Apex cannot view Acme's CRM leads
        acme_lead = Lead.query.filter_by(organization_id=org_acme.id).first()
        if acme_lead:
            cross_lead = apex_client.get(f"/api/v1/leads/{acme_lead.id}")
            self.assertEqual(cross_lead.status_code, 404)

        # 5. Apex cannot view Acme's webhooks
        acme_wh = WebhookEndpoint.query.filter_by(organization_id=org_acme.id).first()
        if acme_wh:
            apex_wh_list = apex_client.get("/api/v1/webhooks").get_json()["webhooks"]
            self.assertNotIn(acme_wh.endpoint_token, [w["endpoint_token"] for w in apex_wh_list])

    # =========================================================================
    # 4. Invalid API Key Rejection
    # =========================================================================
    def test_focused_04_invalid_api_key_rejection(self):
        """4. Validate API key authentication; reject invalid, malformed, or unauthorized keys."""
        unauth_client = flask_app_module.app.test_client()

        # Valid master API key
        valid_res = unauth_client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": "sk_live_opsflow_enterprise_prod_2026"}
        )
        self.assertEqual(valid_res.status_code, 200)
        self.assertEqual(valid_res.get_json()["user"]["email"], "admin@opsflow.io")

        # Invalid API key rejected with 401
        invalid_res = unauth_client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": "sk_live_invalid_key_bogus_12345"}
        )
        self.assertEqual(invalid_res.status_code, 401)
        self.assertEqual(invalid_res.get_json()["code"], "UNAUTHORIZED")

        # Malformed key (not starting with sk_) rejected with 401
        malformed_res = unauth_client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": "malformed_key_without_prefix"}
        )
        self.assertEqual(malformed_res.status_code, 401)

    # =========================================================================
    # 5. Quota Enforcement & Audit Recording
    # =========================================================================
    def test_focused_05_quota_enforcement_and_audit(self):
        """5. Quota limits enforced: returns controlled response and logs audit event."""
        org = Organization.query.filter_by(slug="acme-global").first()
        self.assertIsNotNone(org)

        # QuotaService inspection
        quotas = QuotaService.get_quotas(org)
        self.assertIn("rules", quotas)
        self.assertIn("monthly_events", quotas)
        self.assertIn("api_keys", quotas)

        # Simulate reaching rule limit by setting max_rules to current rule count
        original_max = org.max_rules
        current_count = QuotaService.get_rules_count(org)
        org.max_rules = current_count
        db.session.commit()

        try:
            # Attempt to create rule beyond quota
            overflow_res = self.client.post("/api/v1/rules", json={
                "name": "Overflow Rule",
                "category": "System",
                "trigger": {"type": "event", "event_name": "overflow.event"}
            })
            self.assertEqual(overflow_res.status_code, 403)
            data = overflow_res.get_json()
            self.assertEqual(data["code"], "PLAN_LIMIT_EXCEEDED")
            self.assertIn("Rule limit exceeded", data["error"])

            # Verify audit log recorded quota.exceeded event
            audits = AuditLog.query.filter_by(organization_id=org.id, action="quota.exceeded").all()
            self.assertGreaterEqual(len(audits), 1)
        finally:
            org.max_rules = original_max
            db.session.commit()

    # =========================================================================
    # 6. AI Provider Success & Fallback
    # =========================================================================
    def test_focused_06_ai_provider_success_and_fallback(self):
        """6. AI classification, RCA summarization, and safe offline fallback without credentials."""
        provider = get_ai_provider()
        self.assertIsNotNone(provider)

        # Classification
        classified = provider.classify_text(
            "We need enterprise licensing for 200 engineers.",
            categories=["DevOps", "Billing", "Sales", "Security", "Support"]
        )
        self.assertEqual(classified["category"], "Sales")

        # RCA Summarization
        rca = provider.summarize_incident(
            "FATAL: OutOfMemoryError in worker queue container pod-42. Resident memory exceeded limit 4096MB."
        )
        self.assertIn(rca["severity"], ("P1_CRITICAL", "P2_HIGH"))
        self.assertIn("memory", rca["rca_summary"].lower())

        # Safe fallback without credentials
        gemini_fallback = GeminiAIProvider(api_key="")
        info = gemini_fallback.get_info()
        self.assertFalse(info["is_configured"])
        self.assertEqual(info["status"], "missing_key")

        analyzed = gemini_fallback.analyze_text("Out of memory crash in worker container")
        self.assertTrue(len(analyzed.get("intent", "")) > 0)
        gen = gemini_fallback.generate_text("Outage mitigation")
        self.assertTrue(len(gen) > 5)

    # =========================================================================
    # 7. CRM Lead Automation
    # =========================================================================
    def test_focused_07_crm_lead_automation(self):
        """7. Ingest Lead -> Workflow Trigger -> AI Scoring -> CRM Update -> History."""
        # Install AI Lead Qualification template
        self.client.post("/api/v1/templates/template-ai-lead-qualification/install")

        # Ingest new lead
        lead_res = self.client.post("/api/v1/leads", json={
            "name": "Alexander Vance",
            "email": "avance@fintech-enterprise.io",
            "company": "Fintech Enterprise Global",
            "message": "We need an enterprise quote for 250 automation licenses with SLA."
        })
        self.assertEqual(lead_res.status_code, 201)
        lead_data = lead_res.get_json()["lead"]
        lead_id = lead_data["id"]

        # Verify AI scoring and routing
        self.assertGreaterEqual(lead_data["lead_score"], 50)
        self.assertEqual(lead_data["route_department"], "Sales")

        # Trigger workflow with lead.created event
        event_res = self.client.post("/api/v1/events", json={
            "event": "lead.created",
            "payload": {
                "id": lead_id,
                "lead_id": lead_id,
                "name": "Alexander Vance",
                "email": "avance@fintech-enterprise.io"
            }
        })
        self.assertEqual(event_res.status_code, 200)

        # Verify execution record exists in history
        exec_res = self.client.get("/api/v1/executions")
        self.assertEqual(exec_res.status_code, 200)
        executions = exec_res.get_json()["executions"]
        self.assertTrue(any("lead" in e.get("trigger_event", "") for e in executions))

    # =========================================================================
    # 8. Incident Automation
    # =========================================================================
    def test_focused_08_incident_automation(self):
        """8. incident.created + severity condition -> matching workflow -> action -> execution/audit record."""
        # Install Critical Incident Router blueprint
        self.client.post("/api/v1/templates/template-critical-incident-router/install")

        # Dispatch incident.created event with critical severity
        event_res = self.client.post("/api/v1/events", json={
            "event": "incident.created",
            "payload": {
                "severity": "critical",
                "message": "Production database cluster node failure in region eu-central-1",
                "service": "postgres-cluster"
            }
        })
        self.assertEqual(event_res.status_code, 200)

        # Verify alert created in incident queue
        alerts_res = self.client.get("/api/v1/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        alerts = alerts_res.get_json()["alerts"]
        crit_alerts = [a for a in alerts if a.get("severity") == "critical"]
        self.assertGreaterEqual(len(crit_alerts), 1)

    # =========================================================================
    # 9. Execution History & Forensics
    # =========================================================================
    def test_focused_09_execution_history_and_forensics(self):
        """9. Customer can inspect execution detail: rule, trigger, duration, status, action results."""
        exec_res = self.client.get("/api/v1/executions?limit=5")
        self.assertEqual(exec_res.status_code, 200)
        logs = exec_res.get_json()["executions"]
        self.assertGreaterEqual(len(logs), 1)

        detail_res = self.client.get(f"/api/v1/executions/{logs[0]['id']}")
        self.assertEqual(detail_res.status_code, 200)
        execution = detail_res.get_json()["execution"]

        self.assertIn("rule_name", execution)
        self.assertIn("trigger_event", execution)
        self.assertIn("execution_time_ms", execution)
        self.assertIn("status", execution)
        self.assertIn("executed_at", execution)

    # =========================================================================
    # 10. Failure Handling, DLQ & Reliability
    # =========================================================================
    def test_focused_10_failure_handling_and_dlq(self):
        """10. Safe handling for failures, malformed payloads, DLQ replay, and async jobs."""
        # 1. Action failure handled gracefully & added to DLQ
        failing_rule = {
            "name": "Failing Action Test Workflow",
            "category": "DevOps",
            "priority": 50,
            "trigger": {"type": "event", "event_name": "test.dlq_trigger"},
            "actions": [
                {
                    "type": "webhook_call",
                    "params": {
                        "url": "http://127.0.0.1:59999/dead_endpoint",
                        "retries": 1,
                        "timeout": 0.1
                    }
                }
            ]
        }
        create_res = self.client.post("/api/v1/rules", json=failing_rule)
        rule_id = create_res.get_json()["rule"]["id"]

        run_res = self.client.post(f"/api/v1/rules/{rule_id}/run", json={"payload": {"test": "dlq"}})
        self.assertEqual(run_res.status_code, 200)
        self.assertEqual(run_res.get_json()["status"], "failed")

        # Inspect DLQ
        dlq_res = self.client.get("/api/v1/dlq")
        self.assertEqual(dlq_res.status_code, 200)
        dlq_items = dlq_res.get_json()["dlq"]
        self.assertGreaterEqual(len(dlq_items), 1)
        dlq_item = next((i for i in dlq_items if i.get("rule_id") == rule_id), dlq_items[0])
        dlq_id = dlq_item["id"]

        # Replay DLQ item
        replay_res = self.client.post(f"/api/v1/dlq/{dlq_id}/replay")
        self.assertEqual(replay_res.status_code, 200)
        self.assertTrue(replay_res.get_json()["success"])

        # Purge DLQ item
        del_res = self.client.delete(f"/api/v1/dlq/{dlq_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["success"])

        # 2. Async job dispatch
        async_res = self.client.post(f"/api/v1/workflows/{rule_id}/dispatch-async", json={"payload": {}})
        self.assertEqual(async_res.status_code, 202)
        job_id = async_res.get_json()["job_id"]

        jobs_res = self.client.get("/api/v1/jobs")
        self.assertEqual(jobs_res.status_code, 200)
        self.assertIn(job_id, [j["job_id"] for j in jobs_res.get_json()["jobs"]])


if __name__ == "__main__":
    unittest.main()
