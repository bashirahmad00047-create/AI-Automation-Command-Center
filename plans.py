"""SaaS Plan Definitions, Entitlements, and Quota Specifications for OpsFlow Enterprise."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PLAN_FREE = "free"
PLAN_STARTER = "starter"
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"

PLAN_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    PLAN_FREE: {
        "tier": PLAN_FREE,
        "name": "Free",
        "description": "Essential exploration and testing for individual developers.",
        "price_monthly_usd": 0,
        "quotas": {
            "max_rules": 3,
            "monthly_events": 1000,
            "max_monthly_events": 1000,
            "max_api_keys": 1,
            "max_webhooks": 1,
            "max_team_members": 1,
        },
        "allowed_ai_providers": ["local_deterministic"],
        "features": {
            "custom_webhooks": True,
            "dry_run_simulation": True,
            "basic_telemetry": True,
            "advanced_analytics": False,
            "audit_trail": False,
            "export_rules": False,
            "cloud_ai_models": False,
            "sla_priority": False,
        }
    },
    PLAN_STARTER: {
        "tier": PLAN_STARTER,
        "name": "Starter",
        "description": "Essential automation and lead routing for individuals and small teams.",
        "price_monthly_usd": 29,
        "quotas": {
            "max_rules": 10,
            "monthly_events": 5000,
            "max_monthly_events": 5000,
            "max_api_keys": 2,
            "max_webhooks": 2,
            "max_team_members": 2,
        },
        "allowed_ai_providers": ["local_deterministic"],
        "features": {
            "custom_webhooks": True,
            "dry_run_simulation": True,
            "basic_telemetry": True,
            "advanced_analytics": False,
            "audit_trail": False,
            "export_rules": False,
            "cloud_ai_models": False,
            "sla_priority": False,
        }
    },
    PLAN_PRO: {
        "tier": PLAN_PRO,
        "name": "Professional",
        "description": "High-throughput automation, Google Gemini AI integration, and advanced analytics for scaling organizations.",
        "price_monthly_usd": 99,
        "quotas": {
            "max_rules": 50,
            "monthly_events": 200000,
            "max_monthly_events": 200000,
            "max_api_keys": 10,
            "max_webhooks": 10,
            "max_team_members": 10,
        },
        "allowed_ai_providers": ["local_deterministic", "gemini", "google_gemini"],
        "features": {
            "custom_webhooks": True,
            "dry_run_simulation": True,
            "basic_telemetry": True,
            "advanced_analytics": True,
            "audit_trail": True,
            "export_rules": True,
            "cloud_ai_models": True,
            "sla_priority": False,
        }
    },
    PLAN_ENTERPRISE: {
        "tier": PLAN_ENTERPRISE,
        "name": "Enterprise",
        "description": "Unlimited automation capacity, OpenAI & Gemini multimodal intelligence, compliance forensics, and dedicated SLA.",
        "price_monthly_usd": 499,
        "quotas": {
            "max_rules": 250,
            "monthly_events": 1000000,
            "max_monthly_events": 1000000,
            "max_api_keys": 50,
            "max_webhooks": 50,
            "max_team_members": 100,
        },
        "allowed_ai_providers": ["local_deterministic", "gemini", "google_gemini", "openai"],
        "features": {
            "custom_webhooks": True,
            "dry_run_simulation": True,
            "basic_telemetry": True,
            "advanced_analytics": True,
            "audit_trail": True,
            "export_rules": True,
            "cloud_ai_models": True,
            "sla_priority": True,
        }
    }
}

# Aliases for flexible naming
PLANS = PLAN_DEFINITIONS
PLAN_MATRIX = PLAN_DEFINITIONS


def get_plan(plan_tier: Optional[str]) -> Dict[str, Any]:
    """Retrieves plan specification for a tier, defaulting to Free."""
    tier = (plan_tier or PLAN_FREE).lower().strip()
    return PLAN_DEFINITIONS.get(tier, PLAN_DEFINITIONS[PLAN_FREE])


def list_plans() -> List[Dict[str, Any]]:
    """Returns a list of all distinct plans for pricing and upgrade pages."""
    unique_tiers = [PLAN_FREE, PLAN_STARTER, PLAN_PRO, PLAN_ENTERPRISE]
    return [PLAN_DEFINITIONS[t] for t in unique_tiers if t in PLAN_DEFINITIONS]


def is_feature_allowed(plan_tier: str, feature_name: str) -> bool:
    """Checks if a feature is enabled in the given plan tier."""
    plan = get_plan(plan_tier)
    return bool(plan.get("features", {}).get(feature_name, False))


def is_provider_allowed(plan_tier: str, provider_name: str) -> bool:
    """Checks if an AI provider is allowed in the given plan tier."""
    plan = get_plan(plan_tier)
    return provider_name in plan.get("allowed_ai_providers", [])
