import unittest
from app import create_app
from database import db
from models import Organization, User, Membership, Lead, Product, AutomationRule, BroadcastCampaign, CompanyMessage
from whatsapp_service import WhatsAppService
from campaign_service import CampaignService
from storage import Storage
from company_messaging_service import CompanyMessagingService


class TestDemoOverhaulReadiness(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org_id = "org-demo-readiness"
        self.org = Organization.query.filter_by(id=self.org_id).first()
        if not self.org:
            self.org = Organization(
                id=self.org_id,
                name="OpsFlow Demo Readiness Hub",
                slug="opsflow-demo",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        self.user = User.query.filter_by(email="demo_tester@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-demo-tester",
                email="demo_tester@opsflow.io",
                full_name="Demo Architect",
                is_active=True
            )
            self.user.set_password("SecureDemo123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-demo-tester",
                user_id=self.user.id,
                organization_id=self.org.id,
                role="admin"
            )
            db.session.add(mem)
            db.session.commit()

        self.client = self.app.test_client()

        # Login session
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["organization_id"] = self.org.id
            sess["role"] = "admin"

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_products_catalog_auto_seed(self):
        """Fix 1: Products Catalog Auto-Seeding when empty."""
        # Clean products for this org
        Product.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()
        self.assertEqual(Product.query.filter_by(organization_id=self.org.id).count(), 0)

        # Request via API
        resp = self.client.get("/api/v1/ecommerce/products")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        products = data.get("products", [])

        self.assertGreaterEqual(len(products), 5)
        names = [p["name"] for p in products]
        self.assertIn("Men's Cotton Kurta", names)
        self.assertIn("Leather Formal Shoes", names)
        self.assertIn("Wireless Bluetooth Earbuds", names)
        self.assertIn("Pure Organic Honey (500g)", names)
        self.assertIn("Embroidered Lawn Stitched Suit", names)

        for p in products:
            self.assertGreater(p["price"], 0)
            self.assertGreater(p["stock_quantity"], 0)
            self.assertTrue(p["image_url"].startswith("http"))
            self.assertIn(p["category"], ["Apparel & Fashion", "Footwear", "Consumer Electronics", "Grocery & Gourmet", "Women's Fashion"])

    def test_campaigns_and_broadcasts_auto_seed(self):
        """Fix 2: Broadcast Campaigns Auto-Seeding when empty."""
        BroadcastCampaign.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()
        self.assertEqual(BroadcastCampaign.query.filter_by(organization_id=self.org.id).count(), 0)

        campaigns = CampaignService.list_campaigns(self.org.id)
        self.assertGreaterEqual(len(campaigns), 2)
        titles = [c["title"] for c in campaigns]
        self.assertIn("Eid Clearance VIP Broadcast", titles)
        self.assertIn("Weekend Flash Promo", titles)

        eid_camp = next(c for c in campaigns if c["title"] == "Eid Clearance VIP Broadcast")
        self.assertEqual(eid_camp["status"], "completed")
        self.assertEqual(eid_camp["total_recipients"], 1250)
        self.assertEqual(eid_camp["delivered_count"], 1225)

    def test_workflows_studio_auto_seed(self):
        """Fix 3: Workflows Studio Auto-Seeding when empty."""
        AutomationRule.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()
        self.assertEqual(AutomationRule.query.filter_by(organization_id=self.org.id).count(), 0)

        storage = Storage()
        rules = storage.get_rules(organization_id=self.org.id)
        self.assertGreaterEqual(len(rules), 2)
        names = [r["name"] for r in rules]
        self.assertIn("Urdu WhatsApp Voice-Lead Qualifier", names)
        self.assertIn("High-Priority Support Escalation", names)

        # Check visual steps
        urdu_rule = next(r for r in rules if r["name"] == "Urdu WhatsApp Voice-Lead Qualifier")
        self.assertTrue(urdu_rule.get("enabled"))
        self.assertGreaterEqual(len(urdu_rule.get("steps", [])), 3)

    def test_internal_channels_preload_messages(self):
        """Fix 4: Internal Channels Preload Messages in #general and #incidents."""
        # Ensure channels exist
        CompanyMessagingService.ensure_default_channels(self.org.id)
        channels = CompanyMessagingService.list_channels(self.org.id, self.user.id)
        gen_ch = next((c for c in channels if c["name"] == "general"), None)
        inc_ch = next((c for c in channels if c["name"] == "incidents"), None)

        self.assertIsNotNone(gen_ch)
        self.assertIsNotNone(inc_ch)

        # Clear existing messages in both channels to test auto-preload
        CompanyMessage.query.filter(CompanyMessage.channel_id.in_([gen_ch["id"], inc_ch["id"]])).delete(synchronize_session=False)
        db.session.commit()

        gen_msgs = CompanyMessagingService.list_messages(gen_ch["id"], self.org.id)
        self.assertGreaterEqual(len(gen_msgs), 3)
        self.assertTrue(any("Ignite" in m["body"] and "investor demo" in m["body"] for m in gen_msgs))

        inc_msgs = CompanyMessagingService.list_messages(inc_ch["id"], self.org.id)
        self.assertGreaterEqual(len(inc_msgs), 3)
        self.assertTrue(any("INC-892" in m["body"] or "Health Check" in m["body"] for m in inc_msgs))

    def test_crm_leads_contact_metadata_and_intent(self):
        """Fix 5: Contact Name, Formatted Phone, and Intent Classification without 'N/A'."""
        # Test phone formatter
        formatted = WhatsAppService.format_phone_display("923209350858")
        self.assertEqual(formatted, "+92 320 9350858")

        formatted_cus = WhatsAppService.format_phone_display("923001234567@c.us")
        self.assertEqual(formatted_cus, "+92 300 1234567")

        # Clean existing test leads if any
        Lead.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()

        # Test Lead ingestion with explicit sender name
        lead1_dict = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923209350858@c.us",
            sender_name="Muhammad Tariq",
            message_body="Salam, I want to order 2 pairs of Leather Formal Shoes size 42."
        )
        self.assertIsNotNone(lead1_dict)
        self.assertEqual(lead1_dict["name"], "Muhammad Tariq")
        self.assertEqual(lead1_dict["phone"], "+92 320 9350858")
        self.assertEqual(lead1_dict["lead_score"], 85)
        self.assertNotEqual(lead1_dict["status"], "N/A")
        self.assertNotIn("N/A", [lead1_dict["name"], lead1_dict["email"] or "", lead1_dict["company"] or ""])

        # Test Lead ingestion without sender name (fallback to formatted phone)
        lead2_dict = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923007654321@c.us",
            sender_name="",
            message_body="Can someone help me with payment confirmation on JazzCash?"
        )
        self.assertIsNotNone(lead2_dict)
        self.assertEqual(lead2_dict["name"], "+92 300 7654321")
        self.assertEqual(lead2_dict["phone"], "+92 300 7654321")
        self.assertNotIn("N/A", [lead2_dict["name"], lead2_dict["email"] or "", lead2_dict["company"] or ""])


if __name__ == "__main__":
    unittest.main()
