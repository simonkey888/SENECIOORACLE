# H-011b — Pre-Registro (Hipótesis derivada de H-011)

**Fecha creación**: 2026-07-07 (UTC)
**Autor**: GLM (ejecutor), Council (revisión pendiente)
**Estado**: PENDIENTE DE APROBACIÓN DEL COUNCIL (Claude/Simon)
**Hipótesis padre**: H-011 (FASE_0 corriendo, READ-ONLY)

---

## 1. Motivación

H-011 está corriendo en FASE_0 desde el 3 Jul 2026 12:11 UTC. Los scans reales muestran
**señales fuertes pero metodológicamente ambiguas**:

- 3 Jul: 38 sustained, max +19.76pp
- 5 Jul: 10 sustained, max -44.01pp
- 7 Jul: 23 sustained, max +49.55pp

El criterio actual `|dev_signed| >= umbral` detecta mispricing en **ambas direcciones**.
Pero solo `dev_signed < 0` (underpriced, sum < 1.00) representa **arbitraje cross-leg
ejecutable**: comprar YES + NO a un costo total < $1.00 garantiza $1.00 al resolution.

`dev_signed > 0` (overpriced, sum > 1.00) sería "reverse arbitraje" — vender ambos
lados — pero Polymarket no permite shorting directo de forma capital-efficient.

**Recomendación de Gemini (Q4)**: abrir H-011b con criterio direccional exclusivamente
`dev_signed <= -0.02`, dejando H-011 como baseline tracking de eficiencia general.

## 2. Estadístico

Mismo que H-011 pero con filtro direccional:

```
dev_signed = (VWAP_YES + VWAP_NO) - 1.00
señal = (dev_signed <= -THRESHOLD_DIRECTIONAL)
```

- `dev_signed < 0`: underpriced (sum < 1.00) — **arbitraje ejecutable**
- `dev_signed > 0`: overpriced (sum > 1.00) — NO ejecutable en Polymarket
- Umbral: `dev_signed <= -0.02` (mismo valor absoluto que H-011, pero direccional)

## 3. Ventana temporal

**W = 3600s (1h)** — consistente con H-011 (en producción actualmente).

Justificación: H-011 ya está corriendo con W=3600s. Cambiar el valor requeriría
invalidar la data acumulada. H-011b usará el mismo W para permitir comparación
directa entre señales direccionales (H-011b) y señales absolutas (H-011).

## 4. Umbrales (PRE-REGISTRADOS — inmutables una vez aprobado)

- **Threshold direccional**: `dev_signed <= -0.02` → flagged
- **Threshold sostenido direccional**: `dev_signed <= -0.05` → sustained
- **Exclusion**: cualquier leg > 0.95 (mercados ya resueltos)
- **Staleness filter** (Gemini Q7): `|avg_ts_yes - avg_ts_no| <= 60s`
  - Mitiga artefactos de microestructura

## 5. Criterio FASE_0 → FASE_1 (Día 8 desde inicio H-011b)

**GO (proceder a FASE_1 — paper trading)**:
- ≥ 5 mercados con `dev_signed <= -0.05` sostenida
- en ≥ 3 scans distintos a lo largo de los 7 días
- Y ratio dev_signed<0 / total_signals >= 0.30 (al menos 30% de las señales son
  direccionales ejecutables, no solo ruido bidireccional)

**NO-GO (archivar H-011b)**:
- < 5 mercados con esa condición
- O ratio direccional < 0.30 (mayoría de señales son overpriced, no ejecutables)

## 6. Diferencias con H-011

| Aspecto | H-011 | H-011b |
|---------|-------|--------|
| Criterio señal | `\|dev_signed\| >= 0.02` | `dev_signed <= -0.02` |
| Detección | Bidireccional | Solo underpriced (ejecutable) |
| Staleness filter | NO (agregado post-hoc, no en pre-registro original) | SÍ (60s) |
| Estado | En producción desde 3 Jul | Pendiente aprobación |
| Pre-registro | Inmutable | Fresco, modificable hasta inicio |
| Test estadístico OOS | Criterio distribucional (mediana ratio) | **Mann-Whitney U** (riguroso, Gemini Q10) |
| FASE_1 si GO | Detector completo + executor paper trading | Mismo pero solo bajo dev_signed<0 |

## 7. Mejoras metodológicas sobre H-011 (basadas en auditoría Gemini)

1. **EWMA fix (Q3 Issue A)**: `compute_ewma` ahora usa `evaluation_ts = now_ts` en
   lugar de `max(trades.timestamp)`. Ya aplicado a `vwap_detector_v2.py`.

2. **Staleness filter (Q7)**: mercados con `|avg_ts_yes - avg_ts_no| > 60s` son
   excluidos. Configurable via `H011_STALENESS_THRESHOLD`. Ya aplicado.

3. **Test OOS riguroso (Q10)**: en lugar de criterio distribucional ad-hoc,
   H-011b usará **Mann-Whitney U** para comparar distribución de `dev_signed`
   entre IS y OOS. p < 0.05 requerido para PASS.

4. **Baseline simulation mejorada (Q9)**: H-011b exigirá simulación con
   - Ruido gaussiano + jumps (Poisson process para news events)
   - Sizes log-normales (fat tails)
   - Autocorrelación AR(1) en precios
   La simulación actual (90k iters puramente gaussianas) queda como límite inferior.

## 8. Stack técnico (igual que H-011)

- Repo: github.com/simonkey888/SENECIOORACLE
- Deploy: Northflank servicio `senecio-h011` (compartido con H-011)
- Output: `/app/polymarket/results/scan_*.jsonl` + `_master_log.jsonl`
- Volumen persistente: `h011-results-vol` (6GB NVMe, BOUND)

## 9. Implementación

H-011b no requiere un servicio separado. Se implementa como **filtro post-hoc sobre
los JSONL de H-011**:

```python
# Análisis offline Día 8
for scan_file in glob('scan_*.jsonl'):
    for line in open(scan_file):
        r = json.loads(line)
        if r['dev_signed'] is not None and r['dev_signed'] <= -0.02:
            # Señal direccional H-011b
            ...
```

Esto significa:
- H-011 sigue corriendo sin cambios (datos sin filtro)
- H-011b se evalúa offline al Día 8 sobre los mismos JSONL
- Staleness filter se aplica en producción desde ya (mejora H-011 + necesaria para H-011b)

## 10. Restricciones (mismas que H-011)

- READ-ONLY absoluto (cero órdenes reales)
- No tocar oracle crypto
- No reabrir H-010
- Cualquier cambio requiere aprobación Claude/Simon
- Capital real solo Simon por escrito

## 11. Gobernanza

- H-011b **NO es una hipótesis nueva independiente** — es un subconjunto direccional
  de H-011. Comparte data, infraestructura, y análisis Día 8.
- Pre-registro H-011b es **fresco y modificable** hasta el inicio oficial del
  monitoreo H-011b (que será el Día 8 de H-011, cuando se haga el análisis GO/NO-GO).
- Si H-011 sale NO-GO el Día 8, H-011b también se archiva automáticamente
  (no tiene sentido buscar arbitraje direccional si ni siquiera hay mispricing).
- Si H-011 sale GO, H-011b se evalúa independientemente con su propio criterio.

## 12. Pendiente de aprobación

Este pre-registro requiere aprobación explícita de Claude o Simon antes de ser
considerado activo. Mientras tanto, H-011 sigue corriendo sin cambios.
