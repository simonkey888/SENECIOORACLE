# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-14T22:22:04.621098+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 4 |
| Directional (LONG/SHORT) | 3 |
| FLAT | 1 |
| Verified (outcome known) | 2 |
| Verified Directional | 2 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.5000 | 0.0000 | — |
| Recall | 1.0000 | 0.0000 | — |
| F1 | 0.6667 | 0.0000 | — |
| **Accuracy** | — | — | **0.5000** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 1 | 1 |
| **Predicted SHORT** | 0 | 0 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.260545 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.1127 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.60, 0.70) | 2 | 0.6127 | 0.5000 | 0.1127 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.60-0.70 | 2 | 0.00085826 | 0.01711593 | 50.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 2 | 0.00085826 | 0.01711593 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 2 | 0.00085826 | 0.01711593 | 50.00% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 173.8351 |
| Mean Return | 0.01711593 |
| Std Return | 0.01843083 |
| N Returns | 2 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 50.00% | 1.5687 | 0.392180 |
| 2 | bidask | 50.00% | 0.7869 | 0.196725 |
| 3 | volume_delta | 100.00% | 0.0021 | 0.001028 |
| 4 | funding | 0.00% | 0.0004 | 0.000000 |
| 5 | price_momentum | 0.00% | 0.0022 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 50.00% | 1.5687 | 0.392180 |
| 2 | bidask | 50.00% | 0.7869 | 0.196725 |
| 3 | price_momentum | 100.00% | 0.0022 | 0.001093 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0021 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
