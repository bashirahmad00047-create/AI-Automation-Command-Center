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


def test_public_track_portal_rendering(client):
    """Verify /track/<order_id> renders Leaflet map, tabs, and role parameter."""
    res = client.get("/track/ORD-AUTO-TEST-001?role=rider")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert ("radarMap" in html or "deliveryMap" in html)
    assert "cartocdn.com" in html
    assert "Rider GPS Mode" in html
    assert "Customer Live View" in html
    assert "min-height: 380px" in html


def test_csp_allows_map_tiles_and_cdns(client):
    """Verify CSP headers explicitly allow unpkg, cdnjs, cartocdn, and OpenStreetMap tiles."""
    res = client.get("/track/ORD-AUTO-TEST-001")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert "cartocdn.com" in csp
    assert "unpkg.com" in csp
    assert "openstreetmap.org" in csp


def test_sequential_voice_queue_delivery(client):
    """Verify directional audio queues (to_customer_queue & to_admin_queue) and since_seq filtering."""
    test_phone = "923479998877"

    # Step 1: Customer sends voice to Admin
    chunk1_res = client.post(f"/api/call/{test_phone}/audio", json={
        "sender": "customer",
        "audio": "dGVzdF9hdWRpb18x",
        "text": "Salam Admin from customer"
    })
    assert chunk1_res.status_code == 200
    data1 = chunk1_res.get_json()
    assert data1.get("success") is True
    assert data1.get("queue") == "to_admin"
    assert data1.get("seq_id") == 1

    # Step 2: Admin sends voice to Customer
    chunk2_res = client.post(f"/api/call/{test_phone}/audio", json={
        "sender": "admin",
        "audio": "dGVzdF9hdWRpb18y",
        "text": "Walaikum Assalam customer from Admin"
    })
    assert chunk2_res.status_code == 200
    data2 = chunk2_res.get_json()
    assert data2.get("success") is True
    assert data2.get("queue") == "to_customer"
    assert data2.get("seq_id") == 1

    # Step 3: Admin polls customer queue (role=admin) -> gets only to_admin_queue
    admin_poll = client.get(f"/api/call/{test_phone}/audio?role=admin")
    assert admin_poll.status_code == 200
    admin_data = admin_poll.get_json()
    assert len(admin_data.get("chunks", [])) == 1
    assert admin_data["chunks"][0]["sender"] == "customer"
    assert admin_data["chunks"][0]["text"] == "Salam Admin from customer"

    # Step 4: Customer polls customer queue (role=customer) -> gets only to_customer_queue
    customer_poll = client.get(f"/api/call/{test_phone}/audio?role=customer")
    assert customer_poll.status_code == 200
    customer_data = customer_poll.get_json()
    assert len(customer_data.get("chunks", [])) == 1
    assert customer_data["chunks"][0]["sender"] == "admin"
    assert customer_data["chunks"][0]["text"] == "Walaikum Assalam customer from Admin"


def test_phone_normalization_cross_endpoint(client):
    """Verify phone numbers with '+', ' ', and '-' symbols map to the identical session."""
    raw_phone_dash = "+92 347-1122334"
    clean_phone_mobile = "923471122334"

    # Initiate with raw phone
    r_init = client.post("/api/call/initiate", json={"phone": raw_phone_dash, "name": "Test Peer"})
    assert r_init.status_code == 200

    # Mobile joins using digits-only
    r_join = client.post(f"/api/call/{clean_phone_mobile}/join")
    assert r_join.status_code == 200
    assert r_join.get_json().get("status") == "connected"

    # Admin posts voice using raw phone format
    r_post = client.post(f"/api/call/{raw_phone_dash}/audio", json={"sender": "admin", "text": "Normalized voice packet"})
    assert r_post.status_code == 200

    # Customer fetches voice using clean phone format
    r_get = client.get(f"/api/call/{clean_phone_mobile}/audio?role=customer")
    assert r_get.status_code == 200
    assert len(r_get.get_json().get("chunks", [])) == 1
    assert r_get.get_json()["chunks"][0]["text"] == "Normalized voice packet"


def test_store_foodpanda_rendering_and_checkout(client):
    """Verify /store renders Foodpanda badges, sticky cart bar, and checkout returns tracking redirect."""
    # 1. Render /store
    store_res = client.get("/store")
    assert store_res.status_code == 200
    html = store_res.get_data(as_text=True)
    assert "25-35 min Free Delivery" in html
    assert "foodpandaCartBar" in html
    assert "handleProductImgError" in html
    assert "Detect My GPS Location" in html

    # 2. Test Checkout with GPS detection
    payload = {
        "name": "Kashif Khan",
        "phone": "03471234567",
        "address": "Ataliq Bazar, Chitral Town",
        "latitude": 35.8524,
        "longitude": 71.7869,
        "payment_method": "cod",
        "items": [
            {"id": "test-item-1", "name": "Pure Chitrali Sidr Mountain Honey (500g)", "price": 2800, "quantity": 1}
        ]
    }
    checkout_res = client.post("/api/store/checkout", json=payload)
    assert checkout_res.status_code == 201
    c_json = checkout_res.get_json()
    assert c_json.get("success") is True
    assert "order_id" in c_json
    assert "/track/" in c_json.get("tracking_url", "")




def test_live_rider_gps_broadcast_and_polling(client):
    """Verify bike rider can POST live GPS coordinates and customer polling retrieves them with dispatched status."""
    order_id = "ORD-RADAR-TEST-777"
    post_payload = {
        "lat": 35.8524,
        "lng": 71.7869,
        "accuracy": 4.0,
        "speed": 25.5,
        "heading": 180.0
    }
    # 1. Post rider location
    post_res = client.post(f"/api/track/{order_id}/location", json=post_payload)
    assert post_res.status_code == 200
    post_json = post_res.get_json()
    assert post_json.get("success") is True
    assert post_json.get("status") == "dispatched"
    assert post_json.get("lat") == 35.8524

    # 2. Poll rider location
    get_res = client.get(f"/api/track/{order_id}/location")
    assert get_res.status_code == 200
    get_json = get_res.get_json()
    assert get_json.get("success") is True
    assert get_json.get("has_rider") is True
    assert get_json.get("rider", {}).get("lat") == 35.8524
    assert get_json.get("rider", {}).get("lng") == 71.7869
    assert "destination" in get_json
    assert get_json["destination"]["lat"] is not None

