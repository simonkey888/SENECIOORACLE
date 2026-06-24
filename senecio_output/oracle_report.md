# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-24T22:15:40.425183+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 698 |
| Directional (LONG/SHORT) | 33 |
| FLAT | 665 |
| Verified (outcome known) | 32 |
| Verified Directional | 32 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3810 | 0.2727 | — |
| Recall | 0.5000 | 0.1875 | — |
| F1 | 0.4324 | 0.2222 | — |
| **Accuracy** | — | — | **0.3438** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 8 | 13 |
| **Predicted SHORT** | 8 | 3 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.293302 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.262925 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 6 | 0.5816 | 0.3333 | 0.2483 ⚠️ |
| [0.60, 0.70) | 26 | 0.6125 | 0.3462 | 0.2663 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 6 | 0.00057125 | -0.00146252 | 33.33% |
| 0.60-0.70 | 26 | 0.00059588 | -0.00185617 | 34.62% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 32 | 0.00059126 | -0.00178236 | 34.38% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 32 | 0.00059126 | -0.00178236 | 34.38% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -0.0373 |
| Mean Return | -0.00178236 |
| Std Return | 8.95054183 |
| N Returns | 32 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 34.38% | 29.0555 | 0.312119 |
| 2 | bidask | 34.38% | 12.5211 | 0.134504 |
| 3 | volume_delta | 42.86% | 0.0254 | 0.000340 |
| 4 | price_momentum | 27.78% | 0.0248 | 0.000215 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 65.62% | 29.0555 | 0.595864 |
| 2 | bidask | 65.62% | 12.5211 | 0.256781 |
| 3 | price_momentum | 72.22% | 0.0248 | 0.000560 |
| 4 | volume_delta | 57.14% | 0.0254 | 0.000453 |
| 5 | funding | 100.00% | 0.0004 | 0.000352 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 3 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 4 | 2026-06-22T15:45:39 | ETHUSDT | SHORT | 0.6105 | +0.006253 |
| 5 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 6 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |
| 7 | 2026-06-23T06:30:38 | ETHUSDT | LONG | 0.6165 | +0.002907 |
| 8 | 2026-06-22T11:45:40 | ETHUSDT | LONG | 0.6110 | +0.002462 |
| 9 | 2026-06-21T22:30:39 | ETHUSDT | LONG | 0.5749 | +0.002303 |
| 10 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |
| 11 | 2026-06-20T00:00:41 | ETHUSDT | LONG | 0.5898 | +0.000070 |
| 12 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 13 | 2026-06-24T12:00:44 | ETHUSDT | SHORT | 0.6167 | -0.000197 |
| 14 | 2026-06-22T16:00:56 | ETHUSDT | LONG | 0.6006 | -0.000419 |
| 15 | 2026-06-21T23:00:43 | ETHUSDT | LONG | 0.6030 | -0.000531 |
| 16 | 2026-06-23T20:00:54 | ETHUSDT | LONG | 0.6167 | -0.001021 |
| 17 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 18 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |
| 19 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 20 | 2026-06-24T13:30:41 | ETHUSDT | LONG | 0.5980 | -0.002370 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-24T15:30:44 | ETHUSDT | SHORT | 0.6160 | -35.819103 |
| 2 | 2026-06-24T20:00:46 | ETHUSDT | SHORT | 0.6083 | -0.020462 |
| 3 | 2026-06-23T08:00:43 | ETHUSDT | LONG | 0.6159 | -0.019643 |
| 4 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 5 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 6 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 7 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 8 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 9 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 10 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 11 | 2026-06-24T13:45:36 | ETHUSDT | LONG | 0.5659 | -0.002606 |
| 12 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 13 | 2026-06-24T13:30:41 | ETHUSDT | LONG | 0.5980 | -0.002370 |
| 14 | 2026-06-19T13:45:37 | ETHUSDT | LONG | 0.6163 | -0.002368 |
| 15 | 2026-06-18T21:15:38 | ETHUSDT | SHORT | 0.6121 | -0.002132 |
| 16 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 17 | 2026-06-23T20:00:54 | ETHUSDT | LONG | 0.6167 | -0.001021 |
| 18 | 2026-06-21T23:00:43 | ETHUSDT | LONG | 0.6030 | -0.000531 |
| 19 | 2026-06-22T16:00:56 | ETHUSDT | LONG | 0.6006 | -0.000419 |
| 20 | 2026-06-24T12:00:44 | ETHUSDT | SHORT | 0.6167 | -0.000197 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
