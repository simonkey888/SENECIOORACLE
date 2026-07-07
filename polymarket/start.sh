#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# SENECKIO H-011 — Orquestador de 2 procesos
# ══════════════════════════════════════════════════════════════════════
# Ejecuta en paralelo dentro del mismo pod de Northflank:
#   1. dashboard.py (FastAPI/uvicorn) — sirve el dashboard en puerto 8080
#   2. vwap_detector_v2.py — loop cada 15 min (900s)
#
# Si cualquiera de los dos procesos muere, el pod se reinicia entero
# (gracias a Northflank healthchecks / restart policy).
# ══════════════════════════════════════════════════════════════════════

set -u

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] === SENECKIO H-011 starting ==="
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Results dir: /app/polymarket/results"
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Volume mounted: $(test -d /app/polymarket/results && echo 'yes' || echo 'NO (will use ephemeral)')"

# ─── PROCESO 1: Dashboard web (background) ───────────────────────────
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting dashboard on :8080 ..."
# Redirect stderr to stdout so import errors are visible in Northflank logs
python3 /app/polymarket/dashboard.py 2>&1 &
DASHBOARD_PID=$!
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Dashboard PID: ${DASHBOARD_PID}"

# Wait 3s and check if dashboard is still alive (catch import errors)
sleep 3
if ! kill -0 ${DASHBOARD_PID} 2>/dev/null; then
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] !!! Dashboard process died — check import errors above"
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] !!! Testing imports manually..."
    python3 -c "import fastapi; print('fastapi OK')" 2>&1
    python3 -c "import uvicorn; print('uvicorn OK')" 2>&1
    python3 -c "import httpx; print('httpx OK')" 2>&1
    python3 -c "import numpy; print('numpy OK')" 2>&1
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] !!! Dashboard will NOT be available. Detector loop continues."
else
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Dashboard started successfully on :8080"
fi

# ─── PROCESO 2: Loop del detector (foreground) ───────────────────────
# Loop infinito: ejecuta el detector cada 15 minutos (900s).
# El detector hace un solo scan por invocación (modo monitor).
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting detector loop (interval=900s) ..."

while true; do
    SCAN_START=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    echo "[${SCAN_START}] === H-011 scan starting ==="

    python3 /app/polymarket/vwap_detector_v2.py --mode monitor --window 3600 2>&1 | sed 's/^/    /'

    SCAN_END=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    echo "[${SCAN_END}] === H-011 scan finished, sleeping 900s ==="

    # Verificar que el dashboard sigue vivo; si murió, salir para que el pod reinicie
    if ! kill -0 ${DASHBOARD_PID} 2>/dev/null; then
        echo "[${SCAN_END}] !!! Dashboard process died, exiting to trigger pod restart"
        exit 1
    fi

    sleep 900
done
