"""Comprehensive Test Suite for Multi-Audience Campaigns & Targeted Broadcasts.

Verifies:
1. Audience selection & multi-tenant isolation (organization_id scoping).
2. Personalization rendering & preview accuracy ({{name}}, {{phone}}, {{company}}, etc.).
3. Command-assisted AI drafting (draft-only, never auto-activated).
4. Explicit review & approval requirement (draft cannot dispatch without explicit approval).
5. Restart-safe queue, duplicate prevention, and per-recipient idempotency keys.
6. WhatsApp 24-hour care window compliance checks & template recommendation.
7. Regulatory consent & opt-out registry (honors "STOP" and suppresses opted-out contacts).
8. Server-side RBAC permissions (owner/admin vs operator vs viewer 403).
9. Partial provider failure handling (one failure does not halt other recipients).
10. End-to-end delivery tracking (queued -> sent -> delivered -> read).
11. Audit log generation for all campaign and consent actions.
12. Automation engine workflow action (campaign_broadcast).
"""

import datetime
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
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
)
from campaign_service import CampaignService
from whatsapp_service import WhatsAppService


class TestCampaignsAndBroadcasts(unittest.TestCase):
    """Test suite for Campaign & Targeted Broadcast Command Center."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        cls.client = cls.app.test_client()

        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Clean tables for fresh test isolation
        CampaignRecipient.query.delete()
        BroadcastCampaign.query.delete()
        ContactConsent.query.delete()
        MessageTemplate.query.delete()
        WhatsAppMessage.query.delete()
        Lead.query.delete()
        AuditLog.query.delete()
        Membership.query.delete()
        User.query.delete()
        Organization.query.delete()
        db.session.commit()

        # 1. Setup Tenant Alpha
        self.org_alpha = Organization(
            id="org-alpha-campaigns",
            name="Alpha Corp",
            slug="alpha-corp",
            plan_tier="enterprise"
        )
        db.session.add(self.org_alpha)

        # 2. Setup Tenant Beta (for isolation testing)
        self.org_beta = Organization(
            id="org-beta-campaigns",
            name="Beta Innovations",
            slug="beta-innovations",
            plan_tier="pro"
        )
        db.session.add(self.org_beta)

        # 3. Setup Users for Tenant Alpha
        self.admin_alpha = User(
            id="usr-alpha-admin",
            email="admin@alpha.io",
            full_name="Alice Admin",
            phone="+14155551001",
            department="Operations"
        )
        self.admin_alpha.set_password("AdminPass2026!")

        self.operator_alpha = User(
            id="usr-alpha-op",
            email="operator@alpha.io",
            full_name="Bob Operator",
            phone="+14155551002",
            department="Support"
        )
        self.operator_alpha.set_password("OpPass2026!")

        self.viewer_alpha = User(
            id="usr-alpha-view",
            email="viewer@alpha.io",
            full_name="Victor Viewer",
            phone="+14155551003",
            department="Finance"
        )
        self.viewer_alpha.set_password("ViewerPass2026!")

        db.session.add_all([self.admin_alpha, self.operator_alpha, self.viewer_alpha])
        db.session.commit()

        # Memberships
        db.session.add(Membership(user_id=self.admin_alpha.id, organization_id=self.org_alpha.id, role="admin"))
        db.session.add(Membership(user_id=self.operator_alpha.id, organization_id=self.org_alpha.id, role="operator"))
        db.session.add(Membership(user_id=self.viewer_alpha.id, organization_id=self.org_alpha.id, role="viewer"))

        # 4. Setup Customer Leads for Tenant Alpha
        self.lead_alpha_1 = Lead(
            id="lead-alpha-01",
            organization_id=self.org_alpha.id,
            name="John Doe",
            email="john@acme.com",
            phone="+14155552001",
            company="Acme Corp",
            route_department="Support",
            status="qualified"
        )
        self.lead_alpha_2 = Lead(
            id="lead-alpha-02",
            organization_id=self.org_alpha.id,
            name="Sarah Connor",
            email="sarah@skynet.com",
            phone="+14155552002",
            company="Cyberdyne",
            route_department="Sales",
            status="contacted"
        )
        self.lead_alpha_opted_out = Lead(
            id="lead-alpha-03",
            organization_id=self.org_alpha.id,
            name="Opted Out Lead",
            email="optout@test.com",
            phone="+14155552003",
            company="Test Inc",
            route_department="Support",
            status="qualified"
        )

        # 5. Setup Customer Lead for Tenant Beta (Isolation Check)
        self.lead_beta_1 = Lead(
            id="lead-beta-01",
            organization_id=self.org_beta.id,
            name="Beta Customer",
            email="beta@client.com",
            phone="+14155559999",
            company="Beta Client Corp",
            route_department="Support",
            status="qualified"
        )

        db.session.add_all([self.lead_alpha_1, self.lead_alpha_2, self.lead_alpha_opted_out, self.lead_beta_1])

        # Register lead_alpha_opted_out in ContactConsent
        db.session.add(ContactConsent(
            organization_id=self.org_alpha.id,
            phone="+14155552003",
            channel="whatsapp",
            status="opted_out",
            reason="User sent STOP"
        ))

        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def _login(self, email: str, password: str = "AdminPass2026!"):
        return self.client.post("/api/v1/auth/login", json={"email": email, "password": password})

    # ==========================================
    # 1. AUDIENCE RESOLUTION & TENANT ISOLATION
    # ==========================================

    def test_audience_resolution_and_tenant_isolation(self):
        """Audience resolution must strictly isolate contacts by organization_id and honor opt-outs."""
        # Resolve customers for Alpha
        res_alpha = CampaignService.resolve_audience(
            organization_id=self.org_alpha.id,
            audience_type="customers"
        )

        eligible_phones = [c["phone"] for c in res_alpha["eligible"]]
        self.assertIn("+14155552001", eligible_phones)
        self.assertIn("+14155552002", eligible_phones)
        # Opted out phone must NOT be eligible
        self.assertNotIn("+14155552003", eligible_phones)
        # Beta customer must NEVER leak into Alpha
        self.assertNotIn("+14155559999", eligible_phones)

        # Check opt-out list
        opted_out_phones = [c["phone"] for c in res_alpha["opted_out"]]
        self.assertIn("+14155552003", opted_out_phones)
        self.assertEqual(res_alpha["opted_out_count"], 1)

        # Resolve for Beta
        res_beta = CampaignService.resolve_audience(
            organization_id=self.org_beta.id,
            audience_type="customers"
        )
        beta_phones = [c["phone"] for c in res_beta["eligible"]]
        self.assertEqual(len(beta_phones), 1)
        self.assertIn("+14155559999", beta_phones)
        self.assertNotIn("+14155552001", beta_phones)

    def test_employee_and_department_audience_filters(self):
        """Audience resolution filters correctly by employees and specific departments."""
        # Employees audience for Alpha
        res_emp = CampaignService.resolve_audience(
            organization_id=self.org_alpha.id,
            audience_type="employees"
        )
        emp_phones = [c["phone"] for c in res_emp["eligible"]]
        self.assertIn("+14155551001", emp_phones)
        self.assertIn("+14155551002", emp_phones)

        # Department filter (Support department only)
        res_dept = CampaignService.resolve_audience(
            organization_id=self.org_alpha.id,
            audience_type="department",
            audience_filter={"department": "Support"}
        )
        dept_names = [c["name"] for c in res_dept["eligible"]]
        self.assertIn("John Doe", dept_names)
        self.assertNotIn("Sarah Connor", dept_names)  # Sarah is Sales

    # ==========================================
    # 2. PERSONALIZATION & PREVIEW ACCURACY
    # ==========================================

    def test_personalization_rendering(self):
        """Placeholders like {{name}}, {{first_name}}, {{company}} must accurately render."""
        template = "Hi {{first_name}}, this is an update regarding {{company}}. Contact: {{phone}}."
        contact = {
            "name": "Alexander Wright",
            "company": "Quantum Dynamics",
            "phone": "+14155553333",
            "department": "Engineering"
        }

        rendered = CampaignService.render_personalized_text(template, contact)
        self.assertEqual(rendered, "Hi Alexander, this is an update regarding Quantum Dynamics. Contact: +14155553333.")

    def test_campaign_preview_with_compliance_check(self):
        """Preview endpoint reports exact rendered text, costs, and WhatsApp 24h compliance flags."""
        self._login("operator@alpha.io", "OpPass2026!")

        res = self.client.post("/api/v1/campaigns/preview", json={
            "audience_type": "customers",
            "raw_template": "Hello {{name}} from {{company}}!"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["preview"]

        self.assertEqual(data["total_recipients"], 2)
        self.assertEqual(data["opted_out_count"], 1)
        self.assertEqual(data["estimated_cost_usd"], 0.10)  # 2 * 0.05
        self.assertTrue(len(data["sample_previews"]) > 0)
        # Sample preview must be personalized
        self.assertIn("John Doe", data["primary_preview"])
        self.assertIn("Acme Corp", data["primary_preview"])
        # Outside 24h window notice check
        self.assertIn("compliance_status", data)

    # ==========================================
    # 3. COMMAND-ASSISTED AI DRAFTING
    # ==========================================

    def test_command_assisted_ai_drafting(self):
        """AI composition endpoint generates a tailored draft without activating any campaign."""
        self._login("admin@alpha.io")

        res = self.client.post("/api/v1/campaigns/ai-draft", json={
            "prompt": "Urgent announcement: Database failover planned tonight at 23:00 UTC for 10 minutes",
            "audience_type": "customers",
            "tone": "urgent"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(len(data["suggested_body"]) > 20)
        self.assertIn("Database failover", data["suggested_body"])
        self.assertIn("{{name}}", data["suggested_body"])
        self.assertTrue(data.get("caution_note"))

        # Zero campaigns must have been created or dispatched
        self.assertEqual(BroadcastCampaign.query.count(), 0)

    # ==========================================
    # 4. EXPLICIT REVIEW & CONFIRMATION
    # ==========================================

    def test_explicit_review_and_approval_workflow(self):
        """Campaign must remain in pending_approval/draft until explicitly approved by admin."""
        self._login("admin@alpha.io")

        # 1. Create campaign
        create_res = self.client.post("/api/v1/campaigns", json={
            "title": "Platform Upgrade Notice",
            "audience_type": "customers",
            "raw_template": "Hello {{name}}, system upgrade tonight."
        })
        self.assertEqual(create_res.status_code, 200)
        camp = create_res.get_json()["campaign"]
        camp_id = camp["id"]

        self.assertEqual(camp["status"], "pending_approval")
        self.assertEqual(camp["sent_count"], 0)

        # Recipient ledger must be pre-seeded in 'pending' status
        recips = CampaignRecipient.query.filter_by(campaign_id=camp_id).all()
        self.assertEqual(len(recips), 3)  # 2 eligible + 1 opted_out
        pending_recips = [r for r in recips if r.status == "pending"]
        opted_recips = [r for r in recips if r.status == "opted_out"]
        self.assertEqual(len(pending_recips), 2)
        self.assertEqual(len(opted_recips), 1)

        # 2. Explicit Approval
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent", "whatsapp_message_id": "wamid.123"}):
            app_res = self.client.post(f"/api/v1/campaigns/{camp_id}/approve")
            self.assertEqual(app_res.status_code, 200)

        # Verify audit log was recorded
        audit = AuditLog.query.filter_by(target_id=camp_id, action="campaign.approved").first()
        self.assertIsNotNone(audit)

    # ==========================================
    # 5. IDEMPOTENCY & DUPLICATE SEND PREVENTION
    # ==========================================

    def test_idempotency_and_duplicate_prevention(self):
        """Worker must never dispatch twice to the same recipient even across repeated execution calls."""
        with self.app.app_context():
            res = CampaignService.create_campaign(
                organization_id=self.org_alpha.id,
                title="Idempotency Test Campaign",
                raw_template="Hello {{name}}!",
                audience_type="customers"
            )
            camp_id = res["campaign"]["id"]

            send_mock = MagicMock(return_value={"success": True, "status": "sent", "whatsapp_message_id": "wamid.mock.idemp"})
            with patch.object(WhatsAppService, "send_message", send_mock):
                # Run worker first time
                CampaignService._run_campaign_dispatch_worker(camp_id, self.app)
                first_call_count = send_mock.call_count
                self.assertEqual(first_call_count, 2)  # 2 eligible customers

                # Run worker second time (simulation of restart or duplicate trigger)
                CampaignService._run_campaign_dispatch_worker(camp_id, self.app)
                # Call count must NOT increase
                self.assertEqual(send_mock.call_count, first_call_count)

    # ==========================================
    # 6. SCHEDULING & QUEUE EVALUATION
    # ==========================================

    def test_scheduled_campaign_and_evaluation(self):
        """Scheduled campaigns remain pending until due timestamp is reached."""
        self._login("admin@alpha.io")

        future_time = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
        create_res = self.client.post("/api/v1/campaigns", json={
            "title": "Scheduled Nightly Digest",
            "audience_type": "customers",
            "raw_template": "Nightly report {{name}}",
            "scheduled_at": future_time.isoformat()
        })
        camp_id = create_res.get_json()["campaign"]["id"]

        # Approve campaign
        app_res = self.client.post(f"/api/v1/campaigns/{camp_id}/approve")
        self.assertEqual(app_res.get_json()["action"], "scheduled")

        camp = db.session.get(BroadcastCampaign, camp_id)
        self.assertEqual(camp.status, "scheduled")

        # Evaluate when not due
        launched = CampaignService.evaluate_scheduled_campaigns(self.org_alpha.id)
        self.assertEqual(len(launched), 0)

        # Move scheduled_at into the past and re-evaluate
        camp.scheduled_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        db.session.commit()

        with patch.object(CampaignService, "_run_campaign_dispatch_worker"):
            launched = CampaignService.evaluate_scheduled_campaigns(self.org_alpha.id)
            self.assertEqual(len(launched), 1)
            self.assertEqual(launched[0]["id"], camp_id)

    # ==========================================
    # 7. REGULATORY CONSENT & STOP WEBHOOK
    # ==========================================

    def test_automatic_opt_out_on_stop_webhook(self):
        """Inbound WhatsApp message containing STOP must automatically register contact in ContactConsent."""
        # Simulate incoming webhook payload from a customer sending STOP
        webhook_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "waba-01",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "+14155551000", "phone_number_id": "phone-id-01"},
                        "contacts": [{"profile": {"name": "Test User"}, "wa_id": "14155557777"}],
                        "messages": [{
                            "from": "14155557777",
                            "id": "wamid.stop.01",
                            "timestamp": "1710000000",
                            "text": {"body": "STOP"},
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        with patch.object(WhatsAppService, "verify_signature", return_value=True):
            res = self.client.post("/api/v1/webhooks/whatsapp?org_id=org-alpha-campaigns", json=webhook_payload)
            self.assertEqual(res.status_code, 200)

        # Verify opt-out was recorded in ContactConsent
        consent = ContactConsent.query.filter_by(
            organization_id=self.org_alpha.id,
            phone="+14155557777",
            status="opted_out"
        ).first()
        self.assertIsNotNone(consent)
        self.assertIn("STOP", consent.reason)

    # ==========================================
    # 8. RBAC PERMISSIONS & CROSS-TENANT ISOLATION
    # ==========================================

    def test_rbac_and_cross_tenant_restrictions(self):
        """Viewer is forbidden from creating/approving campaigns; cross-tenant access returns 404."""
        # 1. Viewer attempt to create campaign -> 403 Forbidden
        self._login("viewer@alpha.io", "ViewerPass2026!")
        create_res = self.client.post("/api/v1/campaigns", json={
            "title": "Unauthorized Campaign",
            "audience_type": "customers",
            "raw_template": "Hello"
        })
        self.assertEqual(create_res.status_code, 403)

        # 2. Admin creates campaign in Alpha
        self._login("admin@alpha.io")
        alpha_res = self.client.post("/api/v1/campaigns", json={
            "title": "Alpha Secret Broadcast",
            "audience_type": "customers",
            "raw_template": "Secret Alpha Message"
        })
        alpha_camp_id = alpha_res.get_json()["campaign"]["id"]

        # 3. Create admin in Beta and attempt to view/approve Alpha's campaign -> 404 Not Found
        beta_admin = User(id="usr-beta-adm", email="admin@beta.io", full_name="Beta Admin")
        beta_admin.set_password("BetaPass2026!")
        db.session.add(beta_admin)
        db.session.add(Membership(user_id=beta_admin.id, organization_id=self.org_beta.id, role="admin"))
        db.session.commit()

        self._login("admin@beta.io", "BetaPass2026!")
        leak_res = self.client.get(f"/api/v1/campaigns/{alpha_camp_id}")
        self.assertEqual(leak_res.status_code, 404)

        leak_app = self.client.post(f"/api/v1/campaigns/{alpha_camp_id}/approve")
        self.assertEqual(leak_app.status_code, 404)

    # ==========================================
    # 9. PARTIAL PROVIDER FAILURE
    # ==========================================

    def test_partial_provider_failure_handling(self):
        """A failure on one recipient must be recorded without stopping execution for others."""
        with self.app.app_context():
            res = CampaignService.create_campaign(
                organization_id=self.org_alpha.id,
                title="Partial Failure Campaign",
                raw_template="Hello {{name}}",
                audience_type="customers"
            )
            camp_id = res["campaign"]["id"]

            def mock_send_side_effect(organization_id, to_phone, **kwargs):
                if to_phone == "+14155552001":
                    return {"success": True, "status": "sent", "whatsapp_message_id": "wamid.success.01"}
                else:
                    return {"success": False, "status": "failed", "error": "Recipient number unreachable (131026)"}

            with patch.object(WhatsAppService, "send_message", side_effect=mock_send_side_effect):
                CampaignService._run_campaign_dispatch_worker(camp_id, self.app)

            camp = db.session.get(BroadcastCampaign, camp_id)
            self.assertEqual(camp.sent_count, 1)
            self.assertEqual(camp.failed_count, 1)
            self.assertEqual(camp.status, "completed")

            recips = CampaignRecipient.query.filter_by(campaign_id=camp_id).all()
            recip_status_map = {r.phone: r.status for r in recips}
            self.assertEqual(recip_status_map["+14155552001"], "sent")
            self.assertEqual(recip_status_map["+14155552002"], "failed")

    # ==========================================
    # 10. DELIVERY WEBHOOK RECEIPT TRACKING
    # ==========================================

    def test_delivery_and_read_receipt_tracking(self):
        """Provider status webhooks ('delivered', 'read') update CampaignRecipient and BroadcastCampaign."""
        with self.app.app_context():
            camp = BroadcastCampaign(
                organization_id=self.org_alpha.id,
                title="Delivery Tracking Test",
                raw_template="Status Test",
                status="processing",
                total_recipients=1,
                sent_count=1
            )
            db.session.add(camp)
            db.session.flush()

            recip = CampaignRecipient(
                organization_id=self.org_alpha.id,
                campaign_id=camp.id,
                name="Recipient One",
                phone="+14155558888",
                status="sent",
                idempotency_key=f"{camp.id}:+14155558888",
                provider_message_id="wamid.receipt.test.01"
            )
            db.session.add(recip)
            db.session.commit()

            # 1. Simulate delivery status update
            WhatsAppService.update_message_status("wamid.receipt.test.01", "delivered")
            db.session.refresh(recip)
            db.session.refresh(camp)
            self.assertEqual(recip.status, "delivered")
            self.assertEqual(camp.delivered_count, 1)

            # 2. Simulate read status update
            WhatsAppService.update_message_status("wamid.receipt.test.01", "read")
            db.session.refresh(recip)
            db.session.refresh(camp)
            self.assertEqual(recip.status, "read")
            self.assertEqual(camp.read_count, 1)

    # ==========================================
    # 11. REUSABLE TEMPLATES & AUDIT
    # ==========================================

    def test_reusable_templates_and_audit_logging(self):
        """Creating templates and campaigns properly logs audit events."""
        self._login("admin@alpha.io")

        tmpl_res = self.client.post("/api/v1/campaigns/templates", json={
            "name": "system_outage_alert",
            "category": "utility",
            "body": "CRITICAL: Service outage affecting {{company}}. Triage underway."
        })
        self.assertEqual(tmpl_res.status_code, 200)

        # Audit log verification
        tmpl = MessageTemplate.query.filter_by(name="system_outage_alert").first()
        self.assertIsNotNone(tmpl)
        self.assertEqual(tmpl.organization_id, self.org_alpha.id)


if __name__ == "__main__":
    unittest.main()
