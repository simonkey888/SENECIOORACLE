# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-18T15:45:47.980718+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 95 |
| Directional (LONG/SHORT) | 7 |
| FLAT | 88 |
| Verified (outcome known) | 6 |
| Verified Directional | 6 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.2000 | 1.0000 | — |
| Recall | 1.0000 | 0.2000 | — |
| F1 | 0.3333 | 0.3333 | — |
| **Accuracy** | — | — | **0.3333** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 1 | 4 |
| **Predicted SHORT** | 0 | 1 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.297830 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.279 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.60, 0.70) | 6 | 0.6123 | 0.3333 | 0.2790 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.60-0.70 | 6 | 0.00074280 | 0.00396437 | 33.33% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 6 | 0.00074280 | 0.00396437 | 33.33% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 6 | 0.00074280 | 0.00396437 | 33.33% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 47.3636 |
| Mean Return | 0.00396437 |
| Std Return | 0.01566792 |
| N Returns | 6 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 33.33% | 5.4489 | 0.302716 |
| 2 | bidask | 33.33% | 2.4189 | 0.134386 |
| 3 | volume_delta | 100.00% | 0.0056 | 0.000936 |
| 4 | price_momentum | 20.00% | 0.0055 | 0.000184 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 66.67% | 5.4489 | 0.605431 |
| 2 | bidask | 66.67% | 2.4189 | 0.268772 |
| 3 | price_momentum | 80.00% | 0.0055 | 0.000734 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0056 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 3 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 4 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 5 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 6 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T15:30:41 | ETHUSDT | LONG | 0.6039 | -0.014284 |
| 2 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 3 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 4 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 5 | 2026-06-18T15:00:46 | ETHUSDT | SHORT | 0.6165 | +0.009151 |
| 6 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
