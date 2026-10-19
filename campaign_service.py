"""Campaign & Targeted Broadcast Service for OpsFlow Cloud.

Architecture:
- Multi-audience contact selection: customers, employees, departments, saved groups, manual contacts.
- Strict multi-tenant isolation (organization_id scoping).
- Personalization template engine with verified fields: {{name}}, {{phone}}, {{company}}, {{department}}, {{email}}.
- AI-assisted command composition (draft only; never auto-activates without human confirmation).
- Explicit review and approval workflow before campaign activation.
- Restart-safe, reliable queue dispatching with per-recipient status tracking and idempotency keys.
- Delivery tracking: queued -> sent -> delivered -> read -> failed.
- WhatsApp Business 24-hour service window vs template rule compliance checking.
- Consent & opt-out registry honoring "STOP" / "UNSUBSCRIBE" requests.
- Auditable campaign lifecycle: creation, approval, dispatch, cancellation, and recipient updates.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import current_app, has_app_context

from database import db
from models import (
    AuditLog,
    BroadcastCampaign,
    CampaignRecipient,
    ContactConsent,
    Lead,
    Membership,
    MessageTemplate,
    Organization,
    User,
    WhatsAppMessage,
    generate_uuid,
)
from whatsapp_service import WhatsAppService

logger = logging.getLogger("opsflow.campaigns")


def log_audit_event(
    action: str,
    target_type: str,
    target_id: str,
    details: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> None:
    """Safely records an audit log entry within the active application context."""
    if not has_app_context():
        return
    try:
        audit = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=target_type,
            resource_id=str(target_id),
            details_json=json.dumps(details or {}),
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning(f"Failed to record audit log for {action}: {e}")


class CampaignService:
    """Manages multi-audience outbound campaigns, scheduling, consent, and delivery tracking."""

    # Default rate-pacing delay in seconds between WhatsApp bulk messages
    DISPATCH_INTERVAL_SEC = 0.05
    COST_PER_WHATSAPP_MESSAGE_USD = 0.05

    # ==========================================
    # AUDIENCE RESOLUTION & RECIPIENT SELECTION
    # ==========================================

    @classmethod
    def resolve_audience(
        cls,
        organization_id: str,
        audience_type: str = "customers",
        audience_filter: Optional[Dict[str, Any] | str] = None,
        manual_contacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Resolves target contacts for an organization with tenant isolation and consent verification.

        Supported audience_type:
          - "customers": Leads/CRM contacts within the tenant
          - "employees": Workspace members/users within the tenant
          - "department": Contacts or employees filtered by department
          - "saved_group": Leads filtered by status/qualification tag
          - "manual": Explicitly provided list of recipient phone numbers/names

        Returns:
          {
            "eligible": [...],
            "opted_out": [...],
            "ineligible": [...],
            "total_evaluated": int,
            "eligible_count": int,
            "opted_out_count": int
          }
        """
        if isinstance(audience_filter, str):
            try:
                audience_filter = json.loads(audience_filter)
            except Exception:
                audience_filter = {"filter": audience_filter}
        elif not isinstance(audience_filter, dict):
            audience_filter = {}

        raw_candidates: List[Dict[str, Any]] = []

        # 1. Customers / CRM Leads
        if audience_type in ("customers", "leads"):
            query = Lead.query.filter_by(organization_id=organization_id)
            target_status = audience_filter.get("status")
            if target_status and target_status != "all":
                query = query.filter_by(status=target_status)
            leads = query.all()
            for ld in leads:
                raw_candidates.append({
                    "recipient_type": "customer",
                    "recipient_id": ld.id,
                    "name": ld.name or "Valued Customer",
                    "phone": ld.phone or "",
                    "email": ld.email or "",
                    "company": ld.company or "",
                    "department": ld.route_department or "General",
                })

        # 2. Employees / Workspace Members
        elif audience_type == "employees":
            memberships = Membership.query.filter_by(organization_id=organization_id).all()
            target_dept = audience_filter.get("department")
            target_role = audience_filter.get("role")
            for mem in memberships:
                usr = mem.user
                if not usr or not usr.is_active:
                    continue
                if target_role and target_role != "all" and mem.role != target_role:
                    continue
                dept = getattr(usr, "department", "General") or "General"
                if target_dept and target_dept != "all" and dept.lower() != str(target_dept).lower():
                    continue
                raw_candidates.append({
                    "recipient_type": "employee",
                    "recipient_id": usr.id,
                    "name": usr.full_name or "Employee",
                    "phone": getattr(usr, "phone", "") or "",
                    "email": usr.email or "",
                    "company": "OpsFlow Internal",
                    "department": dept,
                })

        # 3. Department Specific
        elif audience_type == "department":
            dept_name = str(audience_filter.get("department") or "Support")
            leads = Lead.query.filter(
                Lead.organization_id == organization_id,
                Lead.route_department.ilike(f"%{dept_name}%")
            ).all()
            for ld in leads:
                raw_candidates.append({
                    "recipient_type": "customer",
                    "recipient_id": ld.id,
                    "name": ld.name or "Valued Customer",
                    "phone": ld.phone or "",
                    "email": ld.email or "",
                    "company": ld.company or "",
                    "department": ld.route_department or dept_name,
                })

        # 4. Saved Group / Presets
        elif audience_type == "saved_group":
            group_name = str(audience_filter.get("group") or "qualified")
            if group_name == "qualified":
                leads = Lead.query.filter(
                    Lead.organization_id == organization_id,
                    Lead.status.in_(["qualified", "converted"])
                ).all()
            elif group_name == "vip":
                leads = Lead.query.filter(
                    Lead.organization_id == organization_id,
                    Lead.lead_score >= 80
                ).all()
            else:
                leads = Lead.query.filter_by(organization_id=organization_id).all()

            for ld in leads:
                raw_candidates.append({
                    "recipient_type": "customer",
                    "recipient_id": ld.id,
                    "name": ld.name or "Customer",
                    "phone": ld.phone or "",
                    "email": ld.email or "",
                    "company": ld.company or "",
                    "department": ld.route_department or "General",
                })

        # 5. Manual Recipient List
        elif audience_type == "manual":
            items = manual_contacts or audience_filter.get("contacts") or []
            for item in items:
                if isinstance(item, str):
                    raw_candidates.append({
                        "recipient_type": "contact",
                        "recipient_id": None,
                        "name": "Contact",
                        "phone": item.strip(),
                        "email": "",
                        "company": "",
                        "department": "General",
                    })
                elif isinstance(item, dict):
                    raw_candidates.append({
                        "recipient_type": "contact",
                        "recipient_id": item.get("id"),
                        "name": item.get("name") or "Contact",
                        "phone": item.get("phone") or "",
                        "email": item.get("email") or "",
                        "company": item.get("company") or "",
                        "department": item.get("department") or "General",
                    })

        # Consent verification & phone normalization
        # Fetch all opted-out phone numbers for this tenant
        opted_out_records = ContactConsent.query.filter_by(
            organization_id=organization_id,
            status="opted_out",
            channel="whatsapp"
        ).all()
        opted_out_phones: Set[str] = set()
        for r in opted_out_records:
            if r.phone:
                d = WhatsAppService.format_phone_number(r.phone)
                opted_out_phones.add(d)
                opted_out_phones.add(f"+{d}")

        eligible: List[Dict[str, Any]] = []
        opted_out: List[Dict[str, Any]] = []
        ineligible: List[Dict[str, Any]] = []
        seen_phones: Set[str] = set()

        for cand in raw_candidates:
            clean_digits = WhatsAppService.format_phone_number(cand.get("phone", ""))
            if not clean_digits or len(clean_digits) < 7:
                cand["ineligible_reason"] = "Invalid or missing phone number"
                ineligible.append(cand)
                continue

            e164_phone = f"+{clean_digits}"
            if clean_digits in seen_phones or e164_phone in seen_phones:
                # Deduplicate repeated phone numbers within the same candidate list
                continue
            seen_phones.add(clean_digits)
            seen_phones.add(e164_phone)
            cand["phone"] = e164_phone

            if clean_digits in opted_out_phones or e164_phone in opted_out_phones:
                cand["ineligible_reason"] = "Recipient opted out (STOP requested)"
                opted_out.append(cand)
                continue

            eligible.append(cand)

        return {
            "eligible": eligible,
            "opted_out": opted_out,
            "ineligible": ineligible,
            "total_evaluated": len(raw_candidates),
            "eligible_count": len(eligible),
            "opted_out_count": len(opted_out),
            "ineligible_count": len(ineligible),
        }

    # ==========================================
    # PERSONALIZATION & TEMPLATE RENDERING
    # ==========================================

    @classmethod
    def render_personalized_text(
        cls,
        template_text: str,
        contact: Dict[str, Any]
    ) -> str:
        """Substitutes {{name}}, {{first_name}}, {{phone}}, {{company}}, {{department}}, {{email}} placeholders."""
        if not template_text:
            return ""

        full_name = str(contact.get("name") or "Valued Customer").strip()
        first_name = full_name.split()[0] if full_name else "Customer"
        phone = str(contact.get("phone") or "")
        company = str(contact.get("company") or "Our Partner").strip()
        dept = str(contact.get("department") or "General").strip()
        email = str(contact.get("email") or "").strip()

        replacements = {
            "name": full_name,
            "first_name": first_name,
            "phone": phone,
            "company": company,
            "department": dept,
            "email": email,
        }

        rendered = template_text
        for key, val in replacements.items():
            # Replace {{key}} and {key} case-insensitively
            rendered = re.sub(rf"\{{\{{\s*{key}\s*\}}\}}", val, rendered, flags=re.IGNORECASE)
            rendered = re.sub(rf"\{{\s*{key}\s*\}}", val, rendered, flags=re.IGNORECASE)

        return rendered

    # ==========================================
    # PREVIEW & COMPLIANCE CHECKING
    # ==========================================

    @classmethod
    def preview_campaign(
        cls,
        organization_id: str,
        audience_type: str,
        audience_filter: Optional[Dict[str, Any] | str],
        raw_template: str,
        template_name: Optional[str] = None,
        manual_contacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Calculates exact audience count, sample rendered message, 24h window compliance, and estimated cost."""
        audience_data = cls.resolve_audience(
            organization_id=organization_id,
            audience_type=audience_type,
            audience_filter=audience_filter,
            manual_contacts=manual_contacts,
        )

        eligible = audience_data["eligible"]
        samples: List[Dict[str, Any]] = []

        # Check 24-hour WhatsApp messaging window rule for non-template broadcasts
        cutoff_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        outside_24h_count = 0

        # Query recent inbound messages to detect contacts inside the 24h care window
        recent_inbounds = WhatsAppMessage.query.filter(
            WhatsAppMessage.organization_id == organization_id,
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.created_at >= cutoff_24h
        ).all()
        inbound_phones = {
            WhatsAppService.format_phone_number(m.sender) for m in recent_inbounds if m.sender
        }

        for idx, contact in enumerate(eligible):
            phone = contact["phone"]
            is_inside_window = phone in inbound_phones
            if not is_inside_window and not template_name:
                outside_24h_count += 1

            if idx < 3:
                rendered_msg = cls.render_personalized_text(raw_template, contact)
                samples.append({
                    "name": contact["name"],
                    "phone": contact["phone"],
                    "rendered_message": rendered_msg,
                    "inside_24h_window": is_inside_window,
                })

        estimated_cost = round(len(eligible) * cls.COST_PER_WHATSAPP_MESSAGE_USD, 2)
        warnings: List[str] = []

        if audience_data["opted_out_count"] > 0:
            warnings.append(
                f"{audience_data['opted_out_count']} contact(s) requested opt-out (STOP) and will be excluded automatically."
            )

        if outside_24h_count > 0 and not template_name:
            warnings.append(
                f"{outside_24h_count} recipient(s) are outside the WhatsApp 24-hour service window. "
                "Meta Cloud API requires an approved WhatsApp Business Template for these recipients."
            )

        primary_preview = samples[0]["rendered_message"] if samples else raw_template

        return {
            "total_recipients": len(eligible),
            "opted_out_count": audience_data["opted_out_count"],
            "ineligible_count": audience_data["ineligible_count"],
            "outside_24h_count": outside_24h_count,
            "estimated_cost_usd": estimated_cost,
            "primary_preview": primary_preview,
            "sample_previews": samples,
            "warnings": warnings,
            "compliance_status": "template_recommended" if (outside_24h_count > 0 and not template_name) else "compliant",
        }

    # ==========================================
    # COMMAND-ASSISTED AI COMPOSITION (DRAFT ONLY)
    # ==========================================

    @classmethod
    def generate_ai_draft(
        cls,
        organization_id: str,
        prompt: str,
        audience_type: str = "customers",
        tone: str = "professional",
    ) -> Dict[str, Any]:
        """Uses AI provider to draft an announcement. Never activates or sends a campaign directly."""
        prompt_clean = (prompt or "").strip()
        if not prompt_clean:
            return {"success": False, "error": "Prompt description cannot be empty"}

        ai_prompt = (
            f"You are the OpsFlow Broadcast Communication Assistant. "
            f"Draft a concise, high-impact announcement message for an audience of '{audience_type}'. "
            f"Tone: '{tone}'.\n"
            f"User Intent Description:\n\"{prompt_clean}\"\n\n"
            f"Instructions:\n"
            f"1. Include appropriate personalization tags like {{name}} or {{company}}.\n"
            f"2. Keep the message professional, clear, and action-oriented for WhatsApp delivery.\n"
            f"3. Return a clean, production-ready broadcast message without meta-commentary."
        )

        draft_body = ""
        suggested_title = prompt_clean[:50].title()

        # Try Gemini AI first if configured
        try:
            ai_reply = WhatsAppService.call_gemini_ai(
                organization_id=organization_id,
                system_prompt="You are an enterprise communications specialist for automated WhatsApp notifications.",
                user_message=ai_prompt
            )
            if ai_reply and len(ai_reply.strip()) > 10:
                draft_body = ai_reply.strip()
        except Exception as e:
            logger.info(f"Gemini AI draft generation fallback triggered: {e}")

        # Try Groq AI if Gemini was not available or empty
        if not draft_body:
            try:
                groq_reply = WhatsAppService.call_groq_ai(
                    system_prompt="You are an enterprise communications specialist for automated WhatsApp notifications.",
                    user_message=ai_prompt
                )
                if groq_reply and len(groq_reply.strip()) > 10:
                    draft_body = groq_reply.strip()
            except Exception as e:
                logger.info(f"Groq AI draft fallback: {e}")

        # Deterministic professional fallback if external LLM providers are unreachable
        if not draft_body:
            draft_body = (
                f"Hello {{{{name}}}},\n\n"
                f"We are writing to inform you regarding: {prompt_clean}.\n\n"
                f"Our team is actively monitoring operations to ensure optimal service. "
                f"If you have any questions, reply to this message directly.\n\n"
                f"Best regards,\nOperations Team"
            )

        return {
            "success": True,
            "suggested_title": suggested_title,
            "suggested_body": draft_body,
            "suggested_category": "utility",
            "caution_note": "AI-generated draft. Explicit human review and approval is required before activation.",
        }

    # ==========================================
    # CAMPAIGN LIFECYCLE (CREATE, APPROVE, CANCEL)
    # ==========================================

    @classmethod
    def create_campaign(
        cls,
        organization_id: str,
        title: str,
        raw_template: str,
        channel: str = "whatsapp",
        audience_type: str = "customers",
        audience_filter: Optional[Dict[str, Any] | str] = None,
        template_name: Optional[str] = None,
        scheduled_at: Optional[datetime.datetime] = None,
        created_by_user_id: Optional[str] = None,
        manual_contacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Creates a campaign in 'draft' or 'pending_approval' state with pre-populated recipient ledger."""
        org = db.session.get(Organization, organization_id)
        if not org:
            return {"success": False, "error": f"Organization '{organization_id}' not found", "code": "NOT_FOUND"}

        clean_title = (title or "").strip()
        clean_template = (raw_template or "").strip()
        if not clean_title or not clean_template:
            return {"success": False, "error": "Campaign title and message content are required"}

        # Resolve target recipients
        audience_data = cls.resolve_audience(
            organization_id=organization_id,
            audience_type=audience_type,
            audience_filter=audience_filter,
            manual_contacts=manual_contacts,
        )

        eligible = audience_data["eligible"]
        if not eligible and audience_data["opted_out_count"] == 0:
            return {
                "success": False,
                "error": "No valid contacts found for the selected audience criteria."
            }

        # Calculate preview for sample contact
        sample_preview = cls.render_personalized_text(clean_template, eligible[0]) if eligible else clean_template
        estimated_cost = round(len(eligible) * cls.COST_PER_WHATSAPP_MESSAGE_USD, 2)

        filter_json = json.dumps(audience_filter) if isinstance(audience_filter, dict) else (audience_filter or "{}")

        campaign = BroadcastCampaign(
            organization_id=organization_id,
            title=clean_title,
            channel=channel,
            audience_type=audience_type,
            audience_filter=filter_json,
            template_name=template_name,
            raw_template=clean_template,
            rendered_preview=sample_preview,
            status="pending_approval",
            scheduled_at=scheduled_at,
            created_by_user_id=created_by_user_id,
            total_recipients=len(eligible),
            opted_out_count=audience_data["opted_out_count"],
            estimated_cost_usd=estimated_cost,
        )
        db.session.add(campaign)
        db.session.flush()

        # Pre-seed recipient records with idempotency keys
        for contact in eligible:
            phone = contact["phone"]
            idempotency_key = f"{campaign.id}:{phone}"
            recip = CampaignRecipient(
                organization_id=organization_id,
                campaign_id=campaign.id,
                recipient_type=contact.get("recipient_type", "customer"),
                recipient_id=contact.get("recipient_id"),
                name=contact["name"],
                phone=phone,
                email=contact.get("email"),
                department=contact.get("department"),
                company=contact.get("company"),
                status="pending",
                idempotency_key=idempotency_key,
                personalized_body=cls.render_personalized_text(clean_template, contact),
            )
            db.session.add(recip)

        # Record opted out recipients in ledger as 'opted_out' for audit transparency
        for contact in audience_data["opted_out"]:
            phone = contact["phone"]
            idempotency_key = f"{campaign.id}:{phone}"
            recip = CampaignRecipient(
                organization_id=organization_id,
                campaign_id=campaign.id,
                recipient_type=contact.get("recipient_type", "customer"),
                recipient_id=contact.get("recipient_id"),
                name=contact["name"],
                phone=phone,
                email=contact.get("email"),
                department=contact.get("department"),
                company=contact.get("company"),
                status="opted_out",
                idempotency_key=idempotency_key,
                error_message="Skipped: Contact opted out of messaging (STOP).",
            )
            db.session.add(recip)

        db.session.commit()

        log_audit_event(
            action="campaign.created",
            target_type="broadcast_campaign",
            target_id=campaign.id,
            details={
                "title": clean_title,
                "audience_type": audience_type,
                "total_recipients": len(eligible),
                "opted_out_excluded": audience_data["opted_out_count"],
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            },
            user_id=created_by_user_id,
            organization_id=organization_id,
        )

        return {"success": True, "campaign": campaign.to_dict()}

    @classmethod
    def approve_and_activate(
        cls,
        campaign_id: str,
        organization_id: str,
        approved_by_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Explicit confirmation and activation of a campaign (Admin/Owner only).

        If scheduled_at is set in the future, transitions to 'scheduled'.
        If scheduled_at is null or due, transitions to 'queued' and starts dispatch worker.
        """
        campaign = BroadcastCampaign.query.filter_by(
            id=campaign_id,
            organization_id=organization_id
        ).first()

        if not campaign:
            return {"success": False, "error": f"Campaign '{campaign_id}' not found", "code": "NOT_FOUND"}

        if campaign.status in ("completed", "processing", "cancelled"):
            return {
                "success": False,
                "error": f"Campaign is already in '{campaign.status}' state and cannot be activated."
            }

        campaign.approved_by_user_id = approved_by_user_id
        campaign.approved_at = datetime.datetime.utcnow()

        now = datetime.datetime.utcnow()
        if campaign.scheduled_at and campaign.scheduled_at > now:
            campaign.status = "scheduled"
            db.session.commit()
            log_audit_event(
                action="campaign.scheduled",
                target_type="broadcast_campaign",
                target_id=campaign.id,
                details={"scheduled_at": campaign.scheduled_at.isoformat()},
                user_id=approved_by_user_id,
                organization_id=organization_id,
            )
            return {"success": True, "campaign": campaign.to_dict(), "action": "scheduled"}

        # Immediate dispatch
        campaign.status = "queued"
        db.session.commit()

        log_audit_event(
            action="campaign.approved",
            target_type="broadcast_campaign",
            target_id=campaign.id,
            details={"dispatched_immediately": True},
            user_id=approved_by_user_id,
            organization_id=organization_id,
        )

        # Trigger background execution worker
        app = current_app._get_current_object() if has_app_context() else None
        worker_thread = threading.Thread(
            target=cls._run_campaign_dispatch_worker,
            args=(campaign.id, app),
            daemon=True
        )
        worker_thread.start()

        return {"success": True, "campaign": campaign.to_dict(), "action": "queued"}

    @classmethod
    def cancel_campaign(
        cls,
        campaign_id: str,
        organization_id: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Cancels a scheduled or active campaign."""
        campaign = BroadcastCampaign.query.filter_by(
            id=campaign_id,
            organization_id=organization_id
        ).first()

        if not campaign:
            return {"success": False, "error": f"Campaign '{campaign_id}' not found", "code": "NOT_FOUND"}

        if campaign.status in ("completed", "cancelled"):
            return {"success": False, "error": f"Campaign is already {campaign.status}."}

        campaign.status = "cancelled"
        db.session.commit()

        log_audit_event(
            action="campaign.cancelled",
            target_type="broadcast_campaign",
            target_id=campaign.id,
            details={"previous_status": campaign.status},
            user_id=user_id,
            organization_id=organization_id,
        )

        return {"success": True, "campaign": campaign.to_dict()}

    # ==========================================
    # RESTART-SAFE QUEUE & DISPATCH WORKER
    # ==========================================

    @classmethod
    def _run_campaign_dispatch_worker(
        cls,
        campaign_id: str,
        app: Optional[Any] = None
    ) -> None:
        """Background worker iterating through pending recipients with idempotency checks."""
        context_manager = app.app_context() if app else None

        def _execute():
            try:
                campaign = db.session.get(BroadcastCampaign, campaign_id)
                if not campaign or campaign.status == "cancelled":
                    return

                campaign.status = "processing"
                db.session.commit()

                pending_recipients = CampaignRecipient.query.filter_by(
                    campaign_id=campaign_id,
                    status="pending"
                ).all()

                for recip in pending_recipients:
                    # Check if campaign was cancelled mid-flight
                    try:
                        campaign = db.session.get(BroadcastCampaign, campaign_id)
                    except Exception:
                        campaign = None
                    if not campaign or campaign.status == "cancelled":
                        break

                    # Idempotency safety: Check if this recipient was already processed
                    if recip.status in ("sent", "delivered", "read", "opted_out"):
                        continue

                    # Verify opt-out consent status immediately before dispatch
                    clean_d = WhatsAppService.format_phone_number(recip.phone)
                    opted_out = ContactConsent.query.filter(
                        ContactConsent.organization_id == recip.organization_id,
                        ContactConsent.channel == "whatsapp",
                        ContactConsent.status == "opted_out",
                        ContactConsent.phone.in_([recip.phone, clean_d, f"+{clean_d}"])
                    ).first()

                    if opted_out:
                        recip.status = "opted_out"
                        recip.error_message = "Recipient opted out prior to dispatch."
                        db.session.commit()
                        continue

                    try:
                        # Dispatch via WhatsApp provider
                        res = WhatsAppService.send_message(
                            organization_id=recip.organization_id,
                            to_phone=recip.phone,
                            message_text=recip.personalized_body,
                            template_name=campaign.template_name,
                        )

                        is_ok = bool(res.get("success") or res.get("status") in ("sent", "mock_sent"))
                        if is_ok:
                            recip.status = "sent"
                            recip.provider_message_id = (
                                res.get("whatsapp_message_id")
                                or res.get("message_id")
                                or res.get("idMessage")
                            )
                            recip.provider_name = res.get("provider", "whatsapp")
                            recip.sent_at = datetime.datetime.utcnow()
                            campaign.sent_count += 1
                        else:
                            recip.status = "failed"
                            recip.error_message = str(res.get("error") or "Provider dispatch failed")
                            campaign.failed_count += 1

                    except Exception as err:
                        recip.status = "failed"
                        recip.error_message = str(err)
                        campaign.failed_count += 1

                    db.session.commit()
                    time.sleep(cls.DISPATCH_INTERVAL_SEC)

                # Mark campaign completed if not cancelled
                try:
                    campaign = db.session.get(BroadcastCampaign, campaign_id)
                except Exception:
                    campaign = None
                if campaign and campaign.status != "cancelled":
                    campaign.status = "completed"
                    db.session.commit()

                    log_audit_event(
                        action="campaign.completed",
                        target_type="broadcast_campaign",
                        target_id=campaign.id,
                        details={
                            "sent_count": campaign.sent_count,
                            "failed_count": campaign.failed_count,
                        },
                        organization_id=campaign.organization_id,
                    )
            except Exception as e:
                logger.debug(f"Campaign worker thread completed/aborted: {e}")
                try:
                    db.session.rollback()
                except Exception:
                    pass

        if context_manager:
            with context_manager:
                _execute()
        else:
            _execute()

    # ==========================================
    # SCHEDULED CAMPAIGN EVALUATION
    # ==========================================

    @classmethod
    def evaluate_scheduled_campaigns(cls, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Evaluates due scheduled campaigns and launches them automatically."""
        now = datetime.datetime.utcnow()
        query = BroadcastCampaign.query.filter(
            BroadcastCampaign.status == "scheduled",
            BroadcastCampaign.scheduled_at <= now
        )
        if organization_id:
            query = query.filter_by(organization_id=organization_id)

        due_campaigns = query.all()
        launched = []

        app = current_app._get_current_object() if has_app_context() else None

        for camp in due_campaigns:
            camp.status = "queued"
            db.session.commit()

            worker_thread = threading.Thread(
                target=cls._run_campaign_dispatch_worker,
                args=(camp.id, app),
                daemon=True
            )
            worker_thread.start()
            launched.append(camp.to_dict())

        return launched

    # ==========================================
    # DELIVERY WEBHOOK RECEIPT TRACKING
    # ==========================================

    @classmethod
    def update_delivery_status(
        cls,
        provider_message_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> bool:
        """Updates per-recipient delivery status from incoming Meta or Green-API webhooks."""
        if not provider_message_id or not has_app_context():
            return False

        try:
            recip = CampaignRecipient.query.filter_by(
                provider_message_id=str(provider_message_id)
            ).first()

            if not recip:
                return False

            campaign = recip.campaign
            normalized_status = str(status).lower()

            if normalized_status in ("delivered", "delivery"):
                if recip.status != "delivered":
                    recip.status = "delivered"
                    recip.delivered_at = datetime.datetime.utcnow()
                    if campaign:
                        campaign.delivered_count += 1
            elif normalized_status in ("read", "viewed"):
                if recip.status != "read":
                    recip.status = "read"
                    recip.read_at = datetime.datetime.utcnow()
                    if campaign:
                        campaign.read_count += 1
            elif normalized_status in ("failed", "undelivered"):
                if recip.status != "failed":
                    recip.status = "failed"
                    recip.error_message = error_message or "Delivery failed"
                    if campaign:
                        campaign.failed_count += 1

            db.session.commit()
            return True

        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning(f"Failed to update campaign recipient delivery status: {e}")
            return False

    # ==========================================
    # CONSENT & OPT-OUT MANAGEMENT
    # ==========================================

    @classmethod
    def handle_opt_out(
        cls,
        organization_id: str,
        phone: str,
        channel: str = "whatsapp",
        reason: str = "Recipient requested STOP",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Registers a contact opt-out honoring user consent and STOP keywords."""
        clean_digits = WhatsAppService.format_phone_number(phone)
        if not clean_digits:
            return {"success": False, "error": "Invalid phone number"}

        e164_phone = f"+{clean_digits}"
        consent = ContactConsent.query.filter(
            ContactConsent.organization_id == organization_id,
            ContactConsent.channel == channel,
            ContactConsent.phone.in_([e164_phone, clean_digits])
        ).first()

        now = datetime.datetime.utcnow()
        if not consent:
            consent = ContactConsent(
                organization_id=organization_id,
                phone=e164_phone,
                channel=channel,
                status="opted_out",
                reason=reason,
                opted_out_at=now,
            )
            db.session.add(consent)
        else:
            consent.phone = e164_phone
            consent.status = "opted_out"
            consent.reason = reason
            consent.opted_out_at = now

        db.session.commit()

        log_audit_event(
            action="contact.opted_out",
            target_type="contact_consent",
            target_id=e164_phone,
            details={"phone": e164_phone, "reason": reason},
            user_id=user_id,
            organization_id=organization_id,
        )

        return {"success": True, "consent": consent.to_dict()}

    @classmethod
    def handle_opt_in(
        cls,
        organization_id: str,
        phone: str,
        channel: str = "whatsapp",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Restores contact consent when requested."""
        clean_digits = WhatsAppService.format_phone_number(phone)
        if not clean_digits:
            return {"success": False, "error": "Invalid phone number"}

        e164_phone = f"+{clean_digits}"
        consent = ContactConsent.query.filter(
            ContactConsent.organization_id == organization_id,
            ContactConsent.channel == channel,
            ContactConsent.phone.in_([e164_phone, clean_digits])
        ).first()

        if consent:
            consent.phone = e164_phone
            consent.status = "opted_in"
            consent.reason = "Contact opted back in"
            db.session.commit()
        else:
            consent = ContactConsent(
                organization_id=organization_id,
                phone=e164_phone,
                channel=channel,
                status="opted_in",
                reason="Contact opted back in",
                opted_in_at=datetime.datetime.utcnow(),
            )
            db.session.add(consent)
            db.session.commit()

        log_audit_event(
            action="contact.opted_in",
            target_type="contact_consent",
            target_id=e164_phone,
            details={"phone": e164_phone},
            user_id=user_id,
            organization_id=organization_id,
        )

        return {"success": True, "status": "opted_in"}

    @classmethod
    def list_consents(
        cls,
        organization_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns all consent and opt-out records for an organization."""
        query = ContactConsent.query.filter_by(organization_id=organization_id)
        if status:
            query = query.filter_by(status=status)
        return [c.to_dict() for c in query.order_by(ContactConsent.created_at.desc()).all()]

    # ==========================================
    # TEMPLATE REPOSITORY
    # ==========================================

    @classmethod
    def list_templates(cls, organization_id: str) -> List[Dict[str, Any]]:
        """Lists reusable message templates for the organization."""
        templates = MessageTemplate.query.filter_by(organization_id=organization_id).all()
        if not templates:
            # Seed default templates for turnkey usability
            cls._seed_default_templates(organization_id)
            templates = MessageTemplate.query.filter_by(organization_id=organization_id).all()
        return [t.to_dict() for t in templates]

    @classmethod
    def create_template(
        cls,
        organization_id: str,
        name: str,
        body: str,
        category: str = "utility",
        language: str = "en_US",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new reusable campaign message template."""
        clean_name = (name or "").strip()
        clean_body = (body or "").strip()
        if not clean_name or not clean_body:
            return {"success": False, "error": "Template name and body are required"}

        tmpl = MessageTemplate(
            organization_id=organization_id,
            name=clean_name,
            body=clean_body,
            category=category,
            language=language,
            created_by_user_id=user_id,
        )
        db.session.add(tmpl)
        db.session.commit()

        return {"success": True, "template": tmpl.to_dict()}

    @classmethod
    def _seed_default_templates(cls, organization_id: str) -> None:
        """Seeds common turnkey templates for a workspace."""
        defaults = [
            {
                "name": "incident_notification",
                "category": "utility",
                "body": "OpsFlow Alert: A {{severity}} event has been detected affecting {{company}}. Our engineering team is currently triaging the incident.",
            },
            {
                "name": "system_maintenance",
                "category": "utility",
                "body": "Hello {{name}},\n\nPlease be advised that scheduled infrastructure maintenance is planned for {{maintenance_time}}. Expect brief intermittent latency.",
            },
            {
                "name": "customer_checkin",
                "category": "support",
                "body": "Hi {{name}}! Following up on your recent request with our {{department}} team at {{company}}. Reply to this message if you need further assistance.",
            },
            {
                "name": "quarterly_product_update",
                "category": "marketing",
                "body": "Hello {{name}}! New automated orchestration features are now live for {{company}}. Check your command dashboard to explore.",
            },
        ]
        for d in defaults:
            t = MessageTemplate(
                organization_id=organization_id,
                name=d["name"],
                category=d["category"],
                body=d["body"],
                channel="whatsapp",
            )
            db.session.add(t)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # ==========================================
    # CAMPAIGN QUERYING & METRICS
    # ==========================================

    @classmethod
    def list_campaigns(
        cls,
        organization_id: str,
        limit: int = 50,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns campaigns for an organization."""
        query = BroadcastCampaign.query.filter_by(organization_id=organization_id)
        if status and status != "all":
            query = query.filter_by(status=status)
        campaigns = query.order_by(BroadcastCampaign.created_at.desc()).limit(limit).all()
        return [c.to_dict() for c in campaigns]

    @classmethod
    def get_campaign_detail(
        cls,
        campaign_id: str,
        organization_id: str
    ) -> Optional[Dict[str, Any]]:
        """Returns campaign details and recipient breakdown ledger."""
        campaign = BroadcastCampaign.query.filter_by(
            id=campaign_id,
            organization_id=organization_id
        ).first()

        if not campaign:
            return None

        data = campaign.to_dict()
        recipients = [r.to_dict() for r in campaign.recipients]
        data["recipients"] = recipients
        data["recipients_count"] = len(recipients)
        return data
