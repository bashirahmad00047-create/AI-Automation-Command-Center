"""Tests for Feature 1 (WhatsApp-Driven Catalog Control & Product Image Sending),
Feature 2 (Humanized Conversational AI + Smart Catalog Pitch), and
Feature 3 (Safe Urdu Voice Humanization).
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from database import db
from models import Organization, Product
from whatsapp_service import WhatsAppService


@pytest.fixture(scope="module")
def app():
    test_app = create_app("testing")
    with test_app.app_context():
        db.create_all()
        # Ensure default org
        org = Organization.query.filter_by(id="org-enterprise-default").first()
        if not org:
            org = Organization(
                id="org-enterprise-default",
                name="OpsFlow Cloud Enterprise",
                slug="opsflow-enterprise",
                is_active=True
            )
            db.session.add(org)
            db.session.commit()
        yield test_app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def test_whatsapp_catalog_add_command_pipe_format(app):
    """WhatsApp admin #add command with pipe format parses, saves Product in DB, and confirms."""
    with app.app_context():
        cmd = "#add Wireless Earbuds Pro | 4500 | 30 | Electronics | High fidelity bluetooth earbuds"
        res = WhatsAppService.handle_whatsapp_catalog_command(
            organization_id="org-enterprise-default",
            sender_phone="923001234567",
            message_body=cmd
        )
        assert res is not None
        assert res["success"] is True
        assert res["action"] == "catalog_updated"
        assert "Wireless Earbuds Pro" in res["reply_body"]
        assert "4,500.00" in res["reply_body"]

        # Verify product exists in database table
        p = Product.query.filter_by(name="Wireless Earbuds Pro", organization_id="org-enterprise-default").first()
        assert p is not None
        assert p.price == 4500.0
        assert p.stock_quantity == 30
        assert p.category == "Electronics"
        assert p.is_active is True


def test_whatsapp_catalog_add_command_with_image(app):
    """WhatsApp admin #add command with attached image saves image_url into catalog."""
    with app.app_context():
        cmd = "Add product: Smart Watch Ultra | 7500 | 15 | Wearables"
        test_img_url = "https://images.unsplash.com/photo-smart-watch.jpg"
        res = WhatsAppService.handle_whatsapp_catalog_command(
            organization_id="org-enterprise-default",
            sender_phone="923001234567",
            message_body=cmd,
            media_url=test_img_url
        )
        assert res is not None
        assert res["success"] is True
        assert res["image_url"] == test_img_url

        p = Product.query.filter_by(name="Smart Watch Ultra", organization_id="org-enterprise-default").first()
        assert p is not None
        assert p.price == 7500.0
        assert p.image_url == test_img_url


def test_whatsapp_catalog_add_command_natural_format(app):
    """WhatsApp natural command '#add Leather Wallet 1800' parses name and price correctly."""
    with app.app_context():
        cmd = "#add Leather Wallet 1800"
        res = WhatsAppService.handle_whatsapp_catalog_command(
            organization_id="org-enterprise-default",
            sender_phone="923001234567",
            message_body=cmd
        )
        assert res is not None
        assert res["success"] is True

        p = Product.query.filter_by(name="Leather Wallet", organization_id="org-enterprise-default").first()
        assert p is not None
        assert p.price == 1800.0


def test_find_catalog_product_by_inquiry(app):
    """Customer asking about 'Earbuds' or 'Smart Watch' locates the exact catalog product."""
    with app.app_context():
        matched = WhatsAppService.find_catalog_product_by_inquiry(
            organization_id="org-enterprise-default",
            query_text="Aap ke paas Wireless Earbuds Pro available hain?"
        )
        assert matched is not None
        assert "Earbuds" in matched.name


def test_auto_extract_catalog_product_from_card_text(app):
    """Outbound catalog card text auto-extracts product and provides image_url."""
    with app.app_context():
        card_text = "🛍️ *Wireless Earbuds Pro*\n🏷️ Price: *PKR 4,500*\n📦 SKU: `PRD-123`"
        prod = WhatsAppService._extract_catalog_product_from_text(card_text, organization_id="org-enterprise-default")
        assert prod is not None
        assert prod.name == "Wireless Earbuds Pro"


def test_live_catalog_grounding_context(app):
    """Live product catalog context includes active products, PKR prices, stock, and descriptions."""
    with app.app_context():
        ctx = WhatsAppService.get_product_catalog_context(organization_id="org-enterprise-default")
        assert "LIVE PRODUCT CATALOG & INVENTORY GROUNDING" in ctx
        assert "Wireless Earbuds Pro" in ctx
        assert "PKR 4,500.00" in ctx
        assert "Smart Watch Ultra" in ctx


def test_voice_preprocessor_markdown_and_fillers():
    """Voice preprocessor strips markdown symbols and injects natural conversational pause markers."""
    raw_script = "Salam! *Wireless Earbuds Pro* ki price #PKR 4500 hai. - High bass audio."
    processed = WhatsAppService.preprocess_text_for_human_speech(raw_script, language="ur")
    assert "*" not in processed
    assert "#" not in processed
    assert "السلام علیکم،" in processed or "سلام" in processed
    assert "روپے" in processed
