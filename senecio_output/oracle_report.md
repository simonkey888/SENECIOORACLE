# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-07-06T21:15:40.841660+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 1844 |
| Directional (LONG/SHORT) | 94 |
| FLAT | 1750 |
| Verified (outcome known) | 94 |
| Verified Directional | 94 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.4694 | 0.4667 | — |
| Recall | 0.4894 | 0.4468 | — |
| F1 | 0.4792 | 0.4565 | — |
| **Accuracy** | — | — | **0.4681** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 23 | 26 |
| **Predicted SHORT** | 24 | 21 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.268191 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.134512 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 32 | 0.5807 | 0.4688 | 0.1120 ⚠️ |
| [0.60, 0.70) | 61 | 0.6120 | 0.4754 | 0.1366 ⚠️ |
| [0.70, 0.80) | 1 | 0.7275 | 0.0000 | 0.7275 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 32 | 0.00067645 | 0.07116271 | 46.88% |
| 0.60-0.70 | 61 | 0.00054349 | 1.18633138 | 47.54% |
| 0.70-0.80 | 1 | 0.00402102 | -0.00126846 | 0.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 92 | 0.00057597 | 0.81132516 | 46.74% |
| TRENDING | 2 | 0.00291560 | 0.00011890 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 94 | 0.00062575 | 0.79406545 | 46.81% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 16.4338 |
| Mean Return | 0.79406545 |
| Std Return | 9.04481225 |
| N Returns | 94 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 46.81% | 76.6559 | 0.381718 |
| 2 | bidask | 46.81% | 32.8517 | 0.163589 |
| 3 | volume_delta | 51.16% | 0.0810 | 0.000441 |
| 4 | price_momentum | 42.31% | 0.0763 | 0.000343 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 53.19% | 76.6559 | 0.433770 |
| 2 | bidask | 53.19% | 32.8517 | 0.185897 |
| 3 | price_momentum | 57.69% | 0.0763 | 0.000468 |
| 4 | volume_delta | 48.84% | 0.0810 | 0.000421 |
| 5 | funding | 100.00% | 0.0004 | 0.000352 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-26T12:45:33 | ETHUSDT | LONG | 0.6133 | +37.657422 |
| 2 | 2026-06-25T14:45:38 | ETHUSDT | LONG | 0.5771 | +36.936631 |
| 3 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 4 | 2026-07-03T14:15:31 | ETHUSDT | LONG | 0.6153 | +34.705644 |
| 5 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 6 | 2026-06-26T13:45:36 | ETHUSDT | LONG | 0.6104 | +0.015811 |
| 7 | 2026-07-05T22:30:55 | ETHUSDT | SHORT | 0.6056 | +0.009408 |
| 8 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 9 | 2026-06-26T03:45:35 | ETHUSDT | LONG | 0.6135 | +0.008764 |
| 10 | 2026-07-03T14:00:43 | ETHUSDT | SHORT | 0.6027 | +0.006257 |
| 11 | 2026-06-22T15:45:39 | ETHUSDT | SHORT | 0.6105 | +0.006253 |
| 12 | 2026-07-04T17:30:43 | ETHUSDT | LONG | 0.5649 | +0.005849 |
| 13 | 2026-06-29T00:00:53 | ETHUSDT | SHORT | 0.6057 | +0.005431 |
| 14 | 2026-06-30T13:45:37 | ETHUSDT | LONG | 0.6155 | +0.005145 |
| 15 | 2026-06-24T18:15:39 | ETHUSDT | LONG | 0.6166 | +0.004538 |
| 16 | 2026-07-04T15:15:32 | ETHUSDT | LONG | 0.6153 | +0.004531 |
| 17 | 2026-06-30T13:00:42 | ETHUSDT | LONG | 0.5977 | +0.004505 |
| 18 | 2026-06-24T15:45:53 | ETHUSDT | LONG | 0.6156 | +0.004292 |
| 19 | 2026-07-05T23:15:36 | ETHUSDT | SHORT | 0.5998 | +0.004145 |
| 20 | 2026-06-24T22:00:41 | ETHUSDT | SHORT | 0.6082 | +0.004132 |

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
| 13 | 2026-07-06T14:01:00 | ETHUSDT | SHORT | 0.5666 | -0.004123 |
| 14 | 2026-06-22T13:30:41 | ETHUSDT | SHORT | 0.5861 | -0.003280 |
| 15 | 2026-06-26T03:00:43 | ETHUSDT | SHORT | 0.6093 | -0.003083 |
| 16 | 2026-06-24T14:30:42 | ETHUSDT | LONG | 0.6166 | -0.003057 |
| 17 | 2026-07-06T16:01:04 | ETHUSDT | SHORT | 0.5990 | -0.002999 |
| 18 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 19 | 2026-07-04T17:00:49 | ETHUSDT | SHORT | 0.6117 | -0.002876 |
| 20 | 2026-06-27T22:15:34 | ETHUSDT | SHORT | 0.6166 | -0.002755 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
