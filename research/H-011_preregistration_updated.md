# H-011 — Pre-Registro Actualizado (post-FASE 0.6 + V2)

**Fecha de actualización**: 2026-06-30
**Autor**: GLM (ejecutor), revisado por Council
**Estado**: LISTO PARA MONITOREO DE 7 DÍAS (pendiente autorización Claude/Simon)

---

## 1. Estadístico

**VWAP Cross-Leg**: `S = VWAP_YES + VWAP_NO` donde `VWAP = sum(price × size) / sum(size)`
sobre todos los trades ejecutados en el mercado dentro de la ventana `[t-W, t)`.

- **`dev_signed = S - 1.0`**: desviación firmada (+overpriced, -underpriced)
- **`dev_abs = |dev_signed|`**: desviación absoluta

**Equivalencia con paper arxiv 2508.03474**: PARCIALMENTE EQUIVALENTE.
- Fórmula VWAP: ✅ idéntica
- Umbral detección 0.02: ✅ idéntico
- Exclusión leg > 0.95: ✅ idéntica
- Ventana temporal: ❌ **diferente** — nosotros usamos 1h/5min fija de fills,
  el paper usa 1 block (~2s) + carry-forward 5K blocks. Nuestro estadístico es
  una variante MÁS CONSERVADORA que detecta desviaciones sostenidas.

## 2. Ventana temporal (DEFINITIVA)

**`W = 300 segundos` (5 minutos)**

Justificación (post-FASE 0.6 + V2_VALIDATION):
- FASE 0.6 mostró que el estimador es estable bajo H₀ (desviación esperada < 0.01)
- V2_VALIDATION T2 (sensibilidad a ventana) pasó con W=300s como balance entre
  sensibilidad y estabilidad
- Ventanas más cortas (60s, 120s) tienen más ruido del estimador
- Ventanas más largas (1800s, 3600s) suavizan demasiado, pierden señales efímeras

## 3. Umbrales (INMUTABLES — pre-registro original)

- **Threshold de detección**: `dev_abs >= 0.02` (2 centavos) → `flagged = True`
- **Threshold sostenido**: `dev_abs >= 0.05` (5 centavos) → `sustained = True`
- **Exclusión**: cualquier leg > 0.95 → mercado excluido (ya resuelto)

## 4. Criterio FASE_0 → FASE_1 (Día 8)

**GO (proceder a FASE_1)**:
- ≥ 5 mercados con `dev_abs >= 0.05` (sostenido)
- en ≥ 3 scans distintos a lo largo de los 7 días
- (no necesariamente consecutivos)

**NO-GO (archivar H-011)**:
- < 5 mercados con esa condición

## 5. Implementación V2

**Script**: `/home/z/my-project/senecio/polymarket/vwap_detector_v2.py`

**Correcciones metodológicas vs V1**:
1. **Look-ahead bias fix**: ventana `[t-W, t)` estrictamente, trades con `ts >= t` descartados
2. **dev_signed**: almacenado además de dev_abs, permite distinguir overpriced (+) de underpriced (-)
3. **Multi-ventana**: `--window W` parameter, testeado con W ∈ {60, 120, 300, 600, 1200, 1800, 3600}
4. **Estimador EWMA opcional**: `--estimator {vwap, ewma}` con half-life = window
5. **Dedup**: por `transactionHash` dentro de cada ventana
6. **Paginación client-side**: `limit=500&offset=N` (los params `conditionId=`, `after=`, `before=` del endpoint son silenciosamente ignorados — lección FASE 0.5)
7. **Heurística de mercados activos**: combina top por volumen + mercados con trades en últimos 30min (vía stream global)

## 6. V2_VALIDATION — Resultados

**4/4 tests PASSED** (2026-06-30):

| Test | Veredicto | Detalle clave |
|------|-----------|---------------|
| T1: Look-ahead check | ✅ PASS | 0 violaciones en 20 trials directos + 30 trials manuales |
| T2: Sensibilidad a ventana | ✅ PASS | 7 ventanas con data, 5/6 pares adyacentes dentro de 2x |
| T3: VWAP vs EWMA | ✅ PASS | Jaccard = 1.000, 100% acuerdo en 30 snapshots |
| T4: Out-of-sample split | ✅ PASS | Distribuciones IS/OOS similares (mediana ratio = 1.00) |

