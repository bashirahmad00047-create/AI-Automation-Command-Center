import sys, os
sys.path.insert(0, os.getcwd())
import json
import shutil
from unittest.mock import patch, MagicMock
from app import create_app
from wa_bridge_manager import resolve_auth_dir, clear_wa_session_in_db

print("=== Starting Test: QR Force-Wipe and Fresh QR Generation ===")

app = create_app()
client = app.test_client()

auth_dir = resolve_auth_dir()
os.makedirs(auth_dir, exist_ok=True)
stale_creds_path = os.path.join(auth_dir, "creds.json")

# 1. Create a stale creds.json file
with open(stale_creds_path, "w") as f:
    f.write(json.dumps({"registrationId": 12345, "noiseKey": {"private": "dummy", "public": "dummy"}, "registered": True}))

assert os.path.exists(stale_creds_path), "Failed to create test stale creds.json"
print(f"[Step 1] Created stale creds.json at: {stale_creds_path} (exists={os.path.exists(stale_creds_path)})")

# 2. Test /api/v1/whatsapp/qr?force_refresh=true
# Mock the Node bridge response returning a fresh QR string from Baileys
mock_bridge_resp = MagicMock()
mock_bridge_resp.status_code = 200
mock_qr_string = "2@f3/MOCK_BAILEYS_QR_DATA_STRING_123456789==,ABCDEF,1,abc"
mock_bridge_resp.json.return_value = {
    "success": True,
    "status": "qr_ready",
    "connected": False,
    "qr": mock_qr_string,
    "qr_image": None,
    "message": "QR code ready for scanning"
}
mock_bridge_resp.text = json.dumps(mock_bridge_resp.json.return_value)

with patch("requests.get", return_value=mock_bridge_resp):
    resp = client.get("/api/v1/whatsapp/qr?force_refresh=true")

print(f"[Step 2] Response status code: {resp.status_code}")
data = resp.get_json() or {}

# Verify stale creds.json was wiped
print(f"[Step 3] Checking if stale creds.json was wiped...")
creds_exist_after = os.path.exists(stale_creds_path)
print(f"Stale creds exist after force_refresh: {creds_exist_after}")
assert not creds_exist_after, "Error: stale creds.json was NOT wiped on force_refresh!"

# Verify returned payload
print(f"[Step 4] Checking QR response payload...")
print(f"status: {data.get('status')}")
print(f"connected: {data.get('connected')}")
print(f"qr: {data.get('qr')}")
qr_img = data.get("qr_image") or ""
print(f"qr_image length: {len(qr_img)}")
print(f"qr_image prefix: {qr_img[:35]}")

assert data.get("status") == "qr_ready", f"Expected status 'qr_ready', got {data.get('status')}"
assert data.get("connected") is False, "Expected connected to be False"
assert data.get("qr") == mock_qr_string, "Expected mock QR string to be returned"
assert str(qr_img).startswith("data:image/png;base64,"), "Expected valid base64 PNG data URI"
assert len(qr_img) > 200, "qr_image data URI too short"

print("\n=== SUCCESS: All QR Force-Wipe & Fresh Generation assertions passed! ===")
os._exit(0)
