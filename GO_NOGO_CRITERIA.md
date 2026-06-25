# SENECIO Oracle — GO / NO-GO Criteria (Pre-Registered)

> **INMUTABLE desde el commit.** Cualquier modificación a este archivo después del commit inicial invalida el pre-registro y requiere re-registrar con nueva fecha y justificación auditable.

---

## GO (proceder a siguiente fase — paper → micro capital)

1. **n >= 1000 verified directional trades**
2. **WR alltime >= 53%** (two-sided p < 0.05 vs 50%)
3. **Walk-forward: >= 3 ventanas independientes de 200 trades con WR >= 52%**
4. **Calibration curve monotónica** (mayor confianza = mayor WR)

---

## NO_GO (abortar fase siguiente — mantener freeze / iterar modelo)

1. **n >= 500 con WR <= 50%** (p > 0.10 vs fair coin)
2. **Walk-forward consistentemente debajo de 50% en >= 2 ventanas**
3. **LONG + SHORT ambos <= 50% simultáneamente**

---

## Metadatos de pre-registro

| Campo | Valor |
|---|---|
| `FECHA_PRE_REGISTRO` | 2026-06-25 |
| `FUENTE` | Sakana AI analysis Q5 |
| `REGLA` | Este archivo no se modifica después del commit. Cualquier cambio invalida el pre-registro. |
| `REPO` | simonkey888/SENECIOORACLE |
| `BRANCH` | main |

---

## Notas de aplicación

- Los criterios se evalúan sobre `primary_outcome` de la tabla `oracle_predictions` (Supabase), filtrando `WIN`/`LOSS` (excluye `SKIP`, `NULL`, `STALE`, `ERROR`).
- "Verified" significa: predicción con `created_at` >= `T_resolucion` (15m o 1h según `primary`), outcome != NULL, no en estado `pending`.
- Walk-forward: ventanas no solapadas, ordenadas por `id` ascendente, sin reposición.
- Calibration curve: bins de `confidence` (e.g. 0.40-0.50, 0.50-0.60, 0.60-0.70, 0.70-0.80, 0.80-0.90, 0.90-1.00) con WR calculado por bin. Monotónica = no hay bin de mayor confianza con WR inferior a un bin de menor confianza.
- p-value: test binomial two-sided contra H0: p=0.5.

---

*Pre-registro locked. Próxima edición = nuevo pre-registro con fecha posterior.*
