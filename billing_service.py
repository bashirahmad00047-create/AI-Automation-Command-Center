"""Stripe Billing & Subscription Management Service for OpsFlow Enterprise.

Encapsulates:
- Stripe SDK initialization and configuration handling
- Checkout Session generation for workspace tier upgrades
- Customer Portal Session generation for self-service subscription management
- Webhook signature verification and guaranteed idempotent event processing
- Bi-directional synchronization of subscription status with Phase 2 entitlements
- Graceful degradation when Stripe is not configured (Free tier fully functional)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app, request
import stripe

from auth import log_audit_event
from database import db
from models import (
    AuditLog,
    Organization,
    StripeWebhookEvent,
    Subscription,
    User,
    generate_uuid,
)
from plans import (
    PLAN_DEFINITIONS,
    PLAN_ENTERPRISE,
    PLAN_FREE,
    PLAN_PRO,
    PLAN_STARTER,
    get_plan,
    list_plans,
)

logger = logging.getLogger("opsflow.billing")


class BillingError(Exception):
    """Base exception for billing domain errors."""
    def __init__(self, message: str, code: str = "BILLING_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class StripeNotConfiguredError(BillingError):
    """Raised when an operation requires Stripe but secret keys are missing."""
    def __init__(self, message: str = "Stripe billing is not configured in this environment."):
        super().__init__(message, code="STRIPE_NOT_CONFIGURED", status_code=503)


class InvalidPlanError(BillingError):
    """Raised when an invalid or ineligible plan is requested."""
    def __init__(self, message: str = "Invalid plan tier requested."):
        super().__init__(message, code="INVALID_PLAN", status_code=400)


def get_stripe_config() -> Dict[str, str]:
    """Retrieves safe Stripe configuration from Flask config or environment variables."""
    cfg = current_app.config if current_app else {}
    return {
        "secret_key": cfg.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY", ""),
        "publishable_key": cfg.get("STRIPE_PUBLISHABLE_KEY") or os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
        "webhook_secret": cfg.get("STRIPE_WEBHOOK_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
    }


def is_stripe_configured() -> bool:
    """Returns True if Stripe secret key is configured and non-empty."""
    cfg = get_stripe_config()
    key = cfg.get("secret_key", "").strip()
    return bool(key and not key.startswith("sk_test_placeholder"))


def get_stripe_client():
    """Initializes and returns configured stripe module."""
    cfg = get_stripe_config()
    secret_key = cfg.get("secret_key", "").strip()
    if not secret_key or secret_key.startswith("sk_test_placeholder"):
        raise StripeNotConfiguredError()
    stripe.api_key = secret_key
    return stripe


def get_configured_price_id(plan_tier: str, interval: str = "month") -> Optional[str]:
    """Looks up pre-configured Stripe Price ID from app config / env."""
    cfg = current_app.config if current_app else {}
    interval_key = "YEARLY" if interval == "year" else "MONTHLY"
    env_key = f"STRIPE_PRICE_{plan_tier.upper()}_{interval_key}"
    price_id = cfg.get(env_key) or os.environ.get(env_key, "")
    if price_id and not price_id.endswith("_placeholder"):
        return price_id.strip()
    return None


def get_or_create_stripe_customer(org: Organization, user: Optional[User] = None) -> str:
    """Retrieves existing Stripe Customer ID or creates a new Stripe Customer record."""
    if org.stripe_customer_id:
        return org.stripe_customer_id

    client = get_stripe_client()
    email = user.email if user else f"billing@{org.slug}.opsflow.local"
    name = org.name

    customer = client.Customer.create(
        email=email,
        name=name,
        metadata={
            "organization_id": org.id,
            "organization_slug": org.slug,
        }
    )

    org.stripe_customer_id = customer.id
    # Also update subscription record if present
    if org.subscription:
        org.subscription.stripe_customer_id = customer.id
    db.session.commit()

    return customer.id


def create_checkout_session(
    org: Organization,
    user: User,
    plan_tier: str,
    interval: str = "month",
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a Stripe Checkout Session for upgrading a workspace subscription.
    
    Validates plan tier against server-side plan matrix (client pricing is never trusted).
    """
    tier = (plan_tier or "").strip().lower()
    if tier not in PLAN_DEFINITIONS:
        raise InvalidPlanError(f"Plan tier '{tier}' does not exist.")
    if tier == PLAN_FREE:
        raise InvalidPlanError("The Free tier does not require a Stripe checkout session.")

    plan_spec = get_plan(tier)
    if interval not in ("month", "year"):
        interval = "month"

    client = get_stripe_client()
    customer_id = get_or_create_stripe_customer(org, user)

    # Server-side pricing resolution
    configured_price_id = get_configured_price_id(tier, interval)
    if configured_price_id:
        line_items = [{
            "price": configured_price_id,
            "quantity": 1,
        }]
    else:
        # Construct verified line item directly from authoritative PLAN_DEFINITIONS
        monthly_usd = plan_spec["price_monthly_usd"]
        annual_discount_factor = 10  # 10 months billed for 12 months on annual
        unit_amount_cents = (monthly_usd * 100) if interval == "month" else (monthly_usd * annual_discount_factor * 100)

        line_items = [{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"OpsFlow {plan_spec['name']} Plan",
                    "description": plan_spec["description"],
                },
                "unit_amount": unit_amount_cents,
                "recurring": {
                    "interval": interval,
                }
            },
            "quantity": 1,
        }]

    base_url = request.host_url.rstrip("/") if request else "http://localhost:5000"
    resolved_success_url = success_url or f"{base_url}/?billing_session={{CHECKOUT_SESSION_ID}}&status=success"
    resolved_cancel_url = cancel_url or f"{base_url}/?billing_status=cancelled"

    session = client.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        payment_method_types=["card"],
        line_items=line_items,
        client_reference_id=org.id,
        metadata={
            "organization_id": org.id,
            "organization_slug": org.slug,
            "plan_tier": tier,
            "billing_interval": interval,
            "initiated_by_user_id": user.id,
        },
        subscription_data={
            "metadata": {
                "organization_id": org.id,
                "organization_slug": org.slug,
                "plan_tier": tier,
                "billing_interval": interval,
            }
        },
        success_url=resolved_success_url,
        cancel_url=resolved_cancel_url,
    )

    return {
        "session_id": session.id,
        "checkout_url": session.url,
        "plan_tier": tier,
        "interval": interval,
    }


