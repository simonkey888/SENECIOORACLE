# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-16T01:45:41.719811+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 16 |
| Directional (LONG/SHORT) | 3 |
| FLAT | 13 |
| Verified (outcome known) | 3 |
| Verified Directional | 3 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.3333 | 0.0000 | — |
| Recall | 1.0000 | 0.0000 | — |
| F1 | 0.5000 | 0.0000 | — |
| **Accuracy** | — | — | **0.3333** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 1 | 2 |
| **Predicted SHORT** | 0 | 0 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.298422 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.279 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.60, 0.70) | 3 | 0.6123 | 0.3333 | 0.2790 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.60-0.70 | 3 | 0.00105325 | 0.01055413 | 33.33% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 3 | 0.00105325 | 0.01055413 | 33.33% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 3 | 0.00105325 | 0.01055413 | 33.33% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 111.7442 |
| Mean Return | 0.01055413 |
| Std Return | 0.01767988 |
| N Returns | 3 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 33.33% | 2.3354 | 0.259488 |
| 2 | bidask | 33.33% | 1.1233 | 0.124816 |
| 3 | volume_delta | 100.00% | 0.0028 | 0.000946 |
| 4 | funding | 0.00% | 0.0004 | 0.000000 |
| 5 | price_momentum | 0.00% | 0.0030 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 66.67% | 2.3354 | 0.518977 |
| 2 | bidask | 66.67% | 1.1233 | 0.249633 |
| 3 | price_momentum | 100.00% | 0.0030 | 0.000992 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0028 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 3 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 2 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 3 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
