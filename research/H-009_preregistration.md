# H-009 Pre-Registration — Regime Filter Retrospective Analysis

> **INMUTABLE desde el commit.** Cualquier modificación posterior a este archivo invalida el pre-registro y requiere re-registrar con nueva fecha y justificación auditable.

---

## 1. Identificación

| Campo | Valor |
|---|---|
| Experimento | H-009 |
| Título | Regime filter retrospective: does filtering predictions by regime_hint improve net PnL? |
| Fecha pre-registro | 2026-06-27 |
| Repositorio | simonkey888/SENECIOORACLE |
| Branch | main |
| Autor | Claude (GLM) bajo directiva SENECIO |
| Estado | PRE-REGISTRADO — pendiente de ejecución |

---

## 2. Hipótesis

### H0 (nula)
Filtering predictions by `regime_hint` does **not** improve win rate. Specifically, WR_TRENDING - WR_RANGING = 0 (no statistically significant difference between regimes).

### H1 (alternativa)
TRENDING regime predictions have significantly higher win rate than RANGING regime predictions. Specifically, WR_TRENDING >= 55% with n >= 50 AND WR_RANGING <= 50% with n >= 50, with the difference being statistically significant (Fisher exact test, p < 0.05, two-sided).

### Direccionalidad
Unilateral: solo se considera evidencia a favor si TRENDING > RANGING. Si RANGING > TRENDING, el resultado es NO-GO (no se invierte la hipótesis).

---

## 3. Definición del dataset

### Fuente de datos
Tabla `oracle_predictions` en Supabase (producción), correspondiente al sistema SENECIO Oracle desplegado en fly.io.

### Campos utilizados
- `audit->'pipeline'->'step2_features'->'regime_hint'` — régimen detectado al momento de la predicción
- `outcome` — resultado verificado (`WIN` o `LOSS`)

### Filtros de inclusión
- `outcome IN ('WIN', 'LOSS')` — se excluyen `SKIP`, `NULL`, `STALE`, `ERROR`
- Predicciones con `regime_hint` no nulo y no vacío
- Sin filtro de fecha (se usa toda la data disponible)

### Filtros de exclusión
- Predicciones sin `regime_hint` válido
- Predicciones con `outcome` distinto de `WIN`/`LOSS`

### Versión del dataset
La data es la existente al momento de ejecutar T2. No se añadirán predicciones posteriores al análisis sin re-registrar.

---

## 4. Ventana OOS (Out-of-Sample)

Este experimento es **retrospectivo** sobre predicciones ya realizadas por el sistema en producción. No hay split train/test ni forward-looking OOS window. La validez descansa en:

1. El SDC (Sovereign Decision Core) no fue modificado en respuesta a los datos que se analizan
2. El `regime_hint` se calculó al momento de cada predicción, sin conocimiento del outcome
3. El análisis es post-hoc pero **pre-registrado** antes de ver los resultados agrupados por régimen

**Limitación reconocida**: Al ser retrospectivo, el resultado es **exploratorio-confirmatorio** (pre-registered hypothesis on existing data), no un ensayo prospectivo. Si H-009 pasa GO, el siguiente paso sería un ensayo prospectivo (paper trading con filtro).

---

## 5. Criterios GO / NO-GO

### GO (proceder a paper trading con regime filter)

Se requieren **TODAS** las condiciones simultáneamente:

1. **n_TRENDING >= 50** (mínimo 50 predicciones TRENDING con outcome WIN/LOSS)
2. **n_RANGING >= 50** (mínimo 50 predicciones RANGING con outcome WIN/LOSS)
3. **WR_TRENDING >= 55%** (win rate en régimen TRENDING)
4. **WR_RANGING <= 50%** (win rate en régimen RANGING)
5. **Fisher exact test p < 0.05** (two-sided, diferencia estadísticamente significativa)

### NO_GO (no implementar filtro; mantener SDC sin cambios)

Cualquiera de las siguientes condiciones es suficiente para NO-GO:

1. n_TRENDING < 50 o n_RANGING < 50 (insuficiente data)
2. WR_TRENDING < 55% (no hay edge en TRENDING)
3. WR_RANGING > 50% (RANGING también es profitable — no hay diferenciación)
4. Fisher exact test p >= 0.05 (diferencia no significativa)
5. RANGING tiene WR superior a TRENDING (hipótesis invertida)

---

## 6. Métricas definidas (locked)

| Métrica | Definición | Cálculo |
|---|---|---|
| WR por régimen | Proporción de WIN sobre (WIN + LOSS) | COUNT(WIN) / COUNT(WIN + LOSS) por regime_hint |
| n por régimen | Total de predicciones con outcome WIN/LOSS | COUNT(*) WHERE outcome IN ('WIN','LOSS') por regime_hint |
| Significancia | Fisher exact test (two-sided) | `scipy.stats.fisher_exact([[a,b],[c,d]])` donde a=WIN_TRENDING, b=LOSS_TRENDING, c=WIN_RANGING, d=LOSS_RANGING |
| Efecto | Diferencia de proporciones | WR_TRENDING - WR_RANGING |

No se usarán métricas adicionales no listadas aquí sin re-registrar.

---

## 7. Cláusula de prohibición de ajustes post-hoc

1. **No se ajustarán los criterios GO/NO-GO** después de ver los datos
2. **No se cambiará la definición de régimen** (se usa `regime_hint` tal como existe en el campo audit)
3. **No se agregarán regímenes adicionales** (ej. LOW, MEDIUM) al análisis sin re-registrar
4. **No se excluirán outliers** de las predicciones que cumplan los filtros de inclusión
5. **No se ajustará el umbral de significancia** (p < 0.05 queda fijo)
6. Si los resultados son ambiguos (ej. WR_TRENDING = 54%, cerca del umbral), el resultado es **NO-GO** — no se ajusta el umbral hacia abajo

---

## 8. Implementación (solo si GO)

Si H-009 resulta en GO, la implementación será:

- **Un único archivo nuevo**: `oracle/regime_filter.py` — standalone, no modifica archivos existentes
- **Lógica**: Lee `regime_hint` de predicciones existentes, aplica filtro SKIP a predicciones RANGING si el criterio GO se mantiene
- **No toca**: `institutional_core.py`, `predict_only.py`, `market_ev.py`, `survivability.py`, ni ningún archivo en el freeze manifest

Si H-009 resulta en NO-GO, no se crea ningún archivo nuevo.

---

## 9. Metadatos de integridad

| Campo | Valor |
|---|---|
| SHA256 de este archivo al commit | (se calculará al commit) |
| Commit hash | (se registrará al commit) |
| Código freeze manifest | `senecio_polymarket/freeze/manifest_sha256.txt` (71 archivos, sin cambios) |
| LIVE_GATE | LOCKED / PAPER_ONLY |
| Tipo de experimento | Retrospectivo pre-registrado |

---

*Pre-registro locked. Próxima edición = nuevo pre-registro con fecha posterior.*
