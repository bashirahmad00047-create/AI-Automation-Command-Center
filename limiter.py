"""Lightweight Flask-compatible in-memory sliding-window rate limiter for OpsFlow SaaS."""

from __future__ import annotations

import functools
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
from flask import current_app, jsonify, request


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}

    def is_rate_limited(self, key: str, limit: int, window: int = 60) -> Tuple[bool, int]:
        """Checks if key has exceeded limit requests within window seconds.

        Returns:
            (is_limited, retry_after)
        """
        now = time.time()
        with self._lock:
            timestamps = self._records.setdefault(key, [])
            cutoff = now - window
            self._records[key] = [ts for ts in timestamps if ts > cutoff]
            timestamps = self._records[key]

            if len(timestamps) >= limit:
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + window - now))
                return True, retry_after

            timestamps.append(now)
            return False, 0

    def reset(self, key: Optional[str] = None) -> None:
        """Clears records for a key or all keys (useful in tests)."""
        with self._lock:
            if key:
                self._records.pop(key, None)
            else:
                self._records.clear()


limiter = InMemoryRateLimiter()


def get_client_ip() -> str:
    """Extracts client IP address respecting reverse proxies if available."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def rate_limit(
    limit: Optional[int] = None,
    window: int = 60,
    key_func: Optional[Callable[[], str]] = None,
    config_key: Optional[str] = None,
    message: str = "Rate limit exceeded. Please try again later."
):
    """Decorator to apply rate limiting to Flask routes."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if current_app.config.get("RATELIMIT_ENABLED") is False:
                return f(*args, **kwargs)

            # Determine limit: route param -> app.config[config_key] -> env var -> default 60
            actual_limit = limit
            if config_key and current_app.config.get(config_key) is not None:
                actual_limit = int(current_app.config[config_key])
            elif config_key and os.environ.get(config_key):
                actual_limit = int(os.environ[config_key])
            elif actual_limit is None:
                actual_limit = 60

            # Determine rate limit key
            if key_func:
                key = key_func()
            else:
                key = f"{request.endpoint or request.path}:{get_client_ip()}"

            is_limited, retry_after = limiter.is_rate_limited(key, actual_limit, window)
            if is_limited:
                resp = jsonify({
                    "error": message,
                    "code": "TOO_MANY_REQUESTS",
                    "retry_after": retry_after
                })
                resp.headers["Retry-After"] = str(retry_after)
                return resp, 429

            return f(*args, **kwargs)

        return decorated_function

    return decorator