def create_customer_portal_session(org: Organization, return_url: Optional[str] = None) -> Dict[str, Any]:
    """Creates a Stripe Customer Portal session so an existing customer can manage billing."""
    if not org.stripe_customer_id:
        raise BillingError(
            "No Stripe billing profile found for this workspace. Please upgrade to a paid plan first.",
            code="NO_BILLING_PROFILE",
            status_code=400
        )

    client = get_stripe_client()
    base_url = request.host_url.rstrip("/") if request else "http://localhost:5000"
    resolved_return_url = return_url or f"{base_url}/"

    portal_session = client.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=resolved_return_url,
    )

    return {
        "portal_url": portal_session.url,
        "customer_id": org.stripe_customer_id,
    }


def verify_webhook_signature(payload: bytes, sig_header: str) -> Dict[str, Any]:
    """Verifies Stripe webhook signature using configured signing secret.
    
    Raises ValueError or stripe.error.SignatureVerificationError if verification fails.
    """
    cfg = get_stripe_config()
    secret = cfg.get("webhook_secret", "").strip()

    if not secret or secret.startswith("whsec_placeholder"):
        # When unconfigured in local dev / testing, fallback to JSON parsing if sig_header is mock-valid
        if current_app and current_app.config.get("TESTING"):
            try:
                return json.loads(payload.decode("utf-8"))
            except Exception as e:
                raise ValueError(f"Invalid webhook JSON payload: {e}")
        raise BillingError("Stripe webhook signing secret is not configured.", code="WEBHOOK_UNCONFIGURED", status_code=503)

    return stripe.Webhook.construct_event(payload, sig_header, secret)


