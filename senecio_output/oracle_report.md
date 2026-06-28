# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-28T07:00:42.493615+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 1020 |
| Directional (LONG/SHORT) | 58 |
| FLAT | 962 |
| Verified (outcome known) | 58 |
| Verified Directional | 58 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.4062 | 0.4615 | — |
| Recall | 0.4815 | 0.3871 | — |
| F1 | 0.4407 | 0.4211 | — |
| **Accuracy** | — | — | **0.4310** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 13 | 19 |
| **Predicted SHORT** | 14 | 12 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.277769 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.174647 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 16 | 0.5813 | 0.4375 | 0.1438 ⚠️ |
| [0.60, 0.70) | 41 | 0.6122 | 0.4390 | 0.1732 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 16 | 0.00076048 | 2.30593827 | 43.75% |
| 0.60-0.70 | 41 | 0.00058628 | 0.91788491 | 43.90% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 56 | 0.00061420 | 1.33083549 | 42.86% |
| TRENDING | 2 | 0.00291560 | 0.00011890 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 58 | 0.00069356 | 1.28494871 | 43.10% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 25.2809 |
| Mean Return | 1.28494871 |
| Std Return | 9.51425815 |
| N Returns | 58 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 43.10% | 48.6545 | 0.361582 |
| 2 | bidask | 43.10% | 20.6137 | 0.153193 |
| 3 | volume_delta | 50.00% | 0.0545 | 0.000470 |
| 4 | price_momentum | 33.33% | 0.0489 | 0.000281 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 56.90% | 48.6545 | 0.477288 |
| 2 | bidask | 56.90% | 20.6137 | 0.202215 |
| 3 | price_momentum | 66.67% | 0.0489 | 0.000562 |
| 4 | volume_delta | 50.00% | 0.0545 | 0.000470 |
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
| 9 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 10 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |
| 11 | 2026-06-24T22:00:41 | ETHUSDT | SHORT | 0.6082 | +0.004132 |
| 12 | 2026-06-25T11:15:40 | ETHUSDT | SHORT | 0.5865 | +0.003560 |
| 13 | 2026-06-23T06:30:38 | ETHUSDT | LONG | 0.6165 | +0.002907 |
| 14 | 2026-06-25T13:00:46 | ETHUSDT | SHORT | 0.5782 | +0.002539 |
| 15 | 2026-06-22T11:45:40 | ETHUSDT | LONG | 0.6110 | +0.002462 |
| 16 | 2026-06-21T22:30:39 | ETHUSDT | LONG | 0.5749 | +0.002303 |
| 17 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |
| 18 | 2026-06-25T17:15:37 | ETHUSDT | SHORT | 0.5546 | +0.001874 |
| 19 | 2026-06-26T04:00:40 | ETHUSDT | SHORT | 0.6133 | +0.001691 |
| 20 | 2026-06-26T20:00:40 | ETHUSDT | SHORT | 0.5966 | +0.001506 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-24T15:30:44 | ETHUSDT | SHORT | 0.6160 | -35.819103 |
| 2 | 2026-06-26T13:30:38 | ETHUSDT | SHORT | 0.5545 | -0.023464 |
| 3 | 2026-06-24T20:00:46 | ETHUSDT | SHORT | 0.6083 | -0.020462 |
| 4 | 2026-06-23T08:00:43 | ETHUSDT | LONG | 0.6159 | -0.019643 |
| 5 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 6 | 2026-06-26T02:30:39 | ETHUSDT | LONG | 0.5992 | -0.009513 |
| 7 | 2026-06-26T14:30:37 | ETHUSDT | LONG | 0.5947 | -0.006584 |
| 8 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 9 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 10 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 11 | 2026-06-26T03:00:43 | ETHUSDT | SHORT | 0.6093 | -0.003083 |
| 12 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 13 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 14 | 2026-06-27T22:15:34 | ETHUSDT | SHORT | 0.6166 | -0.002755 |
| 15 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 16 | 2026-06-25T15:01:03 | ETHUSDT | LONG | 0.5962 | -0.002617 |
| 17 | 2026-06-24T13:45:36 | ETHUSDT | LONG | 0.5659 | -0.002606 |
| 18 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 19 | 2026-06-25T18:30:38 | ETHUSDT | LONG | 0.6152 | -0.002521 |
| 20 | 2026-06-24T13:30:41 | ETHUSDT | LONG | 0.5980 | -0.002370 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
