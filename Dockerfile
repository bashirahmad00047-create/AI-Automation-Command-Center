FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=10000 \
    WA_BRIDGE_PORT=3001 \
    NODE_OPTIONS="--max-old-space-size=192" \
    WEB_CONCURRENCY=1 \
    PYTHON_THREADS=4

WORKDIR /app

# Install system dependencies, curl, and Node.js 20 LTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    ffmpeg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy package manifests first for optimal layer caching
COPY requirements.txt package.json package-lock.json* ./

# Install Python requirements and npm dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    npm install

# Copy application source code
COPY . .

# Ensure start.sh is executable
RUN chmod +x start.sh

# Expose web service port (Render default 10000)
EXPOSE 10000 5000

# Run entrypoint script
CMD ["/bin/bash", "start.sh"]
