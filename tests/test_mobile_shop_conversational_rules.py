import unittest
from whatsapp_service import WhatsAppService


class TestMobileShopConversationalRules(unittest.TestCase):
    def test_casual_greeting_with_name(self):
        """Casual greeting like 'Kaisa ho AP sir' returns natural Roman Urdu shop assistant reply."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Kaisa ho AP sir",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        print("\n[Greeting Reply]:", reply)
        self.assertIn("Alhamdulillah main theek hoon Bashir bhai", reply)
        self.assertIn("Bataiye, dukan ke liye kis cheez ki maloomat chahiye ya koi mobile repair/stock ka masla hai?", reply)
        self.assertNotIn("BashFlow Cloud", reply)
        self.assertNotIn("Enterprise", reply)

    def test_salam_greeting(self):
        """'Salam' returns friendly conversational shop assistant reply."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Salam",
            lang_fmt="roman_urdu",
            sender_name="Bashir"
        )
        print("\n[Salam Reply]:", reply)
        self.assertIn("Alhamdulillah main theek hoon Bashir bhai", reply)

    def test_mobile_repair_question_no_software_packages(self):
        """Repair questions return repair details, NOT software pricing packages ($29, $99, etc.)."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Display screen aur battery repair ka kitna rate hai?",
            lang_fmt="roman_urdu",
            sender_name="Ali"
        )
        print("\n[Repair Reply]:", reply)
        self.assertIn("display screen", reply.lower())
        self.assertIn("battery", reply.lower())
        self.assertNotIn("$29", reply)
        self.assertNotIn("$99", reply)
        self.assertNotIn("Starter Plan", reply)
        self.assertNotIn("BashFlow Cloud", reply)

    def test_accessories_question(self):
        """Accessories questions return accessories stock details."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Original fast charger aur airpods dastiyab hain?",
            lang_fmt="roman_urdu",
            sender_name="Hamza"
        )
        print("\n[Accessories Reply]:", reply)
        self.assertIn("charger", reply.lower())
        self.assertIn("airpod", reply.lower())
        self.assertNotIn("BashFlow Cloud", reply)

    def test_phone_stock_and_rate_question(self):
        """Phone stock/rate questions discuss phones, NOT software packages."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="iPhone 13 PTA approved available hai price kya hai?",
            lang_fmt="roman_urdu",
            sender_name="Kashif"
        )
        print("\n[Stock Reply]:", reply)
        self.assertIn("iphone", reply.lower())
        self.assertNotIn("$29", reply)
        self.assertNotIn("BashFlow Cloud", reply)

    def test_imei_tracking_question(self):
        """IMEI questions return 15-digit IMEI tracking details."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="IMEI number kaise save hoga mobile ka",
            lang_fmt="roman_urdu"
        )
        print("\n[IMEI Reply]:", reply)
        self.assertIn("imei", reply.lower())
        self.assertIn("15-digit", reply.lower())
        self.assertNotIn("BashFlow Cloud", reply)

    def test_jazzcash_question(self):
        """JazzCash questions provide account 03209350858 and title Bashir Uddin."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="JazzCash par payment karni hai",
            lang_fmt="roman_urdu"
        )
        print("\n[JazzCash Reply]:", reply)
        self.assertIn("03209350858", reply)
        self.assertIn("Bashir Uddin", reply)

    def test_software_pricing_only_when_explicitly_asked(self):
        """Software pricing packages are ONLY returned when customer explicitly asks about software/bot plans."""
        reply = WhatsAppService.generate_smart_conversational_fallback(
            message_body="Dukan ke liye WhatsApp software bot package aur rate batao",
            lang_fmt="roman_urdu"
        )
        print("\n[Software Price Reply]:", reply)
        self.assertIn("Starter Plan", reply)
        self.assertIn("Professional Plan", reply)
        self.assertIn("03209350858", reply)


if __name__ == "__main__":
    unittest.main()
