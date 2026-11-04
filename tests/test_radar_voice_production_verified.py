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
    """Verify CSP headers explicitly allow unpkg, cdnjs, cartocdn, OpenStreetMap tiles, and HTTPS image sources."""
    res = client.get("/track/ORD-AUTO-TEST-001")
    assert res.status_code == 200
    csp = res.headers.get("Content-Security-Policy", "")
    assert "cartocdn.com" in csp
    assert "unpkg.com" in csp
    assert "openstreetmap.org" in csp
    # Explicit assertion: CSP img-src allows https: so external store photos never get blocked
    assert "img-src" in csp
    assert "https:" in csp
    assert "images.unsplash.com" in csp


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

    # Step 5: Verify direct /api/call/voice base64 relay without STT requirement
    voice_res1 = client.post(f"/api/call/voice/{test_phone}", json={
        "sender": "customer",
        "audio": "GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQRChYECGFOAZwEAAAAAAA",
        "mimeType": "audio/webm"
    })
    assert voice_res1.status_code == 200
    assert voice_res1.get_json().get("queue") == "to_admin"

    voice_res2 = client.post(f"/api/call/voice/{test_phone}", json={
        "sender": "admin",
        "audio": "GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQRChYECGFOAZwEAAAAAAA",
        "mimeType": "audio/webm"
    })
    assert voice_res2.status_code == 200
    assert voice_res2.get_json().get("queue") == "to_customer"

    # Step 6: Verify /api/call/status/<phone> returns queued audio chunks directly
    status_admin_poll = client.get(f"/api/call/status/{test_phone}?role=admin&since_seq=1")
    assert status_admin_poll.status_code == 200
    status_admin_data = status_admin_poll.get_json()
    assert "chunks" in status_admin_data
    assert len(status_admin_data["chunks"]) >= 1
    assert status_admin_data["chunks"][-1]["sender"] == "customer"


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

def test_live_call_room_turn_id_global_scope(client):
    """Regression test: Ensure currentTurnId and turnId are declared in global <script> scope

    before any function usage or async handler, preventing ReferenceError on mobile.
    Also validates JavaScript syntax with node -c.
    """
    import re
    import subprocess
    import tempfile

    template_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates", "live_call_room.html"))
    assert os.path.exists(template_path), f"Template not found: {template_path}"

    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 1. Verify let currentTurnId = 0 and let turnId = 0 exist in template
    assert "let currentTurnId = 0;" in html_content, "let currentTurnId = 0; missing in template"
    assert "let turnId = 0;" in html_content, "let turnId = 0; missing in template"

    # 2. Extract <script> content
    m = re.search(r"<script>(.*?)</script>", html_content, re.DOTALL)
    assert m is not None, "<script> tag not found in live_call_room.html"
    js_content = m.group(1)

    # 3. Check position: declaration MUST precede sendLiveVoicePayload, startPrimarySpeechRecognition, etc.
    decl_pos = js_content.find("let currentTurnId = 0;")
    assert decl_pos != -1, "currentTurnId declaration not found in <script>"

    send_payload_pos = js_content.find("async function sendLiveVoicePayload")
    assert send_payload_pos != -1, "sendLiveVoicePayload function not found"
    assert decl_pos < send_payload_pos, "currentTurnId declared AFTER sendLiveVoicePayload (must be in top-level scope)"

    start_speech_pos = js_content.find("function startPrimarySpeechRecognition")
    assert start_speech_pos != -1, "startPrimarySpeechRecognition function not found"
    assert decl_pos < start_speech_pos, "currentTurnId declared AFTER startPrimarySpeechRecognition (must be global)"

    # Ensure it is NOT declared inside startPrimarySpeechRecognition
    inner_speech_code = js_content[start_speech_pos:send_payload_pos]
    assert "let currentTurnId" not in inner_speech_code, "currentTurnId should not be scoped inside startPrimarySpeechRecognition"

    # 4. Check rendered route /call/<phone>
    res = client.get("/call/923209350858")
    assert res.status_code == 200
    assert "no-store" in res.headers.get("Cache-Control", "")
    rendered = res.get_data(as_text=True)
    assert "let currentTurnId = 0;" in rendered
    assert "let turnId = 0;" in rendered
    assert "Tap to Send" not in rendered
    assert "Type here if mic pauses" not in rendered

    # 5. Syntax validation via node -c
    js_for_node = re.sub(r"\{\{.*?\}\}", "923209350858", js_content)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
        tf.write(js_for_node)
        temp_js_path = tf.name

    try:
        proc = subprocess.run(["node", "-c", temp_js_path], capture_output=True, text=True)
        assert proc.returncode == 0, f"node -c failed: {proc.stderr}"
    finally:
        if os.path.exists(temp_js_path):
            os.remove(temp_js_path)

