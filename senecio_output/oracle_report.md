# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-17T17:00:57.676087+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 173 |
| Directional (LONG/SHORT) | 17 |
| FLAT | 156 |
| Verified (outcome known) | 17 |
| Verified Directional | 17 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.6000 | 0.5714 | — |
| Recall | 0.6667 | 0.5000 | — |
| F1 | 0.6316 | 0.5333 | — |
| **Accuracy** | — | — | **0.5882** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 6 | 4 |
| **Predicted SHORT** | 3 | 4 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.246594 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.073341 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 6 | 0.5832 | 0.6667 | 0.0835 ✅ |
| [0.60, 0.70) | 11 | 0.6132 | 0.5455 | 0.0678 ✅ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 6 | 0.00064233 | 0.00204781 | 66.67% |
| 0.60-0.70 | 11 | 0.00058166 | -3.27687598 | 54.55% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 17 | 0.00060307 | -2.11960876 | 58.82% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 17 | 0.00060307 | -2.11960876 | 58.82% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -46.7294 |
| Mean Return | -2.11960876 |
| Std Return | 8.49077731 |
| N Returns | 17 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 58.82% | 12.7042 | 0.439592 |
| 2 | bidask | 58.82% | 5.5344 | 0.191502 |
| 3 | volume_delta | 100.00% | 0.0145 | 0.000854 |
| 4 | price_momentum | 41.67% | 0.0139 | 0.000342 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 41.18% | 12.7042 | 0.307715 |
| 2 | bidask | 41.18% | 5.5344 | 0.134051 |
| 3 | price_momentum | 58.33% | 0.0139 | 0.000478 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0145 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 2 | 2026-06-17T12:30:47 | ETHUSDT | LONG | 0.5754 | +0.006935 |
| 3 | 2026-06-17T13:45:38 | ETHUSDT | SHORT | 0.5672 | +0.005161 |
| 4 | 2026-06-17T16:30:50 | ETHUSDT | SHORT | 0.5986 | +0.004354 |
| 5 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 6 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 7 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 8 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 9 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 10 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 11 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 12 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 13 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 14 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 15 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 16 | 2026-06-17T14:15:43 | ETHUSDT | LONG | 0.5972 | -0.004624 |
| 17 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

## Top 20 Worst Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |
| 2 | 2026-06-17T14:15:43 | ETHUSDT | LONG | 0.5972 | -0.004624 |
| 3 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 4 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 5 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 6 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 7 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 8 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 9 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 10 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 11 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 12 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 13 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 14 | 2026-06-17T16:30:50 | ETHUSDT | SHORT | 0.5986 | +0.004354 |
| 15 | 2026-06-17T13:45:38 | ETHUSDT | SHORT | 0.5672 | +0.005161 |
| 16 | 2026-06-17T12:30:47 | ETHUSDT | LONG | 0.5754 | +0.006935 |
| 17 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
