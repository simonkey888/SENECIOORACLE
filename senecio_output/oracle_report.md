# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-17T09:45:47.861233+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 144 |
| Directional (LONG/SHORT) | 13 |
| FLAT | 131 |
| Verified (outcome known) | 13 |
| Verified Directional | 13 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.6250 | 0.4000 | — |
| Recall | 0.6250 | 0.4000 | — |
| F1 | 0.6250 | 0.4000 | — |
| **Accuracy** | — | — | **0.5385** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 5 | 3 |
| **Predicted SHORT** | 3 | 2 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.254364 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.069754 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 2 | 0.5805 | 0.5000 | 0.0805 ✅ |
| [0.60, 0.70) | 11 | 0.6132 | 0.5455 | 0.0678 ✅ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 2 | 0.00071543 | 0.00023033 | 50.00% |
| 0.60-0.70 | 11 | 0.00058166 | -3.27687598 | 54.55% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 13 | 0.00060224 | -2.77270578 | 53.85% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 13 | 0.00060224 | -2.77270578 | 53.85% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -53.9761 |
| Mean Return | -2.77270578 |
| Std Return | 9.61577194 |
| N Returns | 13 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 53.85% | 10.6116 | 0.439533 |
| 2 | bidask | 53.85% | 4.6509 | 0.192642 |
| 3 | volume_delta | 100.00% | 0.0112 | 0.000864 |
| 4 | price_momentum | 40.00% | 0.0109 | 0.000334 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 46.15% | 10.6116 | 0.376743 |
| 2 | bidask | 46.15% | 4.6509 | 0.165122 |
| 3 | price_momentum | 60.00% | 0.0109 | 0.000502 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0112 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 3 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 4 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 5 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 6 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 7 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 8 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 9 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 10 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 11 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 12 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 13 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

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
| 8 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 9 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 10 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 11 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 12 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 13 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
