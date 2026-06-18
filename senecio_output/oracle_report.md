# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-18T21:00:53.636910+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 116 |
| Directional (LONG/SHORT) | 9 |
| FLAT | 107 |
| Verified (outcome known) | 9 |
| Verified Directional | 9 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.2857 | 0.5000 | — |
| Recall | 0.6667 | 0.1667 | — |
| F1 | 0.4000 | 0.2500 | — |
| **Accuracy** | — | — | **0.3333** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 2 | 5 |
| **Predicted SHORT** | 1 | 1 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.293587 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.275544 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 1 | 0.5751 | 0.0000 | 0.5751 ⚠️ |
| [0.60, 0.70) | 8 | 0.6131 | 0.3750 | 0.2381 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 1 | 0.00072260 | -0.00289217 | 0.00% |
| 0.60-0.70 | 8 | 0.00083520 | 4.47612187 | 37.50% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 9 | 0.00082269 | 3.97845364 | 33.33% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 9 | 0.00082269 | 3.97845364 | 33.33% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 66.2250 |
| Mean Return | 3.97845364 |
| Std Return | 11.24538656 |
| N Returns | 9 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 33.33% | 8.0313 | 0.297454 |
| 2 | bidask | 33.33% | 3.5018 | 0.129695 |
| 3 | volume_delta | 66.67% | 0.0080 | 0.000592 |
| 4 | price_momentum | 16.67% | 0.0077 | 0.000143 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 66.67% | 8.0313 | 0.594908 |
| 2 | bidask | 66.67% | 3.5018 | 0.259389 |
| 3 | price_momentum | 83.33% | 0.0077 | 0.000717 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 33.33% | 0.0080 | 0.000296 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 3 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 4 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 5 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 6 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 7 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 8 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 9 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 2 | 2026-06-18T20:00:45 | ETHUSDT | SHORT | 0.5751 | -0.002892 |
| 3 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 4 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 5 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 6 | 2026-06-18T16:00:52 | ETHUSDT | LONG | 0.6144 | +0.000000 |
| 7 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 8 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 9 | 2026-06-18T15:45:42 | ETHUSDT | LONG | 0.6165 | +35.785189 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