**Informe completo**: `/home/z/my-project/download/h011_v2_validation_report.md`

## 7. Modo monitor (cron cada 15 min)

**Comando cron sugerido**:
```bash
*/15 * * * * cd /home/z/my-project/senecio/polymarket && python3 vwap_detector_v2.py --mode monitor --window 300 >> /var/log/senecio_h011_cron.log 2>&1
```

**Comportamiento**:
- Fetchea top-500 mercados binarios activos de Gamma API
- Pre-filtra los que tienen leg > 0.95 (ya resueltos)
- Identifica mercados activos en últimos 30 min vía stream global de data-api
- Combina ambos y escanea top-100 (activos primero, luego por volumen)
- Para cada mercado: fetch trades con paginación client-side, dedup, filtro temporal estricto
- Calcula VWAP_YES, VWAP_NO, dev_signed, dev_abs
- Aplica exclusiones y thresholds
- Persiste JSONL por scan + actualiza master log
- Duration típica: 30-75 segundos

**Outputs**:
- `/home/z/my-project/senecio/polymarket/results/scan_YYYYMMDD_HHMMSS.jsonl` (1 archivo por scan)
- `/home/z/my-project/senecio/polymarket/results/_master_log.jsonl` (append-only summary)

## 8. Análisis Día 8

Al finalizar los 7 días de monitoreo, ejecutar análisis offline:

1. Leer todos los JSONL de `results/`
2. Para cada `market` (conditionId), contar en cuántos scans distintos tuvo `dev_abs >= 0.05`
3. Si ≥ 5 mercados tienen `sustained=True` en ≥ 3 scans distintos → **GO FASE_1**
4. Si no → **ARCHIVAR H-011**

**Script de análisis offline**: pendiente de implementar al Día 8.

## 9. Restricciones (FASE_0 absolutas)

- ❌ NO órdenes de compra/venta bajo ninguna circunstancia
- ❌ NO modificar estado en Polymarket
- ❌ NO tocar oracle crypto (sigue corriendo en Northflank)
- ❌ NO mezclar con H-010 (archivado)
- ❌ NO construir ejecutor de órdenes — solo detector de lectura
- ✅ Solo lectura y persistencia de señales detectadas

## 10. Gobernanza

- **Ningún LLM puede autorizar capital real** — solo Simon, por escrito, explícitamente
- **Ningún LLM puede mergear código de producción sin revisión de Claude**
- **Ningún miembro del council (GPT, Sakana, Qwen, DeepSeek) puede declarar inicio de fase operativa** — solo Claude o Simon
- **Pre-registro inmutable**: si se necesita cambiar umbrales, ventana, o criterios, abrir nueva hipótesis (H-011b, H-011c) con pre-registro fresco

## 11. Cambios pendientes de aprobación (NO aplicados a H-011)

Estos cambios requieren nueva hipótesis con pre-registro fresco:

1. **Signo de desviación**: el criterio actual `|dev| >= umbral` detecta mispricing en ambos sentidos. Para distinguir oportunidades de arbitraje ejecutable (underpriced, `dev_signed < 0`) de reverse-arbitrage (overpriced, `dev_signed > 0`), se requiere refinar el criterio. **Recomendación: abrir H-011b** con pre-registro fresco que especifique `dev_signed <= -umbral` para arbitraje cross-leg real.

2. **Profit mínimo**: el paper filtra oportunidades con profit < $0.05 on the dollar. NO implementado en V2. Se podría agregar como filtro post-detección (no requiere nuevo pre-registro, solo documentación adicional).

3. **Filtro de liquidez mínima**: el paper filtra bids < $2.00. Se podría agregar N mínimo de trades por snapshot (ej. N >= 10) para reducir varianza del estimador en mercados ilíquidos.
