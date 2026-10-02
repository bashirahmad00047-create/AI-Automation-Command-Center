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
import logging
import os
import re
import secrets
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
    OrganizationUsage,
    StripeWebhookEvent,
    Subscription,
    SystemEvent,
    User,
    WebhookEndpoint,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
    generate_uuid,
)
from presets import PRESET_BLUEPRINTS
from billing_service import (
    BillingError,
    InvalidPlanError,
    StripeNotConfiguredError,
    create_checkout_session,
    create_customer_portal_session,
    get_billing_status,
    is_stripe_configured,
    process_webhook_event,
    sync_organization_subscription,
    verify_webhook_signature,
)

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")
logger = logging.getLogger("opsflow.api")


def get_engine():
    """Helper to retrieve the global AutomationEngine instance."""
    from flask import current_app
    return current_app.config.get("AUTOMATION_ENGINE")


def get_storage():
    """Helper to retrieve the global Storage instance."""
    from flask import current_app
    return current_app.config.get("STORAGE_ENGINE")


def normalize_slug(text: str) -> str:
    """Converts organization or project name into a clean, URL-safe slug."""
    text = (text or "").lower().strip()
    text = re.sub(r'[^a-z0-9\-]+', '-', text)
    text = re.sub(r'\-+', '-', text)
    return text.strip('-')


@api_v1.route("/auth/check-slug", methods=["GET"])
def check_slug_availability():
    """Checks if a workspace slug is available for self-service tenant registration."""
    raw_slug = request.args.get("slug", "").strip().lower()
    raw_name = request.args.get("name", "").strip()

    if not raw_slug and raw_name:
        raw_slug = normalize_slug(raw_name)

    if not raw_slug:
        return jsonify({"available": False, "error": "Slug or name parameter is required.", "code": "VALIDATION_ERROR"}), 400

    normalized = normalize_slug(raw_slug)
    if len(normalized) < 3 or len(normalized) > 64:
        return jsonify({
            "available": False,
            "slug": normalized,
            "error": "Slug must be between 3 and 64 characters.",
            "code": "VALIDATION_ERROR"
        }), 200

    if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', normalized):
        return jsonify({
            "available": False,
            "slug": normalized,
            "error": "Slug may only contain lowercase letters, numbers, and hyphens.",
            "code": "VALIDATION_ERROR"
        }), 200

    existing = Organization.query.filter_by(slug=normalized).first()
    if existing:
        return jsonify({
            "available": False,
            "slug": normalized,
            "reason": "Already in use"
        }), 200

    return jsonify({
        "available": True,
        "slug": normalized,
        "reason": "Available"
    }), 200


