"""Plan Entitlement & Quota Enforcement Engine for OpsFlow SaaS."""

from __future__ import annotations

import datetime
import functools
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from flask import g, jsonify, request

from database import db
from models import (
    ApiKey,
    AutomationRule,
    Membership,
    Organization,
    OrganizationUsage,
    SystemEvent,
    WebhookEndpoint,
)
from plans import PLAN_DEFINITIONS, PLAN_FREE, PLAN_ENTERPRISE, get_plan


def get_current_month_start() -> datetime.datetime:
    """Returns midnight on the first day of the current UTC calendar month."""
    now = datetime.datetime.utcnow()
    return datetime.datetime(now.year, now.month, 1, 0, 0, 0)


def get_current_period(now: Optional[datetime.datetime] = None) -> str:
    """Returns YYYY-MM formatted calendar period (e.g. '2026-10')."""
    dt = now or datetime.datetime.utcnow()
    return f"{dt.year:04d}-{dt.month:02d}"


class QuotaService:
    """Central Entitlement and Quota Service for multi-tenant organizations."""

    @staticmethod
    def get_current_period(now: Optional[datetime.datetime] = None) -> str:
        """Returns active billing period string (e.g. '2026-10')."""
        return get_current_period(now)

    @staticmethod
    def get_plan(org: Optional[Organization]) -> Dict[str, Any]:
        """What plan does this organization have?"""
        tier = org.plan_tier if org and org.plan_tier else PLAN_FREE
        return get_plan(tier)

    @classmethod
    def is_feature_enabled(cls, org: Optional[Organization], feature_name: str) -> bool:
        """Is this feature enabled for this organization?"""
        if not org:
            return False
        plan = cls.get_plan(org)
        features = plan.get("features", {})
        return bool(features.get(feature_name, False))

    @classmethod
    def get_max_rules(cls, org: Optional[Organization]) -> int:
        """How many rules may this organization have?"""
        if not org:
            return 0
        plan = cls.get_plan(org)
        plan_max = plan["quotas"]["max_rules"]
        # Allow Enterprise or explicitly customized organizations to have custom limits
        if org.plan_tier == PLAN_ENTERPRISE and org.max_rules is not None and org.max_rules > 0:
            return org.max_rules
        if org.max_rules is not None and org.max_rules > 0 and org.max_rules != 100:
            return org.max_rules
        return plan_max

    @classmethod
    def get_max_monthly_events(cls, org: Optional[Organization]) -> int:
        """How many monthly events may this organization process?"""
        if not org:
            return 0
        plan = cls.get_plan(org)
        plan_max = plan["quotas"]["max_monthly_events"]
        # Allow Enterprise or explicitly customized organizations to have custom limits
        if org.plan_tier == PLAN_ENTERPRISE and org.max_monthly_events is not None and org.max_monthly_events > 0:
            return org.max_monthly_events
        if org.max_monthly_events is not None and org.max_monthly_events > 0 and org.max_monthly_events != 500000:
            return org.max_monthly_events
        return plan_max

    @staticmethod
    def get_monthly_events_count(org: Optional[Organization], period: Optional[str] = None) -> int:
        """How many monthly events has this organization consumed in the specified period?"""
        if not org:
            return 0
        target_period = period or get_current_period()
        usage = OrganizationUsage.query.filter_by(
            organization_id=org.id,
            period=target_period
        ).first()
        if usage:
            return usage.event_count
        month_start = get_current_month_start()
        return SystemEvent.query.filter(
            SystemEvent.organization_id == org.id,
            SystemEvent.created_at >= month_start
        ).count()

    @staticmethod
    def get_rules_count(org: Optional[Organization]) -> int:
        """How many active rules does this organization currently have?"""
        if not org:
            return 0
        return AutomationRule.query.filter_by(organization_id=org.id).count()

    @classmethod
    def is_event_allowed(cls, org: Optional[Organization], delta: int = 1) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Is another event allowed?"""
        if not org:
            return True, None
        current = cls.get_monthly_events_count(org)
        limit = cls.get_max_monthly_events(org)
        if current + delta > limit:
            return False, {
                "resource": "monthly_events",
                "current": current,
                "requested": delta,
                "limit": limit,
                "plan_tier": org.plan_tier,
                "upgrade_recommended": "pro" if org.plan_tier in (PLAN_FREE, "starter") else "enterprise"
            }
        return True, None

    @classmethod
    def is_rule_allowed(cls, org: Optional[Organization], delta: int = 1) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Is another rule/workflow allowed?"""
        if not org:
            return True, None
        current = cls.get_rules_count(org)
        limit = cls.get_max_rules(org)
        if current + delta > limit:
            return False, {
                "resource": "rules",
                "current": current,
                "requested": delta,
                "limit": limit,
                "plan_tier": org.plan_tier,
                "upgrade_recommended": "pro" if org.plan_tier in (PLAN_FREE, "starter") else "enterprise"
            }
        return True, None

    @classmethod
    def check_resource_quota(cls, org: Optional[Organization], resource: str, delta: int = 1) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Validates if incrementing a resource by delta violates the organization's quota."""
        if not org:
            return True, None

        if resource in ("rules", "max_rules", "rule", "workflow", "workflows"):
            return cls.is_rule_allowed(org, delta=delta)
        elif resource in ("monthly_events", "events", "max_monthly_events", "event"):
            return cls.is_event_allowed(org, delta=delta)

        entitlements = get_org_entitlements(org)
        quota_info = entitlements["quotas"].get(resource)
        if not quota_info:
            return True, None

        current = quota_info["current"]
        limit = quota_info["limit"]

        if current + delta > limit:
            return False, {
                "resource": resource,
                "current": current,
                "requested": delta,
                "limit": limit,
                "plan_tier": org.plan_tier,
                "upgrade_recommended": "pro" if org.plan_tier in (PLAN_FREE, "starter") else "enterprise"
            }

        return True, None

    @classmethod
    def check_ai_provider(cls, org: Optional[Organization], provider_name: str) -> Tuple[bool, Optional[str]]:
        """Validates if the AI provider is entitled under the organization's plan."""
        if not org:
            return True, None
        plan = cls.get_plan(org)
        allowed = plan.get("allowed_ai_providers", [])
        if provider_name not in allowed:
            required_tier = "enterprise" if provider_name == "openai" else "pro"
            return False, required_tier
        return True, None

    @classmethod
    def record_event(
        cls,
        org: Organization,
        event_name: str,
        payload: Any,
        source: str = "api",
        dry_run: bool = False,
        period: Optional[str] = None
    ) -> Optional[SystemEvent]:
        """Atomically increments organization usage and persists event stream record.
        
        Rejected and dry-run events are NEVER counted towards usage.
        Avoids race conditions using atomic database increments.
        """
        if dry_run or not org:
            return None

        target_period = period or get_current_period()

        # Atomic increment of OrganizationUsage: ensure row exists first
        usage = OrganizationUsage.query.filter_by(
            organization_id=org.id,
            period=target_period
        ).first()
        if not usage:
            try:
                usage = OrganizationUsage(
                    organization_id=org.id,
                    period=target_period,
                    event_count=0
                )
                db.session.add(usage)
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Atomic SQL update prevents concurrency race conditions
        db.session.query(OrganizationUsage).filter(
            OrganizationUsage.organization_id == org.id,
            OrganizationUsage.period == target_period
        ).update(
            {OrganizationUsage.event_count: OrganizationUsage.event_count + 1},
            synchronize_session=False
        )

        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        evt = SystemEvent(
            organization_id=org.id,
            event_name=event_name,
            payload_json=payload_str,
            source=source,
            processed=True,
            created_at=datetime.datetime.utcnow()
        )
        db.session.add(evt)
        db.session.commit()
        return evt

    @classmethod
    def reset_monthly_usage(cls, org: Organization, period: Optional[str] = None) -> int:
        """Resets monthly event usage for a specific period (ready for monthly billing cycle resets)."""
        if not org:
            return 0
        target_period = period or get_current_period()
        usage = OrganizationUsage.query.filter_by(
            organization_id=org.id,
            period=target_period
        ).first()
        if usage:
            usage.event_count = 0
            db.session.commit()
        return 0


