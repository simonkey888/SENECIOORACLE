# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-17T14:03:46.608085+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 161 |
| Directional (LONG/SHORT) | 15 |
| FLAT | 146 |
| Verified (outcome known) | 15 |
| Verified Directional | 15 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.6667 | 0.5000 | — |
| Recall | 0.6667 | 0.5000 | — |
| F1 | 0.6667 | 0.5000 | — |
| **Accuracy** | — | — | **0.6000** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 6 | 3 |
| **Predicted SHORT** | 3 | 3 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.244955 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.096147 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 4 | 0.5759 | 0.7500 | 0.1741 ⚠️ |
| [0.60, 0.70) | 11 | 0.6132 | 0.5455 | 0.0678 ✅ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 4 | 0.00060274 | 0.00313917 | 75.00% |
| 0.60-0.70 | 11 | 0.00058166 | -3.27687598 | 54.55% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 15 | 0.00058728 | -2.40220527 | 60.00% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 15 | 0.00058728 | -2.40220527 | 60.00% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -49.9548 |
| Mean Return | -2.40220527 |
| Std Return | 9.00149542 |
| N Returns | 15 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 60.00% | 11.5318 | 0.461271 |
| 2 | bidask | 60.00% | 5.0386 | 0.201542 |
| 3 | volume_delta | 100.00% | 0.0121 | 0.000808 |
| 4 | price_momentum | 40.00% | 0.0117 | 0.000312 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 40.00% | 11.5318 | 0.307514 |
| 2 | bidask | 40.00% | 5.0386 | 0.134361 |
| 3 | price_momentum | 60.00% | 0.0117 | 0.000468 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0121 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-17T12:30:47 | ETHUSDT | LONG | 0.5754 | +0.006935 |
| 3 | 2026-06-17T13:45:38 | ETHUSDT | SHORT | 0.5672 | +0.005161 |
| 4 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 5 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 6 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 7 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 8 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 9 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 10 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 11 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 12 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 13 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 14 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 15 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

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
| 13 | 2026-06-17T13:45:38 | ETHUSDT | SHORT | 0.5672 | +0.005161 |
| 14 | 2026-06-17T12:30:47 | ETHUSDT | LONG | 0.5754 | +0.006935 |
| 15 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
