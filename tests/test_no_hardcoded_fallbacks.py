"""
Architectural Verification Test: NO HARDCODED FALLBACKS ALLOWED
Verifies:
1. Absence of static hardcoded pricing packages ("Starter Plan PKR 7,500", "Pro Plan PKR 25,000", "JazzCash 03209350858 Bashir Uddin") in conversational fallbacks.
2. Complete elimination of mobile shop / repair canned strings across general inquiries.
3. Multi-tier dynamic LLM fallback architecture (Gemini -> Groq -> OpenAI -> Pollinations AI).
4. Dynamic AI call event response in wa_bridge.js rather than static rejection text.
"""

import os
import unittest
from app import create_app, get_gemini_ai_response
from database import db
from models import Organization
from whatsapp_service import WhatsAppService

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestNoHardcodedFallbacks(unittest.TestCase):

    def setUp(self):
        self.app = create_app("testing")
        self.app_context = self.app.app_context()
        self.app_context.push()

        org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not org:
            org = Organization(
                id="org-enterprise-default",
                name="BashFlow Enterprise",
                slug="default",
                plan_tier="enterprise"
            )
            db.session.add(org)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_01_conversational_fallback_contains_no_hardcoded_packages(self):
        """Verifies conversational fallback contains zero hardcoded pricing packages or JazzCash account strings."""
        test_queries = [
            "Kaise ho ap",
            "Aap kya kaam karte ho",
            "Software lena hai",
            "Pricing kya hai",
            "Payment kaise karni hai",
            "AI kya hai aur automation kaise hoti hai?",
            "Weather kaisa hai aaj?"
        ]

        forbidden_snippets = [
            "starter plan: pkr 7,500",
            "professional plan: pkr 25,000",
            "jazzcash (03209350858",
            "title: bashir uddin",
            "2-day free trial bilkul muft",
            "bashir mobile",
            "telecom",
            "kis mobile ya repair"
        ]

        for q in test_queries:
            reply = WhatsAppService.generate_smart_conversational_fallback(
                message_body=q,
                lang_fmt="roman_urdu",
                sender_name="Ahmed"
            )
            self.assertIsNotNone(reply)
            self.assertGreater(len(reply.strip()), 10)
            reply_lower = reply.lower()
            for forbidden in forbidden_snippets:
                self.assertNotIn(
                    forbidden,
                    reply_lower,
                    f"Query '{q}' produced forbidden hardcoded fallback string '{forbidden}':\n{reply}"
                )

    def test_02_wa_bridge_contains_no_hardcoded_call_reject_string(self):
        """Verifies wa_bridge.js dynamically queries the backend AI rather than using static hardcoded reject messages."""
        bridge_path = os.path.join(REPO_DIR, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            js = f.read()

        # Hardcoded static reject message must NOT be in wa_bridge.js
        self.assertNotIn(
            'const autoRejectMessage = process.env.CALL_REJECT_MESSAGE || "Assalam-o-Alaikum! Aap ki voice call receive nahi ho saki',
            js
        )
        self.assertNotIn(
            'const voiceMsgText = "Assalam-o-Alaikum! Aap ki voice call receive nahi ho saki.',
            js
        )
        # Must contain dynamic AI voice chat fetch for calls
        self.assertIn("/api/v1/voice/chat", js)
        self.assertIn("[Incoming WhatsApp Voice Call", js)

    def test_03_multi_tier_ai_pipeline_methods(self):
        """Verifies WhatsAppService defines all multi-tiered dynamic LLM methods."""
        self.assertTrue(hasattr(WhatsAppService, "call_gemini_ai"))
        self.assertTrue(hasattr(WhatsAppService, "call_groq_ai"))
        self.assertTrue(hasattr(WhatsAppService, "call_openai_ai"))
        self.assertTrue(hasattr(WhatsAppService, "call_pollinations_ai"))
        self.assertTrue(hasattr(WhatsAppService, "generate_smart_conversational_fallback"))

    def test_04_app_get_gemini_ai_response_never_returns_static_failure_note(self):
        """Verifies get_gemini_ai_response in app.py resolves dynamically across the tiered architecture."""
        res = get_gemini_ai_response("Kaise ho ap")
        self.assertIsNotNone(res)
        self.assertNotIn("API Key is missing", res)
        self.assertNotIn("generation failed", res)
        self.assertTrue(len(res.strip()) > 5)


if __name__ == "__main__":
    unittest.main()
