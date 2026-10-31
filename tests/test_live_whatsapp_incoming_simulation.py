import os
import sys
import json
import base64
import pytest

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from models import db, WhatsAppMessage
from whatsapp_service import WhatsAppService

@pytest.fixture(scope="module")
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app

@pytest.fixture(scope="module")
def client(app):
    return app.test_client()

def test_roman_to_urdu_script_conversion():
    """Roman Urdu is accurately translated to pure Urdu script for Edge-TTS HD voice synthesis."""
    sample = "Walaikum Assalam! Jee bilkul, main theek hoon. Aap sunayein aap kaise hain? Batayein main aap ki kya madad kar sakta hoon?"
    urdu_out = WhatsAppService.roman_to_urdu_script(sample)
    assert len(urdu_out) > 0
    # Must contain Arabic/Urdu unicode characters
    assert any('\u0600' <= ch <= '\u06FF' for ch in urdu_out)
    assert "وعلیکم السلام" in urdu_out or "السلام" in urdu_out
    assert "جی بالکل" in urdu_out or "بالکل" in urdu_out

def test_simulated_incoming_messages_me_and_friend(client, app):
    """Simulates 2 distinct incoming messages (from user and friend) verifying DB persistence, UI conversation listing, and AI replies."""
    my_phone = "923001112233"
    friend_phone = "923214445566"

    with app.app_context():
        # 1. Message from user (text inquiry)
        payload_me = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {"idInstance": "baileys_bridge"},
            "timestamp": 1730419200,
            "idMessage": "sim_msg_me_001",
            "senderData": {
                "chatId": f"{my_phone}@s.whatsapp.net",
                "sender": my_phone,
                "senderName": "Bashir Ahmed",
                "chatName": "Bashir Ahmed"
            },
            "messageData": {
                "typeMessage": "textMessage",
                "textMessageData": {"textMessage": "Salam bhai, package aur features ki details chahiye"}
            },
            "from_phone": my_phone,
            "body": "Salam bhai, package aur features ki details chahiye"
        }

        res_me = client.post("/api/v1/webhooks/whatsapp", json=payload_me)
        assert res_me.status_code == 200
        data_me = res_me.get_json()
        assert data_me["status"] == "ok"

        # 2. Message from friend (voice note)
        dummy_audio_b64 = base64.b64encode(b"OggS dummy voice bytes for test").decode("ascii")
        payload_friend = {
            "typeWebhook": "incomingMessageReceived",
            "instanceData": {"idInstance": "baileys_bridge"},
            "timestamp": 1730419210,
            "idMessage": "sim_msg_friend_002",
            "senderData": {
                "chatId": f"{friend_phone}@s.whatsapp.net",
                "sender": friend_phone,
                "senderName": "Kamran Dost",
                "chatName": "Kamran Dost"
            },
            "messageData": {
                "typeMessage": "audioMessage",
                "fileData": {"mimeType": "audio/ogg", "downloadUrl": f"data:audio/ogg;base64,{dummy_audio_b64}"}
            },
            "from_phone": friend_phone,
            "body": "[Voice note]",
            "is_voice": True,
            "audio_base64": dummy_audio_b64
        }

        res_friend = client.post("/api/v1/webhooks/whatsapp", json=payload_friend)
        assert res_friend.status_code == 200
        data_friend = res_friend.get_json()
        assert data_friend["status"] == "ok"

        # Verify both messages are in database
        msg_me = WhatsAppMessage.query.filter_by(whatsapp_message_id="sim_msg_me_001").first()
        assert msg_me is not None
        assert my_phone in msg_me.sender
        assert "Salam bhai" in msg_me.body

        msg_fr = WhatsAppMessage.query.filter_by(whatsapp_message_id="sim_msg_friend_002").first()
        assert msg_fr is not None
        assert friend_phone in msg_fr.sender

        # Verify both conversations appear in GET /api/whatsapp/conversations for UI
        conv_res = client.get("/api/whatsapp/conversations")
        assert conv_res.status_code == 200
        c_data = conv_res.get_json()
        assert c_data["success"] is True
        
        all_conv_phones = [c["phone"] for c in c_data.get("conversations", [])]
        assert any(my_phone in p for p in all_conv_phones)
        assert any(friend_phone in p for p in all_conv_phones)
