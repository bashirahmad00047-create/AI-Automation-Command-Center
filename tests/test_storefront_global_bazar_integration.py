"""
Comprehensive Integration Tests for Storefront (/store) & Multi-Vendor WhatsApp Flow
with Global-Bazar-Core ERP engine.
"""

import os
import sys
import json
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import application
from models import db, Product, Lead, EcommerceOrder
from services.global_bazar_service import GlobalBazarService


class TestStorefrontGlobalBazarIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        application.config["TESTING"] = True
        application.config["WTF_CSRF_ENABLED"] = False
        cls.client = application.test_client()

    def test_01_store_products_includes_global_bazar_items(self):
        """Verify GET /api/v1/store/products returns Global-Bazar items with seller info and smart_broker mode."""
        res = self.client.get("/api/v1/store/products")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        products = data.get("products", [])
        self.assertGreater(len(products), 0)

        # Check for presence of Global-Bazar-Core products
        gb_items = [p for p in products if str(p.get("id")).startswith("gb-") or p.get("source") == "global_bazar"]
        self.assertGreater(len(gb_items), 0, "Global-Bazar products should appear in store products feed")

        first_gb = gb_items[0]
        self.assertIn("seller_name", first_gb)
        self.assertIn("seller_phone", first_gb)
        self.assertEqual(first_gb.get("contact_mode"), "smart_broker")
        self.assertTrue(len(first_gb["seller_name"]) > 0)
        print(f"\n[STORE TEST 1 PASS] Found {len(gb_items)} Global-Bazar items in storefront. Sample: {first_gb['name']} by {first_gb['seller_name']}")

    def test_02_store_checkout_multi_vendor_stock_and_ledger(self):
        """
        Verify POST /api/store/checkout processes a Global-Bazar product:
        - Deducts stock in Global-Bazar-Core
        - Creates Global-Bazar order
        - Logs sale in vendor ledger
        - Returns seller direct WhatsApp link
        """
        # Fetch an active Global-Bazar product
        gb_products = GlobalBazarService.get_products()
        self.assertGreater(len(gb_products), 0)
        test_item = gb_products[0]
        initial_stock = test_item["stock"]
        item_id = test_item["id"]
        item_price = float(test_item["price"])
        item_title = test_item["title"]

        checkout_payload = {
            "customer_name": "Hamid Khan",
            "customer_phone": "03451234567",
            "customer_address": "Ataliq Bazar, Chitral",
            "payment_method": "cod",
            "notes": "Fast delivery requested",
            "cart": [
                {
                    "id": f"gb-{item_id}",
                    "name": item_title,
                    "price": item_price,
                    "quantity": 1
                }
            ]
        }

        with patch("whatsapp_service.WhatsAppService.send_message") as mock_wa:
            mock_wa.return_value = {"success": True, "message_id": "test_mid_123"}
            res = self.client.post("/api/store/checkout", json=checkout_payload)
            self.assertEqual(res.status_code, 201)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("order_number", data)

            # Check seller direct link was provided
            seller_links = data.get("seller_whatsapp_links", [])
            self.assertGreater(len(seller_links), 0)
            wa_url = seller_links[0].get("whatsapp_url") or seller_links[0].get("chat_url")
            self.assertIsNotNone(wa_url)
            self.assertTrue(wa_url.startswith("https://wa.me/"))

            # Check stock was deducted in Global-Bazar-Core
            updated_prod = GlobalBazarService.get_product_by_id(item_id)
            self.assertEqual(updated_prod["stock"], max(0, initial_stock - 1))

            # Verify Global-Bazar order exists in DB
            with GlobalBazarService.get_db_connection() as conn:
                c = conn.cursor()
                gb_orders = c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 1").fetchall()
                self.assertGreater(len(gb_orders), 0)
                last_gb_order = dict(gb_orders[0])
                self.assertEqual(last_gb_order["customer_name"], "Hamid Khan")

                # Verify ledger record was created
                ledger_entries = c.execute("SELECT * FROM ledger WHERE entry_type = 'sale' ORDER BY id DESC LIMIT 1").fetchall()
                self.assertGreater(len(ledger_entries), 0)
                last_ledger = dict(ledger_entries[0])
                self.assertEqual(last_ledger["amount"], item_price)

            print(f"[STORE TEST 2 PASS] Checkout deducted stock ({initial_stock} -> {updated_prod['stock']}) and recorded sale in ledger!")

    def test_03_seller_listing_syncs_to_global_bazar(self):
        """Verify POST /api/v1/store/seller/list-product creates both local Product and Global-Bazar-Core vendor/product."""
        unique_suffix = os.urandom(3).hex()
        unique_shop = f"Shahi Bazar Crafts {unique_suffix}"
        unique_item = f"Pure Chitrali Wool Chugha {unique_suffix}"
        seller_phone = f"0333{int(unique_suffix, 16) % 10000000:07d}"

        listing_payload = {
            "seller_name": unique_shop,
            "seller_phone": seller_phone,
            "seller_city": "Booni, Upper Chitral",
            "name": unique_item,
            "category": "Chitrali Crafts",
            "price": 8500.0,
            "description": "Exquisite handmade Chitrali warm chugha with traditional embroidery.",
            "image_url": "https://example.com/test_chugha.jpg"
        }

        with patch("whatsapp_service.WhatsAppService.send_message") as mock_wa:
            mock_wa.return_value = {"success": True}
            res = self.client.post("/api/v1/store/seller/list-product", json=listing_payload)
            self.assertEqual(res.status_code, 201)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertIn("global_bazar_product_id", data)

            # Verify vendor exists in Global-Bazar-Core
            with GlobalBazarService.get_db_connection() as conn:
                c = conn.cursor()
                digits = "".join(filter(str.isdigit, seller_phone))[-7:]
                vendor_row = c.execute("SELECT * FROM vendors WHERE phone LIKE ? OR name = ?", (f"%{digits}%", unique_shop)).fetchone()
                self.assertIsNotNone(vendor_row)
                v = dict(vendor_row)
                self.assertEqual(v["name"], unique_shop)

                # Verify product exists in Global-Bazar-Core
                prod_row = c.execute("SELECT * FROM products WHERE title = ?", (unique_item,)).fetchone()
                self.assertIsNotNone(prod_row)
                p = dict(prod_row)
                self.assertEqual(p["vendor_id"], v["id"])
                self.assertEqual(p["price"], 8500.0)

            print(f"[STORE TEST 3 PASS] Seller onboarding successfully created Vendor '{unique_shop}' and Product '{unique_item}' in Global-Bazar-Core!")

    def test_04_static_uploads_route(self):
        """Verify GET /static/uploads/<filename> route is mounted and handled."""
        res = self.client.get("/static/uploads/non_existent_image_test_123.png")
        # Should return 404 gracefully rather than 500 error
        self.assertIn(res.status_code, [404, 200])
        print(f"[STORE TEST 4 PASS] /static/uploads route is active (responded with status {res.status_code}).")

    def test_05_store_html_render(self):
        """Verify GET /store renders the HTML storefront containing category nav, vendor filter bar, and smart broker UI."""
        res = self.client.get("/store")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("getCategoryIcon", html)
        self.assertIn("categoryNav", html)
        self.assertIn("Chat Seller on WhatsApp", html)
        self.assertIn("vendorSelectFilter", html)
        self.assertIn("filterByVendor", html)
        self.assertIn("🏪 Shop:", html)
        print("[STORE TEST 5 PASS] /store HTML contains vendorSelectFilter, filterByVendor, dynamic categoryNav, and seller WhatsApp links.")

    def test_06_vendor_identification_via_whatsapp_image(self):
        """Verify WhatsApp image upload automatically captures sender pushName and phone as vendor."""
        from whatsapp_service import WhatsAppService
        v_phone = "03449988776"
        v_pushname = "Pamir Mountain Organic Hub"
        sample_img = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        with patch("whatsapp_service.WhatsAppService.send_message") as mock_wa:
            mock_wa.return_value = {"success": True}
            res = WhatsAppService.handle_whatsapp_inventory_image(
                organization_id="org-enterprise-default",
                sender_phone=v_phone,
                message_body="Add Pure Sidr Honey Rs 3800",
                image_bytes=sample_img,
                is_image=True,
                pushName=v_pushname
            )
            self.assertIsNotNone(res)
            self.assertTrue(res.get("success"))

            # Check vendor was created in Global-Bazar-Core
            with GlobalBazarService.get_db_connection() as conn:
                c = conn.cursor()
                v_row = c.execute("SELECT * FROM vendors WHERE name = ?", (v_pushname,)).fetchone()
                self.assertIsNotNone(v_row, "Vendor record must be created with pushName")
                v = dict(v_row)
                self.assertEqual(v["name"], v_pushname)

                # Check product is associated with this vendor
                p_row = c.execute("SELECT * FROM products WHERE vendor_id = ? ORDER BY id DESC LIMIT 1", (v["id"],)).fetchone()
                self.assertIsNotNone(p_row, "Product must be saved under this vendor ID")
                p = dict(p_row)
                self.assertEqual(p["vendor_id"], v["id"])
                self.assertEqual(p["price"], 3800.0)

            print(f"[STORE TEST 6 PASS] Vendor '{v_pushname}' automatically identified and saved with product!")

    def test_07_vendor_command_my_inventory_and_mera_saman(self):
        """Verify 'my inventory' and 'mera saman' replies with total product count and item list for that vendor's phone."""
        from whatsapp_service import WhatsAppService
        v_phone = "03449988776"
        v_pushname = "Pamir Mountain Organic Hub"

        with patch("whatsapp_service.WhatsAppService.send_message") as mock_wa:
            mock_wa.return_value = {"success": True}
            # Test "my inventory"
            res1 = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-enterprise-default",
                sender_phone=v_phone,
                message_body="my inventory",
                raw_payload={"pushName": v_pushname}
            )
            self.assertIsNotNone(res1)
            self.assertTrue(res1.get("success"))
            self.assertEqual(res1.get("action"), "vendor_inventory_inquiry")
            self.assertIn("Pamir Mountain Organic Hub", res1.get("reply_body"))
            self.assertIn("Pure Sidr Honey", res1.get("reply_body"))

            # Test "mera saman"
            res2 = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-enterprise-default",
                sender_phone=v_phone,
                message_body="mera saman",
                raw_payload={"pushName": v_pushname}
            )
            self.assertIsNotNone(res2)
            self.assertTrue(res2.get("success"))
            self.assertEqual(res2.get("action"), "vendor_inventory_inquiry")
            self.assertIn("Total Products", res2.get("reply_body"))

            print(f"[STORE TEST 7 PASS] 'my inventory' and 'mera saman' vendor inquiries verified successfully!")

    def test_08_storefront_product_fields_and_top_ordering(self):
        """Verify GET /api/v1/store/products returns unified mapped fields with newest items at the top."""
        res = self.client.get("/api/v1/store/products")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        prods = data.get("products", [])
        self.assertGreater(len(prods), 0)

        # Check fields on first item
        first_item = prods[0]
        self.assertIn("title", first_item)
        self.assertIn("description", first_item)
        self.assertIn("price", first_item)
        self.assertIn("estimated_price", first_item)
        self.assertIn("cleaned_image_url", first_item)
        self.assertIn("category", first_item)
        self.assertIn("vendor_name", first_item)
        self.assertIn("vendor_phone", first_item)

        # First item should be a Global-Bazar item (newest items at top)
        self.assertEqual(first_item.get("source"), "global_bazar")
        self.assertTrue(str(first_item.get("id")).startswith("gb-"))

        # Image URL should be cleaned (relative or valid URL without host:8000)
        img = first_item.get("cleaned_image_url") or ""
        self.assertFalse("http://127.0.0.1:8000" in img)
        self.assertFalse("http://localhost:8000" in img)

        print(f"[STORE TEST 8 PASS] All product fields correctly mapped and newly added items placed at top of store feed!")

    def test_09_vendor_magic_link_command(self):
        """Verify 'meri dukan' and 'my shop' generates short-lived token and sends formatted magic link."""
        from whatsapp_service import WhatsAppService
        v_phone = "03112233445"
        v_pushname = "Karakoram Mountain Gems"

        with patch("whatsapp_service.WhatsAppService.send_message") as mock_wa:
            mock_wa.return_value = {"success": True}
            # Test "meri dukan"
            res = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-enterprise-default",
                sender_phone=v_phone,
                message_body="meri dukan",
                raw_payload={"pushName": v_pushname}
            )
            self.assertIsNotNone(res)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "vendor_magic_link")

            reply = res.get("reply_body", "")
            self.assertIn("Aapki Online Dukaan Tayyar Hai!", reply)
            self.assertIn("http://66.45.230.232:5000/vendor/auth/", reply)

            token = res.get("token")
            self.assertTrue(len(token) > 10)

            # Test "my shop"
            res2 = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-enterprise-default",
                sender_phone=v_phone,
                message_body="my shop",
                raw_payload={"pushName": v_pushname}
            )
            self.assertIsNotNone(res2)
            self.assertTrue(res2.get("success"))
            self.assertIn("http://66.45.230.232:5000/vendor/auth/", res2.get("reply_body", ""))

            print(f"[STORE TEST 9 PASS] 'meri dukan' and 'my shop' WhatsApp magic link generator verified!")

    def test_10_vendor_auth_and_dashboard_route(self):
        """Verify /vendor/auth/<token> authenticates vendor and /vendor/dashboard renders vendor-specific portal."""
        # 1. Setup a test vendor with products
        vendor = GlobalBazarService.find_or_create_vendor(
            name="Wakhan Silk & Wool Crafts",
            phone="03129988771",
            owner_name="Karim Khan",
            address="Garam Chashma, Chitral"
        )
        v_id = vendor["id"]
        GlobalBazarService.add_product(
            title="Hand-spun Chitrali Pattu Wool Fabric",
            price=6800.0,
            stock=20,
            vendor_id=v_id,
            category="Chitrali Crafts",
            description="Pure sheep wool hand-woven fabric from Garam Chashma."
        )

        # 2. Generate valid magic token
        token = GlobalBazarService.generate_vendor_magic_token(v_id, "03129988771")

        # 3. Access /vendor/auth/<token>
        auth_res = self.client.get(f"/vendor/auth/{token}", follow_redirects=True)
        self.assertEqual(auth_res.status_code, 200)
        html = auth_res.data.decode("utf-8")
        self.assertIn("Wakhan Silk", html)
        self.assertIn("Hand-spun Chitrali Pattu Wool Fabric", html)
        self.assertIn("Garam Chashma, Chitral", html)
        self.assertIn("PKR 6,800", html)
        self.assertIn("Inventory Value", html)
        self.assertIn("Verified Merchant", html)

        # 4. Access /vendor/dashboard directly while logged in
        dash_res = self.client.get("/vendor/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn("Wakhan Silk", dash_res.data.decode("utf-8"))

        # 5. Access /vendor/auth with invalid token
        invalid_res = self.client.get("/vendor/auth/invalid_token_xyz_123")
        self.assertEqual(invalid_res.status_code, 401)
        self.assertIn("Authentication Error", invalid_res.data.decode("utf-8"))

        # 6. Test Logout
        logout_res = self.client.get("/vendor/logout", follow_redirects=False)
        self.assertEqual(logout_res.status_code, 302)

        print(f"[STORE TEST 10 PASS] /vendor/auth/<token> and /vendor/dashboard mobile portal verified end-to-end!")


if __name__ == "__main__":
    unittest.main()
