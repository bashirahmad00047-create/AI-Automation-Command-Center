"""Comprehensive Unit & Integration Test Suite for Customer Onboarding & Tenant Registration (Phase 4).

Verifies:
- Self-service organization registration with custom and auto-generated slugs
- Real-time slug availability verification
- Automated tenant provisioning (User, Membership, ApiKey, OrganizationUsage)
- Turnkey onboarding starter blueprints installation
- Team member invitations with plan seat quota enforcement (Free/Starter limits vs Pro)
- Team role updates, member removal, and last-owner protection
- Organization profile and workspace switching
"""

from __future__ import annotations

import json
import unittest

from sqlalchemy import text

from app import create_app
from database import db
from models import (
    ApiKey,
    AuditLog,
    AutomationRule,
    Membership,
    Organization,
    OrganizationUsage,
    User,
)
from limiter import limiter
from plans import PLAN_FREE, PLAN_STARTER, PLAN_PRO


class TestCustomerOnboarding(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        limiter.reset()

    def tearDown(self):
        db.session.remove()
        try:
            db.session.execute(text("PRAGMA foreign_keys = OFF;"))
            db.drop_all()
        except Exception:
            pass
        self.ctx.pop()

    def test_slug_availability_check(self):
        """Verifies real-time workspace URL slug availability check."""
        # Pre-seed existing org
        existing = Organization(
            id="org-taken-check",
            name="Existing Tenant",
            slug="taken-slug",
            is_active=True
        )
        db.session.add(existing)
        db.session.commit()

        # 1. Taken slug returns available=False
        res_taken = self.client.get("/api/v1/auth/check-slug?slug=taken-slug")
        self.assertEqual(res_taken.status_code, 200)
        self.assertFalse(res_taken.get_json()["available"])
        self.assertEqual(res_taken.get_json()["reason"], "Already in use")

        # 2. Available slug returns available=True
        res_avail = self.client.get("/api/v1/auth/check-slug?slug=novel-workspace")
        self.assertEqual(res_avail.status_code, 200)
        self.assertTrue(res_avail.get_json()["available"])
        self.assertEqual(res_avail.get_json()["slug"], "novel-workspace")

        # 3. Slug from workspace name converts cleanly
        res_name = self.client.get("/api/v1/auth/check-slug?name=BioHealth%20Systems%20Inc")
        self.assertEqual(res_name.status_code, 200)
        self.assertTrue(res_name.get_json()["available"])
        self.assertEqual(res_name.get_json()["slug"], "biohealth-systems-inc")

        # 4. Too short slug (<3 chars) returns validation notice
        res_short = self.client.get("/api/v1/auth/check-slug?slug=ab")
        self.assertEqual(res_short.status_code, 200)
        self.assertFalse(res_short.get_json()["available"])

        # 5. Missing parameter returns 400
        res_empty = self.client.get("/api/v1/auth/check-slug")
        self.assertEqual(res_empty.status_code, 400)

    def test_self_service_registration_free_plan(self):
        """Verifies new tenant signup creates user, workspace, usage record, API key, and signs in."""
        payload = {
            "email": "sarah.chen@biopulse.io",
            "password": "BioPulseSecure2026!",
            "full_name": "Dr. Sarah Chen",
            "org_name": "BioPulse Analytics",
            "workspace_slug": "biopulse-analytics",
            "plan_tier": "free",
            "install_starter_blueprints": True
        }
        res = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()

        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["email"], "sarah.chen@biopulse.io")
        self.assertEqual(data["organization"]["name"], "BioPulse Analytics")
        self.assertEqual(data["organization"]["slug"], "biopulse-analytics")
        self.assertEqual(data["organization"]["plan_tier"], "free")
        self.assertEqual(data["role"], "owner")
        self.assertTrue(data["initial_api_key"].startswith("sk_live_"))

        # Verify OrganizationUsage row initialized
        usage = OrganizationUsage.query.filter_by(organization_id=data["organization"]["id"]).first()
        self.assertIsNotNone(usage)
        self.assertEqual(usage.event_count, 0)

        # Verify starter blueprints installed
        rules = AutomationRule.query.filter_by(organization_id=data["organization"]["id"]).all()
        self.assertGreaterEqual(len(rules), 1)

        # Verify user can access authenticated endpoints immediately via active session
        res_me = self.client.get("/api/v1/auth/me")
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.get_json()["user"]["email"], "sarah.chen@biopulse.io")
        self.assertEqual(res_me.get_json()["current_organization"]["slug"], "biopulse-analytics")
        self.assertEqual(res_me.get_json()["role"], "owner")

    def test_registration_duplicate_slug_and_email_prevention(self):
        """Verifies duplicate email and duplicate slug return 409 CONFLICT."""
        payload1 = {
            "email": "lead@quantumops.com",
            "password": "QuantumPassword2026!",
            "full_name": "Quantum Admin",
            "org_name": "Quantum Ops",
            "slug": "quantum-ops"
        }
        res1 = self.client.post("/api/v1/auth/register", json=payload1)
        self.assertEqual(res1.status_code, 201)

        # 1. Duplicate email -> 409
        payload_dup_email = dict(payload1)
        payload_dup_email["slug"] = "quantum-ops-different"
        res_dup_email = self.client.post("/api/v1/auth/register", json=payload_dup_email)
        self.assertEqual(res_dup_email.status_code, 409)
        self.assertEqual(res_dup_email.get_json()["code"], "CONFLICT")

        # 2. Duplicate slug with different email -> 409 SLUG_ALREADY_EXISTS
        payload_dup_slug = {
            "email": "different@company.com",
            "password": "DifferentPassword2026!",
            "full_name": "Different User",
            "org_name": "Different Company",
            "slug": "quantum-ops"
        }
        res_dup_slug = self.client.post("/api/v1/auth/register", json=payload_dup_slug)
        self.assertEqual(res_dup_slug.status_code, 409)
        self.assertEqual(res_dup_slug.get_json()["code"], "SLUG_ALREADY_EXISTS")

    def test_registration_validation_errors(self):
        """Verifies invalid or missing fields return 400 VALIDATION_ERROR."""
        limiter.reset()
        # 1. Invalid email
        res1 = self.client.post("/api/v1/auth/register", json={"email": "invalid-email", "password": "Pass1234!", "full_name": "Name"})
        self.assertEqual(res1.status_code, 400)

        limiter.reset()
        # 2. Short password
        res2 = self.client.post("/api/v1/auth/register", json={"email": "valid@email.com", "password": "short", "full_name": "Name"})
        self.assertEqual(res2.status_code, 400)

        limiter.reset()
        # 3. Missing full name
        res3 = self.client.post("/api/v1/auth/register", json={"email": "valid@email.com", "password": "Pass1234!", "full_name": ""})
        self.assertEqual(res3.status_code, 400)

    def test_team_members_listing_and_quotas(self):
        """Verifies GET /api/v1/team/members lists organization members with seat quota summary."""
        # Register starter organization
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "founder@aeroflow.io",
            "password": "AeroFlowPass2026!",
            "full_name": "Marcus Vance",
            "org_name": "AeroFlow Dynamics",
            "slug": "aeroflow-dynamics",
            "plan_tier": "starter"
        })
        self.assertEqual(reg_res.status_code, 201)

        res_team = self.client.get("/api/v1/team/members")
        self.assertEqual(res_team.status_code, 200)
        team_data = res_team.get_json()

        self.assertEqual(team_data["count"], 1)
        self.assertEqual(team_data["members"][0]["email"], "founder@aeroflow.io")
        self.assertEqual(team_data["members"][0]["role"], "owner")
        # Starter plan allows 2 team members
        self.assertEqual(team_data["seats"]["current"], 1)
        self.assertEqual(team_data["seats"]["limit"], 2)
        self.assertEqual(team_data["seats"]["remaining"], 1)
        self.assertFalse(team_data["seats"]["is_exceeded"])

    def test_team_member_invitation_and_quota_enforcement(self):
        """Verifies member invitations respect plan seat quotas (Free=1, Starter=2, Pro=10)."""
        # 1. Register Free plan organization (limit: 1 team member)
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "solo@freelabs.io",
            "password": "SoloSecurePass2026!",
            "full_name": "Solo Developer",
            "org_name": "Free Labs",
            "slug": "free-labs",
            "plan_tier": "free"
        })
        self.assertEqual(reg_res.status_code, 201)

        # 2. Free plan already has 1 member (the owner) -> Inviting a 2nd member is rejected with 403 QUOTA_EXCEEDED!
        res_invite_blocked = self.client.post("/api/v1/team/invite", json={
            "email": "colleague@freelabs.io",
            "role": "operator",
            "full_name": "Colleague"
        })
        self.assertEqual(res_invite_blocked.status_code, 403)
        self.assertEqual(res_invite_blocked.get_json()["code"], "QUOTA_EXCEEDED")
        self.assertEqual(res_invite_blocked.get_json()["resource"], "team_members")

        # 3. Upgrade to Pro plan (unlocks 10 team seats)
        res_upgrade = self.client.post("/api/v1/plan/upgrade", json={"plan_tier": "pro"})
        self.assertEqual(res_upgrade.status_code, 200)

        # 4. Invitation now succeeds!
        res_invite_success = self.client.post("/api/v1/team/invite", json={
            "email": "colleague@freelabs.io",
            "role": "operator",
            "full_name": "Colleague"
        })
        self.assertEqual(res_invite_success.status_code, 201)
        inv_data = res_invite_success.get_json()
        self.assertTrue(inv_data["success"])
        self.assertEqual(inv_data["member"]["email"], "colleague@freelabs.io")
        self.assertEqual(inv_data["member"]["role"], "operator")

        # 5. Inviting the same member again returns 409 CONFLICT
        res_dup_invite = self.client.post("/api/v1/team/invite", json={
            "email": "colleague@freelabs.io",
            "role": "admin"
        })
        self.assertEqual(res_dup_invite.status_code, 409)

        # 6. Team list now has 2 members
        res_team_after = self.client.get("/api/v1/team/members")
        self.assertEqual(res_team_after.get_json()["count"], 2)
        self.assertEqual(res_team_after.get_json()["seats"]["current"], 2)
        self.assertEqual(res_team_after.get_json()["seats"]["limit"], 10)

    def test_team_member_role_update_and_removal(self):
        """Verifies role modification, member removal, and protection of the last workspace owner."""
        # Register Starter organization
        self.client.post("/api/v1/auth/register", json={
            "email": "lead@fintechops.io",
            "password": "FintechSecurePass2026!",
            "full_name": "Fintech Lead",
            "org_name": "Fintech Ops",
            "slug": "fintech-ops",
            "plan_tier": "starter"
        })

        # Invite operator
        invite_res = self.client.post("/api/v1/team/invite", json={
            "email": "analyst@fintechops.io",
            "role": "operator",
            "full_name": "Sec Analyst"
        })
        self.assertEqual(invite_res.status_code, 201)
        analyst_user_id = invite_res.get_json()["member"]["user_id"]

        # 1. Update analyst role to admin
        res_role = self.client.put(f"/api/v1/team/members/{analyst_user_id}", json={"role": "admin"})
        self.assertEqual(res_role.status_code, 200)
        self.assertEqual(res_role.get_json()["member"]["role"], "admin")

        # 2. Cannot remove the only owner of the workspace
        me_res = self.client.get("/api/v1/auth/me")
        owner_id = me_res.get_json()["user"]["id"]
        res_del_owner = self.client.delete(f"/api/v1/team/members/{owner_id}")
        self.assertEqual(res_del_owner.status_code, 403)
        self.assertEqual(res_del_owner.get_json()["code"], "FORBIDDEN")

        # 3. Remove analyst member succeeds
        res_del = self.client.delete(f"/api/v1/team/members/{analyst_user_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

        # Member count back to 1
        res_team_after = self.client.get("/api/v1/team/members")
        self.assertEqual(res_team_after.get_json()["count"], 1)

    def test_organization_current_profile_and_update(self):
        """Verifies GET and PUT /api/v1/organizations/current."""
        self.client.post("/api/v1/auth/register", json={
            "email": "cto@datacore.io",
            "password": "DataCorePass2026!",
            "full_name": "DataCore CTO",
            "org_name": "DataCore AI",
            "slug": "datacore-ai",
            "plan_tier": "starter"
        })

        # 1. GET current organization
        res = self.client.get("/api/v1/organizations/current")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["organization"]["name"], "DataCore AI")
        self.assertEqual(data["entitlements"]["plan_tier"], "starter")

        # 2. PUT update organization name
        res_put = self.client.put("/api/v1/organizations/current", json={"name": "DataCore Global Enterprise"})
        self.assertEqual(res_put.status_code, 200)
        self.assertEqual(res_put.get_json()["organization"]["name"], "DataCore Global Enterprise")

        # Verify updated name persisted
        res_verify = self.client.get("/api/v1/organizations/current")
        self.assertEqual(res_verify.get_json()["organization"]["name"], "DataCore Global Enterprise")

    def test_login_and_logout_flow(self):
        """Verifies session lifecycle: login, logout, session clearance, and re-authentication."""
        # 1. Register a new user
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "dev@cloudmatrix.io",
            "password": "CloudMatrixPassword2026!",
            "full_name": "Dev User",
            "org_name": "Cloud Matrix",
            "slug": "cloud-matrix"
        })
        self.assertEqual(reg_res.status_code, 201)

        # 2. Currently authenticated via session
        me_res1 = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_res1.status_code, 200)
        self.assertEqual(me_res1.get_json()["user"]["email"], "dev@cloudmatrix.io")

        # 3. Logout
        logout_res = self.client.post("/api/v1/auth/logout")
        self.assertEqual(logout_res.status_code, 200)
        self.assertTrue(logout_res.get_json()["success"])

        # 4. Now unauthenticated
        me_res2 = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_res2.status_code, 401)

        # 5. Invalid credentials return 401
        limiter.reset()
        bad_login = self.client.post("/api/v1/auth/login", json={
            "email": "dev@cloudmatrix.io",
            "password": "WrongPassword!"
        })
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(bad_login.get_json()["code"], "UNAUTHORIZED")

        # 6. Correct credentials re-establishes session
        limiter.reset()
        good_login = self.client.post("/api/v1/auth/login", json={
            "email": "dev@cloudmatrix.io",
            "password": "CloudMatrixPassword2026!"
        })
        self.assertEqual(good_login.status_code, 200)
        self.assertEqual(good_login.get_json()["user"]["email"], "dev@cloudmatrix.io")

        # 7. Session is active again
        me_res3 = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_res3.status_code, 200)

    def test_ui_template_contains_phase5_components(self):
        """Verifies index.html renders authentication modal, onboarding wizard, and seat counters."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # 1. Header session auth buttons
        self.assertIn('id="headerAuthControls"', html)
        self.assertIn('id="headerSignInBtn"', html)
        self.assertIn('id="headerRegisterBtn"', html)
        self.assertIn('id="headerSignOutBtn"', html)

        # 2. Authentication Modal & Tabs
        self.assertIn('id="authModal"', html)
        self.assertIn('id="authTabLogin"', html)
        self.assertIn('id="authTabRegister"', html)
        self.assertIn('id="loginForm"', html)
        self.assertIn('id="registerForm"', html)
        self.assertIn('id="regOrgSlug"', html)
        self.assertIn('id="slugFeedback"', html)

        # 3. Turnkey Customer Onboarding Wizard
        self.assertIn('id="onboardingWizardModal"', html)
        self.assertIn('id="wizardStep1"', html)
        self.assertIn('id="wizardStep2"', html)
        self.assertIn('id="wizardStep3"', html)
        self.assertIn('id="wizardStep4"', html)
        self.assertIn('id="wizardStep5"', html)
        self.assertIn('id="wizApiKeyInput"', html)
        self.assertIn('id="wizCopyKeyBtn"', html)

        # 4. Team seat quota displays
        self.assertIn('id="teamSeatCount"', html)
        self.assertIn('id="teamSeatLimit"', html)

    def test_onboarding_turnkey_blueprints_installed(self):
        """Verifies starter blueprints and audit records are auto-provisioned upon registration."""
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "founder@zenith.ai",
            "password": "ZenithPass2026!",
            "full_name": "Zenith Founder",
            "org_name": "Zenith AI Systems",
            "slug": "zenith-ai",
            "starter_blueprints": True
        })
        self.assertEqual(reg_res.status_code, 201)
        data = reg_res.get_json()
        org_id = data["organization"]["id"]

        # Verify 3 starter automation rules created
        rules = AutomationRule.query.filter_by(organization_id=org_id).all()
        rule_names = [r.name for r in rules]
        self.assertEqual(len(rules), 3)
        self.assertIn("Critical Incident Router", rule_names)
        self.assertIn("AI Lead Qualification", rule_names)
        self.assertIn("API Failure Alert", rule_names)

        # Verify audit log records
        audits = AuditLog.query.filter_by(organization_id=org_id).all()
        actions = [a.action for a in audits]
        self.assertIn("auth.register", actions)

    def test_unauthenticated_visitor_gets_unauthenticated_me_response(self):
        """Verifies unauthenticated visitors receive 401 on /api/v1/auth/me and no auto-login occurs."""
        # 1. Unauthenticated request to /api/v1/auth/me
        res_me = self.client.get("/api/v1/auth/me")
        self.assertEqual(res_me.status_code, 401)
        self.assertEqual(res_me.get_json()["code"], "UNAUTHORIZED")

        # 2. Unauthenticated request to / renders template containing login screen
        res_index = self.client.get("/")
        self.assertEqual(res_index.status_code, 200)
        html = res_index.data.decode("utf-8")
        self.assertIn('id="authModal"', html)
        self.assertIn('id="loginForm"', html)
        self.assertIn('id="registerForm"', html)

        # 3. /api/v1/auth/me is STILL 401 (proves visiting / does NOT auto-login as admin)
        res_me_again = self.client.get("/api/v1/auth/me")
        self.assertEqual(res_me_again.status_code, 401)

    def test_tenant_isolation_on_new_registration(self):
        """Verifies newly registered tenant is isolated and cannot access Acme demo workspace."""
        # Ensure Acme demo organization exists
        acme_org = Organization.query.get("org-enterprise-default")
        if not acme_org:
            acme_org = Organization(
                id="org-enterprise-default",
                name="Acme Global Enterprise",
                slug="acme-global",
                plan_tier="enterprise",
                is_active=True
            )
            db.session.add(acme_org)
            db.session.commit()

        # Register new customer
        reg_res = self.client.post("/api/v1/auth/register", json={
            "email": "owner@solarisenergy.io",
            "password": "SolarisPassword2026!",
            "full_name": "Elena Rostova",
            "org_name": "Solaris Energy",
            "slug": "solaris-energy",
            "plan_tier": "free"
        })
        self.assertEqual(reg_res.status_code, 201)
        user_id = reg_res.get_json()["user"]["id"]
        new_org_id = reg_res.get_json()["organization"]["id"]

        # User is active in their OWN organization
        me_res = self.client.get("/api/v1/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()["current_organization"]["id"], new_org_id)
        self.assertEqual(me_res.get_json()["current_organization"]["slug"], "solaris-energy")

        # User only belongs to Solaris Energy (not Acme)
        user_memberships = Membership.query.filter_by(user_id=user_id).all()
        self.assertEqual(len(user_memberships), 1)
        self.assertEqual(user_memberships[0].organization_id, new_org_id)

        # Attempting to switch to Acme demo organization is blocked
        switch_res = self.client.post("/api/v1/organizations/switch", json={
            "organization_id": "org-enterprise-default"
        })
        self.assertEqual(switch_res.status_code, 403)
        self.assertEqual(switch_res.get_json()["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