# Unified alias for entitlement naming preferences
PlanEntitlements = QuotaService


def get_resource_usage(org_id: str) -> Dict[str, int]:
    """Calculates active resource counts for an organization."""
    rule_count = AutomationRule.query.filter_by(organization_id=org_id).count()
    period = get_current_period()
    usage = OrganizationUsage.query.filter_by(
        organization_id=org_id,
        period=period
    ).first()
    if usage:
        event_count = usage.event_count
    else:
        month_start = get_current_month_start()
        event_count = SystemEvent.query.filter(
            SystemEvent.organization_id == org_id,
            SystemEvent.created_at >= month_start
        ).count()
    key_count = ApiKey.query.filter_by(organization_id=org_id, is_revoked=False).count()
    webhook_count = WebhookEndpoint.query.filter_by(organization_id=org_id, is_active=True).count()
    member_count = Membership.query.filter_by(organization_id=org_id).count()

    return {
        "rules": rule_count,
        "monthly_events": event_count,
        "api_keys": key_count,
        "webhooks": webhook_count,
        "team_members": member_count,
    }


def get_org_entitlements(org: Organization) -> Dict[str, Any]:
    """Aggregates plan details, quotas, live usage, and feature entitlements."""
    plan_def = QuotaService.get_plan(org)
    usage = get_resource_usage(org.id)

    max_rules = QuotaService.get_max_rules(org)
    max_events = QuotaService.get_max_monthly_events(org)
    max_keys = plan_def["quotas"]["max_api_keys"]
    max_webhooks = plan_def["quotas"]["max_webhooks"]
    max_members = plan_def["quotas"]["max_team_members"]

    quotas = {
        "rules": {
            "current": usage["rules"],
            "limit": max_rules,
            "remaining": max(0, max_rules - usage["rules"]),
            "percent_used": round((usage["rules"] / max_rules * 100) if max_rules else 0, 1),
            "is_exceeded": usage["rules"] >= max_rules
        },
        "monthly_events": {
            "current": usage["monthly_events"],
            "limit": max_events,
            "remaining": max(0, max_events - usage["monthly_events"]),
            "percent_used": round((usage["monthly_events"] / max_events * 100) if max_events else 0, 2),
            "is_exceeded": usage["monthly_events"] >= max_events
        },
        "api_keys": {
            "current": usage["api_keys"],
            "limit": max_keys,
            "remaining": max(0, max_keys - usage["api_keys"]),
            "percent_used": round((usage["api_keys"] / max_keys * 100) if max_keys else 0, 1),
            "is_exceeded": usage["api_keys"] >= max_keys
        },
        "webhooks": {
            "current": usage["webhooks"],
            "limit": max_webhooks,
            "remaining": max(0, max_webhooks - usage["webhooks"]),
            "percent_used": round((usage["webhooks"] / max_webhooks * 100) if max_webhooks else 0, 1),
            "is_exceeded": usage["webhooks"] >= max_webhooks
        },
        "team_members": {
            "current": usage["team_members"],
            "limit": max_members,
            "remaining": max(0, max_members - usage["team_members"]),
            "percent_used": round((usage["team_members"] / max_members * 100) if max_members else 0, 1),
            "is_exceeded": usage["team_members"] >= max_members
        }
    }

    return {
        "organization_id": org.id,
        "organization_name": org.name,
        "plan_tier": org.plan_tier,
        "plan_name": plan_def["name"],
        "plan_description": plan_def["description"],
        "price_monthly_usd": plan_def.get("price_monthly_usd", 0),
        "quotas": quotas,
        "allowed_ai_providers": plan_def["allowed_ai_providers"],
        "features": plan_def["features"],
    }


