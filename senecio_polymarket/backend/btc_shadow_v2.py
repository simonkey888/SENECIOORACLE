"""BTC V2 shadow calibrator.

Read-only, fail-closed overlay for the existing oracle.  It never changes the
V1 prediction and never places orders; it only checks whether recent verified
BTC outcomes support the reported direction/confidence.
"""
from __future__ import annotations

import math
from typing import Any, Iterable


MIN_COHORT_N = 30
MIN_POSTERIOR_ACCURACY = 0.52
MIN_WILSON_LOWER = 0.50
CONFIDENCE_BIN_WIDTH = 0.10


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _wilson_lower(wins: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    p = wins / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (centre - radius) / denominator)


def _clean_verified(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for row in rows:
        direction = str(row.get("prediction") or "").upper()
        outcome = str(row.get("outcome") or "").upper()
        confidence = _number(row.get("confidence"))
        if direction not in {"LONG", "SHORT"} or outcome not in {"WIN", "LOSS"}:
            continue
        if confidence is None or not 0.0 <= confidence <= 1.0:
            continue
        clean.append({**row, "prediction": direction, "outcome": outcome, "confidence": confidence})
    return clean


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    wins = sum(row["outcome"] == "WIN" for row in rows)
    posterior = (wins + 1.0) / (n + 2.0)  # Beta(1, 1), explicit shrinkage.
    brier = (
        sum((row["confidence"] - (1.0 if row["outcome"] == "WIN" else 0.0)) ** 2 for row in rows) / n
        if n else None
    )
    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "observed_accuracy": wins / n if n else None,
        "posterior_accuracy": posterior,
        "wilson_lower_95": _wilson_lower(wins, n),
        "reported_confidence_brier": brier,
    }


def evaluate_btc_shadow(
    current: dict[str, Any] | None,
    history: Iterable[dict[str, Any]],
    *,
    recent_limit: int = 100,
) -> dict[str, Any]:
    """Evaluate a V1 BTC prediction against recent verified BTC outcomes."""
    current = current or {}
    direction = str(current.get("prediction") or "FLAT").upper()
    confidence = _number(current.get("confidence"))
    verified = _clean_verified(history)[:recent_limit]

    base = {
        "version": "btc-shadow-v2.0",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "live_capital_locked": True,
        "source_prediction": direction,
        "source_confidence": confidence,
        "shadow_action": "FLAT",
        "gate_status": "UNKNOWN",
        "cohort": None,
        "thresholds": {
            "recent_limit": recent_limit,
            "min_cohort_n": MIN_COHORT_N,
            "min_posterior_accuracy": MIN_POSTERIOR_ACCURACY,
            "min_wilson_lower_95": MIN_WILSON_LOWER,
        },
        "reasons": [],
    }
    if direction not in {"LONG", "SHORT"} or confidence is None:
        base["reasons"] = ["NO_DIRECTIONAL_SOURCE_PREDICTION"]
        return base

    bin_low = math.floor(confidence / CONFIDENCE_BIN_WIDTH) * CONFIDENCE_BIN_WIDTH
    if confidence == 1.0:
        bin_low = 0.9
    bin_high = min(1.0, bin_low + CONFIDENCE_BIN_WIDTH)
    exact = [
        row for row in verified
        if row["prediction"] == direction
        and bin_low <= row["confidence"] <= bin_high
    ]
    directional = [row for row in verified if row["prediction"] == direction]
    if len(exact) >= MIN_COHORT_N:
        cohort_name, cohort = f"{direction}_{bin_low:.1f}_{bin_high:.1f}", exact
    elif len(directional) >= MIN_COHORT_N:
        cohort_name, cohort = f"{direction}_ALL_CONFIDENCE", directional
    else:
        cohort_name, cohort = f"{direction}_INSUFFICIENT", directional

    stats = _stats(cohort)
    base["cohort"] = {"name": cohort_name, **stats}
    if stats["n"] < MIN_COHORT_N:
        base["reasons"] = ["INSUFFICIENT_RECENT_VERIFIED_COHORT"]
        return base

    reasons: list[str] = []
    if stats["posterior_accuracy"] < MIN_POSTERIOR_ACCURACY:
        reasons.append("POSTERIOR_ACCURACY_BELOW_GATE")
    if stats["wilson_lower_95"] <= MIN_WILSON_LOWER:
        reasons.append("EDGE_NOT_DEMONSTRATED_AT_95PCT")
    if reasons:
        base["gate_status"] = "REJECT"
        base["reasons"] = reasons
        return base

    base["gate_status"] = "PASS"
    base["shadow_action"] = direction
    base["reasons"] = ["RECENT_CALIBRATION_GATE_PASSED"]
    return base
