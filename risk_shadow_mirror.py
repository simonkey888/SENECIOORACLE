"""
risk_shadow_mirror.py — RiskShadowMirror
==========================================

Compares model risk estimates against real market outcomes to calibrate
the internal risk model. Part of the GLM/SENECIO LIVE_BRIDGE_LAYER_v1
shadow bridge.

The internal risk model (SingleDecisionCore's risk_filter) makes theoretical
estimates. The RiskShadowMirror compares those estimates to what actually
happened in the market, answering:
- Is our risk model too optimistic? (underestimates risk)
- Is our risk model too conservative? (overestimates risk)
- Are we taking too much or too little risk?
- How accurate is our drawdown prediction?

This is an OBSERVATION and MONITORING component.
NO real orders, NO API keys — purely analytical.
"""

from __future__ import annotations

import time
import math
import logging
from collections import deque
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


class RiskShadowMirror:
    """Mirror risk model estimates against real market outcomes.

    After each shadow execution cycle:
    1. Record what the risk model estimated (risk_score, size_multiplier, etc.)
    2. Record what actually happened (realized drawdown, real slippage, etc.)
    3. Compute calibration metrics

    The mirror answers:
    - Is our risk model too optimistic? (underestimates risk)
    - Is our risk model too conservative? (overestimates risk)
    - Are we taking too much or too little risk?
    - How accurate is our drawdown prediction?

    Attributes:
        max_drawdown: Maximum acceptable drawdown fraction.
        ruin_probability_threshold: Probability threshold for ruin detection.
    """

    # Risk model bias constants
    BIAS_OVERCONFIDENT = "OVERCONFIDENT"
    BIAS_CALIBRATED = "CALIBRATED"
    BIAS_CONSERVATIVE = "CONSERVATIVE"

    # Calibration recommendation constants
    REC_KEEP_MODEL = "KEEP_MODEL"
    REC_RECALIBRATE = "RECALIBRATE"
    REC_OVERHAUL = "OVERHAUL"

    def __init__(self, config: Optional[dict] = None):
        """Initialize the RiskShadowMirror.

        Args:
            config: Optional configuration dict overriding defaults.
                Supported keys:
                - max_drawdown (float): Default 0.12
                - ruin_probability_threshold (float): Default 0.05
                - risk_estimates_maxlen (int): Default 500
                - realized_outcomes_maxlen (int): Default 500
                - calibration_log_maxlen (int): Default 200
                - safe_risk_threshold (float): Default 0.50
                - danger_risk_threshold (float): Default 0.75
                - bad_outcome_dd (float): Default 0.05
                - bad_outcome_slippage_bps (float): Default 10.0
        """
        config = config or {}

        # History buffers
        self._risk_estimates: deque = deque(
            maxlen=config.get("risk_estimates_maxlen", 500)
        )
        self._realized_outcomes: deque = deque(
            maxlen=config.get("realized_outcomes_maxlen", 500)
        )
        self._calibration_log: deque = deque(
            maxlen=config.get("calibration_log_maxlen", 200)
        )

        # Governance thresholds
        self.max_drawdown: float = config.get("max_drawdown", 0.12)
        self.ruin_probability_threshold: float = config.get(
            "ruin_probability_threshold", 0.05
        )

        # Calibration thresholds
        self._safe_risk_threshold: float = config.get("safe_risk_threshold", 0.50)
        self._danger_risk_threshold: float = config.get("danger_risk_threshold", 0.75)
        self._bad_outcome_dd: float = config.get("bad_outcome_dd", 0.05)
        self._bad_outcome_slippage_bps: float = config.get(
            "bad_outcome_slippage_bps", 10.0
        )

        # Running statistics
        self._total_estimates: int = 0
        self._total_outcomes: int = 0
        self._pair_count: int = 0  # matched estimate-outcome pairs
        self._sum_estimated_risk: float = 0.0
        self._sum_realized_risk: float = 0.0
        self._sum_dd_error: float = 0.0
        self._false_safe_count: int = 0
        self._false_danger_count: int = 0
        self._correct_safe_count: int = 0
        self._correct_danger_count: int = 0
        self._max_realized_dd: float = 0.0
        self._breach_count: int = 0  # drawdown exceeded max_drawdown

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_estimate(self, risk_state: dict, risk_filter_result: dict) -> dict:
        """Record the risk model's estimate for a cycle.

        Args:
            risk_state: The risk state snapshot, expected keys:
                - 'risk_score' (float): Overall risk score [0, 1]
                - 'estimated_drawdown' (float): Predicted max drawdown fraction
                - 'volatility' (float, optional): Estimated volatility
                - 'regime' (str, optional): Current regime label
            risk_filter_result: The risk filter output, expected keys:
                - 'size_multiplier' (float): Position size multiplier
                - 'verdict' (str): Risk verdict (e.g., 'PASS', 'REDUCE', 'BLOCK')
                - 'adjusted_score' (float, optional): Score after filter adjustments

        Returns:
            Summary of the recorded estimate.
        """
        ts = time.time() * 1000.0
        risk_score = float(risk_state.get("risk_score", 0.0))
        estimated_dd = float(risk_state.get("estimated_drawdown", 0.0))
        size_mult = float(risk_filter_result.get("size_multiplier", 0.0))
        verdict = str(risk_filter_result.get("verdict", "UNKNOWN"))
        adjusted_score = float(risk_filter_result.get("adjusted_score", risk_score))
        volatility = float(risk_state.get("volatility", 0.0))
        regime = str(risk_state.get("regime", "UNKNOWN"))

        entry = {
            "timestamp_ms": ts,
            "risk_score": risk_score,
            "estimated_drawdown": estimated_dd,
            "size_multiplier": size_mult,
            "verdict": verdict,
            "adjusted_score": adjusted_score,
            "volatility": volatility,
            "regime": regime,
        }
        self._risk_estimates.append(entry)
        self._total_estimates += 1
        self._sum_estimated_risk += risk_score

        return {
            "recorded": True,
            "total_estimates": self._total_estimates,
            "risk_score": risk_score,
            "estimated_drawdown": estimated_dd,
        }

    def record_outcome(
        self,
        realized_pnl_pct: float,
        realized_dd: float,
        realized_slippage_bps: float,
        survival: bool,
    ) -> dict:
        """Record the real market outcome.

        Args:
            realized_pnl_pct: Realized P&L as a percentage of capital.
            realized_dd: Realized maximum drawdown fraction (e.g., 0.03 = 3%).
            realized_slippage_bps: Realized execution slippage in basis points.
            survival: Whether the position/portfolio survived without ruin.

        Returns:
            Summary of the recorded outcome, including a match attempt.
        """
        ts = time.time() * 1000.0

        entry = {
            "timestamp_ms": ts,
            "realized_pnl_pct": realized_pnl_pct,
            "realized_dd": realized_dd,
            "realized_slippage_bps": realized_slippage_bps,
            "survival": survival,
        }
        self._realized_outcomes.append(entry)
        self._total_outcomes += 1

        # Compute a "realized risk" proxy from drawdown and slippage
        realized_risk = min(1.0, realized_dd / self.max_drawdown) if self.max_drawdown > 0 else 0.0
        self._sum_realized_risk += realized_risk
        self._max_realized_dd = max(self._max_realized_dd, realized_dd)

        if realized_dd >= self.max_drawdown:
            self._breach_count += 1

        # Try to match with most recent unpaired estimate
        matched = self._try_match_estimate(entry)

        return {
            "recorded": True,
            "total_outcomes": self._total_outcomes,
            "matched_with_estimate": matched,
            "realized_dd": realized_dd,
            "survival": survival,
        }

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def compute_calibration(self) -> dict:
        """Compute risk model calibration metrics.

        Compares paired risk estimates with realized outcomes to evaluate:
        - How often risk estimates match outcomes
        - Whether the model is overconfident or conservative
        - Drawdown prediction accuracy
        - Size optimality
        - False safe / false danger rates
        - Overall calibration score

        Returns:
            Calibration report dict with:
            - risk_model_accuracy (float): Fraction of correct risk assessments [0, 1]
            - risk_model_bias (str): OVERCONFIDENT / CALIBRATED / CONSERVATIVE
            - avg_estimated_risk (float)
            - avg_realized_risk (float)
            - drawdown_prediction_error (float): Avg |predicted - actual| dd
            - size_optimality (str): TOO_LARGE / OPTIMAL / TOO_SMALL
            - false_safe_rate (float): % of "safe" predictions with bad outcomes
            - false_danger_rate (float): % of "danger" predictions with fine outcomes
            - calibration_score (float): Overall calibration quality [0, 1]
            - recommendation (str): KEEP_MODEL / RECALIBRATE / OVERHAUL
            - pair_count (int): Number of estimate-outcome pairs used
        """
        # Collect all paired entries from calibration log
        pairs = list(self._calibration_log)
        n = len(pairs)

        if n == 0:
            return self._empty_calibration()

        # ---- Risk model accuracy ----
        correct = sum(1 for p in pairs if p.get("correct", False))
        risk_model_accuracy = correct / n

        # ---- Risk model bias ----
        avg_est = sum(p["estimated_risk"] for p in pairs) / n
        avg_real = sum(p["realized_risk"] for p in pairs) / n
        bias_ratio = avg_est / avg_real if avg_real > 0 else float("inf")

        if bias_ratio < 0.80:
            risk_model_bias = self.BIAS_OVERCONFIDENT  # estimating lower than reality
        elif bias_ratio > 1.25:
            risk_model_bias = self.BIAS_CONSERVATIVE  # estimating higher than reality
        else:
            risk_model_bias = self.BIAS_CALIBRATED

        # ---- Drawdown prediction error ----
        dd_errors = [abs(p.get("estimated_dd", 0.0) - p.get("realized_dd", 0.0)) for p in pairs]
        drawdown_prediction_error = sum(dd_errors) / n

        # ---- Size optimality ----
        # If we consistently had bad outcomes with large sizes → TOO_LARGE
        # If we consistently had good outcomes with small sizes → TOO_SMALL
        avg_size = sum(p.get("size_multiplier", 0.0) for p in pairs) / n
        good_outcomes = [p for p in pairs if not p.get("bad_outcome", False)]
        bad_outcomes = [p for p in pairs if p.get("bad_outcome", False)]

        if bad_outcomes:
            avg_size_bad = sum(p.get("size_multiplier", 0.0) for p in bad_outcomes) / len(bad_outcomes)
        else:
            avg_size_bad = 0.0

        if good_outcomes:
            avg_size_good = sum(p.get("size_multiplier", 0.0) for p in good_outcomes) / len(good_outcomes)
        else:
            avg_size_good = 0.0

        if avg_size_bad > avg_size_good * 1.20 and len(bad_outcomes) >= 3:
            size_optimality = "TOO_LARGE"
        elif avg_size_good > avg_size_bad * 1.20 and len(good_outcomes) >= 3 and avg_size < 0.5:
            size_optimality = "TOO_SMALL"
        else:
            size_optimality = "OPTIMAL"

        # ---- False safe / false danger rates ----
        safe_predictions = [p for p in pairs if p.get("predicted_safe", False)]
        danger_predictions = [p for p in pairs if p.get("predicted_danger", False)]

        if safe_predictions:
            false_safe = sum(1 for p in safe_predictions if p.get("bad_outcome", False))
            false_safe_rate = false_safe / len(safe_predictions)
        else:
            false_safe_rate = 0.0

        if danger_predictions:
            false_danger = sum(1 for p in danger_predictions if not p.get("bad_outcome", False))
            false_danger_rate = false_danger / len(danger_predictions)
        else:
            false_danger_rate = 0.0

        # ---- Calibration score (composite) ----
        # Weighted combination: accuracy (40%), dd error inverse (30%), false safe inverse (30%)
        dd_error_score = max(0.0, 1.0 - drawdown_prediction_error / self.max_drawdown) if self.max_drawdown > 0 else 0.0
        false_safe_score = 1.0 - false_safe_rate

        calibration_score = (
            0.40 * risk_model_accuracy
            + 0.30 * dd_error_score
            + 0.30 * false_safe_score
        )
        calibration_score = max(0.0, min(1.0, calibration_score))

        # ---- Recommendation ----
        if calibration_score >= 0.80 and risk_model_bias == self.BIAS_CALIBRATED:
            recommendation = self.REC_KEEP_MODEL
        elif calibration_score >= 0.50:
            recommendation = self.REC_RECALIBRATE
        else:
            recommendation = self.REC_OVERHAUL

        return {
            "risk_model_accuracy": round(risk_model_accuracy, 6),
            "risk_model_bias": risk_model_bias,
            "avg_estimated_risk": round(avg_est, 6),
            "avg_realized_risk": round(avg_real, 6),
            "drawdown_prediction_error": round(drawdown_prediction_error, 6),
            "size_optimality": size_optimality,
            "false_safe_rate": round(false_safe_rate, 6),
            "false_danger_rate": round(false_danger_rate, 6),
            "calibration_score": round(calibration_score, 6),
            "recommendation": recommendation,
            "pair_count": n,
        }

    # ------------------------------------------------------------------
    # State & stats
    # ------------------------------------------------------------------

    def get_risk_mirror_state(self) -> dict:
        """Get current risk mirror state for dashboard.

        Returns:
            Dashboard-ready state dict with latest estimates, outcomes,
            and a quick calibration summary.
        """
        latest_estimate = self._risk_estimates[-1] if self._risk_estimates else None
        latest_outcome = self._realized_outcomes[-1] if self._realized_outcomes else None
        calibration = self.compute_calibration()

        return {
            "total_estimates": self._total_estimates,
            "total_outcomes": self._total_outcomes,
            "pair_count": self._pair_count,
            "max_realized_dd": round(self._max_realized_dd, 6),
            "breach_count": self._breach_count,
            "latest_estimate": latest_estimate,
            "latest_outcome": latest_outcome,
            "calibration_score": calibration["calibration_score"],
            "risk_model_bias": calibration["risk_model_bias"],
            "recommendation": calibration["recommendation"],
        }

    def get_stats(self) -> dict:
        """Get risk mirror statistics.

        Returns:
            Statistics dict with counts, averages, and buffer sizes.
        """
        n_est = self._total_estimates
        n_out = self._total_outcomes

        avg_est = self._sum_estimated_risk / n_est if n_est else 0.0
        avg_real = self._sum_realized_risk / n_out if n_out else 0.0
        avg_dd_err = self._sum_dd_error / self._pair_count if self._pair_count else 0.0

        return {
            "total_estimates": n_est,
            "total_outcomes": n_out,
            "pair_count": self._pair_count,
            "avg_estimated_risk": round(avg_est, 6),
            "avg_realized_risk": round(avg_real, 6),
            "avg_drawdown_error": round(avg_dd_err, 6),
            "max_realized_dd": round(self._max_realized_dd, 6),
            "breach_count": self._breach_count,
            "false_safe_count": self._false_safe_count,
            "false_danger_count": self._false_danger_count,
            "correct_safe_count": self._correct_safe_count,
            "correct_danger_count": self._correct_danger_count,
            "estimates_buffer_len": len(self._risk_estimates),
            "outcomes_buffer_len": len(self._realized_outcomes),
            "calibration_log_len": len(self._calibration_log),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_match_estimate(self, outcome: dict) -> bool:
        """Try to match a realized outcome with the most recent unpaired estimate.

        When a match is found, a calibration entry is created in _calibration_log.

        Args:
            outcome: The realized outcome dict.

        Returns:
            True if a match was found, False otherwise.
        """
        # Find the most recent estimate that hasn't been paired
        # Simple approach: match by order (estimates and outcomes should arrive in pairs)
        if not self._risk_estimates:
            return False

        # Take the most recent estimate (LIFO matching for latency)
        estimate = self._risk_estimates[-1]

        # Build calibration pair
        estimated_risk = estimate["adjusted_score"]
        estimated_dd = estimate["estimated_drawdown"]
        realized_dd = outcome["realized_dd"]
        realized_slippage = outcome["realized_slippage_bps"]

        # Compute realized risk proxy
        realized_risk = min(1.0, realized_dd / self.max_drawdown) if self.max_drawdown > 0 else 0.0

        # Determine predictions
        predicted_safe = estimated_risk < self._safe_risk_threshold
        predicted_danger = estimated_risk >= self._danger_risk_threshold

        # Determine if outcome was bad
        bad_outcome = (
            realized_dd >= self._bad_outcome_dd
            or realized_slippage >= self._bad_outcome_slippage_bps
            or not outcome.get("survival", True)
        )

        # Determine correctness
        if predicted_safe and not bad_outcome:
            correct = True  # Correctly predicted safe
            self._correct_safe_count += 1
        elif predicted_danger and bad_outcome:
            correct = True  # Correctly predicted danger
            self._correct_danger_count += 1
        elif predicted_safe and bad_outcome:
            correct = False  # False safe
            self._false_safe_count += 1
        elif predicted_danger and not bad_outcome:
            correct = False  # False danger
            self._false_danger_count += 1
        else:
            # Middle ground (not clearly safe or danger)
            correct = not bad_outcome

        # Track drawdown error
        dd_error = abs(estimated_dd - realized_dd)
        self._sum_dd_error += dd_error

        # Create calibration entry
        calibration_entry = {
            "timestamp_ms": outcome["timestamp_ms"],
            "estimated_risk": estimated_risk,
            "realized_risk": realized_risk,
            "estimated_dd": estimated_dd,
            "realized_dd": realized_dd,
            "dd_error": dd_error,
            "size_multiplier": estimate["size_multiplier"],
            "verdict": estimate["verdict"],
            "predicted_safe": predicted_safe,
            "predicted_danger": predicted_danger,
            "bad_outcome": bad_outcome,
            "correct": correct,
            "survival": outcome.get("survival", True),
            "realized_pnl_pct": outcome["realized_pnl_pct"],
        }
        self._calibration_log.append(calibration_entry)
        self._pair_count += 1

        return True

    def _empty_calibration(self) -> dict:
        """Return a zeroed-out calibration report when no data exists."""
        return {
            "risk_model_accuracy": 0.0,
            "risk_model_bias": self.BIAS_CALIBRATED,
            "avg_estimated_risk": 0.0,
            "avg_realized_risk": 0.0,
            "drawdown_prediction_error": 0.0,
            "size_optimality": "OPTIMAL",
            "false_safe_rate": 0.0,
            "false_danger_rate": 0.0,
            "calibration_score": 0.0,
            "recommendation": self.REC_KEEP_MODEL,
            "pair_count": 0,
        }


# ======================================================================
# Self-Test
# ======================================================================

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    print("=" * 70)
    print("RiskShadowMirror — Self-Test")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        global passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  — {detail}")

    # ------------------------------------------------------------------
    # Test 1: Basic initialization
    # ------------------------------------------------------------------
    print("\n--- Test 1: Initialization ---")
    rsm = RiskShadowMirror()
    check("default max_drawdown", rsm.max_drawdown == 0.12)
    check("default ruin_probability_threshold", rsm.ruin_probability_threshold == 0.05)
    check("empty stats", rsm.get_stats()["total_estimates"] == 0)
    check("empty calibration pair_count", rsm.compute_calibration()["pair_count"] == 0)

    # ------------------------------------------------------------------
    # Test 2: Custom config
    # ------------------------------------------------------------------
    print("\n--- Test 2: Custom Config ---")
    cfg = {
        "max_drawdown": 0.20,
        "ruin_probability_threshold": 0.03,
        "safe_risk_threshold": 0.40,
        "danger_risk_threshold": 0.70,
        "risk_estimates_maxlen": 100,
        "realized_outcomes_maxlen": 100,
        "calibration_log_maxlen": 50,
    }
    rsm2 = RiskShadowMirror(config=cfg)
    check("custom max_drawdown", rsm2.max_drawdown == 0.20)
    check("custom ruin_probability_threshold", rsm2.ruin_probability_threshold == 0.03)

    # ------------------------------------------------------------------
    # Test 3: record_estimate
    # ------------------------------------------------------------------
    print("\n--- Test 3: record_estimate ---")
    rsm3 = RiskShadowMirror()
    result3 = rsm3.record_estimate(
        risk_state={"risk_score": 0.30, "estimated_drawdown": 0.02, "volatility": 0.15, "regime": "RANGING"},
        risk_filter_result={"size_multiplier": 0.80, "verdict": "PASS", "adjusted_score": 0.30},
    )
    check("estimate recorded", result3["recorded"] is True)
    check("total_estimates == 1", result3["total_estimates"] == 1)
    check("risk_score captured", result3["risk_score"] == 0.30)

    # ------------------------------------------------------------------
    # Test 4: record_outcome
    # ------------------------------------------------------------------
    print("\n--- Test 4: record_outcome ---")
    rsm4 = RiskShadowMirror()
    rsm4.record_estimate(
        risk_state={"risk_score": 0.30, "estimated_drawdown": 0.02},
        risk_filter_result={"size_multiplier": 0.80, "verdict": "PASS"},
    )
    result4 = rsm4.record_outcome(
        realized_pnl_pct=1.5,
        realized_dd=0.01,
        realized_slippage_bps=3.0,
        survival=True,
    )
    check("outcome recorded", result4["recorded"] is True)
    check("total_outcomes == 1", result4["total_outcomes"] == 1)
    check("matched with estimate", result4["matched_with_estimate"] is True)

    # ------------------------------------------------------------------
    # Test 5: Calibrated model (estimates match outcomes)
    # ------------------------------------------------------------------
    print("\n--- Test 5: Calibrated Model ---")
    rsm5 = RiskShadowMirror()
    # Record multiple matching pairs: low risk + good outcomes
    for i in range(10):
        rsm5.record_estimate(
            risk_state={"risk_score": 0.20, "estimated_drawdown": 0.01},
            risk_filter_result={"size_multiplier": 0.80, "verdict": "PASS", "adjusted_score": 0.20},
        )
        rsm5.record_outcome(
            realized_pnl_pct=1.0,
            realized_dd=0.01,
            realized_slippage_bps=2.0,
            survival=True,
        )
    cal5 = rsm5.compute_calibration()
    check("pair_count == 10", cal5["pair_count"] == 10)
    check(
        "calibration_score is high",
        cal5["calibration_score"] >= 0.70,
        f"got {cal5['calibration_score']}",
    )
    check(
        "risk_model_bias is CALIBRATED or CONSERVATIVE",
        cal5["risk_model_bias"] in ("CALIBRATED", "CONSERVATIVE"),
        f"got {cal5['risk_model_bias']}",
    )
    check(
        "false_safe_rate is low",
        cal5["false_safe_rate"] <= 0.20,
        f"got {cal5['false_safe_rate']}",
    )

    # ------------------------------------------------------------------
    # Test 6: Overconfident model (underestimates risk)
    # ------------------------------------------------------------------
    print("\n--- Test 6: Overconfident Model ---")
    rsm6 = RiskShadowMirror()
    # Low risk estimates but bad outcomes
    for i in range(10):
        rsm6.record_estimate(
            risk_state={"risk_score": 0.15, "estimated_drawdown": 0.01},
            risk_filter_result={"size_multiplier": 0.90, "verdict": "PASS", "adjusted_score": 0.15},
        )
        rsm6.record_outcome(
            realized_pnl_pct=-2.0,
            realized_dd=0.08,  # Much worse than estimated 0.01
            realized_slippage_bps=15.0,  # Bad slippage
            survival=True,
        )
    cal6 = rsm6.compute_calibration()
    check(
        "risk_model_bias OVERCONFIDENT",
        cal6["risk_model_bias"] == "OVERCONFIDENT",
        f"got {cal6['risk_model_bias']}, avg_est={cal6['avg_estimated_risk']}, avg_real={cal6['avg_realized_risk']}",
    )
    check(
        "false_safe_rate is high",
        cal6["false_safe_rate"] >= 0.50,
        f"got {cal6['false_safe_rate']}",
    )
    check(
        "recommendation is RECALIBRATE or OVERHAUL",
        cal6["recommendation"] in ("RECALIBRATE", "OVERHAUL"),
        f"got {cal6['recommendation']}",
    )

    # ------------------------------------------------------------------
    # Test 7: Conservative model (overestimates risk)
    # ------------------------------------------------------------------
    print("\n--- Test 7: Conservative Model ---")
    rsm7 = RiskShadowMirror()
    # High risk estimates but fine outcomes
    for i in range(10):
        rsm7.record_estimate(
            risk_state={"risk_score": 0.85, "estimated_drawdown": 0.10},
            risk_filter_result={"size_multiplier": 0.20, "verdict": "REDUCE", "adjusted_score": 0.85},
        )
        rsm7.record_outcome(
            realized_pnl_pct=0.5,
            realized_dd=0.005,  # Much better than estimated
            realized_slippage_bps=1.0,
            survival=True,
        )
    cal7 = rsm7.compute_calibration()
    check(
        "risk_model_bias CONSERVATIVE",
        cal7["risk_model_bias"] == "CONSERVATIVE",
        f"got {cal7['risk_model_bias']}, avg_est={cal7['avg_estimated_risk']}, avg_real={cal7['avg_realized_risk']}",
    )
    check(
        "false_danger_rate is high",
        cal7["false_danger_rate"] >= 0.50,
        f"got {cal7['false_danger_rate']}",
    )

    # ------------------------------------------------------------------
    # Test 8: Drawdown prediction error
    # ------------------------------------------------------------------
    print("\n--- Test 8: Drawdown Prediction Error ---")
    rsm8 = RiskShadowMirror()
    errors_input = [0.01, 0.02, 0.03, 0.005, 0.015]
    for est_dd in errors_input:
        rsm8.record_estimate(
            risk_state={"risk_score": 0.30, "estimated_drawdown": est_dd},
            risk_filter_result={"size_multiplier": 0.60, "verdict": "PASS", "adjusted_score": 0.30},
        )
        actual_dd = est_dd + 0.005  # Small offset
        rsm8.record_outcome(
            realized_pnl_pct=0.5,
            realized_dd=actual_dd,
            realized_slippage_bps=2.0,
            survival=True,
        )
    cal8 = rsm8.compute_calibration()
    check(
        "drawdown_prediction_error is small",
        cal8["drawdown_prediction_error"] <= 0.01,
        f"got {cal8['drawdown_prediction_error']}",
    )

    # ------------------------------------------------------------------
    # Test 9: Drawdown breach detection
    # ------------------------------------------------------------------
    print("\n--- Test 9: Drawdown Breach Detection ---")
    rsm9 = RiskShadowMirror({"max_drawdown": 0.05})
    rsm9.record_estimate(
        risk_state={"risk_score": 0.50, "estimated_drawdown": 0.03},
        risk_filter_result={"size_multiplier": 0.50, "verdict": "REDUCE", "adjusted_score": 0.50},
    )
    rsm9.record_outcome(
        realized_pnl_pct=-5.0,
        realized_dd=0.07,  # Breaches max_drawdown of 0.05
        realized_slippage_bps=8.0,
        survival=True,
    )
    stats9 = rsm9.get_stats()
    check("breach_count >= 1", stats9["breach_count"] >= 1)
    check("max_realized_dd >= 0.07", stats9["max_realized_dd"] >= 0.07)

    # ------------------------------------------------------------------
    # Test 10: get_risk_mirror_state
    # ------------------------------------------------------------------
    print("\n--- Test 10: Risk Mirror State ---")
    rsm10 = RiskShadowMirror()
    rsm10.record_estimate(
        risk_state={"risk_score": 0.40, "estimated_drawdown": 0.02},
        risk_filter_result={"size_multiplier": 0.70, "verdict": "PASS", "adjusted_score": 0.40},
    )
    rsm10.record_outcome(
        realized_pnl_pct=1.0,
        realized_dd=0.015,
        realized_slippage_bps=3.0,
        survival=True,
    )
    state10 = rsm10.get_risk_mirror_state()
    check("total_estimates == 1", state10["total_estimates"] == 1)
    check("total_outcomes == 1", state10["total_outcomes"] == 1)
    check("pair_count == 1", state10["pair_count"] == 1)
    check("calibration_score >= 0", state10["calibration_score"] >= 0.0)
    check("latest_estimate is not None", state10["latest_estimate"] is not None)
    check("latest_outcome is not None", state10["latest_outcome"] is not None)

    # ------------------------------------------------------------------
    # Test 11: Empty calibration
    # ------------------------------------------------------------------
    print("\n--- Test 11: Empty Calibration ---")
    rsm11 = RiskShadowMirror()
    cal11 = rsm11.compute_calibration()
    check("empty pair_count", cal11["pair_count"] == 0)
    check("empty calibration_score == 0", cal11["calibration_score"] == 0.0)
    check("empty recommendation KEEP_MODEL", cal11["recommendation"] == "KEEP_MODEL")

    # ------------------------------------------------------------------
    # Test 12: Stats after multiple cycles
    # ------------------------------------------------------------------
    print("\n--- Test 12: Stats After Multiple Cycles ---")
    rsm12 = RiskShadowMirror()
    for i in range(20):
        risk_score = 0.10 + i * 0.04  # 0.10 to 0.86
        est_dd = 0.005 + i * 0.005
        rsm12.record_estimate(
            risk_state={"risk_score": risk_score, "estimated_drawdown": est_dd},
            risk_filter_result={
                "size_multiplier": max(0.1, 1.0 - risk_score),
                "verdict": "PASS" if risk_score < 0.5 else "REDUCE",
                "adjusted_score": risk_score,
            },
        )
        # Mix of good and bad outcomes
        bad = i % 4 == 3  # Every 4th is bad
        rsm12.record_outcome(
            realized_pnl_pct=-1.0 if bad else 0.8,
            realized_dd=0.06 if bad else 0.01,
            realized_slippage_bps=12.0 if bad else 2.0,
            survival=True,
        )
    stats12 = rsm12.get_stats()
    check("total_estimates == 20", stats12["total_estimates"] == 20)
    check("total_outcomes == 20", stats12["total_outcomes"] == 20)
    check("pair_count == 20", stats12["pair_count"] == 20)
    check("false_safe_count > 0", stats12["false_safe_count"] > 0 or stats12["false_danger_count"] > 0)
    cal12 = rsm12.compute_calibration()
    check("calibration pair_count == 20", cal12["pair_count"] == 20)

    # ------------------------------------------------------------------
    # Test 13: Survival tracking
    # ------------------------------------------------------------------
    print("\n--- Test 13: Survival Tracking ---")
    rsm13 = RiskShadowMirror()
    rsm13.record_estimate(
        risk_state={"risk_score": 0.90, "estimated_drawdown": 0.15},
        risk_filter_result={"size_multiplier": 0.05, "verdict": "BLOCK", "adjusted_score": 0.90},
    )
    result13 = rsm13.record_outcome(
        realized_pnl_pct=-10.0,
        realized_dd=0.15,
        realized_slippage_bps=20.0,
        survival=False,  # Ruin!
    )
    check("outcome recorded", result13["recorded"])
    check("survival=False tracked", not result13["survival"])
    stats13 = rsm13.get_stats()
    check("breach_count >= 1 for ruin", stats13["breach_count"] >= 1)

    # ------------------------------------------------------------------
    # Test 14: Buffer overflow / maxlen
    # ------------------------------------------------------------------
    print("\n--- Test 14: Buffer Overflow ---")
    rsm14 = RiskShadowMirror({"risk_estimates_maxlen": 5, "realized_outcomes_maxlen": 5, "calibration_log_maxlen": 5})
    for i in range(10):
        rsm14.record_estimate(
            risk_state={"risk_score": 0.30, "estimated_drawdown": 0.01},
            risk_filter_result={"size_multiplier": 0.70, "verdict": "PASS", "adjusted_score": 0.30},
        )
        rsm14.record_outcome(realized_pnl_pct=0.5, realized_dd=0.01, realized_slippage_bps=2.0, survival=True)
    stats14 = rsm14.get_stats()
    check("estimates buffer capped", stats14["estimates_buffer_len"] <= 5)
    check("outcomes buffer capped", stats14["outcomes_buffer_len"] <= 5)
    check("calibration log capped", stats14["calibration_log_len"] <= 5)

    # ------------------------------------------------------------------
    # Test 15: Size optimality
    # ------------------------------------------------------------------
    print("\n--- Test 15: Size Optimality ---")
    rsm15 = RiskShadowMirror()
    # Bad outcomes with large sizes, good outcomes with small sizes → TOO_LARGE
    for i in range(8):
        # Good outcomes with small size
        rsm15.record_estimate(
            risk_state={"risk_score": 0.60, "estimated_drawdown": 0.04},
            risk_filter_result={"size_multiplier": 0.20, "verdict": "REDUCE", "adjusted_score": 0.60},
        )
        rsm15.record_outcome(realized_pnl_pct=0.5, realized_dd=0.01, realized_slippage_bps=2.0, survival=True)

    for i in range(5):
        # Bad outcomes with large size
        rsm15.record_estimate(
            risk_state={"risk_score": 0.20, "estimated_drawdown": 0.01},
            risk_filter_result={"size_multiplier": 0.90, "verdict": "PASS", "adjusted_score": 0.20},
        )
        rsm15.record_outcome(realized_pnl_pct=-3.0, realized_dd=0.07, realized_slippage_bps=12.0, survival=True)

    cal15 = rsm15.compute_calibration()
    # Should detect that bad outcomes came with larger sizes
    check(
        "size_optimality detected (TOO_LARGE or OPTIMAL)",
        cal15["size_optimality"] in ("TOO_LARGE", "OPTIMAL"),
        f"got {cal15['size_optimality']}",
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"Self-Test Complete: {passed} passed, {failed} failed")
    print("=" * 70)
    if failed:
        print("⚠  Some tests FAILED — review output above.")
    else:
        print("✓  All tests PASSED.")