def check_resource_quota(org: Organization, resource: str, delta: int = 1) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Compatibility wrapper delegating to QuotaService."""
    return QuotaService.check_resource_quota(org, resource, delta=delta)


def check_feature_entitlement(org: Organization, feature_name: str) -> Tuple[bool, Optional[str]]:
    """Checks whether an organization is entitled to a specific feature flag."""
    if not QuotaService.is_feature_enabled(org, feature_name):
        required_tier = "enterprise" if feature_name == "sla_priority" else "pro"
        return False, required_tier
    return True, None


def check_ai_provider_entitlement(org: Organization, provider_name: str) -> Tuple[bool, Optional[str]]:
    """Checks whether the requested AI provider is permitted for the organization's plan."""
    return QuotaService.check_ai_provider(org, provider_name)


def require_feature(feature_name: str):
    """Decorator to require that the current organization has access to a specific feature."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            org = getattr(g, "current_org", None)
            if not org:
                from auth import get_current_org
                org = get_current_org()

            if org:
                allowed, required_tier = check_feature_entitlement(org, feature_name)
                if not allowed:
                    return jsonify({
                        "error": "This feature is not available on your current plan.",
                        "code": "FEATURE_NOT_AVAILABLE",
                        "plan": org.plan_tier.upper(),
                        "feature": feature_name,
                        "required_plan": required_tier.upper()
                    }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator
