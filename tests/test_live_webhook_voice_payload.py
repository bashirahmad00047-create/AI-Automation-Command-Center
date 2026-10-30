"""
Integration Test: Exact Webhook Payload With Real Audio Buffer
Tests the entire pipeline:
1. Constructs an authentic Baileys wa_bridge incoming voice note payload with a real audio buffer.
2. Posts directly to /api/v1/webhooks/whatsapp.
3. Verifies synchronous return of generated AI text and outbound speech audio_base64.
4. Asserts no canned fallbacks.
"""

import base64
import json
import time
import unittest
from app import create_app
from database import db
from models import Organization
from whatsapp_service import WhatsAppService


class TestLiveWebhookVoicePayload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        cls.app.config["RATELIMIT_ENABLED"] = False
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

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

        WhatsAppService.save_auto_responder_config(
            organization_id="org-enterprise-default",
            enabled=True,
            cooldown_minutes=0
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def test_exact_webhook_payload_with_real_audio(self):
        # 1. Synthesize real audio buffer for user voice note
        synth = WhatsAppService.generate_spoken_audio(
            text="Assalam-o-Alaikum, mujhe services aur packages ke baray mein janna hai",
            language="ur"
        )
        self.assertIsNotNone(synth, "Failed to synthesize inbound audio buffer")
        audio_bytes, audio_fn, audio_mt = synth
        self.assertTrue(len(audio_bytes) > 500, "Audio buffer is too small")

        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        audio_data_url = f"data:audio/ogg;base64,{audio_b64}"
        test_msg_id = f"BAE5TEST_{int(time.time() * 1000)}"
        sender_phone = "923461000420"
        remote_jid = f"{sender_phone}@s.whatsapp.net"

        # 2. Exact payload constructed by wa_bridge.js in messages.upsert
        exact_payload = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {
                "idInstance": "baileys_bridge",
                "wid": "bridge@c.us"
            },
            "timestamp": int(time.time()),
            "idMessage": test_msg_id,
            "senderData": {
                "chatId": remote_jid,
                "sender": sender_phone,
                "chatName": "Shahid Baigal",
                "senderName": "Shahid Baigal"
            },
            "messageData": {
                "typeMessage": "audio",
                "textMessageData": {
                    "textMessage": "[Voice note]"
                },
                "fileData": {
                    "downloadUrl": audio_data_url,
                    "mediaUrl": audio_data_url,
                    "audioUrl": audio_data_url,
                    "mimeType": "audio/ogg",
                    "duration": 3
                }
            },
            "chatId": remote_jid,
            "remoteJid": remote_jid,
            "from": sender_phone,
            "from_phone": sender_phone,
            "sender": sender_phone,
            "senderName": "Shahid Baigal",
            "isGroup": False,
            "message": "[Voice note]",
            "body": "[Voice note]",
            "type": "audio",
            "message_type": "audio",
            "mediaUrl": audio_data_url,
            "audioUrl": audio_data_url,
            "media_url": audio_data_url,
            "audio_url": audio_data_url,
            "downloadUrl": audio_data_url,
            "download_url": audio_data_url,
            "audio_base64": audio_b64,
            "audioBase64": audio_b64,
            "is_voice": True,
            "is_audio": True,
            "mimetype": "audio/ogg",
            "mime_type": "audio/ogg"
        }

        # 3. Post to /api/v1/webhooks/whatsapp
        resp = self.client.post(
            "/api/v1/webhooks/whatsapp",
            data=json.dumps(exact_payload),
            content_type="application/json",
            headers={"User-Agent": "WhatsApp-Baileys-Bridge/1.0"}
        )

        self.assertEqual(resp.status_code, 200, f"Webhook failed: {resp.data}")
        res_data = resp.get_json() or {}

        ai_reply_text = str(res_data.get("reply") or "").strip()
        outbound_audio_b64 = str(res_data.get("audio_base64") or "").strip()
        send_as_voice = res_data.get("send_as_voice")
        is_voice = res_data.get("is_voice")

        # 4. Print results
        print("\n" + "=" * 70)
        print("EXACT WEBHOOK INGRESS VERIFICATION WITH REAL AUDIO BUFFER:")
        print(f"Status Code: {resp.status_code}")
        print(f"Generated AI Text:\n{ai_reply_text}")
        print(f"audio_base64 Length: {len(outbound_audio_b64)} characters")
        print(f"send_as_voice: {send_as_voice}")
        print(f"is_voice: {is_voice}")
        print("=" * 70 + "\n")

        # 5. Assertions
        self.assertTrue(len(ai_reply_text) > 0, "Generated AI text must not be empty")
        self.assertTrue(len(outbound_audio_b64) > 100, "audio_base64 must contain valid speech bytes")
        self.assertTrue(send_as_voice, "send_as_voice must be True for voice notes")
        self.assertTrue(is_voice, "is_voice must be True")

        # Guarantee NO forbidden fallback strings
        lower_reply = ai_reply_text.lower()
        self.assertNotIn("voice note mil gaya", lower_reply)
        self.assertNotIn("main aap ki baat samajh raha hoon", lower_reply)
        self.assertNotIn("bashir mobile", lower_reply)


if __name__ == "__main__":
    unittest.main()
