# H-011 V3 Dashboard Specification

## Funnel principal (de arriba a abajo)
1. Mercados descubiertos
2. Estructura validada (market_structure_verified_v2)
3. Trades vinculados (trade_token_binding_verified_v1)
4. Desviación VWAP (señal)
5. Libros L2 disponibles (both orderbooks respond)
6. Fillable en ambas piernas (equal shares)
7. Edge neto después de fees (net_edge_usdc > 0)

## Tarjetas de estado
- Market identity verified: ✓/✗
- Token pair verified: ✓/✗
- Trade token binding verified: ✓/✗
- L2 executable: ✓/✗
- Net-positive after fees: ✓/✗
- Legacy excluded: count

## Advertencias obligatorias
- "Historical VWAP ≠ executable price"
- "Two-leg CLOB execution is not atomic"
- "Legacy W=3600 excluded from W=300 cohort"
- "Condition-only validation is incomplete"

## Métricas
- "Señal teórica acumulada" (reemplaza "Balance teórico" como principal)
- "Shadow L2" (balance solo para l2_executable_snapshot_v1)

## Panel de detalle por mercado
- condition_id
- labels oficiales (leg_0, leg_1)
- token_id por leg
- metadata_hash
- raw payload hash
- best ask por leg
- depth por leg
- fee rate
- gross edge
- net edge
- snapshot age

## Reglas
- Legacy rows NOT counted as executable
- Balance uses ONLY l2_verified rows
- Dashboard NEVER labels VWAP as realized PnL
