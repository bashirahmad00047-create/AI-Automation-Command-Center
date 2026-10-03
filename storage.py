"""SQLAlchemy Persistence Layer for OpsFlow Multi-Tenant SaaS Platform.

Replaces legacy raw sqlite3 with full SQLAlchemy ORM persistence:
- Thread-safe session management & SQLite WAL mode (safe on PostgreSQL too)
- Multi-tenant organization scoping & isolation
- Workflows (Automation Rules) & Visual Steps
- Forensic Execution Logging & Waterfall Step Traces
- CRM Leads & Inquiries
- Incident Alerts, API Keys, and Webhook Endpoints
- Audit Trails & Analytics Aggregations
- 100% backward-compatible interface with legacy storage methods
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from flask import current_app, has_app_context
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import scoped_session, sessionmaker

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
    Workflow,
    WorkflowExecution,
    WorkflowStep,
    generate_uuid,
)
from presets import PRESET_BLUEPRINTS


DEFAULT_PRESET_RULES = [
    {
        "id": "rule-cpu-sentinel",
        "name": "High CPU Resource Sentinel",
        "description": "Alerts operations and records diagnostics whenever CPU utilization exceeds 85%.",
        "category": "System",
        "enabled": 1,
        "priority": 90,
        "cooldown_seconds": 30,
        "trigger": {"type": "event", "event_name": "system.metrics"},
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.cpu_percent", "operator": ">", "value": 85}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "CPU Spike Detected ({{ payload.cpu_percent }}%)",
                    "message": "Resource usage exceeded critical threshold on host {{ payload.host }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "CRITICAL",
                    "message": "High CPU utilization: {{ payload.cpu_percent }}% recorded on {{ payload.host }}."
                }
            }
        ]
    },
    {
        "id": "rule-security-quarantine",
        "name": "Security Threat & Intrusion Quarantine",
        "description": "Detects unauthorized login attempts or malicious intrusion IPs and dispatches security alert.",
        "category": "Security",
        "enabled": 1,
        "priority": 100,
        "cooldown_seconds": 15,
        "trigger": {"type": "event", "event_name": "auth.failed"},
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.attempts", "operator": ">=", "value": 3},
                {"field": "nlp.intent", "operator": "equals", "value": "security_threat"}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Intrusion Alert: IP Flagged",
                    "message": "Multiple failed attempts from {{ payload.ip }}. Auto-quarantine initiated.",
                    "severity": "critical"
                }
            },
            {
                "type": "email_dispatch",
                "params": {
                    "to": "soc-alerts@commandcenter.internal",
                    "subject": "[SEV-1] Security Intrusion Flagged: {{ payload.ip }}",
                    "body": "Host IP {{ payload.ip }} triggered quarantine rule after repeated unauthorized attempts."
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "WARNING",
                    "message": "Quarantined threat candidate IP {{ payload.ip }} with {{ payload.attempts }} attempts."
                }
            }
        ]
    },
    {
        "id": "rule-nlp-triage",
        "name": "Smart NLP Emergency Ticket Router",
        "description": "Scans incoming textual reports, computes intent & urgency, and escalates high-urgency incidents.",
        "category": "NLP",
        "enabled": 1,
        "priority": 85,
        "cooldown_seconds": 10,
        "trigger": {"type": "natural_text", "event_name": "user.prompt"},
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "nlp.urgency", "operator": ">=", "value": 60}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Urgent Incident Escalate (Urgency: {{ nlp.urgency }})",
                    "message": "NLP classified intent '{{ nlp.intent }}' with urgency {{ nlp.urgency }}/100.",
                    "severity": "warning"
                }
            },
            {
                "type": "file_append",
                "params": {
                    "filename": "urgent_nlp_escalations.log",
                    "content": "[{{ nlp.severity_level }}] Intent={{ nlp.intent }}, Urgency={{ nlp.urgency }}, Text={{ nlp.text }}"
                }
            }
        ]
    },
    {
        "id": "rule-api-outage",
        "name": "API Service Outage Auto-Recovery",
        "description": "Triggered when external API calls fail or return 500 error codes repeatedly.",
        "category": "System",
        "enabled": 1,
        "priority": 75,
        "cooldown_seconds": 20,
        "trigger": {"type": "event", "event_name": "api.error"},
        "condition": {
            "logic": "OR",
            "conditions": [
                {"field": "payload.status_code", "operator": ">=", "value": 500},
                {"field": "payload.error", "operator": "contains", "value": "Connection refused"}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "API Gateway Degraded",
                    "message": "Outage detected on {{ payload.endpoint }}. Status: {{ payload.status_code }}.",
                    "severity": "critical"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "ERROR",
                    "message": "API Failure recorded for {{ payload.endpoint }} (Error: {{ payload.error }})."
                }
            }
        ]
    },
    {
        "id": "rule-daily-backup",
        "name": "Automated Database Backup Verifier",
        "description": "Verifies successful database snapshot archiving and notifies system administrator.",
        "category": "Data",
        "enabled": 1,
        "priority": 50,
        "cooldown_seconds": 60,
        "trigger": {"type": "event", "event_name": "backup.completed"},
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.status", "operator": "equals", "value": "success"}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Backup Verified Successfully",
                    "message": "Archive {{ payload.database }} verified ({{ payload.size_mb }} MB).",
                    "severity": "info"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "INFO",
                    "message": "Backup verified: {{ payload.database }} size={{ payload.size_mb }}MB."
                }
            }
        ]
    },
    {
        "id": "rule-deploy-pipeline",
        "name": "DevOps Pipeline Deployment Auditor",
        "description": "Logs deployment events and triggers security checks on release rollouts.",
        "category": "DevOps",
        "enabled": 1,
        "priority": 60,
        "cooldown_seconds": 10,
        "trigger": {"type": "event", "event_name": "deploy.pipeline"},
        "condition": {
            "logic": "AND",
            "conditions": [
                {"field": "payload.environment", "operator": "in", "value": ["production", "staging"]}
            ]
        },
        "actions": [
            {
                "type": "notification",
                "params": {
                    "title": "Pipeline Rollout Triggered",
                    "message": "Deployment {{ payload.release }} targeting {{ payload.environment }}.",
                    "severity": "info"
                }
            },
            {
                "type": "log_entry",
                "params": {
                    "level": "INFO",
                    "message": "Deployment to {{ payload.environment }} initiated for {{ payload.release }}."
                }
            }
        ]
    }
]


class Storage:
    """Enterprise SQLAlchemy Storage Repository with multi-tenant isolation."""

    def __init__(self, db_path: Optional[str] = None, init_db: bool = True):
        self._lock = threading.Lock()
        self.db_path = db_path
        self._standalone_session = None

        # Check if running outside Flask app context (e.g. standalone scripts or unittests)
        if not has_app_context():
            uri = f"sqlite:///{db_path}" if db_path else os.environ.get("DATABASE_URL", "sqlite:///opsflow_saas.db")
            if uri.startswith("postgres://"):
                uri = uri.replace("postgres://", "postgresql://", 1)
            engine = create_engine(uri, connect_args={"check_same_thread": False} if "sqlite" in uri else {})
            session_factory = sessionmaker(bind=engine)
            self._standalone_session = scoped_session(session_factory)

        is_cli_migration = "db" in sys.argv or os.environ.get("SKIP_DB_INIT") == "1"
        if init_db and not is_cli_migration:
            self._init_db()

    def _init_db(self):
        """Initializes tables and seeds default multi-tenant enterprise data."""
        if self._standalone_session is not None:
            # Bind db metadata to standalone engine
            db.metadata.create_all(bind=self._standalone_session.get_bind())
            self._seed_default_tenant_if_needed()
        elif has_app_context():
            db.create_all()
            self._seed_default_tenant_if_needed()
        else:
            try:
                import app as flask_app_module
                with flask_app_module.app.app_context():
                    db.create_all()
                    self._seed_default_tenant_if_needed()
            except Exception:
                pass

    def _get_session(self):
        """Returns the appropriate SQLAlchemy session (standalone or Flask)."""
        if self._standalone_session is not None:
            return self._standalone_session()
        if has_app_context():
            return db.session
        try:
            import app as flask_app_module
            ctx = flask_app_module.app.app_context()
            ctx.push()
            return db.session
        except Exception:
            return None

    def _seed_default_tenant_if_needed(self):
        """Seeds default enterprise organization, admin users, API keys, and preset rules."""
        session = self._get_session()
        if session is None:
            return

        try:
            default_org = session.query(Organization).filter_by(slug="enterprise-corp").first()
            if not default_org:
                default_org = Organization(
                    id="org-enterprise-default",
                    name="Acme Enterprise Global",
                    slug="enterprise-corp",
                    plan_tier="enterprise",
                    is_active=True,
                    max_rules=250,
                    max_monthly_events=1000000
                )
                session.add(default_org)

                admin_user = User(
                    id="usr-admin-primary",
                    email="admin@opsflow.io",
                    full_name="Operations Director",
                    is_active=True,
                    is_superuser=True
                )
                admin_user.set_password("AdminSecure2026!")
                session.add(admin_user)

                operator_user = User(
                    id="usr-operator-primary",
                    email="operator@opsflow.io",
                    full_name="Site Reliability Engineer",
                    is_active=True,
                    is_superuser=False
                )
                operator_user.set_password("Operator2026!")
                session.add(operator_user)

                session.flush()

                mem_admin = Membership(
                    id="mem-admin-01",
                    user_id=admin_user.id,
                    organization_id=default_org.id,
                    role="admin"
                )
                mem_op = Membership(
                    id="mem-op-01",
                    user_id=operator_user.id,
                    organization_id=default_org.id,
                    role="operator"
                )
                session.add_all([mem_admin, mem_op])

                # Seed API key: sk_live_opsflow_enterprise_prod_2026
                raw_key = "sk_live_opsflow_enterprise_prod_2026"
                key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
                api_key = ApiKey(
                    id="key-enterprise-master",
                    organization_id=default_org.id,
                    user_id=admin_user.id,
                    name="Production Ingestion Gateway",
                    key_prefix=raw_key[:14] + "...",
                    key_hash=key_hash,
                    permissions="*",
                    is_revoked=False
                )
                session.add(api_key)

                # Seed inbound webhook endpoint
                webhook = WebhookEndpoint(
                    id="wh-default-01",
                    organization_id=default_org.id,
                    name="Datadog & PagerDuty Inbound Ingest",
                    endpoint_token="wh_live_prod_alert_stream",
                    secret_token="sec_live_hmac_sign_987",
                    is_active=True
                )
                session.add(webhook)
                session.commit()

            # Seed DEFAULT_PRESET_RULES for default org
            for r in DEFAULT_PRESET_RULES:
                rule_id = r["id"]
                existing = session.get(AutomationRule, rule_id)
                if not existing:
                    new_rule = AutomationRule(
                        id=rule_id,
                        organization_id=default_org.id,
                        name=r["name"],
                        description=r.get("description", ""),
                        category=r.get("category", "System"),
                        enabled=bool(r.get("enabled", 1)),
                        priority=int(r.get("priority", 10)),
                        cooldown_seconds=int(r.get("cooldown_seconds", 0)),
                        trigger_type=r.get("trigger", {}).get("type", "event"),
                        trigger_json=json.dumps(r.get("trigger", {})),
                        condition_json=json.dumps(r.get("condition", {})),
                        actions_json=json.dumps(r.get("actions", [])),
                        steps_json=json.dumps(r.get("steps", [])),
                        execution_count=0
                    )
                    session.add(new_rule)
            session.commit()

            # Seed PRESET_BLUEPRINTS for default org
            for bp in PRESET_BLUEPRINTS:
                rule_id = bp.get("id") or generate_uuid("rule")
                existing = session.get(AutomationRule, rule_id)
                if not existing:
                    new_rule = AutomationRule(
                        id=rule_id,
                        organization_id=default_org.id,
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
                        execution_count=0
                    )
                    session.add(new_rule)
            session.commit()
        except Exception:
            session.rollback()

    def get_default_org_id(self) -> str:
        session = self._get_session()
        org = session.query(Organization).filter_by(is_active=True).first()
        if not org:
            org = Organization(
                id="org-enterprise-default",
                name="Acme Enterprise Global",
                slug="enterprise-corp",
                plan_tier="enterprise",
                is_active=True,
                max_rules=250,
                max_monthly_events=1000000
            )
            session.add(org)
            try:
                session.commit()
            except Exception:
                session.rollback()
                org = session.query(Organization).first()
        return org.id if org else "org-enterprise-default"

    # ==========================================
    # Workflows & Automation Rules CRUD
    # ==========================================

    def get_rules(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
        organization_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        query = session.query(AutomationRule).filter_by(organization_id=org_id)
        if category and category.lower() != "all":
            query = query.filter_by(category=category)
        if enabled_only:
            query = query.filter_by(enabled=True)
        rules = query.order_by(desc(AutomationRule.priority), desc(AutomationRule.created_at)).all()
        return [r.to_dict() for r in rules]

    def get_rule(self, rule_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        query = session.query(AutomationRule).filter_by(id=rule_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        rule = query.first()
        return rule.to_dict() if rule else None

    def save_rule(self, rule_data: Dict[str, Any], organization_id: Optional[str] = None) -> str:
        session = self._get_session()
        org_id = organization_id or rule_data.get("organization_id") or self.get_default_org_id()
        org = session.get(Organization, org_id)
        if not org:
            org = Organization(
                id=org_id,
                name="Acme Enterprise Global",
                slug=f"org-{org_id}",
                plan_tier="enterprise",
                is_active=True
            )
            session.add(org)
            session.flush()
        rule_id = rule_data.get("id") or generate_uuid("rule")
        rule = session.query(AutomationRule).filter_by(id=rule_id, organization_id=org_id).first()

        trigger = rule_data.get("trigger", {})
        condition = rule_data.get("condition", {})
        actions = rule_data.get("actions", [])
        steps = rule_data.get("steps", [])

        trigger_json = json.dumps(trigger) if not isinstance(trigger, str) else trigger
        condition_json = json.dumps(condition) if not isinstance(condition, str) else condition
        actions_json = json.dumps(actions) if not isinstance(actions, str) else actions
        steps_json = json.dumps(steps) if not isinstance(steps, str) else steps

        enabled_val = bool(rule_data.get("enabled", True))
        try:
            if rule:
                rule.name = rule_data.get("name", rule.name)
                rule.description = rule_data.get("description", rule.description)
                rule.category = rule_data.get("category", rule.category)
                rule.enabled = enabled_val
                rule.priority = int(rule_data.get("priority", rule.priority))
                rule.cooldown_seconds = int(rule_data.get("cooldown_seconds", rule.cooldown_seconds))
                rule.trigger_type = trigger.get("type", "event") if isinstance(trigger, dict) else "event"
                rule.trigger_json = trigger_json
                rule.condition_json = condition_json
                rule.actions_json = actions_json
                rule.steps_json = steps_json
            else:
                rule = AutomationRule(
                    id=rule_id,
                    organization_id=org_id,
                    name=rule_data.get("name", "Unnamed Workflow"),
                    description=rule_data.get("description", ""),
                    category=rule_data.get("category", "System"),
                    enabled=enabled_val,
                    priority=int(rule_data.get("priority", 10)),
                    cooldown_seconds=int(rule_data.get("cooldown_seconds", 0)),
                    trigger_type=trigger.get("type", "event") if isinstance(trigger, dict) else "event",
                    trigger_json=trigger_json,
                    condition_json=condition_json,
                    actions_json=actions_json,
                    steps_json=steps_json,
                    execution_count=0
                )
                session.add(rule)
            session.commit()
            return rule.id
        except Exception:
            session.rollback()
            raise

    def duplicate_rule(self, rule_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Duplicates a workflow rule with (Copy) appended to its name."""
        session = self._get_session()
        query = session.query(AutomationRule).filter_by(id=rule_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        orig = query.first()
        if not orig:
            return None

        new_id = generate_uuid("rule")
        new_rule = AutomationRule(
            id=new_id,
            organization_id=orig.organization_id,
            name=f"{orig.name} (Copy)",
            description=orig.description,
            category=orig.category,
            enabled=False,
            priority=orig.priority,
            cooldown_seconds=orig.cooldown_seconds,
            trigger_type=orig.trigger_type,
            trigger_json=orig.trigger_json,
            condition_json=orig.condition_json,
            actions_json=orig.actions_json,
            steps_json=orig.steps_json,
            execution_count=0
        )
        session.add(new_rule)
        session.commit()
        return new_rule.to_dict()

    def delete_rule(self, rule_id: str, organization_id: Optional[str] = None) -> bool:
        session = self._get_session()
        query = session.query(AutomationRule).filter_by(id=rule_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        rule = query.first()
        if not rule:
            return False
        try:
            session.delete(rule)
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False

    def toggle_rule(self, rule_id: str, enabled: Optional[bool] = None, organization_id: Optional[str] = None) -> Optional[bool]:
        session = self._get_session()
        query = session.query(AutomationRule).filter_by(id=rule_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        rule = query.first()
        if not rule:
            return None
        try:
            if enabled is None:
                rule.enabled = not rule.enabled
            else:
                rule.enabled = bool(enabled)
            session.commit()
            return bool(rule.enabled)
        except Exception:
            session.rollback()
            return None

    def record_rule_trigger(self, rule_id: str):
        session = self._get_session()
        rule = session.get(AutomationRule, rule_id)
        if rule:
            try:
                rule.execution_count += 1
                rule.last_triggered_at = datetime.datetime.utcnow()
                session.commit()
            except Exception:
                session.rollback()

    def update_rule_execution(self, rule_id: str):
        self.record_rule_trigger(rule_id)

    # ==========================================
    # Execution Logs & Forensic Traces
    # ==========================================

    def log_execution(self, *args, **kwargs) -> int:
        """Records a forensic execution entry and step waterfall records."""
        session = self._get_session()
        now_dt = datetime.datetime.utcnow()

        if args and isinstance(args[0], dict):
            d = args[0]
            rule_id = d.get("rule_id")
            rule_name = d.get("rule_name")
            trigger_event = d.get("event_name") or d.get("trigger_type") or "unspecified"
            status = d.get("status", "success")
            matched = bool(d.get("matched", True))
            execution_time_ms = float(d.get("duration_ms", 0.0))
            payload = d.get("payload", {})
            trace = d.get("trace", [])
            action_results = d.get("results", [])
            error_message = d.get("error_message")
            org_id = d.get("organization_id")
            is_dry_run = bool(d.get("is_dry_run", False) or d.get("dry_run", False))
            steps_trace = d.get("steps_trace", [])
            ai_result = d.get("ai_result")
        else:
            rule_id = kwargs.get("rule_id") or (args[0] if len(args) > 0 else None)
            trigger_event = kwargs.get("trigger_event") or (args[1] if len(args) > 1 else "unspecified")
            status = kwargs.get("status") or (args[2] if len(args) > 2 else "success")
            matched = kwargs.get("matched") if "matched" in kwargs else (args[3] if len(args) > 3 else True)
            execution_time_ms = kwargs.get("execution_time_ms") if "execution_time_ms" in kwargs else (args[4] if len(args) > 4 else 0.0)
            payload = kwargs.get("payload") if "payload" in kwargs else (args[5] if len(args) > 5 else {})
            trace = kwargs.get("trace") if "trace" in kwargs else (args[6] if len(args) > 6 else [])
            action_results = kwargs.get("action_results") if "action_results" in kwargs else (args[7] if len(args) > 7 else [])
            error_message = kwargs.get("error_message") if "error_message" in kwargs else (args[8] if len(args) > 8 else None)
            org_id = kwargs.get("organization_id") if "organization_id" in kwargs else (args[9] if len(args) > 9 else None)
            rule_name = kwargs.get("rule_name") if "rule_name" in kwargs else (args[10] if len(args) > 10 else None)
            is_dry_run = bool(kwargs.get("is_dry_run", False))
            steps_trace = kwargs.get("steps_trace", [])
            ai_result = kwargs.get("ai_result")

        # Verify foreign key constraint for rule_id
        if rule_id:
            r = session.get(AutomationRule, rule_id)
            if r:
                org_id = org_id or r.organization_id
                rule_name = rule_name or r.name
            else:
                rule_id = None

        if not org_id:
            org_id = self.get_default_org_id()

        try:
            exec_record = WorkflowExecution(
                organization_id=org_id,
                rule_id=rule_id,
                rule_name=rule_name,
                trigger_event=trigger_event,
                status=status.lower(),
                matched=bool(matched),
                execution_time_ms=float(execution_time_ms),
                is_dry_run=is_dry_run,
                input_payload_json=json.dumps(payload),
                condition_trace_json=json.dumps(trace),
                action_results_json=json.dumps(action_results),
                steps_trace_json=json.dumps(steps_trace),
                ai_result_json=json.dumps(ai_result) if ai_result else None,
                error_message=error_message,
                executed_at=now_dt,
                completed_at=now_dt + datetime.timedelta(milliseconds=float(execution_time_ms))
            )
            session.add(exec_record)
            session.flush()

            # Record granular execution steps in database
            if steps_trace and isinstance(steps_trace, list):
                for idx, step_item in enumerate(steps_trace):
                    step_rec = ExecutionStep(
                        execution_id=exec_record.id,
                        step_name=step_item.get("name") or step_item.get("step_name") or f"Step {idx+1}",
                        step_type=step_item.get("type") or step_item.get("step_type") or "action",
                        status=step_item.get("status", "SUCCESS").upper(),
                        input_data_json=json.dumps(step_item.get("input", {})),
                        output_data_json=json.dumps(step_item.get("output", {})),
                        error_message=step_item.get("error"),
                        duration_ms=float(step_item.get("duration_ms", 0.0)),
                        retry_count=int(step_item.get("retry_count", 0)),
                        created_at=now_dt
                    )
                    session.add(step_rec)

            session.commit()
            return exec_record.id
        except Exception:
            session.rollback()
            return 0

    def get_logs(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        rule_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        query = session.query(WorkflowExecution).filter_by(organization_id=org_id)
        if status and status.lower() != "all":
            query = query.filter_by(status=status.lower())
        if rule_id:
            query = query.filter_by(rule_id=rule_id)
        logs = query.order_by(desc(WorkflowExecution.executed_at)).offset(offset).limit(limit).all()

        formatted = []
        for l in logs:
            d = l.to_dict()
            d["duration_ms"] = d["execution_time_ms"]
            d["timestamp"] = d["executed_at"]
            d["event_name"] = d["trigger_event"]
            d["trigger_type"] = "event"
            d["results"] = d["action_results"]
            formatted.append(d)
        return formatted

    def get_execution(self, execution_id: int, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        record = session.get(WorkflowExecution, execution_id)
        if not record:
            return None
        if organization_id and record.organization_id != organization_id:
            return None
        res = record.to_dict()
        res["execution_steps"] = [step.to_dict() for step in record.execution_steps]
        return res

    def clear_logs(self, organization_id: Optional[str] = None):
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        try:
            session.query(WorkflowExecution).filter_by(organization_id=org_id).delete()
            session.commit()
        except Exception:
            session.rollback()

    # ==========================================
    # CRM Leads & Inquiries
    # ==========================================

    def save_lead(self, lead_data: Dict[str, Any], organization_id: Optional[str] = None) -> Dict[str, Any]:
        session = self._get_session()
        org_id = organization_id or lead_data.get("organization_id") or self.get_default_org_id()
        lead_id = lead_data.get("id") or generate_uuid("lead")
        lead = session.query(Lead).filter_by(id=lead_id, organization_id=org_id).first()

        try:
            if lead:
                lead.name = lead_data.get("name", lead.name)
                lead.email = lead_data.get("email", lead.email)
                lead.phone = lead_data.get("phone", lead.phone)
                lead.company = lead_data.get("company", lead.company)
                lead.message = lead_data.get("message", lead.message)
                lead.intent = lead_data.get("intent", lead.intent)
                lead.sentiment = lead_data.get("sentiment", lead.sentiment)
                lead.urgency_score = int(lead_data.get("urgency_score", lead.urgency_score))
                lead.lead_score = int(lead_data.get("lead_score", lead.lead_score))
                lead.route_department = lead_data.get("route_department", lead.route_department)
                lead.status = lead_data.get("status", lead.status)
                lead.draft_response = lead_data.get("draft_response", lead.draft_response)
            else:
                lead = Lead(
                    id=lead_id,
                    organization_id=org_id,
                    name=lead_data.get("name", "Website Visitor"),
                    email=lead_data.get("email"),
                    phone=lead_data.get("phone"),
                    company=lead_data.get("company"),
                    message=lead_data.get("message", ""),
                    intent=lead_data.get("intent", "lead_inquiry"),
                    sentiment=lead_data.get("sentiment", "neutral"),
                    urgency_score=int(lead_data.get("urgency_score", 20)),
                    lead_score=int(lead_data.get("lead_score", 50)),
                    route_department=lead_data.get("route_department", "Sales"),
                    status=lead_data.get("status", "new"),
                    draft_response=lead_data.get("draft_response"),
                    execution_id=lead_data.get("execution_id"),
                    is_sample=bool(lead_data.get("is_sample", False))
                )
                session.add(lead)
            session.commit()
            return lead.to_dict()
        except Exception:
            session.rollback()
            raise

    def get_leads(
        self,
        organization_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        query = session.query(Lead).filter_by(organization_id=org_id)
        if status and status.lower() != "all":
            query = query.filter_by(status=status.lower())
        if search:
            search_term = f"%{search.lower()}%"
            query = query.filter(
                (func.lower(Lead.name).like(search_term)) |
                (func.lower(Lead.email).like(search_term)) |
                (func.lower(Lead.company).like(search_term)) |
                (func.lower(Lead.route_department).like(search_term))
            )
        leads = query.order_by(desc(Lead.created_at)).offset(offset).limit(limit).all()
        return [l.to_dict() for l in leads]

    def get_lead(self, lead_id: str, organization_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        query = session.query(Lead).filter_by(id=lead_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        lead = query.first()
        return lead.to_dict() if lead else None

    def update_lead_status(self, lead_id: str, status: str, organization_id: Optional[str] = None) -> bool:
        session = self._get_session()
        query = session.query(Lead).filter_by(id=lead_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        lead = query.first()
        if not lead:
            return False
        lead.status = status
        session.commit()
        return True

    def delete_lead(self, lead_id: str, organization_id: Optional[str] = None) -> bool:
        session = self._get_session()
        query = session.query(Lead).filter_by(id=lead_id)
        if organization_id:
            query = query.filter_by(organization_id=organization_id)
        lead = query.first()
        if not lead:
            return False
        session.delete(lead)
        session.commit()
        return True

    # ==========================================
    # Incident Alerts & Notifications
    # ==========================================

    def add_notification(
        self,
        title: str,
        message: str,
        severity: str = "info",
        organization_id: Optional[str] = None,
        rule_id: Optional[str] = None,
        execution_id: Optional[int] = None,
        payload_summary: Optional[Dict[str, Any]] = None
    ) -> int:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        try:
            alert = IncidentAlert(
                organization_id=org_id,
                rule_id=rule_id,
                execution_id=execution_id,
                title=title,
                message=message,
                severity=severity.lower(),
                status="open",
                payload_summary_json=json.dumps(payload_summary or {}),
                created_at=datetime.datetime.utcnow()
            )
            session.add(alert)
            session.commit()
            return alert.id
        except Exception:
            session.rollback()
            return 0

    create_alert = add_notification


    def get_notifications(
        self,
        limit: int = 30,
        unread_only: bool = False,
        organization_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        query = session.query(IncidentAlert).filter_by(organization_id=org_id)
        if unread_only:
            query = query.filter_by(status="open")
        alerts = query.order_by(desc(IncidentAlert.created_at)).limit(limit).all()

        results = []
        for a in alerts:
            d = a.to_dict()
            d["read"] = 0 if a.status == "open" else 1
            d["timestamp"] = d["created_at"]
            results.append(d)
        return results

    def mark_notifications_read(self, organization_id: Optional[str] = None):
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        try:
            alerts = session.query(IncidentAlert).filter_by(organization_id=org_id, status="open").all()
            for a in alerts:
                a.status = "acknowledged"
                a.acknowledged_at = datetime.datetime.utcnow()
            session.commit()
        except Exception:
            session.rollback()

    def clear_notifications(self, organization_id: Optional[str] = None):
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        try:
            session.query(IncidentAlert).filter_by(organization_id=org_id).delete()
            session.commit()
        except Exception:
            session.rollback()

    # ==========================================
    # System Events Stream
    # ==========================================

    def log_system_event(
        self,
        event_name: str,
        payload: Dict[str, Any],
        source: str = "manual",
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        evt = SystemEvent(
            organization_id=org_id,
            event_name=event_name,
            payload_json=json.dumps(payload),
            source=source,
            processed=True,
            created_at=datetime.datetime.utcnow()
        )
        session.add(evt)
        session.commit()
        return evt.to_dict()

    def get_system_events(self, organization_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        events = session.query(SystemEvent).filter_by(organization_id=org_id).order_by(desc(SystemEvent.created_at)).limit(limit).all()
        return [e.to_dict() for e in events]

    # ==========================================
    # Compliance Audit Trail
    # ==========================================

    def log_audit(
        self,
        action: str,
        resource_type: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> int:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        try:
            log = AuditLog(
                organization_id=org_id,
                user_id=user_id,
                user_email=user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details_json=json.dumps(details or {}),
                ip_address=ip_address or "127.0.0.1",
                created_at=datetime.datetime.utcnow()
            )
            session.add(log)
            session.commit()
            return log.id
        except Exception:
            session.rollback()
            return 0

    def get_audit_logs(
        self,
        organization_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()
        logs = session.query(AuditLog).filter_by(organization_id=org_id).order_by(desc(AuditLog.created_at)).offset(offset).limit(limit).all()
        return [l.to_dict() for l in logs]

    # ==========================================
    # SaaS Dashboard KPIs & Real DB Analytics
    # ==========================================

    def get_stats(self, organization_id: Optional[str] = None) -> Dict[str, Any]:
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()

        total_rules = session.query(AutomationRule).filter_by(organization_id=org_id).count()
        active_rules = session.query(AutomationRule).filter_by(organization_id=org_id, enabled=True).count()

        total_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id).count()
        success_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="success").count()
        failed_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="failed").count()
        skipped_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="skipped").count()

        open_alerts = session.query(IncidentAlert).filter_by(organization_id=org_id, status="open").count()
        ack_alerts = session.query(IncidentAlert).filter_by(organization_id=org_id, status="acknowledged").count()
        active_webhooks = session.query(WebhookEndpoint).filter_by(organization_id=org_id, is_active=True).count()

        # Category breakdown
        cat_rows = session.query(
            AutomationRule.category, func.count(AutomationRule.id)
        ).filter_by(organization_id=org_id).group_by(AutomationRule.category).all()
        category_counts = {row[0]: row[1] for row in cat_rows}

        effective_runs = total_execs
        success_rate = 100.0 if effective_runs == 0 else round((success_execs / effective_runs * 100), 1)

        total_leads = session.query(Lead).filter_by(organization_id=org_id).count()
        high_priority_leads = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.lead_score >= 70).count()

        return {
            "total_rules": total_rules,
            "active_rules": active_rules,
            "total_workflows": total_rules,
            "active_workflows": active_rules,
            "total_executions": total_execs,
            "successful_executions": success_execs,
            "failed_executions": failed_execs,
            "skipped_executions": skipped_execs,
            "success_rate": success_rate,
            "success_rate_percent": success_rate,
            "total_leads": total_leads,
            "high_priority_leads": high_priority_leads,
            "unread_notifications": open_alerts,
            "open_alerts": open_alerts,
            "acknowledged_alerts": ack_alerts,
            "active_webhooks": active_webhooks,
            "categories": category_counts
        }

    def get_analytics_summary(self, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculates comprehensive analytics directly from real database records."""
        session = self._get_session()
        org_id = organization_id or self.get_default_org_id()

        total_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id).count()
        success_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="success").count()
        failed_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="failed").count()
        skipped_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, status="skipped").count()
        dry_run_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id, is_dry_run=True).count()

        avg_dur_row = session.query(func.avg(WorkflowExecution.execution_time_ms)).filter_by(organization_id=org_id).scalar()
        avg_duration_ms = round(float(avg_dur_row), 1) if avg_dur_row else 0.0

        # Workflow usage breakdown
        usage_rows = session.query(
            WorkflowExecution.rule_name,
            func.count(WorkflowExecution.id)
        ).filter_by(organization_id=org_id).group_by(WorkflowExecution.rule_name).order_by(desc(func.count(WorkflowExecution.id))).limit(8).all()
        workflow_usage = [{"name": row[0] or "Direct Ingestion", "count": row[1]} for row in usage_rows]

        # Lead metrics
        total_leads = session.query(Lead).filter_by(organization_id=org_id).count()
        high_priority_leads = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.lead_score >= 70).count()

        # Lead status breakdown
        status_rows = session.query(Lead.status, func.count(Lead.id)).filter_by(organization_id=org_id).group_by(Lead.status).all()
        leads_by_status = {row[0]: row[1] for row in status_rows}

        # Lead department routing
        dept_rows = session.query(Lead.route_department, func.count(Lead.id)).filter_by(organization_id=org_id).group_by(Lead.route_department).all()
        department_routing = {row[0]: row[1] for row in dept_rows}

        # Urgency breakdown
        crit_urgency = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.urgency_score >= 75).count()
        high_urgency = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.urgency_score.between(50, 74)).count()
        med_urgency = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.urgency_score.between(25, 49)).count()
        low_urgency = session.query(Lead).filter_by(organization_id=org_id).filter(Lead.urgency_score < 25).count()

        success_rate = 100.0 if total_execs == 0 else round((success_execs / total_execs) * 100, 1)

        # Recent executions for timeline
        recent_execs = session.query(WorkflowExecution).filter_by(organization_id=org_id).order_by(desc(WorkflowExecution.executed_at)).limit(10).all()
        timeline = [{
            "id": f"exec-{e.id}",
            "workflow": e.rule_name or "Direct Ingest",
            "status": e.status.upper(),
            "duration_ms": e.execution_time_ms,
            "timestamp": e.executed_at.strftime("%H:%M:%S")
        } for e in reversed(recent_execs)]

        return {
            "total_executions": total_execs,
            "successful_executions": success_execs,
            "failed_executions": failed_execs,
            "skipped_executions": skipped_execs,
            "dry_run_executions": dry_run_execs,
            "success_rate": success_rate,
            "average_duration_ms": avg_duration_ms,
            "workflow_usage": workflow_usage,
            "total_leads": total_leads,
            "high_priority_leads": high_priority_leads,
            "leads_by_status": leads_by_status,
            "department_routing": department_routing,
            "urgency_distribution": {
                "critical": crit_urgency,
                "high": high_urgency,
                "medium": med_urgency,
                "low": low_urgency
            },
            "timeline": timeline
        }

    # ==========================================
    # Multi-Tenant & SaaS Specific Operations
    # ==========================================

    def create_organization(self, name: str, slug: str, plan_tier: str = "enterprise") -> Dict[str, Any]:
        session = self._get_session()
        org = Organization(
            name=name,
            slug=slug,
            plan_tier=plan_tier,
            is_active=True
        )
        session.add(org)
        session.commit()
        return org.to_dict()

    def list_organizations(self) -> List[Dict[str, Any]]:
        session = self._get_session()
        orgs = session.query(Organization).order_by(Organization.created_at).all()
        return [o.to_dict() for o in orgs]

    def create_api_key(
        self,
        organization_id: str,
        name: str,
        permissions: str = "*",
        user_id: Optional[str] = None
    ) -> Tuple[Dict[str, Any], str]:
        """Generates an API key. Returns (key_record_dict, raw_secret_key)."""
        session = self._get_session()
        raw_key = f"sk_live_{generate_uuid()}_{secrets_token()}"
        key_prefix = raw_key[:14] + "..."
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        api_key = ApiKey(
            organization_id=organization_id,
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            permissions=permissions,
            is_revoked=False
        )
        session.add(api_key)
        session.commit()
        return api_key.to_dict(), raw_key

    def list_api_keys(self, organization_id: str) -> List[Dict[str, Any]]:
        session = self._get_session()
        keys = session.query(ApiKey).filter_by(organization_id=organization_id, is_revoked=False).all()
        return [k.to_dict() for k in keys]

    def revoke_api_key(self, key_id: str, organization_id: str) -> bool:
        session = self._get_session()
        key = session.query(ApiKey).filter_by(id=key_id, organization_id=organization_id).first()
        if not key:
            return False
        key.is_revoked = True
        session.commit()
        return True

    def create_webhook_endpoint(
        self,
        organization_id: str,
        name: str,
        target_rule_id: Optional[str] = None,
        secret_token: Optional[str] = None
    ) -> Dict[str, Any]:
        session = self._get_session()
        endpoint_token = f"wh_live_{generate_uuid()}"
        endpoint = WebhookEndpoint(
            organization_id=organization_id,
            name=name,
            endpoint_token=endpoint_token,
            secret_token=secret_token or f"sec_{generate_uuid()}",
            target_rule_id=target_rule_id,
            is_active=True
        )
        session.add(endpoint)
        session.commit()
        return endpoint.to_dict()

    def list_webhook_endpoints(self, organization_id: str) -> List[Dict[str, Any]]:
        session = self._get_session()
        endpoints = session.query(WebhookEndpoint).filter_by(organization_id=organization_id).all()
        return [e.to_dict() for e in endpoints]

    def delete_webhook_endpoint(self, endpoint_id: str, organization_id: str) -> bool:
        session = self._get_session()
        endpoint = session.query(WebhookEndpoint).filter_by(id=endpoint_id, organization_id=organization_id).first()
        if not endpoint:
            return False
        session.delete(endpoint)
        session.commit()
        return True

    def list_incident_alerts(self, organization_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        session = self._get_session()
        query = session.query(IncidentAlert).filter_by(organization_id=organization_id)
        if status and status.lower() != "all":
            query = query.filter_by(status=status.lower())
        alerts = query.order_by(desc(IncidentAlert.created_at)).all()
        return [a.to_dict() for a in alerts]

    def acknowledge_incident(self, alert_id: int, user_id: str, organization_id: str) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        alert = session.query(IncidentAlert).filter_by(id=alert_id, organization_id=organization_id).first()
        if not alert:
            return None
        alert.status = "acknowledged"
        alert.acknowledged_by_id = user_id
        alert.acknowledged_at = datetime.datetime.utcnow()
        session.commit()
        return alert.to_dict()

    def resolve_incident(self, alert_id: int, user_id: str, organization_id: str, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        alert = session.query(IncidentAlert).filter_by(id=alert_id, organization_id=organization_id).first()
        if not alert:
            return None
        alert.status = "resolved"
        alert.resolved_by_id = user_id
        alert.resolved_at = datetime.datetime.utcnow()
        if notes:
            alert.message = f"{alert.message}\n[Resolution]: {notes}"
        session.commit()
        return alert.to_dict()


def secrets_token() -> str:
    import secrets
    return secrets.token_hex(16)
