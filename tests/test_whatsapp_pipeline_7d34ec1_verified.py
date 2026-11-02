"""Tests verifying the surgical, additive-only upgrade and continuous operation
of the commit `7d34ec1` WhatsApp Baileys pipeline.
"""

import os
import sys
import json
import pytest

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from database import db
from models import Organization, WhatsAppMessage
from whatsapp_service import WhatsAppService
from wa_bridge_manager import get_wa_bridge_health, resolve_auth_dir


@pytest.fixture(scope="module")
def app():
    test_app = create_app("testing")
    with test_app.app_context():
        db.create_all()
        yield test_app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def test_whatsapp_bridge_qr_guarantee(client):
    """WhatsApp bridge QR endpoint returns HTTP 200 with JSON payload and never throws 500."""
    res = client.get("/api/v1/whatsapp/bridge-qr")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, dict)
    assert "status" in data
    assert "connected" in data


def test_whatsapp_status_endpoint(client):
    """WhatsApp status endpoint returns HTTP 200 with connection state."""
    res = client.get("/api/v1/whatsapp/status")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, dict)
    assert "status" in data or "connected" in data


def test_whatsapp_session_state_endpoint(client):
    """WhatsApp session state requires auth: 401 when anonymous, 200 with JSON when authenticated."""
    res_anon = client.get("/api/v1/whatsapp/session-state")
    assert res_anon.status_code == 401

    with client.session_transaction() as sess:
        sess["user_id"] = "test-user-id"
        sess["role"] = "admin"
    res_auth = client.get("/api/v1/whatsapp/session-state")
    assert res_auth.status_code == 200
    data = res_auth.get_json()
    assert isinstance(data, dict)
    assert "has_saved_session" in data
    assert "file_count" in data


def test_whatsapp_pipeline_health_endpoint(client):
    """Additive endpoint /api/v1/whatsapp/pipeline-health provides comprehensive diagnostic telemetry."""
    res = client.get("/api/v1/whatsapp/pipeline-health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["pipeline"] == "commit_7d34ec1"
    assert "auth_storage" in data
    assert "database_persistence" in data
    assert "timestamp" in data


def test_root_route_whatsapp_pipeline_health(client):
    """Root route /api/whatsapp/pipeline-health correctly delegates to api_v1."""
    res = client.get("/api/whatsapp/pipeline-health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["pipeline"] == "commit_7d34ec1"


def test_internal_bridge_header_auth(client):
    """X-Internal-Bridge: 1 header authorizes session backup and restore from container bridge."""
    headers = {"X-Internal-Bridge": "1"}
    res_restore = client.get("/api/v1/whatsapp/session-restore", headers=headers)
    assert res_restore.status_code == 200
    data = res_restore.get_json()
    assert data["success"] is True
    assert "restored" in data


def test_unauthorized_session_backup_blocked_on_remote_ip(app):
    """Requests without internal bridge header or authentication are rejected with 401."""
    fresh_client = app.test_client()
    headers = {"X-Forwarded-For": "203.0.113.195"}
    res = fresh_client.post(
        "/api/v1/whatsapp/session-backup",
        environ_base={"REMOTE_ADDR": "203.0.113.195"},
        headers=headers
    )
    assert res.status_code == 401
    data = res.get_json()
    assert "error" in data


def test_wa_bridge_manager_health_helper(app):
    """Additive get_wa_bridge_health function safely returns structured status dictionary."""
    health = get_wa_bridge_health(app=app)
    assert isinstance(health, dict)
    assert "bridge_online" in health
    assert "auth_dir" in health
    assert "has_local_creds" in health
    assert "local_file_count" in health
    assert "db_session_saved" in health
    assert "auto_heal_active" in health
    assert "backup_daemon_active" in health


def test_roman_to_urdu_script_single_classmethod():
    """WhatsAppService.roman_to_urdu_script operates accurately with single classmethod decorator."""
    roman = "salam bhai kya haal hai"
    urdu = WhatsAppService.roman_to_urdu_script(roman)
    assert urdu is not None
    assert len(urdu) > 0


def test_window_location_reload_guard_persists():
    """Guarantees that commit 7d34ec1 reload guard is preserved in static/js/app.js and templates/index.html."""
    app_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "js", "app.js"))
    index_html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates", "index.html"))

    with open(app_js_path, "r", encoding="utf-8") as f:
        app_js = f.read()
    assert "window.location.reload" in app_js
    assert "Automatic page reload intercepted and disabled" in app_js

    with open(index_html_path, "r", encoding="utf-8") as f:
        index_html = f.read()
    assert "window.location.reload" in index_html
    assert "Automatic page reload intercepted and disabled" in index_html
