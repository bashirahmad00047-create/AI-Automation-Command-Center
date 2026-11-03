# -*- coding: utf-8 -*-
"""
Automated unit & integration tests for Multi-Vendor Open Marketplace ("Chitral & Global Bazar").
Tests:
- Public Seller Free Onboarding & Listing Submission (POST /api/v1/store/seller/list-product)
- Commission Engine & Live Payout Calculation
- Multi-Vendor Lead Routing & Direct WhatsApp Links in Checkout (POST /api/v1/store/checkout)
- Platform Owner Control Panel & Aggregated Metrics (GET /api/v1/store/marketplace/sellers)
- Product Moderation & Status Toggle (POST /api/v1/store/marketplace/product/<id>/status)
- Marketplace Commission & Contact Mode Settings (GET/POST /api/v1/store/marketplace/settings)
"""
import pytest
from app import app
from models import db, Product, Lead, EcommerceOrder, SystemSetting


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with app.app_context():
            yield client


def test_public_seller_list_product(client):
    """Verify that any vendor can list a product for free with automatic commission and CRM lead logging."""
    SystemSetting.set_val("MARKETPLACE_COMMISSION_PERCENT", "10")
    payload = {
        "seller_name": "Karakoram Organic Honey",
        "seller_phone": "+923209350856",
        "seller_city": "Booni, Upper Chitral",
        "name": "Pure Mountain Sidr Honey 1kg",
        "category": "Pure Mountain Honey",
        "price": 3500,
        "description": "100% wild berry raw mountain honey from Booni valley.",
        "image_url": "https://images.unsplash.com/photo-1587049352846-4a222e784d38"
    }

    res = client.post("/api/v1/store/seller/list-product", json=payload)
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.get_data(as_text=True)}"
    data = res.get_json()
    assert data["success"] is True
    prod = data["product"]
    assert prod["seller_name"] == "Karakoram Organic Honey"
    assert "923209350856" in prod["seller_phone"]
    assert prod["price"] == 3500.0
    # 10% commission on 3500 = 350 PKR
    assert prod["platform_commission"] == 350.0
    assert prod["is_approved"] is True

    # Verify seller is logged in CRM Leads
    lead = Lead.query.filter_by(name="Karakoram Organic Honey").first()
    assert lead is not None
    assert lead.intent == "marketplace_seller"
    assert lead.lead_score == 90


def test_marketplace_sellers_aggregation(client):
    """Verify platform owner aggregated metrics: total sellers, vendor items, total commission."""
    res = client.get("/api/v1/store/marketplace/sellers")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "sellers" in data
    assert data["total_sellers"] >= 1
    assert data["total_seller_items"] >= 1
    assert "commission_percent" in data


def test_marketplace_checkout_multi_vendor_routing(client):
    """Verify customer checkout routes order, creates GPS pin, and generates direct seller WhatsApp connect links."""
    # Find a product listed by a seller
    prod = Product.query.filter(Product.seller_phone.isnot(None), Product.seller_phone != "").first()
    assert prod is not None

    checkout_payload = {
        "name": "Farhan Khan",
        "phone": "+923001234567",
        "address": "Ataliq Bazar, Chitral",
        "latitude": 35.8510,
        "longitude": 71.7864,
        "payment_method": "cod",
        "items": [
            {
                "id": prod.id,
                "name": prod.name,
                "price": prod.price,
                "quantity": 2
            }
        ]
    }

    res = client.post("/api/v1/store/checkout", json=checkout_payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["success"] is True
    assert "order_id" in data
    assert "tracking_url" in data
    assert "seller_whatsapp_links" in data
    assert len(data["seller_whatsapp_links"]) >= 1
    seller_link = data["seller_whatsapp_links"][0]
    assert "https://wa.me/" in seller_link["whatsapp_url"]
    assert seller_link["seller_phone"] == prod.seller_phone


def test_marketplace_product_moderation_and_settings(client):
    """Verify platform owner can hide/approve vendor products and configure marketplace commission."""
    prod = Product.query.filter(Product.seller_phone.isnot(None)).first()
    assert prod is not None

    # Hide product
    res = client.post(f"/api/v1/store/marketplace/product/{prod.id}/status", json={"action": "hide"})
    assert res.status_code == 200
    assert res.get_json()["is_approved"] is False

    # Approve product
    res2 = client.post(f"/api/v1/store/marketplace/product/{prod.id}/status", json={"action": "approve"})
    assert res2.status_code == 200
    assert res2.get_json()["is_approved"] is True

    # Update commission setting
    res_set = client.post("/api/v1/store/marketplace/settings", json={
        "commission_percent": 12,
        "default_mode": "smart_broker"
    })
    assert res_set.status_code == 200
    assert res_set.get_json()["commission_percent"] == 12.0
