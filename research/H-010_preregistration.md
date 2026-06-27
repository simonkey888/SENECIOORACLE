# H-010 Pre-Registration — Polymarket Edge Detection (National Political Elections)

> **INMUTABLE desde el commit.** Cualquier modificación posterior a este archivo invalida el pre-registro y requiere re-registrar con nueva fecha y justificación auditable.

---

## 1. Identificación

| Campo | Valor |
|---|---|
| Experimento | H-010 |
| Título | Polymarket Edge Detection: favorite-longshot bias in national political election markets |
| Fecha pre-registro | 2026-06-28 |
| Repositorio | simonkey888/SENECIOORACLE |
| Branch | main |
| Autor | GLM bajo directiva SENECIO (diseño Sakana + revisión GPT/QwenCoder) |
| Estado | PRE-REGISTRADO — pendiente de setup técnico y ejecución |
| Antecedente | H-009 resultó NO-GO (regime filter no muestra edge en crypto oracle) |

---

## 2. Fundamento empírico (literatura)

### Hallazgo central
Prediction markets binarios están bien calibrados en promedio, pero con desviaciones sistemáticas en ciertos tipos de eventos.

### Papers clave
1. **Wolfers & Zitzewitz (2004)** — "Prediction Markets": mercados de elecciones bien calibrados en promedio, desviaciones en eventos de alta incertidumbre/baja liquidez.
2. **Snowberg et al. (2013)** — "Prediction Markets: Theory and Practice": edge marginal (1-3%) después de costos en mercados líquidos; edge más alto en mercados con información asimétrica.
3. **Rothschild & Pennock (2014)** — "The Extent of Price Misalignment in Prediction Markets": desviación de calibración en PredictIt; mercados corporativos y climáticos muestran mayores errores sistemáticos.
4. **Servan-Schreiber et al. (2004)** — "Prediction Markets: Does Money Matter?": mercados con dinero real más eficientes, pero conservan desviaciones en eventos de baja frecuencia.

### Tamaño de efecto estimado
- Edge neto después de fees: **1-5%** en promedio.
- En eventos de alta información asimétrica: hasta **10-15%** de desviación de probabilidad.

### Benchmark de calibración (Polymarket)
- Brier Score promedio en mercados resueltos: ~0.18-0.22.
- Traders top 10%: Brier ~0.15-0.18.
- Promedio: Brier ~0.20-0.25.
- Edge necesario después de fees: accuracy > 0.52-0.53 en promedio.

### Nota sobre estructura de fees
No se asume un 2% universal. Reuters señala que la fee structure varía por tipo de apuesta y que algunos mercados geopolíticos son fee-free. El fee real por mercado se registrará y usará en el cálculo de Profit per Bet.

---

## 3. Hipótesis

### H0 (nula)
Los mercados de elecciones políticas nacionales en Polymarket están bien calibrados. Cuando la probabilidad implícita de un candidato supera el 70%, el mercado estima correctamente su probabilidad real de victoria. No hay edge exploitable después de fees.

### H1 (alternativa)
Los mercados de elecciones políticas nacionales en Polymarket están sistemáticamente mal calibrados en favor de los candidatos populares ("favorite-longshot bias"). Cuando `P_market(candidate) > 0.70`, el mercado sobreestima la probabilidad real de victoria. Apostar contra el favorito (comprar shares del outcome opuesto) produce un exceso de retorno estadísticamente significativo después de fees.

### Direccionalidad
Unilateral: solo se considera evidencia a favor si apostar contra el favorito produce edge. Si apostar a favor del favorito produce edge, el resultado es NO-GO (no se invierte la hipótesis).

---

## 4. Mercado objetivo

### Tipo
Elecciones políticas nacionales (presidenciales, parlamentarias) con resolución binaria (0/1).

### Criterios de inclusión
1. Mercado activo en Polymarket al menos 7 días antes de la resolución.
2. Volumen mínimo: **10,000 USD** equivalentes en shares.
3. Resolución no ambigua (no voided).
4. La probabilidad implícita del candidato favorito **excede 0.70** al momento de la señal.

### Criterios de exclusión
1. Mercados voided o con resolución ambigua.
2. Mercados con volumen < 10,000 USD.
3. Mercados donde el fee structure no se puede determinar.
4. Mercados de categorías distintas a elecciones políticas nacionales.

