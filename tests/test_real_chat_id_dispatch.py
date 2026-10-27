import unittest
from unittest.mock import patch
from whatsapp_service import WhatsAppService


class TestRealChatIdDispatch(unittest.TestCase):
    def test_real_chat_id_resolution_and_active_green_api_payload(self):
        """Verifies Green API payload chatId matches real WhatsApp chat ID and disables simulator fallback."""
        with patch("requests.Session.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"idMessage": "REAL_WA_MSG_001"}'
            mock_post.return_value.json.return_value = {"idMessage": "REAL_WA_MSG_001"}

            res = WhatsAppService.send_green_api_message(
                to_phone="03209350858",
                chat_id="923209350858@s.whatsapp.net",
                message_text="Hello WhatsApp Chat",
                allow_fallback=False
            )
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("chat_id"), "923209350858@s.whatsapp.net")
            post_json = mock_post.call_args[1]["json"]
            self.assertEqual(post_json.get("chatId"), "923209350858@s.whatsapp.net")

    def test_inbound_auto_response_routes_real_chat_id_without_fallback(self):
        """Verifies handle_inbound_auto_response routes real chat ID to text and voice dispatchers without fallback."""
        WhatsAppService.clear_in_flight_phones()
        WhatsAppService.clear_recent_replied_trigger_ids()
        with patch.object(WhatsAppService, "get_gemini_api_key", return_value="fake-key"), \
             patch.object(WhatsAppService, "call_gemini_ai", return_value="Salam! Real chat response."), \
             patch.object(WhatsAppService, "generate_spoken_audio", return_value=(b"audio_bytes", "voice_reply.oga", "audio/ogg")), \
             patch.object(WhatsAppService, "send_green_api_file", return_value={"success": True, "whatsapp_message_id": "REAL_VOICE_001"}) as mock_send_file, \
             patch.object(WhatsAppService, "send_green_api_message", return_value={"success": True, "whatsapp_message_id": "REAL_AI_001"}) as mock_send_green:

            res2 = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="03209350858",
                chat_id="923209350858@s.whatsapp.net",
                message_body="What are your service rates?",
                message_id="MSG_IN_999"
            )
            self.assertTrue(res2.get("success"))
            self.assertTrue(mock_send_green.called)
            call_kwargs = mock_send_green.call_args[1]
            self.assertEqual(call_kwargs.get("chat_id"), "923209350858@s.whatsapp.net")
            self.assertFalse(call_kwargs.get("allow_fallback"))

            self.assertTrue(mock_send_file.called)
            file_kwargs = mock_send_file.call_args[1]
            self.assertEqual(file_kwargs.get("chat_id"), "923209350858@s.whatsapp.net")
            self.assertFalse(file_kwargs.get("allow_fallback"))


if __name__ == "__main__":
    unittest.main()
