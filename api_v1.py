"""Version 1 Enterprise REST API for OpsFlow SaaS Platform.

Provides secure, authenticated, and tenant-isolated endpoints for:
- Authentication & Session Management (Login/Logout/Register)
- Workflows & Automation Rules (CRUD, Visual Steps, Duplication, Execution, Dry Run)
- AI Intelligence & Local Lead Qualification
- CRM Leads & Smart Routing Pipeline
- Inbound Webhook Gateway with HMAC-SHA256 Signatures
- Event Ingestion ({ "event": "lead.created", "name": "...", "email": "...", "message": "..." })
- Forensic Execution Logs & Waterfall Step Inspection
- Incident Response & Alert Lifecycle Management
- Real-Database Analytics & Execution Trends
- Workflow Templates Library (8 Ready-to-Run Enterprise Blueprints)
- AI Provider Architecture (Local Heuristics, Gemini, OpenAI)
- Compliance Audit Trail
- System Telemetry & Health Checks
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import desc

from ai_provider import AIProviderManager, get_ai_provider
from auth import (
    generate_secure_api_key,
    get_current_org,
    get_current_user,
    get_user_role,
    log_audit_event,
    require_auth,
    require_role,
)
from database import db
from entitlements import (
    PlanEntitlements,
    QuotaService,
    check_ai_provider_entitlement,
    check_feature_entitlement,
    check_resource_quota,
    get_org_entitlements,
    require_feature,
)
from limiter import limiter, rate_limit
from plans import PLAN_DEFINITIONS, PLAN_FREE, get_plan, list_plans
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

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def get_engine():
    """Helper to retrieve the global AutomationEngine instance."""
    from flask import current_app
    return current_app.config.get("AUTOMATION_ENGINE")


def get_storage():
    """Helper to retrieve the global Storage instance."""
    from flask import current_app
    return current_app.config.get("STORAGE_ENGINE")


# ==========================================
# Authentication & Identity Endpoints
# ==========================================

@api_v1.route("/auth/register", methods=["POST"])
@rate_limit(limit=5, window=60, config_key="REGISTER_RATE_LIMIT", message="Too many registration attempts. Please try again later.")
def auth_register():
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    full_name = data.get("full_name", "").strip()
    org_name = data.get("org_name", "").strip() or f"{full_name}'s Workspace"

    if not email or "@" not in email:
        return jsonify({"error": "A valid email address is required.", "code": "VALIDATION_ERROR"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters.", "code": "VALIDATION_ERROR"}), 400
    if not full_name:
        return jsonify({"error": "Full name is required.", "code": "VALIDATION_ERROR"}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"error": "An account with this email already exists.", "code": "CONFLICT"}), 409

    try:
        # Create organization defaulting to Free plan
        slug = f"{email.split('@')[0]}-{generate_uuid()[:6]}".lower()
        requested_plan = (data.get("plan_tier") or data.get("plan") or PLAN_FREE).strip().lower()
        if requested_plan not in PLAN_DEFINITIONS:
            requested_plan = PLAN_FREE
        plan_spec = get_plan(requested_plan)
        org = Organization(
            id=generate_uuid("org"),
            name=org_name,
            slug=slug,
            plan_tier=requested_plan,
            max_rules=plan_spec["quotas"]["max_rules"],
            max_monthly_events=plan_spec["quotas"]["max_monthly_events"],
            is_active=True
        )
        db.session.add(org)

        # Create user
        user = User(
            id=generate_uuid("usr"),
            email=email,
            full_name=full_name,
            is_active=True,
            is_superuser=False
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        # Create owner membership
        membership = Membership(
            id=generate_uuid("mem"),
            user_id=user.id,
            organization_id=org.id,
            role="owner"
        )
        db.session.add(membership)

        # Generate default API key for the new tenant
        full_key, key_prefix, key_hash = generate_secure_api_key()
        api_key = ApiKey(
            organization_id=org.id,
            user_id=user.id,
            name="Default Workspace Key",
            key_prefix=key_prefix,
            key_hash=key_hash,
            permissions="*",
            is_revoked=False
        )
        db.session.add(api_key)

        db.session.commit()

        # Log audit trail
        log_audit_event("auth.register", "user", user.id, {"email": email, "organization": org.name})

        # Set session
        session["user_id"] = user.id
        session["active_org_id"] = org.id

        return jsonify({
            "success": True,
            "message": "User and enterprise organization created successfully.",
            "user": user.to_dict(),
            "organization": org.to_dict(),
            "role": "owner",
            "initial_api_key": full_key
        }), 201

    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Registration server error: %s", exc, exc_info=True)
        return jsonify({"error": "Registration failed due to a server error.", "code": "REGISTRATION_ERROR"}), 500


@api_v1.route("/auth/login", methods=["POST"])
@rate_limit(limit=10, window=60, config_key="LOGIN_RATE_LIMIT", message="Too many login attempts. Please try again later.")
def auth_login():
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required.", "code": "VALIDATION_ERROR"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password credentials.", "code": "UNAUTHORIZED"}), 401

    if not user.is_active:
        return jsonify({"error": "This account is inactive. Please contact support.", "code": "ACCOUNT_DISABLED"}), 403

    user.last_login_at = datetime.datetime.utcnow()
    db.session.commit()

    # Find primary organization
    membership = Membership.query.filter_by(user_id=user.id).first()
    org_id = membership.organization_id if membership else None

    session.pop("logged_out", None)
    session["user_id"] = user.id
    if org_id:
        session["active_org_id"] = org_id
        session["org_id"] = org_id

    log_audit_event("auth.login", "user", user.id, {"email": email})

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user.to_dict(),
        "role": membership.role if membership else "viewer",
        "active_org_id": org_id
    })


@api_v1.route("/auth/logout", methods=["POST"])
def auth_logout():
    user = get_current_user()
    if user:
        log_audit_event("auth.logout", "user", user.id)
    session.clear()
    session["logged_out"] = True
    g.current_user = None
    g.current_org = None
    g.api_key = None
    g.is_api_key_auth = False
    return jsonify({"success": True, "message": "Successfully logged out."})


@api_v1.route("/auth/me", methods=["GET"])
@require_auth
def auth_me():
    user = g.current_user
    org = g.current_org
    role = get_user_role(user.id, org.id) if user and org else "viewer"

    memberships = Membership.query.filter_by(user_id=user.id).all() if user else []
    organizations = [m.organization.to_dict() for m in memberships if m.organization]

    return jsonify({
        "user": user.to_dict() if user else None,
        "current_organization": org.to_dict() if org else None,
        "role": role,
        "organizations": organizations
    })


# ==========================================
# Organization & Workspace Management
# ==========================================

@api_v1.route("/organizations", methods=["GET"])
@require_auth
def list_organizations():
    user = g.current_user
    if user and user.is_superuser:
        orgs = Organization.query.all()
    elif user:
        memberships = Membership.query.filter_by(user_id=user.id).all()
        orgs = [m.organization for m in memberships if m.organization]
    else:
        orgs = Organization.query.all()

    return jsonify({"organizations": [o.to_dict() for o in orgs if o]})


@api_v1.route("/organizations/switch", methods=["POST"])
@require_auth
def switch_organization():
    data = request.get_json(silent=True) or {}
    target_org_id = data.get("organization_id")
    user = g.current_user

    if not target_org_id:
        return jsonify({"error": "organization_id is required.", "code": "VALIDATION_ERROR"}), 400

    target_org = db.session.get(Organization, target_org_id)
    if not target_org:
        return jsonify({"error": "Organization not found.", "code": "NOT_FOUND"}), 404

    # Verify user has membership unless superuser
    if user and not user.is_superuser:
        membership = Membership.query.filter_by(user_id=user.id, organization_id=target_org.id).first()
        if not membership:
            return jsonify({"error": "Access denied to target organization.", "code": "FORBIDDEN"}), 403

    session["active_org_id"] = target_org.id
    session["org_id"] = target_org.id
    return jsonify({
        "success": True,
        "message": f"Switched to workspace: {target_org.name}",
        "organization": target_org.to_dict()
    })


# ==========================================
# API Key Management
# ==========================================

@api_v1.route("/api-keys", methods=["GET"])
@api_v1.route("/auth/api-keys", methods=["GET"])
@require_role(["owner", "admin"])
def list_api_keys():
    org = g.current_org
    storage = get_storage()
    keys = storage.list_api_keys(org.id)
    return jsonify({"api_keys": keys, "count": len(keys)})


@api_v1.route("/api-keys", methods=["POST"])
@api_v1.route("/auth/api-keys", methods=["POST"])
@require_role(["owner", "admin"])
def create_api_key():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip() or "Programmatic Key"
    permissions = data.get("permissions", "*")
    org = g.current_org
    allowed, violation = check_resource_quota(org, "api_keys", delta=1)
    if not allowed:
        return jsonify({
            "error": f"API key limit reached ({violation['limit']} maximum on {violation['plan_tier'].upper()} plan). Please revoke an existing key or upgrade.",
            "code": "QUOTA_EXCEEDED",
            "quota": violation
        }), 403

    user = g.current_user
    storage = get_storage()

    key_record, raw_secret = storage.create_api_key(
        organization_id=org.id,
        name=name,
        permissions=permissions,
        user_id=user.id if user else None
    )

    log_audit_event("api_key.create", "api_key", key_record.get("id"), {"name": name})

    return jsonify({
        "success": True,
        "message": "API Key created. Copy the secret now; it will not be displayed again.",
        "api_key": key_record,
        "secret_key": raw_secret,
        "secret_token": raw_secret
    }), 201


@api_v1.route("/api-keys/<key_id>", methods=["DELETE"])
@api_v1.route("/auth/api-keys/<key_id>", methods=["DELETE"])
@require_role(["owner", "admin"])
def revoke_api_key(key_id: str):
    org = g.current_org
    storage = get_storage()
    success = storage.revoke_api_key(key_id, org.id)
    if not success:
        return jsonify({"error": "API Key not found or already revoked.", "code": "NOT_FOUND"}), 404

    log_audit_event("api_key.revoke", "api_key", key_id)
    return jsonify({"success": True, "message": "API key successfully revoked."})


# ==========================================
# Workflows & Automation Rules (CRUD & Studio)
# ==========================================

@api_v1.route("/rules", methods=["GET"])
@api_v1.route("/workflows", methods=["GET"])
@require_auth
def list_rules():
    org = g.current_org
    category = request.args.get("category")
    enabled_only = request.args.get("enabled", "").lower() == "true"
    search = request.args.get("search", "").strip().lower()

    storage = get_storage()
    rules = storage.get_rules(category=category, enabled_only=enabled_only, organization_id=org.id)

    if search:
        rules = [
            r for r in rules
            if search in r["name"].lower()
            or search in r.get("description", "").lower()
            or search in r.get("category", "").lower()
        ]

    return jsonify({
        "success": True,
        "rules": rules,
        "workflows": rules,
        "count": len(rules),
        "organization_id": org.id
    })


@api_v1.route("/rules/<rule_id>", methods=["GET"])
@api_v1.route("/workflows/<rule_id>", methods=["GET"])
@require_auth
def get_rule(rule_id: str):
    org = g.current_org
    storage = get_storage()
    rule = storage.get_rule(rule_id, organization_id=org.id)
    if not rule:
        return jsonify({"error": f"Workflow rule '{rule_id}' not found.", "code": "NOT_FOUND"}), 404
    return jsonify({"success": True, "rule": rule, "workflow": rule})


@api_v1.route("/rules", methods=["POST"])
@api_v1.route("/workflows", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def create_rule():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Rule name is required.", "code": "VALIDATION_ERROR"}), 400

    org = g.current_org
    allowed, violation = check_resource_quota(org, "rules", delta=1)
    if not allowed:
        return jsonify({
            "error": "Rule limit exceeded for your current plan.",
            "code": "PLAN_LIMIT_EXCEEDED",
            "plan": org.plan_tier.upper() if org else "FREE",
            "quota": violation
        }), 403

    storage = get_storage()

    rule_id = storage.save_rule(data, organization_id=org.id)
    saved = storage.get_rule(rule_id, organization_id=org.id)

    log_audit_event("workflow.create", "automation_rule", rule_id, {"name": name})

    return jsonify({
        "success": True,
        "message": "Workflow created successfully.",
        "rule": saved,
        "workflow": saved
    }), 201


@api_v1.route("/rules/<rule_id>", methods=["PUT"])
@api_v1.route("/workflows/<rule_id>", methods=["PUT"])
@require_role(["owner", "admin", "operator"])
def update_rule(rule_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    storage = get_storage()

    existing = storage.get_rule(rule_id, organization_id=org.id)
    if not existing:
        return jsonify({"error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}), 404

    data["id"] = rule_id
    storage.save_rule(data, organization_id=org.id)
    updated = storage.get_rule(rule_id, organization_id=org.id)

    log_audit_event("workflow.update", "automation_rule", rule_id, {"name": updated.get("name")})

    return jsonify({"success": True, "rule": updated, "workflow": updated})


@api_v1.route("/rules/<rule_id>", methods=["DELETE"])
@api_v1.route("/workflows/<rule_id>", methods=["DELETE"])
@require_role(["owner", "admin", "operator"])
def delete_rule(rule_id: str):
    org = g.current_org
    storage = get_storage()
    success = storage.delete_rule(rule_id, organization_id=org.id)
    if not success:
        return jsonify({"error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("workflow.delete", "automation_rule", rule_id)
    return jsonify({"success": True, "message": f"Workflow '{rule_id}' deleted."})


@api_v1.route("/rules/<rule_id>/toggle", methods=["POST"])
@api_v1.route("/workflows/<rule_id>/toggle", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def toggle_rule(rule_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    storage = get_storage()
    new_state = storage.toggle_rule(rule_id, data.get("enabled"), organization_id=org.id)
    if new_state is None:
        return jsonify({"error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("workflow.toggle", "automation_rule", rule_id, {"enabled": new_state})
    return jsonify({"success": True, "enabled": new_state})


@api_v1.route("/rules/<rule_id>/duplicate", methods=["POST"])
@api_v1.route("/workflows/<rule_id>/duplicate", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def duplicate_rule(rule_id: str):
    org = g.current_org
    allowed, violation = check_resource_quota(org, "rules", delta=1)
    if not allowed:
        return jsonify({
            "error": "Rule limit exceeded for your current plan.",
            "code": "PLAN_LIMIT_EXCEEDED",
            "plan": org.plan_tier.upper() if org else "FREE",
            "quota": violation
        }), 403

    storage = get_storage()
    duplicated = storage.duplicate_rule(rule_id, organization_id=org.id)
    if not duplicated:
        return jsonify({"error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("workflow.duplicate", "automation_rule", duplicated["id"], {"source_rule_id": rule_id})
    return jsonify({
        "success": True,
        "message": f"Workflow duplicated successfully as '{duplicated['name']}'.",
        "workflow": duplicated,
        "rule": duplicated
    }), 201


@api_v1.route("/rules/<rule_id>/run", methods=["POST"])
@api_v1.route("/rules/<rule_id>/execute", methods=["POST"])
@api_v1.route("/workflows/<rule_id>/run", methods=["POST"])
@api_v1.route("/workflows/<rule_id>/execute", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def run_rule(rule_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    engine = get_engine()
    custom_payload = data.get("payload", {})
    dry_run = bool(data.get("dry_run", False))

    result = engine.execute_rule_manually(rule_id, custom_payload, dry_run=dry_run, organization_id=org.id)
    log_audit_event(
        "workflow.dry_run" if dry_run else "workflow.execute",
        "automation_rule",
        rule_id,
        {"dry_run": dry_run, "status": result.get("status")}
    )
    return jsonify(result)


@api_v1.route("/rules/export", methods=["GET"])
@api_v1.route("/workflows/export", methods=["GET"])
@require_auth
@require_feature("export_rules")
def export_rules():
    org = g.current_org
    storage = get_storage()
    rules = storage.get_rules(organization_id=org.id)
    return jsonify({
        "success": True,
        "rules": rules,
        "count": len(rules),
        "exported_at": datetime.datetime.utcnow().isoformat()
    })


# ==========================================
# Inbound Webhooks Gateway
# ==========================================

@api_v1.route("/webhooks", methods=["GET"])
@require_auth
def list_webhooks():
    org = g.current_org
    storage = get_storage()
    webhooks = storage.list_webhook_endpoints(org.id)
    base_url = request.host_url.rstrip("/")
    for wh in webhooks:
        wh["webhook_url"] = f"{base_url}/api/v1/webhooks/incoming/{wh['endpoint_token']}"
    return jsonify({"webhooks": webhooks, "count": len(webhooks)})


@api_v1.route("/webhooks", methods=["POST"])
@require_role(["owner", "admin"])
def create_webhook():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip() or "Inbound Ingestion Gateway"
    target_rule_id = data.get("target_rule_id")
    secret_token = data.get("secret_token")
    org = g.current_org
    allowed, violation = check_resource_quota(org, "webhooks", delta=1)
    if not allowed:
        return jsonify({
            "error": f"Webhook endpoint limit reached ({violation['limit']} maximum on {violation['plan_tier'].upper()} plan). Please delete an existing webhook or upgrade.",
            "code": "QUOTA_EXCEEDED",
            "quota": violation
        }), 403

    storage = get_storage()

    endpoint = storage.create_webhook_endpoint(
        organization_id=org.id,
        name=name,
        target_rule_id=target_rule_id,
        secret_token=secret_token
    )

    log_audit_event("webhook.create", "webhook_endpoint", endpoint.get("id"), {"name": name})

    base_url = request.host_url.rstrip("/")
    endpoint["webhook_url"] = f"{base_url}/api/v1/webhooks/incoming/{endpoint['endpoint_token']}"

    return jsonify({"success": True, "webhook": endpoint}), 201


@api_v1.route("/webhooks/<endpoint_id>", methods=["DELETE"])
@require_role(["owner", "admin"])
def delete_webhook(endpoint_id: str):
    org = g.current_org
    storage = get_storage()
    success = storage.delete_webhook_endpoint(endpoint_id, org.id)
    if not success:
        return jsonify({"error": f"Webhook endpoint '{endpoint_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("webhook.delete", "webhook_endpoint", endpoint_id)
    return jsonify({"success": True, "message": "Webhook endpoint deleted."})


def check_webhook_rate_limit(endpoint_token: str) -> Tuple[bool, int]:
    """Sliding-window rate limiter for inbound webhook endpoints.
    
    Returns:
        (is_allowed, retry_after_seconds)
    """
    if current_app.config.get("RATELIMIT_ENABLED") is False:
        return True, 0
    window = current_app.config.get("WEBHOOK_RATE_LIMIT_WINDOW", 60)
    limit = current_app.config.get("WEBHOOK_RATE_LIMIT", int(os.environ.get("WEBHOOK_RATE_LIMIT", 60)))
    is_limited, retry_after = limiter.is_rate_limited(f"webhook:{endpoint_token}", limit=limit, window=window)
    return not is_limited, retry_after


@api_v1.route("/webhooks/incoming/<endpoint_token>", methods=["POST"])
def incoming_webhook_receiver(endpoint_token: str):
    """PUBLIC GATEWAY for receiving webhooks from third-party services (GitHub, Stripe, Datadog)."""
    endpoint = WebhookEndpoint.query.filter_by(endpoint_token=endpoint_token, is_active=True).first()
    if not endpoint:
        return jsonify({"error": "Invalid or inactive webhook endpoint.", "code": "NOT_FOUND"}), 404

    # 1. Rate Limiting Check
    allowed, retry_after = check_webhook_rate_limit(endpoint_token)
    if not allowed:
        resp = jsonify({
            "error": "Rate limit exceeded for webhook endpoint.",
            "code": "TOO_MANY_REQUESTS",
            "retry_after": retry_after
        })
        resp.headers["Retry-After"] = str(retry_after)
        return resp, 429

    # 2. HMAC Signature verification if secret configured
    if endpoint.secret_token:
        signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Signature")
        if not signature:
            return jsonify({"error": "Missing HMAC signature header.", "code": "UNAUTHORIZED"}), 401
        raw_body = request.get_data()
        expected_sig = "sha256=" + hmac.new(
            endpoint.secret_token.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return jsonify({"error": "HMAC signature mismatch.", "code": "UNAUTHORIZED"}), 401

    # 3. Monthly Event Quota Check
    webhook_org = db.session.get(Organization, endpoint.organization_id)
    if webhook_org:
        quota_ok, violation = check_resource_quota(webhook_org, "monthly_events", delta=1)
        if not quota_ok:
            return jsonify({
                "error": "Monthly event quota exceeded.",
                "code": "QUOTA_EXCEEDED",
                "plan": webhook_org.plan_tier.upper(),
                "quota": violation
            }), 429

    payload = request.get_json(silent=True) or {}
    endpoint.request_count += 1
    endpoint.last_received_at = datetime.datetime.utcnow()
    db.session.commit()

    engine = get_engine()
    event_name = "webhook.incoming"
    if endpoint.target_rule_id:
        target_rule = db.session.get(AutomationRule, endpoint.target_rule_id)
        if target_rule:
            event_name = target_rule.get_trigger().get("event_name", "webhook.incoming")

    result = engine.ingest_event(
        event_name=event_name,
        payload=payload,
        source=f"webhook_{endpoint.name}",
        dry_run=False,
        organization_id=endpoint.organization_id
    )

    if webhook_org:
        QuotaService.record_event(webhook_org, event_name, payload, source=f"webhook_{endpoint.name}")

    return jsonify({
        "received": True,
        "endpoint": endpoint.name,
        "event_name": event_name,
        "result": result
    }), 200


# ==========================================
# Event Ingestion & NLP Engine
# ==========================================

@api_v1.route("/events/dispatch", methods=["POST"])
@api_v1.route("/events/ingest", methods=["POST"])
@api_v1.route("/events", methods=["POST"])
@require_auth
def dispatch_event():
    data = request.get_json(silent=True) or {}
    # Supports both {"event_name": "...", "payload": {...}} and {"event": "lead.created", "name": "...", ...}
    event_name = data.get("event_name") or data.get("event") or "custom.event"
    payload = data.get("payload")
    if payload is None:
        payload = {k: v for k, v in data.items() if k not in ("event", "event_name", "source", "dry_run")}

    source = data.get("source", "api_dispatch")
    dry_run = bool(data.get("dry_run", False))
    org = g.current_org

    if not dry_run and org:
        quota_ok, violation = check_resource_quota(org, "monthly_events", delta=1)
        if not quota_ok:
            return jsonify({
                "error": "Monthly event quota exceeded.",
                "code": "QUOTA_EXCEEDED",
                "plan": org.plan_tier.upper() if org else "FREE",
                "quota": violation
            }), 429

    # If this is a lead ingestion event, automatically qualify and persist the CRM Lead
    if (event_name == "lead.created" or "lead" in event_name) and not dry_run:
        message = payload.get("message") or payload.get("text") or ""
        ai_provider = get_ai_provider()
        analysis = ai_provider.analyze_text(message)
        email = payload.get("email") or (analysis.get("entities", {}).get("emails", [None])[0])
        name = payload.get("name") or "Website Visitor"
        if email or name:
            storage = get_storage()
            lead_data = {
                "name": name,
                "email": email,
                "phone": payload.get("phone") or (analysis.get("entities", {}).get("phones", [None])[0]),
                "company": payload.get("company") or "N/A",
                "message": message,
                "intent": analysis.get("intent", "lead_inquiry"),
                "sentiment": analysis.get("sentiment_label", "neutral"),
                "urgency_score": analysis.get("urgency_score", 20),
                "lead_score": analysis.get("lead_score", 50),
                "route_department": analysis.get("recommended_route", "Sales"),
                "status": "new",
                "draft_response": ai_provider.generate_draft_response(
                    name=name,
                    company=payload.get("company"),
                    intent=analysis.get("intent", "lead_inquiry"),
                    lead_score=analysis.get("lead_score", 50),
                    route_department=analysis.get("recommended_route", "Sales"),
                    message=message
                ),
                "organization_id": org.id
            }
            saved_lead = storage.save_lead(lead_data, organization_id=org.id)
            payload["lead_id"] = saved_lead.get("id")

    engine = get_engine()
    result = engine.ingest_event(
        event_name=event_name,
        payload=payload,
        source=source,
        dry_run=dry_run,
        organization_id=org.id
    )

    if not dry_run and org:
        QuotaService.record_event(org, event_name, payload, source=source)

    log_audit_event("event.dispatch", "event", event_name, {"event": event_name, "dry_run": dry_run})

    response_payload = dict(result)
    response_payload["success"] = True
    response_payload["result"] = result
    return jsonify(response_payload)


@api_v1.route("/nlp/analyze", methods=["POST"])
@require_auth
def nlp_analyze():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    dry_run = bool(data.get("dry_run", True))

    if not text:
        return jsonify({"error": "Text is required for NLP triage.", "code": "VALIDATION_ERROR"}), 400

    engine = get_engine()
    ai_provider = get_ai_provider()
    nlp_result = ai_provider.analyze_text(text)

    # Map intent to event
    event_name = "user.prompt"
    intent = nlp_result.get("intent")
    text_lower = text.lower()
    entities = nlp_result.get("entities", {})

    if intent in ("lead_inquiry", "sales"):
        event_name = "lead.created"
    elif intent == "server_alert" or any(w in text_lower for w in ("cpu", "metrics", "sentinel", "utilization")):
        event_name = "system.metrics"
    elif intent == "security_threat" or entities.get("ipv4"):
        event_name = "auth.failed"
    elif intent == "backup_request":
        event_name = "backup.completed"
    elif intent == "deploy_request":
        event_name = "deploy.pipeline"
    elif entities.get("http_status"):
        event_name = "api.error"

    simulation = engine.ingest_event(
        event_name=event_name,
        payload={
            "text": text,
            "message": text,
            "prompt": text,
            "intent": nlp_result.get("intent"),
            "urgency": nlp_result.get("urgency")
        },
        source="nlp_sandbox",
        dry_run=dry_run
    )

    return jsonify({
        "nlp": nlp_result,
        "event_inferred": event_name,
        "simulation": simulation
    })


# ==========================================
# CRM Leads & Inquiry Pipeline
# ==========================================

@api_v1.route("/leads", methods=["GET"])
@require_auth
def list_leads():
    org = g.current_org
    status = request.args.get("status")
    search = request.args.get("search")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    storage = get_storage()
    leads = storage.get_leads(organization_id=org.id, status=status, search=search, limit=limit, offset=offset)
    return jsonify({"leads": leads, "count": len(leads)})


@api_v1.route("/leads", methods=["POST"])
@require_auth
def create_lead():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip() or data.get("text", "").strip()

    org = g.current_org
    engine = get_engine()
    storage = get_storage()

    # Deterministic AI Qualification
    ai_provider = get_ai_provider()
    analysis = ai_provider.analyze_text(message)

    lead_data = {
        "name": data.get("name") or "Website Visitor",
        "email": data.get("email") or (analysis.get("entities", {}).get("emails", [None])[0]),
        "phone": data.get("phone") or (analysis.get("entities", {}).get("phones", [None])[0]),
        "company": data.get("company") or "N/A",
        "message": message,
        "intent": analysis.get("intent", "lead_inquiry"),
        "sentiment": analysis.get("sentiment_label", "neutral"),
        "urgency_score": analysis.get("urgency_score", 20),
        "lead_score": analysis.get("lead_score", 50),
        "route_department": analysis.get("recommended_route", "Sales"),
        "status": data.get("status", "new"),
        "draft_response": ai_provider.generate_draft_response(
            name=data.get("name"),
            company=data.get("company"),
            intent=analysis.get("intent", "lead_inquiry"),
            lead_score=analysis.get("lead_score", 50),
            route_department=analysis.get("recommended_route", "Sales"),
            message=message
        ),
        "organization_id": org.id
    }

    saved = storage.save_lead(lead_data, organization_id=org.id)

    # Ingest event so matching workflow rules (e.g. AI Lead Qualification) can trigger
    engine.ingest_event(
        event_name="lead.created",
        payload=lead_data,
        source="lead_pipeline",
        dry_run=False,
        organization_id=org.id
    )

    log_audit_event("lead.create", "lead", saved.get("id"), {"email": saved.get("email"), "lead_score": saved.get("lead_score")})

    return jsonify({"success": True, "lead": saved}), 201


@api_v1.route("/leads/<lead_id>", methods=["GET"])
@require_auth
def get_lead_detail(lead_id: str):
    org = g.current_org
    storage = get_storage()
    lead = storage.get_lead(lead_id, organization_id=org.id)
    if not lead:
        return jsonify({"error": f"Lead '{lead_id}' not found.", "code": "NOT_FOUND"}), 404
    return jsonify({"success": True, "lead": lead})


@api_v1.route("/leads/<lead_id>", methods=["PATCH", "PUT"])
@api_v1.route("/leads/<lead_id>/status", methods=["PATCH", "PUT", "POST"])
@require_role(["owner", "admin", "operator"])
def update_lead(lead_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    storage = get_storage()

    lead = storage.get_lead(lead_id, organization_id=org.id)
    if not lead:
        return jsonify({"error": f"Lead '{lead_id}' not found.", "code": "NOT_FOUND"}), 404

    new_status = data.get("status")
    if new_status:
        storage.update_lead_status(lead_id, new_status, organization_id=org.id)

    updated = storage.get_lead(lead_id, organization_id=org.id)
    log_audit_event("lead.update", "lead", lead_id, {"status": new_status})
    return jsonify({"success": True, "lead": updated})


@api_v1.route("/leads/<lead_id>", methods=["DELETE"])
@require_role(["owner", "admin"])
def delete_lead(lead_id: str):
    org = g.current_org
    storage = get_storage()
    success = storage.delete_lead(lead_id, organization_id=org.id)
    if not success:
        return jsonify({"error": f"Lead '{lead_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("lead.delete", "lead", lead_id)
    return jsonify({"success": True, "message": f"Lead '{lead_id}' deleted."})


# ==========================================
# Execution Forensics & Audits
# ==========================================

@api_v1.route("/executions", methods=["GET"])
@require_auth
def get_executions():
    org = g.current_org
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    rule_id = request.args.get("rule_id")

    storage = get_storage()
    logs = storage.get_logs(limit=limit, offset=offset, status=status, rule_id=rule_id, organization_id=org.id)
    return jsonify({"executions": logs, "count": len(logs)})


@api_v1.route("/executions/<int:exec_id>", methods=["GET"])
@require_auth
def get_execution_detail(exec_id: int):
    storage = get_storage()
    execution = storage.get_execution(exec_id)
    if not execution:
        return jsonify({"error": f"Execution '{exec_id}' not found.", "code": "NOT_FOUND"}), 404
    return jsonify({"execution": execution})


@api_v1.route("/executions", methods=["DELETE"])
@require_role(["owner", "admin"])
def clear_executions():
    org = g.current_org
    storage = get_storage()
    storage.clear_logs(organization_id=org.id)
    log_audit_event("executions.clear", "workflow_executions", None)
    return jsonify({"success": True, "message": "Execution logs cleared."})


# ==========================================
# Real-Database Analytics
# ==========================================

@api_v1.route("/analytics", methods=["GET"])
@require_auth
def get_analytics():
    org = g.current_org
    storage = get_storage()
    analytics = storage.get_analytics_summary(organization_id=org.id)
    return jsonify({"analytics": analytics, "organization_id": org.id})


# ==========================================
# Workflow Templates Library (8 Enterprise Templates)
# ==========================================

@api_v1.route("/templates", methods=["GET"])
@require_auth
def list_templates():
    return jsonify({"templates": PRESET_BLUEPRINTS, "count": len(PRESET_BLUEPRINTS)})


@api_v1.route("/templates/<template_id>/install", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def install_template(template_id: str):
    org = g.current_org
    allowed, violation = check_resource_quota(org, "rules", delta=1)
    if not allowed:
        return jsonify({
            "error": "Rule limit exceeded for your current plan.",
            "code": "PLAN_LIMIT_EXCEEDED",
            "plan": org.plan_tier.upper() if org else "FREE",
            "quota": violation
        }), 403

    storage = get_storage()

    selected = next((p for p in PRESET_BLUEPRINTS if p["id"] == template_id), None)
    if not selected:
        return jsonify({"error": f"Template '{template_id}' not found.", "code": "NOT_FOUND"}), 404

    new_rule = dict(selected)
    new_rule["id"] = f"wf-{int(time.time() * 1000)}"
    new_rule["organization_id"] = org.id
    new_rule["enabled"] = 1
    new_rule["name"] = f"{selected['name']}"

    rule_id = storage.save_rule(new_rule, organization_id=org.id)
    installed = storage.get_rule(rule_id, organization_id=org.id)

    log_audit_event("template.install", "automation_rule", rule_id, {"template": selected["name"]})

    return jsonify({
        "success": True,
        "message": f"Template '{selected['name']}' installed successfully into your workspace.",
        "workflow": installed,
        "rule_id": rule_id
    }), 201


# ==========================================
# Incident Response & Alerts
# ==========================================

@api_v1.route("/alerts", methods=["GET"])
@require_auth
def get_alerts():
    org = g.current_org
    status = request.args.get("status")
    storage = get_storage()
    alerts = storage.list_incident_alerts(organization_id=org.id, status=status)
    return jsonify({"alerts": alerts, "count": len(alerts)})


@api_v1.route("/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def acknowledge_alert(alert_id: int):
    org = g.current_org
    user = g.current_user
    storage = get_storage()
    alert = storage.acknowledge_incident(alert_id, user.id if user else "system", org.id)
    if not alert:
        return jsonify({"error": f"Alert '{alert_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("alert.acknowledge", "incident_alert", str(alert_id))
    return jsonify({"success": True, "alert": alert})


@api_v1.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def resolve_alert(alert_id: int):
    data = request.get_json(silent=True) or {}
    notes = data.get("notes")
    org = g.current_org
    user = g.current_user
    storage = get_storage()
    alert = storage.resolve_incident(alert_id, user.id if user else "system", org.id, notes=notes)
    if not alert:
        return jsonify({"error": f"Alert '{alert_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("alert.resolve", "incident_alert", str(alert_id), {"notes": notes})
    return jsonify({"success": True, "alert": alert})


# ==========================================
# Compliance Audit Trail & System Health
# ==========================================

@api_v1.route("/audit-trail", methods=["GET"])
@require_role(["owner", "admin"])
@require_feature("audit_trail")
def get_audit_trail():
    org = g.current_org
    limit = int(request.args.get("limit", 50))
    audits = AuditLog.query.filter_by(organization_id=org.id).order_by(desc(AuditLog.created_at)).limit(limit).all()
    return jsonify({"audit_trail": [a.to_dict() for a in audits], "count": len(audits)})


@api_v1.route("/health", methods=["GET"])
@api_v1.route("/system/health", methods=["GET"])
def system_health():
    engine = get_engine()
    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    dialect = "postgresql" if "postgres" in db_uri else "sqlite_wal"
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "database": dialect,
        "engine_online": engine.is_running if engine else False,
        "version": "2.4.0-enterprise",
        "cloud_ready": True
    }), 200


@api_v1.route("/system/telemetry", methods=["GET"])
def system_telemetry():
    engine = get_engine()
    storage = get_storage()
    stats = storage.get_stats() if storage else {}
    telemetry = engine.telemetry.get_metrics() if engine else {}
    return jsonify({
        "stats": stats,
        "telemetry": telemetry,
        "engine_online": engine.is_running if engine else False
    })


@api_v1.route("/system/engine/toggle", methods=["POST"])
@require_role(["owner", "admin"])
def toggle_engine():
    data = request.get_json(silent=True) or {}
    engine = get_engine()
    desired_state = data.get("online")
    new_state = engine.toggle_state(desired_state)
    log_audit_event("engine.toggle", "system", None, {"online": new_state})
    return jsonify({"success": True, "engine_running": new_state})


# ==========================================
# Settings & AI Providers Configuration
# ==========================================

@api_v1.route("/settings", methods=["GET"])
@require_auth
def get_settings():
    manager = AIProviderManager.get_instance()
    providers = manager.list_providers()
    active_prov = next((p for p in providers if p.get("is_active")), providers[0])
    return jsonify({
        "ai_provider": active_prov,
        "available_ai_providers": providers,
        "default_dry_run": False,
        "auto_retry_webhooks": True,
        "max_retries": 3,
        "security_policy": {
            "session_timeout_days": 7,
            "csrf_protection": True,
            "safe_simulation_default": True
        }
    })


@api_v1.route("/ai/providers", methods=["GET"])
@require_auth
def list_ai_providers():
    manager = AIProviderManager.get_instance()
    return jsonify({"providers": manager.list_providers()})


@api_v1.route("/ai/provider", methods=["POST"])
@api_v1.route("/ai/providers/switch", methods=["POST"])
@require_role(["owner", "admin"])
def switch_ai_provider():
    data = request.get_json(silent=True) or {}
    provider_name = data.get("provider", "local_deterministic")
    api_key = data.get("api_key")

    org = g.current_org
    allowed, required_tier = check_ai_provider_entitlement(org, provider_name)
    if not allowed:
        return jsonify({
            "error": "This feature is not available on your current plan.",
            "code": "FEATURE_NOT_AVAILABLE",
            "plan": org.plan_tier.upper(),
            "provider": provider_name,
            "required_plan": required_tier.upper()
        }), 403

    manager = AIProviderManager.get_instance()
    success = manager.set_active_provider(provider_name, api_key=api_key)

    if not success:
        return jsonify({"error": f"Unknown provider '{provider_name}'.", "code": "VALIDATION_ERROR"}), 400

    log_audit_event("settings.ai_provider_switch", "settings", provider_name)
    return jsonify({
        "success": True,
        "message": f"Active AI Provider updated to '{provider_name}'.",
        "providers": manager.list_providers()
    })


# ==========================================
# Plan Entitlement & Quotas Endpoints
# ==========================================

@api_v1.route("/plans", methods=["GET"])
def get_available_plans():
    """Lists all available plan specifications."""
    return jsonify({"plans": list_plans(), "count": len(list_plans())})


@api_v1.route("/billing/plan", methods=["GET"])
@api_v1.route("/plan", methods=["GET"])
@api_v1.route("/quotas", methods=["GET"])
@require_auth
def get_current_plan_and_quotas():
    """Returns live quota usage, remaining capacity, and plan entitlements for the organization."""
    org = g.current_org
    plan_def = QuotaService.get_plan(org)
    max_rules = QuotaService.get_max_rules(org)
    current_rule_count = QuotaService.get_rules_count(org)
    monthly_event_limit = QuotaService.get_max_monthly_events(org)
    current_monthly_event_usage = QuotaService.get_monthly_events_count(org)
    features = plan_def.get("features", {})
    entitlements = get_org_entitlements(org)

    return jsonify({
        "success": True,
        "current_plan": org.plan_tier.upper(),
        "plan": org.plan_tier.upper(),
        "plan_tier": org.plan_tier,
        "max_rules": max_rules,
        "current_rule_count": current_rule_count,
        "rule_count": current_rule_count,
        "monthly_event_limit": monthly_event_limit,
        "max_monthly_events": monthly_event_limit,
        "current_monthly_event_usage": current_monthly_event_usage,
        "monthly_event_usage": current_monthly_event_usage,
        "period": QuotaService.get_current_period(),
        "relevant_feature_flags": features,
        "feature_flags": features,
        "features": features,
        "entitlements": entitlements
    })


@api_v1.route("/plan/upgrade", methods=["POST"])
@api_v1.route("/organizations/plan", methods=["POST"])
@require_role(["owner", "admin"])
def upgrade_plan():
    """Upgrades or updates the workspace plan tier and syncs quota capacity."""
    data = request.get_json(silent=True) or {}
    target_tier = (data.get("plan_tier") or data.get("tier") or "").strip().lower()

    if target_tier not in PLAN_DEFINITIONS:
        return jsonify({
            "error": f"Invalid plan tier '{target_tier}'. Valid tiers: {list(PLAN_DEFINITIONS.keys())}",
            "code": "VALIDATION_ERROR"
        }), 400

    org = g.current_org
    old_tier = org.plan_tier
    plan_spec = get_plan(target_tier)

    org.plan_tier = target_tier
    org.max_rules = plan_spec["quotas"]["max_rules"]
    org.max_monthly_events = plan_spec["quotas"]["max_monthly_events"]
    db.session.commit()

    log_audit_event("plan.upgrade", "organization", org.id, {"from_tier": old_tier, "to_tier": target_tier})

    return jsonify({
        "success": True,
        "message": f"Successfully updated workspace plan to '{plan_spec['name']}'.",
        "organization": org.to_dict(),
        "entitlements": get_org_entitlements(org)
    })
