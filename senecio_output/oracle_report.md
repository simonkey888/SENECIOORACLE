# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-30T00:30:47.841410+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 1185 |
| Directional (LONG/SHORT) | 63 |
| FLAT | 1122 |
| Verified (outcome known) | 63 |
| Verified Directional | 63 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3824 | 0.5172 | — |
| Recall | 0.4815 | 0.4167 | — |
| F1 | 0.4262 | 0.4615 | — |
| **Accuracy** | — | — | **0.4444** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 13 | 21 |
| **Predicted SHORT** | 14 | 15 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.274622 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.159125 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 20 | 0.5795 | 0.4500 | 0.1295 ⚠️ |
| [0.60, 0.70) | 42 | 0.6120 | 0.4524 | 0.1597 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 20 | 0.00072466 | 1.84460970 | 45.00% |
| 0.60-0.70 | 42 | 0.00059015 | 0.89615983 | 45.24% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 61 | 0.00061425 | 1.22179345 | 44.26% |
| TRENDING | 2 | 0.00291560 | 0.00011890 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 63 | 0.00068731 | 1.18301013 | 44.44% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 24.2403 |
| Mean Return | 1.18301013 |
| Std Return | 9.13550416 |
| N Returns | 63 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 44.44% | 51.1150 | 0.360600 |
| 2 | bidask | 44.44% | 21.7391 | 0.153362 |
| 3 | volume_delta | 51.52% | 0.0582 | 0.000476 |
| 4 | price_momentum | 35.48% | 0.0532 | 0.000300 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 55.56% | 51.1150 | 0.450749 |
| 2 | bidask | 55.56% | 21.7391 | 0.191702 |
| 3 | price_momentum | 64.52% | 0.0532 | 0.000545 |
| 4 | volume_delta | 48.48% | 0.0582 | 0.000448 |
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
| 10 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 11 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |
| 12 | 2026-06-24T22:00:41 | ETHUSDT | SHORT | 0.6082 | +0.004132 |
| 13 | 2026-06-25T11:15:40 | ETHUSDT | SHORT | 0.5865 | +0.003560 |
| 14 | 2026-06-29T18:00:38 | ETHUSDT | SHORT | 0.5621 | +0.003084 |
| 15 | 2026-06-23T06:30:38 | ETHUSDT | LONG | 0.6165 | +0.002907 |
| 16 | 2026-06-28T12:30:38 | ETHUSDT | SHORT | 0.5758 | +0.002733 |
| 17 | 2026-06-25T13:00:46 | ETHUSDT | SHORT | 0.5782 | +0.002539 |
| 18 | 2026-06-22T11:45:40 | ETHUSDT | LONG | 0.6110 | +0.002462 |
| 19 | 2026-06-21T22:30:39 | ETHUSDT | LONG | 0.5749 | +0.002303 |
| 20 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-24T15:30:44 | ETHUSDT | SHORT | 0.6160 | -35.819103 |
| 2 | 2026-06-26T13:30:38 | ETHUSDT | SHORT | 0.5545 | -0.023464 |
| 3 | 2026-06-24T20:00:46 | ETHUSDT | SHORT | 0.6083 | -0.020462 |
| 4 | 2026-06-23T08:00:43 | ETHUSDT | LONG | 0.6159 | -0.019643 |
| 5 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 6 | 2026-06-26T02:30:39 | ETHUSDT | LONG | 0.5992 | -0.009513 |
| 7 | 2026-06-28T22:30:39 | ETHUSDT | LONG | 0.5804 | -0.008611 |
| 8 | 2026-06-26T14:30:37 | ETHUSDT | LONG | 0.5947 | -0.006584 |
| 9 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 10 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 11 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 12 | 2026-06-26T03:00:43 | ETHUSDT | SHORT | 0.6093 | -0.003083 |
| 13 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 14 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 15 | 2026-06-27T22:15:34 | ETHUSDT | SHORT | 0.6166 | -0.002755 |
| 16 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 17 | 2026-06-25T15:01:03 | ETHUSDT | LONG | 0.5962 | -0.002617 |
| 18 | 2026-06-24T13:45:36 | ETHUSDT | LONG | 0.5659 | -0.002606 |
| 19 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 20 | 2026-06-25T18:30:38 | ETHUSDT | LONG | 0.6152 | -0.002521 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