### Refinamiento GPT: alcance reducido
Se priorizan pocos mercados de alta convicción sobre una canasta amplia de edge pequeño. Retail sistemático = investigación concentrada + posicionamiento selectivo. El volumen por sí solo suele destruir el edge.

---

## 5. Señal propuesta

### Regla de apuesta
Si `P_market(candidate) > 0.70` al momento del snapshot → apostar **CONTRA** ese candidato (comprar shares del outcome opuesto).

### Tamaño de apuesta
1 unidad normalizada por mercado. Fijo, no escalado por confianza.

### Snapshot
Se toma un snapshot diario con timestamp, probabilidad del mercado, fuente usada, y razón de la señal.

### No se usa el oracle crypto
Esta señal es completamente independiente del pipeline crypto. No se toca `institutional_core.py`, `predict_only.py`, `market_ev.py`, `survivability.py`, ni ningún archivo del freeze manifest.

---

## 6. N mínimo

**n_min = 50 mercados resueltos.**

### Justificación
Poder estadístico suficiente para detectar un edge del 5% con alpha = 0.05 y beta = 0.2 (power = 0.80). Con n=50 y H0: p=0.50, un accuracy de 0.60 (30/50) da p ≈ 0.032 (test binomial one-sided).

### Timeline
- Si no se alcanzan n_min en 90 días por falta de mercados elegibles → NO-GO automático.

---

## 7. Métricas (locked)

| Métrica | Definición | Cálculo |
|---|---|---|
| **Accuracy** | Proporción de apuestas correctas | COUNT(correct) / n_total |
| **Brier Score** | Error cuadrático de probabilidad | mean((P_predicted - outcome_numeric)^2) donde outcome_numeric ∈ {0, 1} |
| **Profit per Bet** | Retorno promedio por apuesta después de fees | sum(PnL_net) / n_total. Fee real por mercado registrado. |
| **Calibration Error** | Diferencia entre probabilidad implícita y frecuencia real de victoria | abs(P_market_promedio - frecuencia_real) para mercados con P > 0.70 |

No se usarán métricas adicionales no listadas aquí sin re-registrar.

---

## 8. Criterios GO / NO-GO

### GO (proceder a implementación operativa)

Se requieren **TODAS** las condiciones simultáneamente después de n_min = 50 mercados resueltos:

1. **Accuracy > 0.55** (significativamente mayor que 0.5, test binomial one-sided, p < 0.05)
2. **Profit per Bet > 0.01** (retorno neto positivo después de fees reales)
3. **Brier Score < 0.20** (mejor que el baseline del mercado)
4. **Calibration Error reducido ≥ 0.05** vs baseline (el mercado efectivamente sobreestima al favorito)

### NO_GO (abortar estrategia — no implementar)

Cualquiera de las siguientes condiciones es suficiente:

1. Accuracy ≤ 0.55 después de n_min (no hay edge)
2. Profit per Bet ≤ 0.01 (edge consumido por fees)
3. Brier Score ≥ 0.20 (no superamos al mercado)
4. Calibration Error < 0.05 (no hay sobreestimación sistemática)
5. n_min no alcanzado en 90 días (insuficiente data)
6. Accuracy del favorito (apostar a favor) > accuracy del contra-favorito (hipótesis invertida)

---

## 9. Diseño experimental (protocolo)

### FASE 0 — Setup técnico
1. Crear directorio `polymarket/` en el repo.
2. Implementar `polymarket_connector.py` (< 100 líneas, solo dependencias estándar + httpx).
3. Crear tabla Supabase `polymarket_markets` con schema mínimo.
4. Test de conexión: debe retornar al menos 1 mercado activo real.

### FASE 1 — Recolección de datos
1. Correr `polymarket_connector.py` manualmente — reportar lista de mercados disponibles.
2. Snapshot diario de mercados elegibles (P > 0.70, volumen > 10k, resolución binaria).
3. Registrar: timestamp, market_id, P_market, our_prediction (CONTRA), fee_rate, volumen.

### FASE 2 — Paper trading acumulativo
1. Para cada mercado con señal, registrar apuesta teórica (1 unidad).
2. Al resolverse el mercado, registrar outcome (0/1) y PnL neto.
3. Acumular hasta n_min = 50.

