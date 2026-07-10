# H-014 — CEX-Polymarket Latency Arbitrage

**Estado**: PRE-REGISTRO (sin ejecución, solo medición)
**Hipótesis**: La latencia entre CEX (Binance) y Polymarket permite detectar movimientos de precio antes de que se reflejen en los mercados de predicción.

## Mediciones requeridas ANTES de cualquier claim
- CEX timestamp (Binance trade time)
- Polymarket timestamp (data-api trade time)
- Clock drift (NTP offset)
- Network RTT (ping CEX + Polymarket)
- Book update latency (time between CEX tick and Polymarket book change)
- Signal half-life (cuánto dura el edge antes de cerrarse)
- Net edge after fees

## Regla absoluta
- No aceptar claims de "menos de 100ms" sin medición propia
- Todas las mediciones deben ser reproducibles