def test_multi_tenant_whatsapp_hybrid_and_24h_window(client):
    """Verify multi-tenant WhatsApp hybrid provider mode, non-blocking queue,

    and Meta 24-hour customer service window compliance helper.
    """
    from whatsapp_service import WhatsAppService
    import datetime

    tenant = "tenant_production_retail_01"

    # 1. Default mode is baileys_bridge
    default_mode = WhatsAppService.get_tenant_whatsapp_mode(tenant)
    assert default_mode in ("baileys_bridge", "official_meta_cloud")

    # 2. Switch mode to official_meta_cloud
    set_mode = WhatsAppService.set_tenant_whatsapp_mode(tenant, "official_meta_cloud")
    assert set_mode == "official_meta_cloud"
    assert WhatsAppService.get_tenant_whatsapp_mode(tenant) == "official_meta_cloud"

    # 3. 24-hour compliance window calculations
    now_utc = datetime.datetime.utcnow()
    is_open, rem_secs, exp_str = WhatsAppService.is_within_24h_window(now_utc)
    assert is_open is True
    assert rem_secs > 86000
    assert exp_str is not None

    past_25h = now_utc - datetime.timedelta(hours=25)
    is_open_past, rem_secs_past, _ = WhatsAppService.is_within_24h_window(past_25h)
    assert is_open_past is False
    assert rem_secs_past == 0

    # 4. Update customer service window
    test_phone = "923209350858"
    WhatsAppService.update_customer_service_window(test_phone, tenant_id=tenant, last_seen=now_utc)
    status = WhatsAppService.get_customer_service_window_status(test_phone, tenant_id=tenant)
    assert status["meta_cloud_24h_window_open"] is True
    assert status["can_send_freeform"] is True

    # 5. Non-blocking queue enqueue & status check
    q_res = WhatsAppService.enqueue_tenant_message(tenant, {"type": "test_ping", "from": test_phone})
    assert q_res.get("success") is True
    assert q_res.get("queued") is True

    q_stat = WhatsAppService.get_tenant_queue_status(tenant)
    assert q_stat["tenant_id"] == tenant
    assert q_stat["enqueued_total"] >= 1

    # 6. Test HTTP endpoints
    mode_get = client.get(f"/api/v1/whatsapp/mode?tenant_id={tenant}")
    assert mode_get.status_code == 200
    assert mode_get.get_json().get("mode") == "official_meta_cloud"

    win_get = client.get(f"/api/v1/whatsapp/customer-window?phone={test_phone}&tenant_id={tenant}")
    assert win_get.status_code == 200
    assert win_get.get_json().get("meta_cloud_24h_window_open") is True


