"""
Integration Test Suite: BashFlow & Global-Bazar-Core WhatsApp Inventory Management
Tests SQLite dual-mode sync, merchant WhatsApp commands (!stock, !hisaab, !addstock),
catalog prompt grounding, and automated order/ledger pipeline.
Strictly executed on local files.
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.global_bazar_service import GlobalBazarService
from services.catalog_data import get_all_catalog_items, get_default_catalog_context
from whatsapp_service import WhatsAppService


class TestGlobalBazarIntegration(unittest.TestCase):

    def setUp(self):
        self.db_path = GlobalBazarService.get_db_path()
        self.assertTrue(os.path.exists(self.db_path), f"Global Bazar DB does not exist at {self.db_path}")

    def test_01_db_connection_and_vendors(self):
        """Verifies database connectivity and vendor loading."""
        vendors = GlobalBazarService.get_vendors()
        self.assertIsInstance(vendors, list)
        self.assertGreater(len(vendors), 0, "Expected at least 1 vendor in Global-Bazar-Core DB")
        default_vid = GlobalBazarService.get_default_vendor_id()
        self.assertIsInstance(default_vid, int)
        print(f"[TEST 1 PASS] Connected to Global-Bazar DB. Vendor count: {len(vendors)}, Default Vendor ID: {default_vid}")

    def test_02_products_and_search(self):
        """Verifies products can be fetched and searched by title or SKU."""
        products = GlobalBazarService.get_products()
        self.assertIsInstance(products, list)
        self.assertGreater(len(products), 0, "Expected at least 1 product in inventory")

        first_p = products[0]
        # Test lookup by ID
        p_by_id = GlobalBazarService.get_product_by_id(first_p["id"])
        self.assertIsNotNone(p_by_id)
        self.assertEqual(p_by_id["title"], first_p["title"])

        # Test lookup by title
        search_res = GlobalBazarService.find_product_by_title_or_sku(first_p["title"])
        self.assertIsNotNone(search_res)
        self.assertEqual(search_res["id"], first_p["id"])
        print(f"[TEST 2 PASS] Loaded {len(products)} products. Search for '{first_p['title'][:15]}' succeeded.")

    def test_03_inventory_and_hisaab_messages(self):
        """Verifies WhatsApp formatted messages for !stock and !hisaab."""
        stock_msg = GlobalBazarService.get_inventory_whatsapp_message()
        self.assertIn("LIVE INVENTORY REPORT", stock_msg)
        self.assertIn("PKR", stock_msg)

        hisaab_msg = GlobalBazarService.get_hisaab_whatsapp_message()
        self.assertIn("DAILY HISAAB-KITAAB", hisaab_msg)
        self.assertIn("Total Sales", hisaab_msg)
        self.assertIn("Net Profit", hisaab_msg)
        print("[TEST 3 PASS] !stock and !hisaab WhatsApp messages format correctly with live data.")

    def test_04_catalog_data_ai_grounding(self):
        """Verifies that catalog_data injects Global-Bazar products into AI system prompt."""
        items = get_all_catalog_items()
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)

        context = get_default_catalog_context()
        self.assertIn("VERIFIED PRODUCT & SERVICE CATALOG", context)
        # Check that products from Global-Bazar appear in the context
        products = GlobalBazarService.get_products()
        if products:
            sample_title = products[0]["title"]
            self.assertIn(sample_title, context)
        print(f"[TEST 4 PASS] AI system prompt context generated with {len(items)} live items.")

    def test_05_whatsapp_merchant_commands_detection(self):
        """Verifies WhatsAppService recognizes !stock, !hisaab, !addstock, etc."""
        self.assertTrue(WhatsAppService.is_catalog_command("!stock"))
        self.assertTrue(WhatsAppService.is_catalog_command("!inventory"))
        self.assertTrue(WhatsAppService.is_catalog_command("/stock"))
        self.assertTrue(WhatsAppService.is_catalog_command("!hisaab"))
        self.assertTrue(WhatsAppService.is_catalog_command("!ledger"))
        self.assertTrue(WhatsAppService.is_catalog_command("!summary"))
        self.assertTrue(WhatsAppService.is_catalog_command("!addstock 1 10"))
        self.assertTrue(WhatsAppService.is_catalog_command("!updatestock 1 25"))
        self.assertTrue(WhatsAppService.is_catalog_command("#add Lawn Suit | 3500 | 15 | Apparel"))
        self.assertFalse(WhatsAppService.is_catalog_command("Salam, kya haal hai?"))
        print("[TEST 5 PASS] WhatsApp catalog and merchant command detection verified.")

    def test_06_whatsapp_catalog_command_execution(self):
        """Verifies handle_whatsapp_catalog_command executes !stock, !hisaab, and !addstock."""
        # Mock send_message to prevent network socket calls during test
        original_send = WhatsAppService.send_message
        WhatsAppService.send_message = classmethod(lambda cls, **kwargs: {"status": "success", "simulated": True})

        try:
            # 1. Test !stock execution
            res_stock = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-test",
                sender_phone="+923001234567",
                message_body="!stock"
            )
            self.assertIsNotNone(res_stock)
            self.assertTrue(res_stock.get("success"))
            self.assertEqual(res_stock.get("action"), "inventory_inquiry")
            self.assertIn("LIVE INVENTORY REPORT", res_stock.get("reply_body", ""))

            # 2. Test !hisaab execution
            res_hisaab = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-test",
                sender_phone="+923001234567",
                message_body="!hisaab"
            )
            self.assertIsNotNone(res_hisaab)
            self.assertTrue(res_hisaab.get("success"))
            self.assertEqual(res_hisaab.get("action"), "hisaab_summary")
            self.assertIn("DAILY HISAAB-KITAAB", res_hisaab.get("reply_body", ""))

            # 3. Test !addstock execution on first product
            products = GlobalBazarService.get_products()
            self.assertGreater(len(products), 0)
            p = products[0]
            initial_stock = p["stock"]

            res_stock_update = WhatsAppService.handle_whatsapp_catalog_command(
                organization_id="org-test",
                sender_phone="+923001234567",
                message_body=f"!addstock {p['id']} 5"
            )
            self.assertIsNotNone(res_stock_update)
            self.assertTrue(res_stock_update.get("success"))
            self.assertEqual(res_stock_update.get("action"), "stock_updated")

            refreshed_p = GlobalBazarService.get_product_by_id(p["id"])
            self.assertEqual(refreshed_p["stock"], initial_stock + 5)

            # Restore original stock
            GlobalBazarService.update_product_stock(p["id"], new_stock=initial_stock)
            print("[TEST 6 PASS] Merchant commands !stock, !hisaab, and !addstock handled and verified.")
        finally:
            WhatsAppService.send_message = original_send

    def test_07_end_to_end_order_stock_deduction_and_ledger(self):
        """Verifies process_whatsapp_order deducts stock, creates order, and records ledger sale."""
        products = GlobalBazarService.get_products()
        self.assertGreater(len(products), 0)
        p = products[0]

        # Ensure at least 10 units in stock for test
        GlobalBazarService.update_product_stock(p["id"], new_stock=25)
        stock_before = 25

        order_res = GlobalBazarService.process_whatsapp_order(
            customer_phone="+923009998877",
            customer_name="Ahmad Test Customer",
            product_identifier=p["id"],
            quantity=2,
            delivery_address="Gulberg III, Lahore"
        )

        self.assertTrue(order_res["success"], f"Order failed: {order_res}")
        self.assertEqual(order_res["new_stock"], stock_before - 2)

        # Check stock in DB
        p_after = GlobalBazarService.get_product_by_id(p["id"])
        self.assertEqual(p_after["stock"], stock_before - 2)

        # Check order recorded
        order_obj = order_res.get("order")
        self.assertIsNotNone(order_obj)
        self.assertEqual(order_obj["customer_phone"], "+923009998877")
        self.assertEqual(order_obj["order_source"], "whatsapp")

        # Check ledger sale was posted
        summary = GlobalBazarService.get_ledger_summary()
        self.assertGreaterEqual(summary["total_sales"], float(p["price"] * 2))
        print(f"[TEST 7 PASS] End-to-end order processing succeeded! Stock {stock_before} -> {p_after['stock']}, Sale logged: PKR {order_res['total_amount']:,.0f}")


if __name__ == "__main__":
    unittest.main()