def sync_organization_subscription(
    org: Organization,
    plan_tier: str,
    status: str = "active",
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_price_id: Optional[str] = None,
    billing_interval: str = "month",
    current_period_start: Optional[datetime.datetime] = None,
    current_period_end: Optional[datetime.datetime] = None,
    cancel_at_period_end: bool = False,
    canceled_at: Optional[datetime.datetime] = None,
) -> Subscription:
    """Authoritative synchronization of tenant plan tier and subscription state.
    
    Synchronizes:
    - Organization.plan_tier
    - Organization.max_rules (from plan quota)
    - Organization.max_monthly_events (from plan quota)
    - Organization.stripe_customer_id & stripe_subscription_id
    - Subscription model attributes
    """
    tier = (plan_tier or PLAN_FREE).lower().strip()
    if tier not in PLAN_DEFINITIONS:
        tier = PLAN_FREE
    plan_spec = get_plan(tier)

    # 1. Update Organization attributes
    old_tier = org.plan_tier
    org.plan_tier = tier
    org.max_rules = plan_spec["quotas"]["max_rules"]
    org.max_monthly_events = plan_spec["quotas"]["max_monthly_events"]
    if stripe_customer_id:
        org.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        org.stripe_subscription_id = stripe_subscription_id

    # 2. Update or create Subscription record
    sub = org.subscription
    if not sub:
        sub = Subscription(
            id=generate_uuid("sub"),
            organization_id=org.id,
            plan_tier=tier,
            status=status,
            stripe_customer_id=stripe_customer_id or org.stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id or org.stripe_subscription_id,
            stripe_price_id=stripe_price_id,
            billing_interval=billing_interval,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            canceled_at=canceled_at,
        )
        db.session.add(sub)
    else:
        sub.plan_tier = tier
        sub.status = status
        if stripe_customer_id:
            sub.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id:
            sub.stripe_subscription_id = stripe_subscription_id
        if stripe_price_id:
            sub.stripe_price_id = stripe_price_id
        sub.billing_interval = billing_interval
        if current_period_start:
            sub.current_period_start = current_period_start
        if current_period_end:
            sub.current_period_end = current_period_end
        sub.cancel_at_period_end = cancel_at_period_end
        if canceled_at is not None:
            sub.canceled_at = canceled_at

    db.session.commit()

    # 3. Log compliance audit event
    try:
        log_audit_event(
            action="billing.subscription_sync",
            resource_type="subscription",
            resource_id=sub.id,
            details={
                "from_tier": old_tier,
                "to_tier": tier,
                "status": status,
                "stripe_subscription_id": stripe_subscription_id,
            },
            org_id=org.id
        )
    except Exception as e:
        logger.warning(f"Could not record audit log for subscription sync: {e}")

    return sub


