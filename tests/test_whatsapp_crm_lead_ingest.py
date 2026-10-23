import unittest
from unittest.mock import patch
from app import create_app
from database import db
from models import Organization, User, Membership, Lead, WhatsAppMessage
from whatsapp_service import WhatsAppService


class TestWhatsAppCRMLeadIngestion(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow WhatsApp CRM Hub",
                slug="opsflow-crm",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        self.user = User.query.filter_by(email="crm_admin@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-crm-admin",
                email="crm_admin@opsflow.io",
                full_name="CRM Admin",
                is_active=True
            )
            self.user.set_password("AdminPass123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-crm-admin",
                user_id=self.user.id,
                organization_id=self.org.id,
                role="admin"
            )
            db.session.add(mem)
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_auto_ingest_new_crm_lead_from_incoming_message(self):
        """Verifies that an incoming WhatsApp message creates a new CRM lead when phone is not present."""
        test_phone = "923119988776"

        # Ensure no lead exists initially
        Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).delete()
        db.session.commit()

        msg = WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=test_phone,
            recipient="system",
            direction="inbound",
            body="Hello, I want to inquire about your wholesale enterprise packages.",
            status="received",
            whatsapp_message_id="wamid.TEST.CRM.001",
            raw_payload={"sender_name": "Hamza Tariq"}
        )
        self.assertIsNotNone(msg)

        # Check that CRM Lead was auto-ingested
        lead = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.name, "Hamza Tariq")
        self.assertIn("wholesale enterprise packages", lead.message)
        self.assertIn(lead.status, ("new", "qualified"))

    def test_auto_ingest_skips_duplicate_phone_number(self):
        """Verifies that duplicate leads are not created if the phone number already exists."""
        test_phone = "923451122334"

        # Pre-create lead
        existing = Lead(
            id="lead-existing-01",
            organization_id=self.org.id,
            name="Existing Customer",
            phone=test_phone,
            message="Initial inquiry"
        )
        db.session.add(existing)
        db.session.commit()

        count_before = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).count()
        self.assertEqual(count_before, 1)

        # Inbound message from same phone
        WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=test_phone,
            recipient="system",
            direction="inbound",
            body="Follow up question regarding pricing.",
            status="received",
            whatsapp_message_id="wamid.TEST.CRM.002",
            raw_payload={"sender_name": "Existing Customer"}
        )

        count_after = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).count()
        self.assertEqual(count_after, 1, "Duplicate lead should not be created for existing phone number")

    def test_auto_ingest_location_extracts_google_maps_link_into_lead_message(self):
        """Verifies that an incoming WhatsApp location extracts Google Maps link directly into the lead message."""
        test_phone = "923335566778"
        Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).delete()
        db.session.commit()

        location_payload = {
            "latitude": 24.8607,
            "longitude": 67.0011,
            "name": "Central Retail Outlet Karachi",
            "address": "Shahrah-e-Faisal Block 6",
            "maps_url": "https://www.google.com/maps?q=24.8607,67.0011"
        }

        WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=test_phone,
            recipient="system",
            direction="inbound",
            body="[Location]",
            status="received",
            whatsapp_message_id="wamid.TEST.CRM.003",
            message_type="locationMessage",
            raw_payload={
                "sender_name": "Ayesha Khan",
                "location": location_payload
            }
        )

        lead = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.name, "Ayesha Khan")
        self.assertIn("google.com/maps?q=24.8607,67.0011", lead.message)
        self.assertIn("Central Retail Outlet Karachi", lead.message)
        self.assertEqual(lead.intent, "location_shared")

    def test_text_with_google_maps_url_extracts_into_lead_inquiry(self):
        """Verifies that a text message with a Google Maps URL extracts the link directly into the lead message."""
        test_phone = "923224455667"
        Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).delete()
        db.session.commit()

        maps_url = "https://www.google.com/maps?q=31.5204,74.3587"
        WhatsAppService.record_message(
            organization_id=self.org.id,
            sender=test_phone,
            recipient="system",
            direction="inbound",
            body=f"Please dispatch our warehouse inventory here: {maps_url}",
            status="received",
            whatsapp_message_id="wamid.TEST.CRM.004",
            raw_payload={"sender_name": "Warehouse Manager"}
        )

        lead = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).first()
        self.assertIsNotNone(lead)
        self.assertIn(maps_url, lead.message)
        self.assertIn("dispatch our warehouse inventory", lead.message)

    def test_webhook_ingress_triggers_lead_ingestion(self):
        """Verifies that webhook ingress routes automatically trigger lead ingestion."""
        test_phone = "923008877665"
        Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).delete()
        db.session.commit()

        # Simulate Green-API webhook notification with location
        webhook_data = {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "wamid.HOOK.CRM.005",
            "timestamp": 1729680000,
            "senderData": {
                "chatId": f"{test_phone}@c.us",
                "senderName": "Tariq Mahmood"
            },
            "messageData": {
                "typeMessage": "locationMessage",
                "locationMessageData": {
                    "nameLocation": "Industrial Estate",
                    "address": "Plot 12 Sector 5",
                    "latitude": 33.6844,
                    "longitude": 73.0479
                }
            }
        }

        with patch.object(WhatsAppService, "send_message", return_value={"success": True}):
            resp = self.client.post("/api/v1/webhooks/whatsapp/green-api", json=webhook_data)
            self.assertEqual(resp.status_code, 200)

        lead = Lead.query.filter_by(phone=test_phone, organization_id=self.org.id).first()
        self.assertIsNotNone(lead)
        self.assertEqual(lead.name, "Tariq Mahmood")
        self.assertIn("google.com/maps?q=33.6844,73.0479", lead.message)


if __name__ == "__main__":
    unittest.main()
