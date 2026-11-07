"""Unit tests for Appointment & Booking SQLAlchemy models (Phase 5: Booking Engine)."""

import datetime
import unittest
from flask import Flask
from database import db
from models import Organization, Appointment, Booking


class TestAppointmentModel(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            org = Organization(
                id="org_test_clinic",
                name="HealthPlus Clinic",
                slug="healthplus-clinic",
                plan_tier="pro"
            )
            db.session.add(org)
            db.session.commit()

    def test_create_and_query_appointment(self):
        """Verify Appointment creation, foreign key binding, and dictionary serialization."""
        with self.app.app_context():
            appt_time = datetime.datetime(2026, 11, 15, 14, 30)
            appt = Appointment(
                org_id="org_test_clinic",
                customer_phone="923001234567",
                customer_name="Usman Tariq",
                service_name="Dental Cleaning & Scaling",
                appointment_datetime=appt_time,
                duration_minutes=45,
                status="Pending",
                notes="Patient requested afternoon slot"
            )
            db.session.add(appt)
            db.session.commit()

            fetched = Appointment.query.filter_by(org_id="org_test_clinic").first()
            self.assertIsNotNone(fetched)
            self.assertTrue(fetched.id.startswith("apt-"))
            self.assertEqual(fetched.customer_name, "Usman Tariq")
            self.assertEqual(fetched.customer_phone, "923001234567")
            self.assertEqual(fetched.service_name, "Dental Cleaning & Scaling")
            self.assertEqual(fetched.status, "Pending")
            self.assertEqual(fetched.duration_minutes, 45)
            self.assertEqual(fetched.appointment_datetime, appt_time)

            # Relationship check
            self.assertEqual(fetched.organization.name, "HealthPlus Clinic")

            # Dictionary serialization
            d = fetched.to_dict()
            self.assertEqual(d["org_id"], "org_test_clinic")
            self.assertEqual(d["organization_id"], "org_test_clinic")
            self.assertEqual(d["appointment_datetime"], "2026-11-15 14:30:00")
            self.assertEqual(d["status"], "Pending")

    def test_booking_alias_and_status_transitions(self):
        """Verify Booking alias and status lifecycle (Pending -> Confirmed -> Cancelled)."""
        with self.app.app_context():
            booking = Booking(
                org_id="org_test_clinic",
                customer_phone="923219876543",
                service_name="Consultation",
                appointment_datetime=datetime.datetime(2026, 11, 16, 10, 0),
                status="Pending"
            )
            db.session.add(booking)
            db.session.commit()

            # Confirm
            booking.status = "Confirmed"
            db.session.commit()
            self.assertEqual(Booking.query.get(booking.id).status, "Confirmed")

            # Cancel
            booking.status = "Cancelled"
            db.session.commit()
            self.assertEqual(Appointment.query.get(booking.id).status, "Cancelled")


if __name__ == "__main__":
    unittest.main()