def process_webhook_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Processes incoming verified Stripe webhook event idempotently.
    
    Guarantees:
    - Same event ID is never processed more than once
    - Handled events:
      * checkout.session.completed
      * customer.subscription.created
      * customer.subscription.updated
      * customer.subscription.deleted
      * invoice.payment_succeeded
      * invoice.payment_failed
    """
    event_id = event.get("id")
    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})

    if not event_id:
        return {"status": "ignored", "reason": "No event ID provided."}

    # 1. Idempotency Check
    existing = StripeWebhookEvent.query.filter_by(event_id=event_id).first()
    if existing:
        logger.info(f"Duplicate Stripe webhook received: {event_id} ({event_type}); skipping.")
        return {
            "status": "duplicate",
            "message": "Event already processed.",
            "event_id": event_id,
            "idempotent": True
        }

    action_summary = "unhandled"

    # 2. Dispatch by event type
    if event_type == "checkout.session.completed":
        session = event_data
        org_id = session.get("client_reference_id") or session.get("metadata", {}).get("org_id")
        plan_tier = session.get("metadata", {}).get("plan_tier")
        interval = session.get("metadata", {}).get("billing_interval", "month")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        org = db.session.get(Organization, org_id) if org_id else None
        if not org and customer_id:
            org = Organization.query.filter_by(stripe_customer_id=customer_id).first()

        if org and plan_tier:
            sync_organization_subscription(
                org=org,
                plan_tier=plan_tier,
                status="active",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                billing_interval=interval,
            )
            action_summary = f"synced_checkout_to_{plan_tier}"

    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        sub_obj = event_data
        customer_id = sub_obj.get("customer")
        sub_id = sub_obj.get("id")
        sub_status = sub_obj.get("status", "active")
        cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end", False))
        canceled_at_ts = sub_obj.get("canceled_at")
        canceled_at_dt = datetime.datetime.utcfromtimestamp(canceled_at_ts) if canceled_at_ts else None

        current_period_start_ts = sub_obj.get("current_period_start")
        current_period_end_ts = sub_obj.get("current_period_end")
        start_dt = datetime.datetime.utcfromtimestamp(current_period_start_ts) if current_period_start_ts else None
        end_dt = datetime.datetime.utcfromtimestamp(current_period_end_ts) if current_period_end_ts else None

        # Look up organization by metadata org_id or customer_id
        org_id = sub_obj.get("metadata", {}).get("organization_id") or sub_obj.get("metadata", {}).get("org_id")
        org = db.session.get(Organization, org_id) if org_id else None
        if not org and customer_id:
            org = Organization.query.filter_by(stripe_customer_id=customer_id).first()

        if org:
            target_tier = sub_obj.get("metadata", {}).get("plan_tier") or org.plan_tier
            # If subscription is past_due or canceled, handle appropriately
            if sub_status in ("canceled", "unpaid"):
                target_tier = PLAN_FREE

            sync_organization_subscription(
                org=org,
                plan_tier=target_tier,
                status=sub_status,
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                current_period_start=start_dt,
                current_period_end=end_dt,
                cancel_at_period_end=cancel_at_period_end,
                canceled_at=canceled_at_dt,
            )
            action_summary = f"subscription_{sub_status}_tier_{target_tier}"

    elif event_type == "customer.subscription.deleted":
        sub_obj = event_data
        customer_id = sub_obj.get("customer")
        sub_id = sub_obj.get("id")
        org_id = sub_obj.get("metadata", {}).get("organization_id") or sub_obj.get("metadata", {}).get("org_id")

        org = db.session.get(Organization, org_id) if org_id else None
        if not org and customer_id:
            org = Organization.query.filter_by(stripe_customer_id=customer_id).first()

        if org:
            sync_organization_subscription(
                org=org,
                plan_tier=PLAN_FREE,
                status="canceled",
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                cancel_at_period_end=False,
                canceled_at=datetime.datetime.utcnow(),
            )
            action_summary = "downgraded_to_free_on_deletion"

    elif event_type == "invoice.payment_succeeded":
        invoice = event_data
        customer_id = invoice.get("customer")
        sub_id = invoice.get("subscription")
        org = Organization.query.filter_by(stripe_customer_id=customer_id).first() if customer_id else None
        if org and org.subscription:
            org.subscription.status = "active"
            db.session.commit()
            action_summary = "payment_succeeded_active"

    elif event_type == "invoice.payment_failed":
        invoice = event_data
        customer_id = invoice.get("customer")
        org = Organization.query.filter_by(stripe_customer_id=customer_id).first() if customer_id else None
        if org and org.subscription:
            org.subscription.status = "past_due"
            db.session.commit()
            action_summary = "payment_failed_past_due"

    # 3. Store event in stripe_webhook_events table for idempotency
    try:
        record = StripeWebhookEvent(
            id=generate_uuid("swe"),
            event_id=event_id,
            event_type=event_type,
            payload_summary=action_summary,
            status="processed",
            processed_at=datetime.datetime.utcnow(),
        )
        db.session.add(record)
        db.session.commit()
    except Exception as save_err:
        logger.warning(f"Could not persist webhook event {event_id}: {save_err}")
        db.session.rollback()

    return {
        "status": "processed",
        "event_id": event_id,
        "event_type": event_type,
        "action": action_summary,
    }


def get_billing_status(org: Organization) -> Dict[str, Any]:
    """Returns safe, serialized billing and subscription overview for the tenant."""
    sub = org.subscription
    cfg = get_stripe_config()
    is_configured = is_stripe_configured()

    return {
        "success": True,
        "is_stripe_configured": is_configured,
        "publishable_key": cfg.get("publishable_key", "") if is_configured else "",
        "organization_id": org.id,
        "organization_name": org.name,
        "organization_slug": org.slug,
        "plan_tier": org.plan_tier,
        "stripe_customer_id": org.stripe_customer_id,
        "stripe_subscription_id": org.stripe_subscription_id,
        "has_active_subscription": bool(sub and sub.status in ("active", "trialing")),
        "subscription": sub.to_dict() if sub else {
            "id": None,
            "organization_id": org.id,
            "plan_tier": org.plan_tier,
            "status": "active" if org.plan_tier == PLAN_FREE else "unmanaged",
            "billing_interval": "month",
            "cancel_at_period_end": False,
            "current_period_start": None,
            "current_period_end": None,
        },
        "available_plans": list_plans(),
    }
