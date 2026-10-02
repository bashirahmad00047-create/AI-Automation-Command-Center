"""CLI Entrypoint for OpsFlow Database Migrations.

Usage:
    python migrate.py upgrade [revision]
    python migrate.py downgrade [revision]
    python migrate.py stamp [revision]
    python migrate.py status
    python migrate.py current
    python migrate.py heads
"""

from __future__ import annotations

import argparse
import json
import sys

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


def main():
    parser = argparse.ArgumentParser(description="OpsFlow Database Migrations CLI")
    subparsers = parser.add_subparsers(dest="command", help="Migration command")

    # upgrade
    p_up = subparsers.add_parser("upgrade", help="Upgrade database to head or specified revision")
    p_up.add_argument("revision", nargs="?", default="head", help="Target revision (default: head)")

    # downgrade
    p_down = subparsers.add_parser("downgrade", help="Downgrade database to base or specified revision")
    p_down.add_argument("revision", nargs="?", default="-1", help="Target revision (default: -1)")

    # stamp
    p_stamp = subparsers.add_parser("stamp", help="Stamp database with revision without applying changes")
    p_stamp.add_argument("revision", nargs="?", default="head", help="Revision to stamp (default: head)")

    # status
    subparsers.add_parser("status", help="Show full migration status and table inventory")

    # current
    subparsers.add_parser("current", help="Show current applied database revision")

    # heads
    subparsers.add_parser("heads", help="Show available head revisions")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    app = create_app()

    with app.app_context():
        if args.command == "upgrade":
            print(f"[*] Upgrading database to '{args.revision}'...")
            res = run_database_migrations(app)
            print(f"[OK] Upgrade complete. Current revision: {res.get('current_revision')}")
            print(f"     Status: {'Up to date' if res.get('is_up_to_date') else 'Pending migrations'}")

        elif args.command == "downgrade":
            print(f"[*] Downgrading database to '{args.revision}'...")
            res = downgrade_database(args.revision, app)
            print(f"[OK] Downgrade complete. Current revision: {res.get('current_revision')}")

        elif args.command == "stamp":
            print(f"[*] Stamping database with revision '{args.revision}'...")
            res = stamp_database(args.revision, app)
            print(f"[OK] Stamped. Current revision: {res.get('current_revision')}")

        elif args.command == "status":
            status = get_migration_status(app)
            print("==================================================")
            print("OpsFlow Database Migration Status")
            print("==================================================")
            print(f"  Database Dialect : {status['database_dialect']}")
            print(f"  Current Revision : {status['current_revision']}")
            print(f"  Head Revision    : {status['head_revision']}")
            print(f"  Is Up To Date    : {status['is_up_to_date']}")
            print(f"  Tables Count     : {status['tables_count']}")
            print(f"  Tables           : {', '.join(status['tables'])}")
            print("==================================================")

        elif args.command == "current":
            cur = get_current_revision(app)
            print(f"Current revision: {cur or 'None (unversioned)'}")

        elif args.command == "heads":
            head = get_head_revision()
            print(f"Head revision: {head or 'None'}")


if __name__ == "__main__":
    main()
