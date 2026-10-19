"""Database initialization and connection management using SQLAlchemy."""

import os
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

import sqlite3

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable SQLite WAL mode and configure pragmas for high performance and cloud compatibility."""
    # Check if using SQLite driver
    if isinstance(dbapi_connection, sqlite3.Connection) or dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=OFF;")
        except Exception:
            pass
        finally:
            cursor.close()
