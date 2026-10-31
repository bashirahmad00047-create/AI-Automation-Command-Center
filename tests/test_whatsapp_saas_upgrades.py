import os
import sys

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import json
from app import create_app
from models import db, WhatsAppMessage, Product, Lead, SystemSetting
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

def test_pairing_code_requires_phone(client):
    """Pairing code endpoint should return a friendly error message when phone is missing."""
    res = client.post("/api/v1/whatsapp/pairing-code", json={})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is False
    assert "Phone number is required" in data["message"]

def test_pairing_code_endpoint_active(client):
    """Pairing code endpoint forwards to Baileys bridge and guarantees HTTP 200 JSON."""
    res = client.post("/api/v1/whatsapp/pairing-code", json={"phone": "923001234567"})
    assert res.status_code == 200
    data = res.get_json()
    assert "status" in data
    assert "success" in data

def test_group_ai_default_off(client):
    """WhatsApp groups must have AI Auto-Responder disabled by default."""
    group_jid = "120363000000000001@g.us"
    res = client.get(f"/api/v1/whatsapp/groups/{group_jid}/ai-status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["ai_enabled"] is False

def test_group_ai_toggle(client):
    """Admins can explicitly toggle AI Auto-Responder ON and OFF for groups."""
    group_jid = "120363000000000002@g.us"
    
    # Toggle ON
    res_on = client.post(f"/api/v1/whatsapp/groups/{group_jid}/ai-toggle", json={"enabled": True})
    assert res_on.status_code == 200
    assert res_on.get_json()["ai_enabled"] is True

    # Verify status
    res_status = client.get(f"/api/v1/whatsapp/groups/{group_jid}/ai-status")
    assert res_status.get_json()["ai_enabled"] is True

    # Toggle OFF
    res_off = client.post(f"/api/v1/whatsapp/groups/{group_jid}/ai-toggle", json={"enabled": False})
    assert res_off.status_code == 200
    assert res_off.get_json()["ai_enabled"] is False

def test_group_message_isolation(app):
    """Group messages (@g.us) are classified separately from 1-on-1 chats."""
    with app.app_context():
        group_msg = WhatsAppMessage(
            id="test-msg-grp-1",
            organization_id="org-enterprise-default",
            whatsapp_message_id="wamid-grp-1",
            sender="923001112233@s.whatsapp.net",
            recipient="12036399999999@g.us",
            body="Salam to all group members",
            message_type="text"
        )
        d_grp = group_msg.to_dict()
        assert d_grp["is_group"] is True
        assert d_grp["chat_type"] == "group"

        individual_msg = WhatsAppMessage(
            id="test-msg-ind-1",
            organization_id="org-enterprise-default",
            whatsapp_message_id="wamid-ind-1",
            sender="923001112233@s.whatsapp.net",
            recipient="923214445566@s.whatsapp.net",
            body="Salam brother",
            message_type="text"
        )
        d_ind = individual_msg.to_dict()
        assert d_ind["is_group"] is False
        assert d_ind["chat_type"] == "individual"

def test_voice_chat_endpoint(client):
    """Live AI Voice Chat endpoint handles text queries and returns stats."""
    res = client.post("/api/v1/voice/chat", json={"message": "Salam, how can you help me?"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "reply_text" in data
    assert len(data["reply_text"]) > 0

def test_outbound_call_endpoint(client):
    """Direct Outbound Call endpoint initializes session and returns greeting."""
    res = client.post("/api/v1/voice/outbound-call", json={"phone_number": "+923001234567"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["phone"] == "923001234567"
    assert "greeting_text" in data

def test_product_catalog_context(app):
    """Product catalog grounding context provides real-time prices & stock to Gemini AI."""
    with app.app_context():
        # Ensure a test product exists
        prod = Product.query.filter_by(sku="TEST-SKU-001").first()
        if not prod:
            prod = Product(
                id="prod-test-001",
                organization_id="org-enterprise-default",
                sku="TEST-SKU-001",
                name="BashFlow Premium Automation",
                price=15000.0,
                currency="PKR",
                stock_quantity=50,
                is_active=True
            )
            db.session.add(prod)
            db.session.commit()

        context_str = WhatsAppService.get_product_catalog_context(organization_id="org-enterprise-default")
        assert "LIVE PRODUCT CATALOG & INVENTORY GROUNDING" in context_str
        assert "BashFlow Premium Automation" in context_str
        assert "PKR 15,000.00" in context_str

def test_whatsapp_qr_and_status_guarantee(client):
    """WhatsApp QR and status routes always return HTTP 200 without throwing 500."""
    res_qr = client.get("/api/v1/whatsapp/bridge-qr")
    assert res_qr.status_code == 200
    assert "status" in res_qr.get_json()

    res_status = client.get("/api/v1/whatsapp/status")
    assert res_status.status_code == 200
    assert "connected" in res_status.get_json() or "status" in res_status.get_json()


def test_conversational_tts_prosody_and_pauses(app):
    """Dual-script phonetic pipeline injects breath pauses (commas/ellipses) into conversational TTS scripts."""
    with app.app_context():
        long_urdu_text = "ہمارا سافٹ ویئر آپ کے تمام واٹس ایپ میسجز کو خودکار طریقے سے جواب دیتا ہے اور گاہکوں کو آرڈر تصدیق بھیجتا ہے"
        tuned = WhatsAppService._tune_conversational_tts_script(long_urdu_text)
        assert len(tuned) > 0
        # Check commas or pauses are injected
        assert "،" in tuned or "..." in tuned or "," in tuned

def test_urdu_voice_engine_system_prompt(app):
    """AI System prompt enforces ultra-human Pakistani Urdu tone, fillers, and bans archaic words."""
    with app.app_context():
        kb = WhatsAppService._get_tenant_or_global_knowledge_base("org-enterprise-default")
        assert isinstance(kb, str)
        assert "ULTRA-HUMAN PAKISTANI URDU VOICE ENGINE" in kb
        assert "Jee bilkul..." in kb
        assert "mutaddid" in kb  # in the ban instruction
        assert "CONVERSATIONAL MEMORY & NO REPETITION" in kb

def test_lid_and_resolved_phone_handling(app):
    """14-digit WhatsApp LID is properly mapped to resolved phone and pushName in message to_dict."""
    with app.app_context():
        lid_msg = WhatsAppMessage(
            id="test-msg-lid-1",
            organization_id="org-enterprise-default",
            whatsapp_message_id="wamid-lid-1",
            sender="91788283007142@lid",
            recipient="923001234567@s.whatsapp.net",
            body="Salam, I want to inquire about automation",
            message_type="text",
            raw_payload_json=json.dumps({
                "pushName": "Kamran Khan",
                "senderPn": "923219876543"
            })
        )
        d = lid_msg.to_dict()
        assert d["sender_name"] == "Kamran Khan"
        assert d["sender"] == "923219876543"
        assert d["resolved_phone"] == "923219876543"

def test_auto_ingest_crm_lead_name_extraction_and_order(app):
    """Customer name is extracted from message body and order intent upgrades lead status."""
    with app.app_context():
        phone = "923451122334"
        # First message introducing customer name
        lead_data = WhatsAppService.auto_ingest_crm_lead(
            organization_id="org-enterprise-default",
            from_phone=phone,
            sender_name=None,
            message_body="Mera naam Farhan Ahmed hai aur mujhe information chahiye"
        )
        assert lead_data is not None
        assert "Farhan Ahmed" in lead_data["name"]

        # Second message confirming order
        updated_lead = WhatsAppService.auto_ingest_crm_lead(
            organization_id="org-enterprise-default",
            from_phone=phone,
            message_body="Jee bilkul confirm kardo, mujhe suit buy karna hai"
        )
        assert updated_lead is not None
        assert updated_lead["intent"] == "PRODUCT_ORDER"
        assert updated_lead["status"] == "qualified"

def test_conversational_memory_default_limit(app):
    """WhatsAppService.get_conversation_history default limit is 10 for deep multi-turn memory."""
    with app.app_context():
        import inspect
        sig = inspect.signature(WhatsAppService.get_conversation_history)
        assert sig.parameters["limit"].default == 10


def test_whatsapp_conversations_endpoint(client):
    """GET /api/whatsapp/conversations returns live conversations grouped by partner."""
    res = client.get("/api/whatsapp/conversations")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "conversations" in data

def test_whatsapp_contacts_endpoint(client):
    """GET /api/whatsapp/contacts returns 1-on-1 contact list."""
    res = client.get("/api/whatsapp/contacts")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "contacts" in data

def test_whatsapp_groups_endpoint(client):
    """GET /api/whatsapp/groups returns group chats with AI toggle status."""
    res = client.get("/api/whatsapp/groups")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "groups" in data

def test_whatsapp_contacts_create_endpoint(client):
    """POST /api/whatsapp/contacts/create saves contact and seeds chat."""
    res = client.post("/api/whatsapp/contacts/create", json={
        "phone": "923119988776",
        "name": "Zubair Hashmi"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["contact"]["phone"] == "923119988776"

def test_whatsapp_groups_create_endpoint(client):
    """POST /api/whatsapp/groups/create creates a real WhatsApp group."""
    res = client.post("/api/whatsapp/groups/create", json={
        "subject": "BashFlow VIP Pakistan",
        "participants": ["923001234567"]
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "group_jid" in data
    assert "@g.us" in data["group_jid"]

def test_roman_to_urdu_script_conversion():
    """Roman Urdu is accurately translated to pure Urdu script for Edge-TTS HD voice synthesis."""
    from whatsapp_service import WhatsAppService
    sample = "Walaikum Assalam! Jee bilkul, main theek hoon. Aap sunayein aap kaise hain? Batayein main aap ki kya madad kar sakta hoon?"
    urdu_out = WhatsAppService.roman_to_urdu_script(sample)
    assert len(urdu_out) > 0
    assert any('\u0600' <= ch <= '\u06FF' for ch in urdu_out)
    assert "وعلیکم السلام" in urdu_out or "السلام" in urdu_out
    assert "جی بالکل" in urdu_out or "بالکل" in urdu_out

