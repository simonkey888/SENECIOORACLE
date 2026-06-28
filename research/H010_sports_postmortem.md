# H-010 Sports Markets Post-Mortem

**Fecha**: 2026-06-28
**Estado**: ARCHIVADO — NO-GO
**Veredicto del Council**: UNÁNIME

---

## 1. Resumen Ejecutivo

Se investigaron 3 mercados deportivos en Polymarket buscando un edge >= 10pp entre estimaciones independientes y precios de mercado. **Ningún mercado cruzó el umbral** cuando se usaron estimaciones independientes actualizadas. El edge inicial era un artefacto de comparar precios en vivo contra modelos pre-tournament desactualizados.

---

## 2. Mercados Evaluados

| Mercado | P_market | P_estimada_raw | Diff RAW | P_estimada_actualizada | Diff actualizada | Señal |
|---------|----------|---------------|----------|----------------------|-----------------|-------|
| Argentina WC 2026 | 0.2085 | 0.104 (Opta pre) | 10.4pp | 0.163 (Opta post) | 4.55pp | NO |
| France WC 2026 | 0.2295 | 0.130 (Opta pre) | 10.0pp | 0.187 (Opta post) | 4.25pp | NO |
| Russell F1 2026 | 0.2400 | 0.333 (Neil Paine) | 9.3pp | 0.280 (FB model) | 4.0pp | NO |

---

## 3. El Error: Comparación Asimétrica de Timestamps

### Qué pasó

1. **FASE_2**: Identificamos los 3 mercados con mayor signal_strength del snapshot de Supabase (1,558 mercados).

2. **FASE_3 (primera versión)**: Busqué estimaciones independientes. Encontré el artículo de Opta Supercomputer en TheAnalyst.com con probabilidades pre-tournament (publicado Jun 1). Usé esos valores como P_estimada:
   - Argentina: 10.4%, France: 13.0%
   - Diff Argentina: |20.85 - 10.4| = 10.45pp → CRUZA el umbral

3. **El problema**: Opta pre-tournament (Jun 1) no incluía resultados de la fase de grupos (Jun 11-25). Argentina y France ganaron todos sus partidos, lo que elevó significativamente sus probabilidades reales. Pero P_market (Polymarket, Jun 28) SÍ reflejaba esos resultados.

4. **La corrección**: InternLM/DeepSeek auditó el pipeline y detectó que había ajustado manualmente las estimaciones de Opta hacia arriba (Argentina 10.4%→15.4%) sin documentar el impacto en los diffs, reduciéndolos por debajo del umbral. Más importante aún, Qwen señaló una posible discrepancia (8.7% vs 10.4%).

5. **La resolución definitiva**: Encontré el artículo ACTUALIZADO de Opta post-group-stage (publicado Jun 28, mismo día):
   - Argentina: 10.4% → **16.3%** (+5.9pp)
   - France: 13.0% → **18.7%** (+5.7pp)
   - Con estos valores, los diffs se reducen a 4.55pp y 4.25pp — **muy por debajo del umbral de 10pp**.

### Causa raíz

**Falta de pre-registro de la regla de actualización de fuente independiente.** No se especificó de antemano:
- Qué fuente se usaría como estimación independiente
- Qué versión/timestamp de esa fuente se consideraría válida
- Qué regla aplicar si la fuente publica nuevos datos

Sin esta pre-especificación, era tentador usar la versión que producía el diff más grande (pre-tournament) en lugar de la versión más precisa (post-group-stage).

---

## 4. Discrepancia Qwen (8.7% vs 10.4%)

Qwen reportó que TheAnalyst.com mostraba 8.7% para Argentina. Investigación:

- **Resultado**: El 8.7% NO aparece en ningún artículo de TheAnalyst leído con page_reader.
- **Artículo pre-tournament** (Jun 1): claramente dice "Argentina (10.4%)" — verificado dos veces.
- **Artículo post-group-stage** (Jun 28): dice "second favourites at 16.3%" — verificado una vez.
- **Posibles explicaciones del 8.7%**: (a) gráfico interactivo no capturado en texto estático, (b) versión intermedia del artículo que ya fue actualizada, (c) lectura errónea de otra fuente.

---

## 5. Fuentes Verificadas

| Fuente | URL | Publicado | Argentina | France |
|--------|-----|-----------|-----------|--------|
| Opta pre-tournament | https://theanalyst.com/articles/who-will-win-2026-fifa-world-cup-predictions-opta-supercomputer | 2026-06-01 | 10.4% | 13.0% |
| Opta post-group-stage | https://theanalyst.com/articles/world-cup-2026-knockout-stage-predictions-opta-supercomputer | 2026-06-28 | 16.3% | 18.7% |
| MatchCorner | Facebook post | 2026-06-24 | 15.46% | 15.06% |
| Bookmakers | Oddschecker/FanDuel/Covers | 2026-06-28 | ~20% | ~21% |
| Polymarket (snapshot) | Supabase polymarket_markets | 2026-06-28 | 20.85% | 22.95% |

---

## 6. Lecciones Aprendidas

### 6.1 Pre-registro obligatorio de fuente

Antes de cualquier análisis de edge, se debe pre-registrar explícitamente:
1. **Qué fuente** se usará como estimación independiente
2. **Qué versión/timestamp** de esa fuente se considerará válida
3. **Regla de actualización** si la fuente publica nuevos datos
4. Sin pre-registro, el análisis no es válido

### 6.2 Cuidado con la asimetría temporal

P_market se actualiza en tiempo real. P_estimada puede tener un timestamp diferente. Comparar un precio live contra un modelo stale es metodológicamente inválido — el modelo stale no incorpora información que el mercado sí tiene.

### 6.3 No ajustar manualmente sin documentar

El error de ajustar Opta 10.4%→15.4% sin documentar el impacto en la señal fue una violación de transparencia. Si se ajusta, debe hacerse explícitamente y mostrarse el impacto en la decisión.

### 6.4 Bookmakers NO son independientes

Las odds de DraftKings, FanDuel, etc. están altamente correlacionadas con Polymarket. No pueden usarse como "estimación independiente" — son el mismo mercado visto desde otra plataforma.

### 6.5 El mercado de Polymarket es más eficiente de lo esperado

Para deportes de alto perfil (FIFA World Cup, F1), el mercado de Polymarket se alinea estrechamente con modelos cuantitativos actualizados (Opta). El edge, si existe, probablemente está en mercados más pequeños o con mayor sesgo emocional.

---

## 7. Decisión

**NO-GO** para los 3 mercados deportivos. Pivotar a mercados políticos binarios donde el sesgo partidista documentado puede ofrecer diffs más grandes y estables.

---

## 8. Consenso del Council

| Consejero | Veredicto | Comentario |
|-----------|-----------|------------|
| InternLM | NO-GO | Diffs correctos, metodología válida |
| Sakana | NO-GO | Metodología frágil por falta de pre-registro |
| GPT | NO-GO + PIVOT | Ir a mercados políticos binarios, mantener 10pp |
| Qwen | NO-GO | Fuente verificada, valores correctos |
