"""
ACT-XXIX Smoke Test — Systemic Anti-Fragility Layer
====================================================

Validates that all 8 ACT-XXIX anti-fragility modules import cleanly,
work standalone, integrate via AntiFragilityCoordinator, and DO NOT
break the existing ACT-XXV / ACT-XXVI / ACT-XXVII / ACT-XXVIII pipeline.

Coverage:
  T1   imports (all 8 modules + version bump)
  T2   event_sourcing — append + replay + snapshot + tamper detection
  T3   invariant_checker — registry + state machine + DAG + corruption
  T4   lineage — DAG + prediction ancestry + schema migration
  T5   diagnostics — health + confidence decomposition + anomaly + ensemble
  T6   resilience — circuit breaker + checkpoint + crash recovery + BIV
  T7   reproducibility — seed + experiment registry + CV + benchmarks
  T8   market_simulation — synthetic + scenario + adversarial + regime + fault
  T9   architecture_validator — SENECIO spec validates against actual code
  T10  main.py — 13 new /api/antifragility/* endpoints + version bump
  T11  Regression — all 4 prior ACT smoke tests still import cleanly

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m scripts.act_xxix_smoke
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
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
    banner("TEST 1: imports (all 8 ACT-XXIX modules + version bump)")
    try:
        from backend.antifragility import (
            VERSION,
            # M1
            Event, EventStore, GlobalAuditLedger, SnapshotManager,
            EventSourcedAggregate, PredictionLifecycleAggregate,
            DeterministicReplayer,
            # M2
            InvariantRegistry, StateMachineValidator,
            DependencyGraphValidator, CorruptionDetector, RuntimeAssertions,
            RangeInvariant, HashChainInvariant, SchemaInvariant,
            # M3
            LineageGraph, PredictionAncestry, SchemaVersioner, SchemaVersion,
            DecisionProvenanceGraph, EdgeType,
            # M4
            HealthScorer, ConfidenceDecomposer, AnomalyClusterer,
            EnsembleDisagreementDetector, SelfDiagnostics,
            # M5
            CircuitBreaker, CircuitBreakerRegistry, CheckpointManager,
            CrashRecovery, ResourceWatchdog, BackgroundIntegrityVerifier,
            ResilienceCoordinator, CircuitOpenError,
            # M6
            DeterministicSeed, ExperimentRegistry, Experiment,
            ReproducibilityReport, CVRun, CrossValidationRegistry,
            Benchmark, BenchmarkSuite,
            # M7
            SyntheticMarketGenerator, ScenarioGenerator,
            AdversarialMarketSimulator, RegimeTransitionSimulator,
            Fault, FaultInjector, ExchangeFailureSimulator,
            NetworkDegradationSimulator, APIInconsistencySimulator,
            ClockSkewSimulator, TimeTravelReplayEngine,
            # M8
            ArchitectureValidator, build_senecio_architecture_spec,
            ArchitectureSpec,
            # Coordinator
            AntiFragilityCoordinator,
        )
        assert VERSION == "ACT-XXIX-systemic-antifragility", \
            f"version mismatch: {VERSION}"
        ok(f"VERSION = {VERSION}")
        ok("all 8 modules + coordinator import cleanly")
        return True
    except Exception as e:
        fail(f"import error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T2 — event sourcing
# ---------------------------------------------------------------------------

def test_event_sourcing() -> bool:
    banner("TEST 2: event_sourcing — append + replay + snapshot + tamper")
    try:
        from backend.antifragility import (
            EventStore, GlobalAuditLedger, SnapshotManager,
            PredictionLifecycleAggregate, DeterministicReplayer,
        )
        tmp = tempfile.mkdtemp()
        store = EventStore(os.path.join(tmp, "ledger.jsonl"))
        # Append 5 events for one prediction lifecycle
        for ev_type, payload in [
            ("PREDICTION_MADE", {"prediction_id": "p1", "symbol": "BTC/USDT",
                                  "direction": "LONG", "confidence": 0.65}),
            ("FEATURES_COMPUTED", {"prediction_id": "p1",
                                    "features": {"rsi": 32.1}}),
            ("SIGNAL_GENERATED", {"prediction_id": "p1",
                                   "signal": "LONG", "confidence": 0.72}),
            ("VERIFIED", {"prediction_id": "p1", "outcome": "CORRECT"}),
            ("CLOSED", {"prediction_id": "p1"}),
        ]:
            store.append(ev_type, payload)
        # Verify chain
        ok_count = store.count()
        chain_ok, broken = store.verify_chain()
        assert ok_count == 5, f"expected 5 events, got {ok_count}"
        assert chain_ok, f"chain broken: {broken}"
        ok(f"appended {ok_count} events, chain intact")
        # Replay into aggregate
        agg = PredictionLifecycleAggregate("p1")
        DeterministicReplayer(store).replay_into(agg)
        assert agg.state["outcome"] == "CORRECT"
        assert agg.state["confidence"] == 0.72
        assert agg.state["event_count"] == 5
        ok(f"replay: outcome={agg.state['outcome']} conf={agg.state['confidence']}")
        # Snapshot + restore
        mgr = SnapshotManager(os.path.join(tmp, "snaps"))
        snap = agg.snapshot(mgr)
        agg2 = PredictionLifecycleAggregate("p1")
        agg2.restore(mgr, store)
        assert agg2.state["outcome"] == "CORRECT"
        ok(f"snapshot+restore: seq={snap.seq} state={len(snap.state)} keys")
        # Tamper detection
        ledgpath = os.path.join(tmp, "ledger.jsonl")
        import json as _json
        with open(ledgpath) as f:
            lines = f.readlines()
        mutated = _json.loads(lines[1])
        mutated["payload"]["confidence"] = 0.99
        lines[1] = _json.dumps(mutated) + "\n"
        with open(ledgpath, "w") as f:
            f.writelines(lines)
        store2 = EventStore(ledgpath)
        ok_tamper, broken_tamper = store2.verify_chain()
        assert not ok_tamper and 2 in broken_tamper, \
            f"tamper not detected: ok={ok_tamper} broken={broken_tamper}"
        ok(f"tamper detected at seq=2 (broken_seqs={broken_tamper})")
        return True
    except Exception as e:
        fail(f"event_sourcing error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T3 — invariant_checker
# ---------------------------------------------------------------------------

def test_invariant_checker() -> bool:
    banner("TEST 3: invariant_checker — registry + SM + DAG + corruption")
    try:
        from backend.antifragility import (
            InvariantRegistry, RangeInvariant, SchemaInvariant,
            ThresholdInvariant, StateMachineValidator,
            DependencyGraphValidator, CorruptionDetector,
            RuntimeAssertions, Severity,
        )
        # Registry
        reg = InvariantRegistry()
        reg.register(RangeInvariant("conf_range", lambda: 0.72, 0.0, 1.0,
                                     tags=("prediction",)))
        reg.register(RangeInvariant("kelly_range", lambda: -0.5, -1.0, 1.0,
                                     tags=("prediction",)))
        reg.register(SchemaInvariant(
            "pred_schema",
            lambda: {"prediction_id": "p1", "confidence": 0.72,
                      "direction": "LONG"},
            {"type": "object",
             "required": ["prediction_id", "confidence", "direction"],
             "properties": {
                 "prediction_id": {"type": "string"},
                 "confidence": {"type": "number", "min": 0, "max": 1},
                 "direction": {"type": "string"}}},
            tags=("schema",),
        ))
        results = reg.run_all()
        ok_count = sum(1 for r in results if r.ok)
        assert ok_count == 3, f"expected 3/3 ok, got {ok_count}/3"
        ok(f"registry: 3/3 invariants pass")
        # State machine
        sm = StateMachineValidator()
        for s in ("IDLE", "PROPOSED", "EXECUTED", "CLOSED"):
            sm.add_state(s)
        sm.add_transition("IDLE", "PROPOSED")
        sm.add_transition("PROPOSED", "EXECUTED")
        sm.add_transition("EXECUTED", "CLOSED")
        sm.set_current("IDLE")
        sm.transition("IDLE", "PROPOSED")
        sm.transition("PROPOSED", "EXECUTED")
        try:
            sm.transition("EXECUTED", "IDLE")
            assert False, "should have raised IllegalTransition"
        except StateMachineValidator.IllegalTransition:
            pass
        ok(f"state machine: illegal transition detected")
        # DAG with cycle
        dg = DependencyGraphValidator()
        dg.add_edge("a", "b")
        dg.add_edge("b", "c")
        dg.add_edge("c", "a")  # cycle
        cycle = dg.detect_cycle()
        topo = dg.topological_sort()
        assert cycle is not None, "cycle not detected"
        assert topo is None, "topo should fail on cycle"
        ok(f"DAG cycle detected: {cycle[:3]}...")
        # DAG without cycle
        dg2 = DependencyGraphValidator()
        dg2.add_edge("a", "b")
        dg2.add_edge("b", "c")
        dg2.add_edge("a", "c")
        cycle2 = dg2.detect_cycle()
        topo2 = dg2.topological_sort()
        assert cycle2 is None and topo2 is not None
        ok(f"DAG acyclic: topo={topo2}")
        # CorruptionDetector
        cd = CorruptionDetector()
        cd.register_hash("k1", {"a": 1, "b": 2})
        ok1, _ = cd.verify_hash("k1", {"a": 1, "b": 2})
        ok2, _ = cd.verify_hash("k1", {"a": 1, "b": 3})
        assert ok1 and not ok2
        ok(f"corruption: hash match={ok1} mismatch={not ok2}")
        # RuntimeAssertions
        RuntimeAssertions.in_range(0.5, 0.0, 1.0, "x")
        RuntimeAssertions.is_type("hello", str, "s")
        RuntimeAssertions.not_none(42, "n")
        RuntimeAssertions.is_in("LONG", ["LONG", "SHORT"], "dir")
        RuntimeAssertions.is_positive(1.0, "p")
        try:
            RuntimeAssertions.in_range(2.0, 0.0, 1.0, "x")
            assert False
        except AssertionError:
            pass
        ok(f"runtime assertions: all helpers work")
        return True
    except Exception as e:
        fail(f"invariant_checker error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T4 — lineage
# ---------------------------------------------------------------------------

def test_lineage() -> bool:
    banner("TEST 4: lineage — DAG + ancestry + schema migration")
    try:
        from backend.antifragility import (
            PredictionAncestry, SchemaVersioner, SchemaVersion,
            DecisionProvenanceGraph,
        )
        anc = PredictionAncestry()
        md = anc.record_market_data("BTC/USDT", "15m",
                                     {"close": 50000, "vol": 1000})
        feats = anc.record_features(md, {"rsi": 32.1, "vol": 0.018})
        sig = anc.record_signal(feats, "LONG", 0.72)
        pred = anc.record_prediction(sig, "p1", 0.72)
        outc = anc.record_outcome(pred, "CORRECT", 0.003)
        # Verify DAG
        assert anc.graph.node_count() == 5
        assert anc.graph.edge_count() == 4
        # Verify ancestry walk
        ancestors = anc.ancestry_of("p1")
        descendant = anc.descendants_of("p1")
        assert len(ancestors) == 3  # market_data, features, signal
        assert len(descendant) == 1  # outcome
        ok(f"lineage: nodes={anc.graph.node_count()} "
            f"edges={anc.graph.edge_count()} anc={len(ancestors)} "
            f"desc={len(descendant)}")
        # Schema migration
        sv = SchemaVersioner()
        sv.register(SchemaVersion("prediction", 1,
                                    {"type": "object"},
                                    introduced_at="2026-01-01T00:00:00Z"))
        sv.register(SchemaVersion("prediction", 2,
                                    {"type": "object"},
                                    introduced_at="2026-06-01T00:00:00Z",
                                    migrate_from=1))
        sv._migrators[("prediction", 1, 2)] = lambda old: {**old, "v": 2}
        path = sv.migration_path("prediction", 1, 2)
        assert path == [1, 2], f"bad path: {path}"
        new_payload, mok = sv.migrate("prediction", 1, 2, {"id": "p1"})
        assert mok and new_payload.get("v") == 2
        ok(f"schema migration: v1→v2 ok={mok} payload={new_payload}")
        # Decision provenance (shares the same graph as ancestry)
        dpg = DecisionProvenanceGraph(graph=anc.graph)
        n1 = md  # reuse nodes from ancestry graph
        n2 = sig
        dpg.record_decision("d1", "risk_kernel", [n1], [n2], "because")
        trace = dpg.trace_decision("d1")
        assert trace["decision"]["payload"]["actor"] == "risk_kernel"
        ok(f"decision provenance: traced d1")
        return True
    except Exception as e:
        fail(f"lineage error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T5 — diagnostics
# ---------------------------------------------------------------------------

def test_diagnostics() -> bool:
    banner("TEST 5: diagnostics — health + confidence + anomaly + ensemble")
    try:
        from backend.antifragility import (
            HealthScorer, ConfidenceDecomposer, AnomalyClusterer,
            EnsembleDisagreementDetector, SelfDiagnostics,
        )
        # Health
        hs = HealthScorer()
        hs.register_metric("win_rate", lambda: 0.55, weight=2.0,
                            transform="higher_better", bounds=(0.4, 0.7))
        hs.register_metric("max_dd", lambda: 0.04, weight=1.5,
                            transform="lower_better", bounds=(0.0, 0.10))
        hs.register_metric("latency_p99", lambda: 250, weight=1.0,
                            transform="in_range", bounds=(50, 500))
        h = hs.compute()
        assert 0.0 <= h["score"] <= 1.0
        assert len(h["components"]) == 3
        ok(f"health: score={h['score']:.3f} ok={h['ok']} "
            f"components={len(h['components'])}")
        # Confidence decomposer (weight method)
        cd = ConfidenceDecomposer(method="weight")
        cd.set_weights({"rsi": 0.3, "momentum": 0.25, "vol": 0.2})
        decomp = cd.decompose(
            {"rsi": 0.6, "momentum": -0.3, "vol": 0.4},
            baseline_confidence=0.72,
        )
        assert abs(decomp["total"] - 0.72) < 1e-6
        assert len(decomp["contributions"]) == 3
        ok(f"confidence decomp: total={decomp['total']:.3f} "
            f"contributions={len(decomp['contributions'])}")
        # Anomaly clusterer
        ac = AnomalyClusterer(n_clusters=3, n_features=4)
        rng = np.random.default_rng(0)
        for _ in range(100):
            ac.partial_fit(rng.normal(0, 1, 4))
        normal = ac.score(rng.normal(0, 1, 4))
        anomaly = ac.score(np.array([10.0, 10.0, 10.0, 10.0]))
        assert not normal["is_anomaly"]
        assert anomaly["is_anomaly"]
        ok(f"anomaly: normal z={normal['z_score']:.2f} "
            f"anomaly z={anomaly['z_score']:.2f}")
        # Ensemble disagreement
        ed = EnsembleDisagreementDetector(n_members=3,
                                           disagreement_threshold=0.3)
        snap1 = ed.record([0.65, 0.66, 0.64], outcome=0.7)
        snap2 = ed.record([0.65, 0.30, 0.95], outcome=0.7)
        assert not snap1["disagreement"]
        assert snap2["disagreement"]
        ok(f"ensemble: agree={snap1['spread']:.3f} "
            f"disagree={snap2['spread']:.3f}")
        # Self-diagnostics orchestrator
        sd = SelfDiagnostics()
        sd.health.register_metric("m1", lambda: 0.5, weight=1.0,
                                    transform="higher_better")
        result = sd.run(features={"a": 0.5, "b": -0.3},
                         member_predictions=[0.6, 0.5, 0.55],
                         sample_vector=[0.1, 0.2, 0.3, 0.4,
                                         0.5, 0.6, 0.7, 0.8])
        assert "health" in result
        assert "confidence_decomposition" in result
        assert "ensemble" in result
        assert "anomaly" in result
        ok(f"self-diagnostics: 4 sections present")
        return True
    except Exception as e:
        fail(f"diagnostics error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T6 — resilience
# ---------------------------------------------------------------------------

def test_resilience() -> bool:
    banner("TEST 6: resilience — breaker + checkpoint + crash + BIV")
    try:
        from backend.antifragility import (
            CircuitBreaker, CircuitOpenError, CircuitBreakerRegistry,
            CheckpointManager, CrashRecovery, ResourceWatchdog,
            BackgroundIntegrityVerifier, ResilienceCoordinator,
            CircuitState,
        )
        tmp = tempfile.mkdtemp()
        # Circuit breaker
        cb = CircuitBreaker("test", failure_threshold=3,
                             recovery_timeout_s=0.2, success_threshold=1)
        assert cb.state == CircuitState.CLOSED
        for _ in range(3):
            try:
                cb.call(lambda: 1 / 0)
            except ZeroDivisionError:
                pass
        assert cb.state == CircuitState.OPEN
        try:
            cb.call(lambda: "ok")
            assert False
        except CircuitOpenError:
            pass
        time.sleep(0.25)
        assert cb.state == CircuitState.HALF_OPEN
        result = cb.call(lambda: "ok")
        assert cb.state == CircuitState.CLOSED
        ok(f"breaker: CLOSED→OPEN→HALF_OPEN→CLOSED ok")
        # Checkpoint manager
        cm = CheckpointManager(checkpoint_dir=os.path.join(tmp, "cps"))
        cp1 = cm.take_snapshot("portfolio", {"equity": 10000})
        cp2 = cm.take_snapshot("portfolio", {"equity": 10100})
        cp_dirty = cm.take_snapshot("portfolio", {"equity": 9500},
                                     is_clean=False)
        assert cm.count("portfolio") == 3
        assert cm.latest_clean("portfolio").seq == 2
        restored = cm.restore("portfolio")
        assert restored == {"equity": 10100}
        ok(f"checkpoint: 3 snapshots, latest clean seq=2, restored ok")
        # Crash recovery
        cr = CrashRecovery(cm, heartbeat_file=os.path.join(tmp, "hb.json"))
        cr.mark_started(["portfolio"])
        assert cr.was_dirty_shutdown()  # no clean shutdown yet
        cr.mark_clean_shutdown()
        assert not cr.was_dirty_shutdown()
        ok(f"crash recovery: dirty=True then clean=True")
        # Resource watchdog
        wd = ResourceWatchdog(memory_warning_mb=1.0, memory_critical_mb=2.0)
        for i in range(100):
            wd.record_latency("op1", 100 + i)
        stats = wd.latency_stats("op1")
        assert stats["samples"] == 100
        ok(f"watchdog: latency p99={stats['p99_ms']:.1f}ms "
            f"n={stats['samples']}")
        # BIV
        counter = [0]
        def check():
            counter[0] += 1
            return {"ok": True}
        biv = BackgroundIntegrityVerifier(check_fn=check, interval_s=0.1)
        biv.start()
        time.sleep(0.35)
        biv.stop()
        assert counter[0] >= 2
        ok(f"BIV: ran {counter[0]} times in 0.35s")
        # Coordinator
        rc = ResilienceCoordinator(checkpoint_dir=os.path.join(tmp, "rc"))
        rc.register_subsystem("portfolio", lambda: {"equity": 10000})
        rc.checkpoint_all()
        snap = rc.snapshot()
        assert "breakers" in snap
        assert "checkpoint_counts" in snap
        ok(f"coordinator: snapshot has "
            f"{len(snap['checkpoint_counts'])} subsystems")
        return True
    except Exception as e:
        fail(f"resilience error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T7 — reproducibility
# ---------------------------------------------------------------------------

def test_reproducibility() -> bool:
    banner("TEST 7: reproducibility — seed + experiments + CV + benchmarks")
    try:
        from backend.antifragility import (
            DeterministicSeed, Experiment, ExperimentRegistry,
            ReproducibilityReport, CVRun, CrossValidationRegistry,
            Benchmark, BenchmarkSuite,
        )
        tmp = tempfile.mkdtemp()
        # Deterministic seed
        ds1 = DeterministicSeed(root_seed=42)
        ds2 = DeterministicSeed(root_seed=42)
        s_a = ds1.derive("portfolio_engine")
        s_b = ds2.derive("portfolio_engine")
        assert s_a == s_b, "same seed + same path must give same derived seed"
        s_c = ds1.derive("research.calibration")
        assert s_c != s_a, "different paths must give different seeds"
        rng1 = ds1.get_rng("x")
        rng2 = ds2.get_rng("x")
        v1 = rng1.normal(0, 1, 5)
        v2 = rng2.normal(0, 1, 5)
        assert np.array_equal(v1, v2), "RNG must be deterministic"
        ok(f"seed: same root+path → same derived seed + same RNG output")
        # Experiment registry
        reg = ExperimentRegistry(registry_dir=os.path.join(tmp, "exps"))
        exp = Experiment.create(
            name="test_exp", kind="backtest",
            params={"window": 100}, metrics={"sharpe": 1.5},
            artifacts=[os.path.join(tmp, "artifact.json")],
            seed=ds1.derive("test_exp"),
        )
        # Create the artifact file so repro report can hash it
        with open(os.path.join(tmp, "artifact.json"), "w") as f:
            f.write('{"result": "ok"}')
        reg.register(exp)
        # Verify hash
        assert reg.verify(exp.experiment_id), "hash verification failed"
        # Reproducibility report
        report = ReproducibilityReport(reg, ds1)
        rep = report.generate(exp.experiment_id)
        assert rep["hash_verified"]
        assert len(rep["artifacts"]) == 1
        assert rep["artifacts"][0]["exists"]
        ok(f"experiment: id={exp.experiment_id[:8]}... hash_verified "
            f"artifact_exists={rep['artifacts'][0]['exists']}")
        # CV registry
        cvr = CrossValidationRegistry(registry_dir=os.path.join(tmp, "cvs"))
        for fold in range(5):
            run = CVRun.create(
                experiment_id=exp.experiment_id, fold_idx=fold,
                train_size=80, test_size=20,
                metrics={"accuracy": 0.65 + fold * 0.01,
                          "sharpe": 1.2 + fold * 0.05},
            )
            cvr.register(run)
        agg = cvr.aggregate(exp.experiment_id)
        assert agg["folds"] == 5
        assert "accuracy" in agg["metrics"]
        assert agg["metrics"]["accuracy"]["n"] == 5
        ok(f"CV: 5 folds, accuracy mean="
            f"{agg['metrics']['accuracy']['mean']:.3f}")
        # Benchmark suite
        bs = BenchmarkSuite(results_dir=os.path.join(tmp, "bms"))
        bs.register(Benchmark(
            name="quick_bench",
            description="quick test",
            fn=lambda: {"result": 42, "duration": 0.001},
        ))
        result = bs.run("quick_bench")
        assert result.ok
        assert result.metrics["result"] == 42
        history = bs.history("quick_bench")
        assert len(history) >= 1
        ok(f"benchmark: ran {result.benchmark_name} → "
            f"metrics={result.metrics}")
        return True
    except Exception as e:
        fail(f"reproducibility error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T8 — market_simulation
# ---------------------------------------------------------------------------

def test_market_simulation() -> bool:
    banner("TEST 8: market_simulation — synthetic + scenario + regime + fault")
    try:
        from backend.antifragility import (
            SyntheticMarketGenerator, ScenarioGenerator,
            AdversarialMarketSimulator, RegimeTransitionSimulator,
            FaultInjector, ExchangeFailureSimulator,
            NetworkDegradationSimulator, APIInconsistencySimulator,
            ClockSkewSimulator, TimeTravelReplayEngine, Regime,
        )
        # Synthetic
        gen = SyntheticMarketGenerator(seed=42)
        bars = gen.generate(50)
        assert len(bars) == 50
        assert all(b.close > 0 for b in bars)
        ok(f"synthetic: 50 bars, last close={bars[-1].close:.2f} "
            f"regime={gen.stats()['current_regime']}")
        # Scenarios
        sg = ScenarioGenerator(gen)
        scenarios = sg.all_scenarios()
        assert len(scenarios) >= 5
        ok(f"scenarios: {len(scenarios)} generated "
            f"({list(scenarios.keys())[:3]}...)")
        # Adversarial
        adv = AdversarialMarketSimulator(seed=42)
        dd_path = adv.max_drawdown_path(n_bars=20)
        ws_path = adv.whipsaw_extreme(n_bars=20)
        tail = adv.tail_event(direction="down")
        assert len(dd_path) == 20
        assert len(ws_path) == 20
        assert len(tail) == 1 and tail[0].close < tail[0].open  # down move
        ok(f"adversarial: dd_path=20 bars (final="
            f"{dd_path[-1].close:.2f}), tail_event 1 bar")
        # Regime transition
        rs = RegimeTransitionSimulator(gen)
        bull_to_bear = rs.bull_to_bear(n_bars=30)
        crash_rec = rs.crash_recovery()
        vol_cycle = rs.volatility_cycle()
        assert len(bull_to_bear) == 30
        assert len(crash_rec) > 0
        assert len(vol_cycle) > 0
        ok(f"regime: bull_to_bear=30 crash_recovery={len(crash_rec)} "
            f"vol_cycle={len(vol_cycle)}")
        # Fault injection
        fi = FaultInjector()
        fi.schedule_fault(ExchangeFailureSimulator.outage(duration_s=0.5))
        fi.schedule_fault(NetworkDegradationSimulator.latency_spike(
            latency_ms=500, duration_s=0.5), delay_s=0.1)
        fi.schedule_fault(APIInconsistencySimulator.stale_quotes(duration_s=0.5))
        fi.schedule_fault(ClockSkewSimulator.time_jump(seconds=60))
        fi.start(poll_interval_s=0.05)
        time.sleep(0.3)
        active = fi.active_faults()
        fi.stop()
        assert len(active) >= 1, f"no faults active (got {active})"
        ok(f"faults: {len(active)} active, "
            f"history={len(fi.history())} events")
        # Time travel
        tt = TimeTravelReplayEngine(default_interval_s=0.01)
        tt.load_history(bars[:10])
        replayed = list(tt.replay(start_idx=0, end_idx=5, speed=0, sleep=False))
        assert len(replayed) == 5
        ok(f"time-travel: replayed 5/10 bars at speed=0")
        return True
    except Exception as e:
        fail(f"market_simulation error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T9 — architecture_validator
# ---------------------------------------------------------------------------

def test_architecture_validator() -> bool:
    banner("TEST 9: architecture_validator — SENECIO spec validates against code")
    try:
        from backend.antifragility import (
            ArchitectureValidator, build_senecio_architecture_spec,
        )
        spec = build_senecio_architecture_spec()
        v = ArchitectureValidator(spec)
        report = v.validate()
        assert report.components_checked >= 13, \
            f"expected >=13 components, got {report.components_checked}"
        assert report.ok, \
            f"validation failed: errors={report.error_count} " \
            f"warns={report.warn_count}\n" + \
            "\n".join(f"  [{f.severity.value}] {f.component}: {f.msg}"
                       for f in report.findings
                       if f.severity.value in ("ERROR", "CRITICAL"))
        ok(f"architecture: ok={report.ok} "
            f"components={report.components_checked}/{report.components_passed} "
            f"errors={report.error_count} warns={report.warn_count}")
        return True
    except Exception as e:
        fail(f"architecture_validator error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T10 — main.py endpoints + version bump
# ---------------------------------------------------------------------------

def test_main_endpoints() -> bool:
    banner("TEST 10: main.py — 13 new /api/antifragility/* endpoints + version")
    try:
        import importlib
        if "backend.main" in sys.modules:
            del sys.modules["backend.main"]
        from backend import main
        # Version bump
        accepted_versions = (
            "ACT-XXVIII-institutional-validation",
            "ACT-XXIX-systemic-antifragility",
        )
        assert main.app.version in accepted_versions, \
            f"unexpected version: {main.app.version}"
        assert main.app.version == "ACT-XXIX-systemic-antifragility", \
            f"version not bumped: {main.app.version}"
        ok(f"app version = {main.app.version}")
        # Anti-fragility coordinator initialized
        assert main._antifragility_coord is not None, \
            f"antifragility coord not initialized: {main._af_init_err_msg}"
        ok(f"antifragility coordinator initialized")
        # Check all 13 new endpoints registered
        routes = {r.path for r in main.app.routes if hasattr(r, "path")}
        expected = {
            "/api/antifragility/state",
            "/api/antifragility/invariants/run",
            "/api/antifragility/lineage/explain",
            "/api/antifragility/diagnostics/run",
            "/api/antifragility/architecture/validate",
            "/api/antifragility/market/simulate",
            "/api/antifragility/faults/inject",
            "/api/antifragility/faults/active",
            "/api/antifragility/experiments/register",
            "/api/antifragility/experiments/{experiment_id}/report",
            "/api/antifragility/benchmarks",
            "/api/antifragility/benchmarks/run",
            "/api/antifragility/checkpoint/{subsystem}",
        }
        missing = expected - routes
        assert not missing, f"missing endpoints: {missing}"
        ok(f"all 13 new endpoints registered")
        # Check existing endpoints still present (regression)
        assert any("/api/portfolio/state" == r for r in routes), \
            "ACT-XXV endpoint missing"
        assert any("/api/portfolio/microstructure" == r for r in routes), \
            "ACT-XXVI endpoint missing"
        assert any("/api/research/state" == r for r in routes), \
            "ACT-XXVII endpoint missing"
        assert any("/api/research/walkforward" == r for r in routes), \
            "ACT-XXVIII endpoint missing"
        ok(f"all prior ACT (XXV/XXVI/XXVII/XXVIII) endpoints preserved")
        return True
    except Exception as e:
        fail(f"main endpoints error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# T11 — Regression: all prior smoke modules still import
# ---------------------------------------------------------------------------

def test_regression() -> bool:
    banner("TEST 11: regression — prior ACT smoke modules still importable")
    try:
        # ACT-XXV + XXVI portfolio
        from backend.portfolio import (
            PortfolioEngine, RiskKernel, ExecutionEngine,
            TradeJournal, PortfolioAnalytics, ShadowLive,
            LiveGate, PortfolioCoordinator,
            FillSimulator, MicrostructureIntelligence,
            MetaLabeler, HMMRegimeOverlay,
        )
        # ACT-XXVII research
        from backend.research import (
            ResearchCoordinator, PurgedKFold, Calibrator,
            DriftMonitor, compute_research_metrics, Explainer,
            MetricsRegistry,
        )
        # ACT-XXVIII validation
        from backend.research import (
            WalkForwardReport, MonteCarloReport, StatisticalValidationReport,
            CapacityReport, StressReport, InstitutionalReport,
        )
        # ACT-XXIX antifragility
        from backend.antifragility import (
            AntiFragilityCoordinator, VERSION as AF_VERSION,
        )
        # Check existing smoke test scripts still present
        scripts_dir = PROJECT_ROOT / "scripts"
        for fname in ("act_xxv_smoke.py", "act_xxvi_smoke.py",
                       "act_xxvii_smoke.py", "act_xxviii_smoke.py"):
            assert (scripts_dir / fname).exists(), f"missing {fname}"
        ok(f"backend.portfolio VERSION = "
            f"{__import__('backend.portfolio', fromlist=['VERSION']).VERSION}")
        ok(f"backend.research VERSION = "
            f"{__import__('backend.research', fromlist=['VERSION']).VERSION}")
        ok(f"backend.antifragility VERSION = {AF_VERSION}")
        ok(f"all 4 prior smoke scripts present")
        return True
    except Exception as e:
        fail(f"regression error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Coordinator end-to-end test
# ---------------------------------------------------------------------------

def test_coordinator_e2e() -> bool:
    banner("TEST 12: AntiFragilityCoordinator — end-to-end snapshot")
    try:
        import tempfile
        from backend.antifragility import AntiFragilityCoordinator
        tmp = tempfile.mkdtemp()
        coord = AntiFragilityCoordinator(
            ledger_path=os.path.join(tmp, "ledger.jsonl"),
            snapshot_dir=os.path.join(tmp, "snaps"),
            checkpoint_dir=os.path.join(tmp, "cps"),
            experiment_dir=os.path.join(tmp, "exps"),
            cv_dir=os.path.join(tmp, "cvs"),
            benchmark_dir=os.path.join(tmp, "bms"),
        )
        coord.start()
        # Record a decision
        coord.ledger.record_decision(
            decision_kind="test", actor="smoke",
            inputs={"x": 1}, outputs={"y": 2}, rationale="testing",
        )
        # Run invariants
        results = coord.run_invariants()
        assert len(results) >= 1
        assert all(r["ok"] for r in results), \
            f"invariant failed: {results}"
        # Architecture validation
        arch = coord.run_architecture_validation()
        assert arch["ok"], f"arch validation failed: {arch['error_count']}"
        # Generate synthetic bars
        bars = coord.generate_synthetic_bars(10)
        assert len(bars) == 10
        # Snapshot
        snap = coord.snapshot()
        assert snap["version"] == "ACT-XXIX-systemic-antifragility"
        assert snap["ledger"]["event_count"] >= 1
        assert snap["ledger"]["integrity_ok"]
        assert snap["invariants"]["total_invariants"] >= 1
        assert "diagnostics" in snap
        assert "resilience" in snap
        coord.stop()
        ok(f"coord e2e: ledger events={snap['ledger']['event_count']} "
            f"invariants={snap['invariants']['total_invariants']} "
            f"arch ok={arch['ok']}")
        return True
    except Exception as e:
        fail(f"coordinator e2e error: {e}")
        import traceback; traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("\n" + "#" * 70)
    print("#  ACT-XXIX Smoke Test — Systemic Anti-Fragility Layer")
    print("#" * 70)
    tests = [
        ("T1", test_imports),
        ("T2", test_event_sourcing),
        ("T3", test_invariant_checker),
        ("T4", test_lineage),
        ("T5", test_diagnostics),
        ("T6", test_resilience),
        ("T7", test_reproducibility),
        ("T8", test_market_simulation),
        ("T9", test_architecture_validator),
        ("T10", test_main_endpoints),
        ("T11", test_regression),
        ("T12", test_coordinator_e2e),
    ]
    results = []
    for name, fn in tests:
        try:
            r = fn()
        except Exception as e:
            r = False
            fail(f"{name} uncaught: {e}")
        results.append((name, r))
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    passed = 0
    for name, r in results:
        status = "[OK]  " if r else "[FAIL]"
        print(f"  {status} {name}")
        if r:
            passed += 1
    print(f"\n  TOTAL: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
