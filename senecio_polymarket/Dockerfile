# SENECIO ORACLE — Dockerfile (ACT XIX — Unified Oracle + Dashboard)
# Builds a single image containing:
#   1. FastAPI dashboard (backend/ + frontend/)
#   2. Real Oracle pipeline (oracle/predict_only.py + deps + ccxt)
#   3. Audit log + predictions.jsonl persistence (in-image, seed from repo)
FROM python:3.11-slim

# System deps (curl for healthcheck, git for optional push-back)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (cache layer)
COPY senecio_polymarket/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend + frontend (dashboard)
COPY senecio_polymarket/backend ./backend

# Copy frontend (dashboard static files)
COPY senecio_polymarket/frontend ./frontend

# Copy Oracle modules (real prediction pipeline)
COPY senecio_polymarket/oracle ./oracle

# Copy start.sh (launches uvicorn + oracle_verifier.py)
COPY senecio_polymarket/start.sh ./start.sh
RUN chmod +x ./start.sh

# Ensure runtime dirs exist
RUN mkdir -p /app/data/audit && chmod -R 777 /app/data
# senecio_output is already copied with seed predictions.jsonl via oracle/

# Python optimizations for low-memory container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Make oracle modules importable
ENV PYTHONPATH=/app:/app/oracle

# Expose the internal port Northflank routes to
EXPOSE 8080

# Healthcheck — uses /api/health which now returns oracle status
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8080/api/health || exit 1

# Run uvicorn + oracle_verifier (start.sh manages both processes)
CMD ["./start.sh"]
