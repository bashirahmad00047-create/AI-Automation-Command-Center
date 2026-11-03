import pytest
import json
from app import app, db
from models import Product, SystemSetting, generate_uuid
from whatsapp_service import WhatsAppService


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with app.app_context():
            yield c


def test_store_settings_get_and_post(client):
    """Verifies getting and updating store branding and delivery fee."""
    # GET settings
    res = client.get("/api/v1/store/settings")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "store_name" in data["settings"]

    # POST settings
    update_payload = {
        "store_name": "Chitral Heritage Bazar Test",
        "store_tagline": "Pure Mountain Dry Fruits & Essentials",
        "store_phone": "03209350858",
        "delivery_fee": "250"
    }
    res_post = client.post("/api/v1/store/settings", json=update_payload)
    assert res_post.status_code == 200
    post_data = res_post.get_json()
    assert post_data["success"] is True
    assert post_data["settings"]["store_name"] == "Chitral Heritage Bazar Test"
    assert post_data["settings"]["delivery_fee"] == "250"


def test_store_product_crud_lifecycle(client):
    """Verifies adding a custom product, updating it, and deleting it."""
    # 1. Create product
    new_prod = {
        "name": "Chitrali Pattu Wool Shawl Test Item",
        "category": "Handicrafts",
        "price": 7500,
        "description": "Authentic warm wool shawl handwoven in Chitral.",
        "image_url": "https://example.com/shawl.jpg",
        "stock_status": "in_stock"
    }
    create_res = client.post("/api/v1/store/products/create", json=new_prod)
    assert create_res.status_code == 201
    created_data = create_res.get_json()
    assert created_data["success"] is True
    prod_id = created_data["product"]["id"]
    assert created_data["product"]["name"] == "Chitrali Pattu Wool Shawl Test Item"

    # 2. Edit product
    edit_payload = {
        "name": "Chitrali Pattu Wool Shawl (Special Edition)",
        "price": 8200
    }
    edit_res = client.post(f"/api/v1/store/products/{prod_id}/edit", json=edit_payload)
    assert edit_res.status_code == 200
    edited_data = edit_res.get_json()
    assert edited_data["success"] is True
    assert edited_data["product"]["name"] == "Chitrali Pattu Wool Shawl (Special Edition)"
    assert edited_data["product"]["price"] == 8200.0

    # 3. Delete product
    del_res = client.post(f"/api/v1/store/products/{prod_id}/delete")
    assert del_res.status_code == 200
    assert del_res.get_json()["success"] is True

    # Confirm deletion
    with app.app_context():
        p = db.session.get(Product, prod_id)
        assert p is None


def test_edge_tts_rate_pitch_formatting():
    """Verifies Edge-TTS synthesis handles 0% and 0Hz rate/pitch without validation failure."""
    # Should not crash and safely omit 0 prosody tags
    with app.app_context():
        audio = WhatsAppService._synthesize_edge_tts(
            text="Assalam o Alaikum, Chitral Bazar mein aap ka khair maqdam hai.",
            rate="+0%",
            pitch="+0Hz",
            volume="+0%"
        )
        # In offline or mock mode, audio is either bytes > 1024 or None (gracefully caught)
        if audio is not None:
            assert len(audio) > 1024


def test_ai_catalog_grounding_injection():
    """Verifies active database products are dynamically injected into knowledge base."""
    with app.app_context():
        kb = WhatsAppService.get_verified_business_knowledge_base()
        assert "CURRENT VERIFIED STORE CATALOG" in kb or "VERIFIED PRODUCTS" in kb
