# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-07-03T14:00:49.005803+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 1526 |
| Directional (LONG/SHORT) | 79 |
| FLAT | 1447 |
| Verified (outcome known) | 78 |
| Verified Directional | 78 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.4545 | 0.4706 | — |
| Recall | 0.5263 | 0.4000 | — |
| F1 | 0.4878 | 0.4324 | — |
| **Accuracy** | — | — | **0.4615** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 20 | 24 |
| **Predicted SHORT** | 18 | 16 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.270300 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.141479 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 25 | 0.5799 | 0.4800 | 0.0999 ✅ |
| [0.60, 0.70) | 52 | 0.6118 | 0.4615 | 0.1502 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 25 | 0.00071497 | 0.09103097 | 48.00% |
| 0.60-0.70 | 52 | 0.00056236 | 0.72397679 | 46.15% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 76 | 0.00059614 | 0.52527712 | 46.05% |
| TRENDING | 2 | 0.00291560 | 0.00011890 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 78 | 0.00065562 | 0.51181152 | 46.15% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 10.4754 |
| Mean Return | 0.51181152 |
| Std Return | 9.14580448 |
| N Returns | 78 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 46.15% | 63.3323 | 0.374747 |
| 2 | bidask | 46.15% | 27.1101 | 0.160415 |
| 3 | volume_delta | 51.35% | 0.0700 | 0.000461 |
| 4 | price_momentum | 40.48% | 0.0653 | 0.000339 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 53.85% | 63.3323 | 0.437205 |
| 2 | bidask | 53.85% | 27.1101 | 0.187150 |
| 3 | price_momentum | 59.52% | 0.0653 | 0.000499 |
| 4 | volume_delta | 48.65% | 0.0700 | 0.000437 |
| 5 | funding | 100.00% | 0.0004 | 0.000352 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-26T12:45:33 | ETHUSDT | LONG | 0.6133 | +37.657422 |
| 2 | 2026-06-25T14:45:38 | ETHUSDT | LONG | 0.5771 | +36.936631 |
| 3 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 4 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 5 | 2026-06-26T13:45:36 | ETHUSDT | LONG | 0.6104 | +0.015811 |
| 6 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 7 | 2026-06-26T03:45:35 | ETHUSDT | LONG | 0.6135 | +0.008764 |
| 8 | 2026-06-22T15:45:39 | ETHUSDT | SHORT | 0.6105 | +0.006253 |
| 9 | 2026-06-29T00:00:53 | ETHUSDT | SHORT | 0.6057 | +0.005431 |
| 10 | 2026-06-30T13:45:37 | ETHUSDT | LONG | 0.6155 | +0.005145 |
| 11 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 12 | 2026-06-30T13:00:42 | ETHUSDT | LONG | 0.5977 | +0.004505 |
| 13 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |
| 14 | 2026-06-24T22:00:41 | ETHUSDT | SHORT | 0.6082 | +0.004132 |
| 15 | 2026-06-25T11:15:40 | ETHUSDT | SHORT | 0.5865 | +0.003560 |
| 16 | 2026-07-03T10:00:46 | ETHUSDT | LONG | 0.6166 | +0.003480 |
| 17 | 2026-07-01T01:30:38 | ETHUSDT | LONG | 0.6082 | +0.003210 |
| 18 | 2026-06-29T18:00:38 | ETHUSDT | SHORT | 0.5621 | +0.003084 |
| 19 | 2026-06-23T06:30:38 | ETHUSDT | LONG | 0.6165 | +0.002907 |
| 20 | 2026-07-02T01:30:34 | ETHUSDT | LONG | 0.6167 | +0.002800 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-24T15:30:44 | ETHUSDT | SHORT | 0.6160 | -35.819103 |
| 2 | 2026-07-03T12:15:34 | ETHUSDT | SHORT | 0.5916 | -34.623864 |
| 3 | 2026-06-26T13:30:38 | ETHUSDT | SHORT | 0.5545 | -0.023464 |
| 4 | 2026-06-24T20:00:46 | ETHUSDT | SHORT | 0.6083 | -0.020462 |
| 5 | 2026-06-23T08:00:43 | ETHUSDT | LONG | 0.6159 | -0.019643 |
| 6 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 7 | 2026-06-26T02:30:39 | ETHUSDT | LONG | 0.5992 | -0.009513 |
| 8 | 2026-06-28T22:30:39 | ETHUSDT | LONG | 0.5804 | -0.008611 |
| 9 | 2026-06-26T14:30:37 | ETHUSDT | LONG | 0.5947 | -0.006584 |
| 10 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 11 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 12 | 2026-06-30T14:00:44 | ETHUSDT | SHORT | 0.6001 | -0.004854 |
| 13 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 14 | 2026-06-26T03:00:43 | ETHUSDT | SHORT | 0.6093 | -0.003083 |
| 15 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 16 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 17 | 2026-06-27T22:15:34 | ETHUSDT | SHORT | 0.6166 | -0.002755 |
| 18 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 19 | 2026-06-25T15:01:03 | ETHUSDT | LONG | 0.5962 | -0.002617 |
| 20 | 2026-06-24T13:45:36 | ETHUSDT | LONG | 0.5659 | -0.002606 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
