"""
Test Suite: WhatsApp Image Interception & AI Inventory Auto-Cataloging
Verifies:
1. Detection of images with inventory captions ('add', 'sell', 'price', 'rs', numeric).
2. Price extraction from inventory captions.
3. Execution of handle_whatsapp_inventory_image and local FastAPI engine fallback.
4. Exact WhatsApp success message formatting for Chitral & Global Bazar.
5. Inbound message pipeline interception.
Strictly executed on local files.
"""

import os
import sys
import unittest
import io
from PIL import Image, ImageDraw

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from whatsapp_service import WhatsAppService
from services.global_bazar_service import GlobalBazarService


class TestImageCatalogInterception(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create a sample synthetic PNG image for test
        img = Image.new("RGB", (200, 200), color=(240, 240, 240))
        d = ImageDraw.Draw(img)
        d.rectangle([40, 40, 160, 160], fill=(220, 30, 70))
        d.text((60, 95), "Chitral Shawl", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        cls.sample_image_bytes = buf.getvalue()

    def test_01_is_image_message_detection(self):
        """Verifies detection of image payloads."""
        self.assertTrue(WhatsAppService.is_image_message(is_image=True))
        self.assertTrue(WhatsAppService.is_image_message(media_type="image"))
        self.assertTrue(WhatsAppService.is_image_message(type="imageMessage"))
        self.assertTrue(WhatsAppService.is_image_message(download_url="https://example.com/photo.jpg"))
        self.assertTrue(WhatsAppService.is_image_message(download_url="data:image/png;base64,iVBORw0KGgoAAA=="))
        self.assertTrue(WhatsAppService.is_image_message(text="[photo]"))
        self.assertFalse(WhatsAppService.is_image_message(text="Salam bhai"))
        print("[TEST 1 PASS] Image message payload detection verified.")

    def test_02_is_inventory_caption_detection(self):
        """Verifies detection of inventory keywords and numeric captions."""
        # Keyword triggers
        self.assertTrue(WhatsAppService.is_inventory_caption("Add this kurta Rs 2500"))
        self.assertTrue(WhatsAppService.is_inventory_caption("Sell for 1800"))
        self.assertTrue(WhatsAppService.is_inventory_caption("price 3500"))
        self.assertTrue(WhatsAppService.is_inventory_caption("rs 2200"))
        self.assertTrue(WhatsAppService.is_inventory_caption("add"))
        self.assertTrue(WhatsAppService.is_inventory_caption("sell"))
        self.assertTrue(WhatsAppService.is_inventory_caption("price"))
        self.assertTrue(WhatsAppService.is_inventory_caption("rs"))

        # Pure numeric triggers
        self.assertTrue(WhatsAppService.is_inventory_caption("2500"))
        self.assertTrue(WhatsAppService.is_inventory_caption("2,850"))
        self.assertTrue(WhatsAppService.is_inventory_caption("3500/-"))
        self.assertTrue(WhatsAppService.is_inventory_caption("1500.00"))

        # Non-inventory captions
        self.assertFalse(WhatsAppService.is_inventory_caption("Salam kaisay hain aap?"))
        self.assertFalse(WhatsAppService.is_inventory_caption("Kahan ho bhai"))
        self.assertFalse(WhatsAppService.is_inventory_caption("[image]"))
        print("[TEST 2 PASS] Inventory caption detection verified across all keyword and numeric patterns.")

    def test_03_extract_inventory_price(self):
        """Verifies price extraction from diverse caption styles."""
        self.assertEqual(WhatsAppService.extract_inventory_price("Add kurta Rs. 2,850 only"), 2850.0)
        self.assertEqual(WhatsAppService.extract_inventory_price("Sell for 1800"), 1800.0)
        self.assertEqual(WhatsAppService.extract_inventory_price("Price: 3500/-"), 3500.0)
        self.assertEqual(WhatsAppService.extract_inventory_price("2500"), 2500.0)
        self.assertEqual(WhatsAppService.extract_inventory_price("Rs 4500"), 4500.0)
        self.assertIsNone(WhatsAppService.extract_inventory_price("Add this item"))
        print("[TEST 3 PASS] Price extraction verified.")

    def test_04_handle_whatsapp_inventory_image_direct(self):
        """Verifies handle_whatsapp_inventory_image creates product and formats the exact WhatsApp response."""
        # Mock send_message to prevent Baileys network call during test
        orig_send = WhatsAppService.send_message
        WhatsAppService.send_message = classmethod(lambda cls, **kwargs: {"status": "success", "simulated": True})

        try:
            caption = "Add Handwoven Chitrali Wool Shawl Rs 6,500"
            res = WhatsAppService.handle_whatsapp_inventory_image(
                organization_id="org-test",
                sender_phone="+923007654321",
                message_body=caption,
                image_bytes=self.sample_image_bytes
            )

            self.assertIsNotNone(res)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "ai_catalog_product_added")

            title = res.get("title")
            description = res.get("description")
            estimated_price = res.get("estimated_price")

            self.assertIsNotNone(title)
            self.assertIsNotNone(description)
            self.assertIsNotNone(estimated_price)
            self.assertEqual(estimated_price, 6500.0)

            reply_msg = res.get("reply_body")
            expected_format = (
                f" *Product Successfully Added to Chitral & Global Bazar!*\n\n"
                f"*Title:* {title}\n"
                f"*Description:* {description}\n"
                f"*Listed Price:* {estimated_price}\n\n"
                f"Your perfectly edited product is now live on the store!"
            )

            self.assertEqual(reply_msg, expected_format)
            self.assertIn("*Product Successfully Added to Chitral & Global Bazar!*", reply_msg)
            self.assertIn(f"*Title:* {title}", reply_msg)
            self.assertIn(f"*Description:* {description}", reply_msg)
            self.assertIn(f"*Listed Price:* {estimated_price}", reply_msg)
            self.assertIn("Your perfectly edited product is now live on the store!", reply_msg)

            print(f"[TEST 4 PASS] Automated WhatsApp reply format verified exactly:\n{reply_msg}\n")
        finally:
            WhatsAppService.send_message = orig_send

    def test_05_inbound_pipeline_interception(self):
        """Verifies inbound message processing pipeline intercepts image with inventory caption."""
        orig_send = WhatsAppService.send_message
        WhatsAppService.send_message = classmethod(lambda cls, **kwargs: {"status": "success", "simulated": True})

        try:
            # Send message with image and numeric price caption "3200"
            res = WhatsAppService.handle_inbound_message(
                organization_id="org-test",
                sender_phone="+923001122334",
                message_body="Sell Silk Kurti 3200",
                is_image=True,
                image_bytes=self.sample_image_bytes
            )

            self.assertIsNotNone(res)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("action"), "ai_catalog_product_added")
            self.assertIn("*Product Successfully Added to Chitral & Global Bazar!*", res.get("reply_body", ""))
            self.assertEqual(res.get("estimated_price"), 3200.0)
            print("[TEST 5 PASS] Inbound pipeline successfully intercepted image with inventory caption!")
        finally:
            WhatsAppService.send_message = orig_send


if __name__ == "__main__":
    unittest.main()
