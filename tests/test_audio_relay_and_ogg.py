import unittest
import os
import re

class TestAudioRelayAndOgg(unittest.TestCase):
    def setUp(self):
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_whatsapp_service_convert_mp3_to_ogg_opus(self):
        from whatsapp_service import WhatsAppService
        self.assertTrue(hasattr(WhatsAppService, "convert_mp3_to_ogg_opus"))
        self.assertIsNone(WhatsAppService.convert_mp3_to_ogg_opus(b""))
        self.assertIsNone(WhatsAppService.convert_mp3_to_ogg_opus(None))
        # Preserves buffer if already OggS
        mock_ogg = b"OggS\x00\x02\x00\x00" + b"A" * 100
        self.assertEqual(WhatsAppService.convert_mp3_to_ogg_opus(mock_ogg), mock_ogg)

    def test_wa_bridge_ffmpeg_parameters(self):
        bridge_path = os.path.join(self.repo_dir, "wa_bridge.js")
        with open(bridge_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Check ffmpeg Opus voip flags
        self.assertIn("-b:a", code)
        self.assertIn("24k", code)
        self.assertIn("-application", code)
        self.assertIn("voip", code)
        self.assertIn("-ar", code)
        self.assertIn("48000", code)
        self.assertIn("-ac", code)
        self.assertIn("1", code)
        self.assertIn("OggS", code)

        # Check fallback to audio/mpeg or audio/mp4 if not OggS
        self.assertIn("audio/mpeg", code)
        self.assertIn("audio/mp4", code)

    def test_api_v1_audio_relay(self):
        api_path = os.path.join(self.repo_dir, "api_v1.py")
        with open(api_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("to_admin_queue", code)
        self.assertIn("customer_audio_base64", code)
        self.assertIn("live-call-chunk", code)
        self.assertIn("clean_call_phone", code)

    def test_static_app_js_queue_relay(self):
        app_js_path = os.path.join(self.repo_dir, "static", "js", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("processAdminAudioQueue", code)
        self.assertIn("📞 Live Call: Customer Speaking...", code)
        self.assertIn("🤖 Live Call: AI Responding...", code)
        # Ensure queue is not wiped on window.isAiSpeaking
        self.assertNotIn("if (window.isAiSpeaking || window.isLiveAiSpeaking || window.location.pathname.includes('/call/'))", code)

    def test_live_call_room_customer_audio(self):
        room_path = os.path.join(self.repo_dir, "templates", "live_call_room.html")
        with open(room_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("customer_audio_base64", code)
        self.assertIn("mediaRecorder.start(200)", code)

if __name__ == "__main__":
    unittest.main()
