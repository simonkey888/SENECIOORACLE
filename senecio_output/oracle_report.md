# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-18T14:30:49.782885+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 90 |
| Directional (LONG/SHORT) | 4 |
| FLAT | 86 |
| Verified (outcome known) | 4 |
| Verified Directional | 4 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.2500 | 0.0000 | — |
| Recall | 1.0000 | 0.0000 | — |
| F1 | 0.4000 | 0.0000 | — |
| **Accuracy** | — | — | **0.2500** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 1 | 3 |
| **Predicted SHORT** | 0 | 0 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.318804 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.3634 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.60, 0.70) | 4 | 0.6134 | 0.2500 | 0.3634 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.60-0.70 | 4 | 0.00090202 | 0.00722985 | 25.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 4 | 0.00090202 | 0.00722985 | 25.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 4 | 0.00090202 | 0.00722985 | 25.00% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | 82.7331 |
| Mean Return | 0.00722985 |
| Std Return | 0.01635806 |
| N Returns | 4 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 25.00% | 3.5173 | 0.219829 |
| 2 | bidask | 25.00% | 1.6292 | 0.101822 |
| 3 | volume_delta | 100.00% | 0.0039 | 0.000967 |
| 4 | funding | 0.00% | 0.0004 | 0.000000 |
| 5 | price_momentum | 0.00% | 0.0040 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 75.00% | 3.5173 | 0.659487 |
| 2 | bidask | 75.00% | 1.6292 | 0.305467 |
| 3 | price_momentum | 100.00% | 0.0040 | 0.000991 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0039 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 3 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 4 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-18T01:30:36 | ETHUSDT | LONG | 0.6164 | -0.002743 |
| 2 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 3 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 4 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
