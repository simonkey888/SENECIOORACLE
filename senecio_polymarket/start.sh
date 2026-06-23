#!/usr/bin/env bash
# SENECIO ORACLE — start.sh (ACT-XXXI PASO_2)
# Launches both uvicorn (dashboard + prediction loop) and oracle_verifier.py
# (15-min cron-style verifier). If either dies, the other is killed and the
# container exits — Northflank will then restart it.
set -u

echo "[start.sh] launching uvicorn (dashboard + prediction loop)..."
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --workers 1 \
  --log-level info \
  --no-access-log &
UVICORN_PID=$!

echo "[start.sh] launching oracle_verifier (15-min cycle)..."
python3 /app/oracle/oracle_verifier.py &
VERIFIER_PID=$!

# Cleanup on exit
cleanup() {
  echo "[start.sh] cleanup: killing uvicorn ($UVICORN_PID) and verifier ($VERIFIER_PID)"
  kill -TERM "$UVICORN_PID" "$VERIFIER_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  wait "$VERIFIER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for either process to exit
wait -n
EXIT_CODE=$?
echo "[start.sh] one process exited (code=$EXIT_CODE) — tearing down"
exit $EXIT_CODE
