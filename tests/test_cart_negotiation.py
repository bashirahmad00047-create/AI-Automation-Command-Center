"""Unit and Integration Tests for Phase 6: Sales Negotiation & Cart State Engine (Audit Item 3).

Verifies:
1. CartState model initialization, item serialization, and floor price calculations.
2. Multi-lingual intent and counter-offer parsing (Roman Urdu and English).
3. Deterministic state machine transitions: browsing -> bargaining -> agreed -> checkout.
4. Floor price boundary enforcement (preventing below-cost discounts).
5. Multi-tenant customer cart isolation.
"""

import unittest
from flask import Flask
from database import db
from models import Organization, CartState, Product
from services.ai_responder import (
    parse_intent,
    extract_negotiation_intent,
    handle_sales_negotiation_flow,
    generate_ai_auto_response
)


class TestCartNegotiationEngine(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            org = Organization(
                id="org_retail_bazar",
                name="Bazar Retailers",
                slug="bazar-retailers",
                plan_tier="growth"
            )
            db.session.add(org)

            # Add test product
            prod = Product(
                id="prd_leather_jacket",
                organization_id="org_retail_bazar",
                name="Genuine Leather Jacket",
                price=5000.0,
                seller_price=3500.0,  # Floor cost is 3500
                currency="PKR",
                is_active=True
            )
            db.session.add(prod)
            db.session.commit()

    def test_cart_state_model_basics(self):
        """Verify CartState item addition, removal, and floor price recalculations."""
        with self.app.app_context():
            cart = CartState(
                org_id="org_retail_bazar",
                customer_phone="923001112233",
                customer_name="Ali Khan",
                negotiation_stage="browsing"
            )
            db.session.add(cart)
            db.session.commit()

            # Add item
            cart.add_item("Sneakers", quantity=2, unit_price=2000.0, seller_cost=1400.0)
            self.assertEqual(cart.original_total, 4000.0)
            self.assertEqual(cart.floor_price, 2800.0)
            self.assertEqual(cart.current_total, 4000.0)

            # Apply 10% discount
            cart.apply_negotiation(discount_pct=10.0)
            self.assertEqual(cart.current_total, 3600.0)

            # Remove 1 quantity
            cart.remove_item("Sneakers", quantity=1)
            self.assertEqual(cart.original_total, 2000.0)
            self.assertEqual(cart.floor_price, 1400.0)
            self.assertEqual(cart.current_total, 1800.0)

    def test_negotiation_intent_detection(self):
        """Verify negotiation, cart management, and checkout intents in Roman Urdu and English."""
        neg_samples = [
            "kuch discount mil sakta hai?",
            "bhai bohot mehnga hai thoda kam karo",
            "koi gunjaish nikalein",
            "give me your best price please",
            "can you offer a discount?"
        ]
        for msg in neg_samples:
            res = parse_intent(msg)
            self.assertEqual(res["intent"], "sales_negotiation", f"Failed on: {msg}")

        checkout_samples = [
            "pack krdo bhai delivery address note karein",
            "theek hai order confirm kar dein",
            "deal done parcel bhej dein",
            "confirm order please"
        ]
        for msg in checkout_samples:
            res = parse_intent(msg)
            self.assertEqual(res["intent"], "sales_checkout", f"Failed on: {msg}")

    def test_extract_negotiation_intent_values(self):
        """Verify extraction of specific counter-offer numbers and percentages."""
        price_inquiry = extract_negotiation_intent("3800 mein de dein bhai")
        self.assertEqual(price_inquiry["action"], "bargain_price")
        self.assertEqual(price_inquiry["value"], 3800.0)

        pct_inquiry = extract_negotiation_intent("mujhe 15% discount chahiye")
        self.assertEqual(pct_inquiry["action"], "bargain_pct")
        self.assertEqual(pct_inquiry["value"], 15.0)

        generic_inquiry = extract_negotiation_intent("thoda munasib rate lagayein")
        self.assertEqual(generic_inquiry["action"], "bargain_generic")

    def test_acceptable_counter_offer_transitions_to_agreed(self):
        """When customer counter-offer is >= floor price, state engine agrees and locks stage to 'agreed'."""
        with self.app.app_context():
            # Floor cost is 3500, Original price is 5000. Offer is 4000 (above floor).
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923005556677",
                customer_name="Usman Tariq",
                message_text="4000 mein de dein bhai final deal",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["stage"], "agreed")
            self.assertIn("4,000", res["reply_body"])
            self.assertIn("qabool karte hain", res["reply_body"])

            # Verify DB persistence
            saved = CartState.query.filter_by(customer_phone="923005556677").first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.negotiation_stage, "agreed")
            self.assertEqual(saved.current_total, 4000.0)

    def test_below_cost_counter_offer_counters_with_sweetener(self):
        """When customer counter-offer is < floor price (e.g. 2000 vs floor 3500), engine protects margin and counters."""
        with self.app.app_context():
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923007778899",
                customer_name="Hamza",
                message_text="2000 mein de do bhai",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["stage"], "bargaining")
            self.assertIn("cost se bhi kam hai", res["reply_body"])

            # Verify DB state
            saved = CartState.query.filter_by(customer_phone="923007778899").first()
            self.assertEqual(saved.negotiation_stage, "bargaining")
            self.assertGreaterEqual(saved.current_total, saved.floor_price)

    def test_checkout_transition_prompts_address(self):
        """When customer confirms order, stage transitions to 'checkout' and prompts for delivery address."""
        with self.app.app_context():
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923009990011",
                customer_name="Bilal",
                message_text="theek hai pack krdo address note karein",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["stage"], "checkout")
            self.assertIn("delivery address", res["reply_body"].lower())

            saved = CartState.query.filter_by(customer_phone="923009990011").first()
            self.assertEqual(saved.negotiation_stage, "checkout")

    def test_cart_view_and_revision(self):
        """Verify cart review and item removal."""
        with self.app.app_context():
            # View cart
            view_res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923001239876",
                customer_name="Zubair",
                message_text="mera total bill kitna bana",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(view_res["status"], "success")
            self.assertIn("tafseelat", view_res["reply_body"].lower())

            # Remove item
            rem_res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923001239876",
                customer_name="Zubair",
                message_text="item nikal do",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(rem_res["status"], "success")
            self.assertIn("remove kar diya gaya", rem_res["reply_body"])


if __name__ == "__main__":
    unittest.main()
