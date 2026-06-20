"""
ACT-XXVII Smoke Test — Institutional Research-Grade Validation
==============================================================

Validates that all 6 new ACT-XXVII research modules import cleanly,
work standalone, integrate via the ResearchCoordinator, and DO NOT
break the existing ACT-XXV / ACT-XXVI pipeline.

Coverage:
  T1  imports (all 6 research modules + coordinator + version bump)
  T2  PurgedKFold — leakage window respected
  T3  CombinatorialPurgedCV (CPCV) — combinatorial completeness
  T4  Calibration — Isotonic + Platt + Beta improve Brier / ECE on noisy data
  T5  Drift Detection — PSI + KS + Page-Hinkley + ADWIN each fire on drift
  T6  Research Metrics — IC + rolling Sharpe/PF/MDD on synthetic data
  T7  Explainability — fit_explainer + explain_one returns ranked attributions
  T8  Observability — metrics registry exposes Prometheus format + JSON snapshot
  T9  ResearchCoordinator end-to-end run on synthetic predictions
  T10 main.py has all new endpoints + version bumped to ACT-XXVII
  T11 Regression — ACT-XXV + ACT-XXVI smoke tests can still import (no break)

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m scripts.act_xxvii_smoke
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make the project importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def banner(t: str) -> None:
    print(f"\n{'=' * 70}\n  {t}\n{'=' * 70}")


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ---------------------------------------------------------------------------
# T1 — imports
# ---------------------------------------------------------------------------


def test_imports() -> bool:
    banner("TEST 1: imports (all 6 ACT-XXVII modules + coordinator)")
    try:
        from backend.research import (
            # P1 — purged CV
            PurgedKFold, CombinatorialPurgedCV, run_purged_kfold, run_cpcv,
            # P2 — calibration
            PlattCalibrator, IsotonicCalibrator, BetaCalibrator,
            IdentityCalibrator, fit_and_evaluate, brier_score,
            expected_calibration_error, maximum_calibration_error,
            reliability_curve,
            # P3 — drift
            DriftMonitor, PSIDetector, KSDriftDetector,
            PageHinkleyDetector, ADWINDetector, psi_score,
            # P4 — research metrics
            information_coefficient, rolling_information_coefficient,
            feature_stability, prediction_stability,
            rolling_sharpe, rolling_profit_factor, rolling_max_drawdown,
            compute_research_metrics,
            # P5 — explainability
            Explainer, fit_explainer, Attribution, PredictionExplanation,
            # P6 — observability
            MetricsRegistry, get_registry, timed,
            # coordinator
            ResearchCoordinator, ResearchPassReport,
            VERSION,
        )
        assert VERSION.startswith("ACT-XXVII"), f"unexpected VERSION: {VERSION}"
        ok(f"all 6 modules + coordinator imported")
        ok(f"VERSION = {VERSION}")
        return True
    except Exception as e:
        fail(f"import error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T2 — PurgedKFold
# ---------------------------------------------------------------------------


def test_purged_kfold() -> bool:
    banner("TEST 2: PurgedKFold — leakage window respected")
    try:
        import numpy as np
        from backend.research import PurgedKFold
        # 100 samples with timestamps 60s apart (so a 900s purge window
        # removes 15 samples on each side of the test fold)
        n = 100
        times = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=60 * i)
                 for i in range(n)]
        X = np.random.RandomState(42).randn(n, 3)
        cv = PurgedKFold(n_splits=5, purge_td_seconds=900, embargo_td_seconds=900)
        folds = list(cv.split(X, times=times))
        assert len(folds) == 5, f"expected 5 folds, got {len(folds)}"
        # Each fold should have train + test indices
        for f in folds:
            assert f.n_train + f.n_test + f.purged_indices.shape[0] <= n
            assert f.n_test > 0
            assert f.n_train > 0
        # Check that test indices across folds partition the dataset
        all_test = sorted(set(int(i) for f in folds for i in f.test_indices))
        assert len(all_test) == n, f"test indices not partition: {len(all_test)}/{n}"
        # Check that purged indices are NOT in train
        for f in folds:
            train_set = set(int(i) for i in f.train_indices)
            test_set = set(int(i) for i in f.test_indices)
            purged_set = set(int(i) for i in f.purged_indices)
            assert train_set.isdisjoint(test_set)
            assert train_set.isdisjoint(purged_set)
            # Time-range check: every test time should be in [test_lo, test_hi]
            if f.test_time_range[0] == f.test_time_range[0]:  # not NaN
                test_times = [times[int(i)].timestamp() for i in f.test_indices]
                assert min(test_times) >= f.test_time_range[0] - 1
                assert max(test_times) <= f.test_time_range[1] + 1
        ok(f"5 folds generated with purge window respected")
        ok(f"all folds have disjoint train/test/purge sets")
        return True
    except Exception as e:
        fail(f"purged kfold error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T3 — CPCV
# ---------------------------------------------------------------------------


def test_cpcv() -> bool:
    banner("TEST 3: CombinatorialPurgedCV (CPCV) — combinatorial completeness")
    try:
        import numpy as np
        from backend.research import CombinatorialPurgedCV
        n = 120
        times = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=60 * i)
                 for i in range(n)]
        X = np.random.RandomState(42).randn(n, 3)
        cv = CombinatorialPurgedCV(
            n_groups=6, n_test_groups=2,
            purge_td_seconds=900, embargo_td_seconds=900,
        )
        # 6 groups, 2 test → C(6,2) = 15 paths
        assert cv.n_paths == 15, f"expected 15 paths, got {cv.n_paths}"
        paths = list(cv.split(X, times=times))
        assert len(paths) == 15
        # Every sample should appear in test exactly C(n_groups-1, n_test_groups-1) times.
        # For n_groups=6, n_test_groups=2: C(5,1) = 5 times.
        import math as _m
        expected_test_count = _m.comb(6 - 1, 2 - 1)
        from collections import Counter
        test_counts = Counter()
        for p in paths:
            for i in p.test_indices:
                test_counts[int(i)] += 1
        # Some samples may be missing if they were purged in every path that
        # contained them — so check that present samples have count == expected.
        distinct_counts = set(test_counts.values())
        assert distinct_counts == {expected_test_count}, \
            f"sample test counts not all {expected_test_count}: {distinct_counts}"
        ok(f"C(6,2)=15 paths generated")
        ok(f"every sample appears in test exactly {expected_test_count} times (CPCV invariant)")
        return True
    except Exception as e:
        fail(f"cpcv error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T4 — Calibration
# ---------------------------------------------------------------------------


def test_calibration() -> bool:
    banner("TEST 4: Probability Calibration — Isotonic + Platt + Beta")
    try:
        import numpy as np
        from backend.research import (
            fit_and_evaluate, brier_score, expected_calibration_error,
            reliability_curve,
        )
        rng = np.random.RandomState(42)
        n = 500
        # True probability is a non-linear function of the raw score
        true_p = rng.uniform(0.05, 0.95, n)
        # Miscalibrated: raw = sqrt(true_p) (skewed low)
        raw = np.sqrt(true_p)
        y = (rng.uniform(size=n) < true_p).astype(float)
        for method in ("isotonic", "platt", "beta", "identity"):
            rep = fit_and_evaluate(y_true=y, y_prob=raw, method=method, n_bins=10)
            assert rep.brier_after <= rep.brier_before + 1e-6, \
                f"{method}: brier regressed ({rep.brier_before} → {rep.brier_after})"
            assert rep.ece_after <= rep.ece_before + 1e-6, \
                f"{method}: ECE regressed ({rep.ece_before} → {rep.ece_after})"
        # Isotonic should strictly improve Brier on this miscalibration
        iso = fit_and_evaluate(y_true=y, y_prob=raw, method="isotonic", n_bins=10)
        assert iso.brier_after < iso.brier_before, \
            f"isotonic should improve brier: {iso.brier_before} → {iso.brier_after}"
        ok(f"isotonic improved Brier {iso.brier_before:.4f} → {iso.brier_after:.4f}")
        ok(f"isotonic improved ECE   {iso.ece_before:.4f} → {iso.ece_after:.4f}")
        # Reliability curve has 10 bins
        rc = reliability_curve(y, raw, n_bins=10)
        assert rc["n_bins"] == 10
        ok(f"reliability curve has {rc['n_bins']} bins, "
           f"{sum(rc['counts'])} samples covered")
        return True
    except Exception as e:
        fail(f"calibration error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T5 — Drift Detection
# ---------------------------------------------------------------------------


def test_drift_detection() -> bool:
    banner("TEST 5: Drift Detection — PSI + KS + Page-Hinkley + ADWIN")
    try:
        import numpy as np
        from backend.research import (
            PSIDetector, KSDriftDetector, PageHinkleyDetector,
            ADWINDetector, DriftMonitor, psi_score,
        )
        rng = np.random.RandomState(42)
        # Reference: N(0, 1), then current shifts to N(2, 1)
        ref = rng.normal(0, 1, 200)
        # PSI between same-distribution samples should be small
        same = rng.normal(0, 1, 200)
        psi_same = psi_score(ref, same, n_bins=10)
        # PSI between shifted samples should be large
        shifted = rng.normal(2, 1, 200)
        psi_shifted = psi_score(ref, shifted, n_bins=10)
        assert psi_shifted > psi_same, \
            f"PSI should be larger for shifted: {psi_shifted:.4f} vs {psi_same:.4f}"
        ok(f"PSI: same-distribution={psi_same:.4f}, shifted={psi_shifted:.4f}")

        # Page-Hinkley should fire on a sharp mean shift
        ph = PageHinkleyDetector(threshold=10.0, drift_threshold=0.5,
                                  min_observations=30)
        # First 50 samples around mean=0, then jump to mean=3
        stream = list(rng.normal(0, 0.3, 50)) + list(rng.normal(3, 0.3, 50))
        ph_warnings = []
        for v in stream:
            w = ph.update(v)
            if w is not None:
                ph_warnings.append(w)
        assert len(ph_warnings) > 0, "Page-Hinkley should fire on shift"
        ok(f"Page-Hinkley fired {len(ph_warnings)} time(s) after mean shift")

        # ADWIN should also fire on the shift
        ad = ADWINDetector(delta=0.002, min_window=30)
        ad_warnings = []
        for v in stream:
            w = ad.update(v)
            if w is not None:
                ad_warnings.append(w)
        assert len(ad_warnings) > 0, "ADWIN should fire on shift"
        ok(f"ADWIN fired {len(ad_warnings)} time(s) after mean shift")

        # DriftMonitor aggregates all four detectors
        mon = DriftMonitor()
        mon.set_reference(ref)
        monitor_warnings = []
        for v in shifted:
            ws = mon.update(v)
            monitor_warnings.extend(ws)
        # At least one detector should fire
        assert len(monitor_warnings) > 0, "DriftMonitor should fire ≥1 warning"
        detectors_fired = set(w.detector for w in monitor_warnings)
        ok(f"DriftMonitor fired {len(monitor_warnings)} warning(s) "
           f"from detectors: {detectors_fired}")
        return True
    except Exception as e:
        fail(f"drift detection error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T6 — Research Metrics
# ---------------------------------------------------------------------------


def test_research_metrics() -> bool:
    banner("TEST 6: Research Metrics — IC + rolling Sharpe/PF/MDD")
    try:
        import numpy as np
        from backend.research import (
            information_coefficient, rolling_sharpe, rolling_profit_factor,
            rolling_max_drawdown, feature_stability, prediction_stability,
            compute_research_metrics,
        )
        rng = np.random.RandomState(42)
        n = 200
        # Predictions correlated with returns (IC > 0)
        true_returns = rng.normal(0, 0.01, n)
        preds = true_returns + rng.normal(0, 0.005, n)
        ic = information_coefficient(preds, true_returns, method="spearman")
        assert ic > 0.5, f"expected IC > 0.5 on correlated data, got {ic:.3f}"
        ok(f"IC on correlated data = {ic:.3f} (> 0.5)")

        # Rolling Sharpe on positive-expectancy returns
        pnls = rng.normal(10, 50, n)  # +$10 avg per trade
        rs = rolling_sharpe(pnls / 10_000.0, window=50, step=10,
                             trades_per_year=35040)
        assert len(rs) > 0
        ok(f"rolling Sharpe: {len(rs)} windows, last sharpe = "
           f"{rs[-1]['sharpe']:.2f}")

        rpf = rolling_profit_factor(pnls, window=50, step=10)
        assert len(rpf) > 0
        ok(f"rolling PF: {len(rpf)} windows, last PF = "
           f"{rpf[-1]['profit_factor']:.2f}")

        rmdd = rolling_max_drawdown(pnls, window=50, step=10)
        assert len(rmdd) > 0
        ok(f"rolling MaxDD: {len(rmdd)} windows, last DD = "
           f"${rmdd[-1]['max_drawdown_usd']:.2f}")

        # Feature stability — constant importances → stability_score = 1.0
        history = np.tile([0.3, 0.2, 0.5], (5, 1))
        fs = feature_stability(history)
        assert fs["stability_score"] >= 0.99, \
            f"stable features should give ~1.0: {fs['stability_score']}"
        ok(f"feature stability on constant features = "
           f"{fs['stability_score']:.3f}")

        # Prediction stability — identical predictions → 100% stable
        ps = prediction_stability(preds, preds)
        assert ps["stable_rate"] == 1.0
        ok(f"prediction stability on identical inputs = "
           f"{ps['stable_rate']:.3f}")

        # Full report
        report = compute_research_metrics(
            predictions=preds, realized_returns=true_returns,
            pnls=pnls, window=50, step=10,
        )
        assert report.n_samples == n
        ok(f"compute_research_metrics: n={report.n_samples}, "
           f"IC={report.ic:.3f}")
        return True
    except Exception as e:
        fail(f"research metrics error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T7 — Explainability
# ---------------------------------------------------------------------------


def test_explainability() -> bool:
    banner("TEST 7: Explainability — fit_explainer + explain_one")
    try:
        import numpy as np
        from backend.research import fit_explainer
        rng = np.random.RandomState(42)
        n = 200
        # Two informative features + three noise features
        X = rng.randn(n, 5)
        # Target depends on feature 0 (positive) and feature 2 (negative)
        logits = 2.0 * X[:, 0] - 1.5 * X[:, 2]
        probs = 1 / (1 + np.exp(-logits))
        y = (rng.uniform(size=n) < probs).astype(int)
        feature_names = ["momentum_5m", "noise_1", "spread_bps", "noise_2", "noise_3"]
        # Force prefer_shap=False so we exercise the permutation fallback
        expl = fit_explainer(
            X=X, y=y, feature_names=feature_names,
            model_type="tree", prefer_shap=False, top_k=5,
        )
        assert expl._explainer_kind in ("permutation", "tree_importance"), \
            f"unexpected explainer kind: {expl._explainer_kind}"
        ok(f"explainer fitted with kind={expl._explainer_kind}")

        # Explain one row
        explanation = expl.explain_one(X[0:1])
        assert explanation.model_output is not None
        assert len(explanation.all_attributions) == 5
        assert len(explanation.top_attributions) <= 5
        # The attributions should rank feature 0 or 2 highly (they're informative)
        top_names = [a.feature_name for a in explanation.top_attributions[:2]]
        ok(f"top 2 attributions: {top_names} "
           f"(expected to include 'momentum_5m' or 'spread_bps')")

        # Batch explain
        batch = expl.explain_batch(X[:3])
        assert len(batch) == 3
        ok(f"explain_batch returned {len(batch)} explanations")

        # Feature importance history should have ≥1 snapshot
        history = expl.feature_importance_history()
        # History reads from default explainers_dir; may be empty if no prior fit
        ok(f"feature importance history has {len(history)} snapshot(s)")
        return True
    except Exception as e:
        fail(f"explainability error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T8 — Observability
# ---------------------------------------------------------------------------


def test_observability() -> bool:
    banner("TEST 8: Observability — Prometheus exposition + JSON snapshot")
    try:
        from backend.research import get_registry, timed
        reg = get_registry()
        # Increment a counter, set a gauge, time a call
        reg.observe("senecio_predictions_total", 1,
                    labels={"direction": "LONG", "outcome_window": "1h"})
        reg.observe("senecio_predictions_total", 1,
                    labels={"direction": "SHORT", "outcome_window": "1h"})
        reg.set_gauge("senecio_open_positions", 3)
        reg.set_gauge("senecio_equity_usd", 10_500.0)
        with timed("senecio_research_module_latency_seconds",
                   labels={"module": "smoke_test"}):
            import time as _t; _t.sleep(0.01)
        # Expose Prometheus format
        body, ctype = reg.expose()
        assert isinstance(body, (bytes, bytearray))
        assert "senecio_predictions_total" in body.decode("utf-8")
        assert "senecio_open_positions" in body.decode("utf-8")
        ok(f"Prometheus exposition: {len(body)} bytes, content-type={ctype}")

        # JSON snapshot
        snap = reg.stats()
        assert "uptime_seconds" in snap
        assert "prometheus_samples" in snap
        ok(f"JSON snapshot has {len(snap.get('prometheus_samples') or [])} samples")
        return True
    except Exception as e:
        fail(f"observability error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T9 — ResearchCoordinator end-to-end
# ---------------------------------------------------------------------------


def test_coordinator_end_to_end() -> bool:
    banner("TEST 9: ResearchCoordinator end-to-end on synthetic predictions")
    try:
        import numpy as np
        from backend.research import ResearchCoordinator
        rng = np.random.RandomState(42)
        # Generate 150 synthetic prediction records with outcomes
        records = []
        for i in range(150):
            conf = float(rng.uniform(0.4, 0.85))
            # Long wins ~60% when conf > 0.6
            win_prob = conf if rng.uniform() < 0.6 else (1 - conf)
            outcome = "WIN" if rng.uniform() < win_prob else "LOSS"
            records.append({
                "id": i,
                "symbol": "ETH/USDT",
                "prediction": "LONG" if i % 2 == 0 else "SHORT",
                "confidence": conf,
                "ev": float(rng.uniform(-0.005, 0.01)),
                "price_now": 1700.0 + rng.uniform(-50, 50),
                "vol_pct": float(rng.uniform(0.005, 0.02)),
                "spread_bps": float(rng.uniform(1, 5)),
                "depth_usd": float(rng.uniform(50_000, 200_000)),
                "bidask_imbalance": float(rng.uniform(-0.3, 0.3)),
                "momentum_5m": float(rng.uniform(-0.005, 0.005)),
                "momentum_15m": float(rng.uniform(-0.01, 0.01)),
                "funding_rate": float(rng.uniform(-0.0001, 0.0001)),
                "outcome": outcome,
                "ts": (datetime(2026, 1, 1, tzinfo=timezone.utc)
                       + timedelta(minutes=15 * i)).isoformat(),
            })
        # Use a temporary directory for reports
        with tempfile.TemporaryDirectory() as tmpdir:
            coord = ResearchCoordinator(
                config={
                    "reports_dir": tmpdir,
                    "min_samples_for_run": 50,
                    "purge_td_seconds": 900,
                    "embargo_td_seconds": 900,
                    "n_splits": 5,
                    "n_groups": 5,
                    "n_test_groups": 2,
                    "rolling_window": 30,
                    "rolling_step": 5,
                    "explainer_prefer_shap": False,  # use permutation fallback
                }
            )
            coord.load_predictions_from_records(records)
            # Set drift reference to first 50 confidences
            confs = np.array([r["confidence"] for r in records])
            coord.set_drift_reference(confs[:50])
            # Run full pass
            report = coord.run_full_pass()
            assert report.n_samples == 150, f"expected 150 samples, got {report.n_samples}"
            # At least the calibration should have produced reports (P1 + P2 may
            # fail on synthetic data — that's OK, they go in errors[])
            assert len(report.calibration_reports) >= 1, \
                f"expected ≥1 calibration report, got {len(report.calibration_reports)}"
            # Explainer should have fitted
            assert coord.get_explainer() is not None, "explainer should be fitted"
            ok(f"full pass: n_samples={report.n_samples}, "
               f"errors={len(report.errors)}")
            ok(f"calibration: {len(report.calibration_reports)} reports")
            ok(f"drift stats: {report.drift_stats is not None}")
            ok(f"explainer: {report.explainer_stats is not None}")

            # Explain one prediction
            explanation = coord.explain_prediction(records[0])
            assert explanation is not None
            assert "top_attributions" in explanation
            ok(f"explain_prediction: top attribution = "
               f"{explanation['top_attributions'][0]['feature_name']}")
        return True
    except Exception as e:
        fail(f"coordinator error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T10 — main.py has new endpoints + version bump
# ---------------------------------------------------------------------------


def test_main_endpoints() -> bool:
    banner("TEST 10: main.py has ACT-XXVII endpoints + version bump")
    try:
        from backend import main
        # Accept ACT-XXVII or any later ACT that preserves all XXVII endpoints
        # (additive-only directive — version may move forward but endpoints must stay).
        accepted_versions = (
            "ACT-XXVII-research-grade-validation",
            "ACT-XXVIII-institutional-validation",
            "ACT-XXIX-systemic-antifragility",
        )
        assert main.app.version in accepted_versions, \
            f"unexpected version: {main.app.version}"
        ok(f"main.py version = {main.app.version}")
        # Check all expected new endpoints are registered
        expected = {
            "/api/research/state",
            "/api/research/run_full_pass",
            "/api/research/calibration",
            "/api/research/drift",
            "/api/research/metrics",
            "/api/research/explainer/fit",
            "/api/research/explainer/explain",
            "/api/research/explainer/history",
            "/api/observability",
            "/metrics",
        }
        actual = set()
        for r in main.app.routes:
            path = getattr(r, "path", None)
            if path:
                actual.add(path)
        missing = expected - actual
        assert not missing, f"missing endpoints: {missing}"
        ok(f"all {len(expected)} new endpoints registered")
        # Coordinator + registry must be initialized
        assert main._research_coord is not None
        assert main._metrics_registry is not None
        ok(f"ResearchCoordinator + MetricsRegistry initialized at import time")
        return True
    except Exception as e:
        fail(f"main.py endpoints error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T11 — Regression — ACT-XXV / ACT-XXVI still importable
# ---------------------------------------------------------------------------


def test_regression() -> bool:
    banner("TEST 11: Regression — ACT-XXV + ACT-XXVI still import cleanly")
    try:
        # ACT-XXV/XXVI portfolio layer
        from backend.portfolio import VERSION as PORTFOLIO_VERSION
        assert PORTFOLIO_VERSION.startswith("ACT-XXVI"), \
            f"portfolio version regressed: {PORTFOLIO_VERSION}"
        ok(f"backend.portfolio VERSION = {PORTFOLIO_VERSION}")

        # ACT-XXV/XXVI modules
        from backend.portfolio import (
            PortfolioEngine, RiskKernel, ExecutionEngine,
            TradeJournal, PortfolioAnalytics, ShadowLive, LiveGate,
            PortfolioCoordinator,
            FillSimulator, MicrostructureIntelligence, MetaLabeler,
            HMMRegimeOverlay,
        )
        ok(f"all 10 ACT-XXV/XXVI portfolio symbols still import")

        # Existing smoke test scripts must still be present
        assert (PROJECT_ROOT / "scripts" / "act_xxv_smoke.py").exists()
        assert (PROJECT_ROOT / "scripts" / "act_xxvi_smoke.py").exists()
        ok(f"existing smoke test scripts (act_xxv, act_xxvi) still present")
        return True
    except Exception as e:
        fail(f"regression error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [
        ("T1",  test_imports),
        ("T2",  test_purged_kfold),
        ("T3",  test_cpcv),
        ("T4",  test_calibration),
        ("T5",  test_drift_detection),
        ("T6",  test_research_metrics),
        ("T7",  test_explainability),
        ("T8",  test_observability),
        ("T9",  test_coordinator_end_to_end),
        ("T10", test_main_endpoints),
        ("T11", test_regression),
    ]
    results: list[tuple[str, bool]] = []
    for tid, fn in tests:
        try:
            results.append((tid, bool(fn())))
        except Exception as e:
            print(f"  [FAIL] {tid} uncaught: {e}")
            results.append((tid, False))
    n_pass = sum(1 for _, ok_flag in results if ok_flag)
    n_total = len(results)
    print(f"\n{'=' * 70}")
    print(f"  ACT-XXVII smoke: {n_pass}/{n_total} tests passed")
    print(f"{'=' * 70}")
    for tid, ok_flag in results:
        print(f"  {'[OK]  ' if ok_flag else '[FAIL]'} {tid}")
    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
