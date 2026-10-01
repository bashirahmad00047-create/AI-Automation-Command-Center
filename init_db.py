"""Turnkey Database Seeding & Enterprise Demonstration Data Loader.

Executes database schema creation and loads realistic enterprise client data:
- Multi-Tenant Organizations ('Acme Global Enterprise' & 'Apex HealthTech')
- Role-based User Accounts (Admin, Operator, Viewer)
- Production API Keys
- Production Workflow Automation Rules & 8 Enterprise Templates
- CRM Leads & Inquiries (Clearly labeled sample data)
- Sample Workflow Executions & Step Waterfall Forensic Traces
- Sample Incident Alerts & Lifecycle Statuses
- Inbound Webhook Ingestion Gateways
- Compliance Audit Trail Logs
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys

from app import app
from database import db
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    ExecutionStep,
    IncidentAlert,
    Lead,
    Membership,
    Organization,
    SystemEvent,
    User,
    WebhookEndpoint,
    WorkflowExecution,
    WorkflowStep,
    generate_uuid,
)
from presets import PRESET_BLUEPRINTS


def init_and_seed_database():
    """Initializes database and populates with enterprise demo data."""
    print("[*] Initializing OpsFlow Enterprise SaaS Database...")

    with app.app_context():
        # Create all tables
        db.create_all()
        print("[OK] Database tables created successfully.")

        now_dt = datetime.datetime.utcnow()

        # 1. Organizations (Tenants)
        org_acme = db.session.get(Organization, "org-enterprise-default") or Organization.query.filter_by(slug="acme-global").first()
        if not org_acme:
            org_acme = Organization(
                id="org-enterprise-default",
                name="Acme Global Enterprise",
                slug="acme-global",
                plan_tier="enterprise",
                is_active=True,
                max_rules=250,
                max_monthly_events=1000000
            )
            db.session.add(org_acme)
        else:
            org_acme.name = "Acme Global Enterprise"
            org_acme.slug = "acme-global"

        org_apex = db.session.get(Organization, "org-apex-health-tenant") or Organization.query.filter_by(slug="apex-health").first()
        if not org_apex:
            org_apex = Organization(
                id="org-apex-health-tenant",
                name="Apex HealthTech Systems",
                slug="apex-health",
                plan_tier="pro",
                is_active=True,
                max_rules=50,
                max_monthly_events=200000
            )
            db.session.add(org_apex)

        db.session.flush()

        # 2. Users
        def create_user_if_missing(uid, email, name, password, is_super=False):
            u = User.query.filter_by(email=email).first()
            if not u:
                u = User(
                    id=uid,
                    email=email,
                    full_name=name,
                    is_active=True,
                    is_superuser=is_super
                )
                u.set_password(password)
                db.session.add(u)
                db.session.flush()
            return u

        admin_user = create_user_if_missing("usr-admin-primary", "admin@opsflow.io", "Sarah Lin (VP Ops)", "AdminSecure2026!", True)
        op_user = create_user_if_missing("usr-operator-primary", "operator@opsflow.io", "Alex Rivera (Lead SRE)", "Operator2026!")
        viewer_user = create_user_if_missing("usr-viewer-primary", "viewer@opsflow.io", "Jordan Smith (Auditor)", "Viewer2026!")
        apex_admin = create_user_if_missing("usr-apex-admin", "admin@apexhealth.internal", "Dr. David Vance (CTO)", "HealthTech2026!")

        # 3. Memberships (RBAC)
        def create_membership_if_missing(mem_id, user_id, org_id, role):
            m = Membership.query.filter_by(user_id=user_id, organization_id=org_id).first()
            if not m:
                m = Membership(id=mem_id, user_id=user_id, organization_id=org_id, role=role)
                db.session.add(m)
            return m

        create_membership_if_missing("mem-acme-admin", admin_user.id, org_acme.id, "owner")
        create_membership_if_missing("mem-acme-operator", op_user.id, org_acme.id, "operator")
        create_membership_if_missing("mem-acme-viewer", viewer_user.id, org_acme.id, "viewer")
        create_membership_if_missing("mem-apex-admin", apex_admin.id, org_apex.id, "owner")

        # 4. Production API Keys
        def create_api_key_if_missing(key_id, org_id, user_id, name, raw_secret, permissions="*"):
            key_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
            k = ApiKey.query.filter_by(key_hash=key_hash).first()
            if not k:
                k = ApiKey(
                    id=key_id,
                    organization_id=org_id,
                    user_id=user_id,
                    name=name,
                    key_prefix=raw_secret[:14] + "...",
                    key_hash=key_hash,
                    permissions=permissions,
                    is_revoked=False
                )
                db.session.add(k)
            return k

        create_api_key_if_missing(
            "key-enterprise-master",
            org_acme.id,
            admin_user.id,
            "Acme Production Cloud Connector",
            "sk_live_opsflow_enterprise_prod_2026",
            "*"
        )
        create_api_key_if_missing(
            "key-apex-gateway",
            org_apex.id,
            apex_admin.id,
            "Apex Telemetry Ingestion Key",
            "sk_live_apex_health_gateway_2026",
            "events:ingest,rules:read"
        )

        # 5. Inbound Webhook Endpoints
        def create_webhook_if_missing(wh_id, org_id, name, token, secret):
            wh = WebhookEndpoint.query.filter_by(endpoint_token=token).first()
            if not wh:
                wh = WebhookEndpoint(
                    id=wh_id,
                    organization_id=org_id,
                    name=name,
                    endpoint_token=token,
                    secret_token=secret,
                    is_active=True
                )
                db.session.add(wh)
            return wh

        create_webhook_if_missing("wh-datadog", org_acme.id, "Datadog / PagerDuty Alert Ingest", "wh_live_datadog_alerts_2026", "sec_live_hmac_sign_987")
        create_webhook_if_missing("wh-github", org_acme.id, "GitHub CI/CD Deployment Webhook", "wh_live_github_actions_2026", "sec_github_actions_secret")
        create_webhook_if_missing("wh-apex", org_apex.id, "HIPAA IoT Telemetry Receiver", "wh_live_apex_iot_telemetry", "sec_apex_hipaa_secure_key")

        # 6. Production Workflow Rules for Acme
        for bp in PRESET_BLUEPRINTS:
            rule_id = bp.get("id") or generate_uuid("rule")
            existing = AutomationRule.query.filter_by(id=rule_id, organization_id=org_acme.id).first()
            if not existing:
                r = AutomationRule(
                    id=rule_id,
                    organization_id=org_acme.id,
                    name=bp["name"],
                    description=bp.get("description", ""),
                    category=bp.get("category", "System"),
                    enabled=True,
                    priority=bp.get("priority", 10),
                    cooldown_seconds=bp.get("cooldown_seconds", 0),
                    trigger_type=bp.get("trigger", {}).get("type", "event"),
                    trigger_json=json.dumps(bp.get("trigger", {})),
                    condition_json=json.dumps(bp.get("condition", {})),
                    actions_json=json.dumps(bp.get("actions", [])),
                    steps_json=json.dumps(bp.get("steps", [])),
                    execution_count=14
                )
                db.session.add(r)

        # 7. Sample Executions & Forensic Traces with Waterfall Step Data
        if WorkflowExecution.query.filter_by(organization_id=org_acme.id).count() == 0:
            executions_data = [
                {
                    "rule_id": "template-ai-lead-qualification",
                    "rule_name": "AI Lead Qualification",
                    "trigger_event": "lead.created",
                    "status": "success",
                    "matched": True,
                    "time_ms": 14.2,
                    "payload": {
                        "name": "Robert Henderson",
                        "company": "GlobalCorp Logistics",
                        "email": "r.henderson@globalcorp.io",
                        "message": "Looking to deploy custom workflow orchestration across 4 AWS regions. Budget is $80k."
                    },
                    "steps": [
                        {"name": "Trigger: lead.created", "type": "trigger", "status": "SUCCESS", "duration_ms": 1.2},
                        {"name": "Extract Intent & Entities", "type": "ai_analysis", "status": "SUCCESS", "duration_ms": 4.1},
                        {"name": "Compute Predictive Lead Score", "type": "lead_scoring", "status": "SUCCESS", "duration_ms": 2.0},
                        {"name": "Smart Department Route (Sales)", "type": "route", "status": "SUCCESS", "duration_ms": 0.8},
                        {"name": "Draft Tailored Sales Response", "type": "email_draft", "status": "SUCCESS", "duration_ms": 3.4},
                        {"name": "Persist Lead in CRM", "type": "database_record", "status": "SUCCESS", "duration_ms": 2.7}
                    ],
                    "actions": [{"type": "database_record", "status": "success"}, {"type": "notification", "status": "success"}]
                },
                {
                    "rule_id": "blueprint-cpu-sentinel",
                    "rule_name": "High CPU Resource Sentinel",
                    "trigger_event": "system.metrics",
                    "status": "success",
                    "matched": True,
                    "time_ms": 3.8,
                    "payload": {"cpu_percent": 94.2, "host": "prod-k8s-worker-04"},
                    "steps": [
                        {"name": "Trigger: system.metrics", "type": "trigger", "status": "SUCCESS", "duration_ms": 0.9},
                        {"name": "Check CPU Threshold (>85%)", "type": "condition", "status": "SUCCESS", "duration_ms": 1.1},
                        {"name": "Dispatch Spike Alert", "type": "notification", "status": "SUCCESS", "duration_ms": 1.8}
                    ],
                    "actions": [{"type": "notification", "status": "success"}, {"type": "log_entry", "status": "success"}]
                },
                {
                    "rule_id": "blueprint-security-quarantine",
                    "rule_name": "Security Threat & Intrusion Quarantine",
                    "trigger_event": "auth.failed",
                    "status": "success",
                    "matched": True,
                    "time_ms": 5.1,
                    "payload": {"ip": "198.51.100.42", "attempts": 6},
                    "steps": [
                        {"name": "Trigger: auth.failed", "type": "trigger", "status": "SUCCESS", "duration_ms": 0.8},
                        {"name": "Intrusion Check (>=3 attempts)", "type": "condition", "status": "SUCCESS", "duration_ms": 1.2},
                        {"name": "SOC Threat Dispatch", "type": "notification", "status": "SUCCESS", "duration_ms": 3.1}
                    ],
                    "actions": [{"type": "notification", "status": "success"}, {"type": "email_dispatch", "status": "success"}]
                }
            ]

            for idx, item in enumerate(executions_data):
                exec_rec = WorkflowExecution(
                    organization_id=org_acme.id,
                    rule_id=item["rule_id"],
                    rule_name=item["rule_name"],
                    trigger_event=item["trigger_event"],
                    status=item["status"],
                    matched=item["matched"],
                    execution_time_ms=item["time_ms"],
                    input_payload_json=json.dumps(item["payload"]),
                    condition_trace_json=json.dumps([]),
                    action_results_json=json.dumps(item["actions"]),
                    steps_trace_json=json.dumps(item["steps"]),
                    executed_at=now_dt - datetime.timedelta(minutes=(idx + 1) * 12)
                )
                db.session.add(exec_rec)
                db.session.flush()

                for s_idx, st in enumerate(item["steps"]):
                    step_rec = ExecutionStep(
                        execution_id=exec_rec.id,
                        step_name=st["name"],
                        step_type=st["type"],
                        status=st["status"],
                        input_data_json="{}",
                        output_data_json=json.dumps({"simulated": True}),
                        duration_ms=st["duration_ms"],
                        created_at=now_dt - datetime.timedelta(minutes=(idx + 1) * 12)
                    )
                    db.session.add(step_rec)

        # 8. Seed Realistic Sample CRM Leads (Clearly labeled sample data)
        if Lead.query.filter_by(organization_id=org_acme.id).count() == 0:
            sample_leads = [
                Lead(
                    id="lead-sample-01",
                    organization_id=org_acme.id,
                    name="Robert Henderson",
                    email="r.henderson@globalcorp.io",
                    phone="+1 (415) 890-2134",
                    company="GlobalCorp Logistics",
                    message="Looking to deploy custom workflow orchestration across 4 AWS regions. Budget is $80k. Need discovery demo this week.",
                    intent="lead_inquiry",
                    sentiment="positive",
                    urgency_score=85,
                    lead_score=94,
                    route_department="Sales",
                    status="qualified",
                    draft_response="Hello Robert,\n\nThank you for reaching out regarding your custom workflow orchestration project for GlobalCorp Logistics. Our Enterprise Architecture team in Sales has reviewed your inquiry and is ready to schedule a discovery demo.\n\nBest regards,\nOpsFlow Enterprise",
                    is_sample=True,
                    created_at=now_dt - datetime.timedelta(hours=2)
                ),
                Lead(
                    id="lead-sample-02",
                    organization_id=org_acme.id,
                    name="Elena Rostova",
                    email="elena@fintechpay.com",
                    phone="+1 (212) 555-0182",
                    company="FinTechPay Global",
                    message="Our webhook consumer is experiencing 504 Gateway Timeouts on payments endpoint. Immediate escalation needed.",
                    intent="critical_incident",
                    sentiment="negative",
                    urgency_score=90,
                    lead_score=65,
                    route_department="Priority Support",
                    status="contacted",
                    draft_response="Hello Elena,\n\nWe have received your critical incident report regarding payments endpoint 504 timeouts. A Tier-1 SRE engineer has been assigned.",
                    is_sample=True,
                    created_at=now_dt - datetime.timedelta(hours=5)
                ),
                Lead(
                    id="lead-sample-03",
                    organization_id=org_acme.id,
                    name="Marcus Chen",
                    email="marcus@cloudmetrics.dev",
                    phone="+1 (650) 443-8890",
                    company="CloudMetrics Inc.",
                    message="Interested in the self-hosted multi-tenant plan. Could you send technical documentation and pricing?",
                    intent="lead_inquiry",
                    sentiment="neutral",
                    urgency_score=35,
                    lead_score=78,
                    route_department="Sales",
                    status="new",
                    draft_response="Hello Marcus,\n\nThank you for your interest in OpsFlow Cloud. Our sales engineering team has prepared the requested multi-tenant architecture docs.",
                    is_sample=True,
                    created_at=now_dt - datetime.timedelta(hours=8)
                ),
                Lead(
                    id="lead-sample-04",
                    organization_id=org_acme.id,
                    name="SOC Threat Monitor",
                    email="alerts@soc.opsflow.internal",
                    phone="N/A",
                    company="Acme Enterprise Security",
                    message="Quarantined threat candidate IP 198.51.100.42 after 6 brute-force authentication attempts.",
                    intent="security_threat",
                    sentiment="negative",
                    urgency_score=80,
                    lead_score=20,
                    route_department="Security Operations",
                    status="converted",
                    draft_response="Threat IP 198.51.100.42 added to dynamic firewall quarantine blacklist.",
                    is_sample=True,
                    created_at=now_dt - datetime.timedelta(hours=14)
                )
            ]
            db.session.add_all(sample_leads)

        # 9. Sample Incident Alerts
        if IncidentAlert.query.filter_by(organization_id=org_acme.id).count() == 0:
            alert1 = IncidentAlert(
                organization_id=org_acme.id,
                title="Critical CPU Saturation (94.2%)",
                message="Resource utilization exceeded 85% threshold on production node prod-k8s-worker-04.",
                severity="critical",
                status="open",
                created_at=now_dt - datetime.timedelta(minutes=15)
            )
            alert2 = IncidentAlert(
                organization_id=org_acme.id,
                title="Intrusion Detected: IP 198.51.100.42",
                message="Repeated failed authentications (6 attempts). Threat candidate automatically quarantined.",
                severity="high",
                status="acknowledged",
                acknowledged_by_id=op_user.id,
                acknowledged_at=now_dt - datetime.timedelta(minutes=30),
                created_at=now_dt - datetime.timedelta(minutes=45)
            )
            alert3 = IncidentAlert(
                organization_id=org_acme.id,
                title="Gateway 503 Auto-Restart Ping",
                message="API Gateway returned 503 on /v1/payments/process. Diagnostic ping dispatched.",
                severity="warning",
                status="resolved",
                resolved_by_id=admin_user.id,
                resolved_at=now_dt - datetime.timedelta(hours=2),
                created_at=now_dt - datetime.timedelta(hours=2, minutes=10)
            )
            db.session.add_all([alert1, alert2, alert3])

        # 10. Audit Logs
        if AuditLog.query.filter_by(organization_id=org_acme.id).count() == 0:
            db.session.add(AuditLog(
                organization_id=org_acme.id,
                user_id=admin_user.id,
                user_email=admin_user.email,
                action="workspace.provision",
                resource_type="organization",
                resource_id=org_acme.id,
                details_json=json.dumps({"plan": "enterprise"}),
                ip_address="127.0.0.1"
            ))
            db.session.add(AuditLog(
                organization_id=org_acme.id,
                user_id=admin_user.id,
                user_email=admin_user.email,
                action="apikey.create",
                resource_type="api_key",
                resource_id="key-enterprise-master",
                details_json=json.dumps({"name": "Acme Production Cloud Connector"}),
                ip_address="127.0.0.1"
            ))

        db.session.commit()
        print("[SUCCESS] Database successfully seeded with Enterprise Client Demonstration Data!")
        print("----------------------------------------------------------------------")
        print("Demo Credentials:")
        print("  [Tenant 1]: Acme Global Enterprise (slug: acme-global)")
        print("     [Admin]:    admin@opsflow.io    / AdminSecure2026!")
        print("     [Operator]: operator@opsflow.io / Operator2026!")
        print("     [Viewer]:   viewer@opsflow.io   / Viewer2026!")
        print("     [Master API Key]: sk_live_opsflow_enterprise_prod_2026")
        print("")
        print("  [Tenant 2]: Apex HealthTech Systems (slug: apex-health)")
        print("     [Admin]:    admin@apexhealth.internal / HealthTech2026!")
        print("     [Tenant API Key]: sk_live_apex_health_gateway_2026")
        print("----------------------------------------------------------------------")


if __name__ == "__main__":
    init_and_seed_database()
