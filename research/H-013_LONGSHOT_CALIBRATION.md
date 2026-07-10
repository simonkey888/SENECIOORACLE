# H-013 — Longshot Calibration

**Estado**: PRE-REGISTRO (sin ejecución)
**Hipótesis**: ¿Existen buckets de contratos de 1-3¢ cuya frecuencia posterior, después de shrinkage e intervalo creíble, supere precio + fees?

## Modelo estadístico
- Beta-Binomial con prior uniforme (alpha=1, beta=1)
- Credible interval al 95%
- Shrinkage: posterior mean hacia prior

## Criterios de NO operar
- n insuficiente (< 30 trials por bucket)
- Intervalo demasiado ancho (width > 0.15)
- Lower credible bound <= market price + fees
- OOS Brier score no mejora al mercado
- Log-loss empeora

## Pre-registro inmutable
- No se opera con capital real hasta cumplir todos los criterios
- Beta-Binomial parameters locked: alpha=1, beta=1, level=0.95
