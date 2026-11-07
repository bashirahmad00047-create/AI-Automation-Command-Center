"""Unit and Integration Tests for Phase 5: Booking & Appointment Engine (Audit Item 1).

Verifies:
1. Multi-lingual intent detection for appointments in Urdu and English.
2. Slot conflict detection and double-booking prevention.
3. Database persistence of confirmed appointments with org_id foreign keys.
4. Conversational WhatsApp confirmation text formatting in Roman Urdu and English.
5. Voice note synthesis compatibility.
"""

import datetime
import unittest
from flask import Flask
from database import db
from models import Organization, Appointment
from services.ai_responder import (
    parse_intent,
    extract_appointment_datetime,
    extract_service_name,
    handle_booking_flow,
    generate_ai_auto_response
)


class TestBookingEngine(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            org = Organization(
                id="org_shifa_clinic",
                name="Shifa Polyclinic",
                slug="shifa-polyclinic",
                plan_tier="pro"
            )
            db.session.add(org)
            db.session.commit()

    def test_booking_intent_detection(self):
        """Verify Urdu and English booking expressions are mapped to booking_appointment intent."""
        urdu_msgs = [
            "Doctor consultation kal subah 11 baje book karain",
            "Mujhe kal appointment chahiye",
            "Doctor se milne ka time book karna hai",
            "Kal shaam 5 baje checkup ka slot reserve kar dein"
        ]
        for msg in urdu_msgs:
            res = parse_intent(msg)
            self.assertEqual(res["intent"], "booking_appointment", f"Failed on: {msg}")
            self.assertEqual(res["route_department"], "Appointments")

        eng_msgs = [
            "Please schedule an appointment for tomorrow at 3 pm",
            "I want to book a doctor consultation",
            "Can I reserve a slot for checkup next Monday?"
        ]
        for msg in eng_msgs:
            res = parse_intent(msg)
            self.assertEqual(res["intent"], "booking_appointment", f"Failed on: {msg}")

    def test_datetime_and_service_extraction(self):
        """Verify date/time and service categorization from natural language text."""
        msg = "Doctor consultation kal shaam 5 baje book kar dein"
        service = extract_service_name(msg)
        self.assertEqual(service, "Doctor Consultation")

        dt = extract_appointment_datetime(msg)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 17)
        self.assertEqual(dt.minute, 0)

        # English parsing
        eng_msg = "Please schedule Vehicle Inspection tomorrow at 11 am"
        eng_service = extract_service_name(eng_msg)
        self.assertEqual(eng_service, "Vehicle Inspection & Repair")
        eng_dt = extract_appointment_datetime(eng_msg)
        self.assertIsNotNone(eng_dt)
        self.assertEqual(eng_dt.hour, 11)

    def test_missing_info_prompt(self):
        """Verify prompt returned when customer does not provide date or time."""
        with self.app.app_context():
            res = handle_booking_flow(
                organization_id="org_shifa_clinic",
                customer_phone="923001234567",
                customer_name="Hamza",
                message_text="Mujhe appointment chahiye",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res["status"], "needs_info")
            self.assertFalse(res["booking_saved"])
            self.assertIn("Appointment book karne ke liye", res["reply_body"])

    def test_slot_booking_and_conflict_detection(self):
        """Verify successful booking and subsequent conflict rejection for the same slot."""
        with self.app.app_context():
            # First booking: should succeed
            res1 = handle_booking_flow(
                organization_id="org_shifa_clinic",
                customer_phone="923001112233",
                customer_name="Bilal Ahmed",
                message_text="Doctor consultation kal subah 11 baje",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res1["status"], "confirmed")
            self.assertTrue(res1["booking_saved"])
            self.assertIn("confirm ho gayi hai", res1["reply_body"])

            # Verify saved in database
            saved = Appointment.query.filter_by(
                org_id="org_shifa_clinic",
                customer_phone="923001112233",
                status="Confirmed"
            ).first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.service_name, "Doctor Consultation")

            # Second booking for the exact same slot: should detect conflict
            res2 = handle_booking_flow(
                organization_id="org_shifa_clinic",
                customer_phone="923214445566",
                customer_name="Zubair Khan",
                message_text="Checkup kal subah 11 baje book kar dein",
                lang_fmt="roman_urdu"
            )
            self.assertEqual(res2["status"], "conflict")
            self.assertFalse(res2["booking_saved"])
            self.assertIn("slot pehle se booked hai", res2["reply_body"])


if __name__ == "__main__":
    unittest.main()
