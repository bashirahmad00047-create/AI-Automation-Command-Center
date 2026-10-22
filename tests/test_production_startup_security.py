import contextlib
import io
import os
import unittest
from unittest.mock import patch

from app import create_app
from database import db
from init_db import (
    init_and_seed_database,
    is_production_environment,
    should_seed_demo_data,
)
from models import ApiKey, Organization, User


class TestProductionStartupSecurity(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_is_production_environment_detected_from_flask_env(self):
        """Verifies FLASK_ENV=production is properly detected as a production environment."""
        with patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=False):
            self.assertTrue(is_production_environment())

        with patch.dict(os.environ, {"FLASK_ENV": "prod"}, clear=False):
            self.assertTrue(is_production_environment())

    def test_is_production_environment_detected_from_render(self):
        """Verifies presence of RENDER or RENDER_INSTANCE_ID marks environment as production."""
        with patch.dict(os.environ, {"FLASK_ENV": "", "RENDER": "true"}, clear=False):
            self.assertTrue(is_production_environment())

        with patch.dict(os.environ, {"FLASK_ENV": "", "RENDER_INSTANCE_ID": "srv-12345"}, clear=False):
            self.assertTrue(is_production_environment())

    def test_is_production_environment_false_in_development(self):
        """Verifies development environments are not misidentified as production."""
        with patch.dict(os.environ, {"FLASK_ENV": "development", "RENDER": "", "RENDER_INSTANCE_ID": ""}, clear=False):
            self.assertFalse(is_production_environment())

    def test_should_seed_demo_data_defaults_false_in_production(self):
        """Verifies demo data seeding is disabled by default in production."""
        with patch.dict(os.environ, {"FLASK_ENV": "production", "RENDER": "true", "ENABLE_DEMO_SEED": ""}, clear=False):
            self.assertFalse(should_seed_demo_data())

    def test_should_seed_demo_data_active_in_development(self):
        """Verifies demo data seeding is active for local development and staging."""
        with patch.dict(os.environ, {"FLASK_ENV": "development", "RENDER": "", "RENDER_INSTANCE_ID": "", "ENABLE_DEMO_SEED": ""}, clear=False):
            self.assertTrue(should_seed_demo_data())

    def test_should_seed_demo_data_respects_explicit_opt_in(self):
        """Verifies ENABLE_DEMO_SEED=true allows seeding in staging/testing even if FLASK_ENV is production."""
        with patch.dict(os.environ, {"FLASK_ENV": "production", "ENABLE_DEMO_SEED": "true"}, clear=False):
            self.assertTrue(should_seed_demo_data())

    def test_should_seed_demo_data_respects_explicit_disable(self):
        """Verifies DISABLE_DEMO_SEED=true turns off seeding in local development."""
        with patch.dict(os.environ, {"FLASK_ENV": "development", "DISABLE_DEMO_SEED": "true"}, clear=False):
            self.assertFalse(should_seed_demo_data())

    def test_production_startup_never_prints_passwords_or_secrets(self):
        """Verifies init_and_seed_database() in production never prints passwords, demo credentials, or API keys."""
        output_buffer = io.StringIO()
        with patch.dict(os.environ, {"FLASK_ENV": "production", "RENDER": "true", "ENABLE_DEMO_SEED": ""}, clear=False), \
             contextlib.redirect_stdout(output_buffer):
            init_and_seed_database()

        printed_output = output_buffer.getvalue()

        # Must NOT contain hardcoded demo credentials or master API keys
        self.assertNotIn("AdminSecure2026!", printed_output)
        self.assertNotIn("Operator2026!", printed_output)
        self.assertNotIn("Viewer2026!", printed_output)
        self.assertNotIn("HealthTech2026!", printed_output)
        self.assertNotIn("AuroraTea2026!", printed_output)
        self.assertNotIn("sk_live_opsflow_enterprise_prod_2026", printed_output)
        self.assertNotIn("sk_live_apex_health_gateway_2026", printed_output)
        self.assertNotIn("Demo Credentials:", printed_output)

        # Must report safe production verification
        self.assertIn("Production database schema verified", printed_output)

    def test_production_mode_does_not_create_fixed_demo_users_on_new_db(self):
        """Verifies that in production mode, fixed demo accounts are not created on an empty database."""
        # Use an isolated in-memory testing database
        test_app = create_app("testing")
        with test_app.app_context():
            db.drop_all()
            output_buffer = io.StringIO()
            with patch.dict(os.environ, {"FLASK_ENV": "production", "RENDER": "true", "ENABLE_DEMO_SEED": ""}, clear=False), \
                 contextlib.redirect_stdout(output_buffer):
                init_and_seed_database()

            # Base enterprise tenant must exist for multi-tenancy
            org = db.session.get(Organization, "org-enterprise-default")
            self.assertIsNotNone(org)

            # Fixed demo users must NOT be seeded
            self.assertIsNone(User.query.filter_by(email="admin@opsflow.io").first())
            self.assertIsNone(User.query.filter_by(email="operator@opsflow.io").first())
            self.assertIsNone(User.query.filter_by(email="viewer@opsflow.io").first())
            self.assertIsNone(User.query.filter_by(email="admin@apexhealth.internal").first())
            self.assertIsNone(User.query.filter_by(email="curator@aurorabotanicals.demo").first())

            # Fixed master API keys must NOT be seeded
            self.assertIsNone(ApiKey.query.filter_by(id="key-enterprise-master").first())
            self.assertIsNone(ApiKey.query.filter_by(id="key-apex-gateway").first())


if __name__ == "__main__":
    unittest.main()