@api_v1.route("/auth/register", methods=["POST"])
@rate_limit(limit=5, window=60, config_key="REGISTER_RATE_LIMIT", message="Too many registration attempts. Please try again later.")
def auth_register():
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()
    full_name = data.get("full_name", "").strip()
    org_name = data.get("org_name", "").strip() or data.get("organization_name", "").strip() or data.get("workspace_name", "").strip() or f"{full_name}'s Workspace"
    raw_slug = (data.get("slug") or data.get("organization_slug") or data.get("workspace_slug") or "").strip().lower()
    install_starter_blueprints = data.get("install_starter_blueprints", data.get("starter_blueprints", True))

    if not email or "@" not in email:
        return jsonify({"error": "A valid email address is required.", "code": "VALIDATION_ERROR"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters.", "code": "VALIDATION_ERROR"}), 400
    if not full_name:
        return jsonify({"error": "Full name is required.", "code": "VALIDATION_ERROR"}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"error": "An account with this email already exists.", "code": "CONFLICT"}), 409

    # Determine and validate workspace slug
    if raw_slug:
        slug = normalize_slug(raw_slug)
        if len(slug) < 3 or len(slug) > 64:
            return jsonify({"error": "Workspace slug must be between 3 and 64 characters.", "code": "VALIDATION_ERROR"}), 400
        if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', slug):
            return jsonify({"error": "Workspace slug may only contain lowercase letters, numbers, and hyphens.", "code": "VALIDATION_ERROR"}), 400
        existing_org = Organization.query.filter_by(slug=slug).first()
        if existing_org:
            return jsonify({"error": "This workspace URL slug is already taken.", "code": "SLUG_ALREADY_EXISTS"}), 409
    else:
        base_slug = normalize_slug(org_name) if org_name else normalize_slug(email.split('@')[0])
        if len(base_slug) < 3:
            base_slug = f"org-{base_slug}"
        candidate = base_slug[:48]
        if Organization.query.filter_by(slug=candidate).first():
            candidate = f"{candidate[:40]}-{generate_uuid()[:6]}".lower()
        slug = candidate

    try:
        # Create organization defaulting to Free plan
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

        # Initialize OrganizationUsage for the current billing period
        current_period = datetime.datetime.utcnow().strftime("%Y-%m")
        initial_usage = OrganizationUsage(
            id=generate_uuid("usg"),
            organization_id=org.id,
            period=current_period,
            event_count=0
        )
        db.session.add(initial_usage)

        db.session.commit()

        # Optional turnkey onboarding starter blueprints installation
        starter_blueprints = []
        if install_starter_blueprints:
            try:
                storage = get_storage()
                # Select 3 foundational turnkey templates (Lead qualification, Critical incident, API failure)
                starter_defs = [
                    bp for bp in PRESET_BLUEPRINTS
                    if bp.get("id") in ("template-ai-lead-qualification", "template-critical-incident-router", "template-api-failure-alert")
                ][:3]
                for bp in starter_defs:
                    new_rule = dict(bp)
                    new_rule["id"] = f"wf-{int(time.time() * 1000)}-{generate_uuid()[:4]}"
                    new_rule["organization_id"] = org.id
                    new_rule["enabled"] = 1
                    rule_id = storage.save_rule(new_rule, organization_id=org.id)
                    starter_blueprints.append({"id": rule_id, "name": bp["name"], "category": bp.get("category")})
            except Exception as _bp_err:
                current_app.logger.warning(f"Onboarding starter blueprints installation note: {_bp_err}")

        # Log audit trail
        log_audit_event("auth.register", "user", user.id, {
            "email": email,
            "organization_id": org.id,
            "organization_name": org.name,
            "slug": org.slug,
            "plan_tier": org.plan_tier
        }, org_id=org.id, user_id=user.id)

        # Set authenticated session
        session["user_id"] = user.id
        session["active_org_id"] = org.id

        return jsonify({
            "success": True,
            "message": "User account and tenant workspace registered successfully.",
            "user": user.to_dict(),
            "organization": org.to_dict(),
            "role": "owner",
            "initial_api_key": full_key,
            "starter_blueprints": starter_blueprints
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
# Team & Workspace Access Management
# ==========================================

@api_v1.route("/organizations/current", methods=["GET"])
@require_auth
def get_current_organization():
    org = g.current_org
    if not org:
        return jsonify({"error": "No active organization.", "code": "NOT_FOUND"}), 404
    entitlements = get_org_entitlements(org)
    return jsonify({
        "organization": org.to_dict(),
        "entitlements": entitlements
    }), 200


@api_v1.route("/organizations/current", methods=["PUT", "PATCH"])
@require_role(["owner", "admin"])
def update_current_organization():
    org = g.current_org
    if not org:
        return jsonify({"error": "No active organization.", "code": "NOT_FOUND"}), 404
    data = request.get_json(silent=True) or {}
    new_name = data.get("name")
    if new_name and new_name.strip():
        org.name = new_name.strip()
        db.session.commit()
        log_audit_event("organization.update", "organization", org.id, {"name": org.name})
    return jsonify({"success": True, "organization": org.to_dict()}), 200


@api_v1.route("/team/members", methods=["GET"])
@api_v1.route("/organizations/members", methods=["GET"])
@require_auth
def list_team_members():
    org = g.current_org
    if not org:
        return jsonify({"error": "No active organization.", "code": "NOT_FOUND"}), 404
    plan_def = QuotaService.get_plan(org)
    max_seats = plan_def["quotas"]["max_team_members"]

    memberships = Membership.query.filter_by(organization_id=org.id).all()
    member_list = []
    for m in memberships:
        u = m.user
        member_list.append({
            "membership_id": m.id,
            "user_id": u.id if u else None,
            "email": u.email if u else "unknown",
            "full_name": u.full_name if u else "Invited Member",
            "role": m.role,
            "joined_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else None,
            "is_active": u.is_active if u else True
        })

    current_count = len(memberships)
    return jsonify({
        "organization_id": org.id,
        "organization_name": org.name,
        "plan_tier": org.plan_tier,
        "members": member_list,
        "seats": {
            "current": current_count,
            "limit": max_seats,
            "remaining": max(0, max_seats - current_count),
            "is_exceeded": current_count >= max_seats
        },
        "count": current_count
    }), 200


@api_v1.route("/team/invite", methods=["POST"])
@api_v1.route("/organizations/members", methods=["POST"])
@require_role(["owner", "admin"])
def invite_team_member():
    org = g.current_org
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})
    email = data.get("email", "").strip().lower()
    role = data.get("role", "operator").strip().lower()
    full_name = data.get("full_name", "").strip() or email.split("@")[0].title()

    if not email or "@" not in email:
        return jsonify({"error": "A valid email address is required.", "code": "VALIDATION_ERROR"}), 400

    if role not in ("admin", "operator", "viewer"):
        return jsonify({"error": "Role must be 'admin', 'operator', or 'viewer'.", "code": "VALIDATION_ERROR"}), 400

    # Enforce team seats quota
    allowed, violation = check_resource_quota(org, "team_members", delta=1)
    if not allowed:
        return jsonify({
            "error": f"Team member seat limit reached ({violation.get('limit')} maximum on {violation.get('plan_tier', 'FREE').upper()} plan). Please upgrade your plan.",
            "code": "QUOTA_EXCEEDED",
            "resource": "team_members",
            "quota": violation
        }), 403

    # Check if user already exists
    user = User.query.filter_by(email=email).first()
    if user:
        existing_mem = Membership.query.filter_by(user_id=user.id, organization_id=org.id).first()
        if existing_mem:
            return jsonify({
                "error": f"User '{email}' is already a member of this workspace (role: {existing_mem.role}).",
                "code": "CONFLICT"
            }), 409
    else:
        user = User(
            id=generate_uuid("usr"),
            email=email,
            full_name=full_name,
            is_active=True,
            is_superuser=False
        )
        temp_password = secrets.token_urlsafe(16)
        user.set_password(temp_password)
        db.session.add(user)
        db.session.flush()

    membership = Membership(
        id=generate_uuid("mem"),
        user_id=user.id,
        organization_id=org.id,
        role=role
    )
    db.session.add(membership)
    db.session.commit()

    log_audit_event("team.member_invite", "membership", membership.id, {
        "email": email,
        "role": role,
        "organization_id": org.id
    })

    return jsonify({
        "success": True,
        "message": f"Team member '{email}' invited successfully as '{role}'.",
        "member": {
            "membership_id": membership.id,
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": role,
            "created_at": membership.created_at.strftime("%Y-%m-%d %H:%M:%S") if membership.created_at else None
        }
    }), 201


@api_v1.route("/team/members/<target_id>", methods=["DELETE"])
@require_role(["owner", "admin"])
def remove_team_member(target_id: str):
    org = g.current_org
    membership = Membership.query.filter(
        Membership.organization_id == org.id,
        (Membership.id == target_id) | (Membership.user_id == target_id)
    ).first()

    if not membership:
        return jsonify({"error": "Member not found in this organization.", "code": "NOT_FOUND"}), 404

    # Prevent removing the last owner
    if membership.role == "owner":
        owner_count = Membership.query.filter_by(organization_id=org.id, role="owner").count()
        if owner_count <= 1:
            return jsonify({
                "error": "Cannot remove the only owner of the workspace.",
                "code": "FORBIDDEN"
            }), 403

    user_email = membership.user.email if membership.user else target_id
    db.session.delete(membership)
    db.session.commit()

    log_audit_event("team.member_remove", "membership", target_id, {
        "email": user_email,
        "organization_id": org.id
    })

    return jsonify({
        "success": True,
        "message": f"Team member '{user_email}' removed from workspace."
    }), 200


@api_v1.route("/team/members/<target_id>", methods=["PUT", "PATCH"])
@require_role(["owner", "admin"])
def update_team_member_role(target_id: str):
    org = g.current_org
    membership = Membership.query.filter(
        Membership.organization_id == org.id,
        (Membership.id == target_id) | (Membership.user_id == target_id)
    ).first()

    if not membership:
        return jsonify({"error": "Member not found in this organization.", "code": "NOT_FOUND"}), 404

    data = request.get_json(silent=True) or {}
    new_role = data.get("role", "").strip().lower()
    if new_role not in ("owner", "admin", "operator", "viewer"):
        return jsonify({"error": "Role must be 'owner', 'admin', 'operator', or 'viewer'.", "code": "VALIDATION_ERROR"}), 400

    current_user_role = get_user_role(g.current_user.id, org.id)
    if (new_role == "owner" or membership.role == "owner") and current_user_role != "owner":
        return jsonify({"error": "Only workspace owners can promote or modify owner roles.", "code": "FORBIDDEN"}), 403

    membership.role = new_role
    db.session.commit()

    log_audit_event("team.role_change", "membership", membership.id, {
        "email": membership.user.email if membership.user else target_id,
        "new_role": new_role
    })

    return jsonify({
        "success": True,
        "message": f"Updated member role to '{new_role}'.",
        "member": {
            "membership_id": membership.id,
            "user_id": membership.user_id,
            "role": new_role
        }
    }), 200


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
        log_audit_event("quota.exceeded", "quota", "rules", {"plan": org.plan_tier if org else "free", "violation": violation})
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
        log_audit_event("quota.exceeded", "quota", "rules", {"plan": org.plan_tier if org else "free", "violation": violation})
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


@api_v1.route("/rules/<rule_id>/dispatch-async", methods=["POST"])
@api_v1.route("/workflows/<rule_id>/dispatch-async", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def dispatch_workflow_async(rule_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    engine = get_engine()
    custom_payload = data.get("payload", {})
    dry_run = bool(data.get("dry_run", False))

    if not dry_run and org:
        quota_ok, violation = check_resource_quota(org, "monthly_events", delta=1)
        if not quota_ok:
            return jsonify({
                "error": "Monthly event quota exceeded.",
                "code": "QUOTA_EXCEEDED",
                "plan": org.plan_tier.upper() if org else "FREE",
                "quota": violation
            }), 429

    result = engine.dispatch_job_async(rule_id, custom_payload, dry_run=dry_run, organization_id=org.id)
    if not result.get("success"):
        status_code = 404 if result.get("code") == "NOT_FOUND" else 429
        return jsonify(result), status_code

    log_audit_event(
        "workflow.dispatch_async",
        "automation_rule",
        rule_id,
        {"job_id": result.get("job_id"), "dry_run": dry_run}
    )
    return jsonify(result), 202


@api_v1.route("/jobs", methods=["GET"])
@api_v1.route("/workflows/jobs", methods=["GET"])
@require_auth
def list_execution_jobs():
    org = g.current_org
    engine = get_engine()
    limit = int(request.args.get("limit", 50))
    status = request.args.get("status")
    jobs = engine.list_jobs(organization_id=org.id, limit=limit, status=status)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api_v1.route("/jobs/<job_id>", methods=["GET"])
@api_v1.route("/workflows/jobs/<job_id>", methods=["GET"])
@require_auth
def get_execution_job(job_id: str):
    org = g.current_org
    engine = get_engine()
    job = engine.get_job(job_id, organization_id=org.id)
    if not job:
        return jsonify({"error": f"Execution job '{job_id}' not found.", "code": "NOT_FOUND"}), 404
    return jsonify({"job": job})


@api_v1.route("/jobs/<job_id>/cancel", methods=["POST"])
@api_v1.route("/workflows/jobs/<job_id>/cancel", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def cancel_execution_job(job_id: str):
    org = g.current_org
    engine = get_engine()
    cancelled = engine.cancel_job(job_id, organization_id=org.id)
    if not cancelled:
        return jsonify({"error": f"Job '{job_id}' not found or already completed/cancelled.", "code": "NOT_FOUND"}), 404

    log_audit_event("workflow.job_cancel", "workflow_job", job_id)
    return jsonify({"success": True, "message": f"Job '{job_id}' successfully cancelled.", "job_id": job_id})


@api_v1.route("/rules/<rule_id>/schedule", methods=["POST", "PUT"])
@api_v1.route("/workflows/<rule_id>/schedule", methods=["POST", "PUT"])
@require_role(["owner", "admin", "operator"])
def configure_workflow_schedule(rule_id: str):
    data = request.get_json(silent=True) or {}
    org = g.current_org
    storage = get_storage()
    rule = storage.get_rule(rule_id, organization_id=org.id)
    if not rule:
        return jsonify({"error": f"Workflow '{rule_id}' not found.", "code": "NOT_FOUND"}), 404

    interval_minutes = int(data.get("interval_minutes", data.get("interval", 60)))
    enabled = bool(data.get("enabled", True))

    trigger = rule.get("trigger", {})
    trigger["type"] = "schedule"
    trigger["interval_minutes"] = interval_minutes
    trigger["schedule_enabled"] = enabled

    rule["trigger"] = trigger
    rule["enabled"] = 1 if enabled else rule.get("enabled", 1)
    storage.save_rule(rule, organization_id=org.id)

    log_audit_event("workflow.schedule", "automation_rule", rule_id, {"interval_minutes": interval_minutes, "enabled": enabled})
    return jsonify({
        "success": True,
        "message": f"Workflow '{rule['name']}' schedule set to every {interval_minutes} minutes.",
        "workflow_id": rule_id,
        "interval_minutes": interval_minutes,
        "enabled": enabled
    })


@api_v1.route("/workflows/schedules", methods=["GET"])
@require_auth
def list_scheduled_workflows():
    org = g.current_org
    storage = get_storage()
    rules = storage.get_rules(organization_id=org.id)
    scheduled = []
    for r in rules:
        t = r.get("trigger", {})
        if t.get("type") in ("schedule", "cron", "interval") or t.get("interval_minutes"):
            scheduled.append({
                "workflow_id": r["id"],
                "name": r["name"],
                "interval_minutes": t.get("interval_minutes", 60),
                "enabled": bool(r.get("enabled")),
                "last_triggered": r.get("last_triggered")
            })
    return jsonify({"scheduled_workflows": scheduled, "count": len(scheduled)})


@api_v1.route("/dlq", methods=["GET"])
@api_v1.route("/workflows/dlq", methods=["GET"])
@require_role(["owner", "admin", "operator"])
def list_dlq_items():
    org = g.current_org
    engine = get_engine()
    status = request.args.get("status")
    items = engine.get_dlq(organization_id=org.id, status=status)
    return jsonify({"dlq": items, "count": len(items)})


@api_v1.route("/dlq/<dlq_id>/replay", methods=["POST"])
@api_v1.route("/workflows/dlq/<dlq_id>/replay", methods=["POST"])
@require_role(["owner", "admin", "operator"])
def replay_dlq_item(dlq_id: str):
    org = g.current_org
    engine = get_engine()
    res = engine.replay_dlq(dlq_id, organization_id=org.id)
    if not res.get("success"):
        code = 404 if res.get("code") == "NOT_FOUND" else 403
        return jsonify(res), code

    log_audit_event("dlq.replay", "dead_letter_queue", dlq_id, {"status": res.get("status")})
    return jsonify(res)


@api_v1.route("/dlq/<dlq_id>", methods=["DELETE"])
@api_v1.route("/workflows/dlq/<dlq_id>", methods=["DELETE"])
@require_role(["owner", "admin"])
def delete_dlq_item(dlq_id: str):
    org = g.current_org
    engine = get_engine()
    deleted = engine.delete_dlq(dlq_id, organization_id=org.id)
    if not deleted:
        return jsonify({"error": f"DLQ item '{dlq_id}' not found.", "code": "NOT_FOUND"}), 404

    log_audit_event("dlq.delete", "dead_letter_queue", dlq_id)
    return jsonify({"success": True, "message": f"DLQ item '{dlq_id}' purged.", "dlq_id": dlq_id})



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
        log_audit_event("quota.exceeded", "quota", "webhooks", {"plan": org.plan_tier if org else "free", "violation": violation})
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
            log_audit_event("quota.exceeded", "quota", "monthly_events", {"plan": org.plan_tier.upper() if org else "FREE", "violation": violation})
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


@api_v1.route("/ai/generate", methods=["POST"])
@api_v1.route("/nlp/generate", methods=["POST"])
@require_auth
def ai_generate_text():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt") or data.get("text", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required for AI text generation.", "code": "VALIDATION_ERROR"}), 400

    system_prompt = data.get("system_prompt")
    provider_name = data.get("provider")
    ai_provider = get_ai_provider(provider_name)
    max_tokens = int(data.get("max_tokens", 500))

    start = time.time()
    generated = ai_provider.generate_text(prompt, system_prompt=system_prompt, max_tokens=max_tokens)
    latency_ms = round((time.time() - start) * 1000, 2)

    return jsonify({
        "success": True,
        "prompt": prompt,
        "generated_text": generated,
        "provider": ai_provider.get_info().get("id"),
        "model": ai_provider.get_info().get("model"),
        "latency_ms": latency_ms
    })


@api_v1.route("/ai/triage", methods=["POST"])
@api_v1.route("/nlp/triage", methods=["POST"])
@require_auth
def ai_triage_text():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Text is required for AI triage.", "code": "VALIDATION_ERROR"}), 400

    categories = data.get("categories") or ["Support", "DevOps", "Billing", "Security", "Sales"]
    provider_name = data.get("provider")
    ai_provider = get_ai_provider(provider_name)

    classification = ai_provider.classify_text(text, categories)
    rca = ai_provider.summarize_incident(text)

    return jsonify({
        "success": True,
        "text": text,
        "classification": classification,
        "rca": rca,
        "provider": ai_provider.get_info().get("id")
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
        log_audit_event("quota.exceeded", "quota", "rules", {"plan": org.plan_tier.upper() if org else "FREE", "violation": violation})
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
@api_v1.route("/audit", methods=["GET"])
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

    mig_status = {"current_revision": None, "is_up_to_date": True}
    try:
        from migrations_manager import get_migration_status
        m_info = get_migration_status()
        mig_status = {
            "current_revision": m_info.get("current_revision"),
            "head_revision": m_info.get("head_revision"),
            "is_up_to_date": m_info.get("is_up_to_date", True)
        }
    except Exception:
        pass

    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "database": dialect,
        "database_migration": mig_status,
        "engine_online": engine.is_running if engine else False,
        "version": "2.4.0-enterprise",
        "cloud_ready": True
    }), 200


@api_v1.route("/system/migration-status", methods=["GET"])
def system_migration_status():
    """Returns database migration diagnostics and schema revision details."""
    try:
        from migrations_manager import get_migration_status
        status = get_migration_status()
        return jsonify(status), 200
    except Exception as e:
        return jsonify({"error": str(e), "code": "MIGRATION_ERROR"}), 500


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


# ==========================================
# Stripe Billing & Subscriptions (Phase 4)
# ==========================================

@api_v1.route("/billing/status", methods=["GET"])
@require_auth
def get_workspace_billing_status():
    """Returns safe billing and subscription status for the current workspace."""
    org = g.current_org
    status = get_billing_status(org)
    status["quotas"] = {
        "max_rules": QuotaService.get_max_rules(org),
        "current_rules": QuotaService.get_rules_count(org),
        "max_monthly_events": QuotaService.get_max_monthly_events(org),
        "current_monthly_events": QuotaService.get_monthly_events_count(org),
    }
    status["entitlements"] = get_org_entitlements(org)
    return jsonify(status), 200


@api_v1.route("/billing/plans", methods=["GET"])
def get_billing_plans():
    """Returns all available plan specifications and pricing tiers."""
    plans = list_plans()
    return jsonify({
        "success": True,
        "plans": plans,
        "is_stripe_configured": is_stripe_configured(),
        "count": len(plans)
    }), 200


@api_v1.route("/billing/checkout", methods=["POST"])
@require_role(["owner", "admin"])
@rate_limit(limit=10, window=60, message="Too many checkout session requests.")
def create_billing_checkout():
    """Creates a Stripe Checkout Session to upgrade or subscribe the workspace."""
    org = g.current_org
    user = g.current_user
    data = request.get_json(silent=True) or (request.form.to_dict() if request.form else {})

    target_tier = (data.get("plan_tier") or data.get("tier") or "").strip().lower()
    interval = (data.get("interval") or "month").strip().lower()
    success_url = data.get("success_url")
    cancel_url = data.get("cancel_url")

    try:
        session_info = create_checkout_session(
            org=org,
            user=user,
            plan_tier=target_tier,
            interval=interval,
            success_url=success_url,
            cancel_url=cancel_url
        )
        return jsonify({
            "success": True,
            "session_id": session_info["session_id"],
            "checkout_url": session_info["checkout_url"],
            "plan_tier": session_info["plan_tier"],
            "interval": session_info["interval"],
        }), 200
    except BillingError as be:
        return jsonify({"error": be.message, "code": be.code}), be.status_code
    except Exception as e:
        logger.error(f"Unexpected error creating checkout session: {e}")
        return jsonify({"error": "Unable to initiate checkout session.", "code": "CHECKOUT_FAILED"}), 500


@api_v1.route("/billing/portal", methods=["POST"])
@require_role(["owner", "admin"])
@rate_limit(limit=10, window=60, message="Too many billing portal requests.")
def create_billing_portal():
    """Creates a Stripe Customer Portal session for the current workspace."""
    org = g.current_org
    data = request.get_json(silent=True) or {}
    return_url = data.get("return_url")

    try:
        portal_info = create_customer_portal_session(org, return_url=return_url)
        return jsonify({
            "success": True,
            "portal_url": portal_info["portal_url"]
        }), 200
    except BillingError as be:
        return jsonify({"error": be.message, "code": be.code}), be.status_code
    except Exception as e:
        logger.error(f"Unexpected error creating customer portal: {e}")
        return jsonify({"error": "Unable to open billing portal.", "code": "PORTAL_FAILED"}), 500


@api_v1.route("/billing/cancel", methods=["POST"])
@require_role(["owner", "admin"])
def cancel_subscription():
    """Downgrades workspace to Free tier or requests cancellation."""
    org = g.current_org
    old_tier = org.plan_tier

    if org.plan_tier == PLAN_FREE:
        return jsonify({
            "success": True,
            "message": "Workspace is already on the Free tier.",
            "plan_tier": PLAN_FREE
        }), 200

    sync_organization_subscription(
        org=org,
        plan_tier=PLAN_FREE,
        status="canceled",
        cancel_at_period_end=False,
        canceled_at=datetime.datetime.utcnow()
    )

    log_audit_event("billing.subscription_cancelled", "organization", org.id, {
        "previous_tier": old_tier,
        "new_tier": PLAN_FREE
    })

    return jsonify({
        "success": True,
        "message": "Subscription cancelled. Workspace reverted to Free tier.",
        "plan_tier": PLAN_FREE,
        "organization": org.to_dict(),
        "entitlements": get_org_entitlements(org)
    }), 200


@api_v1.route("/billing/webhook", methods=["POST"])
@api_v1.route("/webhooks/stripe", methods=["POST"])
@rate_limit(limit=100, window=60, message="Too many webhook requests.")
def stripe_webhook():
    """Public webhook receiver for Stripe billing events.
    
    Verifies Stripe HMAC signature and processes events idempotently.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except Exception as sig_err:
        logger.warning(f"Rejected unauthorized Stripe webhook: {sig_err}")
        return jsonify({"error": "Invalid webhook signature or payload.", "code": "INVALID_SIGNATURE"}), 400

    try:
        result = process_webhook_event(event)
        return jsonify({
            "received": True,
            "status": result.get("status"),
            "event_id": result.get("event_id"),
            "action": result.get("action")
        }), 200
    except Exception as proc_err:
        logger.error(f"Error processing Stripe webhook: {proc_err}")
        return jsonify({"error": "Webhook processing failed.", "code": "PROCESSING_ERROR"}), 500
