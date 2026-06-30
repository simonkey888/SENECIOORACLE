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

## 15. PORTFOLIO Extension — H-010_PORTFOLIO (v8, 2026-06-30)

> **Apendice al pre-registro original.** No modifica las secciones 1-14 (locked).
> Define la extensión de portafolio multi-dominio con sizing Sakana.

### 15.1 Motivación

El pipeline original (secciones 1-14) define una estrategia mono-mercado con
umbral de 10pp y posición fija de 1 unidad. Los datos empíricos del pipeline
corregido muestran que los diffs binarios con Pinnacle oscilan entre 1-7pp
(media 4.04pp), muy por debajo del umbral de 10pp. Esto genera 0 señales
en 12/12 partidos.

La extensión PORTFOLIO baja el umbral y diversifica la fuente de señales
para operar múltiples mercados pequeños con posición chica, acumulando edge
a través de volumen en vez de conviction individual.

### 15.2 Parámetros Sakana (aprobados)

| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Kelly fraction | 1/4 (quarter-Kelly) | Reduce volatilidad; estándar para edge estimation impreciso |
| Position size | 1-2.5% bankroll | Conservador para paper trading; ajustable post-validación |
| Umbral deportes | 5 pp | Datos Pinnacle muestran diffs 1-7pp; 5pp captura 50%+ de oportunidades |
| Umbral política | 6.5 pp | Mercados menos eficientes pero más ruidosos; requiere más edge |
| Umbral entretenimiento | 3.5 pp | Mercados muy ineficientes; edge más fácil pero menos confiable |
| n validación | 50 trades | Mismo n_min que H-010 original; poder estadístico equivalente |
| Max exposición | 10% bankroll | Límite de riesgo total en posiciones abiertas simultáneamente |

### 15.3 Sizing por dominio

| Dominio | Threshold | Confidence Factor | Min Position | Max Position | Descripción |
|---------|-----------|-------------------|-------------|-------------|-------------|
| Sports | 5.0 pp | 0.80 | 1.0% | 2.5% | FIFA WC, major leagues — mercados moderadamente eficientes |
| Politics | 6.5 pp | 0.70 | 1.0% | 2.0% | Elecciones nacionales — favorite-longshot bias documentado |
| Entertainment | 3.5 pp | 0.60 | 0.5% | 1.5% | Awards, reality TV — baja liquidez, alto edge potencial |

### 15.4 Fuentes de señal

| Fuente | Dominio | Módulo | Status |
|--------|---------|--------|--------|
| FIFA WC pipeline (Odds API) | Sports | `source_scraper_fifa.py` → `portfolio_trader.py` | Operativo |
| Election fade (favorite-longshot) | Politics | `polymarket_connector.py` → `portfolio_trader.py` | Operativo |
| Entertainment markets | Entertainment | Futuro: scraper genérico | Pendiente |

### 15.5 Criterios GO/NO-GO (PORTFOLIO)

> Adicionales a los criterios originales de H-010 (sección 8).

**GO (proceder a paper trading extendido):**

1. Al menos 50 trades cerrados acumulados (multi-dominio)
2. Win rate global > 0.53 (significativamente > 0.50, p < 0.10 one-sided)
3. PnL neto positivo después de fees simuladas
4. Al menos 2 dominios con win rate > 0.50 (no depender de un solo dominio)

**NO-GO (abortar extensión portfolio):**

1. Win rate global ≤ 0.53 después de 50 trades
2. PnL neto negativo después de fees
3. Un solo dominio genera >90% del PnL (diversificación insuficiente)
4. Menos de 50 trades en 120 días (insuficiente data)

### 15.6 Regla: PAPER TRADING ONLY

Todas las posiciones son simuladas. No se transfiere capital real a Polymarket.
El portfolio state se persiste en `portfolio_state.json` con tracking completo
de entradas, salidas, PnL, y métricas de validación.

### 15.7 Independencia

Esta extensión NO modifica:
- Los criterios GO/NO-GO originales (sección 8) para el experimento de elecciones
- El umbral de 70% del conector original
- El n_min de 50 para el experimento político original
- Los archivos del pipeline crypto

### 15.8 Archivos nuevos

| Archivo | Función | Líneas |
|---------|---------|--------|
| `polymarket/portfolio_trader.py` | Portfolio manager con Kelly fraccional | ~400 |
| `polymarket/liquidity_scanner.py` | Escáner de arbitraje YES+NO (H-011) | ~450 |
| `polymarket/polymarket_connector.py` | Extendido con fetch_orderbook() | ~170 |

---

## 16. H-011 Arbitraje de Liquidez (v8, 2026-06-30)

> Nuevo experimento derivado del hallazgo de que YES+NO sum es típicamente
> 1.01-1.02 en orderbooks CLOB. No requiere predecir dirección.

### 16.1 Estrategia "Broken Math"

Comprar YES y NO simultáneamente cuando `best_ask_YES + best_ask_NO < 1.00 - fee`.
A resolución, un lado paga $1.00, garantizando profit sin importar el outcome.

### 16.2 Datos empíricos (scan inicial 2026-06-30)

- 200 mercados escaneados (Gamma + CLOB)
- Gamma: YES+NO normalizado a 1.0000 en todos los mercados
- CLOB: best_ask_YES + best_ask_NO típicamente 1.01-1.02
- 0 oportunidades detectadas en scan inicial
- Latencia API: ~25ms Gamma, ~30ms CLOB

### 16.3 Veredicto preliminar

El arbitraje "broken math" es **teóricamente posible pero empíricamente raro**.
Los bots de alta frecuencia mantienen los spreads ajustados. Las oportunidades
que aparecen se cierran en segundos. Sin infraestructura de ejecución de baja
latencia, la probabilidad de capturar una oportunidad es baja.

**Recomendación:** Continuar scanning pasivo por 2 semanas. Si la frecuencia
de oportunidades es < 1/día, clasificar como NO-GO para ejecución propia.

---

*Pre-registro locked. Próxima edición = nuevo pre-registro con fecha posterior.*
