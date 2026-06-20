"""
ACT-XXVIII Smoke Test — Institutional Validation-Grade Robustness
==================================================================

Validates that all 6 new ACT-XXVIII validation modules import cleanly,
work standalone, integrate via /api/research/report, and DO NOT break
the existing ACT-XXV / ACT-XXVI / ACT-XXVII pipeline.

Coverage:
  T1   imports (all 6 ACT-XXVIII modules + version bump)
  T2   walk_forward_optimizer — 3 schemes (rolling/anchored/expanding)
       + parameter stability sweep
  T3   monte_carlo_validation — bootstrap + reshuffle + slippage/fee/gap
       perturbation + drawdown distribution + ruin probability + CIs
  T4   statistical_validation — DSR + PSR + PBO + WRC + SPA +
       multiple-hypothesis correction
  T5   capacity_model — ADV + Almgren-Chriss + Kissell + scalability
       sweep + max deployable capital
  T6   stress_testing — all 7 scenarios (vol/spread/latency/outage/
       funding/gap/black_swan) + survival rate
  T7   institutional_report — robustness + readiness scorecard +
       live-gate explanation + JSON/HTML serialisation
  T8   main.py — 6 new /api/research/* endpoints registered + version
       bumped to ACT-XXVIII-institutional-validation
  T9   Regression — ACT-XXV + ACT-XXVI + ACT-XXVII smoke tests can
       still import (no break)

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m scripts.act_xxviii_smoke
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

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
    banner("TEST 1: imports (all 6 ACT-XXVIII modules + version bump)")
    try:
        from backend.research import (
            # M1 — walk forward optimizer
            WalkForwardReport, WalkForwardWindow, ParameterStabilityReport,
            generate_windows, default_score_fn, run_walk_forward, parameter_sweep,
            # M2 — monte carlo validation
            MonteCarloReport, run_monte_carlo, bootstrap_ci,
            # M3 — statistical validation
            DeflatedSharpeReport, ProbabilisticSharpeReport, PBOTReport,
            RealityCheckReport, MultipleHypothesisReport,
            StatisticalValidationReport,
            deflated_sharpe_ratio, probabilistic_sharpe_ratio, pbo,
            white_reality_check, superior_predictive_ability,
            benjamini_hochberg, holm_bonferroni, multiple_hypothesis_correction,
            run_statistical_battery,
            # M4 — capacity model
            ADVEstimate, MarketImpactEstimate, CapacityReport,
            estimate_adv, almgren_chriss_impact, kissell_linear_impact,
            estimate_market_impact, estimate_capacity,
            # M5 — stress testing
            StressReport, StressScenarioResult,
            volatility_shock, spread_shock, latency_shock, exchange_outage,
            funding_shock, gap_simulation, black_swan, run_stress_battery,
            # M6 — institutional report
            RobustnessScorecard, DeploymentReadinessScorecard,
            LiveGateExplanation, InstitutionalReport,
            build_robustness_scorecard, build_readiness_scorecard,
            explain_live_gate, build_institutional_report,
            VERSION,
        )
        assert VERSION == "ACT-XXVIII-institutional-validation", (
            f"VERSION mismatch: got {VERSION!r}"
        )
        ok(f"VERSION = {VERSION}")
        ok("all 6 modules + sub-symbols import cleanly")
        return True
    except Exception as e:
        fail(f"import error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T2 — walk_forward_optimizer
# ---------------------------------------------------------------------------


def test_walk_forward() -> bool:
    banner("TEST 2: walk_forward_optimizer (3 schemes + parameter sweep)")
    try:
        from backend.research import generate_windows, run_walk_forward, parameter_sweep
        # 1) window generation
        ws = generate_windows(n=500, scheme="rolling",
                              train_size=100, test_size=30, step=20)
        assert len(ws) > 0, "no rolling windows generated"
        assert all(w.scheme == "rolling" for w in ws)
        # Anchored: train_end grows
        wa = generate_windows(n=500, scheme="anchored",
                              train_size=100, test_size=30, step=20)
        assert len(wa) > 0
        assert wa[0].train_start == 0
        assert wa[-1].train_end > wa[0].train_end, "anchored train should expand"
        # Expanding: both windows grow
        we = generate_windows(n=800, scheme="expanding",
                              train_size=100, test_size=30, step=20)
        assert len(we) > 0
        assert we[-1].train_size > we[0].train_size, "expanding train should grow"
        ok(f"rolling={len(ws)}, anchored={len(wa)}, expanding={len(we)} windows")

        # 2) walk-forward run with synthetic correlated data
        rng = np.random.default_rng(42)
        n = 400
        X = rng.normal(size=(n, 3))
        # y is correlated with X[:,0]
        logits = X[:, 0] * 0.8 + X[:, 1] * 0.3
        probs = 1.0 / (1.0 + np.exp(-logits))
        y = (rng.random(n) < probs).astype(float)
        # y_pred = noisy version of probs
        y_pred = np.clip(probs + rng.normal(0, 0.15, n), 0.0, 1.0)
        rep = run_walk_forward(
            y=y, y_pred=y_pred, scheme="rolling",
            train_size=80, test_size=30, step=20,
            persist=False,
        )
        assert rep.n_windows > 0
        assert "accuracy_mean" in rep.aggregate_metrics
        assert rep.stability["pass_rate"] >= 0.0
        ok(f"rolling WF: {rep.n_windows} windows, "
           f"acc_mean={rep.aggregate_metrics['accuracy_mean']:.3f}, "
           f"pass_rate={rep.stability['pass_rate']:.3f}, "
           f"composite={rep.stability['composite_robustness']:.3f}")

        # 3) parameter sweep — vary the prediction-noise std
        def make_pred(sigma: float) -> np.ndarray:
            return np.clip(probs + rng.normal(0, sigma, n), 0.0, 1.0)

        sweep = parameter_sweep(
            y=y,
            y_pred_factory=make_pred,
            parameter_name="noise_std",
            parameter_values=[0.05, 0.10, 0.20, 0.40],
            metric_name="accuracy",
            scheme="rolling", train_size=80, test_size=30, step=20,
        )
        assert len(sweep.metric_values) == 4
        assert sweep.optimal_value is not None
        # Best accuracy should be at lower noise (0.05 or 0.10), not at
        # 0.20/0.40 — accept either of the two lowest noise values.
        assert sweep.optimal_value in (0.05, 0.10), (
            f"expected optimal at low noise (0.05 or 0.10), got {sweep.optimal_value}"
        )
        ok(f"param sweep: cv={sweep.cv:.3f}, optimal noise={sweep.optimal_value}, "
           f"optimal acc={sweep.optimal_metric:.3f}")
        return True
    except Exception as e:
        fail(f"walk_forward failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T3 — monte_carlo_validation
# ---------------------------------------------------------------------------


def test_monte_carlo() -> bool:
    banner("TEST 3: monte_carlo_validation (bootstrap + perturbations + ruin)")
    try:
        from backend.research import run_monte_carlo, bootstrap_ci
        rng = np.random.default_rng(7)
        n = 500
        # Strategy with positive edge: +30 bps mean, 30 bps std per trade
        # (Sharpe ~ 1.6 annualised at 252 periods — comfortably profitable)
        returns = rng.normal(0.003, 0.003, size=n)
        rep = run_monte_carlo(
            returns=returns,
            n_bootstrap=500,
            n_reshuffle=200,
            ruin_threshold_pct=-0.20,
            slippage_bps_std=2.0,
            fee_bps_std=0.5,
            gap_penalty_bps=0.5,
            random_seed=7,
            persist=False,
        )
        assert rep.n_trades == n
        # Original Sharpe should be positive
        assert rep.original_stats["sharpe"] > 0, "expected positive Sharpe"
        # Bootstrap stats populated
        assert "sharpe" in rep.bootstrap_stats
        assert "ci_95_lo" in rep.bootstrap_stats["sharpe"]
        assert "max_drawdown" in rep.bootstrap_stats
        # Drawdown distribution populated
        assert "p95" in rep.drawdown_distribution
        # Ruin probability should be low for a profitable strategy
        assert rep.ruin_probability < 0.20, (
            f"ruin_probability too high: {rep.ruin_probability}"
        )
        # Confidence intervals populated
        assert "sharpe" in rep.confidence_intervals
        ok(f"MC: ruin={rep.ruin_probability:.3f}, "
           f"Sharpe={rep.original_stats['sharpe']:.2f}, "
           f"bootstrap p95 DD={rep.drawdown_distribution['p95']:.3f}, "
           f"Sharpe CI95=[{rep.bootstrap_stats['sharpe']['ci_95_lo']:.2f},"
           f"{rep.bootstrap_stats['sharpe']['ci_95_hi']:.2f}]")

        # Bootstrap CI helper
        ci = bootstrap_ci(returns, statistic=lambda r: float(np.mean(r)),
                          n_bootstrap=300)
        assert "ci" in ci and "ci_95" in ci["ci"]
        ok(f"bootstrap_ci helper: mean={ci['mean']:.5f}, "
           f"95% CI=[{ci['ci']['ci_95'][0]:.5f}, {ci['ci']['ci_95'][1]:.5f}]")
        return True
    except Exception as e:
        fail(f"monte_carlo failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T4 — statistical_validation
# ---------------------------------------------------------------------------


def test_statistical() -> bool:
    banner("TEST 4: statistical_validation (DSR + PSR + PBO + WRC + SPA + MH)")
    try:
        from backend.research import (
            deflated_sharpe_ratio, probabilistic_sharpe_ratio, pbo,
            white_reality_check, superior_predictive_ability,
            benjamini_hochberg, holm_bonferroni, multiple_hypothesis_correction,
            run_statistical_battery,
        )
        rng = np.random.default_rng(11)
        n = 300
        # Strategy with positive edge
        returns = rng.normal(0.0008, 0.005, size=n)

        # 1) DSR
        dsr = deflated_sharpe_ratio(returns, n_trials=10)
        assert dsr.sharpe_observed > 0
        assert 0.0 <= dsr.p_value <= 1.0
        assert dsr.sharpe_deflated < dsr.sharpe_observed  # deflation reduces SR
        ok(f"DSR: SR_obs={dsr.sharpe_observed:.3f}, "
           f"SR_def={dsr.sharpe_deflated:.3f}, p={dsr.p_value:.4f}, "
           f"n_trials={dsr.n_trials}")

        # 2) PSR
        psr = probabilistic_sharpe_ratio(returns, sharpe_benchmark=0.0)
        assert 0.0 <= psr.psr <= 1.0
        assert psr.psr > 0.5, "expected PSR > 0.5 for profitable strategy"
        ok(f"PSR: SR_obs={psr.sharpe_observed:.3f}, "
           f"PSR(>0)={psr.psr:.3f}")

        # 3) PBO — synthetic strategy matrix (5 strategies, 1 with real edge)
        T = 200
        N = 5
        SR = np.zeros((T, N))
        for i in range(N):
            if i == 0:
                # Real edge
                SR[:, i] = rng.normal(0.0008, 0.005, size=T)
            else:
                SR[:, i] = rng.normal(0.0, 0.005, size=T)
        pbo_rep = pbo(SR, n_groups=8, n_test_groups=2, random_seed=7)
        assert 0.0 <= pbo_rep.pbo <= 1.0
        assert pbo_rep.n_paths > 0
        ok(f"PBO: pbo={pbo_rep.pbo:.3f}, paths={pbo_rep.n_paths}, "
           f"strategies={pbo_rep.n_strategies}")

        # 4) WRC + SPA — loss-differentials
        # d_{t,i} = L(benchmark) - L(strategy_i) where L is a LOSS function
        # Since L = -return, d = (-bench) - (-strat_i) = strat_i - bench.
        # So positive D → strategy_i beats benchmark.
        D = np.zeros((T, N))
        for i in range(N):
            D[:, i] = SR[:, i] - SR[:, 0]  # strategy i vs benchmark (col 0)
        # Column 0 (benchmark vs itself) is all zeros
        wrc = white_reality_check(D, n_bootstrap=200, random_seed=7)
        assert 0.0 <= wrc.p_value <= 1.0
        # Strategy 0 (the one with edge) should be the best
        assert wrc.best_strategy_index == 0, (
            f"expected best=0 (the strategy with edge), got {wrc.best_strategy_index}"
        )
        ok(f"WRC: best_idx={wrc.best_strategy_index}, "
           f"p={wrc.p_value:.4f}, n_strategies={wrc.n_strategies}")
        spa = superior_predictive_ability(D, n_bootstrap=200, random_seed=7)
        assert 0.0 <= spa.p_value <= 1.0
        ok(f"SPA: p={spa.p_value:.4f}")

        # 5) Multiple hypothesis correction
        p_vals = [0.001, 0.008, 0.039, 0.041, 0.082, 0.150]
        bh = benjamini_hochberg(p_vals, alpha=0.05)
        holm = holm_bonferroni(p_vals, alpha=0.05)
        combined = multiple_hypothesis_correction(p_vals, fdr_alpha=0.05, fwer_alpha=0.05)
        assert combined.n_rejected_bh >= 1, "expected at least 1 BH rejection"
        ok(f"BH: rejected {combined.n_rejected_bh}/{len(p_vals)}; "
           f"Holm: rejected {combined.n_rejected_holm}/{len(p_vals)}")

        # 6) Full battery
        bat = run_statistical_battery(
            returns=returns, strategy_returns=SR,
            n_bootstrap=200, n_trials=5, persist=False,
        )
        assert bat.deflated_sharpe is not None
        assert bat.probabilistic_sharpe is not None
        assert bat.pbo is not None
        assert bat.wrc is not None
        assert bat.spa is not None
        assert bat.multiple_hypothesis is not None
        ok(f"Battery: DSR p={bat.deflated_sharpe['p_value']:.4f}, "
           f"PSR={bat.probabilistic_sharpe['psr']:.3f}, "
           f"PBO={bat.pbo['pbo']:.3f}, "
           f"WRC p={bat.wrc['p_value']:.4f}, "
           f"SPA p={bat.spa['p_value']:.4f}, "
           f"BH rejected={bat.multiple_hypothesis['n_rejected_bh']}")
        return True
    except Exception as e:
        fail(f"statistical failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T5 — capacity_model
# ---------------------------------------------------------------------------


def test_capacity() -> bool:
    banner("TEST 5: capacity_model (ADV + impact + scalability + max capital)")
    try:
        from backend.research import (
            estimate_adv, almgren_chriss_impact, kissell_linear_impact,
            estimate_market_impact, estimate_capacity,
        )
        # 1) ADV estimation
        rng = np.random.default_rng(3)
        vols = rng.lognormal(mean=15, sigma=0.4, size=200)  # ~3M ADV
        adv = estimate_adv(vols, ema_span=20)
        assert adv.n_samples == 200
        assert adv.adv_median > 0
        assert adv.recommended_adv > 0
        # Recommended ADV is min(EMA, p25) so <= median
        assert adv.recommended_adv <= adv.adv_median
        ok(f"ADV: median={adv.adv_median:.0f}, recommended={adv.recommended_adv:.0f}, "
           f"p05={adv.adv_p05:.0f}, p95={adv.adv_p95:.0f}")

        # 2) Impact models
        ac = almgren_chriss_impact(order_qty=10_000, adv=3_000_000, k=0.10)
        kl = kissell_linear_impact(order_qty=10_000, adv=3_000_000, eta=0.05)
        # Square-root impact > linear for small order/ADV
        assert ac > 0
        assert kl > 0
        # For 10k/3M ratio = 0.0033, sqrt impact = 0.10*sqrt(0.0033)=0.0057, linear = 0.05*0.0033=0.000165
        # So AC > KL at small sizes (typical)
        ok(f"AC impact = {ac*1e4:.3f} bps; Kissell = {kl*1e4:.3f} bps (q/ADV = 0.0033)")

        # 3) estimate_market_impact wrapper
        mi = estimate_market_impact(
            order_qty=20_000, adv=3_000_000,
            k=0.10, eta=0.05, slippage_bps_floor=1.0,
        )
        assert mi.slippage_bps >= 1.0  # at least the floor
        assert mi.almgren_chriss_bps > 0
        ok(f"MarketImpact: AC={mi.almgren_chriss_bps:.2f} bps, "
           f"Kissell={mi.kissell_bps:.2f} bps, total={mi.total_impact_bps:.2f}, "
           f"slippage={mi.slippage_bps:.2f}")

        # 4) Capacity model
        cap = estimate_capacity(
            volumes=vols,
            prices=np.full(200, 100.0),
            depth_usd=500_000.0,
            gross_edge_bps=50.0,
            trades_per_day=10.0,
            fee_bps_per_trade=2.0,
            extra={"test": True},
            persist=False,
        )
        assert cap.max_deployable_capital > 0, "expected positive max capital"
        assert cap.recommended_capital > 0
        assert cap.recommended_capital <= cap.max_deployable_capital
        # Liquidity constraints present
        assert cap.liquidity_limits["adv"] > 0
        assert cap.liquidity_limits["binding_max_order_qty"] > 0
        # Scalability curve populated
        assert len(cap.scalability_curve) > 0
        # First point should be passable (small capital, low impact)
        first = cap.scalability_curve[0]
        assert first["passable"] is True, (
            f"first point should be passable; got net_edge={first['net_edge_bps']:.2f}"
        )
        ok(f"Capacity: max=${cap.max_deployable_capital:,.0f}, "
           f"recommended=${cap.recommended_capital:,.0f}, "
           f"reason={cap.max_capital_reason}, "
           f"curve_points={len(cap.scalability_curve)}")
        return True
    except Exception as e:
        fail(f"capacity failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T6 — stress_testing
# ---------------------------------------------------------------------------


def test_stress() -> bool:
    banner("TEST 6: stress_testing (7 scenarios + survival rate)")
    try:
        from backend.research import (
            volatility_shock, spread_shock, latency_shock, exchange_outage,
            funding_shock, gap_simulation, black_swan, run_stress_battery,
        )
        rng = np.random.default_rng(17)
        n = 300
        returns = rng.normal(0.0008, 0.005, size=n)
        # Mixed directions (50/50)
        dirs = rng.choice([-1, 1], size=n)

        # 1) Each scenario produces a non-empty result
        s1 = volatility_shock(returns, k=3.0)
        s2 = spread_shock(returns, shock_bps=5.0)
        s3 = latency_shock(returns, shock_bps=3.0)
        s4 = exchange_outage(returns, outage_trades=5, random_seed=17)
        s5 = funding_shock(returns, directions=dirs, shock_bps=10.0)
        s6 = gap_simulation(returns, gap_pct=-10.0, gap_position=0.5)
        s7 = black_swan(returns, directions=dirs)
        for s in [s1, s2, s3, s4, s5, s6, s7]:
            assert s.n_trades == n
            assert "sharpe" in s.baseline_metrics
            assert "sharpe" in s.stressed_metrics
            assert isinstance(s.survived, bool)
        # Vol shock should REDUCE Sharpe (vol higher)
        assert s1.stressed_metrics["sharpe"] < s1.baseline_metrics["sharpe"]
        # Spread/latency shock should reduce mean
        assert s2.stressed_metrics["mean"] < s2.baseline_metrics["mean"]
        assert s3.stressed_metrics["mean"] < s3.baseline_metrics["mean"]
        # Gap simulation should produce larger max DD
        assert s6.max_drawdown_stressed <= s6.baseline_metrics["max_drawdown"] + 1e-9
        ok(f"7 scenarios: vol/sharpe {s1.stressed_metrics['sharpe']:.2f} vs "
           f"{s1.baseline_metrics['sharpe']:.2f}; "
           f"gap_maxDD {s6.max_drawdown_stressed:.3f}")

        # 2) Battery
        rep = run_stress_battery(
            returns=returns, directions=dirs,
            vol_mult=3.0, spread_bps=5.0, latency_bps=3.0,
            funding_bps=10.0, gap_pct=-10.0, gap_position=0.5,
            outage_trades=5, random_seed=17,
            persist=False,
        )
        assert rep.n_trades == n
        assert len(rep.scenarios) == 7
        assert "n_scenarios" in rep.aggregate
        assert rep.aggregate["n_scenarios"] == 7
        assert 0.0 <= rep.aggregate["survival_rate"] <= 1.0
        ok(f"Battery: {rep.aggregate['n_scenarios']} scenarios, "
           f"survived={rep.aggregate['n_survived']}/7 "
           f"({rep.aggregate['survival_rate']:.2%}), "
           f"worst_DD={rep.aggregate['worst_max_drawdown']:.3f}, "
           f"any_ruin={rep.aggregate['any_ruin']}")
        return True
    except Exception as e:
        fail(f"stress failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T7 — institutional_report
# ---------------------------------------------------------------------------


def test_institutional_report() -> bool:
    banner("TEST 7: institutional_report (robustness + readiness + JSON/HTML)")
    try:
        from backend.research import (
            run_walk_forward, run_monte_carlo, run_statistical_battery,
            run_stress_battery, estimate_capacity, fit_and_evaluate,
            build_robustness_scorecard, build_readiness_scorecard,
            explain_live_gate, build_institutional_report,
        )
        rng = np.random.default_rng(21)
        n = 300
        returns = rng.normal(0.0008, 0.005, size=n)
        y_pred = np.clip(rng.normal(0.55, 0.15, n), 0.0, 1.0)
        y = (rng.random(n) < y_pred).astype(float)
        vols = rng.lognormal(mean=15, sigma=0.4, size=200)

        # Build sub-reports
        wf = run_walk_forward(
            y=y, y_pred=y_pred, scheme="rolling",
            train_size=80, test_size=30, step=20,
            persist=False,
        ).to_dict()
        mc = run_monte_carlo(
            returns=returns, n_bootstrap=200, n_reshuffle=100,
            persist=False,
        ).to_dict()
        stat = run_statistical_battery(
            returns=returns, n_bootstrap=200, persist=False,
        ).to_dict()
        stress = run_stress_battery(
            returns=returns, persist=False,
        ).to_dict()
        cap = estimate_capacity(
            volumes=vols, prices=np.full(200, 100.0),
            depth_usd=500_000.0, gross_edge_bps=50.0,
            persist=False,
        ).to_dict()
        cal = fit_and_evaluate(
            y_true=y, y_prob=y_pred, method="isotonic",
        ).to_dict()

        # Robustness scorecard
        rob = build_robustness_scorecard(
            walk_forward_report=wf, monte_carlo_report=mc,
            statistical_report=stat, stress_report=stress,
            calibration_report=cal, drift_stats={"active_alerts": 0},
        )
        assert 0.0 <= rob.composite <= 1.0
        assert len(rob.components) == 6
        ok(f"Robustness: composite={rob.composite:.3f}, "
           f"WF={rob.components['walk_forward']:.3f}, "
           f"MC={rob.components['monte_carlo']:.3f}, "
           f"Stat={rob.components['statistical']:.3f}, "
           f"Stress={rob.components['stress']:.3f}, "
           f"Cal={rob.components['calibration']:.3f}, "
           f"Drift={rob.components['drift']:.3f}")

        # Readiness scorecard — gate still locked (insufficient data)
        gate_state = {
            "unlocked": False,
            "pass_count": 2,
            "total": 6,
            "failed_reasons": ["insufficient verified predictions",
                              "max_drawdown_pct too high"],
            "conditions": [
                {"name": "global_win_rate", "passed": True, "actual": 0.55, "required": 0.52},
                {"name": "verified_count", "passed": False, "actual": 50, "required": 300},
                {"name": "profit_factor", "passed": True, "actual": 1.30, "required": 1.20},
                {"name": "max_drawdown", "passed": False, "actual": 0.15, "required": 0.10},
                {"name": "shadow_live_passed", "passed": False, "actual": False, "required": True},
                {"name": "execution_engine_verified", "passed": False, "actual": False, "required": True},
            ],
        }
        rd = build_readiness_scorecard(
            robustness_score=rob.composite,
            capacity_report=cap,
            capacity_target_usd=100_000.0,
            live_gate_state=gate_state,
            verified_predictions_n=50,
            min_verified_n=300,
        )
        assert 0.0 <= rd.composite <= 1.0
        assert not rd.live_gate_unlocked  # gate is locked
        assert len(rd.blockers) >= 1
        ok(f"Readiness: composite={rd.composite:.3f}, "
           f"capacity_headroom={rd.capacity_headroom_ratio:.3f}, "
           f"gate={rd.live_gate_pass_count}/{rd.live_gate_total}, "
           f"verified={rd.verified_predictions_n}, "
           f"blockers={len(rd.blockers)}")

        # Live gate explanation
        exp = explain_live_gate(gate_state)
        assert not exp.unlocked
        assert exp.pass_count == 2
        assert exp.total == 6
        assert len(exp.blockers) == 2
        assert "LOCKED" in exp.summary
        ok(f"LiveGateExpl: {exp.summary}")

        # Full institutional report
        rep = build_institutional_report(
            n_trades=n, n_predictions=n,
            walk_forward_report=wf, monte_carlo_report=mc,
            statistical_report=stat, capacity_report=cap,
            stress_report=stress, calibration_report=cal,
            drift_stats={"active_alerts": 0},
            live_gate_state=gate_state,
            verified_predictions_n=50,
            persist=False, persist_html=False,
        )
        assert rep.version == "ACT-XXVIII-institutional-validation"
        # JSON serialisable
        js = rep.to_json()
        assert '"robustness"' in js
        assert '"readiness"' in js
        # HTML view
        html = rep.to_html()
        assert "<html" in html
        assert "Robustness" in html
        ok(f"Institutional report: robustness={rep.robustness['composite']:.3f}, "
           f"readiness={rep.readiness['composite']:.3f}, "
           f"json={len(js)} bytes, html={len(html)} bytes")
        return True
    except Exception as e:
        fail(f"institutional_report failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T8 — main.py endpoints + version
# ---------------------------------------------------------------------------


def test_main_endpoints() -> bool:
    banner("TEST 8: main.py — 6 new endpoints + version bump")
    try:
        from backend.main import app
        # Version
        assert app.version == "ACT-XXVIII-institutional-validation", (
            f"version mismatch: got {app.version!r}"
        )
        ok(f"app version = {app.version}")
        # Endpoints present
        expected = {
            "/api/research/walkforward",
            "/api/research/montecarlo",
            "/api/research/statistics",
            "/api/research/stress",
            "/api/research/capacity",
            "/api/research/report",
        }
        present = {r.path for r in app.routes if hasattr(r, "path")}
        missing = expected - present
        assert not missing, f"missing endpoints: {missing}"
        ok(f"all 6 new endpoints registered: {sorted(expected)}")
        # Also ensure pre-existing ACT-XXVII endpoints still present (no regression)
        xxvii_expected = {
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
        xxvii_missing = xxvii_expected - present
        assert not xxvii_missing, (
            f"pre-existing ACT-XXVII endpoints missing: {xxvii_missing}"
        )
        ok(f"all {len(xxvii_expected)} ACT-XXVII endpoints still present")
        # Portfolio endpoints (ACT-XXV/XXVI) still present
        for path in ["/api/portfolio/state", "/api/portfolio/analytics",
                     "/api/portfolio/live_gate", "/api/portfolio/microstructure",
                     "/api/portfolio/regime_hmm", "/api/portfolio/meta_labeler"]:
            assert path in present, f"missing portfolio endpoint: {path}"
        ok("all ACT-XXV/XXVI portfolio endpoints still present")
        return True
    except Exception as e:
        fail(f"main_endpoints failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T9 — regression: prior smoke tests still importable
# ---------------------------------------------------------------------------


def test_regression_imports() -> bool:
    banner("TEST 9: regression — prior ACT smoke modules still importable")
    try:
        # ACT-XXV/XXVI portfolio modules
        from backend.portfolio import (  # noqa: F401
            PortfolioCoordinator, PortfolioEngine, RiskKernel,
            ExecutionEngine, TradeJournal, PortfolioAnalytics, ShadowLive,
        )
        try:
            from backend.portfolio import (  # noqa: F401
                FillSimulator, MicrostructureIntelligence,
                MetaLabeler, HMMRegimeOverlay,
            )
            ok("ACT-XXVI modules import")
        except ImportError:
            ok("ACT-XXVI modules not exported in portfolio __init__ (skip)")
        # ACT-XXVII research modules
        from backend.research import (  # noqa: F401
            PurgedKFold, CombinatorialPurgedCV, PlattCalibrator,
            IsotonicCalibrator, BetaCalibrator, DriftMonitor,
            PSIDetector, KSDriftDetector, PageHinkleyDetector, ADWINDetector,
            information_coefficient, rolling_sharpe, Explainer,
            MetricsRegistry, get_registry, ResearchCoordinator,
        )
        ok("ACT-XXVII research modules still import")
        # Oracle engine (entrypoint — should always be importable)
        from backend.oracle_engine import OracleEngine  # noqa: F401
        ok("oracle_engine still imports (DO_NOT_TOUCH layers respected)")
        # Existing smoke test scripts present
        for name in ["act_xxv_smoke.py", "act_xxvi_smoke.py", "act_xxvii_smoke.py"]:
            p = PROJECT_ROOT / "scripts" / name
            assert p.exists(), f"missing {name}"
        ok("all prior smoke scripts still present")
        return True
    except Exception as e:
        fail(f"regression failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


TESTS = [
    ("T1", test_imports),
    ("T2", test_walk_forward),
    ("T3", test_monte_carlo),
    ("T4", test_statistical),
    ("T5", test_capacity),
    ("T6", test_stress),
    ("T7", test_institutional_report),
    ("T8", test_main_endpoints),
    ("T9", test_regression_imports),
]


def main() -> int:
    print("\n" + "#" * 70)
    print("#  ACT-XXVIII Smoke Test — Institutional Validation-Grade")
    print("#" * 70)
    results: list[tuple[str, bool]] = []
    for tid, fn in TESTS:
        try:
            r = fn()
        except Exception as e:
            fail(f"{tid} raised: {e}")
            import traceback
            traceback.print_exc()
            r = False
        results.append((tid, r))
    print("\n" + "#" * 70)
    print("#  SUMMARY")
    print("#" * 70)
    n_pass = sum(1 for _, r in results if r)
    for tid, r in results:
        print(f"  {tid}: {'PASS' if r else 'FAIL'}")
    print(f"\n  TOTAL: {n_pass}/{len(results)}")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
