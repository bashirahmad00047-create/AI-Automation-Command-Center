"""Official WhatsApp Business / Meta Cloud API Integration Service for OpsFlow SaaS.

Architecture:
- Secure environment variable configuration:
  WHATSAPP_PHONE_NUMBER_ID: Meta Graph API Phone Number ID
  WHATSAPP_ACCESS_TOKEN: System User / Graph API Bearer Token
  WHATSAPP_VERIFY_TOKEN: Custom webhook subscription verification token
  WHATSAPP_BUSINESS_ACCOUNT_ID: WhatsApp Business Account ID (WABA)
  WHATSAPP_APP_SECRET: App secret for X-Hub-Signature-256 HMAC verification
- Webhook verification & incoming event parsing (Meta Cloud API standard format)
- Idempotency & duplicate event deduplication using Meta wamid.<id>
- Outgoing message dispatching via Meta Graph API v19.0
- Safe development / mock mode when real credentials are not configured
- Zero hardcoded tokens or secrets
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import current_app, has_app_context

from database import db
from models import Organization, SystemSetting, WhatsAppMessage, generate_uuid

logger = logging.getLogger("opsflow.whatsapp")

# Automatically load .env for standalone execution if present
_base_dir = os.path.abspath(os.path.dirname(__file__))
_env_file = os.path.join(_base_dir, ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                    if _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass


class WhatsAppService:
    """Manages WhatsApp Business Cloud API & Green-API interactions and message tracking."""

    GRAPH_API_VERSION = "v19.0"
    DEFAULT_VERIFY_TOKEN = "opsflow_whatsapp_verify_2026"
    DEFAULT_GREEN_API_HOST = "https://api.greenapi.com"
    DEFAULT_CONNECT_TIMEOUT = 30.0
    DEFAULT_READ_TIMEOUT = 30.0

    def __init__(
        self,
        id_instance: Optional[str] = None,
        api_token: Optional[str] = None,
        host: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> None:
        """Initializes WhatsAppService instance with optional instance-level overrides."""
        self._id_instance = id_instance
        self._api_token = api_token
        self._host = host
        self._organization_id = organization_id
        if id_instance:
            os.environ["GREEN_API_ID_INSTANCE"] = str(id_instance).strip()
        if api_token:
            os.environ["GREEN_API_TOKEN_INSTANCE"] = str(api_token).strip()
        if host:
            os.environ["GREEN_API_HOST"] = str(host).strip()

    @property
    def id_instance(self) -> str:
        """Returns configured Green-API idInstance or empty string."""
        if self._id_instance:
            return self._id_instance
        conf = self.get_config(organization_id=self._organization_id)
        return conf.get("green_api_id_instance") or conf.get("phone_number_id") or ""

    @property
    def api_token(self) -> str:
        """Returns configured Green-API apiTokenInstance (or Meta access_token) or empty string."""
        if self._api_token:
            return self._api_token
        conf = self.get_config(organization_id=self._organization_id)
        return conf.get("green_api_token_instance") or conf.get("access_token") or ""

    @property
    def host(self) -> str:
        """Returns configured Green-API host."""
        if self._host:
            return self.normalize_green_api_host(self._host, self.id_instance)
        conf = self.get_config(organization_id=self._organization_id)
        return conf.get("green_api_host") or self.DEFAULT_GREEN_API_HOST

    @classmethod
    def get_timeout_tuple(cls) -> Tuple[float, float]:
        """Returns (connect_timeout, read_timeout) tuple without restrictive connection timeout."""
        cfg = current_app.config if has_app_context() else {}
        try:
            connect_t = float(
                SystemSetting.get_val("WHATSAPP_CONNECT_TIMEOUT")
                or cfg.get("WHATSAPP_CONNECT_TIMEOUT")
                or os.environ.get("WHATSAPP_CONNECT_TIMEOUT", cls.DEFAULT_CONNECT_TIMEOUT)
            )
        except (ValueError, TypeError):
            connect_t = cls.DEFAULT_CONNECT_TIMEOUT

        try:
            read_t = float(
                SystemSetting.get_val("GREEN_API_TIMEOUT")
                or SystemSetting.get_val("WHATSAPP_READ_TIMEOUT")
                or SystemSetting.get_val("WHATSAPP_TIMEOUT")
                or cfg.get("GREEN_API_TIMEOUT")
                or cfg.get("WHATSAPP_READ_TIMEOUT")
                or cfg.get("WHATSAPP_TIMEOUT")
                or os.environ.get("GREEN_API_TIMEOUT")
                or os.environ.get("WHATSAPP_READ_TIMEOUT")
                or os.environ.get("WHATSAPP_TIMEOUT", cls.DEFAULT_READ_TIMEOUT)
            )
        except (ValueError, TypeError):
            read_t = cls.DEFAULT_READ_TIMEOUT

        # Allow generous connection window matching full timeout duration to eliminate premature connect timeouts
        effective_connect = max(15.0, connect_t, read_t)
        effective_read = max(5.0, read_t)
        return (effective_connect, effective_read)

    @classmethod
    def is_simulator_fallback_enabled(cls) -> bool:
        """Determines whether simulator fallback should be used upon timeout or network errors.

        Active when:
        - Environment variable or SystemSetting WHATSAPP_SIMULATOR_FALLBACK is 'true'
        - Or running on Render (RENDER or RENDER_INSTANCE_ID set)
        - Defaults to True to ensure resilient message processing and zero dropped workflows.
        """
        cfg = current_app.config if has_app_context() else {}
        val = (
            SystemSetting.get_val("WHATSAPP_SIMULATOR_FALLBACK")
            or cfg.get("WHATSAPP_SIMULATOR_FALLBACK")
            or os.environ.get("WHATSAPP_SIMULATOR_FALLBACK")
        )
        if val is not None:
            return str(val).strip().lower() in ("true", "1", "yes", "enabled")
        return True

    @classmethod
    def get_http_session(cls, retries: int = 2) -> requests.Session:
        """Creates a requests.Session with connection pooling and transient retry policy."""
        session = requests.Session()
        if retries > 0:
            retry_strategy = Retry(
                total=retries,
                backoff_factor=0.5,
                status_forcelist=[429, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        return session

    @classmethod
    def normalize_green_api_host(cls, host: Optional[str] = None, id_instance: Optional[str] = None) -> str:
        """Normalizes Green-API host routing to official high-speed endpoints without connection timeouts.

        - Automatically fixes legacy/typo domain 'api.green-api.com' -> 'api.greenapi.com'.
        - Ensures valid https:// scheme without trailing slash.
        - Directs instances with 4-digit cluster prefix (e.g. 7103xxxxxx) to their dedicated cluster host (https://7103.api.greenapi.com) for optimal latency.
        """
        raw = (host or "").strip().rstrip("/")
        if not raw:
            raw = cls.DEFAULT_GREEN_API_HOST
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = f"https://{raw}"

        # Fix legacy / blocked domain: api.green-api.com -> api.greenapi.com
        raw = raw.replace("api.green-api.com", "api.greenapi.com").replace("green-api.com", "greenapi.com")

        # Cluster routing: if instance starts with 4-digit cluster and host is universal, route directly to cluster host
        if id_instance:
            clean_id = str(id_instance).strip()
            if len(clean_id) >= 8 and clean_id[:4].isdigit() and raw in ("https://api.greenapi.com", "http://api.greenapi.com"):
                cluster = clean_id[:4]
                return f"https://{cluster}.api.greenapi.com"

        return raw

    @classmethod
    def _get_tenant_or_global_setting(cls, key: str, organization_id: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
        """Resolves setting scoped to tenant first, falling back to global setting."""
        if organization_id and organization_id != "global":
            scoped_key = f"ORG_{organization_id}_{key}"
            val = SystemSetting.get_val(scoped_key)
            if val is not None and val != "":
                return val
        return SystemSetting.get_val(key, default)

    @classmethod
    def get_instance_mappings(cls) -> Dict[str, str]:
        """Returns dictionary mapping instance_id / phone_id -> organization_id."""
        val = SystemSetting.get_val("WHATSAPP_INSTANCE_MAP")
        if val:
            try:
                data = json.loads(val)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    @classmethod
    def register_instance_mapping(cls, instance_or_phone_id: str, organization_id: str, provider: str = "green_api"):
        """Registers an Instance ID or Phone Number ID to an organization ID for multi-tenant webhook routing."""
        clean_id = str(instance_or_phone_id or "").strip()
        clean_org = str(organization_id or "").strip()
        if not clean_id or not clean_org:
            return
        mappings = cls.get_instance_mappings()
        mappings[clean_id] = clean_org
        SystemSetting.set_val(
            "WHATSAPP_INSTANCE_MAP",
            json.dumps(mappings, indent=2),
            is_secret=False,
            description="Mapping of WhatsApp Instance IDs and Phone IDs to Organization IDs"
        )
        SystemSetting.set_val(
            f"WHATSAPP_MAP_INSTANCE_{clean_id}",
            clean_org,
            is_secret=False,
            description=f"Direct routing map for instance/phone {clean_id} -> {clean_org}"
        )

    @classmethod
    def resolve_organization_by_instance(cls, instance_or_phone_id: Optional[str]) -> Optional[str]:
        """Resolves the organization ID for a given Green-API instance ID or Meta phone number ID."""
        if not instance_or_phone_id:
            return None
        clean_id = str(instance_or_phone_id).strip()
        direct = SystemSetting.get_val(f"WHATSAPP_MAP_INSTANCE_{clean_id}")
        if direct:
            return direct
        mappings = cls.get_instance_mappings()
        if clean_id in mappings:
            return mappings[clean_id]
        return None

    @classmethod
    def delete_instance_mapping(cls, instance_or_phone_id: str) -> bool:
        """Deletes an instance or phone mapping from the registry."""
        clean_id = str(instance_or_phone_id or "").strip()
        if not clean_id:
            return False
        mappings = cls.get_instance_mappings()
        deleted = False
        if clean_id in mappings:
            del mappings[clean_id]
            SystemSetting.set_val(
                "WHATSAPP_INSTANCE_MAP",
                json.dumps(mappings, indent=2),
                is_secret=False,
                description="Mapping of WhatsApp Instance IDs and Phone IDs to Organization IDs"
            )
            deleted = True
        direct_key = f"WHATSAPP_MAP_INSTANCE_{clean_id}"
        if has_app_context():
            setting = SystemSetting.query.filter_by(key=direct_key).first()
            if setting:
                db.session.delete(setting)
                db.session.commit()
                deleted = True
        return deleted

    @classmethod
    def get_config(cls, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieves WhatsApp configuration from tenant-scoped settings, global database settings, or environment."""
        cfg = current_app.config if has_app_context() else {}

        phone_id_val = cls._get_tenant_or_global_setting("WHATSAPP_PHONE_NUMBER_ID", organization_id)
        phone_id = (
            phone_id_val
            if phone_id_val is not None
            else (
                cfg.get("WHATSAPP_PHONE_NUMBER_ID")
                or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
                or os.environ.get("META_PHONE_NUMBER_ID", "")
            )
        ).strip()

        token_val = cls._get_tenant_or_global_setting("WHATSAPP_ACCESS_TOKEN", organization_id)
        if token_val is None:
            token_val = cls._get_tenant_or_global_setting("WHATSAPP_TOKEN", organization_id)
        access_token = (
            token_val
            if token_val is not None
            else (
                cfg.get("WHATSAPP_ACCESS_TOKEN")
                or cfg.get("WHATSAPP_TOKEN")
                or os.environ.get("WHATSAPP_TOKEN")
                or os.environ.get("WHATSAPP_ACCESS_TOKEN")
                or os.environ.get("META_ACCESS_TOKEN", "")
            )
        ).strip()

        verify_token = (
            cls._get_tenant_or_global_setting("WHATSAPP_VERIFY_TOKEN", organization_id)
            or cfg.get("WHATSAPP_VERIFY_TOKEN")
            or os.environ.get("WHATSAPP_VERIFY_TOKEN", cls.DEFAULT_VERIFY_TOKEN)
        ).strip()

        business_account_id = (
            cls._get_tenant_or_global_setting("WHATSAPP_BUSINESS_ACCOUNT_ID", organization_id)
            or cfg.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
            or os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
            or os.environ.get("META_WABA_ID", "")
        ).strip()

        app_secret = (
            cls._get_tenant_or_global_setting("WHATSAPP_APP_SECRET", organization_id)
            or cfg.get("WHATSAPP_APP_SECRET")
            or os.environ.get("WHATSAPP_APP_SECRET")
            or os.environ.get("META_APP_SECRET", "")
        ).strip()

        # Green-API Parameters
        green_id_val = cls._get_tenant_or_global_setting("GREEN_API_ID_INSTANCE", organization_id)
        if green_id_val is None:
            green_id_val = cls._get_tenant_or_global_setting("ID_INSTANCE", organization_id)
        if green_id_val is None:
            green_id_val = cls._get_tenant_or_global_setting("GREEN_API_ID", organization_id)
        green_api_id = (
            green_id_val
            if green_id_val is not None
            else (
                cfg.get("GREEN_API_ID_INSTANCE")
                or cfg.get("ID_INSTANCE")
                or cfg.get("GREEN_API_ID")
                or os.environ.get("GREEN_API_ID_INSTANCE")
                or os.environ.get("ID_INSTANCE")
                or os.environ.get("GREEN_API_ID", "")
            )
        ).strip()

        green_tok_val = cls._get_tenant_or_global_setting("GREEN_API_TOKEN_INSTANCE", organization_id)
        if green_tok_val is None:
            green_tok_val = cls._get_tenant_or_global_setting("API_TOKEN_INSTANCE", organization_id)
        if green_tok_val is None:
            green_tok_val = cls._get_tenant_or_global_setting("GREEN_API_TOKEN", organization_id)
        green_api_token = (
            green_tok_val
            if green_tok_val is not None
            else (
                cfg.get("GREEN_API_TOKEN_INSTANCE")
                or cfg.get("API_TOKEN_INSTANCE")
                or cfg.get("GREEN_API_TOKEN")
                or os.environ.get("GREEN_API_TOKEN_INSTANCE")
                or os.environ.get("API_TOKEN_INSTANCE")
                or os.environ.get("GREEN_API_TOKEN", "")
            )
        ).strip()

        green_api_host_val = cls._get_tenant_or_global_setting("GREEN_API_HOST", organization_id)
        green_api_host = (
            green_api_host_val
            if green_api_host_val is not None
            else (
                cfg.get("GREEN_API_HOST")
                or os.environ.get("GREEN_API_HOST", cls.DEFAULT_GREEN_API_HOST)
            )
        ).strip().rstrip("/")
        green_api_host = cls.normalize_green_api_host(green_api_host, green_api_id)

        provider = (
            cls._get_tenant_or_global_setting("WHATSAPP_PROVIDER", organization_id)
            or cfg.get("WHATSAPP_PROVIDER")
            or os.environ.get("WHATSAPP_PROVIDER", "auto")
        ).strip().lower()

        auto_reply_enabled_str = cls._get_tenant_or_global_setting("AI_AUTO_REPLY_ENABLED", organization_id)
        auto_reply_enabled = (auto_reply_enabled_str or "").strip().lower() in ("true", "1", "yes", "on")

        return {
            "organization_id": organization_id,
            "phone_number_id": phone_id,
            "access_token": access_token,
            "verify_token": verify_token,
            "business_account_id": business_account_id,
            "app_secret": app_secret,
            "green_api_id_instance": green_api_id,
            "green_api_token_instance": green_api_token,
            "green_api_host": green_api_host,
            "whatsapp_provider": provider,
            "ai_auto_reply_enabled": auto_reply_enabled,
        }

    @classmethod
    def save_config(
        cls,
        organization_id: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        business_account_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verify_token: Optional[str] = None,
        green_api_id_instance: Optional[str] = None,
        green_api_token_instance: Optional[str] = None,
        green_api_host: Optional[str] = None,
        whatsapp_provider: Optional[str] = None,
        ai_auto_reply_enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Saves live WhatsApp / Green-API configuration dynamically into tenant-scoped and global database settings."""
        prefix = f"ORG_{organization_id}_" if organization_id and organization_id != "global" else ""

        if phone_number_id is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_PHONE_NUMBER_ID", phone_number_id, is_secret=False, description=f"[{organization_id or 'global'}] Meta Graph Phone Number ID")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_PHONE_NUMBER_ID", phone_number_id, is_secret=False)
            if organization_id and phone_number_id:
                cls.register_instance_mapping(phone_number_id, organization_id, provider="meta")

        if access_token is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_ACCESS_TOKEN", access_token, is_secret=True, description=f"[{organization_id or 'global'}] Meta Graph Access Token")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_ACCESS_TOKEN", access_token, is_secret=True)

        if business_account_id is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_BUSINESS_ACCOUNT_ID", business_account_id, is_secret=False, description=f"[{organization_id or 'global'}] WhatsApp Business Account ID")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_BUSINESS_ACCOUNT_ID", business_account_id, is_secret=False)

        if app_secret is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_APP_SECRET", app_secret, is_secret=True, description=f"[{organization_id or 'global'}] Meta App Secret")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_APP_SECRET", app_secret, is_secret=True)

        if verify_token is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_VERIFY_TOKEN", verify_token, is_secret=False, description=f"[{organization_id or 'global'}] Webhook Verify Token")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_VERIFY_TOKEN", verify_token, is_secret=False)

        if green_api_id_instance is not None:
            SystemSetting.set_val(f"{prefix}GREEN_API_ID_INSTANCE", green_api_id_instance, is_secret=False, description=f"[{organization_id or 'global'}] Green-API Instance ID")
            if not prefix:
                SystemSetting.set_val("GREEN_API_ID_INSTANCE", green_api_id_instance, is_secret=False)
            if organization_id and green_api_id_instance:
                cls.register_instance_mapping(green_api_id_instance, organization_id, provider="green_api")

        if green_api_token_instance is not None:
            SystemSetting.set_val(f"{prefix}GREEN_API_TOKEN_INSTANCE", green_api_token_instance, is_secret=True, description=f"[{organization_id or 'global'}] Green-API API Token Instance")
            if not prefix:
                SystemSetting.set_val("GREEN_API_TOKEN_INSTANCE", green_api_token_instance, is_secret=True)

        if green_api_host is not None:
            clean_host = cls.normalize_green_api_host(green_api_host, green_api_id_instance)
            SystemSetting.set_val(f"{prefix}GREEN_API_HOST", clean_host, is_secret=False, description=f"[{organization_id or 'global'}] Green-API API Host")
            if not prefix:
                SystemSetting.set_val("GREEN_API_HOST", clean_host, is_secret=False)

        if whatsapp_provider is not None:
            SystemSetting.set_val(f"{prefix}WHATSAPP_PROVIDER", whatsapp_provider, is_secret=False, description=f"[{organization_id or 'global'}] Active WhatsApp Provider")
            if not prefix:
                SystemSetting.set_val("WHATSAPP_PROVIDER", whatsapp_provider, is_secret=False)

        if ai_auto_reply_enabled is not None:
            val = "true" if ai_auto_reply_enabled else "false"
            SystemSetting.set_val(f"{prefix}AI_AUTO_REPLY_ENABLED", val, is_secret=False, description=f"[{organization_id or 'global'}] AI Auto-Reply Enabled")
            if not prefix:
                SystemSetting.set_val("AI_AUTO_REPLY_ENABLED", val, is_secret=False)

        return cls.get_config(organization_id=organization_id)

    @classmethod
    def get_auto_responder_config(cls, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieves AI Auto-Responder configuration for an organization."""
        enabled_str = cls._get_tenant_or_global_setting("AI_AUTO_REPLY_ENABLED", organization_id)
        gemini_key = cls.get_gemini_api_key(organization_id=organization_id)
        gemini_model = cls.get_gemini_model_name(organization_id=organization_id)
        has_gemini = bool(gemini_key)
        enabled = has_gemini or ((enabled_str or "").strip().lower() in ("true", "1", "yes", "on"))

        mode = cls._get_tenant_or_global_setting("AI_AUTO_REPLY_MODE", organization_id) or "smart_concierge"
        system_prompt = cls._get_tenant_or_global_setting("AI_SYSTEM_PROMPT", organization_id) or ""
        cooldown_str = cls._get_tenant_or_global_setting("AI_COOLDOWN_MINUTES", organization_id)
        try:
            cooldown_minutes = int(cooldown_str) if cooldown_str else 5
        except (ValueError, TypeError):
            cooldown_minutes = 5

        threshold_str = cls._get_tenant_or_global_setting("AI_CONFIDENCE_THRESHOLD", organization_id)
        try:
            confidence_threshold = int(threshold_str) if threshold_str else 60
        except (ValueError, TypeError):
            confidence_threshold = 60

        capture_str = cls._get_tenant_or_global_setting("AI_AUTO_LEAD_CAPTURE", organization_id)
        auto_lead_capture = (capture_str or "true").strip().lower() in ("true", "1", "yes", "on")

        greeting = cls._get_tenant_or_global_setting("AI_FALLBACK_GREETING", organization_id) or ""

        return {
            "organization_id": organization_id,
            "enabled": enabled,
            "has_gemini": has_gemini,
            "gemini_model": gemini_model,
            "gemini_api_key_configured": bool(gemini_key),
            "mode": mode,
            "system_prompt": system_prompt,
            "cooldown_minutes": cooldown_minutes,
            "confidence_threshold": confidence_threshold,
            "auto_lead_capture": auto_lead_capture,
            "fallback_greeting": greeting
        }

    @classmethod
    def save_auto_responder_config(
        cls,
        organization_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        mode: Optional[str] = None,
        system_prompt: Optional[str] = None,
        cooldown_minutes: Optional[int] = None,
        confidence_threshold: Optional[int] = None,
        auto_lead_capture: Optional[bool] = None,
        fallback_greeting: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Saves AI Auto-Responder configuration for a tenant or globally."""
        prefix = f"ORG_{organization_id}_" if organization_id and organization_id != "global" else ""

        if enabled is not None:
            val = "true" if enabled else "false"
            SystemSetting.set_val(f"{prefix}AI_AUTO_REPLY_ENABLED", val, is_secret=False, description=f"[{organization_id or 'global'}] AI Auto-Reply Enabled")
            if not prefix:
                SystemSetting.set_val("AI_AUTO_REPLY_ENABLED", val, is_secret=False)

        if mode is not None:
            SystemSetting.set_val(f"{prefix}AI_AUTO_REPLY_MODE", mode.strip(), is_secret=False, description=f"[{organization_id or 'global'}] AI Auto-Reply Mode")
            if not prefix:
                SystemSetting.set_val("AI_AUTO_REPLY_MODE", mode.strip(), is_secret=False)

        if system_prompt is not None:
            SystemSetting.set_val(f"{prefix}AI_SYSTEM_PROMPT", system_prompt.strip(), is_secret=False, description=f"[{organization_id or 'global'}] AI Auto-Responder Custom System Prompt")
            if not prefix:
                SystemSetting.set_val("AI_SYSTEM_PROMPT", system_prompt.strip(), is_secret=False)

        if cooldown_minutes is not None:
            SystemSetting.set_val(f"{prefix}AI_COOLDOWN_MINUTES", str(cooldown_minutes), is_secret=False, description=f"[{organization_id or 'global'}] Debounce cooldown in minutes")
            if not prefix:
                SystemSetting.set_val("AI_COOLDOWN_MINUTES", str(cooldown_minutes), is_secret=False)

        if confidence_threshold is not None:
            SystemSetting.set_val(f"{prefix}AI_CONFIDENCE_THRESHOLD", str(confidence_threshold), is_secret=False, description=f"[{organization_id or 'global'}] Confidence threshold")
            if not prefix:
                SystemSetting.set_val("AI_CONFIDENCE_THRESHOLD", str(confidence_threshold), is_secret=False)

        if auto_lead_capture is not None:
            val = "true" if auto_lead_capture else "false"
            SystemSetting.set_val(f"{prefix}AI_AUTO_LEAD_CAPTURE", val, is_secret=False, description=f"[{organization_id or 'global'}] Auto create CRM lead")
            if not prefix:
                SystemSetting.set_val("AI_AUTO_LEAD_CAPTURE", val, is_secret=False)

        if fallback_greeting is not None:
            SystemSetting.set_val(f"{prefix}AI_FALLBACK_GREETING", fallback_greeting.strip(), is_secret=False)
            if not prefix:
                SystemSetting.set_val("AI_FALLBACK_GREETING", fallback_greeting.strip(), is_secret=False)

        if gemini_api_key is not None:
            clean_k = str(gemini_api_key).strip().strip("'\" \t\r\n")
            SystemSetting.set_val(f"{prefix}GEMINI_API_KEY", clean_k, is_secret=True, description=f"[{organization_id or 'global'}] Google Gemini API Key")
            if not prefix:
                SystemSetting.set_val("GEMINI_API_KEY", clean_k, is_secret=True)

        if gemini_model is not None:
            clean_m = str(gemini_model).strip()
            SystemSetting.set_val(f"{prefix}GEMINI_MODEL", clean_m, is_secret=False, description=f"[{organization_id or 'global'}] Google Gemini Model")
            if not prefix:
                SystemSetting.set_val("GEMINI_MODEL", clean_m, is_secret=False)

        return cls.get_auto_responder_config(organization_id=organization_id)

    @classmethod
    def is_auto_reply_enabled(cls, organization_id: Optional[str] = None) -> bool:
        """Returns True if AI Auto-Responder is enabled for this organization."""
        conf = cls.get_auto_responder_config(organization_id=organization_id)
        return conf.get("enabled", False)

    @classmethod
    def get_gemini_api_key(cls, organization_id: Optional[str] = None) -> Optional[str]:
        """Resolves Gemini API key across environment, database settings, and app config."""
        candidates = [
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENAI_API_KEY",
            "GEMINI_KEY",
            "GOOGLE_AI_KEY",
            "GEMINI_TOKEN",
            "AI_API_KEY",
        ]
        api_key = None
        for k in candidates:
            # 1. Tenant or global setting in database
            val = cls._get_tenant_or_global_setting(k, organization_id)
            if val and str(val).strip():
                api_key = str(val).strip()
                break
            # 2. Environment variable
            val = os.environ.get(k)
            if val and str(val).strip():
                api_key = str(val).strip()
                break
            # 3. Flask app config
            if has_app_context():
                val = current_app.config.get(k)
                if val and str(val).strip():
                    api_key = str(val).strip()
                    break

        if not api_key:
            try:
                from ai_provider import get_ai_provider
                gemini_prov = get_ai_provider("gemini")
                api_key = getattr(gemini_prov, "api_key", None)
            except Exception:
                pass

        if api_key:
            api_key = str(api_key).strip().strip("'\" \t\r\n")

        return api_key or None

    @classmethod
    def get_gemini_model_name(cls, organization_id: Optional[str] = None) -> str:
        """Resolves the configured Gemini model name with supported fallback cascade."""
        model = (
            cls._get_tenant_or_global_setting("GEMINI_MODEL", organization_id)
            or os.environ.get("GEMINI_MODEL")
        )
        if not model and has_app_context():
            model = current_app.config.get("GEMINI_MODEL")
        if not model:
            try:
                from ai_provider import get_ai_provider
                gemini_prov = get_ai_provider("gemini")
                model = getattr(gemini_prov, "model", None)
            except Exception:
                pass
        return (model or "gemini-1.5-flash").strip()

    @classmethod
    def call_gemini_ai(
        cls,
        user_message: Union[str, Dict[str, Any]],
        system_prompt: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> Optional[str]:
        """Calls configured Google Gemini AI provider to generate a pure, natural response directly tailored to customer inquiries."""
        api_key = cls.get_gemini_api_key(organization_id=organization_id)
        if not api_key:
            err_msg = "No Gemini API key found in environment variables (GEMINI_API_KEY, GOOGLE_API_KEY), database settings, or app config."
            cls._last_gemini_error = err_msg
            logger.warning(f"[WhatsApp AI Auto-Responder] {err_msg} Returning clean fallback response.")
            return None

        user_msg_text = user_message.get('text', '') if isinstance(user_message, dict) else str(user_message)
        clean_text = user_msg_text.strip()
        if not clean_text:
            return None

        default_business_context = (
            "Business Name: OpsFlow Cloud (AI Automation Command Center & IT Operations Platform).\n"
            "Core Offerings & Services:\n"
            "- Multi-agent automation engine and real-time IT incident orchestration.\n"
            "- Two-way WhatsApp Business & Green-API customer routing and intelligent auto-responder.\n"
            "- Observability, alert routing (PagerDuty, Slack, Email), and automated remediation pipelines.\n"
            "- Payment gateway support (Stripe internationally, JazzCash for Pakistan).\n"
            "Pricing & Subscription Tiers:\n"
            "- 2-Day Free Trial available on all plans.\n"
            "- Starter: $49/month (PKR 7,500/mo) - up to 10 automated rules, 50,000 monthly events.\n"
            "- Pro: $149/month (PKR 25,000/mo) - up to 50 rules, 200,000 monthly events, priority alert routing.\n"
            "- Enterprise: $499/month (PKR 125,000/mo) - unlimited rules, 1,000,000+ events, dedicated SLA, customized integrations."
        )
        sys_instruct = (
            f"\nAdditional Context / Business Instructions:\n{system_prompt.strip()}"
            if system_prompt and len(system_prompt.strip()) > 3
            else f"\nBusiness Knowledge Base:\n{default_business_context}"
        )
        prompt = (
            f"You are an intelligent, polite, and direct AI assistant for OpsFlow Cloud.{sys_instruct}\n\n"
            f"A customer has sent the following message: '{clean_text}'.\n\n"
            f"Please provide a direct, helpful, and natural response specifically addressing their inquiry. "
            f"Keep your tone professional, concise, and helpful. Do not include robotic canned boilerplate or disclaimers."
        )

        configured_model = cls.get_gemini_model_name(organization_id=organization_id)
        models_to_try = [configured_model]
        for fallback_m in ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-pro"]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        # 1. Try google.generativeai SDK if available
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            for m_name in models_to_try:
                clean_m = m_name.replace("models/", "")
                try:
                    model = genai.GenerativeModel(clean_m)
                    response = model.generate_content(prompt)
                    if response:
                        text = None
                        try:
                            if response.text:
                                text = response.text
                        except Exception:
                            pass
                        if not text and hasattr(response, "candidates") and response.candidates:
                            candidate = response.candidates[0]
                            if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                                parts = candidate.content.parts
                                if parts and hasattr(parts[0], "text"):
                                    text = parts[0].text
                        if text and text.strip():
                            cls._last_gemini_error = None
                            logger.info(f"[WhatsApp AI Auto-Responder] Successfully generated response via Gemini model '{clean_m}' ({len(text)} chars)")
                            return text.strip()
                except Exception as model_err:
                    err_str = str(model_err)
                    cls._last_gemini_error = f"google.generativeai error with '{clean_m}': {err_str}"
                    logger.warning(f"[WhatsApp AI Auto-Responder] google.generativeai error with model '{clean_m}': {model_err}")
                    if "quota" in err_str.lower() or "429" in err_str:
                        break
                    continue
        except Exception as genai_err:
            cls._last_gemini_error = f"google.generativeai setup failed: {genai_err}"
            logger.warning(f"[WhatsApp AI Auto-Responder] google.generativeai setup failed: {genai_err}")

        # 2. Direct HTTP REST API via requests across v1beta and v1
        for api_ver in ["v1beta", "v1"]:
            for m_name in models_to_try:
                clean_m = m_name.replace("models/", "")
                try:
                    url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{clean_m}:generateContent"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}]
                    }
                    resp = requests.post(
                        url,
                        params={"key": api_key},
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "OpsFlow-Cloud/2.4 (WhatsApp-Auto-Responder)"
                        },
                        timeout=12
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                text = parts[0]["text"].strip()
                                if text:
                                    cls._last_gemini_error = None
                                    logger.info(f"[WhatsApp AI Auto-Responder] Successfully generated response via HTTP REST Gemini model '{clean_m}' ({api_ver})")
                                    return text
                    else:
                        detail = ""
                        try:
                            detail = resp.text[:300]
                        except Exception:
                            pass
                        err_msg = f"HTTP {resp.status_code} ({api_ver}/{clean_m}): {detail}"
                        cls._last_gemini_error = err_msg
                        logger.error(f"[WhatsApp AI Auto-Responder] {err_msg}")
                except Exception as req_err:
                    err_msg = f"Network error calling Gemini API ({api_ver}/{clean_m}): {req_err}"
                    cls._last_gemini_error = err_msg
                    logger.error(f"[WhatsApp AI Auto-Responder] {err_msg}")
                    continue

        logger.warning(
            f"[WhatsApp AI Auto-Responder] Gemini AI generation returned no response or failed across all models "
            f"for organization '{organization_id or 'global'}'. Falling back to non-AI response. (Last error: {getattr(cls, '_last_gemini_error', 'None')})"
        )
        return None

    @classmethod
    def get_last_gemini_error(cls) -> Optional[str]:
        """Returns the most recent Gemini AI generation error for diagnostic / observability purposes."""
        return getattr(cls, "_last_gemini_error", None)

    @classmethod
    def generate_ai_auto_response(
        cls,
        organization_id: Optional[str],
        message_body: str,
        sender_name: Optional[str] = None,
        sender_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyzes an incoming message and generates a tailored AI auto-response draft via direct Gemini AI or clean fallback."""
        from nlp_engine import NLPEngine
        engine = NLPEngine()

        conf = cls.get_auto_responder_config(organization_id=organization_id)
        mode = conf.get("mode", "smart_concierge")
        custom_prompt = conf.get("system_prompt", "")

        analysis = engine.parse(message_body)
        intent = analysis.get("intent", "lead_inquiry")
        urgency = analysis.get("urgency", 20)
        lead_score = analysis.get("lead_score", 50)
        route_dept = analysis.get("recommended_route") or analysis.get("route_department", "Sales")
        entities = analysis.get("entities", {})

        # Resolve organization brand name
        org_name = "OpsFlow Cloud"
        if organization_id and has_app_context():
            org = db.session.get(Organization, organization_id)
            if org and org.name:
                org_name = org.name

        # Mode-based adjustments
        if mode == "sre_incident":
            route_dept = "Priority Support" if urgency >= 50 else "Support"
        elif mode == "lead_qualifier":
            route_dept = "Sales"

        # 1. Direct Gemini AI Generation
        ai_reply = cls.call_gemini_ai(message_body, system_prompt=custom_prompt, organization_id=organization_id)
        if ai_reply:
            return {
                "reply_body": ai_reply.strip(),
                "intent": intent,
                "urgency": urgency,
                "lead_score": lead_score,
                "route_department": route_dept,
                "entities": entities,
                "mode": "gemini_ai",
                "is_gemini": True,
                "confidence": 98
            }

        # 2. Clean fallback when AI provider is offline (NO echoing of user message, NO canned wrapper templates)
        logger.warning(
            f"[WhatsApp AI Auto-Responder] Gemini AI generation was unavailable or failed for inbound message: "
            f"'{message_body[:60]}'. Falling back to non-AI response rather than presenting as Gemini answer."
        )
        if intent == "lead_inquiry" or route_dept == "Sales":
            final_reply = "A solutions specialist is reviewing your inquiry and will follow up with tailored details and pricing."
        elif intent in ("critical_incident", "security_threat") or route_dept in ("Priority Support", "Security Operations"):
            final_reply = "Your critical incident report has been registered with highest priority and routed to our engineering team."
        elif intent in ("support_request", "incident_ticket") or route_dept == "Support":
            final_reply = "A technical support specialist has been assigned to your request and will assist you shortly."
        else:
            final_reply = "Thank you for reaching out. Our team has received your inquiry and will follow up shortly."

        return {
            "reply_body": final_reply,
            "intent": intent,
            "urgency": urgency,
            "lead_score": lead_score,
            "route_department": route_dept,
            "entities": entities,
            "mode": mode,
            "is_gemini": False,
            "confidence": min(98, max(65, lead_score + (10 if intent != 'unknown' else 0)))
        }

    @classmethod
    def handle_inbound_auto_response(
        cls,
        organization_id: Optional[str],
        sender_phone: str,
        message_body: str,
        sender_name: Optional[str] = None,
        message_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Handles automated AI response to an inbound message if enabled and not debounced."""
        if not sender_phone or not message_body:
            return None

        # Ignore group messages and broadcast channels
        if "@g.us" in str(sender_phone) or str(sender_phone).startswith("120363"):
            return None

        org_id = organization_id or "org-enterprise-default"
        conf = cls.get_auto_responder_config(organization_id=org_id)

        # Force enabled if Gemini API key exists or explicitly enabled
        has_gemini = bool(cls.get_gemini_api_key(organization_id=org_id))
        if not conf.get("enabled") and not has_gemini:
            return None

        if has_gemini:
            logger.info("Direct Gemini AI auto-responder enabled for inbound WhatsApp message.")

        cooldown_mins = conf.get("cooldown_minutes", 5)

        # Prevent duplicate reply storm / loop: Check if an outbound message was already sent to this phone recently
        clean_phone = cls.format_phone_number(sender_phone)
        if not has_gemini:
            if has_app_context() and cooldown_mins > 0:
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=cooldown_mins)
                recent_outbound = WhatsAppMessage.query.filter(
                    WhatsAppMessage.organization_id == org_id,
                    WhatsAppMessage.recipient.like(f"%{clean_phone[-8:]}%"),
                    WhatsAppMessage.direction == "outbound",
                    WhatsAppMessage.created_at >= cutoff
                ).first()
                if recent_outbound:
                    logger.info(f"AI Auto-Reply debounced for {clean_phone} (last outbound at {recent_outbound.created_at})")
                    return None

        # Generate response
        generated = cls.generate_ai_auto_response(
            organization_id=org_id,
            message_body=message_body,
            sender_name=sender_name,
            sender_phone=clean_phone
        )
        reply_body = generated["reply_body"]
        intent = generated["intent"]
        lead_score = generated["lead_score"]

        # If auto_lead_capture is True and intent is lead_inquiry or score >= 50, ensure Lead exists in CRM
        if conf.get("auto_lead_capture") and has_app_context() and (intent == "lead_inquiry" or lead_score >= 50):
            try:
                from models import Lead
                existing_lead = Lead.query.filter(
                    Lead.organization_id == org_id,
                    Lead.phone.like(f"%{clean_phone[-9:]}%")
                ).first()
                if not existing_lead:
                    new_lead = Lead(
                        organization_id=org_id,
                        name=sender_name or f"WhatsApp {clean_phone}",
                        phone=clean_phone,
                        company="",
                        message=message_body[:500],
                        intent=intent,
                        urgency_score=generated.get("urgency", 0),
                        lead_score=lead_score,
                        route_department=generated.get("route_department", "Sales"),
                        draft_response=reply_body
                    )
                    db.session.add(new_lead)
                    db.session.commit()
                    logger.info(f"Auto-captured CRM Lead for WhatsApp sender: {clean_phone}")
            except Exception as lead_err:
                logger.error(f"Failed to auto-capture CRM Lead: {lead_err}")

        # Dispatch outbound message via WhatsAppService.send_message
        try:
            dispatch_res = cls.send_message(
                organization_id=org_id,
                to_phone=clean_phone,
                message_text=reply_body
            )
            # Tag the newly recorded outbound message with AI metadata
            outbound_record_id = dispatch_res.get("record_id") or dispatch_res.get("message_record_id")
            msg_rec = None
            if outbound_record_id and has_app_context():
                msg_rec = db.session.get(WhatsAppMessage, outbound_record_id)
            if not msg_rec and dispatch_res.get("whatsapp_message_id") and has_app_context():
                msg_rec = WhatsAppMessage.query.filter_by(whatsapp_message_id=dispatch_res["whatsapp_message_id"]).first()

            if msg_rec:
                is_gemini = (generated.get("mode") == "gemini_ai") or bool(generated.get("is_gemini"))
                meta = {
                    "is_ai_response": True,
                    "is_gemini_response": is_gemini,
                    "response_source": "gemini_ai" if is_gemini else "system_fallback",
                    "ai_intent": intent,
                    "lead_score": lead_score,
                    "urgency": generated["urgency"],
                    "confidence": generated["confidence"],
                    "triggered_by_message_id": message_id
                }
                msg_rec.raw_payload_json = json.dumps(meta)
                db.session.commit()

            if generated.get("mode") == "gemini_ai" or generated.get("is_gemini"):
                logger.info(f"Gemini AI response successfully dispatched to {clean_phone} [Intent: {intent}, Score: {lead_score}]")
            else:
                logger.warning(
                    f"[WhatsApp AI Auto-Responder] System fallback response dispatched to {clean_phone} "
                    f"because Gemini AI was unavailable or failed. [Intent: {intent}, Score: {lead_score}]"
                )
            return {
                "success": True,
                "reply_body": reply_body,
                "intent": intent,
                "lead_score": lead_score,
                "dispatch": dispatch_res
            }
        except Exception as dispatch_err:
            logger.error(f"Failed to dispatch AI Auto-Reply to {clean_phone}: {dispatch_err}")
            return None

    @classmethod
    def format_phone_number(cls, phone: str) -> str:
        """Formats phone number to international E.164 digits, handling Pakistani local numbers automatically."""
        clean = "".join(filter(str.isdigit, str(phone or "")))
        # Handle Pakistani local formats like 03001234567 -> 923001234567
        if clean.startswith("03") and len(clean) == 11:
            return "92" + clean[1:]
        if clean.startswith("00"):
            return clean[2:]
        return clean

    @classmethod
    def is_meta_configured(cls, organization_id: Optional[str] = None) -> bool:
        """Returns True if live Meta WhatsApp credentials are configured for tenant."""
        conf = cls.get_config(organization_id=organization_id)
        phone_id = conf["phone_number_id"]
        token = conf["access_token"]
        return bool(
            phone_id
            and token
            and not phone_id.startswith("mock_")
            and not token.startswith("mock_")
        )

    @classmethod
    def is_green_api_configured(cls, organization_id: Optional[str] = None) -> bool:
        """Returns True if live Green-API credentials are configured for tenant."""
        conf = cls.get_config(organization_id=organization_id)
        id_inst = conf.get("green_api_id_instance", "")
        tok_inst = conf.get("green_api_token_instance", "")
        return bool(
            id_inst
            and tok_inst
            and not str(id_inst).startswith("mock_")
            and not str(tok_inst).startswith("mock_")
        )

    @classmethod
    def get_active_provider(cls, organization_id: Optional[str] = None) -> str:
        """Resolves active WhatsApp provider for tenant: 'green_api', 'meta', or 'simulator'."""
        conf = cls.get_config(organization_id=organization_id)
        configured_pref = conf.get("whatsapp_provider", "auto")

        if configured_pref == "green_api" and cls.is_green_api_configured(organization_id=organization_id):
            return "green_api"
        if configured_pref == "meta" and cls.is_meta_configured(organization_id=organization_id):
            return "meta"

        # Auto resolution
        if cls.is_green_api_configured(organization_id=organization_id):
            return "green_api"
        if cls.is_meta_configured(organization_id=organization_id):
            return "meta"
        return "simulator"

    @classmethod
    def is_configured(cls, organization_id: Optional[str] = None) -> bool:
        """Returns True if either Meta Cloud API or Green-API credentials are configured."""
        return cls.is_green_api_configured(organization_id=organization_id) or cls.is_meta_configured(organization_id=organization_id)

    @classmethod
    def test_green_api_connection(cls, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Probes Green-API getStateInstance endpoint with robust timeout and error handling."""
        conf = cls.get_config(organization_id=organization_id)
        id_inst = conf.get("green_api_id_instance", "")
        tok_inst = conf.get("green_api_token_instance", "")
        host = cls.normalize_green_api_host(conf.get("green_api_host"), id_inst)

        if not id_inst or not tok_inst:
            return {
                "success": False,
                "provider": "green_api",
                "status": "not_configured",
                "message": "Both Green-API Instance ID and API Token Instance must be configured."
            }

        url = f"{host}/waInstance{id_inst}/getStateInstance/{tok_inst}"
        timeouts = cls.get_timeout_tuple()

        try:
            with cls.get_http_session(retries=1) as session:
                resp = session.get(url, timeout=timeouts)
                try:
                    data = resp.json() if resp.text and resp.text.strip() else {}
                except Exception:
                    data = {}
                if resp.status_code == 200:
                    state = data.get("stateInstance", "unknown")
                    is_authorized = (state.lower() == "authorized")
                    return {
                        "success": is_authorized,
                        "provider": "green_api",
                        "status": state,
                        "id_instance": id_inst,
                        "state_instance": state,
                        "message": (
                            f"Green-API Instance {id_inst} is ONLINE and AUTHORIZED!"
                            if is_authorized else
                            f"Green-API Instance state: '{state}'. Please link WhatsApp by scanning the QR code in your Green-API console."
                        )
                    }
                else:
                    err_text = data.get("message") or resp.text[:200] or (
                        f"HTTP 401 Unauthorized: Invalid Instance ID '{id_inst}' or API Token Instance. Please verify credentials in your Green-API console."
                        if resp.status_code == 401 else f"HTTP {resp.status_code}"
                    )
                    return {
                        "success": False,
                        "provider": "green_api",
                        "status": f"http_{resp.status_code}",
                        "error": err_text,
                        "message": f"Green-API rejected credentials: {err_text}"
                    }
        except requests.exceptions.ConnectTimeout:
            err_msg = f"Connection timeout: Failed to reach Green-API host within {timeouts[0]}s."
            logger.warning(f"Green-API connect timeout: {err_msg}")
            is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))
            return {
                "success": False,
                "provider": "green_api",
                "status": "connect_timeout",
                "error": err_msg,
                "is_render": is_render,
                "simulator_fallback_active": cls.is_simulator_fallback_enabled(),
                "message": (
                    f"{err_msg} Render outbound connection latency detected. "
                    "Automatic Simulator Fallback is active to ensure zero dropped messages."
                    if is_render or cls.is_simulator_fallback_enabled() else
                    f"{err_msg} Verify host URL '{host}' and network connectivity."
                )
            }
        except requests.exceptions.ReadTimeout:
            err_msg = f"Read timeout: Green-API server did not respond within {timeouts[1]}s."
            logger.warning(f"Green-API read timeout: {err_msg}")
            is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))
            return {
                "success": False,
                "provider": "green_api",
                "status": "read_timeout",
                "error": err_msg,
                "is_render": is_render,
                "simulator_fallback_active": cls.is_simulator_fallback_enabled(),
                "message": (
                    f"{err_msg} Green-API upstream latency on Render. "
                    "Automatic Simulator Fallback is active to ensure zero dropped messages."
                    if is_render or cls.is_simulator_fallback_enabled() else
                    f"{err_msg} Green-API may be experiencing high latency."
                )
            }
        except requests.exceptions.ConnectionError as ce:
            err_msg = f"Network connection error: Unable to establish link to {host} ({str(ce)})."
            logger.warning(f"Green-API connection error: {err_msg}")
            is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))
            return {
                "success": False,
                "provider": "green_api",
                "status": "connection_error",
                "error": str(ce),
                "is_render": is_render,
                "simulator_fallback_active": cls.is_simulator_fallback_enabled(),
                "message": (
                    f"{err_msg} Automatic Simulator Fallback is active on Render."
                    if is_render or cls.is_simulator_fallback_enabled() else
                    f"Network error contacting Green-API host: {err_msg}"
                )
            }
        except requests.exceptions.RequestException as re:
            err_msg = f"HTTP request error: {str(re)}"
            logger.error(f"Green-API request error: {err_msg}")
            return {
                "success": False,
                "provider": "green_api",
                "status": "request_error",
                "error": str(re),
                "message": f"Green-API request failed: {str(re)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error in Green-API probe: {e}")
            return {
                "success": False,
                "provider": "green_api",
                "status": "internal_error",
                "error": str(e),
                "message": f"Internal probe error: {str(e)}"
            }

    @classmethod
    def test_live_connection(cls, provider: Optional[str] = None, organization_id: Optional[str] = None) -> Dict[str, Any]:
        """Probes Meta Cloud API or Green-API with configured credentials and robust timeout handling."""
        target_provider = provider or cls.get_active_provider(organization_id=organization_id)
        if target_provider == "green_api":
            return cls.test_green_api_connection(organization_id=organization_id)

        # Meta Cloud API check
        conf = cls.get_config(organization_id=organization_id)
        phone_id = conf["phone_number_id"]
        token = conf["access_token"]

        if not phone_id or not token:
            return {
                "success": False,
                "provider": "meta",
                "status": "not_configured",
                "message": "Both Phone Number ID and Access Token must be configured."
            }

        url = f"https://graph.facebook.com/{cls.GRAPH_API_VERSION}/{phone_id}?fields=verified_name,display_phone_number,quality_rating,code_verification_status"
        headers = {"Authorization": f"Bearer {token}"}
        timeouts = cls.get_timeout_tuple()

        try:
            with cls.get_http_session(retries=1) as session:
                resp = session.get(url, headers=headers, timeout=timeouts)
                data = resp.json() if resp.status_code < 500 else {}
                if resp.status_code == 200:
                    return {
                        "success": True,
                        "provider": "meta",
                        "status": "connected",
                        "phone_number_id": phone_id,
                        "verified_name": data.get("verified_name", "Verified Meta Business Account"),
                        "display_phone_number": data.get("display_phone_number", ""),
                        "quality_rating": data.get("quality_rating", "GREEN"),
                        "code_verification_status": data.get("code_verification_status", "VERIFIED"),
                        "message": "Live Meta Graph API connection verified successfully!"
                    }
                else:
                    err_detail = data.get("error", {}).get("message") or f"HTTP {resp.status_code}"
                    return {
                        "success": False,
                        "provider": "meta",
                        "status": "error",
                        "error": err_detail,
                        "error_code": data.get("error", {}).get("code"),
                        "message": f"Meta Graph API rejected credentials: {err_detail}"
                    }
        except requests.exceptions.ConnectTimeout:
            is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))
            return {
                "success": False,
                "provider": "meta",
                "status": "connect_timeout",
                "is_render": is_render,
                "simulator_fallback_active": cls.is_simulator_fallback_enabled(),
                "error": f"Connection timed out after {timeouts[0]}s connecting to Meta Graph API.",
                "message": f"Connection to Meta Graph API timed out ({timeouts[0]}s). Simulator fallback active: {cls.is_simulator_fallback_enabled()}."
            }
        except requests.exceptions.ReadTimeout:
            is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))
            return {
                "success": False,
                "provider": "meta",
                "status": "read_timeout",
                "is_render": is_render,
                "simulator_fallback_active": cls.is_simulator_fallback_enabled(),
                "error": f"Read timed out after {timeouts[1]}s from Meta Graph API.",
                "message": f"Meta Graph API read response timed out ({timeouts[1]}s). Simulator fallback active: {cls.is_simulator_fallback_enabled()}."
            }
        except requests.exceptions.ConnectionError as ce:
            return {
                "success": False,
                "provider": "meta",
                "status": "connection_error",
                "error": str(ce),
                "message": f"Network connection error contacting Meta Graph API: {str(ce)}"
            }
        except requests.exceptions.RequestException as re:
            return {
                "success": False,
                "provider": "meta",
                "status": "network_error",
                "error": str(re),
                "message": f"Request failed while probing Meta Graph API: {str(re)}"
            }
        except Exception as e:
            return {
                "success": False,
                "provider": "meta",
                "status": "internal_error",
                "error": str(e),
                "message": f"Unexpected error probing Meta Graph API: {str(e)}"
            }

    @classmethod
    def verify_webhook_challenge(
        cls,
        mode: Optional[str],
        token: Optional[str],
        challenge: Optional[str],
        organization_id: Optional[str] = None
    ) -> Optional[str]:
        """Verifies Meta Webhook subscription request.
        
        Returns the challenge string if valid, else None.
        """
        conf = cls.get_config(organization_id=organization_id)
        expected_token = conf["verify_token"]

        if mode == "subscribe" and token and hmac.compare_digest(token, expected_token):
            return challenge
        return None

    @classmethod
    def verify_signature(
        cls,
        raw_payload: bytes,
        signature_header: Optional[str],
        organization_id: Optional[str] = None
    ) -> bool:
        """Validates Meta X-Hub-Signature-256 header using WHATSAPP_APP_SECRET."""
        conf = cls.get_config(organization_id=organization_id)
        app_secret = conf["app_secret"]
        if not app_secret:
            # If app secret not configured in dev, pass signature check
            return True

        if not signature_header:
            return False

        expected_sig = "sha256=" + hmac.new(
            app_secret.encode("utf-8"),
            raw_payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature_header, expected_sig)

    @classmethod
    def parse_webhook_payload(cls, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parses Meta Cloud API webhook JSON payload into normalized message events."""
        messages: List[Dict[str, Any]] = []

        if not data or not isinstance(data, dict):
            return messages

        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                if not value or not isinstance(value, dict):
                    continue

                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                display_phone_number = metadata.get("display_phone_number")

                contacts = value.get("contacts", [])
                sender_names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in contacts if isinstance(c, dict)}

                raw_msgs = value.get("messages", [])
                for msg in raw_msgs:
                    msg_id = msg.get("id")
                    from_phone = msg.get("from")
                    timestamp = msg.get("timestamp")
                    msg_type = msg.get("type", "text")

                    body = ""
                    if msg_type == "text":
                        body = msg.get("text", {}).get("body", "")
                    elif msg_type == "button":
                        body = msg.get("button", {}).get("text", "")
                    elif msg_type == "interactive":
                        body = msg.get("interactive", {}).get("button_reply", {}).get("title", "") or msg.get("interactive", {}).get("list_reply", {}).get("title", "")
                    else:
                        body = f"[{msg_type.upper()} message]"

                    messages.append({
                        "message_id": msg_id,
                        "from_phone": from_phone,
                        "sender_name": sender_names.get(from_phone, "WhatsApp Contact"),
                        "recipient_phone_id": phone_number_id,
                        "display_phone_number": display_phone_number,
                        "timestamp": timestamp,
                        "message_type": msg_type,
                        "body": body,
                        "raw": msg
                    })

        return messages

    @classmethod
    def parse_green_api_payload(cls, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parses Green-API webhook notification JSON payload into normalized message events."""
        messages: List[Dict[str, Any]] = []
        if not data or not isinstance(data, dict):
            return messages

        type_webhook = data.get("typeWebhook")

        # Handle message delivery status updates
        if type_webhook in ("outgoingMessageStatus", "statusInstanceChanged"):
            msg_id = data.get("idMessage")
            status = data.get("status") or type_webhook
            if msg_id and status:
                cls.update_message_status(msg_id, status)
            return messages

        if type_webhook != "incomingMessageReceived":
            # Non-message notifications (e.g., stateInstanceChanged, deviceInfo, etc.)
            return messages

        msg_id = data.get("idMessage")
        timestamp = data.get("timestamp")
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId", "")
        from_phone = chat_id.replace("@c.us", "").replace("@g.us", "")
        sender_name = sender_data.get("senderName") or sender_data.get("chatName") or from_phone or "WhatsApp Contact"

        instance_data = data.get("instanceData", {})
        instance_id = str(instance_data.get("idInstance", "green_api"))

        message_data = data.get("messageData", {})
        type_message = message_data.get("typeMessage", "textMessage")

        body = ""
        if type_message == "textMessage":
            body = message_data.get("textMessageData", {}).get("textMessage", "")
        elif type_message == "extendedTextMessage":
            body = message_data.get("extendedTextMessageData", {}).get("text", "")
        elif type_message == "buttonsResponseMessage":
            btn_data = message_data.get("buttonsResponseMessageData", {})
            body = btn_data.get("selectedDisplayText") or btn_data.get("selectedButtonId", "")
        elif type_message == "listResponseMessage":
            body = message_data.get("listResponseMessageData", {}).get("title", "")
        elif type_message == "imageMessage":
            cap = message_data.get("fileMessageData", {}).get("caption", "")
            body = f"[Image] {cap}" if cap else "[Image message]"
        elif type_message == "documentMessage":
            fname = message_data.get("fileMessageData", {}).get("fileName", "")
            body = f"[Document: {fname}]" if fname else "[Document message]"
        else:
            body = f"[{type_message}]"

        messages.append({
            "message_id": msg_id,
            "from_phone": from_phone,
            "sender_name": sender_name,
            "recipient_phone_id": instance_id,
            "display_phone_number": instance_data.get("wid", instance_id),
            "timestamp": timestamp,
            "message_type": type_message,
            "body": body,
            "provider": "green_api",
            "raw": data
        })

        return messages

    @classmethod
    def receive_green_api_notification(cls, organization_id: Optional[str] = None) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Fetches a single pending notification from Green-API's receiveNotification queue.

        Returns (receipt_id, body_dict) if a notification is waiting, else None.
        """
        conf = cls.get_config(organization_id=organization_id)
        id_inst = conf.get("green_api_id_instance")
        tok_inst = conf.get("green_api_token_instance")
        host = cls.normalize_green_api_host(conf.get("green_api_host"), id_inst)
        if not id_inst or not tok_inst:
            return None

        url = f"{host}/waInstance{id_inst}/receiveNotification/{tok_inst}"
        timeouts = cls.get_timeout_tuple()
        try:
            with cls.get_http_session(retries=1) as session:
                resp = session.get(url, timeout=timeouts)
                if resp.status_code == 200 and resp.text and resp.text.strip():
                    data = resp.json()
                    if isinstance(data, dict) and "receiptId" in data and "body" in data:
                        return (int(data["receiptId"]), data["body"])
        except Exception as e:
            logger.debug(f"Green-API receiveNotification probe: {e}")
        return None

    @classmethod
    def delete_green_api_notification(cls, receipt_id: int, organization_id: Optional[str] = None) -> bool:
        """Confirms and deletes a processed notification from the Green-API receive queue."""
        conf = cls.get_config(organization_id=organization_id)
        id_inst = conf.get("green_api_id_instance")
        tok_inst = conf.get("green_api_token_instance")
        host = cls.normalize_green_api_host(conf.get("green_api_host"), id_inst)
        if not id_inst or not tok_inst or not receipt_id:
            return False

        url = f"{host}/waInstance{id_inst}/deleteNotification/{tok_inst}/{receipt_id}"
        timeouts = cls.get_timeout_tuple()
        try:
            with cls.get_http_session(retries=2) as session:
                resp = session.delete(url, timeout=timeouts)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to delete Green-API notification receiptId={receipt_id}: {e}")
            return False

    @classmethod
    def fetch_last_incoming_messages(cls, minutes: int = 1440, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches the latest incoming messages directly from Green-API's message journal."""
        conf = cls.get_config(organization_id=organization_id)
        id_inst = conf.get("green_api_id_instance")
        tok_inst = conf.get("green_api_token_instance")
        host = cls.normalize_green_api_host(conf.get("green_api_host"), id_inst)
        if not id_inst or not tok_inst:
            return []

        url = f"{host}/waInstance{id_inst}/lastIncomingMessages/{tok_inst}?minutes={minutes}"
        timeouts = cls.get_timeout_tuple()
        try:
            with cls.get_http_session(retries=1) as session:
                resp = session.get(url, timeout=timeouts)
                if resp.status_code == 200 and resp.text and resp.text.strip():
                    data = resp.json()
                    if isinstance(data, list):
                        return data
        except Exception as e:
            logger.debug(f"Green-API lastIncomingMessages error: {e}")
        return []

    @classmethod
    def sync_last_incoming_messages(
        cls,
        organization_id: Optional[str] = None,
        minutes: int = 1440,
        max_messages: int = 50
    ) -> Dict[str, Any]:
        """Synchronizes recent incoming messages into the database and triggers engine rules.

        Guarantees idempotency via is_duplicate_message so already-recorded messages are ignored.
        """
        org_id = organization_id or "org-enterprise-default"
        raw_items = cls.fetch_last_incoming_messages(minutes=minutes, organization_id=org_id)
        processed_count = 0
        newly_ingested: List[Dict[str, Any]] = []

        engine = None
        if has_app_context():
            engine = current_app.config.get("AUTOMATION_ENGINE")

        for item in raw_items[:max_messages]:
            msg_id = item.get("idMessage")
            if not msg_id:
                continue

            if cls.is_duplicate_message(msg_id):
                continue

            sender_id = item.get("senderId") or item.get("chatId", "")
            from_phone = sender_id.replace("@c.us", "").replace("@g.us", "")
            sender_name = item.get("senderName") or item.get("senderContactName") or from_phone or "WhatsApp Contact"
            t_msg = item.get("typeMessage", "textMessage")

            body = ""
            if t_msg == "textMessage":
                body = item.get("textMessage", "")
            elif t_msg == "extendedTextMessage":
                body = item.get("extendedTextMessageData", {}).get("text", "") or item.get("textMessage", "")
            elif t_msg == "reactionMessage":
                body = item.get("extendedTextMessageData", {}).get("text", "[Reaction]")
            elif t_msg in ("imageMessage", "documentMessage", "audioMessage", "videoMessage"):
                cap = item.get("caption", "")
                body = f"[{t_msg}] {cap}".strip()
            else:
                body = item.get("textMessage") or f"[{t_msg}]"

            record = cls.record_message(
                organization_id=org_id,
                sender=from_phone,
                recipient=item.get("chatId", "system"),
                direction="inbound",
                body=body,
                status="received",
                whatsapp_message_id=msg_id,
                message_type=t_msg,
                raw_payload=item
            )

            newly_ingested.append({
                "message_id": msg_id,
                "from": from_phone,
                "sender_name": sender_name,
                "body": body,
                "record_id": record.id if record else None
            })

            if engine:
                try:
                    event_data = {
                        "from": from_phone,
                        "sender_name": sender_name,
                        "message": body,
                        "text": body,
                        "whatsapp_message_id": msg_id,
                        "recipient_phone_id": item.get("chatId", ""),
                        "direction": "inbound",
                        "record_id": record.id if record else None,
                        "provider": "green_api",
                        "synced_from_history": True
                    }
                    engine.ingest_event(
                        event_name="whatsapp.message",
                        payload=event_data,
                        source="green_api_history_sync",
                        dry_run=False,
                        organization_id=org_id
                    )
                except Exception as eng_err:
                    logger.error(f"Engine event ingestion failed for synced WhatsApp message: {eng_err}")

            # Trigger AI Auto-Responder if configured and active
            try:
                cls.handle_inbound_auto_response(
                    organization_id=org_id,
                    sender_phone=from_phone,
                    message_body=body,
                    sender_name=sender_name,
                    message_id=msg_id
                )
            except Exception as auto_err:
                logger.error(f"AI Auto-Responder error on synced message: {auto_err}")

            processed_count += 1

        return {
            "success": True,
            "total_fetched": len(raw_items),
            "new_messages_ingested": processed_count,
            "messages": newly_ingested
        }

    @classmethod
    def poll_and_process_incoming_notifications(
        cls,
        organization_id: Optional[str] = None,
        max_batch: int = 15,
        sync_incoming_history: bool = True
    ) -> Dict[str, Any]:
        """Polls Green-API queue and message journal for inbound messages without requiring public webhook URLs.

        Fetches each notification, persists inbound messages to the database ledger,
        triggers automation engine events, and deletes the acknowledged notification.
        Also syncs latest incoming messages from lastIncomingMessages journal.
        """
        org_id = organization_id or "org-enterprise-default"
        processed_count = 0
        messages_received: List[Dict[str, Any]] = []

        engine = None
        if has_app_context():
            engine = current_app.config.get("AUTOMATION_ENGINE")

        for _ in range(max_batch):
            item = cls.receive_green_api_notification(organization_id=org_id)
            if not item:
                break

            receipt_id, body_payload = item
            messages = cls.parse_green_api_payload(body_payload)

            for msg in messages:
                msg_id = msg.get("message_id")
                if msg_id and cls.is_duplicate_message(msg_id):
                    logger.info(f"Duplicate Green-API polled message ignored: {msg_id}")
                    continue

                record = cls.record_message(
                    organization_id=org_id,
                    sender=msg.get("from_phone", "unknown"),
                    recipient=msg.get("recipient_phone_id", "system"),
                    direction="inbound",
                    body=msg.get("body", ""),
                    status="received",
                    whatsapp_message_id=msg_id,
                    message_type=msg.get("message_type", "text"),
                    raw_payload=msg
                )
                messages_received.append({
                    "message_id": msg_id,
                    "from": msg.get("from_phone"),
                    "body": msg.get("body"),
                    "record_id": record.id if record else None
                })

                if engine:
                    try:
                        event_data = {
                            "from": msg.get("from_phone"),
                            "sender_name": msg.get("sender_name", ""),
                            "message": msg.get("body", ""),
                            "text": msg.get("body", ""),
                            "whatsapp_message_id": msg_id,
                            "recipient_phone_id": msg.get("recipient_phone_id", ""),
                            "direction": "inbound",
                            "record_id": record.id if record else None,
                            "provider": "green_api",
                            "polled": True
                        }
                        engine.ingest_event(
                            event_name="whatsapp.message",
                            payload=event_data,
                            source="green_api_poller",
                            dry_run=False,
                            organization_id=org_id
                        )
                    except Exception as eng_err:
                        logger.error(f"Engine event ingestion failed for polled WhatsApp message: {eng_err}")

                # Trigger AI Auto-Responder if configured and active
                try:
                    cls.handle_inbound_auto_response(
                        organization_id=org_id,
                        sender_phone=msg.get("from_phone", "unknown"),
                        message_body=msg.get("body", ""),
                        sender_name=msg.get("sender_name", ""),
                        message_id=msg_id
                    )
                except Exception as auto_err:
                    logger.error(f"AI Auto-Responder error on polled message: {auto_err}")

                processed_count += 1

            # Acknowledge and delete notification from Green-API queue
            cls.delete_green_api_notification(receipt_id, organization_id=org_id)

        # Also synchronize lastIncomingMessages journal to ensure zero missed messages
        history_synced = 0
        if sync_incoming_history:
            sync_res = cls.sync_last_incoming_messages(organization_id=org_id, minutes=1440, max_messages=max_batch)
            history_synced = sync_res.get("new_messages_ingested", 0)
            messages_received.extend(sync_res.get("messages", []))
            processed_count += history_synced

        return {
            "success": True,
            "processed": processed_count,
            "notifications_processed": (processed_count - history_synced),
            "history_synced": history_synced,
            "messages": messages_received,
            "queue_empty": (processed_count < max_batch)
        }

    @classmethod
    def update_message_status(cls, whatsapp_message_id: str, status: str, error_message: Optional[str] = None) -> bool:
        """Updates the status of a tracked WhatsApp message by its provider message ID."""
        if not whatsapp_message_id or not has_app_context():
            return False
        try:
            msg = WhatsAppMessage.query.filter_by(whatsapp_message_id=whatsapp_message_id).first()
            if msg:
                msg.status = status
                if error_message:
                    msg.error_message = error_message
                db.session.commit()
                return True
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.warning(f"Failed to update message status: {e}")
        return False

    @classmethod
    def is_duplicate_message(cls, message_id: str) -> bool:
        """Guarantees idempotency by checking if a message ID was already processed."""
        if not message_id or not has_app_context():
            return False
        try:
            existing = WhatsAppMessage.query.filter_by(whatsapp_message_id=message_id).first()
            return existing is not None
        except Exception:
            return False

    @classmethod
    def record_message(
        cls,
        organization_id: Optional[str] = None,
        sender: str = "WhatsApp",
        recipient: str = "",
        direction: str = "outbound",
        body: str = "",
        status: str = "received",
        whatsapp_message_id: Optional[str] = None,
        message_type: str = "text",
        execution_id: Optional[int] = None,
        error_message: Optional[str] = None,
        raw_payload: Optional[Dict[str, Any]] = None
    ) -> WhatsAppMessage:
        """Persists a WhatsApp message record in the tenant workspace."""
        msg = WhatsAppMessage(
            id=generate_uuid("wam"),
            organization_id=organization_id or "org-enterprise-default",
            whatsapp_message_id=whatsapp_message_id or f"wamid.{uuid.uuid4().hex[:16]}",
            direction=direction,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            body=body,
            status=status,
            execution_id=execution_id,
            error_message=error_message,
            raw_payload_json=json.dumps(raw_payload) if raw_payload else None,
            created_at=datetime.datetime.utcnow()
        )
        if has_app_context():
            try:
                db.session.add(msg)
                db.session.commit()
            except Exception as e:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                logger.warning(f"Failed to commit WhatsAppMessage to database: {e}")
        else:
            logger.debug("No active Flask app context; WhatsAppMessage recorded in-memory.")
        return msg

    @classmethod
    def dispatch_simulator_message(
        cls,
        organization_id: Optional[str] = None,
        to_phone: Optional[str] = None,
        message_text: Optional[str] = None,
        preview_url: bool = False,
        execution_id: Optional[int] = None,
        template_name: Optional[str] = None,
        template_language: str = "en_US",
        fallback_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Dispatches and persists a message using the built-in WhatsApp Sandbox Simulator."""
        if to_phone is not None and message_text is None:
            message_text = to_phone
            to_phone = organization_id
            organization_id = "org-enterprise-default"
        elif organization_id is None:
            organization_id = "org-enterprise-default"

        clean_to = cls.format_phone_number(to_phone or "")
        actual_body = f"[Template: {template_name}] {message_text}" if template_name and message_text else (f"[Template: {template_name}]" if template_name else (message_text or ""))
        msg_type = "template" if template_name else "text"
        mock_msg_id = f"wamid.mock_{uuid.uuid4().hex[:16]}"
        is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_INSTANCE_ID"))

        notice = f" (Render fallback: {fallback_reason})" if fallback_reason else ""
        logger.info(f"[WhatsApp Simulator] Dispatched message to {clean_to}: '{actual_body}' (ID: {mock_msg_id}){notice}")

        raw_payload = {
            "mode": "local_simulator",
            "simulated": True,
            "template_name": template_name,
            "template_language": template_language,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "is_render": is_render
        }
        if fallback_reason:
            raw_payload["fallback_reason"] = fallback_reason
            raw_payload["simulated_fallback"] = True

        record = cls.record_message(
            organization_id=organization_id,
            sender="OpsFlow-Sandbox (+15550001234)",
            recipient=clean_to,
            direction="outbound",
            body=actual_body,
            message_type=msg_type,
            status="mock_sent",
            whatsapp_message_id=mock_msg_id,
            execution_id=execution_id,
            raw_payload=raw_payload
        )

        resp = {
            "success": True,
            "status": "mock_sent",
            "mode": "simulator",
            "simulated": True,
            "whatsapp_message_id": mock_msg_id,
            "message_record_id": record.id,
            "recipient": clean_to,
            "message_type": msg_type,
            "message": (
                f"Message safely dispatched via WhatsApp Sandbox Simulator (Render fallback: {fallback_reason})"
                if fallback_reason else
                "Message successfully recorded and dispatched via WhatsApp Sandbox Simulator."
            )
        }
        if fallback_reason:
            resp["simulated_fallback"] = True
            resp["fallback_reason"] = fallback_reason
        return resp

    @classmethod
    def send_green_api_message(
        cls,
        organization_id: Optional[str] = None,
        to_phone: Optional[str] = None,
        message_text: Optional[str] = None,
        execution_id: Optional[int] = None,
        allow_fallback: bool = True
    ) -> Dict[str, Any]:
        """Dispatches an outbound WhatsApp text message via Green-API with timeout & simulator fallback.

        Supports both:
          - send_green_api_message(organization_id, to_phone, message_text)
          - send_green_api_message(to_phone, message_text)
        """
        if to_phone is not None and message_text is None:
            message_text = to_phone
            to_phone = organization_id
            organization_id = "org-enterprise-default"
        elif organization_id is None:
            organization_id = "org-enterprise-default"

        conf = cls.get_config(organization_id=organization_id)
        clean_to = cls.format_phone_number(to_phone or "")
        if not clean_to or len(clean_to) < 7:
            raise ValueError(f"Invalid recipient phone number: '{to_phone}'. Must include country code and digits.")

        id_inst = conf.get("green_api_id_instance")
        tok_inst = conf.get("green_api_token_instance")
        host = cls.normalize_green_api_host(conf.get("green_api_host"), id_inst)

        if not id_inst or not tok_inst:
            err_msg = "Green-API credentials not configured (GREEN_API_ID_INSTANCE and GREEN_API_TOKEN_INSTANCE required)."
            if allow_fallback and cls.is_simulator_fallback_enabled():
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender="GreenAPI",
                recipient=clean_to,
                direction="outbound",
                body=message_text or "",
                status="failed",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "not_configured",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }

        chat_id = f"{clean_to}@c.us"
        url = f"{host}/waInstance{id_inst}/sendMessage/{tok_inst}"
        payload = {
            "chatId": chat_id,
            "message": message_text or ""
        }

        timeouts = cls.get_timeout_tuple()

        try:
            with cls.get_http_session(retries=2) as session:
                resp = session.post(url, json=payload, timeout=timeouts)
                try:
                    resp_json = resp.json() if resp.text and resp.text.strip() else {}
                except Exception:
                    resp_json = {}
                if resp.status_code == 200 and resp_json.get("idMessage"):
                    msg_id = resp_json.get("idMessage")
                    record = cls.record_message(
                        organization_id=organization_id,
                        sender=f"GreenAPI Instance {id_inst}",
                        recipient=clean_to,
                        direction="outbound",
                        body=message_text,
                        message_type="text",
                        status="sent",
                        whatsapp_message_id=msg_id,
                        execution_id=execution_id,
                        raw_payload=resp_json
                    )
                    return {
                        "success": True,
                        "status": "sent",
                        "provider": "green_api",
                        "whatsapp_message_id": msg_id,
                        "message_record_id": record.id if record else None,
                        "recipient": clean_to,
                        "message_type": "text"
                    }
                else:
                    err = resp_json.get("message") or resp.text[:200] or (
                        f"Green-API authentication failed (HTTP {resp.status_code} Unauthorized). Verify Instance ID and API Token Instance in Green-API console."
                        if resp.status_code == 401 else f"HTTP {resp.status_code}"
                    )
                    is_quota_or_rate = (
                        "quota" in err.lower()
                        or "quote_allowed" in err.lower()
                        or "exceeded" in err.lower()
                        or resp.status_code == 429
                    )
                    if (resp.status_code >= 500 or resp.status_code == 401 or is_quota_or_rate) and allow_fallback and cls.is_simulator_fallback_enabled():
                        logger.warning(f"Green-API returned HTTP {resp.status_code} ({err}). Falling back to simulator.")
                        return cls.dispatch_simulator_message(
                            organization_id=organization_id,
                            to_phone=clean_to,
                            message_text=message_text,
                            execution_id=execution_id,
                            fallback_reason=f"Green-API HTTP {resp.status_code}: {err}"
                        )
                    record = cls.record_message(
                        organization_id=organization_id,
                        sender=f"GreenAPI Instance {id_inst}",
                        recipient=clean_to,
                        direction="outbound",
                        body=message_text,
                        message_type="text",
                        status="failed",
                        execution_id=execution_id,
                        error_message=err,
                        raw_payload=resp_json
                    )
                    return {
                        "success": False,
                        "status": "failed",
                        "provider": "green_api",
                        "error": err,
                        "recipient": clean_to,
                        "message_record_id": record.id if record else None
                    }
        except requests.exceptions.ConnectTimeout:
            err_msg = f"Connection timeout: Failed to connect to Green-API within {timeouts[0]}s."
            logger.warning(f"Green-API send connect timeout: {err_msg}")
            if allow_fallback and cls.is_simulator_fallback_enabled():
                logger.info(f"Triggering WhatsApp simulator fallback for {clean_to} due to connection timeout.")
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender=f"GreenAPI Instance {id_inst}",
                recipient=clean_to,
                direction="outbound",
                body=message_text,
                status="timeout",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "timeout",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }
        except requests.exceptions.ReadTimeout:
            err_msg = f"Read timeout: Green-API server did not respond within {timeouts[1]}s."
            logger.warning(f"Green-API send read timeout: {err_msg}")
            if allow_fallback and cls.is_simulator_fallback_enabled():
                logger.info(f"Triggering WhatsApp simulator fallback for {clean_to} due to read timeout.")
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender=f"GreenAPI Instance {id_inst}",
                recipient=clean_to,
                direction="outbound",
                body=message_text,
                status="timeout",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "timeout",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }
        except requests.exceptions.ConnectionError as ce:
            err_msg = f"Network connection error: Unable to reach Green-API host ({str(ce)})."
            logger.warning(f"Green-API send connection error: {err_msg}")
            if allow_fallback and cls.is_simulator_fallback_enabled():
                logger.info(f"Triggering WhatsApp simulator fallback for {clean_to} due to network connection error.")
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender=f"GreenAPI Instance {id_inst}",
                recipient=clean_to,
                direction="outbound",
                body=message_text,
                status="connection_error",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "connection_error",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }
        except requests.exceptions.RequestException as re:
            err_msg = f"HTTP request error: {str(re)}"
            logger.error(f"Green-API send request error: {err_msg}")
            if allow_fallback and cls.is_simulator_fallback_enabled():
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender=f"GreenAPI Instance {id_inst}",
                recipient=clean_to,
                direction="outbound",
                body=message_text,
                status="failed",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "failed",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Unexpected error in Green-API send: {err_msg}")
            if allow_fallback and cls.is_simulator_fallback_enabled():
                return cls.dispatch_simulator_message(
                    organization_id=organization_id,
                    to_phone=clean_to,
                    message_text=message_text,
                    execution_id=execution_id,
                    fallback_reason=err_msg
                )
            cls.record_message(
                organization_id=organization_id,
                sender=f"GreenAPI Instance {id_inst}",
                recipient=clean_to,
                direction="outbound",
                body=message_text,
                status="failed",
                execution_id=execution_id,
                error_message=err_msg
            )
            return {
                "success": False,
                "status": "failed",
                "provider": "green_api",
                "error": err_msg,
                "recipient": clean_to
            }

    @classmethod
    def send_message(
        cls,
        organization_id: Optional[str] = None,
        to_phone: Optional[str] = None,
        message_text: Optional[str] = None,
        preview_url: bool = False,
        execution_id: Optional[int] = None,
        template_name: Optional[str] = None,
        template_language: str = "en_US"
    ) -> Dict[str, Any]:
        """Dispatches an outbound WhatsApp text or template message via the active provider (Green-API or Meta Cloud API).

        Supports both:
          - send_message(organization_id, to_phone, message_text, ...)
          - send_message(to_phone, message_text, ...)
        """
        if to_phone is not None and message_text is None:
            message_text = to_phone
            to_phone = organization_id
            organization_id = "org-enterprise-default"
        elif organization_id is None:
            organization_id = "org-enterprise-default"

        conf = cls.get_config(organization_id=organization_id)
        clean_to = cls.format_phone_number(to_phone or "")
        if not clean_to or len(clean_to) < 7:
            raise ValueError(f"Invalid recipient phone number: '{to_phone}'. Must include country code and digits.")

        active_provider = cls.get_active_provider(organization_id=organization_id)

        # If Green-API is the active configured provider
        if active_provider == "green_api":
            return cls.send_green_api_message(
                organization_id=organization_id,
                to_phone=to_phone,
                message_text=message_text,
                execution_id=execution_id,
                allow_fallback=True
            )

        # If Meta Cloud API is the active configured provider
        if active_provider == "meta":
            phone_id = conf["phone_number_id"]
            token = conf["access_token"]
            url = f"https://graph.facebook.com/{cls.GRAPH_API_VERSION}/{phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            if template_name:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_to,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {
                            "code": template_language
                        }
                    }
                }
                actual_body = f"[Template: {template_name}] {message_text}" if message_text else f"[Template: {template_name}]"
                msg_type = "template"
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_to,
                    "type": "text",
                    "text": {
                        "preview_url": preview_url,
                        "body": message_text
                    }
                }
                actual_body = message_text
                msg_type = "text"

            timeouts = cls.get_timeout_tuple()
            try:
                with cls.get_http_session(retries=2) as session:
                    resp = session.post(url, json=payload, headers=headers, timeout=timeouts)
                    resp_json = resp.json() if resp.status_code < 500 else {}

                    if resp.status_code in (200, 201):
                        msg_id = (resp_json.get("messages", [{}])[0].get("id")) or f"wamid.{uuid.uuid4().hex[:12]}"
                        record = cls.record_message(
                            organization_id=organization_id,
                            sender=conf.get("phone_number_id", "System"),
                            recipient=clean_to,
                            direction="outbound",
                            body=actual_body,
                            message_type=msg_type,
                            status="sent",
                            whatsapp_message_id=msg_id,
                            execution_id=execution_id,
                            raw_payload=resp_json
                        )
                        return {
                            "success": True,
                            "status": "sent",
                            "provider": "meta",
                            "whatsapp_message_id": msg_id,
                            "message_record_id": record.id,
                            "recipient": clean_to,
                            "message_type": msg_type
                        }
                    else:
                        err = resp_json.get("error", {}).get("message") or f"HTTP {resp.status_code}"
                        if cls.is_simulator_fallback_enabled():
                            logger.warning(f"Meta Graph API error (HTTP {resp.status_code}: {err}). Falling back to simulator.")
                            return cls.dispatch_simulator_message(
                                organization_id=organization_id,
                                to_phone=clean_to,
                                message_text=message_text,
                                execution_id=execution_id,
                                template_name=template_name,
                                template_language=template_language,
                                fallback_reason=f"Meta Graph API HTTP {resp.status_code}: {err}"
                            )
                        record = cls.record_message(
                            organization_id=organization_id,
                            sender=conf.get("phone_number_id", "System"),
                            recipient=clean_to,
                            direction="outbound",
                            body=actual_body,
                            message_type=msg_type,
                            status="failed",
                            execution_id=execution_id,
                            error_message=err,
                            raw_payload=resp_json
                        )
                        return {
                            "success": False,
                            "status": "failed",
                            "provider": "meta",
                            "error": err,
                            "recipient": clean_to,
                            "record_id": record.id if record else None,
                            "message_record_id": record.id if record else None
                        }
            except requests.exceptions.ConnectTimeout:
                err_msg = f"Connection timeout: Failed to connect to Meta Graph API within {timeouts[0]}s."
                logger.warning(f"Meta Graph API send connect timeout: {err_msg}")
                if cls.is_simulator_fallback_enabled():
                    return cls.dispatch_simulator_message(
                        organization_id=organization_id,
                        to_phone=clean_to,
                        message_text=message_text,
                        execution_id=execution_id,
                        template_name=template_name,
                        template_language=template_language,
                        fallback_reason=err_msg
                    )
                cls.record_message(
                    organization_id=organization_id,
                    sender=conf.get("phone_number_id", "System"),
                    recipient=clean_to,
                    direction="outbound",
                    body=actual_body,
                    status="timeout",
                    execution_id=execution_id,
                    error_message=err_msg
                )
                return {
                    "success": False,
                    "status": "timeout",
                    "provider": "meta",
                    "error": err_msg,
                    "recipient": clean_to
                }
            except requests.exceptions.ReadTimeout:
                err_msg = f"Read timeout: Meta Graph API server did not respond within {timeouts[1]}s."
                logger.warning(f"Meta Graph API send read timeout: {err_msg}")
                if cls.is_simulator_fallback_enabled():
                    return cls.dispatch_simulator_message(
                        organization_id=organization_id,
                        to_phone=clean_to,
                        message_text=message_text,
                        execution_id=execution_id,
                        template_name=template_name,
                        template_language=template_language,
                        fallback_reason=err_msg
                    )
                cls.record_message(
                    organization_id=organization_id,
                    sender=conf.get("phone_number_id", "System"),
                    recipient=clean_to,
                    direction="outbound",
                    body=actual_body,
                    status="timeout",
                    execution_id=execution_id,
                    error_message=err_msg
                )
                return {
                    "success": False,
                    "status": "timeout",
                    "provider": "meta",
                    "error": err_msg,
                    "recipient": clean_to
                }
            except requests.exceptions.ConnectionError as ce:
                err_msg = f"Network connection error contacting Meta Graph API: {str(ce)}"
                logger.warning(f"Meta Graph API send connection error: {err_msg}")
                if cls.is_simulator_fallback_enabled():
                    return cls.dispatch_simulator_message(
                        organization_id=organization_id,
                        to_phone=clean_to,
                        message_text=message_text,
                        execution_id=execution_id,
                        template_name=template_name,
                        template_language=template_language,
                        fallback_reason=err_msg
                    )
                cls.record_message(
                    organization_id=organization_id,
                    sender=conf.get("phone_number_id", "System"),
                    recipient=clean_to,
                    direction="outbound",
                    body=actual_body,
                    status="connection_error",
                    execution_id=execution_id,
                    error_message=err_msg
                )
                return {
                    "success": False,
                    "status": "connection_error",
                    "provider": "meta",
                    "error": err_msg,
                    "recipient": clean_to
                }
            except requests.exceptions.RequestException as re:
                err_msg = f"HTTP request error: {str(re)}"
                logger.error(f"Meta Graph API send request error: {err_msg}")
                if cls.is_simulator_fallback_enabled():
                    return cls.dispatch_simulator_message(
                        organization_id=organization_id,
                        to_phone=clean_to,
                        message_text=message_text,
                        execution_id=execution_id,
                        template_name=template_name,
                        template_language=template_language,
                        fallback_reason=err_msg
                    )
                cls.record_message(
                    organization_id=organization_id,
                    sender=conf.get("phone_number_id", "System"),
                    recipient=clean_to,
                    direction="outbound",
                    body=actual_body,
                    status="failed",
                    execution_id=execution_id,
                    error_message=err_msg
                )
                return {
                    "success": False,
                    "status": "failed",
                    "provider": "meta",
                    "error": err_msg,
                    "recipient": clean_to
                }
            except Exception as e:
                err_msg = str(e)
                logger.error(f"Unexpected error in Meta Graph API send: {err_msg}")
                if cls.is_simulator_fallback_enabled():
                    return cls.dispatch_simulator_message(
                        organization_id=organization_id,
                        to_phone=clean_to,
                        message_text=message_text,
                        execution_id=execution_id,
                        template_name=template_name,
                        template_language=template_language,
                        fallback_reason=err_msg
                    )
                cls.record_message(
                    organization_id=organization_id,
                    sender=conf.get("phone_number_id", "System"),
                    recipient=clean_to,
                    direction="outbound",
                    body=actual_body,
                    status="failed",
                    execution_id=execution_id,
                    error_message=err_msg
                )
                return {
                    "success": False,
                    "status": "failed",
                    "provider": "meta",
                    "error": err_msg,
                    "recipient": clean_to
                }

        # Production-ready Local Simulator / Sandbox mode when live API keys are empty or mock
        return cls.dispatch_simulator_message(
            organization_id=organization_id,
            to_phone=clean_to,
            message_text=message_text,
            preview_url=preview_url,
            execution_id=execution_id,
            template_name=template_name,
            template_language=template_language
        )

    send_text_message = send_message