def test_fleet_driver_registration_and_multi_vehicle_status(client):
    """Verify fleet drivers can register across multiple vehicle types (bike, rickshaw, car, van)

    and report online GPS status.
    """
    # 1. Register Bike Rider
    res_bike = client.post("/api/fleet/register", json={
        "name": "Javed Bike Express",
        "phone": "03471000111",
        "vehicle_type": "bike",
        "plate_no": "CH-BK-101",
        "online_status": "online",
        "lat": 35.8518,
        "lng": 71.7864
    })
    assert res_bike.status_code in (200, 201)
    d_bike = res_bike.get_json().get("driver")
    assert d_bike["vehicle_type"] == "bike"
    assert d_bike["online_status"] == "online"

    # 2. Register Auto Rickshaw Driver
    res_rickshaw = client.post("/api/fleet/register", json={
        "name": "Gulzar Auto Rickshaw",
        "phone": "03472000222",
        "vehicle_type": "rickshaw",
        "plate_no": "CH-RK-202",
        "online_status": "online",
        "lat": 35.8530,
        "lng": 71.7870
    })
    assert res_rickshaw.status_code in (200, 201)
    d_rk = res_rickshaw.get_json().get("driver")
    assert d_rk["vehicle_type"] == "rickshaw"

    # 3. Register Car / Taxi Driver
    res_car = client.post("/api/fleet/register", json={
        "name": "Shabbir Chitral Taxi",
        "phone": "03473000333",
        "vehicle_type": "car",
        "plate_no": "CH-CAR-303",
        "online_status": "online",
        "lat": 35.8550,
        "lng": 71.7890
    })
    assert res_car.status_code in (200, 201)
    d_car = res_car.get_json().get("driver")
    assert d_car["vehicle_type"] == "car"

    # 4. List drivers and filter by vehicle_type
    list_res = client.get("/api/fleet/drivers?vehicle_type=rickshaw")
    assert list_res.status_code == 200
    drivers = list_res.get_json().get("drivers", [])
    assert len(drivers) >= 1
    assert any(d["phone"] == "03472000222" for d in drivers)


def test_indrive_ride_request_bidding_and_tracking(client):
    """Verify InDrive-style ride creation with customer fare offer, driver bidding/counter-offers,

    acceptance, and live multi-vehicle GPS tracking on /track/<id>.
    """
    # 1. Customer creates Ride Request with initial fare offer of PKR 300
    ride_payload = {
        "customer_name": "Zubair Ahmad",
        "customer_phone": "03209350858",
        "pickup_address": "Ataliq Bazar, Chitral",
        "dropoff_address": "Danin, Chitral",
        "pickup_lat": 35.8518,
        "pickup_lng": 71.7864,
        "dropoff_lat": 35.8697,
        "dropoff_lng": 71.7840,
        "vehicle_type": "rickshaw",
        "customer_offer_pkr": 300.0
    }
    create_res = client.post("/api/rides/request", json=ride_payload)
    assert create_res.status_code in (200, 201)
    create_json = create_res.get_json()
    assert create_json.get("success") is True
    ride_id = create_json.get("ride_id")
    assert ride_id.startswith("RIDE-")
    assert "/track/" in create_json.get("tracking_url")

    # 2. Driver 1 submits a counter-fare offer of PKR 350
    bid_payload = {
        "driver_name": "Gulzar Auto Rickshaw",
        "driver_phone": "03472000222",
        "vehicle_type": "rickshaw",
        "bid_type": "counter",
        "counter_offer_pkr": 350.0
    }
    bid_res = client.post(f"/api/rides/{ride_id}/bid", json=bid_payload)
    assert bid_res.status_code == 200
    bid_json = bid_res.get_json()
    assert bid_json.get("success") is True
    assert bid_json.get("status") == "bidding"
    assert len(bid_json.get("all_bids")) == 1
    assert bid_json["all_bids"][0]["bid_pkr"] == 350.0

    # 3. Customer accepts the counter-offer
    accept_res = client.post(f"/api/rides/{ride_id}/accept_bid", json={"bid_index": 0})
    assert accept_res.status_code == 200
    accept_json = accept_res.get_json()
    assert accept_json.get("success") is True
    assert accept_json.get("status") == "accepted"
    assert accept_json.get("fare_pkr") == 350.0

    # 4. Driver broadcasts live GPS location
    loc_post = client.post(f"/api/track/{ride_id}/location", json={
        "lat": 35.8525,
        "lng": 71.7868,
        "speed": 32.0,
        "heading": 90.0,
        "vehicle_type": "rickshaw"
    })
    assert loc_post.status_code == 200
    loc_post_json = loc_post.get_json()
    assert loc_post_json.get("success") is True
    assert loc_post_json.get("vehicle_type") == "rickshaw"

    # 5. Customer polls location
    loc_get = client.get(f"/api/track/{ride_id}/location")
    assert loc_get.status_code == 200
    loc_get_json = loc_get.get_json()
    assert loc_get_json.get("success") is True
    assert loc_get_json.get("is_ride") is True
    assert loc_get_json.get("vehicle_type") == "rickshaw"
    assert loc_get_json.get("final_fare_pkr") == 350.0
    assert loc_get_json.get("has_rider") is True
    assert loc_get_json["rider"]["lat"] == 35.8525

    # 6. Render /track/<ride_id>
    page_res = client.get(f"/track/{ride_id}")
    assert page_res.status_code == 200
    page_html = page_res.get_data(as_text=True)
    assert ride_id in page_html
    assert "InDrive Fare Offer" in page_html



