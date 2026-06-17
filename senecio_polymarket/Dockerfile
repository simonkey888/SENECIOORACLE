# SENECIO ORACLE — Dockerfile for Fly.io
FROM python:3.11-slim

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (cache layer)
COPY senecio_polymarket/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend + frontend
COPY senecio_polymarket/backend ./backend
COPY senecio_polymarket/frontend ./frontend
COPY senecio_polymarket/README.md ./README.md

# Ensure data dir exists (Fly volume mounts here)
RUN mkdir -p /app/data/audit

# Expose the internal port Fly routes to
EXPOSE 8080

# Run uvicorn (single worker — fits in 256MB)
# --host 0.0.0.0 so Fly's proxy can reach it
# --port 8080 matches fly.toml internal_port
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--log-level", "info"]
