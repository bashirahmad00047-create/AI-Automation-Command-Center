"""SQLAlchemy ORM Data Models for OpsFlow Multi-Tenant SaaS Platform.

Defines schemas for:
- Organizations (Tenants)
- Users and RBAC Memberships
- API Keys
- Workflows & Automation Rules
- Workflow Steps (Visual Builder Pipeline)
- Workflow Executions & Forensic Traces
- Execution Steps (Waterfall Execution Trace)
- CRM Leads & Inquiries
- Incident Alerts
- Webhook Ingestion Endpoints
- Compliance Audit Logs
- System Events Stream
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Dict, List, Optional
from werkzeug.security import check_password_hash, generate_password_hash

from database import db


def generate_uuid(prefix: str = "") -> str:
    """Generate a readable prefixed UUID."""
    val = uuid.uuid4().hex
    return f"{prefix}-{val[:12]}" if prefix else val


class Organization(db.Model):
    """Multi-tenant Organization workspace."""
    __tablename__ = "organizations"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("org"))
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    plan_tier = db.Column(db.String(32), nullable=False, default="enterprise")  # starter, pro, enterprise
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    max_rules = db.Column(db.Integer, nullable=False, default=100)
    max_monthly_events = db.Column(db.Integer, nullable=False, default=500000)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    # Relationships
    memberships = db.relationship("Membership", backref="organization", cascade="all, delete-orphan", lazy="select")
    rules = db.relationship("AutomationRule", backref="organization", cascade="all, delete-orphan", lazy="select")
    executions = db.relationship("WorkflowExecution", backref="organization", cascade="all, delete-orphan", lazy="select")
    alerts = db.relationship("IncidentAlert", backref="organization", cascade="all, delete-orphan", lazy="select")
    api_keys = db.relationship("ApiKey", backref="organization", cascade="all, delete-orphan", lazy="select")
    webhook_endpoints = db.relationship("WebhookEndpoint", backref="organization", cascade="all, delete-orphan", lazy="select")
    audit_logs = db.relationship("AuditLog", backref="organization", cascade="all, delete-orphan", lazy="select")
    leads = db.relationship("Lead", backref="organization", cascade="all, delete-orphan", lazy="select")
    events = db.relationship("SystemEvent", backref="organization", cascade="all, delete-orphan", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "plan_tier": self.plan_tier,
            "is_active": self.is_active,
            "max_rules": self.max_rules,
            "max_monthly_events": self.max_monthly_events,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class User(db.Model):
    """User account with credentials and profile."""
    __tablename__ = "users"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("usr"))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(128), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_superuser = db.Column(db.Boolean, nullable=False, default=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    # Relationships
    memberships = db.relationship("Membership", backref="user", cascade="all, delete-orphan", lazy="select")
    api_keys = db.relationship("ApiKey", backref="user", lazy="select")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "last_login_at": self.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_login_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class Membership(db.Model):
    """Associates a User with an Organization workspace and assigns an RBAC role."""
    __tablename__ = "memberships"
    __table_args__ = (db.UniqueConstraint("user_id", "organization_id", name="uq_user_org"),)

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("mem"))
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, default="operator")  # owner, admin, operator, viewer
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "role": self.role,
            "user": self.user.to_dict() if self.user else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class ApiKey(db.Model):
    """Scoped API Keys for programmatic integration."""
    __tablename__ = "api_keys"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("key"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = db.Column(db.String(128), nullable=False)
    key_prefix = db.Column(db.String(24), nullable=False)  # e.g., sk_live_7a8b9c...
    key_hash = db.Column(db.String(128), nullable=False, index=True)  # SHA-256 hash of secret key
    permissions = db.Column(db.Text, nullable=False, default="*")  # comma-separated or JSON list
    is_revoked = db.Column(db.Boolean, nullable=False, default=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "permissions": self.permissions.split(",") if "," in self.permissions else [self.permissions],
            "is_revoked": self.is_revoked,
            "last_used_at": self.last_used_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_used_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class AutomationRule(db.Model):
    """Tenant-scoped Automation Workflow Rule."""
    __tablename__ = "automation_rules"

    id = db.Column(db.String(64), primary_key=True)
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(64), nullable=False, default="System")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    priority = db.Column(db.Integer, nullable=False, default=10)
    cooldown_seconds = db.Column(db.Integer, nullable=False, default=0)
    
    # JSON-encoded workflow definitions
    trigger_type = db.Column(db.String(32), nullable=False, default="event")
    trigger_json = db.Column(db.Text, nullable=False, default="{}")
    condition_json = db.Column(db.Text, nullable=False, default="{}")
    actions_json = db.Column(db.Text, nullable=False, default="[]")
    steps_json = db.Column(db.Text, nullable=False, default="[]")  # Visual builder multi-step pipeline
    
    execution_count = db.Column(db.Integer, nullable=False, default=0)
    last_triggered_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    executions = db.relationship("WorkflowExecution", backref="rule", cascade="all, delete-orphan", lazy="select")
    alerts = db.relationship("IncidentAlert", backref="rule", lazy="select")
    steps = db.relationship("WorkflowStep", backref="workflow", cascade="all, delete-orphan", lazy="select")

    def get_trigger(self) -> Dict[str, Any]:
        try:
            return json.loads(self.trigger_json)
        except Exception:
            return {}

    def get_condition(self) -> Dict[str, Any]:
        try:
            return json.loads(self.condition_json)
        except Exception:
            return {}

    def get_actions(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.actions_json)
        except Exception:
            return []

    def get_steps(self) -> List[Dict[str, Any]]:
        try:
            loaded = json.loads(self.steps_json)
            if isinstance(loaded, list) and loaded:
                return loaded
        except Exception:
            pass
        # Synthesize steps from trigger, condition, and actions if steps_json is empty
        synth = []
        synth.append({"type": "trigger", "config": self.get_trigger()})
        cond = self.get_condition()
        if cond and cond.get("conditions"):
            synth.append({"type": "condition", "config": cond})
        for act in self.get_actions():
            synth.append({"type": act.get("type", "notification"), "config": act.get("params", {})})
        synth.append({"type": "end", "config": {}})
        return synth

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "description": self.description or "",
            "category": self.category,
            "enabled": 1 if self.enabled else 0,
            "status": "active" if self.enabled else "disabled",
            "priority": self.priority,
            "cooldown_seconds": self.cooldown_seconds,
            "trigger": self.get_trigger(),
            "condition": self.get_condition(),
            "actions": self.get_actions(),
            "steps": self.get_steps(),
            "execution_count": self.execution_count,
            "last_triggered": self.last_triggered_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_triggered_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


# Workflow is a direct alias for AutomationRule to support modern terminology seamlessly
Workflow = AutomationRule


class WorkflowStep(db.Model):
    """Configured step in a visual workflow."""
    __tablename__ = "workflow_steps"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("step"))
    workflow_id = db.Column(db.String(64), db.ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    step_order = db.Column(db.Integer, nullable=False, default=1)
    step_type = db.Column(db.String(64), nullable=False)  # trigger, condition, ai_analysis, lead_scoring, etc.
    name = db.Column(db.String(128), nullable=False)
    config_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def get_config(self) -> Dict[str, Any]:
        try:
            return json.loads(self.config_json)
        except Exception:
            return {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_order": self.step_order,
            "step_type": self.step_type,
            "name": self.name,
            "config": self.get_config(),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class WorkflowExecution(db.Model):
    """Forensic execution record and audit trail."""
    __tablename__ = "workflow_executions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = db.Column(db.String(64), db.ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    rule_name = db.Column(db.String(255), nullable=True)
    trigger_event = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(32), nullable=False)  # SUCCESS, FAILED, SKIPPED, DRY_RUN
    matched = db.Column(db.Boolean, nullable=False, default=False)
    execution_time_ms = db.Column(db.Float, nullable=False, default=0.0)
    is_dry_run = db.Column(db.Boolean, nullable=False, default=False)
    
    input_payload_json = db.Column(db.Text, nullable=False, default="{}")
    condition_trace_json = db.Column(db.Text, nullable=False, default="[]")
    action_results_json = db.Column(db.Text, nullable=False, default="[]")
    steps_trace_json = db.Column(db.Text, nullable=False, default="[]")
    ai_result_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    executed_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Granular step traces
    execution_steps = db.relationship("ExecutionStep", backref="execution", cascade="all, delete-orphan", lazy="select")
    leads = db.relationship("Lead", backref="execution", lazy="select")

    @property
    def workflow_id(self) -> Optional[str]:
        return self.rule_id

    @property
    def workflow_name(self) -> Optional[str]:
        return self.rule_name

    def to_dict(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.input_payload_json)
        except Exception:
            payload = {}
        try:
            trace = json.loads(self.condition_trace_json)
        except Exception:
            trace = []
        try:
            results = json.loads(self.action_results_json)
        except Exception:
            results = []
        try:
            steps_trace = json.loads(self.steps_trace_json) if self.steps_trace_json else []
        except Exception:
            steps_trace = []
        try:
            ai_res = json.loads(self.ai_result_json) if self.ai_result_json else None
        except Exception:
            ai_res = None

        return {
            "id": self.id,
            "execution_id": f"exec-{self.id}",
            "organization_id": self.organization_id,
            "rule_id": self.rule_id,
            "workflow_id": self.rule_id,
            "rule_name": self.rule_name,
            "workflow_name": self.rule_name,
            "trigger_event": self.trigger_event,
            "trigger": self.trigger_event,
            "status": self.status.upper() if self.status else "SUCCESS",
            "matched": 1 if self.matched else 0,
            "execution_time_ms": self.execution_time_ms,
            "duration_ms": self.execution_time_ms,
            "is_dry_run": self.is_dry_run,
            "payload": payload,
            "input": payload,
            "trace": trace,
            "condition_result": bool(self.matched),
            "action_results": results,
            "steps_trace": steps_trace,
            "ai_result": ai_res,
            "error_message": self.error_message,
            "executed_at": self.executed_at.strftime("%Y-%m-%d %H:%M:%S") if self.executed_at else None,
            "completed_at": self.completed_at.strftime("%Y-%m-%d %H:%M:%S") if self.completed_at else None,
        }


class ExecutionStep(db.Model):
    """Granular step-level forensic execution record."""
    __tablename__ = "execution_steps"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    step_name = db.Column(db.String(128), nullable=False)
    step_type = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="SUCCESS")  # SUCCESS, FAILED, SKIPPED, DRY_RUN
    input_data_json = db.Column(db.Text, nullable=False, default="{}")
    output_data_json = db.Column(db.Text, nullable=False, default="{}")
    error_message = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Float, nullable=False, default=0.0)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        try:
            inp = json.loads(self.input_data_json)
        except Exception:
            inp = {}
        try:
            out = json.loads(self.output_data_json)
        except Exception:
            out = {}
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_name": self.step_name,
            "step_type": self.step_type,
            "status": self.status,
            "input": inp,
            "output": out,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class Lead(db.Model):
    """Customer Inquiry & CRM Lead Record."""
    __tablename__ = "leads"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("lead"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    phone = db.Column(db.String(64), nullable=True)
    company = db.Column(db.String(128), nullable=True)
    message = db.Column(db.Text, nullable=True)
    intent = db.Column(db.String(64), nullable=True, default="lead_inquiry")
    sentiment = db.Column(db.String(32), nullable=True, default="neutral")
    urgency_score = db.Column(db.Integer, nullable=False, default=0)
    lead_score = db.Column(db.Integer, nullable=False, default=0)
    route_department = db.Column(db.String(64), nullable=False, default="General Queue")  # Sales, Support, Priority Support, General Queue, Review
    status = db.Column(db.String(32), nullable=False, default="new")  # new, contacted, qualified, converted, archived
    draft_response = db.Column(db.Text, nullable=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True)
    is_sample = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name or "Anonymous",
            "email": self.email or "N/A",
            "phone": self.phone or "N/A",
            "company": self.company or "N/A",
            "message": self.message or "",
            "intent": self.intent or "general_inquiry",
            "sentiment": self.sentiment or "neutral",
            "urgency_score": self.urgency_score,
            "lead_score": self.lead_score,
            "route_department": self.route_department,
            "status": self.status,
            "draft_response": self.draft_response or "",
            "execution_id": self.execution_id,
            "is_sample": self.is_sample,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class IncidentAlert(db.Model):
    """Operational incident alerts generated by workflows."""
    __tablename__ = "incident_alerts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = db.Column(db.String(64), db.ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(32), nullable=False, default="info")  # critical, high, warning, info
    status = db.Column(db.String(32), nullable=False, default="open")  # open, acknowledged, resolved
    payload_summary_json = db.Column(db.Text, nullable=True)
    acknowledged_by_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_by_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "rule_id": self.rule_id,
            "execution_id": self.execution_id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "status": self.status,
            "acknowledged_by_id": self.acknowledged_by_id,
            "resolved_by_id": self.resolved_by_id,
            "acknowledged_at": self.acknowledged_at.strftime("%Y-%m-%d %H:%M:%S") if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if self.resolved_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class WebhookEndpoint(db.Model):
    """Inbound webhook ingestion endpoints."""
    __tablename__ = "webhook_endpoints"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("wh"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    endpoint_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    secret_token = db.Column(db.String(64), nullable=True)  # for HMAC signature verification
    target_rule_id = db.Column(db.String(64), db.ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    request_count = db.Column(db.Integer, nullable=False, default=0)
    last_received_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "endpoint_token": self.endpoint_token,
            "secret_configured": bool(self.secret_token),
            "target_rule_id": self.target_rule_id,
            "is_active": self.is_active,
            "request_count": self.request_count,
            "last_received_at": self.last_received_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_received_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class AuditLog(db.Model):
    """Administrative & compliance audit log."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email = db.Column(db.String(255), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    resource_type = db.Column(db.String(64), nullable=False)
    resource_id = db.Column(db.String(64), nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        try:
            details = json.loads(self.details_json) if self.details_json else {}
        except Exception:
            details = {}
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "user": self.user_email or self.user_id or "System",
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SystemEvent(db.Model):
    """Ingested System Event Stream Record."""
    __tablename__ = "system_events"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("evt"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_name = db.Column(db.String(128), nullable=False, index=True)
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    source = db.Column(db.String(64), nullable=False, default="manual")
    processed = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    def get_payload(self) -> Dict[str, Any]:
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "event_name": self.event_name,
            "payload": self.get_payload(),
            "source": self.source,
            "processed": self.processed,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
