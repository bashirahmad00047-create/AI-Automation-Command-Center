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


PKT_TZ = datetime.timezone(datetime.timedelta(hours=5))


def get_pakistan_time(timestamp: Optional[Any] = None) -> datetime.datetime:
    """Returns real-world local time in Pakistan Standard Time (PKT, UTC+5 / Asia/Karachi)."""
    if timestamp:
        try:
            ts = float(timestamp)
            if ts > 1e11:
                ts = ts / 1000.0
            return datetime.datetime.fromtimestamp(ts, tz=PKT_TZ).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.datetime.now(PKT_TZ).replace(tzinfo=None)


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
    plan_tier = db.Column(db.String(32), nullable=False, default="free")  # free, starter, pro, enterprise
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    max_rules = db.Column(db.Integer, nullable=False, default=100)
    max_monthly_events = db.Column(db.Integer, nullable=False, default=500000)
    stripe_customer_id = db.Column(db.String(128), nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(128), nullable=True, index=True)
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
    usages = db.relationship("OrganizationUsage", backref="organization", cascade="all, delete-orphan", lazy="select")
    subscription = db.relationship("Subscription", backref="organization", uselist=False, cascade="all, delete-orphan", lazy="select")
    whatsapp_messages = db.relationship("WhatsAppMessage", backref="organization", cascade="all, delete-orphan", lazy="select")
    jazzcash_transactions = db.relationship("JazzCashTransaction", backref="organization", cascade="all, delete-orphan", lazy="select")
    company_channels = db.relationship("CompanyChannel", backref="organization", cascade="all, delete-orphan", lazy="select")
    company_messages = db.relationship("CompanyMessage", backref="organization", cascade="all, delete-orphan", lazy="select")
    company_broadcasts = db.relationship("CompanyBroadcast", backref="organization", cascade="all, delete-orphan", lazy="select")
    broadcast_campaigns = db.relationship("BroadcastCampaign", backref="organization", cascade="all, delete-orphan", lazy="select")
    campaign_recipients = db.relationship("CampaignRecipient", backref="organization", cascade="all, delete-orphan", lazy="select")
    message_templates = db.relationship("MessageTemplate", backref="organization", cascade="all, delete-orphan", lazy="select")
    contact_consents = db.relationship("ContactConsent", backref="organization", cascade="all, delete-orphan", lazy="select")
    products = db.relationship("Product", backref="organization", cascade="all, delete-orphan", lazy="select")
    business_profile = db.relationship("BusinessProfile", backref="organization", uselist=False, cascade="all, delete-orphan", lazy="select")

    def get_subscription(self) -> "Subscription":
        """Get or lazily initialize the tenant subscription record."""
        if self.subscription:
            return self.subscription
        sub = Subscription(
            organization_id=self.id,
            plan_tier=self.plan_tier or "free",
            status="active",
            stripe_customer_id=self.stripe_customer_id,
            stripe_subscription_id=self.stripe_subscription_id,
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def get_business_profile(self) -> "BusinessProfile":
        """Get or lazily initialize the tenant business profile record."""
        if self.business_profile:
            return self.business_profile
        prof = BusinessProfile(
            organization_id=self.id,
            business_category="online",
            industry="ecommerce",
            industry_name="E-Commerce & Online Store",
            company_name=self.name,
        )
        db.session.add(prof)
        db.session.flush()
        return prof

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "plan_tier": self.plan_tier,
            "is_active": self.is_active,
            "max_rules": self.max_rules,
            "max_monthly_events": self.max_monthly_events,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "subscription": self.subscription.to_dict() if self.subscription else None,
            "business_profile": self.business_profile.to_dict() if self.business_profile else None,
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
    
    # MFA / TOTP Fields
    mfa_secret = db.Column(db.String(64), nullable=True)
    is_mfa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    mfa_backup_codes = db.Column(db.Text, nullable=True)
    
    phone = db.Column(db.String(64), nullable=True)
    department = db.Column(db.String(64), nullable=True, default="General")
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    # Relationships
    memberships = db.relationship("Membership", backref="user", cascade="all, delete-orphan", lazy="select")
    api_keys = db.relationship("ApiKey", backref="user", lazy="select")
    reset_tokens = db.relationship("PasswordResetToken", backref="user", cascade="all, delete-orphan", lazy="select")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "phone": self.phone or "",
            "department": self.department or "General",
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "is_mfa_enabled": self.is_mfa_enabled,
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
    created_at = db.Column(db.DateTime, nullable=False, default=get_pakistan_time, index=True)
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
    target_type = db.synonym("resource_type")
    target_id = db.synonym("resource_id")
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
            "event": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "target_type": self.resource_type,
            "target_id": self.resource_id,
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


class OrganizationUsage(db.Model):
    """Tracks organization usage per billing period / month.
    
    Attributes:
        organization_id: Organization tenant identifier.
        period: YYYY-MM formatted calendar period (e.g. '2026-10').
        event_count: Total non-dry-run billable events consumed in this period.
    """
    __tablename__ = "organization_usages"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("usg"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    period = db.Column(db.String(16), nullable=False, index=True)  # e.g. "2026-10"
    event_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint("organization_id", "period", name="uq_org_period"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "period": self.period,
            "event_count": self.event_count,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class Subscription(db.Model):
    """SaaS Tenant Subscription record tracking Stripe billing state."""
    __tablename__ = "subscriptions"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("sub"))
    organization_id = db.Column(
        db.String(64),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )
    stripe_customer_id = db.Column(db.String(128), nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(128), nullable=True, index=True)
    stripe_price_id = db.Column(db.String(128), nullable=True)
    plan_tier = db.Column(db.String(32), nullable=False, default="free")
    status = db.Column(db.String(64), nullable=False, default="active")  # active, trialing, past_due, canceled, unpaid
    billing_interval = db.Column(db.String(32), nullable=False, default="month")  # month, year
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False)
    canceled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "stripe_price_id": self.stripe_price_id,
            "plan_tier": self.plan_tier,
            "status": self.status,
            "billing_interval": self.billing_interval,
            "current_period_start": self.current_period_start.strftime("%Y-%m-%d %H:%M:%S") if self.current_period_start else None,
            "current_period_end": self.current_period_end.strftime("%Y-%m-%d %H:%M:%S") if self.current_period_end else None,
            "cancel_at_period_end": self.cancel_at_period_end,
            "canceled_at": self.canceled_at.strftime("%Y-%m-%d %H:%M:%S") if self.canceled_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class StripeWebhookEvent(db.Model):
    """Tracks processed Stripe webhook event IDs for guaranteed idempotency."""
    __tablename__ = "stripe_webhook_events"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("swe"))
    event_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    event_type = db.Column(db.String(128), nullable=False)
    payload_summary = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="processed")
    processed_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "status": self.status,
            "processed_at": self.processed_at.strftime("%Y-%m-%d %H:%M:%S") if self.processed_at else None,
        }


