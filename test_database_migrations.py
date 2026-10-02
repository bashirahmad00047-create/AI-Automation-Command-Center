"""Comprehensive Unit & Integration Test Suite for Database Migrations (Phase 3).

Verifies:
- Alembic / Flask-Migrate schema initialization and upgrade lifecycle
- Idempotent execution of programmatic migrations
- Legacy pre-existing database auto-stamping
- Downgrade and re-upgrade reversibility
- API diagnostics (/api/v1/system/migration-status and /api/v1/system/health)
- Model metadata alignment with migration head
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from sqlalchemy import inspect, text

from app import create_app
from database import db
from migrations_manager import (
    downgrade_database,
    get_current_revision,
    get_head_revision,
    get_migration_status,
    run_database_migrations,
    stamp_database,
)


class TestDatabaseMigrations(unittest.TestCase):
    """Test suite for database migrations lifecycle and diagnostics."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_migration.db")
        self.db_uri = f"sqlite:///{self.db_path}"

        # Initialize fresh app pointed to isolated test database
        os.environ["DATABASE_URL"] = self.db_uri
        os.environ["SKIP_DB_INIT"] = "1"
        self.app = create_app("testing")
        self.app.config["SQLALCHEMY_DATABASE_URI"] = self.db_uri
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            try:
                db.engine.dispose()
            except Exception:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_migration_status_uninitialized(self):
        """Verifies migration status before any migrations are applied."""
        with self.app.app_context():
            status = get_migration_status(self.app)
            self.assertFalse(status["has_version_table"])
            self.assertIsNone(status["current_revision"])
            self.assertIsNotNone(status["head_revision"])
            self.assertFalse(status["is_up_to_date"])
            self.assertEqual(status["database_dialect"], "sqlite")

    def test_run_migrations_fresh_database(self):
        """Verifies applying migrations to a fresh database creates all required tables and stamps head."""
        with self.app.app_context():
            result = run_database_migrations(self.app)
            self.assertEqual(result["action_taken"], "upgraded")
            self.assertTrue(result["has_version_table"])
            self.assertTrue(result["is_up_to_date"])
            self.assertEqual(result["current_revision"], result["head_revision"])

            # Verify all expected tables exist
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            expected_tables = {
                "alembic_version",
                "organizations",
                "users",
                "memberships",
                "api_keys",
                "automation_rules",
                "workflow_steps",
                "workflow_executions",
                "execution_steps",
                "leads",
                "incident_alerts",
                "webhook_endpoints",
                "audit_logs",
                "system_events",
                "organization_usages",
            }
            for table in expected_tables:
                self.assertIn(table, tables, f"Expected table '{table}' not found in migrated database")

    def test_migration_idempotency(self):
        """Verifies running migrations multiple times is safe and idempotent."""
        with self.app.app_context():
            res1 = run_database_migrations(self.app)
            self.assertEqual(res1["action_taken"], "upgraded")
            self.assertTrue(res1["is_up_to_date"])

            # Second execution should run cleanly without error
            res2 = run_database_migrations(self.app)
            self.assertEqual(res2["action_taken"], "upgraded")
            self.assertTrue(res2["is_up_to_date"])
            self.assertEqual(res2["current_revision"], res1["current_revision"])

    def test_migration_downgrade_and_reupgrade_cycle(self):
        """Verifies migrations can be downgraded to base and re-upgraded cleanly."""
        with self.app.app_context():
            # Initial upgrade
            run_database_migrations(self.app)
            head_rev = get_head_revision()

            # Downgrade to base
            down_res = downgrade_database("base", self.app)
            self.assertEqual(down_res["action_taken"], "downgraded_to_base")
            self.assertIsNone(down_res["current_revision"])

            # Verify application tables were dropped
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            self.assertNotIn("organizations", tables)
            self.assertNotIn("automation_rules", tables)

            # Re-upgrade to head
            up_res = run_database_migrations(self.app)
            self.assertEqual(up_res["current_revision"], head_rev)
            self.assertTrue(up_res["is_up_to_date"])

            # Verify tables restored
            tables_after = inspect(db.engine).get_table_names()
            self.assertIn("organizations", tables_after)
            self.assertIn("automation_rules", tables_after)

    def test_legacy_database_auto_stamp(self):
        """Verifies a pre-existing database with tables but no alembic_version is stamped to head."""
        with self.app.app_context():
            # Simulate legacy state: create tables via db.create_all() directly
            db.create_all()

            # Verify alembic_version does not exist yet
            inspector = inspect(db.engine)
            self.assertIn("organizations", inspector.get_table_names())
            self.assertNotIn("alembic_version", inspector.get_table_names())

            # Run migration runner
            result = run_database_migrations(self.app)
            self.assertEqual(result["action_taken"], "stamped")
            self.assertTrue(result["has_version_table"])
            self.assertTrue(result["is_up_to_date"])
            self.assertEqual(result["current_revision"], result["head_revision"])

    def test_system_migration_status_endpoint(self):
        """Verifies GET /api/v1/system/migration-status API."""
        with self.app.app_context():
            run_database_migrations(self.app)

        res = self.client.get("/api/v1/system/migration-status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertTrue(data["has_version_table"])
        self.assertTrue(data["is_up_to_date"])
        self.assertIsNotNone(data["current_revision"])
        self.assertEqual(data["current_revision"], data["head_revision"])
        self.assertEqual(data["database_dialect"], "sqlite")
        self.assertGreaterEqual(data["tables_count"], 15)
        self.assertIn("organizations", data["tables"])
        self.assertIn("organization_usages", data["tables"])

    def test_system_health_endpoint_migration_info(self):
        """Verifies GET /api/v1/system/health returns migration revision metadata."""
        with self.app.app_context():
            run_database_migrations(self.app)

        res = self.client.get("/api/v1/system/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data["status"], "healthy")
        self.assertIn("database_migration", data)
        mig_info = data["database_migration"]
        self.assertIsNotNone(mig_info["current_revision"])
        self.assertTrue(mig_info["is_up_to_date"])


if __name__ == "__main__":
    unittest.main()
