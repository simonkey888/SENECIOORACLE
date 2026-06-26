# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-26T14:00:48.167324+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 856 |
| Directional (LONG/SHORT) | 52 |
| FLAT | 804 |
| Verified (outcome known) | 52 |
| Verified Directional | 52 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.4138 | 0.4783 | — |
| Recall | 0.5000 | 0.3929 | — |
| F1 | 0.4528 | 0.4314 | — |
| **Accuracy** | — | — | **0.4423** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 12 | 17 |
| **Predicted SHORT** | 12 | 11 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.276169 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.163898 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 13 | 0.5797 | 0.4615 | 0.1182 ⚠️ |
| [0.60, 0.70) | 38 | 0.6120 | 0.4474 | 0.1647 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 13 | 0.00071481 | 2.83847963 | 46.15% |
| 0.60-0.70 | 38 | 0.00059142 | 0.99039179 | 44.74% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 51 | 0.00062287 | 1.46147301 | 45.10% |
| TRENDING | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 52 | 0.00068822 | 1.43334336 | 44.23% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 26.7303 |
| Mean Return | 1.43334336 |
| Std Return | 10.03757845 |
| N Returns | 52 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 44.23% | 44.1058 | 0.375160 |
| 2 | bidask | 44.23% | 18.6394 | 0.158545 |
| 3 | volume_delta | 50.00% | 0.0481 | 0.000462 |
| 4 | price_momentum | 36.00% | 0.0418 | 0.000290 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 55.77% | 44.1058 | 0.473028 |
| 2 | bidask | 55.77% | 18.6394 | 0.199905 |
| 3 | price_momentum | 64.00% | 0.0418 | 0.000515 |
| 4 | volume_delta | 50.00% | 0.0481 | 0.000462 |
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
| 20 | 2026-06-26T11:15:33 | ETHUSDT | SHORT | 0.6003 | +0.001355 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-24T15:30:44 | ETHUSDT | SHORT | 0.6160 | -35.819103 |
| 2 | 2026-06-26T13:30:38 | ETHUSDT | SHORT | 0.5545 | -0.023464 |
| 3 | 2026-06-24T20:00:46 | ETHUSDT | SHORT | 0.6083 | -0.020462 |
| 4 | 2026-06-23T08:00:43 | ETHUSDT | LONG | 0.6159 | -0.019643 |
| 5 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 6 | 2026-06-26T02:30:39 | ETHUSDT | LONG | 0.5992 | -0.009513 |
| 7 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 8 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 9 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 10 | 2026-06-26T03:00:43 | ETHUSDT | SHORT | 0.6093 | -0.003083 |
| 11 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 12 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 13 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 14 | 2026-06-25T15:01:03 | ETHUSDT | LONG | 0.5962 | -0.002617 |
| 15 | 2026-06-24T13:45:36 | ETHUSDT | LONG | 0.5659 | -0.002606 |
| 16 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 17 | 2026-06-25T18:30:38 | ETHUSDT | LONG | 0.6152 | -0.002521 |
| 18 | 2026-06-24T13:30:41 | ETHUSDT | LONG | 0.5980 | -0.002370 |
| 19 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 20 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
