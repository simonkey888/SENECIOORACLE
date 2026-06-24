#!/bin/sh
# SENECIO ORACLE — start.sh (ACT-XXXI PASO_2)
# POSIX-compliant launcher: uvicorn (dashboard + prediction loop) + oracle_verifier.py
# Either process dying exits the container — Northflank auto-restarts.
set -u

echo "[start.sh] launching uvicorn..."
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

cleanup() {
  echo "[start.sh] cleanup: killing uvicorn ($UVICORN_PID) and verifier ($VERIFIER_PID)"
  kill -TERM "$UVICORN_PID" "$VERIFIER_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  wait "$VERIFIER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# POSIX: poll every 1s; exit if either PID is no longer alive
while true; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "[start.sh] uvicorn exited"
    break
  fi
  if ! kill -0 "$VERIFIER_PID" 2>/dev/null; then
    echo "[start.sh] verifier exited"
    break
  fi
  sleep 1
done
exit 1
