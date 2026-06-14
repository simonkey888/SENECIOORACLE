# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-14T22:01:58.389943+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 3 |
| Directional (LONG/SHORT) | 2 |
| FLAT | 1 |
| Verified (outcome known) | 1 |
| Verified Directional | 1 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 1.0000 | 0.0000 | — |
| Recall | 1.0000 | 0.0000 | — |
| F1 | 1.0000 | 0.0000 | — |
| **Accuracy** | — | — | **1.0000** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 1 | 0 |
| **Predicted SHORT** | 0 | 0 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.148379 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.3852 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.60, 0.70) | 1 | 0.6148 | 1.0000 | 0.3852 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.60-0.70 | 1 | 0.00022908 | 0.03554676 | 100.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 1 | 0.00022908 | 0.03554676 | 100.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 1 | 0.00022908 | 0.03554676 | 100.00% |

## Theoretical Sharpe Ratio

*Insufficient data for Sharpe calculation*

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 100.00% | 0.8372 | 0.837230 |
| 2 | bidask | 100.00% | 0.4603 | 0.460319 |
| 3 | volume_delta | 100.00% | 0.0000 | 0.000028 |
| 4 | funding | 0.00% | 0.0004 | 0.000000 |
| 5 | price_momentum | 0.00% | 0.0001 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | funding | 100.00% | 0.0004 | 0.000352 |
| 2 | price_momentum | 100.00% | 0.0001 | 0.000051 |
| 3 | orderflow | 0.00% | 0.8372 | 0.000000 |
| 4 | volume_delta | 0.00% | 0.0000 | 0.000000 |
| 5 | bidask | 0.00% | 0.4603 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
