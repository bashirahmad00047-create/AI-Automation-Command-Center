"""Keep-Alive Self-Pinger Service for Render Cloud Deployment.

Prevents Render Free Tier web services from spinning down after 15 minutes of inactivity.
Periodically pings the service's public health endpoint in the background.
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("opsflow.keep_alive")


class KeepAliveService:
    DEFAULT_INTERVAL_SECONDS = 540  # 9 minutes (well within Render's 15-minute idle cutoff)
    DEFAULT_RENDER_URL = "https://ai-automation-command-center-4.onrender.com"
    PING_PATH = os.environ.get("KEEP_ALIVE_PING_PATH", "/health")

    _thread: Optional[threading.Thread] = None
    _stop_event = threading.Event()
    _lock = threading.Lock()

    # Telemetry
    _is_running: bool = False
    _ping_count: int = 0
    _fail_count: int = 0
    _last_ping_time: Optional[str] = None
    _last_status_code: Optional[int] = None
    _last_latency_ms: Optional[float] = None
    _last_error: Optional[str] = None
    _target_url: Optional[str] = None

    @classmethod
    def resolve_target_url(cls) -> str:
        """Resolves the external public base URL for Render self-pinging."""
        # 1. Check RENDER_EXTERNAL_URL (automatically set by Render for web services)
        url = os.environ.get("RENDER_EXTERNAL_URL")
        # 2. Check explicit APP_URL or BASE_URL or PING_TARGET_URL
        if not url:
            url = (
                os.environ.get("PING_TARGET_URL")
                or os.environ.get("APP_URL")
                or os.environ.get("BASE_URL")
                or os.environ.get("PUBLIC_URL")
            )
        # 3. Fallback to known live Render host
        if not url:
            url = cls.DEFAULT_RENDER_URL

        clean_url = url.strip().rstrip("/")
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"
        return clean_url

    @classmethod
    def is_render_environment(cls) -> bool:
        """Detects if running on Render cloud platform or explicitly enabled."""
        return bool(
            os.environ.get("RENDER")
            or os.environ.get("RENDER_SERVICE_ID")
            or os.environ.get("RENDER_INSTANCE_ID")
            or os.environ.get("RENDER_EXTERNAL_URL")
            or os.environ.get("ENABLE_KEEP_ALIVE", "").lower() in ("1", "true", "yes")
        )

    @classmethod
    def get_ping_url(cls) -> str:
        base = cls.resolve_target_url()
        return f"{base}{cls.PING_PATH}"

    @classmethod
    def ping_now(cls, timeout: float = 12.0) -> Dict[str, Any]:
        """Performs a fast ping to the keep-alive endpoint and updates telemetry."""
        ping_url = cls.get_ping_url()
        cls._target_url = ping_url
        start_time = time.time()
        headers = {
            "User-Agent": "OpsFlow-KeepAlive/2.0 (+https://render.com; anti-spindown)",
            "X-OpsFlow-Ping": "render-keep-alive"
        }
        try:
            resp = requests.get(ping_url, headers=headers, timeout=timeout)
            latency_ms = round((time.time() - start_time) * 1000, 2)
            cls._last_ping_time = datetime.datetime.utcnow().isoformat() + "Z"
            cls._last_status_code = resp.status_code
            cls._last_latency_ms = latency_ms
            cls._last_error = None
            cls._ping_count += 1

            logger.info(
                f"[Render Keep-Alive] Heartbeat ping successfully sent to {ping_url} "
                f"(Status: {resp.status_code}, Latency: {latency_ms}ms, Total Pings: {cls._ping_count})"
            )
            return {
                "success": resp.status_code == 200,
                "url": ping_url,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "timestamp": cls._last_ping_time
            }
        except Exception as e:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            cls._last_ping_time = datetime.datetime.utcnow().isoformat() + "Z"
            cls._last_status_code = None
            cls._last_latency_ms = latency_ms
            cls._last_error = str(e)
            cls._fail_count += 1
            logger.warning(f"[Render Keep-Alive] Ping to {ping_url} encountered note: {e}")
            return {
                "success": False,
                "url": ping_url,
                "error": str(e),
                "latency_ms": latency_ms,
                "timestamp": cls._last_ping_time
            }

    @classmethod
    def _run_loop(cls, interval_seconds: int) -> None:
        """Background loop executing periodic keep-alive heartbeats."""
        cls._is_running = True
        logger.info(
            f"[Render Keep-Alive] Background pinger daemon started. Interval: {interval_seconds}s. Target: {cls.get_ping_url()}"
        )

        # Initial delay of 45 seconds before first ping to allow app boot to finish
        if cls._stop_event.wait(45):
            cls._is_running = False
            return

        while not cls._stop_event.is_set():
            try:
                cls.ping_now()
            except Exception as loop_err:
                logger.error(f"[Render Keep-Alive] Unhandled error in heartbeat loop: {loop_err}")

            if cls._stop_event.wait(interval_seconds):
                break

        cls._is_running = False
        logger.info("[Render Keep-Alive] Background pinger daemon stopped.")

    @classmethod
    def should_run(cls, app=None) -> bool:
        """Determines if the keep-alive background worker should run."""
        # Never run during unit tests
        if app and app.config.get("TESTING"):
            return False

        if os.environ.get("FLASK_ENV") == "testing" or os.environ.get("TESTING") == "1":
            return False

        if os.environ.get("DISABLE_KEEP_ALIVE", "").lower() in ("1", "true", "yes"):
            return False

        # Run if on Render, explicitly enabled, or running in a deployed environment
        return (
            cls.is_render_environment()
            or os.environ.get("FLASK_ENV") == "production"
            or bool(os.environ.get("PORT"))
            or bool(os.environ.get("RENDER_EXTERNAL_URL"))
        )

    @classmethod
    def start(cls, app=None, interval_seconds: Optional[int] = None) -> bool:
        """Starts the background keep-alive pinger daemon thread if not already running."""
        if not cls.should_run(app):
            logger.debug("[Render Keep-Alive] Conditions not met for keep-alive pinger; inactive.")
            return False

        with cls._lock:
            if cls._thread and cls._thread.is_alive():
                return True

            int_val = interval_seconds
            if int_val is None:
                try:
                    int_val = int(os.environ.get("KEEP_ALIVE_INTERVAL_SECONDS", str(cls.DEFAULT_INTERVAL_SECONDS)))
                except (ValueError, TypeError):
                    int_val = cls.DEFAULT_INTERVAL_SECONDS

            cls._stop_event.clear()
            cls._thread = threading.Thread(
                target=cls._run_loop,
                args=(int_val,),
                name="OpsFlow-RenderKeepAliveThread",
                daemon=True
            )
            cls._thread.start()
            return True

    @classmethod
    def stop(cls) -> None:
        """Stops the keep-alive pinger."""
        with cls._lock:
            cls._stop_event.set()
            if cls._thread and cls._thread.is_alive():
                cls._thread.join(timeout=2.0)
            cls._is_running = False

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns diagnostic telemetry of the keep-alive service."""
        return {
            "is_running": cls._is_running or (cls._thread is not None and cls._thread.is_alive()),
            "is_render_environment": cls.is_render_environment(),
            "target_url": cls.get_ping_url(),
            "interval_seconds": int(os.environ.get("KEEP_ALIVE_INTERVAL_SECONDS", str(cls.DEFAULT_INTERVAL_SECONDS))),
            "ping_count": cls._ping_count,
            "fail_count": cls._fail_count,
            "last_ping_time": cls._last_ping_time,
            "last_status_code": cls._last_status_code,
            "last_latency_ms": cls._last_latency_ms,
            "last_error": cls._last_error
        }
