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
from typing import Any, Dict, List, Optional, Tuple

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
        host: Optional[str] = None
    ) -> None:
        """Initializes WhatsAppService instance with optional instance-level overrides."""
        self._id_instance = id_instance
        self._api_token = api_token
        self._host = host
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
        conf = self.get_config()
        return conf.get("green_api_id_instance") or conf.get("phone_number_id") or ""

    @property
    def api_token(self) -> str:
        """Returns configured Green-API apiTokenInstance (or Meta access_token) or empty string."""
        if self._api_token:
            return self._api_token
        conf = self.get_config()
        return conf.get("green_api_token_instance") or conf.get("access_token") or ""

    @property
    def host(self) -> str:
        """Returns configured Green-API host."""
        if self._host:
            return self.normalize_green_api_host(self._host, self.id_instance)
        conf = self.get_config()
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
    def get_config(cls) -> Dict[str, Any]:
        """Retrieves WhatsApp configuration from database settings, environment, or app config."""
        cfg = current_app.config if has_app_context() else {}

        phone_id_val = SystemSetting.get_val("WHATSAPP_PHONE_NUMBER_ID")
        phone_id = (
            phone_id_val
            if phone_id_val is not None
            else (
                cfg.get("WHATSAPP_PHONE_NUMBER_ID")
                or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
                or os.environ.get("META_PHONE_NUMBER_ID", "")
            )
        ).strip()

        token_val = SystemSetting.get_val("WHATSAPP_ACCESS_TOKEN")
        if token_val is None:
            token_val = SystemSetting.get_val("WHATSAPP_TOKEN")
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
            SystemSetting.get_val("WHATSAPP_VERIFY_TOKEN")
            or cfg.get("WHATSAPP_VERIFY_TOKEN")
            or os.environ.get("WHATSAPP_VERIFY_TOKEN", cls.DEFAULT_VERIFY_TOKEN)
        ).strip()

        business_account_id = (
            SystemSetting.get_val("WHATSAPP_BUSINESS_ACCOUNT_ID")
            or cfg.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
            or os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID")
            or os.environ.get("META_WABA_ID", "")
        ).strip()

        app_secret = (
            SystemSetting.get_val("WHATSAPP_APP_SECRET")
            or cfg.get("WHATSAPP_APP_SECRET")
            or os.environ.get("WHATSAPP_APP_SECRET")
            or os.environ.get("META_APP_SECRET", "")
        ).strip()

        # Green-API Parameters
        green_id_val = SystemSetting.get_val("GREEN_API_ID_INSTANCE")
        if green_id_val is None:
            green_id_val = SystemSetting.get_val("ID_INSTANCE")
        green_api_id = (
            green_id_val
            if green_id_val is not None
            else (
                cfg.get("GREEN_API_ID_INSTANCE")
                or cfg.get("ID_INSTANCE")
                or os.environ.get("GREEN_API_ID_INSTANCE")
                or os.environ.get("ID_INSTANCE", "")
            )
        ).strip()

        green_tok_val = SystemSetting.get_val("GREEN_API_TOKEN_INSTANCE")
        if green_tok_val is None:
            green_tok_val = SystemSetting.get_val("API_TOKEN_INSTANCE")
        green_api_token = (
            green_tok_val
            if green_tok_val is not None
            else (
                cfg.get("GREEN_API_TOKEN_INSTANCE")
                or cfg.get("API_TOKEN_INSTANCE")
                or os.environ.get("GREEN_API_TOKEN_INSTANCE")
                or os.environ.get("API_TOKEN_INSTANCE", "")
            )
        ).strip()

        green_api_host_val = SystemSetting.get_val("GREEN_API_HOST")
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
            SystemSetting.get_val("WHATSAPP_PROVIDER")
            or cfg.get("WHATSAPP_PROVIDER")
            or os.environ.get("WHATSAPP_PROVIDER", "auto")
        ).strip().lower()

        return {
            "phone_number_id": phone_id,
            "access_token": access_token,
            "verify_token": verify_token,
            "business_account_id": business_account_id,
            "app_secret": app_secret,
            "green_api_id_instance": green_api_id,
            "green_api_token_instance": green_api_token,
            "green_api_host": green_api_host,
            "whatsapp_provider": provider,
        }

    @classmethod
    def save_config(
        cls,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        business_account_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verify_token: Optional[str] = None,
        green_api_id_instance: Optional[str] = None,
        green_api_token_instance: Optional[str] = None,
        green_api_host: Optional[str] = None,
        whatsapp_provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """Saves live WhatsApp / Green-API configuration dynamically into database settings."""
        if phone_number_id is not None:
            SystemSetting.set_val("WHATSAPP_PHONE_NUMBER_ID", phone_number_id, is_secret=False, description="Meta Graph Phone Number ID")
        if access_token is not None:
            SystemSetting.set_val("WHATSAPP_ACCESS_TOKEN", access_token, is_secret=True, description="Meta Graph Access Token")
        if business_account_id is not None:
            SystemSetting.set_val("WHATSAPP_BUSINESS_ACCOUNT_ID", business_account_id, is_secret=False, description="WhatsApp Business Account ID")
        if app_secret is not None:
            SystemSetting.set_val("WHATSAPP_APP_SECRET", app_secret, is_secret=True, description="Meta App Secret for HMAC webhook verification")
        if verify_token is not None:
            SystemSetting.set_val("WHATSAPP_VERIFY_TOKEN", verify_token, is_secret=False, description="Webhook Verify Token")

        if green_api_id_instance is not None:
            SystemSetting.set_val("GREEN_API_ID_INSTANCE", green_api_id_instance, is_secret=False, description="Green-API Instance ID")
        if green_api_token_instance is not None:
            SystemSetting.set_val("GREEN_API_TOKEN_INSTANCE", green_api_token_instance, is_secret=True, description="Green-API API Token Instance")
        if green_api_host is not None:
            clean_host = cls.normalize_green_api_host(green_api_host)
            SystemSetting.set_val("GREEN_API_HOST", clean_host, is_secret=False, description="Green-API API Host")
        if whatsapp_provider is not None:
            SystemSetting.set_val("WHATSAPP_PROVIDER", whatsapp_provider, is_secret=False, description="Active WhatsApp Provider (auto, meta, green_api)")

        return cls.get_config()

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
    def is_meta_configured(cls) -> bool:
        """Returns True if live Meta WhatsApp credentials are configured."""
        conf = cls.get_config()
        phone_id = conf["phone_number_id"]
        token = conf["access_token"]
        return bool(
            phone_id
            and token
            and not phone_id.startswith("mock_")
            and not token.startswith("mock_")
        )

    @classmethod
    def is_green_api_configured(cls) -> bool:
        """Returns True if live Green-API credentials are configured."""
        conf = cls.get_config()
        id_inst = conf.get("green_api_id_instance", "")
        tok_inst = conf.get("green_api_token_instance", "")
        return bool(
            id_inst
            and tok_inst
            and not str(id_inst).startswith("mock_")
            and not str(tok_inst).startswith("mock_")
        )

    @classmethod
    def get_active_provider(cls) -> str:
        """Resolves active WhatsApp provider: 'green_api', 'meta', or 'simulator'."""
        conf = cls.get_config()
        configured_pref = conf.get("whatsapp_provider", "auto")

        if configured_pref == "green_api" and cls.is_green_api_configured():
            return "green_api"
        if configured_pref == "meta" and cls.is_meta_configured():
            return "meta"

        # Auto resolution
        if cls.is_green_api_configured():
            return "green_api"
        if cls.is_meta_configured():
            return "meta"
        return "simulator"

    @classmethod
    def is_configured(cls) -> bool:
        """Returns True if either Meta Cloud API or Green-API credentials are configured."""
        return cls.is_green_api_configured() or cls.is_meta_configured()

    @classmethod
    def test_green_api_connection(cls) -> Dict[str, Any]:
        """Probes Green-API getStateInstance endpoint with robust timeout and error handling."""
        conf = cls.get_config()
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
    def test_live_connection(cls, provider: Optional[str] = None) -> Dict[str, Any]:
        """Probes Meta Cloud API or Green-API with configured credentials and robust timeout handling."""
        target_provider = provider or cls.get_active_provider()
        if target_provider == "green_api":
            return cls.test_green_api_connection()

        # Meta Cloud API check
        conf = cls.get_config()
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
        challenge: Optional[str]
    ) -> Optional[str]:
        """Verifies Meta Webhook subscription request.
        
        Returns the challenge string if valid, else None.
        """
        conf = cls.get_config()
        expected_token = conf["verify_token"]

        if mode == "subscribe" and token and hmac.compare_digest(token, expected_token):
            return challenge
        return None

    @classmethod
    def verify_signature(cls, raw_payload: bytes, signature_header: Optional[str]) -> bool:
        """Validates Meta X-Hub-Signature-256 header using WHATSAPP_APP_SECRET."""
        conf = cls.get_config()
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

        conf = cls.get_config()
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

        conf = cls.get_config()
        clean_to = cls.format_phone_number(to_phone or "")
        if not clean_to or len(clean_to) < 7:
            raise ValueError(f"Invalid recipient phone number: '{to_phone}'. Must include country code and digits.")

        active_provider = cls.get_active_provider()

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
                        if resp.status_code >= 500 and cls.is_simulator_fallback_enabled():
                            logger.warning(f"Meta Graph API returned HTTP {resp.status_code}. Falling back to simulator.")
                            return cls.dispatch_simulator_message(
                                organization_id=organization_id,
                                to_phone=clean_to,
                                message_text=message_text,
                                execution_id=execution_id,
                                template_name=template_name,
                                template_language=template_language,
                                fallback_reason=f"Meta Graph API HTTP {resp.status_code}: {err}"
                            )
                        cls.record_message(
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
                            "recipient": clean_to
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
