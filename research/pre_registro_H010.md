# H-010 Pre-Registro — Pivot a Mercados Políticos Binarios

**Fecha de pre-registro**: 2026-06-28
**Autor**: GLM (ejecución), Council (aprobación)
**Estado**: PRE-REGISTRADO — pendiente de validación de InternLM

---

## 1. Contexto

H-010 FASE_3 (deportes) resultó NO-GO. El edge detectado era artefacto de comparar P_market (live) contra P_estimada (pre-tournament stale). Con estimaciones actualizadas, ningún mercado deportivo cruza 10pp.

Este pre-registro aplica la lección aprendida: **toda fuente independiente debe estar pre-registrada con versión, timestamp, y regla de actualización ANTES de calcular cualquier diff.**

---

## 2. Hipótesis

Los mercados políticos binarios en Polymarket exhiben sesgo partidista documentado: participantes sobreestiman la probabilidad de resultados que favorecen su preferencia ideológica. Cuando una fuente independiente (encuestas, modelos electorales) difiere >= 10pp del precio de mercado, existe un edge explotable apostando contra el sesgo.

---

## 3. Mercados Candidatos (P2.1)

Seleccionados por: (a) resolución binaria clara, (b) fecha <= 4 meses, (c) volumen >= $100K, (d) P en rango [0.10-0.90], (e) fuente independiente disponible.

| # | Mercado | P_market | Vol | End Date | Sesgo potencial | Fuente independiente propuesta |
|---|---------|----------|-----|----------|-----------------|-------------------------------|
| 1 | Democratic Party controls House after 2026 midterms | 0.825 | $4.3M | 2026-11-03 | Overconfidence D (midterm histórico favorece D) | Cook Political, Sabato Crystal Ball, RaceToTheWH |
| 2 | Republican Party controls House after 2026 midterms | 0.175 | $3.6M | 2026-11-03 | Underestimation R (redistricting, incumbency) | Cook Political, Sabato Crystal Ball, RaceToTheWH |
| 3 | Lula wins 2026 Brazilian presidential election | 0.575 | $7.0M | 2026-10-04 | Emocional anti-Lula (Bolsonaro base) | Datafolha/IPEC/Quaest polls, AS/COA poll tracker |
| 4 | Flávio Bolsonaro wins 2026 Brazilian election | 0.223 | $7.1M | 2026-10-04 | Overconfidence Bolsonarista | Datafolha/IPEC/Quaest polls |
| 5 | AfD wins most seats in 2026 Berlin state election | 0.161 | $2.2M | 2026-09-20 | Overestimation AfD (fear premium) | Infratest dimap, Forsa, Politbarometer polls |
| 6 | CA billionaire wealth tax passes 2026 | 0.355 | $3.5M | 2026-11-03 | Anti-tax sentiment overestimation | PPIC polls, Berkeley IGS polls |
| 7 | Putin out as President by Dec 31 2026 | 0.115 | $10.1M | 2026-12-31 | Wishful thinking premium | ACAMS/academic regime models |
| 8 | Netanyahu next PM of Israel | 0.345 | $2.1M | 2026-12-31 | Emocional anti/prounión | Israeli polls (Channel 12, Maariv) |

---

## 4. Fuentes Independientes Pre-Registradas (P2.2)

Cada mercado tiene una fuente independiente designada. **No se usará ninguna otra fuente sin actualizar este pre-registro.**

### 4.1 US House Midterms (mercados 1-2)

| Campo | Valor |
|-------|-------|
| Fuente primaria | **Cook Political Report** — ratings de distritos |
| URL | https://cookpolitical.com/ratings/house-race-ratings |
| Fuente secundaria | **Sabato's Crystal Ball** (UVA Center for Politics) |
| URL | https://centerforpolitics.org/crystalball/2026-house |
| Fuente cuantitativa | **RaceToTheWH** — modelo de simulación Monte Carlo |
| URL | https://www.racetothewh.com/house |
| Timestamp válido | Última actualización antes del cálculo de diff |
| Regla de actualización | Se usará la versión más reciente publicada. Si Cook/Sabato cambian ratings, se recalcula. |
| Método de estimación | De ratings cualitativos (Lean D, Toss Up, Lean R) → conteo de distritos → probabilidad de mayoría. RaceToTheWH da probabilidad directa. |

