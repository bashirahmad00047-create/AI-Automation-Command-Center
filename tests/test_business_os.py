"""Tests for OpsFlow Multi-Tenant Business Operating System.

Verifies:
1. Business template catalog retrieval (Online vs. Offline)
2. Automatic lazy initialization of BusinessProfile on Organization
3. Multi-tenant isolation between workspace business profiles
4. Template application and configuration of services, hours, policies, and AI instructions
5. Operating hours evaluation (is_open_now)
6. REST API v1 endpoints (/api/v1/business/*)
"""

import datetime
import json
import unittest

from app import create_app
from database import db
from models import BusinessProfile, Membership, Organization, User, generate_uuid
from business_templates import get_all_templates, get_template_by_id, get_templates_by_category


class TestBusinessOS(unittest.TestCase):
    """Test suite for Business Operating System functionality."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        cls.app.config["TESTING"] = True
        cls.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        cls.client = cls.app.test_client()

        with cls.app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Create isolated test organizations and owners
        self.org1 = Organization(
            id=generate_uuid("org"),
            name="Retail Hub Store",
            slug=f"retail-hub-{generate_uuid()[:6]}",
            plan_tier="pro"
        )
        self.org2 = Organization(
            id=generate_uuid("org"),
            name="Metro Dental Clinic",
            slug=f"metro-dental-{generate_uuid()[:6]}",
            plan_tier="pro"
        )
        db.session.add_all([self.org1, self.org2])

        self.user1 = User(
            id=generate_uuid("usr"),
            email=f"owner1-{generate_uuid()[:6]}@retailhub.com",
            full_name="Retail Owner"
        )
        self.user1.set_password("SecurePass2026!")

        self.user2 = User(
            id=generate_uuid("usr"),
            email=f"doctor-{generate_uuid()[:6]}@metrodental.com",
            full_name="Dr. Dental"
        )
        self.user2.set_password("SecurePass2026!")

        db.session.add_all([self.user1, self.user2])
        db.session.flush()

        self.mem1 = Membership(
            id=generate_uuid("mem"),
            user_id=self.user1.id,
            organization_id=self.org1.id,
            role="owner"
        )
        self.mem2 = Membership(
            id=generate_uuid("mem"),
            user_id=self.user2.id,
            organization_id=self.org2.id,
            role="owner"
        )
        db.session.add_all([self.mem1, self.mem2])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_business_template_catalog_definitions(self):
        """Templates must contain 10 total (5 online, 5 offline) with complete configurations."""
        all_tpls = get_all_templates()
        self.assertGreaterEqual(len(all_tpls), 10)

        online_tpls = get_templates_by_category("online")
        offline_tpls = get_templates_by_category("offline")
        self.assertEqual(len(online_tpls), 5)
        self.assertEqual(len(offline_tpls), 5)

        # Verify essential fields in each template
        for tpl in all_tpls:
            self.assertIn("id", tpl)
            self.assertIn("category", tpl)
            self.assertIn("industry", tpl)
            self.assertIn("default_services", tpl)
            self.assertIn("default_operating_hours", tpl)
            self.assertIn("default_policies", tpl)
            self.assertIn("ai_instructions", tpl)
            self.assertIn("default_roles", tpl)

    def test_lazy_initialization_of_business_profile(self):
        """Organization.get_business_profile() automatically creates profile if none exists."""
        self.assertIsNone(self.org1.business_profile)
        prof = self.org1.get_business_profile()
        self.assertIsNotNone(prof)
        self.assertEqual(prof.organization_id, self.org1.id)
        self.assertEqual(prof.business_category, "online")
        self.assertFalse(prof.is_configured)

    def test_multi_tenant_profile_isolation(self):
        """Updates to Organization 1's profile must not affect Organization 2."""
        prof1 = self.org1.get_business_profile()
        prof2 = self.org2.get_business_profile()

        prof1.business_category = "offline"
        prof1.industry = "retail"
        prof1.company_name = "Retail Hub Prime"

        prof2.business_category = "offline"
        prof2.industry = "clinic"
        prof2.company_name = "Metro Dental Clinic"

        db.session.commit()

        # Re-fetch from database to verify persistence and isolation
        fetched1 = BusinessProfile.query.filter_by(organization_id=self.org1.id).first()
        fetched2 = BusinessProfile.query.filter_by(organization_id=self.org2.id).first()

        self.assertEqual(fetched1.company_name, "Retail Hub Prime")
        self.assertEqual(fetched1.industry, "retail")
        self.assertEqual(fetched2.company_name, "Metro Dental Clinic")
        self.assertEqual(fetched2.industry, "clinic")

    def test_operating_hours_calculation(self):
        """is_open_now correctly handles operating schedule."""
        prof = self.org1.get_business_profile()
        prof.operating_hours_json = json.dumps({
            "timezone": "UTC",
            "schedule": {
                "mon": {"open": "09:00", "close": "17:00", "closed": False},
                "sun": {"open": "00:00", "close": "00:00", "closed": True},
            }
        })
        db.session.commit()

        # Simulate Monday at 12:00 (Open)
        monday_noon = datetime.datetime(2026, 10, 19, 12, 0, 0)  # Oct 19, 2026 is Monday
        status = prof.is_open_now(monday_noon)
        self.assertTrue(status["is_open"])
        self.assertIn("Open", status["reason"])

        # Simulate Monday at 20:00 (Closed)
        monday_night = datetime.datetime(2026, 10, 19, 20, 0, 0)
        status_closed = prof.is_open_now(monday_night)
        self.assertFalse(status_closed["is_open"])

        # Simulate Sunday (Closed all day)
        sunday = datetime.datetime(2026, 10, 25, 12, 0, 0)  # Oct 25, 2026 is Sunday
        status_sun = prof.is_open_now(sunday)
        self.assertFalse(status_sun["is_open"])
        self.assertIn("Closed on Sunday", status_sun["reason"])

    def test_api_catalog_endpoint(self):
        """GET /api/v1/business/catalog returns categorized template catalog."""
        resp = self.client.get("/api/v1/business/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["total_templates"], 10)
        self.assertEqual(data["online_count"], 5)
        self.assertEqual(data["offline_count"], 5)

        # Filter by category
        resp_online = self.client.get("/api/v1/business/catalog?category=online")
        self.assertEqual(resp_online.status_code, 200)
        data_online = resp_online.get_json()
        self.assertEqual(data_online["total_templates"], 5)
        self.assertTrue(all(t["category"] == "online" for t in data_online["templates"]))

    def test_api_profile_and_template_application(self):
        """POST /api/v1/business/apply-template configures the workspace profile."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user2.id
            sess["organization_id"] = self.org2.id
            sess["role"] = "owner"

        # Apply clinic template
        resp = self.client.post("/api/v1/business/apply-template", json={
            "template_id": "tpl-offline-clinic"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["profile"]["business_category"], "offline")
        self.assertEqual(data["profile"]["industry"], "clinic")
        self.assertTrue(data["profile"]["is_configured"])
        self.assertGreater(len(data["profile"]["services"]), 0)
        self.assertIn("emergency_disclaimer", data["profile"]["policies"])
        self.assertIn("medical", data["profile"]["ai_instructions"].lower())

        # Verify GET /api/v1/business/profile reflects updated profile
        get_resp = self.client.get("/api/v1/business/profile")
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.get_json()
        self.assertEqual(get_data["profile"]["industry"], "clinic")
        self.assertEqual(get_data["profile"]["business_category"], "offline")


if __name__ == "__main__":
    unittest.main()