### FASE 3 — Evaluación final (Día 91 o cuando se alcance n_min)
1. Calcular las 4 métricas locked.
2. Evaluar contra criterios GO/NO-GO.
3. Veredicto irreversible.

### Protocolo OOS (refinamiento GPT)
- Evaluación OOS por bloques temporales fijos, no por muestras mezcladas.
- Guardar post-mortem completo aunque falle: hipótesis, evidencia, y si fue suerte o señal.
- Cualquier tercero debe poder reconstruir exactamente por qué se tomó la apuesta y verificar si la ventaja venía de la señal o de azar.

---

## 10. Fuentes de información (ranking)

| Prioridad | Fuente | Justificación |
|---|---|---|
| 1 | Fuentes primarias con evento material y fecha fija | Regulatory filings, dockets, calendarios oficiales, resultados electorales oficiales. Menos dependientes de agregación social. |
| 2 | Organismos electorales oficiales | Calendarios, encuestas oficiales, proclamas. Información local que el mercado puede no haber incorporado. |
| 3 | Datos públicos estructurados | Bases históricas, rankings, series de resultados. Regla de actualización clara. |
| 4 | Agregadores con metodología explícita | Forecast aggregators como baseline, no como edge principal (ya parcialmente incorporados al precio). |
| 5 | Redes sociales / foros | Solo en nichos muy específicos o cuando se detecta un evento local antes que el resto. Ruido en mercados grandes. |

---

## 11. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Resolución ambigua (voided) | false positive/negative | Excluir mercados voided del análisis. Solo contar mercados con resolución clara 0/1. |
| Baja liquidez en mercados nicho | slippage, no ejecución | Requisito volumen > 10k USD + depth mínima antes de entrar. |
| Market impact en mercados pequeños | destruye edge | Tamaño de apuesta fijo y pequeño (1 unidad). Monitorear slippage. |
| Sesgo de survivorship en análisis histórico | false positive | Usar solo mercados resueltos durante el período de estudio, no históricos completos. |
| Fee structure variable | cálculo de PnL incorrecto | Registrar fee real por mercado. No asumir 2% universal. |
| Insider trading en mercados políticos | precios ya reflejan info privilegiada | Reuters/WSJ señalan escrutinio creciente. Si el mercado es muy competido, el edge será menor — el experimento lo detectará. |

---

## 12. Cláusula de prohibición de ajustes post-hoc

1. **No se ajustarán los criterios GO/NO-GO** después de ver los datos.
2. **No se cambiará el umbral de 70%** de probabilidad del favorito.
3. **No se agregarán mercados de otras categorías** (deportes, crypto, etc.) sin re-registrar.
4. **No se excluirán mercados** que cumplan los filtros de inclusión.
5. **No se ajustará el n_min** hacia abajo si los datos son ambiguos.
6. **No se invertirá la hipótesis** si apostar a favor del favorito resulta mejor.
7. Si los resultados son ambiguos (ej. accuracy = 0.54%), el resultado es **NO-GO**.

---

## 13. Independencia del pipeline crypto

Este experimento es completamente independiente del oracle crypto existente:

- ❌ No se toca `institutional_core.py`, `predict_only.py`, `market_ev.py`, `survivability.py`
- ❌ No se toca ningún archivo del freeze manifest
- ❌ No se modifica `oracle_verifier.py` (el verifier de crypto sigue corriendo en Northflank)
- ✅ Se crea un conector nuevo (`polymarket/`) independiente
- ✅ Se usa una tabla Supabase nueva (`polymarket_markets`)
- ✅ Señal basada en datos de mercado Polymarket, no en features crypto

---

## 14. Metadatos de integridad

| Campo | Valor |
|---|---|
| SHA256 de este archivo al commit | (se calculará al commit) |
| Commit hash | (se registrará al commit) |
| Código freeze manifest | `senecio_polymarket/freeze/manifest_sha256.txt` (71 archivos, sin cambios) |
| LIVE_GATE (crypto oracle) | LOCKED / PAPER_ONLY |
| Tipo de experimento | Prospectivo pre-registrado |
| Antecedente | H-009 NO-GO (2026-06-27) — regime filter no muestra edge |

---

*Pre-registro locked. Próxima edición = nuevo pre-registro con fecha posterior.*
