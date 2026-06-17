# SENECIO ORACLE_LAB — Statistical Evidence Report

**Generated:** 2026-06-17T20:30:47.691530+00:00
**Source:** predictions.jsonl

## Dataset Overview

| Metric | Value |
|--------|-------|
| Total Predictions | 187 |
| Directional (LONG/SHORT) | 18 |
| FLAT | 169 |
| Verified (outcome known) | 18 |
| Verified Directional | 18 |

## Classification Metrics

| Metric | LONG | SHORT | Overall |
|--------|------|--------|---------|
| Precision | 0.6364 | 0.5714 | — |
| Recall | 0.7000 | 0.5000 | — |
| F1 | 0.6667 | 0.5333 | — |
| **Accuracy** | — | — | **0.6111** |

### Confusion Matrix

| | Market UP | Market DOWN |
|-----------|-----------|-------------|
| **Predicted LONG** | 7 | 4 |
| **Predicted SHORT** | 3 | 4 |

## Probabilistic Calibration

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Brier Score | 0.241232 | 0=perfect, 0.25=random, 1=worst |
| ECE | 0.047767 | 0=perfectly calibrated |

### Calibration Bins

| Confidence Range | Count | Avg Confidence | Actual Accuracy | Gap |
|-----------------|-------|---------------|-----------------|-----|
| [0.50, 0.60) | 6 | 0.5832 | 0.6667 | 0.0835 ✅ |
| [0.60, 0.70) | 12 | 0.6132 | 0.5833 | 0.0299 ✅ |

## Expected Value Analysis

### EV by Confidence Bucket

| Bucket | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| 0.50-0.60 | 6 | 0.00064233 | 0.00204781 | 66.67% |
| 0.60-0.70 | 12 | 0.00058437 | -0.04916097 | 58.33% |

### EV by Market Regime

| Regime | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| RANGING | 18 | 0.00060369 | -0.03209138 | 61.11% |

### EV by Symbol

| Symbol | Count | Model EV | Realized EV | Win Rate |
|--------|-------|----------|-------------|----------|
| ETHUSDT | 18 | 0.00060369 | -0.03209138 | 61.11% |

## Theoretical Sharpe Ratio

| Metric | Value |
|--------|-------|
| Sharpe (annualized) | -0.5038 |
| Mean Return | -0.03209138 |
| Std Return | 11.92348547 |
| N Returns | 18 |
| Cycles/Year | 35040 |

## Signal Rankings

### Most Predictive Signals (agreement → correct outcome)

| Rank | Signal | Agreed Accuracy | Total Influence | Predictive Score |
|------|--------|----------------|-----------------|------------------|
| 1 | orderflow | 61.11% | 13.5138 | 0.458803 |
| 2 | bidask | 61.11% | 5.8646 | 0.199106 |
| 3 | volume_delta | 100.00% | 0.0157 | 0.000870 |
| 4 | price_momentum | 41.67% | 0.0149 | 0.000346 |
| 5 | funding | 0.00% | 0.0004 | 0.000000 |

### Most Destructive Signals (agreement → wrong outcome)

| Rank | Signal | Agreed Failure Rate | Total Influence | Destructive Score |
|------|--------|---------------------|-----------------|-------------------|
| 1 | orderflow | 38.89% | 13.5138 | 0.291966 |
| 2 | bidask | 38.89% | 5.8646 | 0.126704 |
| 3 | price_momentum | 58.33% | 0.0149 | 0.000484 |
| 4 | funding | 100.00% | 0.0004 | 0.000352 |
| 5 | volume_delta | 0.00% | 0.0157 | 0.000000 |

## Top 20 Best Predictions

| # | Timestamp | Symbol | Dir | Conf | Realized Return |
|---|-----------|--------|-----|------|----------------|
| 1 | 2026-06-17T19:15:36 | ETHUSDT | LONG | 0.6126 | +35.455704 |
| 2 | 2026-06-13T02:57:57 | ETHUSDT | LONG | 0.6148 | +0.035547 |
| 3 | 2026-06-17T12:30:47 | ETHUSDT | LONG | 0.5754 | +0.006935 |
| 4 | 2026-06-17T13:45:38 | ETHUSDT | SHORT | 0.5672 | +0.005161 |
| 5 | 2026-06-17T16:30:50 | ETHUSDT | SHORT | 0.5986 | +0.004354 |
| 6 | 2026-06-16T15:45:40 | ETHUSDT | LONG | 0.6097 | +0.003647 |
| 7 | 2026-06-16T14:31:03 | ETHUSDT | LONG | 0.6156 | +0.003439 |
| 8 | 2026-06-16T14:45:51 | ETHUSDT | SHORT | 0.5764 | +0.001688 |
| 9 | 2026-06-17T08:45:46 | ETHUSDT | LONG | 0.6130 | +0.001586 |
| 10 | 2026-06-17T09:00:47 | ETHUSDT | LONG | 0.6083 | +0.001375 |
| 11 | 2026-06-16T10:30:46 | ETHUSDT | SHORT | 0.6142 | +0.000162 |
| 12 | 2026-06-16T16:20:44 | ETHUSDT | SHORT | 0.5845 | -0.001227 |
| 13 | 2026-06-14T22:01:54 | ETHUSDT | LONG | 0.6105 | -0.001315 |
| 14 | 2026-06-16T19:00:59 | ETHUSDT | SHORT | 0.6155 | -0.001353 |
| 15 | 2026-06-14T22:22:00 | ETHUSDT | LONG | 0.6117 | -0.002569 |
| 16 | 2026-06-16T02:30:43 | ETHUSDT | LONG | 0.6161 | -0.003454 |
| 17 | 2026-06-17T14:15:43 | ETHUSDT | LONG | 0.5972 | -0.004624 |
| 18 | 2026-06-16T09:15:42 | ETHUSDT | SHORT | 0.6163 | -36.082700 |

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
| 18 | 2026-06-17T19:15:36 | ETHUSDT | LONG | 0.6126 | +35.455704 |

---

*SENECIO ORACLE_LAB — Primero medir. Después decidir.*

Rules: No modificar el SDC. No agregar nuevas señales. No optimizar parámetros.