class PasswordResetToken(db.Model):
    """Secure, single-use, time-limited password reset tokens."""
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("rst"))
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, index=True)  # SHA-256 hash of the plaintext token
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    is_used = db.Column(db.Boolean, nullable=False, default=False)
    used_at = db.Column(db.DateTime, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "expires_at": self.expires_at.strftime("%Y-%m-%d %H:%M:%S") if self.expires_at else None,
            "is_used": self.is_used,
            "used_at": self.used_at.strftime("%Y-%m-%d %H:%M:%S") if self.used_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class WhatsAppMessage(db.Model):
    """Multi-tenant WhatsApp Business Cloud API incoming & outgoing message log."""
    __tablename__ = "whatsapp_messages"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("wam"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    whatsapp_message_id = db.Column(db.String(128), nullable=True, index=True)  # Meta wamid...
    parent_message_id = db.Column(db.String(128), nullable=True, index=True)  # Quoted / parent message ID
    direction = db.Column(db.String(16), nullable=False, default="inbound")  # inbound, outbound
    sender = db.Column(db.String(64), nullable=False)  # Phone number or System
    recipient = db.Column(db.String(64), nullable=False)  # Phone number or System
    message_type = db.Column(db.String(32), nullable=False, default="text")  # text, template, interactive
    body = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="received")  # received, sent, mock_sent, failed
    execution_id = db.Column(db.Integer, db.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_payload_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        media_url = None
        sender_name = None
        duration = None
        is_ai_response = False
        is_ai_generated = False
        ai_intent = None
        response_source = None
        parent_id = getattr(self, "parent_message_id", None)
        if self.raw_payload_json:
            try:
                raw = json.loads(self.raw_payload_json)
                if isinstance(raw, dict):
                    sender_name = raw.get("senderName") or raw.get("senderContactName")
                    media_url = (
                        raw.get("download_url") or
                        raw.get("downloadUrl") or
                        raw.get("urlFile") or
                        raw.get("media_url") or
                        (raw.get("fileMessageData", {}).get("downloadUrl") if isinstance(raw.get("fileMessageData"), dict) else None) or
                        (raw.get("audioMessageData", {}).get("downloadUrl") if isinstance(raw.get("audioMessageData"), dict) else None) or
                        (raw.get("raw", {}).get("messageData", {}).get("fileMessageData", {}).get("downloadUrl") if isinstance(raw.get("raw"), dict) and isinstance(raw.get("raw", {}).get("messageData"), dict) else None) or
                        (raw.get("raw", {}).get("downloadUrl") if isinstance(raw.get("raw"), dict) else None)
                    )
                    duration = (
                        raw.get("audioMessageData", {}).get("duration") or
                        raw.get("duration")
                    )
                    is_ai_response = bool(raw.get("is_ai_response") or raw.get("is_ai"))
                    is_ai_generated = bool(raw.get("is_ai_generated"))
                    ai_intent = raw.get("ai_intent") or raw.get("intent")
                    response_source = raw.get("response_source")
            except Exception:
                pass

        is_audio = (
            self.message_type in ("audioMessage", "voiceMessage", "audio", "voice", "ptt") or
            bool(self.body and any(tag in self.body.lower() for tag in ("[audiomessage]", "[voicemessage]", "[voice note]"))) or
            bool(media_url and any(str(media_url).lower().split("?")[0].endswith(ext) for ext in (".ogg", ".oga", ".mp3", ".wav", ".m4a", ".aac", ".opus")))
        )

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "whatsapp_message_id": self.whatsapp_message_id,
            "parent_message_id": parent_id,
            "parent_msg_id": parent_id,
            "direction": self.direction,
            "sender": self.sender,
            "recipient": self.recipient,
            "sender_name": sender_name,
            "message_type": self.message_type,
            "body": self.body,
            "media_url": media_url,
            "is_audio": is_audio,
            "audio_duration": duration,
            "is_ai_response": is_ai_response,
            "is_ai_generated": is_ai_generated,
            "response_source": response_source,
            "ai_intent": ai_intent,
            "status": self.status,
            "execution_id": self.execution_id,
            "error_message": self.error_message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SystemSetting(db.Model):
    """Dynamic configuration settings stored in database for gateways & integrations."""
    __tablename__ = "system_settings"

    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    is_secret = db.Column(db.Boolean, nullable=False, default=False)
    description = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    @classmethod
    def get_val(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        try:
            setting = cls.query.filter_by(key=key).first()
            if setting is not None:
                return setting.value if setting.value is not None else ""
        except Exception:
            pass
        return default

    @classmethod
    def set_val(cls, key: str, value: Optional[str], is_secret: bool = False, description: Optional[str] = None):
        setting = cls.query.filter_by(key=key).first()
        clean_val = value.strip() if value else None
        if not setting:
            setting = cls(key=key, value=clean_val, is_secret=is_secret, description=description)
            db.session.add(setting)
        else:
            setting.value = clean_val
            if description:
                setting.description = description
            setting.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        return setting

    def to_dict(self) -> Dict[str, Any]:
        val = self.value
        if self.is_secret and val:
            val = val[:4] + "••••••••" + val[-4:] if len(val) > 8 else "••••••••"
        return {
            "key": self.key,
            "value": val,
            "is_secret": self.is_secret,
            "description": self.description,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class JazzCashTransaction(db.Model):
    """Multi-tenant JazzCash mobile wallet and card payment transaction ledger."""
    __tablename__ = "jazzcash_transactions"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("jzc"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    txn_ref_no = db.Column(db.String(64), unique=True, nullable=False, index=True)
    bill_reference = db.Column(db.String(64), nullable=True, index=True)
    plan_tier = db.Column(db.String(32), nullable=False)  # starter, pro, enterprise
    billing_interval = db.Column(db.String(16), nullable=False, default="month")  # month, year
    amount_pkr = db.Column(db.Float, nullable=False)
    mobile_number = db.Column(db.String(20), nullable=True)
    cnic_last6 = db.Column(db.String(10), nullable=True)
    payment_channel = db.Column(db.String(32), nullable=False, default="MWALLET")  # MWALLET, REDIRECT
    status = db.Column(db.String(32), nullable=False, default="PENDING")  # PENDING, COMPLETED, FAILED
    response_code = db.Column(db.String(10), nullable=True)
    response_message = db.Column(db.String(255), nullable=True)
    raw_response_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "txn_ref_no": self.txn_ref_no,
            "bill_reference": self.bill_reference,
            "plan_tier": self.plan_tier,
            "billing_interval": self.billing_interval,
            "amount_pkr": self.amount_pkr,
            "mobile_number": self.mobile_number,
            "payment_channel": self.payment_channel,
            "status": self.status,
            "response_code": self.response_code,
            "response_message": self.response_message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "completed_at": self.completed_at.strftime("%Y-%m-%d %H:%M:%S") if self.completed_at else None,
        }


class CompanyChannel(db.Model):
    """Multi-tenant Company Messaging Channel (e.g. #general, #incidents, #sre-alerts)."""
    __tablename__ = "company_channels"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("chn"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)  # slug: general, incidents, sre-alerts
    display_name = db.Column(db.String(128), nullable=False)  # #general, #Incident War Room
    description = db.Column(db.String(255), nullable=True)
    channel_type = db.Column(db.String(32), nullable=False, default="public")  # public, announcement, private
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_by_user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    messages = db.relationship("CompanyMessage", backref="channel", cascade="all, delete-orphan", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "channel_type": self.channel_type,
            "is_archived": self.is_archived,
            "is_system": self.is_system,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
            "message_count": len(self.messages) if self.messages else 0
        }


class CompanyMessage(db.Model):
    """Multi-tenant internal company message stream."""
    __tablename__ = "company_messages"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("cmsg"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = db.Column(db.String(64), db.ForeignKey("company_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    sender_name = db.Column(db.String(128), nullable=False)
    sender_role = db.Column(db.String(32), nullable=False, default="member")
    body = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(32), nullable=False, default="normal")  # normal, urgent, critical
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    parent_message_id = db.Column(db.String(64), db.ForeignKey("company_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "channel_id": self.channel_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_role": self.sender_role,
            "body": self.body,
            "priority": self.priority,
            "is_system": self.is_system,
            "parent_message_id": self.parent_message_id,
            "execution_id": self.execution_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class CompanyBroadcast(db.Model):
    """Multi-tenant operational announcement / broadcast banner."""
    __tablename__ = "company_broadcasts"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("bc"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(32), nullable=False, default="info")  # info, warning, critical, urgent
    requires_acknowledgment = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by_user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_name = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    acknowledgments = db.relationship("CompanyBroadcastAck", backref="broadcast", cascade="all, delete-orphan", lazy="select")

    def to_dict(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        is_ack = False
        if user_id and self.acknowledgments:
            is_ack = any(a.user_id == user_id for a in self.acknowledgments)
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "requires_acknowledgment": self.requires_acknowledgment,
            "is_active": self.is_active,
            "created_by_user_id": self.created_by_user_id,
            "created_by_name": self.created_by_name,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "expires_at": self.expires_at.strftime("%Y-%m-%d %H:%M:%S") if self.expires_at else None,
            "acknowledgments_count": len(self.acknowledgments) if self.acknowledgments else 0,
            "is_acknowledged": is_ack
        }


class CompanyBroadcastAck(db.Model):
    """Audit record for employee acknowledgment of mandatory company broadcasts."""
    __tablename__ = "company_broadcast_acks"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("back"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    broadcast_id = db.Column(db.String(64), db.ForeignKey("company_broadcasts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_name = db.Column(db.String(128), nullable=False)
    acknowledged_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_user_ack"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "broadcast_id": self.broadcast_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "acknowledged_at": self.acknowledged_at.strftime("%Y-%m-%d %H:%M:%S") if self.acknowledged_at else None
        }


class MessageTemplate(db.Model):
    """Reusable message templates for WhatsApp and multi-channel campaigns."""
    __tablename__ = "message_templates"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("tmpl"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    category = db.Column(db.String(64), nullable=False, default="utility")  # utility, marketing, authentication, support
    language = db.Column(db.String(16), nullable=False, default="en_US")
    body = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(32), nullable=False, default="whatsapp")
    is_approved_by_meta = db.Column(db.Boolean, nullable=False, default=False)
    meta_template_id = db.Column(db.String(128), nullable=True)
    created_by_user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "category": self.category,
            "language": self.language,
            "body": self.body,
            "channel": self.channel,
            "is_approved_by_meta": self.is_approved_by_meta,
            "meta_template_id": self.meta_template_id,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class ContactConsent(db.Model):
    """Compliance & opt-out registry to honor recipient consent across WhatsApp and messaging."""
    __tablename__ = "contact_consents"
    __table_args__ = (
        db.UniqueConstraint("organization_id", "phone", "channel", name="uq_org_phone_channel_consent"),
    )

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("cst"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default="opted_in")  # opted_in, opted_out
    channel = db.Column(db.String(32), nullable=False, default="whatsapp")
    reason = db.Column(db.String(255), nullable=True)
    opted_out_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "phone": self.phone,
            "status": self.status,
            "channel": self.channel,
            "reason": self.reason,
            "opted_out_at": self.opted_out_at.strftime("%Y-%m-%d %H:%M:%S") if self.opted_out_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class BroadcastCampaign(db.Model):
    """Multi-audience outbound campaign and broadcast with review, scheduling, and delivery tracking."""
    __tablename__ = "broadcast_campaigns"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("cmp"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    channel = db.Column(db.String(32), nullable=False, default="whatsapp")  # whatsapp, internal, multi
    audience_type = db.Column(db.String(64), nullable=False, default="customers")  # customers, employees, department, saved_group, manual
    audience_filter = db.Column(db.Text, nullable=True)  # JSON or filter string
    template_name = db.Column(db.String(128), nullable=True)
    raw_template = db.Column(db.Text, nullable=False)
    rendered_preview = db.Column(db.Text, nullable=True)
    
    # Lifecycle status: draft -> pending_approval -> approved -> scheduled -> queued -> processing -> completed / cancelled / failed
    status = db.Column(db.String(32), nullable=False, default="draft")
    scheduled_at = db.Column(db.DateTime, nullable=True)
    
    approved_by_user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_by_user_id = db.Column(db.String(64), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Aggregate telemetry counters
    total_recipients = db.Column(db.Integer, nullable=False, default=0)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    delivered_count = db.Column(db.Integer, nullable=False, default=0)
    read_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    opted_out_count = db.Column(db.Integer, nullable=False, default=0)
    estimated_cost_usd = db.Column(db.Float, nullable=False, default=0.0)
    execution_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationship
    recipients = db.relationship("CampaignRecipient", backref="campaign", cascade="all, delete-orphan", lazy="select")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "title": self.title,
            "channel": self.channel,
            "audience_type": self.audience_type,
            "audience_filter": self.audience_filter,
            "template_name": self.template_name,
            "raw_template": self.raw_template,
            "rendered_preview": self.rendered_preview,
            "status": self.status,
            "scheduled_at": self.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if self.scheduled_at else None,
            "approved_by_user_id": self.approved_by_user_id,
            "approved_at": self.approved_at.strftime("%Y-%m-%d %H:%M:%S") if self.approved_at else None,
            "created_by_user_id": self.created_by_user_id,
            "total_recipients": self.total_recipients,
            "sent_count": self.sent_count,
            "delivered_count": self.delivered_count,
            "read_count": self.read_count,
            "failed_count": self.failed_count,
            "opted_out_count": self.opted_out_count,
            "estimated_cost_usd": self.estimated_cost_usd,
            "execution_notes": self.execution_notes,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class CampaignRecipient(db.Model):
    """Per-recipient delivery ledger ensuring idempotency and per-recipient delivery tracking."""
    __tablename__ = "campaign_recipients"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("cmpr"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = db.Column(db.String(64), db.ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    
    recipient_type = db.Column(db.String(32), nullable=False, default="customer")  # customer, employee, contact
    recipient_id = db.Column(db.String(64), nullable=True)
    name = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    department = db.Column(db.String(64), nullable=True)
    company = db.Column(db.String(128), nullable=True)

    # Delivery status: pending, queued, sent, delivered, read, failed, opted_out, ineligible
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    idempotency_key = db.Column(db.String(160), nullable=False, index=True)  # {campaign_id}:{clean_phone}
    provider_message_id = db.Column(db.String(128), nullable=True, index=True)
    provider_name = db.Column(db.String(32), nullable=True)
    personalized_body = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)

    sent_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "campaign_id": self.campaign_id,
            "recipient_type": self.recipient_type,
            "recipient_id": self.recipient_id,
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "department": self.department,
            "company": self.company,
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "provider_message_id": self.provider_message_id,
            "provider_name": self.provider_name,
            "personalized_body": self.personalized_body,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "sent_at": self.sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.sent_at else None,
            "delivered_at": self.delivered_at.strftime("%Y-%m-%d %H:%M:%S") if self.delivered_at else None,
            "read_at": self.read_at.strftime("%Y-%m-%d %H:%M:%S") if self.read_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class Product(db.Model):
    """Tenant-scoped product, service, and inventory item for commerce, catalog, and AI auto-response grounding."""
    __tablename__ = "products"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("prd"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    category = db.Column(db.String(128), nullable=True, index=True, default="General")
    description = db.Column(db.Text, nullable=True)
    sku = db.Column(db.String(128), nullable=True, index=True)
    barcode = db.Column(db.String(128), nullable=True)
    image_url = db.Column(db.String(512), nullable=True)
    unit = db.Column(db.String(64), nullable=False, default="piece")
    price = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(10), nullable=False, default="PKR")
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    stock_status = db.Column(db.String(32), nullable=False, default="in_stock")  # in_stock, low_stock, out_of_stock
    is_active = db.Column(db.Boolean, nullable=False, default=True)  # True = Active, False = Archived
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def calculate_stock_status(self) -> str:
        if self.stock_quantity <= 0:
            return "out_of_stock"
        elif self.stock_quantity <= 5:
            return "low_stock"
        return "in_stock"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "category": self.category or "General",
            "description": self.description or "",
            "sku": self.sku or "",
            "barcode": self.barcode or "",
            "image_url": self.image_url or "",
            "unit": self.unit or "piece",
            "price": float(self.price),
            "currency": self.currency or "PKR",
            "stock_quantity": int(self.stock_quantity),
            "stock_status": self.stock_status or self.calculate_stock_status(),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class BusinessProfile(db.Model):
    """Tenant-scoped Business Operating System Profile for Online & Offline businesses."""
    __tablename__ = "business_profiles"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("bprof"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    # Category: "online" or "offline"
    business_category = db.Column(db.String(32), nullable=False, default="online")

    # Industry slug: "ecommerce", "agency", "saas", "booking", "leadgen", "retail", "clinic", "restaurant", "warehouse", "services"
    industry = db.Column(db.String(64), nullable=False, default="ecommerce")
    industry_name = db.Column(db.String(128), nullable=False, default="E-Commerce & Online Store")
    company_name = db.Column(db.String(160), nullable=True)
    tagline = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # JSON-encoded configurations
    services_json = db.Column(db.Text, nullable=False, default="[]")
    operating_hours_json = db.Column(db.Text, nullable=False, default="{}")
    policies_json = db.Column(db.Text, nullable=False, default="{}")
    channels_config_json = db.Column(db.Text, nullable=False, default="{}")
    custom_roles_json = db.Column(db.Text, nullable=False, default="[]")

    # AI Grounding Instructions
    ai_instructions = db.Column(db.Text, nullable=True)
    ai_guardrails = db.Column(db.Text, nullable=True)
    ai_tone = db.Column(db.String(32), nullable=False, default="professional")

    is_configured = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def get_services(self) -> List[Dict[str, Any]]:
        try:
            val = json.loads(self.services_json)
            return val if isinstance(val, list) else []
        except Exception:
            return []

    def get_operating_hours(self) -> Dict[str, Any]:
        try:
            val = json.loads(self.operating_hours_json)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    def get_policies(self) -> Dict[str, Any]:
        try:
            val = json.loads(self.policies_json)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    def get_channels_config(self) -> Dict[str, Any]:
        try:
            val = json.loads(self.channels_config_json)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    def get_custom_roles(self) -> List[Dict[str, Any]]:
        try:
            val = json.loads(self.custom_roles_json)
            return val if isinstance(val, list) else []
        except Exception:
            return []

    def is_open_now(self, dt: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """Calculates whether business is currently open based on operating hours."""
        now = dt or datetime.datetime.now()
        day_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        current_day_key = day_keys[now.weekday()]

        hours_conf = self.get_operating_hours()
        if not hours_conf or not hours_conf.get("schedule"):
            return {"is_open": True, "reason": "Always open / 24-7"}

        schedule = hours_conf.get("schedule", {})
        day_sched = schedule.get(current_day_key)
        if not day_sched or day_sched.get("closed"):
            return {"is_open": False, "reason": f"Closed on {now.strftime('%A')}s"}

        open_str = day_sched.get("open", "09:00")
        close_str = day_sched.get("close", "18:00")

        try:
            open_h, open_m = map(int, open_str.split(":"))
            close_h, close_m = map(int, close_str.split(":"))
            now_mins = now.hour * 60 + now.minute
            open_mins = open_h * 60 + open_m
            close_mins = close_h * 60 + close_m

            if close_mins < open_mins:  # Overnight shift
                is_open = now_mins >= open_mins or now_mins <= close_mins
            else:
                is_open = open_mins <= now_mins <= close_mins

            return {
                "is_open": is_open,
                "current_time": now.strftime("%H:%M"),
                "hours_today": f"{open_str} - {close_str}",
                "day": now.strftime("%A"),
                "reason": "Open for business" if is_open else f"Closed outside operating hours ({open_str} - {close_str})"
            }
        except Exception as e:
            return {"is_open": True, "reason": f"Standard hours ({e})"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "business_category": self.business_category,
            "industry": self.industry,
            "industry_name": self.industry_name,
            "company_name": self.company_name or "",
            "tagline": self.tagline or "",
            "description": self.description or "",
            "services": self.get_services(),
            "operating_hours": self.get_operating_hours(),
            "policies": self.get_policies(),
            "channels_config": self.get_channels_config(),
            "custom_roles": self.get_custom_roles(),
            "ai_instructions": self.ai_instructions or "",
            "ai_guardrails": self.ai_guardrails or "",
            "ai_tone": self.ai_tone or "professional",
            "is_configured": bool(self.is_configured),
            "is_open_now": self.is_open_now(),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class EcommerceOrder(db.Model):
    """Tenant-scoped e-commerce orders for multi-channel sales, WhatsApp status updates, and tracking."""
    __tablename__ = "ecommerce_orders"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("ord"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = db.Column(db.String(64), nullable=False, index=True)
    customer_phone = db.Column(db.String(32), nullable=False, index=True)
    customer_name = db.Column(db.String(255), nullable=True)
    customer_email = db.Column(db.String(255), nullable=True)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(10), nullable=False, default="PKR")
    order_status = db.Column(db.String(32), nullable=False, default="confirmed", index=True)  # pending, confirmed, processing, shipped, delivered, cancelled
    payment_status = db.Column(db.String(32), nullable=False, default="unpaid")  # unpaid, paid, cod, refunded
    payment_method = db.Column(db.String(64), nullable=True, default="cod")  # cod, jazzcash, stripe, bank_transfer
    items_json = db.Column(db.Text, nullable=True)  # JSON list of [{"name": str, "sku": str, "quantity": int, "price": float}]
    tracking_number = db.Column(db.String(128), nullable=True, index=True)
    courier_name = db.Column(db.String(128), nullable=True)  # e.g., TCS, Leopard, CallCourier, DHL, Trax, M&P
    tracking_url = db.Column(db.String(512), nullable=True)
    shipping_address = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    last_notified_status = db.Column(db.String(32), nullable=True)
    last_notified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def get_items(self) -> List[Dict[str, Any]]:
        if self.items_json:
            try:
                data = json.loads(self.items_json)
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.items_json = json.dumps(items or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "order_number": self.order_number,
            "customer_phone": self.customer_phone,
            "customer_name": self.customer_name or "",
            "customer_email": self.customer_email or "",
            "total_amount": float(self.total_amount),
            "currency": self.currency or "PKR",
            "order_status": self.order_status,
            "payment_status": self.payment_status,
            "payment_method": self.payment_method or "cod",
            "items": self.get_items(),
            "tracking_number": self.tracking_number or "",
            "courier_name": self.courier_name or "",
            "tracking_url": self.tracking_url or "",
            "shipping_address": self.shipping_address or "",
            "notes": self.notes or "",
            "last_notified_status": self.last_notified_status,
            "last_notified_at": self.last_notified_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_notified_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class AbandonedCart(db.Model):
    """Tenant-scoped abandoned carts for automated WhatsApp recovery flows and conversion alerts."""
    __tablename__ = "abandoned_carts"

    id = db.Column(db.String(64), primary_key=True, default=lambda: generate_uuid("crt"))
    organization_id = db.Column(db.String(64), db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_phone = db.Column(db.String(32), nullable=False, index=True)
    customer_name = db.Column(db.String(255), nullable=True)
    customer_email = db.Column(db.String(255), nullable=True)
    cart_value = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(10), nullable=False, default="PKR")
    cart_items_json = db.Column(db.Text, nullable=True)  # JSON list of [{"name": str, "price": float, "quantity": int}]
    checkout_url = db.Column(db.String(512), nullable=True)
    recovery_status = db.Column(db.String(32), nullable=False, default="abandoned", index=True)  # abandoned, reminder_sent, recovered, expired
    discount_code = db.Column(db.String(64), nullable=True)
    reminder_count = db.Column(db.Integer, nullable=False, default=0)
    last_reminder_sent_at = db.Column(db.DateTime, nullable=True)
    recovered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def get_items(self) -> List[Dict[str, Any]]:
        if self.cart_items_json:
            try:
                data = json.loads(self.cart_items_json)
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.cart_items_json = json.dumps(items or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "customer_phone": self.customer_phone,
            "customer_name": self.customer_name or "",
            "customer_email": self.customer_email or "",
            "cart_value": float(self.cart_value),
            "currency": self.currency or "PKR",
            "items": self.get_items(),
            "checkout_url": self.checkout_url or "",
            "recovery_status": self.recovery_status,
            "discount_code": self.discount_code or "",
            "reminder_count": int(self.reminder_count),
            "last_reminder_sent_at": self.last_reminder_sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_reminder_sent_at else None,
            "recovered_at": self.recovered_at.strftime("%Y-%m-%d %H:%M:%S") if self.recovered_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }

