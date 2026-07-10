# H-015 — Maker Ladder Strategy

**Estado**: PRE-REGISTRO (sin ejecución)
**Hipótesis**: Colocar órdenes maker en múltiples niveles del orderbook puede capturar spread con menor adverse selection que taker puro.

## Variables a medir
- Queue position (tiempo hasta fill)
- Fill probability por nivel
- Cancel latency
- Adverse selection (precio post-fill vs pre-fill)
- Maker rebate (si existe)
- Inventory imbalance
- Merge costs (combinar posiciones)
- Capital locked

## Restricciones
- Shadow maker solamente (no órdenes reales)
- Medir fill probability antes de claim de rentabilidad
