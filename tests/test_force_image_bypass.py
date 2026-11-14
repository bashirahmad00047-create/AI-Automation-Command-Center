import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from whatsapp_service import WhatsAppService
from services.ai_responder import construct_gemini_prompt

class TestForceImageBypass(unittest.TestCase):
    def test_1_force_dispatch_auto_responder_bypass(self):
        res1 = WhatsAppService.force_dispatch_auto_responder(
            organization_id='org-enterprise-default',
            sender_phone='03129988771',
            message_body='add rs 150',
            is_image=True,
            download_url='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
            sender_name='Shahi Bazar Vendor'
        )
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get('action'), 'ai_catalog_product_added')
        self.assertIn('Product Successfully Added to Chitral & Global Bazar!', res1.get('reply_body', ''))
        print('[CHECK 1 PASS] force_dispatch_auto_responder successfully bypassed LLM and returned product added confirmation!')

    def test_2_handle_inbound_message_bypass(self):
        res2 = WhatsAppService.handle_inbound_message(
            organization_id='org-enterprise-default',
            sender_phone='03129988771',
            message_body='add rs 150',
            is_image=True,
            download_url='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
            sender_name='Shahi Bazar Vendor'
        )
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get('action'), 'ai_catalog_product_added')
        print('[CHECK 2 PASS] handle_inbound_message successfully bypassed LLM!')

    def test_3_prompt_restriction(self):
        prompt = construct_gemini_prompt('Add Pure Chitrali Chugha for 5000')
        expected_rule = "CRITICAL RULE: You CANNOT add products. If a user tries to add an item via text, tell them STRICTLY to attach a photo with the caption 'Add Rs [price]'. Do not ever claim a product was added."
        self.assertIn(expected_rule, prompt)
        print('[CHECK 3 PASS] AI prompt restriction correctly embedded in services/ai_responder.py!')

    def test_4_text_price_keywords_without_image(self):
        # 4a: "rs 160" without image
        res_a = WhatsAppService.force_dispatch_auto_responder(
            organization_id='org-enterprise-default',
            sender_phone='03129988771',
            message_body='rs 160',
            is_image=False,
            sender_name='Shahi Bazar Vendor'
        )
        self.assertIsNotNone(res_a)
        self.assertEqual(res_a.get('action'), 'missing_image_warning')
        self.assertIn("Item add karne ke liye tasveer attach karna lazmi hai", res_a.get('reply_body', ''))

        # 4b: "add 150" without image
        res_b = WhatsAppService.force_dispatch_auto_responder(
            organization_id='org-enterprise-default',
            sender_phone='03129988771',
            message_body='add 150',
            is_image=False,
            sender_name='Shahi Bazar Vendor'
        )
        self.assertIsNotNone(res_b)
        self.assertEqual(res_b.get('action'), 'missing_image_warning')
        self.assertIn("Item add karne ke liye tasveer attach karna lazmi hai", res_b.get('reply_body', ''))
        print('[CHECK 4 PASS] Text price keywords without image successfully intercepted with warning!')

    def test_5_meri_dukan_magic_link_top_bypass(self):
        res = WhatsAppService.force_dispatch_auto_responder(
            organization_id='org-enterprise-default',
            sender_phone='03129988771',
            message_body='meri dukan',
            sender_name='Shahi Bazar Vendor'
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get('action'), 'vendor_magic_link')
        self.assertIn("Aapki Online Dukaan Tayyar Hai!", res.get('reply_body', ''))
        self.assertIn("http://66.45.230.232:5000/vendor/auth/", res.get('reply_body', ''))
        print('[CHECK 5 PASS] meri dukan command successfully generated magic link at top level!')

if __name__ == '__main__':
    unittest.main()
