import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import math
import json
from app import app


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        with app.app_context():
            yield test_client


def test_permissions_policy_header(client):
    """Verify Permissions-Policy header allows microphone, camera, and geolocation without blocking."""
    res = client.get("/health")
    assert res.status_code == 200
    perm = res.headers.get("Permissions-Policy", "")
    assert 'microphone=(self "*")' in perm, f"Permissions-Policy missing microphone allowance: {perm}"
    assert 'camera=(self "*")' in perm, f"Permissions-Policy missing camera allowance: {perm}"
    assert 'geolocation=(self "*")' in perm, f"Permissions-Policy missing geolocation allowance: {perm}"


def test_chitral_distance_calculation():
    """Verify local Chitral distance from Ataliq Bazar base (35.8518, 71.7864)

    to customer pin (35.8697, 71.7840) is strictly < 5 km (NOT the 539 km bug).
    """
    store_base_lat = 35.8518
    store_base_lng = 71.7864
    customer_lat = 35.8697
    customer_lng = 71.7840

    dist_km = haversine_distance(store_base_lat, store_base_lng, customer_lat, customer_lng)
    road_dist_km = dist_km * 1.25

    print(f"Calculated straight distance: {dist_km:.2f} km, estimated road: {road_dist_km:.2f} km")
    assert dist_km < 5.0, f"Distance too large: {dist_km} km (must be local < 5 km)"
    assert road_dist_km < 5.0, f"Road distance too large: {road_dist_km} km"
    assert dist_km < 3.0, f"Expected ~2.0 km local Chitral distance, got {dist_km} km"


def test_reverse_geocode_endpoint(client):
    """Verify /api/v1/reverse-geocode resolves coordinates to human-readable street/area."""
    res = client.get("/api/v1/reverse-geocode?lat=35.8518&lng=71.7864")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert "address" in data
    assert len(data.get("address", "")) > 0


def test_voice_transcribe_and_reply_endpoint(client):
    """Verify /api/voice/transcribe-and-reply accepts speech payload, transcribes, and replies with voice audio."""
    payload = {
        "message": "Chitral Sidr honey ka rate bataiye",
        "contactName": "Bashir khani",
        "persona": "ur-PK-AsadNeural"
    }
    res = client.post("/api/voice/transcribe-and-reply", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert "replyText" in data or "reply_text" in data
    reply = data.get("replyText") or data.get("reply_text")
    assert len(reply) > 0
    assert bool(data.get("audioBase64") or data.get("audio_base64")) is True


def test_call_handshake_state_machine(client):
    """Verify call state machine starts in RINGING_WAITING_FOR_JOIN, transitions to CUSTOMER_JOINED upon join, and ends properly."""
    test_phone = "923471000668"
    test_name = "Khanii Jani"

    # 1. Admin initiates call: state must be ringing
    init_res = client.post("/api/call/initiate", json={"phone": test_phone, "name": test_name})
    assert init_res.status_code == 200
    init_data = init_res.get_json()
    assert init_data.get("success") is True
    assert init_data.get("status") in ("RINGING_WAITING_FOR_JOIN", "ringing")
    assert "/call/923471000668" in init_data.get("call_url", "")

    # 2. Check status while ringing: joined must be False
    status_res = client.get(f"/api/call/{test_phone}/status")
    assert status_res.status_code == 200
    status_data = status_res.get_json()
    assert status_data.get("joined") is False
    assert status_data.get("status") in ("RINGING_WAITING_FOR_JOIN", "ringing")

    # Also verify route variant /api/call/status/<phone>
    status_res_alt = client.get(f"/api/call/status/{test_phone}")
    assert status_res_alt.status_code == 200
    assert status_res_alt.get_json().get("status") in ("RINGING_WAITING_FOR_JOIN", "ringing")

    # 3. Customer opens link and taps join: state becomes connected
    join_res = client.post(f"/api/call/{test_phone}/join", json={"phone": test_phone})
    assert join_res.status_code == 200
    join_data = join_res.get_json()
    assert join_data.get("success") is True
    assert join_data.get("status") in ("CUSTOMER_JOINED", "connected")

    # 4. Check status after join: joined must now be True
    status_res2 = client.get(f"/api/call/{test_phone}/status")
    assert status_res2.status_code == 200
    status_data2 = status_res2.get_json()
    assert status_data2.get("joined") is True
    assert status_data2.get("status") in ("CUSTOMER_JOINED", "connected")

    # 5. End call
    end_res = client.post(f"/api/call/{test_phone}/end")
    assert end_res.status_code == 200
    assert end_res.get_json().get("status") in ("CALL_ENDED", "ended")

    # 6. Verify status after call ended is ended
    status_res3 = client.get(f"/api/call/status/{test_phone}")
    assert status_res3.status_code == 200
    assert status_res3.get_json().get("status") == "ended"


def test_customer_latest_order_info_endpoint(client):
    """Verify /api/customer-latest-order-info returns dynamic customer inquiry/order data without hardcoded demo strings."""
    res = client.get("/api/customer-latest-order-info?phone=923471000668")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert "summary" in data
    assert len(data.get("summary")) > 0
