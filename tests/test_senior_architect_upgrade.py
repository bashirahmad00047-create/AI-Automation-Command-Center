import os
import sys
import json
import io
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app import create_app
from services.global_bazar_service import GlobalBazarService
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
# UPGRADE 1: Duplicate Product Insertion & Idempotency
# =============================================================================
def test_idempotency_prevents_duplicate_product():
    """Verify handle_whatsapp_inventory_image rejects duplicate message_ids."""
    WhatsAppService._inventory_idempotency_cache.clear()

    # Generate small valid JPEG bytes
    img = Image.new("RGB", (60, 60), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    fake_img_bytes = buf.getvalue()

    mock_product = {
        "id": 9991,
        "title": "Heavy Duty Brass Security Padlock",
        "price": 450.0,
        "category": "Hardware & Tools"
    }

    with patch("requests.get") as mock_get, \
         patch.object(GlobalBazarService, "process_ai_catalog_direct") as mock_direct, \
         patch.object(GlobalBazarService, "add_product") as mock_add_product, \
         patch.object(WhatsAppService, "send_message") as mock_send_msg:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_img_bytes
        mock_get.return_value = mock_resp
        mock_send_msg.return_value = {"success": True}

        mock_direct.return_value = {
            "success": True,
            "title": "Heavy Duty Brass Security Padlock",
            "price": 450.0,
            "category": "Hardware & Tools",
            "saved_product": mock_product
        }

        # First Call
        res1 = WhatsAppService.handle_whatsapp_inventory_image(
            organization_id="org-enterprise-default",
            sender_phone="923471000668",
            message_body="RS 450",
            download_url="http://mock.image/padlock.jpg",
            message_id="msg_test_idemp_101"
        )
        assert res1.get("success") is True
        assert res1.get("duplicate") is not True

        # Second Call with identical message_id
        res2 = WhatsAppService.handle_whatsapp_inventory_image(
            organization_id="org-enterprise-default",
            sender_phone="923471000668",
            message_body="RS 450",
            download_url="http://mock.image/padlock.jpg",
            message_id="msg_test_idemp_101"
        )
        assert res2.get("success") is True
        assert res2.get("duplicate") is True
        assert "already processed" in res2.get("message", "").lower()

        # Ensure mock_direct was only called once, and mock_add_product was NOT called a second time
        assert mock_direct.call_count == 1
        assert mock_add_product.call_count == 0


def test_single_pipeline_insertion_when_saved_product_returned():
    """Verify that when direct/FastAPI pipeline saves the product, secondary fallback insertion is bypassed."""
    WhatsAppService._inventory_idempotency_cache.clear()

    img = Image.new("RGB", (60, 60), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    fake_img_bytes = buf.getvalue()

    with patch("requests.get") as mock_get, \
         patch.object(GlobalBazarService, "process_ai_catalog_direct") as mock_direct, \
         patch.object(GlobalBazarService, "add_product") as mock_add_product, \
         patch.object(WhatsAppService, "send_message") as mock_send_msg:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_img_bytes
        mock_get.return_value = mock_resp
        mock_send_msg.return_value = {"success": True}

        mock_direct.return_value = {
            "success": True,
            "title": "Handmade Woolen Shawl",
            "price": 2500.0,
            "category": "Apparel & Accessories",
            "saved_product": {"id": 8881, "title": "Handmade Woolen Shawl"}
        }

        res = WhatsAppService.handle_whatsapp_inventory_image(
            organization_id="org-enterprise-default",
            sender_phone="923471000668",
            message_body="RS 2500",
            download_url="http://mock.image/shawl.jpg",
            message_id="msg_test_single_pipeline_202"
        )
        assert res.get("success") is True
        # GlobalBazarService.add_product should NOT be called directly since process_ai_catalog_direct already saved it
        assert mock_add_product.call_count == 0


# =============================================================================
# UPGRADE 2: Studio Image Enhancement & Real Vision AI
# =============================================================================
def test_studio_image_enhancement():
    """Verify enhance_product_image_studio processes raw bytes into a square enhanced studio photo."""
    raw_img = Image.new("RGB", (300, 200), color=(120, 80, 60))
    buf = io.BytesIO()
    raw_img.save(buf, format="JPEG")
    raw_bytes = buf.getvalue()

    enhanced_bytes = GlobalBazarService.enhance_product_image_studio(raw_bytes)
    assert isinstance(enhanced_bytes, bytes)
    assert len(enhanced_bytes) > 0

    # Read back enhanced image and check dimensions
    out_img = Image.open(io.BytesIO(enhanced_bytes))
    # It must be perfectly square
    assert out_img.size[0] == out_img.size[1]
    assert out_img.size[0] >= 640
    assert out_img.format in ("JPEG", "PNG")


def test_real_vision_ai_parsing_and_price_stripping():
    """Verify analyze_product_vision parses Gemini JSON response and strips out repetitive price tags."""
    raw_img = Image.new("RGB", (100, 100), color=(200, 200, 200))
    buf = io.BytesIO()
    raw_img.save(buf, format="JPEG")
    raw_bytes = buf.getvalue()

    mock_ai_json = json.dumps({
        "title": "Heavy Duty Brass Security Padlock",
        "category": "Hardware & Tools",
        "description": "High quality hardened brass padlock with anti-drill cylinder. Ideal for shop shutters and gates. RS 450"
    })

    mock_client = MagicMock()
    mock_model = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = mock_ai_json
    mock_model.generate_content.return_value = mock_resp
    mock_client.models = mock_model

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_test_key_123"}), \
         patch("google.genai.Client", return_value=mock_client):

        vision_result = GlobalBazarService.analyze_product_vision(raw_bytes, caption="RS 450")
        assert vision_result is not None
        assert vision_result["title"] == "Heavy Duty Brass Security Padlock"
        assert vision_result["category"] == "Hardware & Tools"
        # Verify "RS 450" was cleanly stripped from description
        assert "RS 450" not in vision_result["description"]
        assert "brass padlock" in vision_result["description"].lower()


# =============================================================================
# UPGRADE 3: Direct Vendor Auth & Magic Link (Never Redirects to Admin Dashboard)
# =============================================================================
def test_vendor_auth_renders_portal_directly_no_redirect(client):
    """Verify /vendor/auth/<token> returns HTTP 200 and directly renders vendor_dashboard.html, NOT 302 to /dashboard."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    token = GlobalBazarService.generate_vendor_magic_token(vendor["id"], phone=vendor["phone"])

    res = client.get(f"/vendor/auth/{token}", follow_redirects=False)
    # MUST be 200 OK directly, NOT 302 redirect
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Verify Vendor ERP header & 6 KPI Cards are present
    assert "ERP" in html and "Dukan" in html
    assert "Total Maal" in html
    assert "Aaj Ki Sale" in html
    assert "Mahine Ki Sale" in html
    assert "Kul Munafa" in html
    assert "Aaj Ka Kharcha" in html
    assert "Kam Stock" in html

    # Verify no Admin BashFlow UI leak
    assert "WhatsApp Cloud Admin" not in html
    assert "Acme Global Enterprise" not in html


def test_vendor_portal_renders_directly(client):
    """Verify /vendor/portal with session or phone returns HTTP 200 with vendor ERP."""
    with client.session_transaction() as sess:
        sess["vendor_phone"] = "923471000668"

    res = client.get("/vendor/portal", follow_redirects=False)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Total Maal" in html
    assert "Sell 1 (+Sale)" in html


# =============================================================================
# UPGRADE 4: Customer-Ready Vendor ERP, Khata, & "Sell 1 (+Sale)"
# =============================================================================
def test_sell_one_product_flow(client):
    """Verify sell_one_product decrements stock by 1 and records sale in ledger."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    vendor_id = vendor["id"]

    # Add a dedicated test product
    prod = GlobalBazarService.add_product(
        vendor_id=vendor_id,
        title="Test Hardware Lock For ERP",
        price=500.0,
        cost_price=350.0,
        stock=10,
        category="Hardware & Tools"
    )
    prod_id = prod["id"]
    initial_stock = prod["stock"]

    # Sell 1 via API
    with client.session_transaction() as sess:
        sess["vendor_id"] = vendor_id
        sess["vendor_phone"] = "923471000668"

    res = client.post("/vendor/product/sell-one", json={"product_id": prod_id})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert data.get("new_stock") == initial_stock - 1

    # Verify stats
    stats = GlobalBazarService.get_vendor_dashboard_data(vendor_id)
    assert stats["today_sales"] >= 500.0
    assert stats["today_orders"] >= 1
    assert stats["total_products"] >= 1


def test_vendor_khata_record(client):
    """Verify recording an expense or cash sale via quick khata updates stats."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    vendor_id = vendor["id"]

    with client.session_transaction() as sess:
        sess["vendor_id"] = vendor_id
        sess["vendor_phone"] = "923471000668"

    # Record expense
    res = client.post("/vendor/khata/record", data={
        "entry_type": "expense",
        "amount": "150",
        "description": "Tea and snacks for shop",
        "customer_name": ""
    }, follow_redirects=True)
    assert res.status_code == 200

    stats = GlobalBazarService.get_vendor_dashboard_data(vendor_id)
    assert stats["expenses"] >= 150.0


# =============================================================================
# CORE ARCHITECTURAL REQUIREMENTS: 
# 1. Strict Single-Vendor Isolation
# 2. Automated Bijak / Wholesale Bill Scanner
# 3. Numeric Title Rejection & Gemini Vision Setup
# =============================================================================

def test_single_vendor_isolation_storefront(client):
    """Verify /store?shop=<vendor_id> and /dukan/<vendor_id> show ONLY this vendor and hide others."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    v_id = vendor["id"]

    res = client.get(f"/store?shop={v_id}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Must contain Bashir Store and its product
    assert "Bashir Store" in html
    assert "Traditional Metallic Spout Kettle" in html or "Hardware Lock" in html

    # NEVER contain other vendors' products like Biryani or Pizza
    assert "Special Chicken Dum Biryani" not in html
    assert "Italiano Stone Crust Pizza" not in html
    assert "Shahi Dastarkhwan Restaurant" not in html

    # Multi-shop filter bar must be hidden
    assert "Filter by Shop:" not in html


def test_single_vendor_isolation_api(client):
    """Verify /api/store/products?shop=<vendor_id> returns ONLY this vendor's items."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    v_id = vendor["id"]

    res = client.get(f"/api/store/products?shop={v_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert data.get("is_single_shop") is True
    assert len(data.get("products", [])) > 0
    for p in data["products"]:
        assert p.get("vendor_id") == v_id or "Bashir Store" in p.get("seller_name", "")
        assert "Biryani" not in p.get("title", "")


def test_process_vendor_bijak_multi_item_scanner():
    """Verify process_vendor_bijak_image extracts items, updates stock/ledger, and formats links."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    v_id = vendor["id"]

    fake_bijak_json = {
        "is_bijak": True,
        "vendor_shop_name": "Lahore Wholesale Market",
        "items": [
            {
                "title": "Brass Security Padlock 50mm",
                "quantity": 15,
                "cost_price": 380.0,
                "selling_price": 500.0,
                "category": "Hardware & Tools"
            },
            {
                "title": "Chitrali Woolen Muffler",
                "quantity": 8,
                "cost_price": 600.0,
                "selling_price": 900.0,
                "category": "Apparel & Accessories"
            }
        ]
    }

    raw_img = Image.new("RGB", (200, 200), color="white")
    buf = io.BytesIO()
    raw_img.save(buf, format="JPEG")
    fake_img = buf.getvalue()

    with patch.object(GlobalBazarService, "analyze_product_vision", return_value=None), \
         patch("requests.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps(fake_bijak_json)}]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res = GlobalBazarService.process_vendor_bijak_image(
            vendor_id=v_id,
            image_bytes=fake_img,
            caption="bijak wholesale market list"
        )
        assert res.get("success") is True
        assert res.get("is_bijak") is True
        assert res.get("total_items") >= 2
        assert "Brass Security Padlock" in res.get("whatsapp_message", "")
        # Must include both Admin View and Shareable Storefront links
        assert "/vendor/auth/" in res.get("whatsapp_message", "")
        assert f"/store?shop={v_id}" in res.get("whatsapp_message", "")


def test_numeric_title_rejection_for_550_and_kettle_naming():
    """Verify caption with only '550' or 'Rs 550' is treated strictly as price, never title."""
    WhatsAppService._inventory_idempotency_cache.clear()

    raw_img = Image.new("RGB", (80, 80), color="silver")
    buf = io.BytesIO()
    raw_img.save(buf, format="JPEG")
    fake_img = buf.getvalue()

    with patch("requests.get") as mock_get, \
         patch.object(GlobalBazarService, "analyze_product_vision", return_value=None), \
         patch.object(WhatsAppService, "send_message") as mock_send_msg:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_img
        mock_get.return_value = mock_resp
        mock_send_msg.return_value = {"success": True}

        res = WhatsAppService.handle_whatsapp_inventory_image(
            organization_id="org-enterprise-default",
            sender_phone="923471000668",
            message_body="550",
            download_url="http://mock.image/kettle.jpg",
            message_id="msg_test_numeric_title_550"
        )
        assert res.get("success") is True
        # Title must NEVER be purely "550"
        assert res.get("title") != "550"
        assert res.get("title") != "Rs 550"
        assert "Kettle" in res.get("title") or "Lota" in res.get("title") or "Store" in res.get("title")
        # WhatsApp reply must include both links
        assert "/vendor/auth/" in res.get("reply_body", "")
        assert "/store?shop=" in res.get("reply_body", "")


def test_cleanup_duplicates_and_fix_numeric_titles():
    """Verify cleanup_vendor_duplicates_and_fix_numeric_titles removes old duplicate test items."""
    res = GlobalBazarService.cleanup_vendor_duplicates_and_fix_numeric_titles()
    assert isinstance(res, dict)
    assert "cleaned_duplicates" in res
    assert "fixed_numeric_titles" in res


# =============================================================================
# ARCHITECTURAL VERIFICATION: Multi-Vendor Phone Routing, COD + GPS, Rider Map
# =============================================================================
def test_multi_vendor_phone_routing():
    """Verify distinct vendor phone numbers resolve to completely isolated shops."""
    phone_a = "923201111222"
    phone_b = "923203333444"

    v_a = GlobalBazarService.find_or_create_vendor(name="Shop Alpha", phone=phone_a)
    v_b = GlobalBazarService.find_or_create_vendor(name="Shop Beta", phone=phone_b)

    assert v_a["id"] != v_b["id"]

    # Add product for Shop Alpha
    prod_a = GlobalBazarService.add_product(
        vendor_id=v_a["id"],
        title="Alpha Exclusive Item",
        price=1200.0,
        stock=10
    )

    # Verify Shop Beta DOES NOT see Alpha's product in its inventory
    beta_products = GlobalBazarService.get_products(vendor_id=v_b["id"])
    beta_titles = [p["title"] for p in beta_products]
    assert "Alpha Exclusive Item" not in beta_titles

    # Verify token isolation
    tok_a = GlobalBazarService.generate_vendor_magic_token(v_a["id"], phone_a)
    tok_b = GlobalBazarService.generate_vendor_magic_token(v_b["id"], phone_b)
    assert tok_a != tok_b


def test_cod_and_gps_checkout_flow(client):
    """Verify Cash on Delivery (COD) + Live GPS Coordinates in create_order and API checkout."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    v_id = vendor["id"]

    # Test create_order directly with COD and GPS
    order = GlobalBazarService.create_order(
        vendor_id=v_id,
        customer_name="Sher Ali Chitrali",
        customer_phone="03451234567",
        items_summary="2x Pure Chitrali Walnut @ PKR 1,500",
        total_amount=3000.0,
        delivery_address="Shahi Bazar Chitral Near Polo Ground",
        order_source="storefront",
        latitude=35.85112,
        longitude=71.78654,
        payment_method="cod"
    )

    assert order is not None
    assert order["payment_method"] == "COD"
    assert abs(order["latitude"] - 35.85112) < 0.001
    assert abs(order["longitude"] - 71.78654) < 0.001
    assert "https://www.google.com/maps/dir/?api=1&destination=35.851120,71.786540" in order["maps_link"]

    # Verify order is fetched in vendor dashboard data
    dash_data = GlobalBazarService.get_vendor_dashboard_data(v_id)
    assert any(o["id"] == order["id"] for o in dash_data.get("orders", []))


def test_rider_whatsapp_forward_link_and_dashboard_card(client):
    """Verify Vendor Dashboard renders orders with COD cash to collect and 1-Click Rider WhatsApp forward."""
    vendor = GlobalBazarService.get_vendor_by_phone("923471000668")
    v_id = vendor["id"]
    token = GlobalBazarService.generate_vendor_magic_token(v_id, phone=vendor["phone"])

    # Create test order with GPS
    GlobalBazarService.create_order(
        vendor_id=v_id,
        customer_name="Karim Khan",
        customer_phone="03009876543",
        items_summary="1x Chitrali Woolen Cap @ PKR 850",
        total_amount=850.0,
        delivery_address="Ataliq Bazar, Chitral",
        order_source="storefront",
        latitude=35.8456,
        longitude=71.7912,
        payment_method="COD"
    )

    res = client.get(f"/vendor/auth/{token}", follow_redirects=False)
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # 1. Full inventory on first screen
    assert 'id="tab-inventory"' in html
    assert 'id="tab-orders"' in html
    assert 'id="tab-hisab"' in html
    assert 'id="tab-store"' in html

    # 2. 1-Click Rider WhatsApp forward button & Google Maps Route
    assert "Rider Ko WhatsApp Karein" in html
    assert "wa.me/?text=" in html
    assert "google.com/maps/dir" in html
    assert "COD Cash Collect" in html or "Cash to Collect (COD)" in html

    # 3. Pro Upgrade modal for own WhatsApp QR
    assert "Pro Upgrade" in html
    assert "proUpgradeModal" in html


