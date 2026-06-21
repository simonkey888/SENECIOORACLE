# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-21T11:15:47.875836+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 365 |
| Directional (LONG/SHORT) | 13 |
| FLAT | 352 |
| Verified (outcome known) | 13 |
| Verified Directional | 13 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3333 | 0.5000 | — |
| Recall | 0.6000 | 0.2500 | — |
| F1 | 0.4286 | 0.3333 | — |
| **Accuracy** | — | — | **0.3846** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 3 | 6 |
| **Predicted SHORT** | 2 | 2 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.285553 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.224215 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 2 | 0.5824 | 0.5000 | 0.0824 ✅ |
| [0.60, 0.70) | 11 | 0.6136 | 0.3636 | 0.2500 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 2 | 0.00046523 | -0.00141103 | 50.00% |
| 0.60-0.70 | 11 | 0.00074227 | 3.25515371 | 36.36% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 13 | 0.00069965 | 2.75414375 | 38.46% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 13 | 0.00069965 | 2.75414375 | 38.46% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 54.0675 |
| Mean Return | 2.75414375 |
| Std Return | 9.53524766 |
| N Returns | 13 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 38.46% | 11.6349 | 0.344227 |
| 2 | bidask | 38.46% | 5.1158 | 0.151356 |
| 3 | volume_delta | 66.67% | 0.0106 | 0.000544 |
| 4 | price_momentum | 30.00% | 0.0106 | 0.000245 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 61.54% | 11.6349 | 0.550763 |
| 2 | bidask | 61.54% | 5.1158 | 0.242170 |
| 3 | price_momentum | 70.00% | 0.0106 | 0.000571 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 33.33% | 0.0106 | 0.000272 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 3 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 4 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |
| 5 | 2026-06-20T00:00:41 | ETHUSDT | LONG | 0.5898 | +0.000070 |
| 6 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 7 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 8 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |
| 9 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 10 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 11 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 12 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 13 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 2 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 3 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 4 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 5 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 6 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |
| 7 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 8 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 9 | 2026-06-20T00:00:41 | ETHUSDT | LONG | 0.5898 | +0.000070 |
| 10 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |
| 11 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 12 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 13 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
