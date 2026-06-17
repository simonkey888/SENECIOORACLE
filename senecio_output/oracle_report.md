# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-17T09:00:52.630381+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 141 |
| Directional (LONG/SHORT) | 13 |
| FLAT | 128 |
| Verified (outcome known) | 12 |
| Verified Directional | 12 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.5714 | 0.4000 | — |
| Recall | 0.5714 | 0.4000 | — |
| F1 | 0.5714 | 0.4000 | — |
| **Accuracy** | — | — | **0.5000** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 4 | 3 |
| **Predicted SHORT** | 3 | 2 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.262775 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.108167 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 2 | 0.5805 | 0.5000 | 0.0805 ✅ |
| [0.60, 0.70) | 10 | 0.6137 | 0.5000 | 0.1137 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 2 | 0.00071543 | 0.00023033 | 50.00% |
| 0.60-0.70 | 10 | 0.00061746 | -3.60470104 | 50.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 12 | 0.00063379 | -3.00387914 | 50.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 12 | 0.00063379 | -3.00387914 | 50.00% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -56.3781 |
| Mean Return | -3.00387914 |
| Std Return | 9.97364483 |
| N Returns | 12 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 50.00% | 9.9051 | 0.412714 |
| 2 | bidask | 50.00% | 4.3609 | 0.181706 |
| 3 | volume_delta | 100.00% | 0.0105 | 0.000874 |
| 4 | price_momentum | 33.33% | 0.0102 | 0.000284 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 50.00% | 9.9051 | 0.412714 |
| 2 | bidask | 50.00% | 4.3609 | 0.181706 |
| 3 | price_momentum | 66.67% | 0.0102 | 0.000568 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0105 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 3 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 4 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 5 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 6 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 7 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 8 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 9 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 10 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 11 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 12 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |
| 2 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 3 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 4 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 5 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 6 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 7 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 8 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 9 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 10 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 11 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 12 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
