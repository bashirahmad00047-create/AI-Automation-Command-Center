import datetime
import json
import time
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from database import db
from models import Organization, User, Product, EcommerceOrder, AbandonedCart, WhatsAppMessage
from whatsapp_service import WhatsAppService


class TestEcommerceWhatsAppFeatures(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not self.org:
            self.org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Cloud Commerce",
                slug="opsflow-commerce",
                is_active=True
            )
            db.session.add(self.org)
            db.session.commit()

        from models import Membership
        # Admin user for authenticated routes
        self.user = User.query.filter_by(email="commerce_admin@opsflow.io").first()
        if not self.user:
            self.user = User(
                id="usr-commerce-admin",
                email="commerce_admin@opsflow.io",
                full_name="Commerce Admin",
                is_active=True
            )
            self.user.set_password("SecurePass123!")
            db.session.add(self.user)
            db.session.commit()

            mem = Membership(
                id="mem-commerce-admin",
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
    # FEATURE 1 TESTS: Live Product Catalog & Inventory Search
    # =========================================================================

    def test_query_product_catalog_and_formatting(self):
        """Verifies product catalog queries, stock filtering, and mobile WhatsApp formatting."""
        p1 = Product(
            organization_id=self.org.id,
            name="Wireless Noise-Cancelling Earbuds",
            category="Audio",
            description="Premium earbuds with 30-hour battery life",
            sku="EAR-001",
            price=6500.0,
            currency="PKR",
            stock_quantity=15,
            stock_status="in_stock"
        )
        p2 = Product(
            organization_id=self.org.id,
            name="Smart Fitness Watch V2",
            category="Wearables",
            description="Heart-rate monitor with AMOLED display",
            sku="WAT-002",
            price=12000.0,
            currency="PKR",
            stock_quantity=2,
            stock_status="low_stock"
        )
        p3 = Product(
            organization_id=self.org.id,
            name="Ultra-Fast 65W GaN Charger",
            category="Accessories",
            description="Compact 3-port charger",
            sku="CHG-003",
            price=4200.0,
            currency="PKR",
            stock_quantity=0,
            stock_status="out_of_stock"
        )
        db.session.add_all([p1, p2, p3])
        db.session.commit()

        # 1. Query all
        all_items = WhatsAppService.query_product_catalog(self.org.id)
        self.assertGreaterEqual(len(all_items), 3)

        # 2. Filter by search query
        searched = WhatsAppService.query_product_catalog(self.org.id, search_query="Earbuds")
        self.assertEqual(len(searched), 1)
        self.assertEqual(searched[0]["sku"], "EAR-001")

        # 3. Filter in_stock_only
        in_stock = WhatsAppService.query_product_catalog(self.org.id, in_stock_only=True)
        skus = [p["sku"] for p in in_stock]
        self.assertIn("EAR-001", skus)
        self.assertIn("WAT-002", skus)
        self.assertNotIn("CHG-003", skus)

        # 4. Format into WhatsApp message
        catalog_msg = WhatsAppService.format_product_catalog_message(all_items[:3], self.org.id)
        self.assertIn("Wireless Noise-Cancelling Earbuds", catalog_msg)
        self.assertIn("PKR 6,500.00", catalog_msg)
        self.assertIn("✅ In Stock", catalog_msg)
        self.assertIn("⚠️ Only 2 left!", catalog_msg)
        self.assertIn("❌ Out of Stock", catalog_msg)

    def test_get_product_catalog_context_for_ai_grounding(self):
        """Verifies get_product_catalog_context generates accurate grounding lines for LLM."""
        p = Product(
            organization_id=self.org.id,
            name="iPhone 15 Pro Max 256GB",
            category="Smartphones",
            price=450000.0,
            currency="PKR",
            stock_quantity=4,
            stock_status="in_stock",
            sku="IPH-15PM-256"
        )
        db.session.add(p)
        db.session.commit()

        context = WhatsAppService.get_product_catalog_context(self.org.id, search_term="iPhone 15")
        self.assertIn("LIVE PRODUCT CATALOG & INVENTORY GROUNDING", context)
        self.assertIn("iPhone 15 Pro Max 256GB", context)
        self.assertIn("PKR 450,000.00", context)
        self.assertIn("IPH-15PM-256", context)

    def test_send_catalog_to_whatsapp(self):
        """Verifies send_catalog_to_whatsapp dispatches catalog message via send_message."""
        p = Product(
            organization_id=self.org.id,
            name="Gaming Keyboard RGB",
            category="Gaming",
            price=8500.0,
            currency="PKR",
            stock_quantity=10
        )
        db.session.add(p)
        db.session.commit()

        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
            res = WhatsAppService.send_catalog_to_whatsapp(
                organization_id=self.org.id,
                to_phone="923209350858",
                search_query="Gaming"
            )
            self.assertTrue(res["success"])
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            self.assertIn("Gaming Keyboard RGB", call_kwargs["message_text"])

    # =========================================================================
    # FEATURE 2 TESTS: Order Tracking & Status Updates
    # =========================================================================

    def test_send_order_status_update_confirmed(self):
        """Verifies order confirmed WhatsApp message dispatch and database record tracking."""
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
            res = WhatsAppService.send_order_status_update(
                organization_id=self.org.id,
                to_phone="923209350858",
                order_number="ORD-1001",
                order_status="confirmed",
                customer_name="Kamran",
                items=[{"name": "Wireless Earbuds", "quantity": 1}],
                total_amount=6500.0,
                currency="PKR"
            )
            self.assertTrue(res["success"])
            mock_send.assert_called_once()
            text = mock_send.call_args[1]["message_text"]
            self.assertIn("Order Confirmed!", text)
            self.assertIn("ORD-1001", text)
            self.assertIn("PKR 6,500.00", text)

            # Check DB record created
            order = EcommerceOrder.query.filter_by(order_number="ORD-1001").first()
            self.assertIsNotNone(order)
            self.assertEqual(order.order_status, "confirmed")
            self.assertEqual(order.last_notified_status, "confirmed")
            self.assertIsNotNone(order.last_notified_at)

    def test_send_order_status_update_shipped(self):
        """Verifies order shipped notification dispatches tracking number, courier, and live tracking link."""
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
            res = WhatsAppService.send_order_status_update(
                organization_id=self.org.id,
                to_phone="923209350858",
                order_number="ORD-1002",
                order_status="shipped",
                customer_name="Kamran",
                total_amount=12000.0,
                courier_name="TCS Courier",
                tracking_number="TCS-778899",
                tracking_url="https://tcs.com.pk/track/TCS-778899"
            )
            self.assertTrue(res["success"])
            text = mock_send.call_args[1]["message_text"]
            self.assertIn("Your Order Has Been Shipped!", text)
            self.assertIn("TCS Courier", text)
            self.assertIn("TCS-778899", text)
            self.assertIn("https://tcs.com.pk/track/TCS-778899", text)

    def test_get_order_tracking_context(self):
        """Verifies get_order_tracking_context extracts order number from customer message."""
        order = EcommerceOrder(
            organization_id=self.org.id,
            order_number="ORD-8821",
            customer_phone="923209350858",
            customer_name="Hamza",
            order_status="shipped",
            courier_name="Leopard Courier",
            tracking_number="LEO-991122",
            tracking_url="https://leopardscourier.com/track/LEO-991122",
            total_amount=15500.0,
            currency="PKR"
        )
        order.set_items([{"name": "Mechanical Keyboard", "quantity": 1}])
        db.session.add(order)
        db.session.commit()

        context = WhatsAppService.get_order_tracking_context(
            organization_id=self.org.id,
            sender_phone="923209350858",
            query_text="Where is my order ORD-8821?"
        )
        self.assertIn("CUSTOMER ORDER & TRACKING GROUNDING", context)
        self.assertIn("ORD-8821", context)
        self.assertIn("SHIPPED", context)
        self.assertIn("Leopard Courier", context)
        self.assertIn("LEO-991122", context)

    # =========================================================================
    # FEATURE 3 TESTS: Abandoned Cart Recovery Alerts
    # =========================================================================

    def test_send_abandoned_cart_recovery(self):
        """Verifies abandoned cart recovery message dispatch, discount code, and status update."""
        cart = AbandonedCart(
            organization_id=self.org.id,
            customer_phone="923209350858",
            customer_name="Zubair",
            cart_value=8500.0,
            currency="PKR",
            checkout_url="https://mystore.pk/checkout/crt_test_101",
            discount_code="SAVE10",
            recovery_status="abandoned"
        )
        cart.set_items([{"name": "Leather Jacket", "quantity": 1, "price": 8500.0}])
        db.session.add(cart)
        db.session.commit()

        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}) as mock_send:
            res = WhatsAppService.send_abandoned_cart_recovery(
                organization_id=self.org.id,
                to_phone=cart.customer_phone,
                customer_name=cart.customer_name,
                items=cart.get_items(),
                cart_value=cart.cart_value,
                currency=cart.currency,
                checkout_url=cart.checkout_url,
                discount_code=cart.discount_code,
                cart_id=cart.id
            )
            self.assertTrue(res["success"])
            mock_send.assert_called_once()
            text = mock_send.call_args[1]["message_text"]
            self.assertIn("Salam Zubair!", text)
            self.assertIn("Leather Jacket", text)
            self.assertIn("PKR 8,500.00", text)
            self.assertIn("SAVE10", text)
            self.assertIn("https://mystore.pk/checkout/crt_test_101", text)

            # Check DB updated
            db.session.refresh(cart)
            self.assertEqual(cart.recovery_status, "reminder_sent")
            self.assertEqual(cart.reminder_count, 1)
            self.assertIsNotNone(cart.last_reminder_sent_at)

    def test_process_pending_cart_reminders_batch(self):
        """Verifies process_pending_cart_reminders finds eligible carts and dispatches batch reminders."""
        old_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=45)
        cart = AbandonedCart(
            organization_id=self.org.id,
            customer_phone="923209350858",
            customer_name="Ali",
            cart_value=3200.0,
            currency="PKR",
            recovery_status="abandoned",
            reminder_count=0,
            created_at=old_time
        )
        db.session.add(cart)
        db.session.commit()

        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}):
            batch_res = WhatsAppService.process_pending_cart_reminders(
                organization_id=self.org.id,
                older_than_minutes=30,
                max_batch=10
            )
            self.assertTrue(batch_res["success"])
            self.assertGreaterEqual(batch_res["reminders_sent"], 1)

    # =========================================================================
    # REST API ENDPOINT TESTS
    # =========================================================================

    def test_api_ecommerce_product_crud_and_share(self):
        """Verifies /api/v1/ecommerce/products and /api/v1/ecommerce/catalog/share endpoints."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        # 1. Create product via API
        create_resp = self.client.post("/api/v1/ecommerce/products", json={
            "name": "USB-C Fast Cable 2M",
            "category": "Cables",
            "price": 1200.0,
            "currency": "PKR",
            "stock_quantity": 25,
            "sku": "CAB-002"
        })
        self.assertEqual(create_resp.status_code, 201)
        prd_data = create_resp.get_json()["product"]
        self.assertEqual(prd_data["name"], "USB-C Fast Cable 2M")

        # 2. List products
        list_resp = self.client.get("/api/v1/ecommerce/products?query=Cable")
        self.assertEqual(list_resp.status_code, 200)
        self.assertGreaterEqual(list_resp.get_json()["count"], 1)

        # 3. Share catalog via WhatsApp
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}):
            share_resp = self.client.post("/api/v1/ecommerce/catalog/share", json={
                "to_phone": "923209350858",
                "query": "Cable"
            })
            self.assertEqual(share_resp.status_code, 200)

    def test_api_ecommerce_orders_and_tracking(self):
        """Verifies order creation, WhatsApp notification endpoint, and public tracking lookup."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        # 1. Ingest order
        ord_resp = self.client.post("/api/v1/ecommerce/orders", json={
            "order_number": "ORD-5544",
            "customer_phone": "923209350858",
            "customer_name": "Tariq",
            "total_amount": 7500.0,
            "currency": "PKR",
            "items": [{"name": "Smart Watch", "quantity": 1}],
            "courier_name": "TCS",
            "tracking_number": "TCS-112233"
        })
        self.assertEqual(ord_resp.status_code, 201)

        # 2. Trigger notification
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}):
            notify_resp = self.client.post("/api/v1/ecommerce/orders/ORD-5544/notify", json={
                "order_status": "shipped",
                "tracking_number": "TCS-112233"
            })
            self.assertEqual(notify_resp.status_code, 200)
            self.assertTrue(notify_resp.get_json()["status"] == "success")

        # 3. Public order tracking
        track_resp = self.client.post("/api/v1/ecommerce/orders/track", json={
            "order_number": "ORD-5544"
        })
        self.assertEqual(track_resp.status_code, 200)
        self.assertEqual(track_resp.get_json()["orders"][0]["order_number"], "ORD-5544")
        self.assertEqual(track_resp.get_json()["orders"][0]["tracking_number"], "TCS-112233")

    def test_api_ecommerce_abandoned_carts(self):
        """Verifies abandoned cart ingestion, listing, and WhatsApp recovery dispatch."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user.id
            sess["org_id"] = self.org.id

        # 1. Ingest cart
        ingest_resp = self.client.post("/api/v1/ecommerce/carts/abandoned", json={
            "customer_phone": "923209350858",
            "customer_name": "Noman",
            "cart_value": 4500.0,
            "items": [{"name": "Running Shoes", "quantity": 1, "price": 4500.0}],
            "checkout_url": "https://mystore.pk/checkout/crt_999"
        })
        self.assertEqual(ingest_resp.status_code, 201)
        cart_id = ingest_resp.get_json()["cart"]["id"]

        # 2. List carts with metrics
        list_resp = self.client.get("/api/v1/ecommerce/carts/abandoned")
        self.assertEqual(list_resp.status_code, 200)
        metrics = list_resp.get_json()["metrics"]
        self.assertGreaterEqual(metrics["total_abandoned_carts"], 1)

        # 3. Recover cart via WhatsApp
        with patch.object(WhatsAppService, "send_message", return_value={"success": True, "status": "sent"}):
            recover_resp = self.client.post(f"/api/v1/ecommerce/carts/{cart_id}/recover", json={
                "discount_code": "PROMO20"
            })
            self.assertEqual(recover_resp.status_code, 200)
            self.assertEqual(recover_resp.get_json()["cart"]["recovery_status"], "reminder_sent")

        # 4. Mark recovered
        mark_resp = self.client.post(f"/api/v1/ecommerce/carts/{cart_id}/mark-recovered")
        self.assertEqual(mark_resp.status_code, 200)
        self.assertEqual(mark_resp.get_json()["cart"]["recovery_status"], "recovered")


if __name__ == "__main__":
    unittest.main()
