"""Authentication, API Key Management, RBAC, and Security Middleware for OpsFlow SaaS."""

from __future__ import annotations

import functools
import hashlib
import json
import secrets
from typing import Callable, List, Optional, Tuple, Any
from flask import g, jsonify, request, session

from database import db
from models import ApiKey, AuditLog, Membership, Organization, User


def generate_secure_api_key(prefix: str = "sk_live") -> Tuple[str, str, str]:
    """Generates a secure API key.
    
    Returns:
        (full_secret_key, key_prefix, key_hash)
        full_secret_key is shown to the user ONLY ONCE.
    """
    random_bytes = secrets.token_hex(24)
    full_key = f"{prefix}_{random_bytes}"
    key_prefix = full_key[:14] + "..."
    key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
    return full_key, key_prefix, key_hash


def verify_api_key(token: str) -> Optional[Tuple[ApiKey, Organization, Optional[User]]]:
    """Verifies a plaintext API key and returns associated ApiKey, Organization, and User."""
    if not token or not token.startswith("sk_"):
        return None
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    api_key = ApiKey.query.filter_by(key_hash=key_hash, is_revoked=False).first()
    if not api_key:
        return None

    org = db.session.get(Organization, api_key.organization_id)
    if not org or not org.is_active:
        return None

    user = db.session.get(User, api_key.user_id) if api_key.user_id else None
    return api_key, org, user


def get_current_user() -> Optional[User]:
    """Retrieves current authenticated user from session or request context."""
    if hasattr(g, "current_user") and g.current_user is not None:
        return g.current_user
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user and user.is_active:
            g.current_user = user
            return user
    return None


def get_current_org() -> Optional[Organization]:
    """Retrieves current active organization for the request."""
    if hasattr(g, "current_org") and g.current_org is not None:
        return g.current_org

    # 1. If set by API Key auth
    if hasattr(g, "api_key") and g.api_key:
        org = db.session.get(Organization, g.api_key.organization_id)
        if org and org.is_active:
            g.current_org = org
            return org

    # 2. From session
    org_id = session.get("org_id")
    if org_id:
        org = db.session.get(Organization, org_id)
        if org and org.is_active:
            g.current_org = org
            return org

    # 3. Default fallback to first active org
    default_org = Organization.query.filter_by(is_active=True).first()
    if default_org:
        g.current_org = default_org
        return default_org

    return None


def get_user_role(user_id: str, org_id: str) -> Optional[str]:
    """Gets the user's role in the specified organization."""
    membership = Membership.query.filter_by(user_id=user_id, organization_id=org_id).first()
    return membership.role if membership else None


def require_auth(f: Callable) -> Callable:
    """Decorator requiring valid session login OR valid API key."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Check API Key in headers (X-API-Key or Authorization Bearer)
        auth_header = request.headers.get("X-API-Key") or request.headers.get("Authorization")
        token = None
        if auth_header:
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1].strip()
            else:
                token = auth_header.strip()

        if token and token.startswith("sk_"):
            res = verify_api_key(token)
            if not res:
                return jsonify({"error": "Invalid or revoked API key.", "code": "UNAUTHORIZED"}), 401
            api_key, org, user = res
            g.api_key = api_key
            g.current_org = org
            g.current_user = user
            g.is_api_key_auth = True
            return f(*args, **kwargs)

        # 2. Check Session Login
        user = get_current_user()
        if not user:
            # For API requests return JSON, otherwise 401
            return jsonify({"error": "Authentication required. Please log in or provide an API key.", "code": "UNAUTHORIZED"}), 401

        org = get_current_org()
        if not org:
            return jsonify({"error": "No active organization workspace found.", "code": "FORBIDDEN"}), 403

        g.current_user = user
        g.current_org = org
        g.is_api_key_auth = False
        return f(*args, **kwargs)

    return decorated_function


def require_role(allowed_roles: List[str]) -> Callable:
    """Decorator requiring the current user to have one of the allowed roles in the current organization."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        @require_auth
        def decorated_function(*args, **kwargs):
            # API Keys with admin/wildcard permission bypass role checks if configured
            if getattr(g, "is_api_key_auth", False):
                permissions = getattr(g.api_key, "permissions", "*")
                if "*" in permissions or "admin" in permissions:
                    return f(*args, **kwargs)

            user = g.current_user
            org = g.current_org
            if not user:
                return jsonify({"error": "User context required for this operation.", "code": "FORBIDDEN"}), 403

            if user.is_superuser:
                return f(*args, **kwargs)

            role = get_user_role(user.id, org.id)
            if not role or role not in allowed_roles:
                return jsonify({
                    "error": f"Permission denied. Required role in [{', '.join(allowed_roles)}], but your role is '{role or 'none'}'.",
                    "code": "FORBIDDEN"
                }), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def log_audit_event(
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    org_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> None:
    """Persists an administrative audit event for compliance and security forensics."""
    try:
        if not org_id and hasattr(g, "current_org") and g.current_org:
            org_id = g.current_org.id
        if not user_id and hasattr(g, "current_user") and g.current_user:
            user_id = g.current_user.id

        if not org_id:
            # Fallback to first available org
            first_org = Organization.query.first()
            org_id = first_org.id if first_org else "system"

        audit = AuditLog(
            organization_id=org_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=json.dumps(details or {}),
            ip_address=request.remote_addr if request else "127.0.0.1"
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        db.session.rollback()
