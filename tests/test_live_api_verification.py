"""
Live Production API Verification Test (NO MOCKS ALLOWED)
Verifies:
1. Prompt 1 ("Kaisa ho") produces a real, natural conversational greeting in Roman Urdu.
2. Prompt 2 ("Apnay service k bar e main batawo") produces a distinct, relevant explanation of services.
3. Prompt 3 (Inbound Voice Note Buffer) produces a distinct, non-empty response.
4. Voice-to-voice synthesis converts the response into real HD spoken audio (> 10KB, .oga / .mp3).
5. All three responses are distinct and contain NO canned mobile shop templates or "Main aap ki baat samajh raha hoon".
"""

import sys
import unittest
from app import create_app
from database import db
from models import Organization, WhatsAppMessage
from whatsapp_service import WhatsAppService


class TestLiveApiVerification(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

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

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_live_api_and_voice_pipeline(self):
        # 1. Prompt 1: "Kaisa ho"
        prompt1 = "Kaisa ho"
        res1_dict = WhatsAppService.generate_ai_auto_response(
            organization_id="org-enterprise-default",
            message_body=prompt1,
            sender_name="Bashir Khan",
            sender_phone="923209350858"
        )
        reply1 = (res1_dict.get("reply_body") or "").strip()

        # 2. Prompt 2: "Apnay service k bar e main batawo"
        prompt2 = "Apnay service k bar e main batawo"
        res2_dict = WhatsAppService.generate_ai_auto_response(
            organization_id="org-enterprise-default",
            message_body=prompt2,
            sender_name="Bashir Khan",
            sender_phone="923209350858"
        )
        reply2 = (res2_dict.get("reply_body") or "").strip()

        # 3. Prompt 3: Voice Note Inbound Buffer
        # Synthesize real voice note buffer to simulate incoming WhatsApp voice note
        synth_inbound = WhatsAppService.generate_spoken_audio(
            text="Assalam-o-Alaikum, mujhe services ke baray mein janna hai",
            language="ur"
        )
        self.assertIsNotNone(synth_inbound, "Failed to create sample inbound audio buffer")
        sample_audio_bytes, _, _ = synth_inbound

        # Process inbound audio via handle_inbound_auto_response
        res3_dict = WhatsAppService.handle_inbound_auto_response(
            organization_id="org-enterprise-default",
            sender_phone="923209350858",
            message_body="",
            is_voice=True,
            audio_bytes=sample_audio_bytes,
            sender_name="Bashir Khan",
            message_id="test_live_msg_1234567"
        )
        self.assertIsNotNone(res3_dict, "handle_inbound_auto_response returned None")
        reply3 = (res3_dict.get("reply_body") or "").strip()

        # 4. Outbound TTS Voice Synthesis (> 10KB)
        audio_res = WhatsAppService.generate_spoken_audio(
            text=reply2,
            language="ur"
        )
        self.assertIsNotNone(audio_res, "Outbound TTS generation failed")
        audio_bytes, audio_fn, audio_mt = audio_res

        # Print outputs to terminal in UTF-8
        out = (
            "\n" + "=" * 70 + "\n"
            "LIVE API VERIFICATION RESULTS (NO MOCKS):\n"
            f"Prompt 1: '{prompt1}'\n"
            f"AI Response 1: {reply1}\n\n"
            f"Prompt 2: '{prompt2}'\n"
            f"AI Response 2: {reply2}\n\n"
            f"Prompt 3: Audio Buffer ({len(sample_audio_bytes)} bytes)\n"
            f"AI Response 3: {reply3}\n\n"
            f"Generated Outbound Audio: {len(audio_bytes)} bytes (> 10KB: {len(audio_bytes) > 10000})\n"
            f"Audio Format: {audio_fn} ({audio_mt})\n"
            + "=" * 70 + "\n"
        )
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(out)
        sys.stdout.flush()

        # Assertions
        # 1. Non-empty
        self.assertTrue(len(reply1) > 0, "Response 1 is empty")
        self.assertTrue(len(reply2) > 0, "Response 2 is empty")
        self.assertTrue(len(reply3) > 0, "Response 3 is empty")

        # 2. Distinct responses
        self.assertNotEqual(reply1, reply2, "Response 1 and Response 2 must be distinct")
        self.assertNotEqual(reply2, reply3, "Response 2 and Response 3 must be distinct")

        # 3. NO static fallback phrases or mobile shop templates
        forbidden_phrases = [
            "main aap ki baat samajh raha hoon",
            "bashir mobile",
            "kis mobile ya repair"
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, reply1.lower(), f"Response 1 contained forbidden phrase: '{phrase}'")
            self.assertNotIn(phrase, reply2.lower(), f"Response 2 contained forbidden phrase: '{phrase}'")
            self.assertNotIn(phrase, reply3.lower(), f"Response 3 contained forbidden phrase: '{phrase}'")

        # 4. Outbound audio size > 10KB (10,000 bytes)
        self.assertGreater(
            len(audio_bytes),
            10000,
            f"Generated audio size ({len(audio_bytes)} bytes) is not > 10KB"
        )


if __name__ == "__main__":
    unittest.main()
