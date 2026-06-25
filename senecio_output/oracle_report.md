# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-25T14:00:51.016997+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 760 |
| Directional (LONG/SHORT) | 36 |
| FLAT | 724 |
| Verified (outcome known) | 36 |
| Verified Directional | 36 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3636 | 0.4286 | — |
| Recall | 0.5000 | 0.3000 | — |
| F1 | 0.4211 | 0.3529 | — |
| **Accuracy** | — | — | **0.3889** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 8 | 14 |
| **Predicted SHORT** | 8 | 6 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.289370 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.219811 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 8 | 0.5818 | 0.5000 | 0.0818 ✅ |
| [0.60, 0.70) | 27 | 0.6123 | 0.3704 | 0.2419 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 8 | 0.00057259 | -0.00033451 | 50.00% |
| 0.60-0.70 | 27 | 0.00061928 | -0.00163439 | 37.04% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 35 | 0.00060860 | -0.00133727 | 40.00% |
| TRENDING | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 36 | 0.00070339 | -0.00133536 | 38.89% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -0.0296 |
| Mean Return | -0.00133536 |
| Std Return | 8.43865189 |
| N Returns | 36 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 38.89% | 31.9888 | 0.345558 |
| 2 | bidask | 38.89% | 13.6858 | 0.147840 |
| 3 | volume_delta | 50.00% | 0.0353 | 0.000491 |
| 4 | price_momentum | 26.32% | 0.0306 | 0.000223 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 61.11% | 31.9888 | 0.543020 |
| 2 | bidask | 61.11% | 13.6858 | 0.232321 |
| 3 | price_momentum | 73.68% | 0.0306 | 0.000626 |
| 4 | volume_delta | 50.00% | 0.0353 | 0.000491 |
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
| 7 | 2026-06-24T22:00:41 | ETHUSDT | SHORT | 0.6082 | +0.004132 |
| 8 | 2026-06-25T11:15:40 | ETHUSDT | SHORT | 0.5865 | +0.003560 |
| 9 | 2026-06-23T06:30:38 | ETHUSDT | LONG | 0.6165 | +0.002907 |
| 10 | 2026-06-25T13:00:46 | ETHUSDT | SHORT | 0.5782 | +0.002539 |
| 11 | 2026-06-22T11:45:40 | ETHUSDT | LONG | 0.6110 | +0.002462 |
| 12 | 2026-06-21T22:30:39 | ETHUSDT | LONG | 0.5749 | +0.002303 |
| 13 | 2026-06-20T16:00:48 | ETHUSDT | SHORT | 0.6164 | +0.002216 |
| 14 | 2026-06-20T00:00:41 | ETHUSDT | LONG | 0.5898 | +0.000070 |
| 15 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 16 | 2026-06-24T12:00:44 | ETHUSDT | SHORT | 0.6167 | -0.000197 |
| 17 | 2026-06-22T16:00:56 | ETHUSDT | LONG | 0.6006 | -0.000419 |
| 18 | 2026-06-21T23:00:43 | ETHUSDT | LONG | 0.6030 | -0.000531 |
| 19 | 2026-06-23T20:00:54 | ETHUSDT | LONG | 0.6167 | -0.001021 |
| 20 | 2026-06-25T12:30:50 | ETHUSDT | LONG | 0.7275 | -0.001268 |

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
| 17 | 2026-06-25T12:30:50 | ETHUSDT | LONG | 0.7275 | -0.001268 |
| 18 | 2026-06-23T20:00:54 | ETHUSDT | LONG | 0.6167 | -0.001021 |
| 19 | 2026-06-21T23:00:43 | ETHUSDT | LONG | 0.6030 | -0.000531 |
| 20 | 2026-06-22T16:00:56 | ETHUSDT | LONG | 0.6006 | -0.000419 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
