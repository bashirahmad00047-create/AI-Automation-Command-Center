import unittest
from unittest.mock import patch
from app import create_app
from database import db
from models import Organization, User, Membership, EcommerceOrder, Lead
from whatsapp_service import WhatsAppService


class TestBulkLeadsLocationAndTruckDispatch(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Logistics & Commerce",
                slug="opsflow-logistics",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        self.user = User.query.filter_by(email="logistics_admin@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-logistics-admin",
                email="logistics_admin@opsflow.io",
                full_name="Logistics Admin",
                is_active=True
            )
            self.user.set_password("SecurePass123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-logistics-admin",
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

    # =========================================================================
    # FEATURE 1: Bulk Leads Importer Tests
    # =========================================================================

    def test_bulk_lead_import_csv(self):
        """Verifies bulk CSV importing, field mapping, and duplicate phone skipping."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        csv_data = (
            "name,phone,email,company,message,category\n"
            "Hamza Tariq,03001234567,hamza@example.com,Retail Hub,Need POS scanners,Offline\n"
            "Ayesha Khan,03219876543,ayesha@shop.com,Ecom Direct,Online shop integration,Online\n"
            "Duplicate Lead,03001234567,duplicate@example.com,Dup Corp,Should be skipped,Offline\n"
        )

        resp = self.client.post("/api/v1/leads/bulk-import", json={"csv_content": csv_data})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["imported_count"], 2)
        self.assertEqual(data["skipped_count"], 1)

    # =========================================================================
    # FEATURE 2: WhatsApp Location Capture Tests
    # =========================================================================

    def test_whatsapp_location_capture_parsing(self):
        """Verifies parsing of location messages from Green-API and Meta payloads."""
        # 1. Green-API payload simulation
        green_payload = {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "MSG-LOC-001",
            "timestamp": 1729670000,
            "senderData": {
                "chatId": "923001234567@c.us",
                "senderName": "Zainab"
            },
            "messageData": {
                "typeMessage": "locationMessage",
                "locationMessageData": {
                    "nameLocation": "Central Warehouse Karachi",
                    "address": "Korangi Industrial Area Plot 44",
                    "latitude": 24.8307,
                    "longitude": 67.1245
                }
            }
        }
        parsed_green = WhatsAppService.parse_green_api_payload(green_payload)
        self.assertEqual(len(parsed_green), 1)
        self.assertIn("google.com/maps", parsed_green[0]["body"])
        self.assertIsNotNone(parsed_green[0].get("location"))
        self.assertAlmostEqual(parsed_green[0]["location"]["latitude"], 24.8307)
        self.assertAlmostEqual(parsed_green[0]["location"]["longitude"], 67.1245)

        # 2. Meta Cloud API payload simulation
        meta_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "phone_123"},
                        "messages": [{
                            "id": "wamid.LOC.99",
                            "from": "923219876543",
                            "type": "location",
                            "location": {
                                "latitude": 31.5204,
                                "longitude": 74.3587,
                                "name": "Gulberg III Lahore",
                                "address": "Main Boulevard"
                            }
                        }]
                    }
                }]
            }]
        }
        parsed_meta = WhatsAppService.parse_webhook_payload(meta_payload)
        self.assertEqual(len(parsed_meta), 1)
        self.assertIn("google.com/maps", parsed_meta[0]["body"])
        self.assertIsNotNone(parsed_meta[0].get("location"))
        self.assertAlmostEqual(parsed_meta[0]["location"]["latitude"], 31.5204)

    # =========================================================================
    # FEATURE 3: Truck Dispatch Tracking Tests
    # =========================================================================

    def test_truck_dispatch_tracking_flow(self):
        """Verifies assigning a fleet truck to an order, updating status, and generating WhatsApp alerts."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        # 1. Create Order
        order = EcommerceOrder(
            id="ord-truck-test-1",
            organization_id=self.org.id,
            order_number="ORD-TRUCK-8899",
            customer_phone="923001234567",
            customer_name="Bilal Shah",
            total_amount=14500.0,
            currency="PKR",
            order_status="confirmed",
            shipping_address="Shahrah-e-Faisal, Karachi"
        )
        db.session.add(order)
        db.session.commit()

        # 2. Dispatch Truck via API
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}):
            dispatch_resp = self.client.post("/api/v1/ecommerce/orders/ORD-TRUCK-8899/dispatch-truck", json={
                "truck_id": "TRK-08",
                "driver_name": "Aslam Khan",
                "driver_phone": "03129876543",
                "destination": "Shahrah-e-Faisal, Karachi",
                "estimated_arrival": "Today by 5:30 PM",
                "tracking_url": "https://maps.google.com/?q=24.8607,67.0011",
                "notify_whatsapp": True
            })
            self.assertEqual(dispatch_resp.status_code, 200)
            data = dispatch_resp.get_json()
            self.assertEqual(data["status"], "success")

            # Verify order was updated
            updated_order = EcommerceOrder.query.filter_by(order_number="ORD-TRUCK-8899").first()
            self.assertEqual(updated_order.order_status, "shipped")
            self.assertEqual(updated_order.courier_name, "Fleet Truck (TRK-08)")
            self.assertEqual(updated_order.tracking_number, "TRK-TRK-08")
            self.assertIn("TRK-08", updated_order.notes)

        # 3. Public tracking lookup
        track_resp = self.client.get("/api/v1/logistics/truck-dispatches/ORD-TRUCK-8899")
        self.assertEqual(track_resp.status_code, 200)
        track_data = track_resp.get_json()
        self.assertEqual(track_data["order_number"], "ORD-TRUCK-8899")
        self.assertEqual(track_data["courier_name"], "Fleet Truck (TRK-08)")


if __name__ == "__main__":
    unittest.main()
