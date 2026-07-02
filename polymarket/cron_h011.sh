#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
# SENECKIO H-011 FASE_0 — Cron wrapper con retry/backoff
# ══════════════════════════════════════════════════════════════════════
# Ejecuta vwap_detector_v2.py en modo monitor cada vez que cron lo invoca.
#
# Reglas (DeepSeek):
#   - Si el script falla por rate limiting, reintentar con backoff exponencial
#   - Si falla >5 veces consecutivas, loguear y pausar hasta intervención humana
#     (crea archivo CRON_PAUSED.flag que el humano debe borrar para reanudar)
#
# Configuración:
#   - Ventana: 3600s (1h)
#   - Modo: monitor (top-100 mercados, excluye ya-resueltos >0.95)
#   - Estimador: vwap (default)
#
# Crontab line (instalar con `crontab -e`):
#   */15 * * * * /home/z/my-project/senecio/polymarket/cron_h011.sh >> /var/log/senecio_h011_cron.log 2>&1
# ══════════════════════════════════════════════════════════════════════

set -u  # exit on undefined variable (no -e porque manejamos errores manualmente)

# ─── Configuración ───────────────────────────────────────────────────
SCRIPT_DIR="/home/z/my-project/senecio/polymarket"
DETECTOR="${SCRIPT_DIR}/vwap_detector_v2.py"
PAUSE_FLAG="${SCRIPT_DIR}/CRON_PAUSED.flag"
FAILURE_COUNTER="${SCRIPT_DIR}/.cron_failure_counter"
MAX_CONSECUTIVE_FAILURES=5
WINDOW_S=3600  # 1h ventana trades (DeepSeek spec)
MAX_RETRIES=3
LOG_PREFIX="[H011-cron $(date -u +%Y-%m-%dT%H:%M:%SZ)]"

# ─── Helpers ─────────────────────────────────────────────────────────
log() {
    echo "${LOG_PREFIX} $*"
}

# ─── Check pause flag ────────────────────────────────────────────────
if [ -f "${PAUSE_FLAG}" ]; then
    log "⚠ PAUSED — flag file ${PAUSE_FLAG} existe. Skipping ejecución."
    log "  Para reanudar: rm ${PAUSE_FLAG} && rm ${FAILURE_COUNTER}"
    exit 0
fi

# ─── Ejecutar detector con retry/backoff ─────────────────────────────
cd "${SCRIPT_DIR}" || {
    log "❌ No se pudo cd a ${SCRIPT_DIR}"
    exit 1
}

attempt=0
success=0

while [ ${attempt} -lt ${MAX_RETRIES} ]; do
    attempt=$((attempt + 1))
    log "▶ Intento ${attempt}/${MAX_RETRIES} — ejecutando detector (window=${WINDOW_S}s)"
    
    # Timestamps para medir duración
    start_ts=$(date +%s)
    
    python3 "${DETECTOR}" --mode monitor --window ${WINDOW_S} >> /tmp/h011_cron_run_$$.log 2>&1
    exit_code=$?
    
    end_ts=$(date +%s)
    duration=$((end_ts - start_ts))
    
    if [ ${exit_code} -eq 0 ]; then
        log "✅ Éxito en intento ${attempt} (duración: ${duration}s)"
        success=1
        # Reset failure counter on success
        if [ -f "${FAILURE_COUNTER}" ]; then
            rm -f "${FAILURE_COUNTER}"
        fi
        break
    else
        log "⚠ Fallo en intento ${attempt} (exit=${exit_code}, duración: ${duration}s)"
        # Log últimas 10 líneas del output para debug
        if [ -f /tmp/h011_cron_run_$$.log ]; then
            log "  Últimas 10 líneas del output:"
            tail -10 /tmp/h011_cron_run_$$.log | sed 's/^/    /'
        fi
        # Backoff exponencial: 30s, 60s, 120s
        if [ ${attempt} -lt ${MAX_RETRIES} ]; then
            backoff=$((30 * (2 ** (attempt - 1))))
            log "  Esperando ${backoff}s antes de reintentar..."
            sleep ${backoff}
        fi
    fi
done

# ─── Manejo de fallos consecutivos ───────────────────────────────────
if [ ${success} -eq 0 ]; then
    log "❌ Todos los intentos fallaron (${MAX_RETRIES}/${MAX_RETRIES})"
    
    # Incrementar contador de fallos consecutivos
    current_failures=0
    if [ -f "${FAILURE_COUNTER}" ]; then
        current_failures=$(cat "${FAILURE_COUNTER}" 2>/dev/null || echo 0)
    fi
    current_failures=$((current_failures + 1))
    echo "${current_failures}" > "${FAILURE_COUNTER}"
    
    log "  Fallos consecutivos acumulados: ${current_failures}/${MAX_CONSECUTIVE_FAILURES}"
    
    if [ ${current_failures} -ge ${MAX_CONSECUTIVE_FAILURES} ]; then
        log "🚨 UMBRAL DE FALLOS CONSECUTIVOS ALCANZADO (${current_failures} >= ${MAX_CONSECUTIVE_FAILURES})"
        log "🚨 PAUSANDO CRON — requiere intervención humana"
        log "🚨 Para reanudar:"
        log "🚨   1. Investigar causa raíz en /var/log/senecio_h011_cron.log"
        log "🚨   2. rm ${PAUSE_FLAG}"
        log "🚨   3. rm ${FAILURE_COUNTER}"
        log "🚨   4. Verificar próxima ejecución de cron"
        
        # Crear flag file con metadata
        cat > "${PAUSE_FLAG}" <<EOF
PAUSED_AT: $(date -u +%Y-%m-%dT%H:%M:%SZ)
REASON: ${MAX_CONSECUTIVE_FAILURES} fallos consecutivos del cron
ACTION_REQUIRED: Borrar este archivo + .cron_failure_counter tras investigar
LOG: /var/log/senecio_h011_cron.log
EOF
        # Salir con código distinto para que cron lo registre como fallo
        exit 2
    fi
    
    exit 1
fi

# ─── Limpiar logs temporales ─────────────────────────────────────────
rm -f /tmp/h011_cron_run_$$.log

# ─── Validación post-ejecución: confirmar que generó JSONL ───────────
latest_jsonl=$(ls -t "${SCRIPT_DIR}/results/scan_"*.jsonl 2>/dev/null | head -1)
if [ -z "${latest_jsonl}" ]; then
    log "⚠ No se generó archivo scan_*.jsonl — posible problema silencioso"
    exit 1
fi

# Verificar que el archivo tiene contenido (al menos 1 línea = 1 mercado escaneado)
n_lines=$(wc -l < "${latest_jsonl}")
if [ "${n_lines}" -lt 1 ]; then
    log "⚠ ${latest_jsonl} está vacío"
    exit 1
fi

log "📊 JSONL generado: $(basename ${latest_jsonl}) (${n_lines} mercados)"

# Verificar que el master_log fue actualizado
master_log="${SCRIPT_DIR}/results/_master_log.jsonl"
if [ ! -f "${master_log}" ]; then
    log "⚠ Master log no existe o no fue actualizado"
    exit 1
fi

n_scans_total=$(wc -l < "${master_log}")
log "📋 Master log acumula ${n_scans_total} scans totales"

exit 0
