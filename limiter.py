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


class LoginRateLimiter:
    """Sliding-window rate limiter for login attempts (in-memory + DB-backed).
    Allows a maximum of 5 login attempts per minute per IP/username.
    On the 6th attempt within 60s, strictly returns HTTP 429 with lockout message.
    """

    def __init__(self, limit: int = 5, window: int = 60):
        self.limit = limit
        self.window = window
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}

    def is_rate_limited(self, ip: str, username: Optional[str] = None) -> Tuple[bool, int, str]:
        now = time.time()
        cutoff = now - self.window
        clean_user = (username or "").strip().lower()
        keys = [f"ip:{ip}"]
        if clean_user:
            keys.append(f"user:{clean_user}")
            keys.append(f"pair:{ip}:{clean_user}")

        with self._lock:
            for k in keys:
                timestamps = [ts for ts in self._records.get(k, []) if ts > cutoff]
                self._records[k] = timestamps
                if len(timestamps) >= self.limit:
                    oldest = timestamps[0]
                    retry_after = max(1, int(oldest + self.window - now))
                    msg = (
                        f"Too many login attempts. Access temporarily locked for security. "
                        f"Please wait {retry_after} seconds before trying again."
                    )
                    return True, retry_after, msg

        # DB-backed sliding-window check if database available
        try:
            from models import LoginAttempt, db
            import datetime
            cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(seconds=self.window)
            query = LoginAttempt.query.filter(LoginAttempt.attempt_time >= cutoff_dt)
            if clean_user:
                db_count = query.filter(
                    (LoginAttempt.ip_address == ip) | (LoginAttempt.username == clean_user)
                ).count()
            else:
                db_count = query.filter(LoginAttempt.ip_address == ip).count()

            if db_count >= self.limit:
                retry_after = self.window
                msg = (
                    "Too many login attempts. Access temporarily locked for security. "
                    "Please wait 1 minute before trying again."
                )
                return True, retry_after, msg
        except Exception:
            pass

        return False, 0, ""

    def record_attempt(self, ip: str, username: Optional[str] = None, success: bool = False, user_agent: Optional[str] = None) -> None:
        now = time.time()
        cutoff = now - self.window
        clean_user = (username or "").strip().lower()
        keys = [f"ip:{ip}"]
        if clean_user:
            keys.append(f"user:{clean_user}")
            keys.append(f"pair:{ip}:{clean_user}")

        with self._lock:
            for k in keys:
                timestamps = [ts for ts in self._records.setdefault(k, []) if ts > cutoff]
                timestamps.append(now)
                self._records[k] = timestamps

        try:
            from models import LoginAttempt, db
            import datetime
            attempt = LoginAttempt(
                ip_address=ip,
                username=clean_user or None,
                attempt_time=datetime.datetime.utcnow(),
                success=success,
                user_agent=user_agent
            )
            db.session.add(attempt)
            db.session.commit()
        except Exception:
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass

    def record_success(self, ip: str, username: Optional[str] = None) -> None:
        clean_user = (username or "").strip().lower()
        keys = [f"ip:{ip}"]
        if clean_user:
            keys.append(f"user:{clean_user}")
            keys.append(f"pair:{ip}:{clean_user}")
        with self._lock:
            for k in keys:
                self._records.pop(k, None)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
        try:
            from models import LoginAttempt, db
            LoginAttempt.query.delete()
            db.session.commit()
        except Exception:
            pass


login_limiter = LoginRateLimiter(limit=5, window=60)
