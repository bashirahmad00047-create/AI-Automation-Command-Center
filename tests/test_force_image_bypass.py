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

if __name__ == '__main__':
    unittest.main()
