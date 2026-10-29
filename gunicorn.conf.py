import logging
import os

logger = logging.getLogger("gunicorn.config")

# Bind configuration: Render assigns PORT dynamically (e.g. 10000)
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("PYTHON_THREADS", "4"))
timeout = int(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "120"))
