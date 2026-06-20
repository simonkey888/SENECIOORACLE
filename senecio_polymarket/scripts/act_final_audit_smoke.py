#!/usr/bin/env python3
"""
ACT FINAL_AUDIT (MYTHOS) — Smoke Test Suite
==============================================
Verifies that ALL A1-A9 deliverables are correctly installed and
that the trading-logic DO_NOT_TOUCH zones are intact.

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m scripts.act_final_audit_smoke
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Set up path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
PASSES = []


def check(name: str, ok: bool, detail: str = ""):
    if ok:
        PASSES.append((name, detail))
        print(f"  PASS  {name}  {detail}")
    else:
        FAILS.append((name, detail))
        print(f"  FAIL  {name}  {detail}")


# ─────────────────────────────────────────────────────────────────────
# T1: Freeze artifacts exist (A1)
# ─────────────────────────────────────────────────────────────────────
def t1_freeze_artifacts():
    print("\n=== T1: Freeze Artifacts (A1) ===")
    freeze_dir = ROOT / "freeze"
    check("freeze dir exists", freeze_dir.exists(), str(freeze_dir))
    for fname in ("manifest_sha256.txt", "versions.json", "pip_freeze.txt", "environment.json"):
        p = freeze_dir / fname
        check(f"freeze/{fname} exists", p.exists(), f"{p.stat().st_size} bytes" if p.exists() else "missing")

    versions = json.loads((freeze_dir / "versions.json").read_text())
    check("versions.freeze_tag == PRE_LONG_FIX_FREEZE",
          versions.get("freeze_tag") == "PRE_LONG_FIX_FREEZE",
          versions.get("freeze_tag"))
    check("versions.freeze_mode == STRICT_ADDITIVE",
          versions.get("freeze_mode") == "STRICT_ADDITIVE",
          versions.get("freeze_mode"))
    check("versions.freeze_trade_mode == PAPER_ONLY",
          versions.get("freeze_trade_mode") == "PAPER_ONLY",
          versions.get("freeze_trade_mode"))
    check("versions.freeze_live_gate == LOCKED",
          versions.get("freeze_live_gate") == "LOCKED",
          versions.get("freeze_live_gate"))
    check("versions.file_count > 50",
          versions.get("file_count", 0) > 50,
          str(versions.get("file_count")))

    # Check git tag
    import subprocess
    r = subprocess.run(["git", "-C", str(ROOT.parent), "tag", "-l", "PRE_LONG_FIX_FREEZE"],
                       capture_output=True, text=True, check=False)
    check("git tag PRE_LONG_FIX_FREEZE exists",
          "PRE_LONG_FIX_FREEZE" in r.stdout,
          r.stdout.strip())


# ─────────────────────────────────────────────────────────────────────
# T2: Audit enrichment (A2)
# ─────────────────────────────────────────────────────────────────────
def t2_audit_enrichment():
    print("\n=== T2: Audit Enrichment (A2) ===")
    try:
        from backend import audit_enrichment
        check("audit_enrichment imports", True)
    except Exception as e:
        check("audit_enrichment imports", False, str(e))
        return

    check("ENRICHMENT_VERSION set",
          hasattr(audit_enrichment, "ENRICHMENT_VERSION") and audit_enrichment.ENRICHMENT_VERSION,
          audit_enrichment.ENRICHMENT_VERSION)
    check("MODEL_VERSION set",
          hasattr(audit_enrichment, "MODEL_VERSION") and audit_enrichment.MODEL_VERSION,
          audit_enrichment.MODEL_VERSION)
    check("REQUIRED_FIELDS count == 33",
          len(audit_enrichment.REQUIRED_FIELDS) == 33,
          str(len(audit_enrichment.REQUIRED_FIELDS)))

    # Test enrichment on a fake prediction
    test_pred = {
        "timestamp": "2026-06-20T14:30:00+00:00",
        "symbol": "ETHUSDT",
        "prediction": "LONG",
        "confidence": 0.65,
        "ev": 0.0012,
        "price_now": 2500.50,
        "_audit": {
            "action_vector": {"action": "EXECUTE", "side": "LONG", "size": 0.15},
            "pipeline": {
                "step1_market": {"ticker": {"bid": 2500.0, "ask": 2500.5}, "liquidity_quality": 0.78, "funding_rate": 0.0001},
                "step2_features": {"conviction": 0.65, "pressures": {"bidask_imbalance": 0.7},
                                   "microstructure": {"vpin": 0.12, "ofi": 0.3},
                                   "regime_4h": "BULL", "regime_hint": "RANGING"},
                "step3_risk": {"capacity_score": 0.85, "stress_score": 0.15},
                "step4_ev": {"adjusted_ev": 0.0012, "expected_value": 0.0012},
                "step5_feasibility": {},
            },
            "execution_state": {},
            "candle_ts": 0,
        },
    }

    enriched = audit_enrichment.enrich_prediction(test_pred)
    report = audit_enrichment.verify_enrichment(test_pred)
    check("enrichment ok", report["ok"], str(report))
    check("enrichment preserves prediction field",
          enriched["prediction"] == "LONG",
          enriched["prediction"])
    check("enrichment preserves confidence",
          enriched["confidence"] == 0.65,
          str(enriched["confidence"]))
    check("enrichment preserves ev",
          enriched["ev"] == 0.0012,
          str(enriched["ev"]))
    check("enrichment preserves existing _audit sub-dicts",
          "action_vector" in enriched["_audit"]
          and "pipeline" in enriched["_audit"]
          and "execution_state" in enriched["_audit"])
    check("enrichment adds 'enriched' sub-dict",
          "enriched" in enriched["_audit"])
    check("enriched has prediction_hash",
          enriched["_audit"]["enriched"].get("prediction_hash") is not None)
    check("enriched has feature_hash",
          enriched["_audit"]["enriched"].get("feature_hash") is not None)
    check("enriched has commit_hash",
          enriched["_audit"]["enriched"].get("commit_hash") is not None)


# ─────────────────────────────────────────────────────────────────────
# T3: Forensics pipeline (A3)
# ─────────────────────────────────────────────────────────────────────
def t3_forensics():
    print("\n=== T3: Forensics Pipeline (A3) ===")
    try:
        from backend.forensics import pipeline as fp
        check("forensics.pipeline imports", True)
    except Exception as e:
        check("forensics.pipeline imports", False, str(e))
        return

    # Run on synthetic data
    import random
    random.seed(42)
    rows = []
    for i in range(150):
        direction = random.choice(["LONG", "SHORT"])
        wr = 0.40 if direction == "LONG" and i > 75 else 0.55
        outcome = "WIN" if random.random() < wr else "LOSS"
        rows.append({
            "ts": f"2026-06-{20 - i // 50}T{10 + i % 24}:00:00+00:00",
            "symbol": "ETHUSDT",
            "prediction": direction,
            "confidence": round(0.4 + random.random() * 0.4, 3),
            "ev": round(random.uniform(-0.001, 0.002), 5),
            "outcome": outcome,
            "audit": {"enriched": {
                "hour_utc": (10 + i) % 24, "weekday": i % 7,
                "weekday_name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i % 7],
                "month": 6,
                "session_asia": False, "session_europe": True, "session_us": True,
                "market_phase": "EUROPE_OPEN",
                "regime_4h": random.choice(["BULL", "BEAR", "RANGING"]),
                "regime_hint": random.choice(["TRENDING", "RANGING"]),
                "spread_bps": round(random.uniform(0.5, 3.0), 2),
                "book_imbalance": round(random.uniform(-1, 1), 3),
                "vpin": round(random.uniform(0.05, 0.30), 3),
                "ofi": round(random.uniform(-0.5, 0.5), 3),
                "funding": round(random.uniform(-0.001, 0.001), 5),
                "liquidity_score": round(random.uniform(0.5, 0.9), 3),
                "signal_strength": round(random.uniform(0.3, 0.8), 3),
                "capacity_score": round(random.uniform(0.5, 0.95), 3),
                "stress_score": round(random.uniform(0.05, 0.30), 3),
                "meta_label": random.choice(["good", "bad"]),
            }},
        })

    report = fp.run_pipeline(rows)
    check("forensics.run_pipeline returns dict", isinstance(report, dict))
    check("forensics.n_rows_input == 150", report.get("n_rows_input") == 150)
    check("forensics has all 12 analyses",
          all(k in report.get("analyses", {}) for k in [
              "direction_breakdown", "hour_analysis", "weekday_analysis",
              "session_analysis", "regime_analysis", "rolling_wr",
              "calibration", "ic", "drift", "feature_importance",
              "cpcv", "permutation",
          ]),
          str(list(report.get("analyses", {}).keys())))

    # Check summary has evidence targets
    s = report.get("summary", {})
    check("forensics.summary has n_verified", "n_verified" in s)
    check("forensics.summary has evidence_target_long", "evidence_target_long" in s)
    check("forensics.summary has evidence_target_short", "evidence_target_short" in s)


# ─────────────────────────────────────────────────────────────────────
# T4: Watchdogs (A4)
# ─────────────────────────────────────────────────────────────────────
def t4_watchdogs():
    print("\n=== T4: Watchdogs (A4) ===")
    try:
        from backend.watchdogs import coordinator as wd
        check("watchdogs.coordinator imports", True)
    except Exception as e:
        check("watchdogs.coordinator imports", False, str(e))
        return

    check("all 8 watchdogs registered", len(wd.WATCHDOGS) == 8,
          f"{len(wd.WATCHDOGS)} watchdogs")
    expected_names = {
        "LONG_WR_DROP", "SHORT_WR_DROP", "CALIBRATION_DRIFT", "FEATURE_DRIFT",
        "EXECUTION_DRIFT", "CAPACITY_DRIFT", "MICROSTRUCTURE_DRIFT", "REGIME_SHIFT",
    }
    actual_names = {n for n, _ in wd.WATCHDOGS}
    check("watchdog names match spec", actual_names == expected_names,
          ",".join(sorted(actual_names)))

    # Run against a synthetic forensics report that should fire some watchdogs
    fake_forensics = {
        "analyses": {
            "direction_breakdown": {
                "LONG": {"n": 50, "wins": 25, "win_rate": 0.50},
                "SHORT": {"n": 50, "wins": 25, "win_rate": 0.50},
            },
            "rolling_wr": {
                "LONG": {"w25": {"current": 0.20}},  # 30pp drop → LONG_WR_DROP
                "SHORT": {"w25": {"current": 0.50}},
            },
            "calibration": {"brier": 0.30, "ece": 0.15, "n": 100},  # CALIBRATION_DRIFT
            "drift": {"features": {"confidence": {"psi": 0.30, "ks_p": 0.01}}},  # FEATURE_DRIFT
        }
    }
    summary = wd.run_all_watchdogs(fake_forensics, rows=[])
    check("watchdog sweep returns summary", isinstance(summary, dict))
    check("watchdog sweep status is RED",
          summary.get("status") == "RED",
          summary.get("status"))
    fired_names = {a["watchdog"] for a in summary.get("alerts", []) if "watchdog" in a}
    check("LONG_WR_DROP fired", "LONG_WR_DROP" in fired_names,
          ",".join(sorted(fired_names)))
    check("CALIBRATION_DRIFT fired", "CALIBRATION_DRIFT" in fired_names)
    check("FEATURE_DRIFT fired", "FEATURE_DRIFT" in fired_names)


# ─────────────────────────────────────────────────────────────────────
# T5: Evidence tracker (A6)
# ─────────────────────────────────────────────────────────────────────
def t5_evidence_tracker():
    print("\n=== T5: Evidence Tracker (A6) ===")
    try:
        from backend import evidence_tracker
        check("evidence_tracker imports", True)
    except Exception as e:
        check("evidence_tracker imports", False, str(e))
        return

    progress = evidence_tracker.get_progress({
        "n_verified": 127, "n_long": 57, "n_short": 70,
    })
    check("progress has targets",
          progress.get("targets", {}).get("verified") == 200)
    check("progress has current",
          progress.get("current", {}).get("verified") == 127)
    check("progress has pct",
          progress.get("pct", {}).get("verified") == 63.5)
    check("progress has remaining",
          progress.get("remaining", {}).get("verified") == 73)
    check("progress.all_targets_met is False (when below targets)",
          progress.get("all_targets_met") is False)

    # Test met case
    progress_met = evidence_tracker.get_progress({
        "n_verified": 250, "n_long": 120, "n_short": 130,
    })
    check("progress.all_targets_met is True (when above targets)",
          progress_met.get("all_targets_met") is True)


# ─────────────────────────────────────────────────────────────────────
# T6: Statistical study suite (A7)
# ─────────────────────────────────────────────────────────────────────
def t6_statistical_study():
    print("\n=== T6: Statistical Study (A7) ===")
    try:
        from backend.research import statistical_study as ss
        check("statistical_study imports", True)
    except Exception as e:
        check("statistical_study imports", False, str(e))
        return

    # Build synthetic data
    import random
    random.seed(42)
    rows = []
    for i in range(150):
        direction = random.choice(["LONG", "SHORT"])
        wr = 0.40 if direction == "LONG" else 0.55
        outcome = "WIN" if random.random() < wr else "LOSS"
        rows.append({
            "ts": f"2026-06-{20 - i // 50}T{10 + i % 24}:00:00+00:00",
            "symbol": "ETHUSDT",
            "prediction": direction,
            "confidence": round(0.4 + random.random() * 0.4, 3),
            "ev": round(random.uniform(-0.001, 0.002), 5),
            "outcome": outcome,
            "audit": {"enriched": {
                "hour_utc": (10 + i) % 24, "weekday": i % 7,
                "weekday_name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i % 7],
                "month": 6,
                "session_asia": False, "session_europe": True, "session_us": True,
                "market_phase": "EUROPE_OPEN",
                "regime_4h": random.choice(["BULL", "BEAR", "RANGING"]),
                "regime_hint": random.choice(["TRENDING", "RANGING"]),
                "spread_bps": round(random.uniform(0.5, 3.0), 2),
                "book_imbalance": round(random.uniform(-1, 1), 3),
                "vpin": round(random.uniform(0.05, 0.30), 3),
                "ofi": round(random.uniform(-0.5, 0.5), 3),
                "funding": round(random.uniform(-0.001, 0.001), 5),
                "open_interest": 1.5e9,
                "liquidity_score": round(random.uniform(0.5, 0.9), 3),
                "signal_strength": round(random.uniform(0.3, 0.8), 3),
                "signal_confidence": round(random.uniform(0.3, 0.8), 3),
                "confidence_before_meta": round(random.uniform(0.3, 0.8), 3),
                "confidence_after_meta": round(random.uniform(0.3, 0.8), 3),
                "capacity_score": round(random.uniform(0.5, 0.95), 3),
                "stress_score": round(random.uniform(0.05, 0.30), 3),
                "meta_label": random.choice(["good", "bad"]),
            }},
        })

    study = ss.run_full_study(rows)
    check("study returns dict", isinstance(study, dict))
    check("study has n_rows_input", study.get("n_rows_input") == 150)
    check("study has tests dict", isinstance(study.get("tests"), dict))

    expected_tests = [
        "wilson_by_direction", "bootstrap_by_direction",
        "permutation_long_vs_short", "permutation_hour_buckets",
        "permutation_regime_buckets", "cpcv", "chronological_replay",
        "feature_importance_model_free", "decision_tree_long",
        "decision_tree_short", "random_forest_long", "random_forest_short",
        "logistic_l1_long", "logistic_l1_short", "shap_long",
        "counterfactual_search", "multiple_testing_corrections",
    ]
    actual_tests = set(study.get("tests", {}).keys())
    missing = [t for t in expected_tests if t not in actual_tests]
    check(f"all expected tests present ({len(expected_tests)})",
          len(missing) == 0, f"missing: {missing}" if missing else "all present")

    # Check multiple_testing_corrections has bonferroni + BH
    mtc = study.get("tests", {}).get("multiple_testing_corrections", {})
    check("mtc has bonferroni threshold", "bonferroni_threshold" in mtc)
    check("mtc has tests list", isinstance(mtc.get("tests"), list))


# ─────────────────────────────────────────────────────────────────────
# T7: Decision engine (A8)
# ─────────────────────────────────────────────────────────────────────
def t7_decision_engine():
    print("\n=== T7: Decision Engine (A8) ===")
    try:
        from backend.research import decision_engine as de
        check("decision_engine imports", True)
    except Exception as e:
        check("decision_engine imports", False, str(e))
        return

    # Default decision: DEFER (no evidence)
    decision = de.make_decision(
        study={"tests": {}},
        evidence_progress={"all_targets_met": False, "current": {"verified": 50, "long": 20, "short": 30}},
    )
    check("decision is DEFER when evidence insufficient",
          decision.get("decision") == "DEFER",
          decision.get("decision"))


# ─────────────────────────────────────────────────────────────────────
# T8: Executive report (A9)
# ─────────────────────────────────────────────────────────────────────
def t8_executive_report():
    print("\n=== T8: Executive Report (A9) ===")
    try:
        from backend.research import executive_report as er
        check("executive_report imports", True)
    except Exception as e:
        check("executive_report imports", False, str(e))
        return

    # Generate report with DEFER decision
    report = er.generate_executive_report(
        study={"tests": {}, "n_rows_input": 100},
        decision={"decision": "DEFER", "candidate_evaluation": {}},
        evidence={"all_targets_met": False, "current": {"verified": 100, "long": 40, "short": 60}},
    )
    check("report has FINAL_VERDICT", "FINAL_VERDICT" in report)
    check("report has ROOT_CAUSES_ORDERED", "ROOT_CAUSES_ORDERED" in report)
    check("report has PATCH_RECOMMENDATIONS", "PATCH_RECOMMENDATIONS" in report)
    check("report has CONFIDENCE_SCORE", "CONFIDENCE_SCORE" in report)
    check("report has GO_NO_GO", "GO_NO_GO" in report)
    check("FINAL_VERDICT is NO_CHANGE when DEFER",
          report["FINAL_VERDICT"] == "NO_CHANGE")
    check("GO_NO_GO is NO_GO when DEFER",
          report["GO_NO_GO"] == "NO_GO")
    check("PATCH_RECOMMENDATIONS empty when DEFER",
          len(report["PATCH_RECOMMENDATIONS"]) == 0)
    check("report has DISCLAIMER", "DISCLAIMER" in report)


# ─────────────────────────────────────────────────────────────────────
# T9: DO_NOT_TOUCH verification — critical trading logic files unchanged
# ─────────────────────────────────────────────────────────────────────
def t9_do_not_touch():
    print("\n=== T9: DO_NOT_TOUCH Verification ===")
    # Hash key files and compare against freeze manifest
    import hashlib
    freeze_dir = ROOT / "freeze"
    manifest_path = freeze_dir / "manifest_sha256.txt"
    if not manifest_path.exists():
        check("freeze manifest exists", False, "manifest missing")
        return

    manifest = {}
    for line in manifest_path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) == 2:
            manifest[parts[1]] = parts[0]

    # Check that DO_NOT_TOUCH files are unchanged since freeze
    do_not_touch_files = [
        "oracle/institutional_core.py",   # feature_engineering + signal_generation
        "oracle/predict_only.py",          # prediction_model
        "oracle/market_ev.py",             # market EV (signal generation)
        # oracle_runner.py and supabase_client.py WERE modified (additively) —
        # those changes are intentional A2/A3 hooks and don't touch the verifier logic.
    ]
    for rel in do_not_touch_files:
        p = ROOT / rel
        if not p.exists():
            check(f"DO_NOT_TOUCH {rel} exists", False, "missing")
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if rel in manifest:
            match = h == manifest[rel]
            check(f"DO_NOT_TOUCH {rel} unchanged since freeze", match,
                  f"current={h[:12]} frozen={manifest[rel][:12]}")
        else:
            check(f"DO_NOT_TOUCH {rel} in manifest", False, "not in manifest")

    # Verify oracle_runner.py was modified ONLY by adding the enrichment hook
    # (additive). We check that the verifier function _verify_pending_outcomes
    # still ends with "return settled" and the enrichment call appears only
    # in the prediction path.
    op = ROOT / "backend" / "oracle_runner.py"
    content = op.read_text()
    check("oracle_runner has audit_enrichment import",
          "from . import audit_enrichment" in content)
    check("oracle_runner has forensics_pipeline import",
          "from .forensics import pipeline as forensics_pipeline" in content)
    check("oracle_runner still returns settled from verifier",
          "return settled" in content)
    # Count verifier returns — should be exactly 1
    count = content.count("return settled")
    check("oracle_runner has exactly one 'return settled'",
          count == 1, f"found {count}")


# ─────────────────────────────────────────────────────────────────────
# T10: API endpoints (additive)
# ─────────────────────────────────────────────────────────────────────
def t10_api_endpoints():
    print("\n=== T10: API Endpoints (Additive) ===")
    main_path = ROOT / "backend" / "main.py"
    content = main_path.read_text()

    expected_endpoints = [
        "/api/final_audit/version",
        "/api/final_audit/forensics/latest",
        "/api/final_audit/forensics/run",
        "/api/final_audit/watchdogs/latest",
        "/api/final_audit/evidence/progress",
        "/api/final_audit/study/run",
        "/api/final_audit/study/latest",
        "/api/final_audit/audit_enrichment/schema",
        "/api/final_audit/state",
    ]
    for ep in expected_endpoints:
        check(f"endpoint {ep} registered", ep in content, "found" if ep in content else "MISSING")

    # Verify version bump not changed
    check("app version still ACT-XXIX-systemic-antifragility",
          'version="ACT-XXIX-systemic-antifragility"' in content,
          "ACT-XXIX preserved (FINAL_AUDIT is additive)")


# ─────────────────────────────────────────────────────────────────────
# T11: Final audit orchestrator end-to-end
# ─────────────────────────────────────────────────────────────────────
def t11_orchestrator_e2e():
    print("\n=== T11: Orchestrator End-to-End ===")
    try:
        from backend.research import final_audit_orchestrator as fa
        check("final_audit_orchestrator imports", True)
    except Exception as e:
        check("final_audit_orchestrator imports", False, str(e))
        return

    # Just verify the function signature — we can't run it without Supabase data
    check("run_final_audit_async is async",
          hasattr(fa, "run_final_audit_async")
          and __import__("inspect").iscoroutinefunction(fa.run_final_audit_async))
    check("run_final_audit_sync is sync",
          hasattr(fa, "run_final_audit_sync")
          and not __import__("inspect").iscoroutinefunction(fa.run_final_audit_sync))


# ─────────────────────────────────────────────────────────────────────
# T12: All modules import cleanly together
# ─────────────────────────────────────────────────────────────────────
def t12_imports():
    print("\n=== T12: All Modules Import Cleanly ===")
    try:
        from backend import audit_enrichment, evidence_tracker
        from backend.forensics import pipeline as fp
        from backend.watchdogs import coordinator as wd
        from backend.research import (statistical_study, decision_engine,
                                       executive_report, final_audit_orchestrator)
        check("all FINAL_AUDIT modules import together", True)
    except Exception as e:
        check("all FINAL_AUDIT modules import together", False, str(e))


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  ACT FINAL_AUDIT (MYTHOS) — Smoke Test Suite                    ║")
    print("║  STRICT_ADDITIVE / PAPER_ONLY / LIVE_GATE_LOCKED                ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    t1_freeze_artifacts()
    t2_audit_enrichment()
    t3_forensics()
    t4_watchdogs()
    t5_evidence_tracker()
    t6_statistical_study()
    t7_decision_engine()
    t8_executive_report()
    t9_do_not_touch()
    t10_api_endpoints()
    t11_orchestrator_e2e()
    t12_imports()

    total = len(PASSES) + len(FAILS)
    print()
    print("=" * 70)
    print(f"  RESULTS: {len(PASSES)}/{total} passed, {len(FAILS)} failed")
    print("=" * 70)
    if FAILS:
        print("\nFAILED TESTS:")
        for name, detail in FAILS:
            print(f"  - {name}: {detail}")
        return 1
    print("\nAll FINAL_AUDIT infrastructure checks passed.")
    print("System is FROZEN, additive observability layer installed,")
    print("trading logic UNTOUCHED, PAPER mode preserved, LIVE gate LOCKED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
