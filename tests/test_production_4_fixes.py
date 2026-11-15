import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app import create_app
from services.global_bazar_service import GlobalBazarService
from services.ingress import parse_green_api_payload
from whatsapp_service import WhatsAppService


@pytest.fixture(scope="module")
def test_app():
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(test_app):
    return test_app.test_client()


# =============================================================================
# ISSUE 1: Fix Reply Going to Owner Instead of Friend/Sender
# =============================================================================
def test_ingress_preserves_third_party_jid_and_phone():
    """Verify parse_green_api_payload extracts exact third-party sender JID/phone without owner fallback."""
    raw_payload = {
        "typeWebhook": "incomingMessageReceived",
        "remoteJid": "447123456789@s.whatsapp.net",
        "senderData": {
            "chatId": "447123456789@s.whatsapp.net",
            "sender": "447123456789@s.whatsapp.net",
            "senderName": "Alice Smith"
        },
        "messageData": {
            "typeMessage": "textMessage",
            "textMessageData": {"textMessage": "Hello, how much is honey?"}
        }
    }
    messages = parse_green_api_payload(raw_payload)
    assert len(messages) == 1
    parsed = messages[0]
    assert parsed["from_phone"] == "447123456789"
    assert parsed["chat_id"] == "447123456789@s.whatsapp.net"
    assert parsed["sender_name"] == "Alice Smith"
    # Ensure it did NOT fall back to owner
    assert "923471000668" not in parsed["from_phone"]


def test_outbound_reply_targets_exact_sender_phone():
    """Verify WhatsAppService.send_message sends to the sender phone, never replacing it with owner."""
    with patch("requests.Session.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"success": True, "messageId": "msg_test_123"})
        mock_resp.json.return_value = {"success": True, "messageId": "msg_test_123"}
        mock_post.return_value = mock_resp

        res = WhatsAppService.send_message(
            organization_id="org-enterprise-default",
            to_phone="447123456789",
            message_text="Salam Alice, honey is PKR 2800.",
            chat_id="447123456789@s.whatsapp.net"
        )
        assert res.get("success") is True
        # Verify the outgoing payload to bridge
        called_args, called_kwargs = mock_post.call_args
        sent_body = called_kwargs.get("json") or {}
        assert sent_body.get("to") == "447123456789" or "447123456789" in sent_body.get("chatId", "")
        assert "923471000668" not in str(sent_body.get("to"))


# =============================================================================
# ISSUE 2: Lock Default Organization & Stop Fake "Scan QR Code" State
# =============================================================================
def test_bridge_status_reports_connected_when_any_session_active(client):
    """When another tenant session is active in the bridge, bridge-status returns connected."""
    mock_all_response = {
        "success": True,
        "bridge": "WhatsApp Baileys Multi-Tenant Bridge",
        "total_sessions": 2,
        "sessions": [
            {
                "tenant_id": "org-44",
                "connected": True,
                "genuinelyConnected": True,
                "phone": "923456789012",
                "user": {"id": "923456789012:1@s.whatsapp.net"}
            },
            {
                "tenant_id": "org-enterprise-default",
                "connected": False,
                "genuinelyConnected": False
            }
        ]
    }
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps(mock_all_response)
        mock_resp.json.return_value = mock_all_response
        mock_get.return_value = mock_resp

        res = client.get("/api/v1/whatsapp/bridge-status")
        assert res.status_code == 200
        data = res.get_json()
        assert data.get("connected") is True
        assert data.get("status") == "connected"
        assert data.get("active_org_id") == "org-44"


def test_bridge_qr_suppressed_when_session_active(client):
    """When a session is active, /api/v1/whatsapp/bridge-qr does not return a fake QR code."""
    mock_all_response = {
        "success": True,
        "bridge": "WhatsApp Baileys Multi-Tenant Bridge",
        "sessions": [
            {
                "tenant_id": "org-44",
                "connected": True,
                "genuinelyConnected": True,
                "phone": "923456789012"
            }
        ]
    }
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps(mock_all_response)
        mock_resp.json.return_value = mock_all_response
        mock_get.return_value = mock_resp

        res = client.get("/api/v1/whatsapp/bridge-qr?org_id=org-enterprise-default")
        assert res.status_code == 200
        data = res.get_json()
        assert data.get("connected") is True
        assert data.get("qr") is None
        assert data.get("active_org_id") == "org-44"


# =============================================================================
# ISSUE 3: Vendor Hisab-Kitab Summary & Endpoints
# =============================================================================
def test_format_vendor_hisab_summary_output():
    """Verify format_vendor_hisab_summary generates all 5 required elements."""
    summary = GlobalBazarService.format_vendor_hisab_summary(vendor_id=1, token="test_token_xyz")
    assert "Dukan:" in summary
    assert "Total Saman (Inventory):" in summary
    assert "Aaj Ki Sale (Daily Sale):" in summary
    assert "Mahine Ki Sale (Monthly Sale):" in summary
    assert "Dukan & Khata Dashboard Link:" in summary
    assert "http://66.45.230.232:5000/vendor/auth/test_token_xyz" in summary


def test_hisab_triggers_in_whatsapp_service():
    """Verify that hisab/sale/inventory commands trigger hisab summary reply."""
    with patch.object(WhatsAppService, "send_message") as mock_send:
        mock_send.return_value = {"success": True}
        for cmd in ["hisab", "meri dukan", "sale", "inventory", "!hisab"]:
            res = WhatsAppService.handle_inbound_auto_response(
                organization_id="org-enterprise-default",
                sender_phone="923112233445",
                message_body=cmd
            )
            assert res.get("success") is True
            reply = res.get("reply") or res.get("reply_body")
            assert "Total Saman (Inventory):" in reply
            assert "Aaj Ki Sale (Daily Sale):" in reply
            assert "Mahine Ki Sale (Monthly Sale):" in reply


def test_vendor_khata_record_and_stats_api(client):
    """Verify /vendor/khata/record writes ledger entry and /api/vendor/stats reads it."""
    # 1. Record a sale via POST /vendor/khata/record
    rec_res = client.post("/vendor/khata/record", json={
        "vendor_id": 1,
        "entry_type": "sale",
        "amount": 4500.0,
        "description": "Pytest Daily Sale Entry"
    })
    assert rec_res.status_code == 200
    rec_data = rec_res.get_json()
    assert rec_data.get("success") is True

    # 2. Verify stats from GET /api/vendor/stats
    stats_res = client.get("/api/vendor/stats?vendor_id=1")
    assert stats_res.status_code == 200
    stats_data = stats_res.get_json()
    assert stats_data.get("success") is True
    assert "total_products" in stats_data
    assert "total_inventory_value" in stats_data
    assert "today_sales_total" in stats_data
    assert stats_data["today_sales_total"] >= 4500.0
    assert "month_sales_total" in stats_data
    assert stats_data["month_sales_total"] >= 4500.0
