import unittest
from whatsapp_service import WhatsAppService


class MobileShopContextAITestCase(unittest.TestCase):
    def test_mobile_shop_usage_inquiry(self):
        """Inquiries about mobile shop usage return detailed domain explanation in Roman Urdu."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Mara mobile shop k Liya Kaisa Kam karaga ya",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        self.assertIn("mobile shop", reply.lower())
        self.assertIn("repair", reply.lower())
        self.assertIn("imei", reply.lower())

    def test_imei_number_saving_and_tracking(self):
        """IMEI questions explain 15-digit IMEI database saving and warranty verification."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="imei number kaise save hoga mobile ka",
            lang_fmt="roman_urdu"
        )
        self.assertIn("imei", reply.lower())
        self.assertTrue("15-digit" in reply or "warranty" in reply)

    def test_mobile_repair_status_tracking(self):
        """Repair questions explain unique token number and automated pickup notification."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Customer mobile repair status kaise check karega?",
            lang_fmt="roman_urdu"
        )
        self.assertIn("repair", reply.lower())
        self.assertIn("token", reply.lower())

    def test_jazzcash_payment_details(self):
        """Payment inquiries provide exact JazzCash number and Bashir Uddin account title."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="JazzCash par payment karni hai details bata dein",
            lang_fmt="roman_urdu"
        )
        self.assertIn("03209350858", reply)
        self.assertIn("Bashir Uddin", reply)

    def test_anti_repetition_in_conversation(self):
        """Fallback engine never repeats the same message twice in the same conversation."""
        first_reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Mara mobile shop k Liya Kaisa Kam karaga ya",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        history = [
            {"role": "Customer", "content": "Mara mobile shop k Liya Kaisa Kam karaga ya"},
            {"role": "Assistant", "content": first_reply}
        ]
        second_reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Mara mobile shop k Liya Kaisa Kam karaga ya",
            lang_fmt="roman_urdu",
            sender_name="Bashir",
            conversation_history=history
        )
        self.assertNotEqual(first_reply, second_reply)
        self.assertNotIn(first_reply[:50], second_reply)


if __name__ == "__main__":
    unittest.main()
