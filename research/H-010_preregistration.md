# H-010 Pre-Registration — Polymarket Edge Detection (Public Research vs Market Price)

> **INMUTABLE desde el commit.** Cualquier modificación posterior a este archivo invalida el pre-registro y requiere re-registrar con nueva fecha y justificación auditable.

> **Nota**: Este documento reemplaza la versión anterior (commit 542da19, "favorite-longshot bias en elecciones").
> Justificación: ningún dato fue recolectado bajo la versión anterior. La nueva hipótesis es más amplia,
> basada en análisis estratégico de Sakana AI + GPT, e incluye deportes con datos verificables.

---

## 1. Identificación

| Campo | Valor |
|---|---|
| Experimento | H-010 |
| Título | Polymarket Edge Detection: public research vs market price deviations |
| Fecha pre-registro | 2026-06-28 |
| Repositorio | simonkey888/SENECIOORACLE |
| Branch | main |
| Autor | GLM bajo directiva SENECIO (diseño Sakana AI + revisión GPT/QwenCoder) |
| Estado | PRE-REGISTRADO — pendiente de ejecución |
| Antecedentes | H-009 NO-GO (regime filter crypto), H-010 v1 reemplazado sin datos |

---

## 2. Hipótesis

### H0 (nula)
En mercados de Polymarket con resultado binario (YES/NO) y resolución oficial verificable, no existen desviaciones sistemáticas explotables entre el precio de mercado y la probabilidad real estimada mediante investigación pública. Un trader retail con proceso sistemático no logra edge después de fees.

### H1 (alternativa)
En mercados de Polymarket con resultado binario (YES/NO) y resolución oficial verificable (deportes con datos Sportradar, eventos con fuente primaria pública), existen desviaciones sistemáticas entre el precio de mercado y la probabilidad real estimada mediante investigación pública. Estas desviaciones son explotables por un trader retail con proceso sistemático de investigación.

### Direccionalidad
Bilateral: se busca cualquier desviación >= 10pp entre nuestra estimación y el precio de mercado, en cualquier dirección.

---

## 3. Mercados objetivo

### Categorías incluidas

| Categoría | Ejemplos | Fuente de verificación |
|---|---|---|
| **Deportes con datos oficiales** | MLB, NFL, NBA — resultados con datos Sportradar | Sportradar API, resultados oficiales de la liga |
| **Eventos binarios con resolución administrativa clara** | Aprobaciones FDA, resultados electorales con fuente primaria | FDA.gov, organismos electorales oficiales |

### Criterios de inclusión
1. Resultado binario (YES/NO) con resolución verificable
2. Volumen mínimo: **10,000 USD** equivalentes en shares
3. Resolución no ambigua (no voided)
4. Fuente de resolución identificable y pública

### Criterios de exclusión
1. Política con alta narrativa (favorito-longshot bias confunde)
2. Mercados con resolución ambigua o subjetiva
3. Mercados con volumen < 10,000 USD
4. Mercados voided

---

## 4. Señal propuesta

### Definición
Diferencia entre probabilidad estimada por investigación pública (modelos estadísticos, datos históricos, fuentes primarias) y precio actual del mercado.

### Regla de apuesta
Solo apostar cuando la diferencia entre nuestra estimación y el precio de mercado es **>= 10 puntos porcentuales** (0.10 en probabilidad).

- Si `P_our_estimate - P_market >= 0.10` → comprar YES
- Si `P_market - P_our_estimate >= 0.10` → comprar NO (equivalente a apostar contra)

### Tamaño de apuesta
1 unidad normalizada por mercado. Fijo.

### No se usa umbral de precio fijo
El umbral NO es un precio fijo (ej. P > 0.70). Es una diferencia >= 10pp vs nuestra estimación.

---

## 5. N mínimo y timeline

### N mínimo
**n_min = 30 mercados resueltos.**

### Plazo máximo
**90 días** para acumular n=30. Si no se alcanza → NO-GO automático.

### Capital
**$0 — fase de paper prediction primero.**
Capital real solo si n=15 paper predictions pasan con accuracy >= 0.60.

---

## 6. Métricas (locked)

| Métrica | Definición | Cálculo |
|---|---|---|
| **Accuracy** | Proporción de mercados resueltos a favor de nuestra predicción | COUNT(correct) / n_total |
| **Calibration Error (ECE)** | Expected Calibration Error | Promedio de |accuracy_por_bin - confidence_promedio_del_bin| |
| **Profit per Bet (after fees)** | Retorno neto por apuesta después de fees de Polymarket | sum(PnL_net) / n_total. Fee ~2% por transacción (verificar por mercado). |
| **Signal Strength** | Proxy de cuánto difiere nuestra estimación del mercado | abs(P_our_estimate - P_market). Umbral: >= 0.10 |

---

## 7. Criterios GO / NO-GO

### GO (proceder a paper trading con capital real)

Se requieren **TODAS** las condiciones simultáneamente después de n_min = 30:

1. **Accuracy >= 0.55** (55% de mercados resueltos a favor de nuestra predicción)
2. **Calibration Error (ECE) <= 0.10**
3. **Profit per Bet after fees > 0** (retorno neto positivo)
4. Plazo: n=30 alcanzado dentro de 90 días

### NO_GO (abortar)

Cualquiera de las siguientes condiciones:

1. **n=30 con accuracy <= 0.50** (no hay edge)
2. **Profit per Bet after fees <= 0 en n=20+** (edge consumido por fees)
3. **Accuracy < 0.45 con n >= 15** (early stop — señal tan mala que no merece continuar)
4. n=30 no alcanzado en 90 días

### Gate para capital real
Si paper predictions con n >= 15 tienen accuracy >= 0.60 → autorizar capital real micro ($10-50 por mercado). Si no → mantener paper.

---

## 8. Cláusula de prohibición de ajustes post-hoc

1. **No se ajustarán los criterios GO/NO-GO** después de ver los datos
2. **No se cambiará el umbral de 10pp** de diferencia
3. **No se agregarán categorías de mercado** sin re-registrar
4. **No se excluirán mercados** que cumplan los filtros de inclusión
5. **No se ajustará n_min** hacia abajo
6. **No se cambiará el fee estimado** sin documentar el fee real por mercado
7. Si los resultados son ambiguos, el resultado es **NO-GO**

---

## 9. Independencia del pipeline crypto

- ❌ No se toca `institutional_core.py`, `predict_only.py`, `market_ev.py`, `survivability.py`
- ❌ No se toca ningún archivo del freeze manifest
- ❌ No se modifica `oracle_verifier.py`
- ✅ Conector independiente (`polymarket/`)
- ✅ Tabla Supabase nueva (`polymarket_markets`)
- ✅ Señal basada en datos de mercado Polymarket + investigación pública

---

## 10. Metadatos de integridad

| Campo | Valor |
|---|---|
| SHA256 de este archivo al commit | (se calculará al commit) |
| Commit hash | (se registrará al commit) |
| Código freeze manifest (crypto) | `senecio_polymarket/freeze/manifest_sha256.txt` (71 archivos, sin cambios) |
| LIVE_GATE (crypto oracle) | LOCKED / PAPER_ONLY |
| Tipo de experimento | Prospectivo pre-registrado |
| Fuente del diseño | Sakana AI + GPT strategic analysis |

---

*Pre-registro locked. Próxima edición = nuevo pre-registro con fecha posterior.*
