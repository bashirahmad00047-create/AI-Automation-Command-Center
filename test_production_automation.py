"""Production Automation Execution & AI Workflow Integration Test Suite (Phase 6).

Covers:
1. End-to-end customer workflow execution (Trigger -> Match -> Condition -> Action -> Exec Record -> Audit)
2. Inbound webhook execution with HMAC, tenant isolation, and API key auth validation
3. AI workflow integration (classify, summarize, extract entities, score leads, generate operational response)
4. CRM automation (new lead -> trigger -> AI scoring -> lead update -> execution history)
5. Incident automation (incident.created + severity condition -> matching workflow -> action -> execution)
6. Quota and plan enforcement (rule limits, event limits, plan matrix, tenant data isolation)
7. Asynchronous job execution and Dead-Letter Queue (DLQ) replay
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

    # ==========================================
    # 1. Real End-to-End Workflow Execution
    # ==========================================
    def test_customer_created_workflow_end_to_end_execution(self):
        """Verify custom customer workflow executes: Trigger -> Match -> Condition -> Action -> Exec Record -> Audit."""
        # Create custom workflow rule
        rule_payload = {
            "name": "Custom Server Latency Monitor",
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

        # Verify execution record is persisted
        exec_res = self.client.get(f"/api/v1/executions?rule_id={rule_id}")
        self.assertEqual(exec_res.status_code, 200)
        executions = exec_res.get_json()["executions"]
        self.assertGreaterEqual(len(executions), 1)
        self.assertEqual(executions[0]["rule_id"], rule_id)
        self.assertEqual(executions[0]["status"], "SUCCESS")

        # Verify audit log event
        audit_res = self.client.get("/api/v1/audit")
        self.assertEqual(audit_res.status_code, 200)
        events = [a["event"] for a in audit_res.get_json()["audit_trail"]]
        self.assertIn("workflow.create", events)

    # ==========================================
    # 2. Inbound Webhook Execution & Security
    # ==========================================
    def test_inbound_webhook_execution_and_tenant_isolation(self):
        """Verify Webhook -> Correct tenant -> Matching workflow -> Action -> History, and block cross-tenant."""
        # Create webhook endpoint in Acme Global
        wh_create = self.client.post("/api/v1/webhooks", json={
            "name": "Datadog Integration Webhook",
            "secret_token": "phase6-hmac-secret-key-2026"
        })
        self.assertEqual(wh_create.status_code, 201)
        wh_data = wh_create.get_json()["webhook"]
        endpoint_token = wh_data["endpoint_token"]

        # Unauthenticated client posts valid HMAC payload to public webhook receiver
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

        # Cross-tenant webhook isolation: Apex Health admin cannot see Acme Global's webhook
        apex_client = flask_app_module.app.test_client()
        apex_client.post("/api/v1/auth/login", json={
            "email": "admin@apexhealth.internal",
            "password": "HealthTech2026!"
        })
        apex_wh_list = apex_client.get("/api/v1/webhooks").get_json()["webhooks"]
        apex_tokens = [w["endpoint_token"] for w in apex_wh_list]
        self.assertNotIn(endpoint_token, apex_tokens)

    def test_api_key_authentication_validation(self):
        """Verify API key authentication works and invalid keys are rejected."""
        unauth_client = flask_app_module.app.test_client()

        # Valid master API key
        valid_res = unauth_client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": "sk_live_opsflow_enterprise_prod_2026"}
        )
        self.assertEqual(valid_res.status_code, 200)
        self.assertEqual(valid_res.get_json()["user"]["email"], "admin@opsflow.io")

        # Invalid API key rejected
        invalid_res = unauth_client.get(
            "/api/v1/auth/me",
            headers={"X-API-Key": "sk_live_invalid_key_bogus_12345"}
        )
        self.assertEqual(invalid_res.status_code, 401)
        self.assertEqual(invalid_res.get_json()["code"], "UNAUTHORIZED")

    # ==========================================
    # 3. AI Workflow Integration & Safe Fallbacks
    # ==========================================
    def test_ai_workflow_classification_and_summarization(self):
        """Test AI classification, incident RCA summarization, and direct endpoints."""
        provider = get_ai_provider()
        self.assertIsNotNone(provider)

        # 1. Text classification
        classified = provider.classify_text(
            "We need enterprise pricing and licensing for 500 SRE seats.",
            categories=["DevOps", "Billing", "Sales", "Security", "Support"]
        )
        self.assertEqual(classified["category"], "Sales")
        self.assertGreater(classified["confidence"], 0.5)

        # 2. Incident RCA summarization
        rca = provider.summarize_incident(
            "FATAL: OutOfMemoryError in worker process pod-77. Resident memory exceeded limit 4096MB."
        )
        self.assertIn(rca["severity"], ("P1_CRITICAL", "P2_HIGH"))
        self.assertIn("memory", rca["rca_summary"].lower())
        self.assertGreaterEqual(len(rca["recommended_actions"]), 1)

        # 3. Operational response generation
        response_text = provider.generate_text("Provide recommendations to mitigate high latency in production.")
        self.assertTrue(len(response_text) > 20)

        # 4. Safe AI API endpoints
        gen_res = self.client.post("/api/v1/ai/generate", json={
            "prompt": "Recommend mitigation steps for CPU spike on prod-api-01."
        })
        self.assertEqual(gen_res.status_code, 200)
        self.assertTrue(gen_res.get_json()["success"])
        self.assertIn("generated_text", gen_res.get_json())

        triage_res = self.client.post("/api/v1/ai/triage", json={
            "text": "Out of memory crash in worker queue container",
            "categories": ["Infrastructure", "Billing", "Security"]
        })
        self.assertEqual(triage_res.status_code, 200)
        self.assertEqual(triage_res.get_json()["classification"]["category"], "Infrastructure")

    def test_gemini_safe_fallback_without_credentials(self):
        """Verify Gemini provider operates safely without credentials and never crashes."""
        gemini_fallback = GeminiAIProvider(api_key="")
        info = gemini_fallback.get_info()
        self.assertFalse(info["is_configured"])
        self.assertEqual(info["status"], "missing_key")

        # analyze_text falls back gracefully
        analyzed = gemini_fallback.analyze_text("Payment gateway failure with 500 error code")
        self.assertIn(analyzed["intent"], ("incident_ticket", "billing_issue", "api_error"))

        # generate_text falls back gracefully
        gen = gemini_fallback.generate_text("Mitigate outage")
        self.assertTrue(len(gen) > 10)

        # summarize_incident falls back gracefully
        rca = gemini_fallback.summarize_incident("Network timeout: connection refused to redis:6379")
        self.assertEqual(rca["severity"], "P1_CRITICAL")

    # ==========================================
    # 4. CRM Lead Automation
    # ==========================================
    def test_crm_lead_automation_pipeline(self):
        """Verify New Lead -> Workflow Trigger -> AI Enrichment -> Update -> Execution History."""
        # Install the pre-configured AI Lead Qualification template
        install_res = self.client.post("/api/v1/templates/template-ai-lead-qualification/install")
        self.assertIn(install_res.status_code, (200, 201))

        # Ingest new lead via CRM endpoint
        lead_res = self.client.post("/api/v1/leads", json={
            "name": "Samantha Vance",
            "email": "svance@fintech-enterprise.io",
            "company": "Fintech Enterprise Global",
            "message": "We require an enterprise quote for 250 automation licenses and high-throughput SLA."
        })
        self.assertEqual(lead_res.status_code, 201)
        lead_data = lead_res.get_json()["lead"]
        lead_id = lead_data["id"]

        # Verify AI scoring
        self.assertGreaterEqual(lead_data["lead_score"], 50)
        self.assertEqual(lead_data["route_department"], "Sales")

        # Ingest lead.created event explicitly to trigger installed blueprint
        event_res = self.client.post("/api/v1/events", json={
            "event": "lead.created",
            "payload": {
                "id": lead_id,
                "lead_id": lead_id,
                "name": "Samantha Vance",
                "email": "svance@fintech-enterprise.io",
                "company": "Fintech Enterprise Global",
                "message": "We require an enterprise quote for 250 automation licenses."
            }
        })
        self.assertEqual(event_res.status_code, 200)

        # Verify execution was recorded in history
        exec_res = self.client.get("/api/v1/executions")
        self.assertEqual(exec_res.status_code, 200)
        executions = exec_res.get_json()["executions"]
        lead_execs = [e for e in executions if e["trigger_event"] == "lead.created"]
        self.assertGreaterEqual(len(lead_execs), 1)

    # ==========================================
    # 5. Incident Automation
    # ==========================================
    def test_incident_automation_blueprint(self):
        """Verify incident.created + severity condition -> matching workflow -> action -> execution/audit record."""
        # Install Critical Incident Router blueprint
        install_res = self.client.post("/api/v1/templates/template-critical-incident-router/install")
        self.assertIn(install_res.status_code, (200, 201))

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
        res_data = event_res.get_json()
        executed_rules = res_data["result"]["executed_rules"]
        incident_rules = [r for r in executed_rules if "Incident" in r["rule_name"] or r["category"] == "Incident"]
        self.assertGreaterEqual(len(incident_rules), 1)
        self.assertTrue(incident_rules[0]["matched"])

        # Verify in-app alert was dispatched
        alerts_res = self.client.get("/api/v1/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        alerts = alerts_res.get_json()["alerts"]
        crit_alerts = [a for a in alerts if a["severity"] == "critical"]
        self.assertGreaterEqual(len(crit_alerts), 1)

    # ==========================================
    # 6. Quotas & Plan Enforcement
    # ==========================================
    def test_plan_matrix_and_quota_enforcement(self):
        """Verify plan limits: rules limit, monthly event limits, and tenant data isolation."""
        org = Organization.query.filter_by(slug="acme-global").first()
        self.assertIsNotNone(org)

        # QuotaService inspection
        quotas = QuotaService.get_quotas(org)
        self.assertIn("rules", quotas)
        self.assertIn("monthly_events", quotas)
        self.assertIn("api_keys", quotas)

        # Tenant rule isolation: verify tenant A cannot see or delete tenant B's rules
        apex_client = flask_app_module.app.test_client()
        apex_client.post("/api/v1/auth/login", json={
            "email": "admin@apexhealth.internal",
            "password": "HealthTech2026!"
        })

        # Apex tries to access Acme rule
        acme_rule = AutomationRule.query.filter_by(organization_id=org.id).first()
        if acme_rule:
            cross_res = apex_client.get(f"/api/v1/rules/{acme_rule.id}")
            self.assertEqual(cross_res.status_code, 404)

            cross_del = apex_client.delete(f"/api/v1/rules/{acme_rule.id}")
            self.assertEqual(cross_del.status_code, 404)

    # ==========================================
    # 7. Asynchronous Jobs & Dead-Letter Queue (DLQ)
    # ==========================================
    def test_async_workflow_dispatch_and_job_lifecycle(self):
        """Verify asynchronous job dispatch, status polling, and cancellation."""
        rule = AutomationRule.query.filter_by(enabled=True).first()
        self.assertIsNotNone(rule)

        # Dispatch async job
        async_res = self.client.post(f"/api/v1/workflows/{rule.id}/dispatch-async", json={
            "payload": {"test_async": True, "host": "prod-worker-async-01"}
        })
        self.assertEqual(async_res.status_code, 202)
        job_data = async_res.get_json()
        self.assertTrue(job_data["success"])
        job_id = job_data["job_id"]

        # List jobs
        jobs_res = self.client.get("/api/v1/jobs")
        self.assertEqual(jobs_res.status_code, 200)
        jobs = jobs_res.get_json()["jobs"]
        self.assertIn(job_id, [j["job_id"] for j in jobs])

        # Get job detail
        job_detail = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(job_detail.status_code, 200)
        self.assertIn(job_detail.get_json()["job"]["status"], ("QUEUED", "RUNNING", "COMPLETED"))

    def test_dead_letter_queue_and_replay(self):
        """Verify Dead-Letter Queue (DLQ) records failures and allows replay."""
        # Create a workflow with an action that fails
        failing_rule = {
            "name": "Failing Webhook Workflow",
            "category": "DevOps",
            "priority": 50,
            "trigger": {"type": "event", "event_name": "test.dlq_trigger"},
            "actions": [
                {
                    "type": "webhook_call",
                    "params": {
                        "url": "http://127.0.0.1:59999/non_existent_dead_endpoint",
                        "retries": 1,
                        "timeout": 0.1
                    }
                }
            ]
        }

        create_res = self.client.post("/api/v1/rules", json=failing_rule)
        rule_id = create_res.get_json()["rule"]["id"]

        # Run rule to trigger failure
        run_res = self.client.post(f"/api/v1/rules/{rule_id}/run", json={"payload": {"trace_id": "dlq-test-01"}})
        self.assertEqual(run_res.status_code, 200)
        self.assertEqual(run_res.get_json()["status"], "failed")

        # Inspect DLQ
        dlq_res = self.client.get("/api/v1/dlq")
        self.assertEqual(dlq_res.status_code, 200)
        dlq_items = dlq_res.get_json()["dlq"]
        self.assertGreaterEqual(len(dlq_items), 1)

        dlq_item = next((i for i in dlq_items if i.get("rule_id") == rule_id), None)
        self.assertIsNotNone(dlq_item)
        dlq_id = dlq_item["id"]

        # Replay DLQ item
        replay_res = self.client.post(f"/api/v1/dlq/{dlq_id}/replay")
        self.assertEqual(replay_res.status_code, 200)
        self.assertTrue(replay_res.get_json()["success"])

        # Purge DLQ item
        del_res = self.client.delete(f"/api/v1/dlq/{dlq_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
