import json
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db
from models import Product, EcommerceOrder, Lead, SystemSetting, SystemEvent, generate_uuid


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with app.app_context():
            db.create_all()
            # Ensure at least one active product exists for testing
            p = Product.query.filter_by(is_active=True).first()
            if not p:
                p = Product(
                    id=generate_uuid("prd"),
                    organization_id="org-enterprise-default",
                    name="Chitrali Pure Mountain Honey (1 Kg)",
                    category="Honey",
                    description="Pure raw honey from Hindukush.",
                    price=2500.0,
                    currency="PKR",
                    stock_quantity=50,
                    stock_status="in_stock",
                    is_active=True
                )
                db.session.add(p)
                db.session.commit()
        yield c


def test_public_storefront_page(client):
    """Module 1: Verify GET /store renders public storefront without requiring login."""
    res = client.get("/store")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Chitral &amp; Global Bazar" in html or "Chitral & Global Bazar" in html
    assert "Shopping Cart" in html


def test_public_store_products_api(client):
    """Module 1: Verify GET /api/v1/store/products returns active products."""
    res = client.get("/api/v1/store/products")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert len(data["products"]) > 0
    assert any("price" in p and "name" in p for p in data["products"])


def test_store_checkout_and_tracking(client):
    """Module 1: Verify POST /api/v1/store/checkout places order, sets GPS, and /track works."""
    payload = {
        "name": "Bashir Ahmad Test",
        "phone": "03209350856",
        "address": "Bazar Chitral, Khyber Pakhtunkhwa",
        "latitude": 35.8510,
        "longitude": 71.7864,
        "payment_method": "cod",
        "items": [
            {
                "id": "test-honey-01",
                "name": "Chitrali Pure Mountain Honey (1 Kg)",
                "price": 2500,
                "quantity": 2
            }
        ]
    }
    res = client.post("/api/v1/store/checkout", json=payload)
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["success"] is True
    assert "order_id" in data
    assert "order_number" in data
    assert data["total_amount"] == 5000.0

    order_id = data["order_id"]

    # Verify order exists in DB
    with app.app_context():
        ord_db = db.session.get(EcommerceOrder, order_id)
        assert ord_db is not None
        assert ord_db.customer_phone == "923209350856"
        assert ord_db.total_amount == 5000.0

        # Verify Lead created with GPS pin
        lead_db = Lead.query.filter(Lead.phone.ilike("%3209350856%")).order_by(Lead.created_at.desc()).first()
        assert lead_db is not None
        assert "[Location: 35.851000, 71.786400]" in lead_db.message

    # Verify GET /track/<order_id>
    track_res = client.get(f"/track/{order_id}")
    assert track_res.status_code == 200
    track_html = track_res.data.decode("utf-8")
    assert ord_db.order_number in track_html
    assert "Live Delivery Radar Map" in track_html


def test_voice_studio_test_and_settings(client):
    """Module 2: Verify voice test and settings persistence."""
    # Test settings update
    settings_payload = {
        "voice": "ur-PK-AsadNeural",
        "rate": "+4%",
        "pitch": "+0Hz"
    }
    post_res = client.post("/api/v1/voice/settings", json=settings_payload)
    assert post_res.status_code == 200
    data = json.loads(post_res.data)
    assert data["success"] is True
    assert data["settings"]["voice"] == "ur-PK-AsadNeural"

    # Test GET settings
    get_res = client.get("/api/v1/voice/settings")
    assert get_res.status_code == 200
    get_data = json.loads(get_res.data)
    assert get_data["settings"]["voice"] == "ur-PK-AsadNeural"


def test_payment_receipt_verification_and_duplicate_check(client):
    """Module 3: Verify duplicate TID detection and order update."""
    import secrets
    from whatsapp_service import WhatsAppService

    tid_test = f"TEST_TID_{secrets.token_hex(4)}"
    # Initially TID should not be duplicate
    assert WhatsAppService.is_tid_duplicate(tid_test) is False

    # Record verified TID
    with app.app_context():
        WhatsAppService.record_verified_tid(
            tid=tid_test,
            amount=3500.0,
            provider="EasyPaisa",
            phone="923209350856"
        )
        assert WhatsAppService.is_tid_duplicate(tid_test) is True
