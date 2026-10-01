# syntax=docker/dockerfile:1
# Production Dockerfile for OpsFlow Enterprise AI Automation SaaS

FROM python:3.11-slim AS builder

WORKDIR /install

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final runtime image
FROM python:3.11-slim

WORKDIR /app

# Install runtime utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python dependencies from builder
COPY --from=builder /install /usr/local

# Create non-root system user for security
RUN groupadd -r opsflow && useradd -r -g opsflow -d /app -s /sbin/nologin opsflow

# Copy application source code
COPY . /app

# Ensure proper permissions for database and storage directories
RUN mkdir -p /app/automation_storage/logs /app/automation_storage/output \
    && chown -R opsflow:opsflow /app

USER opsflow

# Environment variables
ENV FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    DATABASE_URL=sqlite:////app/opsflow_saas.db

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/v1/system/health || exit 1

EXPOSE 5000

# Start production WSGI server
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
