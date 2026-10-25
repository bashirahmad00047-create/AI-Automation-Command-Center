import unittest
from app import create_app
from database import db
from models import Organization, User, Membership, Lead, Product, AutomationRule, BroadcastCampaign, CompanyMessage
from whatsapp_service import WhatsAppService
from campaign_service import CampaignService
from storage import Storage
from company_messaging_service import CompanyMessagingService
from auth import get_client_ip, log_audit_event


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
        Product.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()
        self.assertEqual(Product.query.filter_by(organization_id=self.org.id).count(), 0)

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

        urdu_rule = next(r for r in rules if r["name"] == "Urdu WhatsApp Voice-Lead Qualifier")
        self.assertTrue(urdu_rule.get("enabled"))
        self.assertGreaterEqual(len(urdu_rule.get("steps", [])), 3)

    def test_internal_channels_preload_messages(self):
        """Fix 4: Internal Channels Preload Messages in #general and #incidents."""
        CompanyMessagingService.ensure_default_channels(self.org.id)
        channels = CompanyMessagingService.list_channels(self.org.id, self.user.id)
        gen_ch = next((c for c in channels if c["name"] == "general"), None)
        inc_ch = next((c for c in channels if c["name"] == "incidents"), None)

        self.assertIsNotNone(gen_ch)
        self.assertIsNotNone(inc_ch)

        CompanyMessage.query.filter(CompanyMessage.channel_id.in_([gen_ch["id"], inc_ch["id"]])).delete(synchronize_session=False)
        db.session.commit()

        gen_msgs = CompanyMessagingService.list_messages(gen_ch["id"], self.org.id)
        self.assertGreaterEqual(len(gen_msgs), 3)
        self.assertTrue(any("Ignite" in m["body"] and "investor demo" in m["body"] for m in gen_msgs))

        inc_msgs = CompanyMessagingService.list_messages(inc_ch["id"], self.org.id)
        self.assertGreaterEqual(len(inc_msgs), 3)
        self.assertTrue(any("INC-892" in m["body"] or "Health Check" in m["body"] for m in inc_msgs))

    def test_crm_leads_contact_metadata_and_granular_intents(self):
        """Fix 5: Granular dynamic intent classification and dynamic lead scoring without 'N/A'."""
        formatted = WhatsAppService.format_phone_display("923209350858")
        self.assertEqual(formatted, "+92 320 9350858")

        formatted_cus = WhatsAppService.format_phone_display("923001234567@c.us")
        self.assertEqual(formatted_cus, "+92 300 1234567")

        Lead.query.filter_by(organization_id=self.org.id).delete()
        db.session.commit()

        # 1. Product Order Intent: score 85 - 95
        lead_order = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923209350858@c.us",
            sender_name="Muhammad Tariq",
            message_body="Salam, I want to order 2 pairs of Leather Formal Shoes size 42."
        )
        self.assertIsNotNone(lead_order)
        self.assertEqual(lead_order["name"], "Muhammad Tariq")
        self.assertEqual(lead_order["phone"], "+92 320 9350858")
        self.assertEqual(lead_order["intent"], "PRODUCT_ORDER")
        self.assertGreaterEqual(lead_order["lead_score"], 85)
        self.assertLessEqual(lead_order["lead_score"], 95)
        self.assertNotIn("N/A", [lead_order["name"], lead_order["email"] or "", lead_order["company"] or ""])

        # 2. Service & Pricing Query Intent: score 75 - 90
        lead_pricing = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923114455667@c.us",
            sender_name="Zubair Ahmed",
            message_body="Can you please share the enterprise rate list and pricing quote for automation workflows?"
        )
        self.assertIsNotNone(lead_pricing)
        self.assertEqual(lead_pricing["intent"], "SERVICE_PRICING_QUERY")
        self.assertGreaterEqual(lead_pricing["lead_score"], 75)
        self.assertLessEqual(lead_pricing["lead_score"], 90)

        # 3. Casual Greeting Intent: score 30 - 45
        lead_greeting = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923337788990@c.us",
            sender_name="Ali Raza",
            message_body="Assalam-o-Alaikum brother, hope you are doing well!"
        )
        self.assertIsNotNone(lead_greeting)
        self.assertEqual(lead_greeting["intent"], "CASUAL_GREETING")
        self.assertGreaterEqual(lead_greeting["lead_score"], 30)
        self.assertLessEqual(lead_greeting["lead_score"], 45)

        # 4. Tech Support Intent: routed to Support
        lead_support = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923458899001@c.us",
            sender_name="Farhan Saeed",
            message_body="Our webhook ingress is returning 500 error, please help resolve this problem."
        )
        self.assertIsNotNone(lead_support)
        self.assertEqual(lead_support["intent"], "TECH_SUPPORT")
        self.assertEqual(lead_support["route_department"], "Support")

        # 5. Missing profile name fallback to formatted phone
        lead_fallback = WhatsAppService.auto_ingest_crm_lead(
            organization_id=self.org.id,
            from_phone="923007654321@c.us",
            sender_name="",
            message_body="Payment confirmation done on JazzCash."
        )
        self.assertIsNotNone(lead_fallback)
        self.assertEqual(lead_fallback["name"], "+92 300 7654321")
        self.assertEqual(lead_fallback["phone"], "+92 300 7654321")
        self.assertEqual(lead_fallback["intent"], "PAYMENT_CONFIRMATION")
        self.assertNotIn("N/A", [lead_fallback["name"], lead_fallback["email"] or "", lead_fallback["company"] or ""])

    def test_dynamic_client_ip_audit_logging(self):
        """Fix 3 & 4: Inbound real IP detection in audit logs."""
        with self.app.test_request_context("/api/v1/auth/me", headers={"X-Forwarded-For": "182.180.74.192, 10.0.0.1"}):
            ip = get_client_ip()
            self.assertEqual(ip, "182.180.74.192")

            log_audit_event(
                action="test.client_ip_verification",
                resource_type="audit",
                org_id=self.org.id,
                user_id=self.user.id
            )

        from models import AuditLog
        audit = AuditLog.query.filter_by(action="test.client_ip_verification").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.ip_address, "182.180.74.192")

    def test_edge_tts_neural_voice_synthesis(self):
        """Verifies Microsoft Edge Neural TTS synthesizes realistic Pakistani Urdu voice audio."""
        audio_bytes = WhatsAppService._synthesize_edge_tts(
            "Assalam-o-Alaikum, aap ka order confirm ho chuka hai.",
            language="roman_urdu"
        )
        self.assertIsNotNone(audio_bytes)
        self.assertGreater(len(audio_bytes), 500)

    def test_dispatch_guarantee_text_and_voice_oga(self):
        """Requirement 1 & 2: Tests text dispatch via send_green_api_message AND .oga voice note via send_green_api_file."""
        from unittest.mock import patch, MagicMock

        fake_oga = b"OggS\x00\x02\x00\x00" + b"\x00" * 300

        with patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "idMessage": "msg-123"}) as mock_msg, \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=(fake_oga, "voice_reply.oga", "audio/ogg; codecs=opus")) as mock_voice, \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": True, "idMessage": "file-456"}) as mock_file, \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={"reply_body": "Aap ka shukriya, order process ho raha hai.", "intent": "order_intent", "lead_score": 85}):

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="Can you please confirm my order delivery?",
                sender_name="Mubi",
                message_id="wamid.test.dispatch.001"
            )

            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            mock_msg.assert_called_once()
            self.assertIn("order process ho raha hai", mock_msg.call_args[1]["message_text"])

            mock_voice.assert_called_once()
            self.assertEqual(mock_voice.call_args[1]["output_format"], "oga")

            mock_file.assert_called_once()
            self.assertEqual(mock_file.call_args[1]["file_bytes"], fake_oga)
            self.assertEqual(mock_file.call_args[1]["filename"], "voice_reply.oga")

    def test_voice_synthesis_fallback_protection(self):
        """Requirement 3: Fallback Protection: if voice synthesis fails, text reply STILL goes through without skipping."""
        from unittest.mock import patch

        with patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "idMessage": "msg-789"}) as mock_msg, \
             patch.object(WhatsAppService, "generate_spoken_audio", side_effect=RuntimeError("TTS engine network timeout")), \
             patch.object(WhatsAppService, "generate_ai_auto_response", return_value={"reply_body": "OpsFlow support team active hai.", "intent": "support_request", "lead_score": 60}):

            res = WhatsAppService.handle_inbound_auto_response(
                organization_id=self.org.id,
                sender_phone="923209350858",
                message_body="Support ticket test",
                sender_name="B",
                message_id="wamid.test.fallback.002"
            )

            self.assertIsNotNone(res)
            self.assertTrue(res["success"])
            mock_msg.assert_called_once()
            self.assertIn("OpsFlow support team active hai", mock_msg.call_args[1]["message_text"])


if __name__ == "__main__":
    unittest.main()
