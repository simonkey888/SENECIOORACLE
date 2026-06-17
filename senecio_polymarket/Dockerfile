# SENECIO ORACLE — Dockerfile for Fly.io (v2)
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

# Ensure data dir exists (audit JSONL writes here)
RUN mkdir -p /app/data/audit && chmod -R 777 /app/data

# Python optimizations for low-memory container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose the internal port Fly routes to
EXPOSE 8080

# Healthcheck — Fly uses /api/health via http_service.checks, but this is a backup
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8080/api/health || exit 1

# Run uvicorn (single worker — fits in 256MB)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--log-level", "info", "--no-access-log"]