### 4.2 Brazil Presidential Election (mercados 3-4)

| Campo | Valor |
|-------|-------|
| Fuente primaria | **Datafolha** — encuesta brasileña gold standard |
| URL | Publicado en Folha de S.Paulo |
| Fuente secundaria | **IPEC (ex-IBOPE)** y **Quaest** |
| Agregador | **AS/COA Poll Tracker** |
| URL | https://www.as-coa.org/articles/poll-tracker-brazils-2026-presidential-election |
| Timestamp válido | Encuesta publicada dentro de los 14 días previos al cálculo |
| Regla de actualización | Promedio móvil de últimas 3 encuestas de firms distintas |
| Método de estimación | Encuestas → probabilidad de victoria en 1ra/2da vuelta → modelo simple |

### 4.3 Berlin State Election (mercado 5)

| Campo | Valor |
|-------|-------|
| Fuente primaria | **Infratest dimap** — encuestas estatales alemanas |
| Fuente secundaria | **Forsa**, **Politbarometer** |
| Agregador | **Wahlrecht.de** — agregador de encuestas alemanas |
| URL | https://www.wahlrecht.de/umfragen/berlin.htm |
| Timestamp válido | Última encuesta publicada antes del cálculo |
| Método de estimación | Encuestas → proyección de escaños → probabilidad de mayoría AfD |

### 4.4 CA Wealth Tax (mercado 6)

| Campo | Valor |
|-------|-------|
| Fuente primaria | **PPIC** (Public Policy Institute of California) |
| URL | https://www.ppic.org |
| Fuente secundaria | **Berkeley IGS Poll** |
| Timestamp válido | Encuesta publicada dentro de los 30 días previos |
| Método de estimación | PPIC approval % → ajuste por sesgo de no-respuesta → probabilidad de aprobación |

### 4.5 Putin / Netanyahu (mercados 7-8)

| Campo | Valor |
|-------|-------|
| Fuente primaria | Modelos académicos de estabilidad de regímenes (ACAMS dataset) |
| Fuente secundaria | Encuestas israelíes (Channel 12, Maariv/Panel4All) para Netanyahu |
| Timestamp válido | Última publicación antes del cálculo |
| Nota | Mercados de "evento raro" — dificultad de estimación independiente alta. **Prioridad baja.** |

---

## 5. Criterios de Decisión

| Criterio | Valor |
|----------|-------|
| Umbral de señal | **|P_estimada - P_market| >= 10pp** (NO se baja sin autorización del council) |
| GO | Diff >= 10pp con fuente pre-registrada + independencia confirmada |
| NO-GO | Diff < 10pp con mejor estimación disponible |
| Early stop | n=15 accuracy < 0.45 → detener inmediatamente |
| Capital real | $0 hasta n=15 paper accuracy >= 60% |
| Autorización capital | Solo Simon |

---

## 6. Regla de Actualización de Fuente

1. Se usará siempre la **versión más reciente** de la fuente pre-registrada al momento del cálculo
2. Si la fuente no se ha actualizado en >30 días, se notifica al council y se busca alternativa
3. No se puede cambiar de fuente sin actualizar este pre-registro y obtener aprobación de InternLM
4. Los diffs se calculan SIEMPRE con el mismo timestamp de fuente y mercado (no comparar live vs stale)

---

## 7. Orden de Prioridad

1. **US House Midterms** — mayor volumen, mejores fuentes independientes, sesgo partidista documentado
2. **Brazil Presidential** — alto volumen, encuestas frecuentes, polarización extrema
3. **CA Wealth Tax** — referendo binario, encuestas PPIC, sesgo anti-fiscal
4. **Berlin AfD** — buen volumen, sesgo de miedo premium, encuestas disponibles
5. **Putin/Netanyahu** — baja prioridad, difícil estimación independiente

---

## 8. Prohibiciones

- No usar bookmakers como fuente independiente (correlacionados con Polymarket)
- No usar el mismo Polymarket como fuente (obvio)
- No ajustar manualmente estimaciones sin documentar impacto en diff
- No usar modelos stale cuando versiones actualizadas existen
- No crear módulos de trading sin señal validada
- No tocar oracle crypto
