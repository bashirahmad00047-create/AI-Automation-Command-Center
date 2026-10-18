"""Configuration management for OpsFlow SaaS Platform."""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load .env file and Render secret files automatically into os.environ
_env_files = [
    os.path.join(BASE_DIR, ".env"),
    "/etc/secrets/.env",
    "/etc/secrets/secrets.env",
]
for _env_path in _env_files:
    if os.path.exists(_env_path):
        try:
            with open(_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and (k not in os.environ or not os.environ[k]):
                            os.environ[k] = v
        except Exception:
            pass

# Also load individual Render secret files from /etc/secrets/ (e.g. /etc/secrets/GROQ_API_KEY)
if os.path.exists("/etc/secrets") and os.path.isdir("/etc/secrets"):
    try:
        for _s_name in os.listdir("/etc/secrets"):
            _s_path = os.path.join("/etc/secrets", _s_name)
            if os.path.isfile(_s_path) and not _s_name.startswith("."):
                try:
                    with open(_s_path, "r", encoding="utf-8") as _sf:
                        _s_val = _sf.read().strip().strip('"').strip("'")
                        if _s_val and (_s_name not in os.environ or not os.environ[_s_name]):
                            os.environ[_s_name] = _s_val
                except Exception:
                    pass
    except Exception:
        pass


class Config:
    """Base application configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "opsflow-enterprise-secret-key-2026-production")
    
    # SQLAlchemy configuration
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'opsflow_saas.db')}"
    )
    # Fix for Heroku / Render postgres:// vs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }
    if "sqlite" in SQLALCHEMY_DATABASE_URI:
        from sqlalchemy.pool import NullPool
        SQLALCHEMY_ENGINE_OPTIONS["poolclass"] = NullPool

    # Session security
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_NAME = "opsflow_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    # Engine & Security limits
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max payload
    WEBHOOK_TIMEOUT_SECONDS = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "5"))
    DEFAULT_TENANT_ID = "org-enterprise-default"

    # AI Intelligence Providers (Gemini & Groq)
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    # Stripe Billing & Subscriptions
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_STARTER_MONTHLY = os.environ.get("STRIPE_PRICE_STARTER_MONTHLY", "")
    STRIPE_PRICE_STARTER_YEARLY = os.environ.get("STRIPE_PRICE_STARTER_YEARLY", "")
    STRIPE_PRICE_PRO_MONTHLY = os.environ.get("STRIPE_PRICE_PRO_MONTHLY", "")
    STRIPE_PRICE_PRO_YEARLY = os.environ.get("STRIPE_PRICE_PRO_YEARLY", "")
    STRIPE_PRICE_ENTERPRISE_MONTHLY = os.environ.get("STRIPE_PRICE_ENTERPRISE_MONTHLY", "")
    STRIPE_PRICE_ENTERPRISE_YEARLY = os.environ.get("STRIPE_PRICE_ENTERPRISE_YEARLY", "")


class DevelopmentConfig(Config):
    """Local development configuration."""
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    """Testing configuration with in-memory or dedicated test database."""
    DEBUG = False
    TESTING = True
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Hardened production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
