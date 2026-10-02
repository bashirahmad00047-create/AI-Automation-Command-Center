"""Database Migration Management Service for OpsFlow Multi-Tenant SaaS Platform.

Provides programmatic and CLI utilities to:
- Auto-run pending database migrations on application startup
- Detect and stamp unmanaged existing databases
- Report database migration status, current revision, and head revision
- Downgrade or upgrade database revisions safely
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask, current_app
from sqlalchemy import inspect, text

from database import db

logger = logging.getLogger("opsflow.migrations")


def get_alembic_config(directory: Optional[str] = None) -> AlembicConfig:
    """Builds and returns an Alembic Config object pointing to the migrations directory."""
    base_dir = os.path.abspath(os.path.dirname(__file__))
    mig_dir = directory or os.path.join(base_dir, "migrations")
    ini_path = os.path.join(mig_dir, "alembic.ini")

    if not os.path.exists(ini_path):
        ini_path = os.path.join(base_dir, "alembic.ini")

    config = AlembicConfig(ini_path if os.path.exists(ini_path) else None)
    config.set_main_option("script_location", mig_dir)
    return config


def get_current_revision(app: Optional[Flask] = None) -> Optional[str]:
    """Returns the current database revision ID, or None if not initialized."""
    target_app = app or (current_app._get_current_object() if current_app else None)
    if target_app:
        with target_app.app_context():
            return _inspect_current_revision()
    return _inspect_current_revision()


def _inspect_current_revision() -> Optional[str]:
    inspector = inspect(db.engine)
    if "alembic_version" not in inspector.get_table_names():
        return None
    with db.engine.connect() as conn:
        res = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        return res[0] if res else None


def get_head_revision(directory: Optional[str] = None) -> Optional[str]:
    """Returns the latest head revision defined in the migrations directory."""
    config = get_alembic_config(directory)
    script_dir = ScriptDirectory.from_config(config)
    return script_dir.get_current_head()


def get_migration_status(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Returns complete diagnostic status of database migrations."""
    target_app = app or (current_app._get_current_object() if current_app else None)

    def _collect_status():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        current_rev = _inspect_current_revision()
        head_rev = get_head_revision()
        dialect_name = db.engine.dialect.name

        has_version_table = "alembic_version" in tables
        is_up_to_date = (current_rev == head_rev) and (head_rev is not None)

        return {
            "has_version_table": has_version_table,
            "current_revision": current_rev,
            "head_revision": head_rev,
            "is_up_to_date": is_up_to_date,
            "database_dialect": dialect_name,
            "tables_count": len(tables),
            "tables": sorted(tables),
        }

    if target_app:
        with target_app.app_context():
            return _collect_status()
    return _collect_status()


def run_database_migrations(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Safely runs pending database migrations or stamps legacy pre-existing databases."""
    import flask_migrate

    target_app = app or (current_app._get_current_object() if current_app else None)

    def _execute():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        has_version_table = "alembic_version" in tables
        has_existing_app_tables = "organizations" in tables

        if not has_version_table and has_existing_app_tables:
            # Pre-existing database without Alembic tracking: stamp to head
            logger.info("Existing database schema detected without alembic_version; stamping to head.")
            flask_migrate.stamp()
            action = "stamped"
        else:
            # New or version-tracked database: upgrade to latest migration
            logger.info("Executing database migration upgrade to head...")
            flask_migrate.upgrade()
            action = "upgraded"

        status = get_migration_status()
        status["action_taken"] = action
        return status

    if target_app:
        with target_app.app_context():
            return _execute()
    return _execute()


def downgrade_database(target_revision: str = "base", app: Optional[Flask] = None) -> Dict[str, Any]:
    """Reverts database migrations back to the target revision."""
    import flask_migrate

    target_app = app or (current_app._get_current_object() if current_app else None)

    def _execute():
        flask_migrate.downgrade(revision=target_revision)
        status = get_migration_status()
        status["action_taken"] = f"downgraded_to_{target_revision}"
        return status

    if target_app:
        with target_app.app_context():
            return _execute()
    return _execute()


def stamp_database(revision: str = "head", app: Optional[Flask] = None) -> Dict[str, Any]:
    """Stamps database with specified revision without running SQL migration scripts."""
    import flask_migrate

    target_app = app or (current_app._get_current_object() if current_app else None)

    def _execute():
        flask_migrate.stamp(revision=revision)
        status = get_migration_status()
        status["action_taken"] = f"stamped_{revision}"
        return status

    if target_app:
        with target_app.app_context():
            return _execute()
    return _execute()
