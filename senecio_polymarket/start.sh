#!/bin/sh
# SENECIO ORACLE — start.sh (ACT-XXXII)
# POSIX-compliant launcher: uvicorn (dashboard + prediction loop) + oracle_verifier.py
# CRITICAL: uvicorn.  BEST-EFFORT: oracle_verifier.
# If verifier dies → log + re-spawn (don't take down uvicorn).
set -u

echo "[start.sh] launching uvicorn..."
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8080 \
  --workers 1 \
  --log-level info \
  --no-access-log &
UVICORN_PID=$!

start_verifier() {
  echo "[start.sh] launching oracle_verifier (15-min cycle, best-effort)..."
  python3 /app/oracle/oracle_verifier.py &
  VERIFIER_PID=$!
}

start_verifier

cleanup() {
  echo "[start.sh] cleanup: killing uvicorn ($UVICORN_PID) and verifier (${VERIFIER_PID:-none})"
  kill -TERM "$UVICORN_PID" 2>/dev/null || true
  [ -n "${VERIFIER_PID:-}" ] && kill -TERM "$VERIFIER_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  [ -n "${VERIFIER_PID:-}" ] && wait "$VERIFIER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# POSIX: poll every 1s. Only uvicorn dying exits the container.
# Verifier dying → log + sleep 5 + re-spawn. Never cascade-kill uvicorn.
while true; do
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "[start.sh] uvicorn exited — shutting down container"
    VERIFIER_PID=""
    break
  fi
  if [ -n "${VERIFIER_PID:-}" ] && ! kill -0 "$VERIFIER_PID" 2>/dev/null; then
    echo "[start.sh] verifier exited (best-effort, will re-spawn in 5s)"
    VERIFIER_PID=""
    sleep 5
    start_verifier
    continue
  fi
  sleep 1
done
exit 1
