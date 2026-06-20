# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-20T08:15:41.013120+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 257 |
| Directional (LONG/SHORT) | 12 |
| FLAT | 245 |
| Verified (outcome known) | 12 |
| Verified Directional | 12 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3333 | 0.3333 | — |
| Recall | 0.6000 | 0.1429 | — |
| F1 | 0.4286 | 0.2000 | — |
| **Accuracy** | — | — | **0.3333** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 3 | 6 |
| **Predicted SHORT** | 2 | 1 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.297087 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.274817 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 2 | 0.5824 | 0.5000 | 0.0824 ✅ |
| [0.60, 0.70) | 10 | 0.6133 | 0.3000 | 0.3133 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 2 | 0.00046523 | -0.00141103 | 50.00% |
| 0.60-0.70 | 10 | 0.00077308 | 3.58044749 | 30.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 12 | 0.00072177 | 2.98347107 | 33.33% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 12 | 0.00072177 | 2.98347107 | 33.33% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 56.4681 |
| Mean Return | 2.98347107 |
| Std Return | 9.89009658 |
| N Returns | 12 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 33.33% | 10.4355 | 0.289875 |
| 2 | bidask | 33.33% | 4.5970 | 0.127695 |
| 3 | volume_delta | 66.67% | 0.0096 | 0.000536 |
| 4 | price_momentum | 22.22% | 0.0097 | 0.000179 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 66.67% | 10.4355 | 0.579749 |
| 2 | bidask | 66.67% | 4.5970 | 0.255390 |
| 3 | price_momentum | 77.78% | 0.0097 | 0.000626 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 33.33% | 0.0096 | 0.000268 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 3 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 4 | 2026-06-20T00:00:41 | ETHUSDT | LONG | 0.5898 | +0.000070 |
| 5 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 6 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 7 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |
| 8 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 9 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 10 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 11 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 12 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |

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
| 10 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 11 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 12 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