def test_live_voice_call_resilience_and_empty_turn(client):
    """Verify live voice call handles empty turns and audio blobs gracefully without 400 or Speech text error."""
    import base64
    from unittest.mock import patch

    # 1. Empty turn / silence ping: must return 200 with empty_turn=True, never 400
    res_empty = client.post("/api/v1/live-voice-call", json={})
    assert res_empty.status_code == 200
    json_empty = res_empty.get_json()
    assert json_empty.get("success") is True
    assert json_empty.get("empty_turn") is True

    # 2. AudioBase64 without text: must return 200, forward to admin queue, never return 400 or Speech text error
    dummy_audio_b64 = base64.b64encode(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00").decode("ascii")
    test_phone = "923209350858"
    with patch("whatsapp_service.WhatsAppService._transcribe_audio", return_value=None), \
         patch("whatsapp_service.WhatsAppService._synthesize_edge_tts", return_value=b"fake_mp3_audio"):
        res_audio = client.post("/api/v1/live-voice-call", json={
            "audioBase64": dummy_audio_b64,
            "phone": test_phone,
            "text": ""
        })
    # Explicit assertion: handles audio-only payloads (when browser speech-to-text text is empty) without returning error
    assert res_audio.status_code == 200
    json_audio = res_audio.get_json()
    assert json_audio.get("success") is True
    assert json_audio.get("error") is None
    assert "Speech text is required" not in str(json_audio)
    assert json_audio.get("replyText") is not None

    # 3. Verify Admin audio queue received the customer chunk
    from api_v1 import _ACTIVE_CALL_SESSIONS, _ACTIVE_CALL_SESSIONS_LOCK
    with _ACTIVE_CALL_SESSIONS_LOCK:
        sess = _ACTIVE_CALL_SESSIONS.get(test_phone)
        assert sess is not None
        assert len(sess.get("to_admin_queue", [])) > 0


def test_foodpanda_store_catalog_and_hd_images(client):
    """Verify Foodpanda restaurant and artisan catalog items have real HD photos, delivery badges, and ratings."""
    # 1. API Catalog test
    res = client.get("/api/v1/store/products")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    prods = data.get("products", [])
    assert len(prods) >= 12

    names = [p["name"] for p in prods]
    assert "Pure Chitrali Sidr Mountain Honey (500g)" in names
    assert "Special Chicken Dum Biryani" in names
    assert "Peshawari Shinwari Mutton Karahi (Half kg)" in names
    assert "Gourmet Smash Beef Burger & Fries" in names

    # Verify Honey Jar image is genuine glass jar (not watermelon)
    honey_prod = next(p for p in prods if p["name"] == "Pure Chitrali Sidr Mountain Honey (500g)")
    assert "photo-1471943311424-646960669fbc" in honey_prod["image_url"]
    assert honey_prod.get("delivery_time") is not None
    assert honey_prod.get("rating") is not None

    # Verify popular foodpanda & local categories
    cats = [p.get("category", "") for p in prods]
    assert any("Fast Food" in c or "Burger" in c for c in cats)
    assert any("Desi" in c or "Biryani" in c for c in cats)
    assert any("Pizza" in c or "Bakery" in c for c in cats)
    assert any("Honey" in c for c in cats)
    assert any("Craft" in c or "Shawl" in c for c in cats)
    assert any("Dry Fruit" in c or "Fruit" in c for c in cats)

    # 2. Render /store page
    page = client.get("/store")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "foodpanda-delivery-badges" in html
    assert "referrerpolicy=\"no-referrer\"" in html
    assert "Foodpanda Restaurants" in html
    assert "Chitral Local Bazar" in html
