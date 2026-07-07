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
python3 /app/polymarket/dashboard.py &
DASHBOARD_PID=$!
echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Dashboard PID: ${DASHBOARD_PID}"

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
