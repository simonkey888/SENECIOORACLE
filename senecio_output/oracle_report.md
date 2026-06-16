# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-16T16:01:04.463308+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 73 |
| Directional (LONG/SHORT) | 9 |
| FLAT | 64 |
| Verified (outcome known) | 9 |
| Verified Directional | 9 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.5000 | 0.6667 | — |
| Recall | 0.7500 | 0.4000 | — |
| F1 | 0.6000 | 0.5000 | — |
| **Accuracy** | — | — | **0.5556** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 3 | 3 |
| **Predicted SHORT** | 1 | 2 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.253672 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.148044 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 1 | 0.5764 | 1.0000 | 0.4236 ⚠️ |
| [0.60, 0.70) | 8 | 0.6136 | 0.5000 | 0.1136 ⚠️ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 1 | 0.00095314 | 0.00168761 | 100.00% |
| 0.60-0.70 | 8 | 0.00068778 | -4.50590547 | 50.00% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 9 | 0.00071727 | -4.00506179 | 55.56% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 9 | 0.00071727 | -4.00506179 | 55.56% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -66.1049 |
| Mean Return | -4.00506179 |
| Std Return | 11.34116342 |
| N Returns | 9 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 55.56% | 7.6442 | 0.471867 |
| 2 | bidask | 55.56% | 3.3348 | 0.205852 |
| 3 | volume_delta | 100.00% | 0.0087 | 0.000965 |
| 4 | price_momentum | 33.33% | 0.0083 | 0.000309 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 44.44% | 7.6442 | 0.377493 |
| 2 | bidask | 44.44% | 3.3348 | 0.164681 |
| 3 | price_momentum | 66.67% | 0.0083 | 0.000618 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0087 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 3 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 4 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 5 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 6 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 7 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 8 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 9 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |
| 2 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 3 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 4 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 5 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 6 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 7 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 8 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 9 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
