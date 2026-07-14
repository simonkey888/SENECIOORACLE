# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-07-14T13:15:42.134626+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 2576 |
| Directional (LONG/SHORT) | 121 |
| FLAT | 2455 |
| Verified (outcome known) | 120 |
| Verified Directional | 120 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.5077 | 0.4364 | — |
| Recall | 0.5156 | 0.4286 | — |
| F1 | 0.5116 | 0.4324 | — |
| **Accuracy** | — | — | **0.4750** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 33 | 32 |
| **Predicted SHORT** | 31 | 24 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.265298 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.128107 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 40 | 0.5803 | 0.4750 | 0.1053 ⚠️ |
| [0.60, 0.70) | 78 | 0.6118 | 0.4744 | 0.1374 ⚠️ |
| [0.70, 0.80) | 2 | 0.7218 | 0.5000 | 0.2218 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 40 | 0.00062676 | 0.05695653 | 47.50% |
| 0.60-0.70 | 78 | 0.00051586 | 1.37323190 | 47.44% |
| 0.70-0.80 | 2 | 0.00359260 | 0.01037443 | 50.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 117 | 0.00054271 | 0.93494737 | 47.01% |
| TRENDING | 3 | 0.00299846 | 0.00741837 | 66.67% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 120 | 0.00060411 | 0.91175915 | 47.50% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 19.8643 |
| Mean Return | 0.91175915 |
| Std Return | 8.59187995 |
| N Returns | 120 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 47.50% | 96.1088 | 0.380431 |
| 2 | bidask | 47.50% | 41.1606 | 0.162928 |
| 3 | volume_delta | 51.72% | 0.1014 | 0.000437 |
| 4 | price_momentum | 43.75% | 0.0956 | 0.000349 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 52.50% | 96.1088 | 0.420476 |
| 2 | bidask | 52.50% | 41.1606 | 0.180078 |
| 3 | price_momentum | 56.25% | 0.0956 | 0.000448 |
| 4 | volume_delta | 48.28% | 0.1014 | 0.000408 |
| 5 | funding | 100.00% | 0.0004 | 0.000352 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-26T12:45:33 | ETHUSDT | LONG | 0.6133 | +37.657422 |
| 2 | 2026-06-25T14:45:38 | ETHUSDT | LONG | 0.5771 | +36.936631 |
| 3 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 4 | 2026-07-12T00:30:47 | ETHUSDT | LONG | 0.6100 | +34.769558 |
| 5 | 2026-07-03T14:15:31 | ETHUSDT | LONG | 0.6153 | +34.705644 |
| 6 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 7 | 2026-07-14T12:30:50 | ETHUSDT | LONG | 0.7161 | +0.022017 |
| 8 | 2026-06-26T13:45:36 | ETHUSDT | LONG | 0.6104 | +0.015811 |
| 9 | 2026-07-05T22:30:55 | ETHUSDT | SHORT | 0.6056 | +0.009408 |
| 10 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 11 | 2026-06-26T03:45:35 | ETHUSDT | LONG | 0.6135 | +0.008764 |
| 12 | 2026-07-03T14:00:43 | ETHUSDT | SHORT | 0.6027 | +0.006257 |
| 13 | 2026-06-22T15:45:39 | ETHUSDT | SHORT | 0.6105 | +0.006253 |
| 14 | 2026-07-04T17:30:43 | ETHUSDT | LONG | 0.5649 | +0.005849 |
| 15 | 2026-06-29T00:00:53 | ETHUSDT | SHORT | 0.6057 | +0.005431 |
| 16 | 2026-06-30T13:45:37 | ETHUSDT | LONG | 0.6155 | +0.005145 |
| 17 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 18 | 2026-07-04T15:15:32 | ETHUSDT | LONG | 0.6153 | +0.004531 |
| 19 | 2026-06-30T13:00:42 | ETHUSDT | LONG | 0.5977 | +0.004505 |
| 20 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |

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
| 10 | 2026-07-07T21:00:57 | ETHUSDT | LONG | 0.6095 | -0.006490 |
| 11 | 2026-06-23T13:30:41 | ETHUSDT | SHORT | 0.6091 | -0.005548 |
| 12 | 2026-06-22T00:00:40 | ETHUSDT | SHORT | 0.6013 | -0.005424 |
| 13 | 2026-07-13T01:15:34 | ETHUSDT | LONG | 0.6055 | -0.005012 |
| 14 | 2026-06-30T14:00:44 | ETHUSDT | SHORT | 0.6001 | -0.004854 |
| 15 | 2026-07-07T13:45:33 | ETHUSDT | LONG | 0.6104 | -0.004670 |
| 16 | 2026-07-09T06:20:39 | ETHUSDT | SHORT | 0.6166 | -0.004414 |
| 17 | 2026-07-06T14:01:00 | ETHUSDT | SHORT | 0.5666 | -0.004123 |
| 18 | 2026-07-13T00:15:37 | ETHUSDT | LONG | 0.6024 | -0.003833 |
| 19 | 2026-07-08T16:01:03 | ETHUSDT | SHORT | 0.6134 | -0.003525 |
| 20 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
