"""Gunicorn Production Configuration for Render Cloud Deployment.

Automatically binds to 0.0.0.0:$PORT and configures worker threads.
Gunicorn automatically detects this file when started with 'gunicorn app:app'.
"""

import os

# Dynamic port binding from Render environment ($PORT)
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# Concurrency & Performance
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 2
timeout = 120
keepalive = 5

# Logging to stdout/stderr for cloud platform log streams
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
