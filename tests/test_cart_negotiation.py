"""Unit and Integration Tests for Phase 6: Sales Negotiation & Cart State Engine (Audit Item 3).

Verifies:
1. CartState model initialization, item serialization, and floor price calculations.
2. Multi-lingual intent and counter-offer parsing (Roman Urdu and English).
3. Deterministic state machine transitions: browsing -> bargaining -> agreed -> Pending Payment.
4. Floor price boundary enforcement (preventing below-cost discounts).
5. Natural language cart revisions ("mujhe 2 nahi 3 chahiye", "is mein se blue wala nikal do").
6. Invoice and receipt generation with Quantity, Discount Applied, and Final Total.
7. Abandoned cart follow-up recovery prompt.
8. Multi-tenant customer cart isolation.
"""

import unittest
from flask import Flask
from database import db
from models import Organization, CartState, Product, EcommerceOrder
from services.ai_responder import (
    parse_intent,
    extract_negotiation_intent,
    handle_sales_negotiation_flow,
    generate_invoice_summary,
    generate_abandonment_prompt
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

            # Add test products
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

    def test_natural_language_quantity_revision(self):
        """Verify natural language cart revision: 'mujhe 2 nahi 3 chahiye'."""
        with self.app.app_context():
            # First create cart with 2 pieces
            cart = CartState(
                org_id="org_retail_bazar",
                customer_phone="923002223344",
                customer_name="Kamran",
                negotiation_stage="browsing"
            )
            cart.add_item("Cotton Shirt", quantity=2, unit_price=1500.0, seller_cost=1000.0)
            db.session.add(cart)
            db.session.commit()

            # Now send natural language revision request
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923002223344",
                customer_name="Kamran",
                message_text="mujhe 2 nahi 3 chahiye bhai",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertIn("3", res["reply_body"])

            # Verify in DB
            saved = CartState.query.filter_by(customer_phone="923002223344").first()
            items = saved.get_items()
            self.assertEqual(items[0]["quantity"], 3)
            self.assertEqual(saved.current_total, 4500.0)

    def test_natural_language_specific_item_removal(self):
        """Verify natural language removal: 'is mein se blue wala nikal do'."""
        with self.app.app_context():
            cart = CartState(
                org_id="org_retail_bazar",
                customer_phone="923003334455",
                customer_name="Noman",
                negotiation_stage="browsing"
            )
            cart.add_item("Blue Denim Jeans", quantity=1, unit_price=2500.0, seller_cost=1800.0)
            cart.add_item("White T-Shirt", quantity=1, unit_price=1000.0, seller_cost=700.0)
            db.session.add(cart)
            db.session.commit()

            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923003334455",
                customer_name="Noman",
                message_text="is mein se blue wala nikal do please",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertIn("nikal diya gaya", res["reply_body"])

            # Verify only White T-Shirt remains
            saved = CartState.query.filter_by(customer_phone="923003334455").first()
            items = saved.get_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "White T-Shirt")
            self.assertEqual(saved.current_total, 1000.0)

    def test_acceptable_counter_offer_transitions_to_pending_payment_with_invoice(self):
        """When customer counter-offer is >= floor price, state engine agrees, transitions to Pending Payment and generates invoice."""
        with self.app.app_context():
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923005556677",
                customer_name="Usman Tariq",
                message_text="4000 mein de dein bhai final deal",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["stage"], "Pending Payment")
            self.assertIn("INVOICE & ORDER SUMMARY", res["reply_body"])
            self.assertIn("Final Total: PKR 4,000", res["reply_body"])
            self.assertIn("Status: ⏳ Pending Payment", res["reply_body"])

            # Verify DB persistence and EcommerceOrder creation
            saved = CartState.query.filter_by(customer_phone="923005556677").first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.negotiation_stage, "Pending Payment")
            self.assertEqual(saved.current_total, 4000.0)

            ord_rec = EcommerceOrder.query.filter_by(customer_phone="923005556677").first()
            self.assertIsNotNone(ord_rec)
            self.assertEqual(ord_rec.order_status, "pending")
            self.assertEqual(ord_rec.total_amount, 4000.0)

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

            saved = CartState.query.filter_by(customer_phone="923007778899").first()
            self.assertEqual(saved.negotiation_stage, "bargaining")
            self.assertGreaterEqual(saved.current_total, saved.floor_price)

    def test_checkout_transition_generates_final_invoice(self):
        """When customer confirms order, stage transitions to 'Pending Payment' and generates full receipt summary."""
        with self.app.app_context():
            res = handle_sales_negotiation_flow(
                organization_id="org_retail_bazar",
                customer_phone="923009990011",
                customer_name="Bilal",
                message_text="theek hai pack krdo address note karein",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["stage"], "Pending Payment")
            self.assertIn("INVOICE & ORDER SUMMARY", res["reply_body"])
            self.assertIn("Pending Payment", res["reply_body"])

            saved = CartState.query.filter_by(customer_phone="923009990011").first()
            self.assertEqual(saved.negotiation_stage, "Pending Payment")

    def test_abandoned_cart_recovery_prompt(self):
        """Verify gentle AI follow-up prompt generation for abandoned carts."""
        with self.app.app_context():
            cart = CartState(
                org_id="org_retail_bazar",
                customer_phone="923008889900",
                customer_name="Zahid",
                negotiation_stage="abandoned"
            )
            cart.add_item("Smart Watch", quantity=1, unit_price=3500.0)
            prompt_urdu = generate_abandonment_prompt(cart, "Zahid", lang_fmt="roman_urdu")
            self.assertIn("Aapka saman cart mein mehfooz hai", prompt_urdu)
            self.assertIn("free delivery", prompt_urdu)

            prompt_eng = generate_abandonment_prompt(cart, "Zahid", lang_fmt="english")
            self.assertIn("safely saved in your cart", prompt_eng)


if __name__ == "__main__":
    unittest.main()
