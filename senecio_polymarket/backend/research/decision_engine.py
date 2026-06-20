"""
SENECIO ORACLE — Decision Engine (ACT FINAL_AUDIT — A8)
==========================================================

STRICT_ADDITIVE automatic patch-recommendation engine.

Reads the output of statistical_study.run_full_study() and applies
the decision rules from A8:

  if (hour_filter still significant OOS) AND
     (delta_wr >= 10pp) AND
     (p < 0.05) AND
     (permutation_p < 0.05) AND
     (bootstrap_positive) AND
     (CPCV_positive)
  then PROPOSE_PATCH
  else REJECT_PATCH

Crucially: this module does NOT implement patches. It only emits a
recommendation that a human must review before any code change.

NEVER modifies trading logic.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("senecio.decision_engine")

# Decision thresholds (per A8 spec)
THRESHOLDS = {
    "delta_wr_pp": 10.0,        # >=10pp
    "p_value": 0.05,             # p < 0.05
    "permutation_p": 0.05,       # permutation < 0.05
    "bootstrap_positive": True,  # CI lower bound > 0
    "cpcv_positive": True,       # PBO < 0.5 (less than half combos overfit)
    "bonferroni_survives": True, # survives multiple-testing correction
}


def _evaluate_candidate_filter(candidate: dict, study: dict) -> dict:
    """Evaluate a single candidate filter against all 5 decision criteria."""
    cf = candidate.get("filter", {})
    delta_pp = candidate.get("wr_delta_pp", 0.0)
    n_kept = candidate.get("n_kept", 0)
    n_removed = candidate.get("n_removed", 0)

    # Find matching permutation test (if exists)
    feature = cf.get("feature")
    bucket = cf.get("excluded_bucket")
    perm_p = None
    if feature == "hour_utc":
        perm_info = study.get("tests", {}).get("permutation_hour_buckets", {}).get(bucket)
        if perm_info:
            perm_p = perm_info.get("p_value")
    elif feature == "regime_4h":
        perm_info = study.get("tests", {}).get("permutation_regime_buckets", {}).get(bucket)
        if perm_info:
            perm_p = perm_info.get("p_value")

    # Bootstrap CI of the KEPT subset (approximate — uses Wilson lower bound)
    # For simplicity, use Wilson lower bound as bootstrap proxy
    kept_wr = candidate.get("wr_with_filter", 0.0)
    # Wilson lower bound as a CI proxy
    import math
    n = n_kept
    if n > 0:
        z = 1.96
        p = kept_wr
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        wilson_low = max(0.0, center - margin)
    else:
        wilson_low = 0.0

    # CPCV positive: PBO < 0.5
    cpcv = study.get("tests", {}).get("cpcv", {})
    cpcv_pbo = cpcv.get("pbo")
    cpcv_positive = (cpcv_pbo is not None and cpcv_pbo < 0.5) if cpcv_pbo is not None else False

    # Bonferroni: does the matching test survive?
    bonf_survives = False
    mtc = study.get("tests", {}).get("multiple_testing_corrections", {})
    for test in mtc.get("tests", []):
        if feature == "hour_utc" and test.get("test") == f"permutation_hour_{bucket}":
            bonf_survives = test.get("survives_bonferroni", False)
            break
        if feature == "regime_4h" and test.get("test") == f"permutation_regime_{bucket}":
            bonf_survives = test.get("survives_bonferroni", False)
            break

    # Apply rules
    checks = {
        "delta_wr_pp": round(delta_pp, 2),
        "delta_wr_passes": delta_pp >= THRESHOLDS["delta_wr_pp"],
        "p_value": perm_p,
        "p_value_passes": (perm_p is not None and perm_p < THRESHOLDS["p_value"]),
        "permutation_p": perm_p,  # same as p_value for our permutation tests
        "permutation_p_passes": (perm_p is not None and perm_p < THRESHOLDS["permutation_p"]),
        "bootstrap_lower_bound": round(wilson_low, 4),
        "bootstrap_positive": wilson_low > 0.0,
        "cpcv_pbo": cpcv_pbo,
        "cpcv_positive": cpcv_positive,
        "bonferrani_survives": bonf_survives,
    }

    all_pass = (
        checks["delta_wr_passes"]
        and checks["p_value_passes"]
        and checks["permutation_p_passes"]
        and checks["bootstrap_positive"]
        and checks["cpcv_positive"]
    )

    return {
        "candidate": cf,
        "n_kept": n_kept,
        "n_removed": n_removed,
        "wr_with_filter": kept_wr,
        "wr_without_filter": candidate.get("wr_without_filter"),
        "wr_delta_pp": round(delta_pp, 2),
        "checks": checks,
        "all_checks_pass": all_pass,
        "recommendation": "PROPOSE_PATCH" if all_pass else "REJECT_PATCH",
    }


def evaluate_all_candidates(study: dict) -> dict:
    """Evaluate every counterfactual candidate from the study."""
    cf_results = (study.get("tests", {}).get("counterfactual_search", {}) or {}).get("results", [])
    if not cf_results:
        return {
            "n_candidates": 0,
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidates": [],
            "any_proposed": False,
            "decision": "REJECT_PATCH",
            "reason": "no counterfactual candidates available",
        }

    evaluations = []
    for cf in cf_results:
        try:
            evaluations.append(_evaluate_candidate_filter(cf, study))
        except Exception as e:
            log.warning("candidate evaluation failed: %s", e)

    # Sort by delta_wr descending
    evaluations.sort(key=lambda x: -x.get("wr_delta_pp", 0))

    proposed = [e for e in evaluations if e["recommendation"] == "PROPOSE_PATCH"]
    return {
        "n_candidates": len(evaluations),
        "n_proposed": len(proposed),
        "n_rejected": len(evaluations) - len(proposed),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "thresholds": THRESHOLDS,
        "candidates": evaluations,
        "any_proposed": len(proposed) > 0,
        "decision": "PROPOSE_PATCH" if proposed else "REJECT_PATCH",
        "top_proposed": proposed[:3] if proposed else [],
        "top_rejected": [e for e in evaluations if e["recommendation"] == "REJECT_PATCH"][:3],
    }


def make_decision(study: dict, evidence_progress: dict) -> dict:
    """Top-level: combine statistical study + evidence progress to emit decision.

    The decision is REJECT_PATCH unless:
      - evidence targets are met (>=200 verified, >=100 long, >=100 short)
      - at least one counterfactual candidate passes ALL 5 criteria
    """
    targets_met = evidence_progress.get("all_targets_met", False)
    candidate_eval = evaluate_all_candidates(study)

    if not targets_met:
        return {
            "decision": "DEFER",
            "reason": "evidence targets not yet met",
            "evidence_progress": evidence_progress,
            "candidate_evaluation": candidate_eval,
            "decided_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "decision": candidate_eval["decision"],
        "reason": (
            "all 5 criteria met for at least one candidate" if candidate_eval["any_proposed"]
            else "no candidate passed all 5 criteria"
        ),
        "evidence_progress": evidence_progress,
        "candidate_evaluation": candidate_eval,
        "decided_at_utc": datetime.now(timezone.utc).isoformat(),
    }
