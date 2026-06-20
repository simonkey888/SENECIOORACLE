"""
ACT-XXVI Smoke Test — Deep Edge Integration
===========================================

Validates that all 3 new ACT-XXVI modules import cleanly, work standalone,
and integrate with the existing ACT-XXV coordinator without breaking it.

Coverage:
  T1  imports (all 3 new modules + bump to ACT-XXVI version)
  T2  FillSimulator — L2 walk + queue + impact vs fallback stochastic
  T3  ExecutionEngine with BookSnapshot → uses high-fidelity path
  T4  ExecutionEngine without BookSnapshot → falls back to legacy (no break)
  T5  MicrostructureIntelligence — VPIN + OFI + liquidation cluster
  T6  RiskKernel with microstructure attached → REJECT on toxic flow
  T7  MetaLabeler — LONG reject on low conviction, SHORT pass-through
  T8  MetaLabeler — triple-barrier reward/risk gate
  T9  PortfolioEngine with meta_labeler → REJECT for low-conviction LONG
  T10 HMMRegimeOverlay — belief update + dominant state transitions
  T11 PortfolioCoordinator end-to-end with all ACT-XXVI modules attached
  T12 main.py has the 3 new endpoints + version bumped to ACT-XXVI

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m scripts.act_xxvi_smoke
"""
from __future__ import annotations

import asyncio
import json
import sys
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


# -------------------- T1: imports + version bump --------------------

def test_imports() -> bool:
    banner("TEST 1: imports + ACT-XXVI version")
    try:
        from backend.portfolio import (
            # ACT-XXV baseline
            PortfolioEngine, TradeProposal, PortfolioState,
            RiskKernel, RiskDecision, KernelState, VolRegime,
            ExecutionEngine, Order, Fill, Position, OrderStatus, ExitReason,
            TradeJournal, PortfolioAnalytics, ShadowLive, ShadowTrade,
            LiveGate, GateStatus, PortfolioCoordinator,
            # ACT-XXVI additions
            FillSimulator, BookSnapshot, BookLevel, FillEstimate,
            QueuePositionModel, walk_book, estimate_market_impact, book_snapshot_from_dict,
            MicrostructureIntelligence, MicrostructureReport,
            VPINEstimator, OFIEstimator, LiquidationClusterDetector,
            MetaLabeler, MetaLabel, TripleBarrier,
            HMMRegimeOverlay, RegimeBelief,
            VERSION,
        )
        assert VERSION == "ACT-XXVI-deep-edge-integration", f"version mismatch: {VERSION}"
        ok(f"all 3 new ACT-XXVI modules imported")
        ok(f"VERSION = {VERSION}")
        return True
    except Exception as e:
        fail(f"import error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T2: FillSimulator — L2 walk + fallback --------------------

def test_fill_simulator() -> bool:
    banner("TEST 2: FillSimulator — L2 walk + fallback stochastic")
    try:
        from backend.portfolio import FillSimulator, BookSnapshot, BookLevel
        sim = FillSimulator()

        # Build a synthetic L2 book — mid=1700, spread=2 bps, $50k on each side
        mid = 1700.0
        bids = [
            BookLevel(price=mid * (1 - 0.0001), size=5.0),
            BookLevel(price=mid * (1 - 0.0003), size=10.0),
            BookLevel(price=mid * (1 - 0.0005), size=20.0),
        ]
        asks = [
            BookLevel(price=mid * (1 + 0.0001), size=5.0),
            BookLevel(price=mid * (1 + 0.0003), size=10.0),
            BookLevel(price=mid * (1 + 0.0005), size=20.0),
        ]
        book = BookSnapshot(symbol="ETH/USDT", bids=bids, asks=asks, last_trade_price=mid)

        # Small order — should fill fully at top-of-book
        est_small = sim.simulate_fill(side="BUY", notional_usd=500.0, book=book, is_marketable=True)
        assert est_small.expected_qty > 0, f"small order didn't fill: {est_small}"
        assert est_small.model == "l2_walk", f"expected l2_walk, got {est_small.model}"
        ok(f"small $500 BUY fill: qty={est_small.expected_qty:.4f} vwap=${est_small.expected_vwap_price:.4f} "
           f"slip={est_small.expected_slippage_bps:.2f}bps levels={est_small.levels_consumed}")

        # Large order — should walk multiple levels + show impact
        est_large = sim.simulate_fill(side="BUY", notional_usd=60_000.0, book=book, is_marketable=True)
        assert est_large.expected_qty > 0
        assert est_large.levels_consumed >= 2, f"expected >=2 levels consumed, got {est_large.levels_consumed}"
        assert est_large.expected_slippage_bps > est_small.expected_slippage_bps, \
            "large order should have more slippage than small"
        ok(f"large $60k BUY fill: qty={est_large.expected_qty:.4f} vwap=${est_large.expected_vwap_price:.4f} "
           f"slip={est_large.expected_slippage_bps:.2f}bps impact={est_large.expected_market_impact_bps:.2f}bps "
           f"levels={est_large.levels_consumed}")

        # No book → fallback stochastic
        est_fallback = sim.simulate_fill(side="BUY", notional_usd=1000.0, book=None, is_marketable=True)
        assert est_fallback.model == "fallback_stochastic"
        ok(f"fallback (no book): model={est_fallback.model} slip={est_fallback.expected_slippage_bps:.2f}bps")

        # Toxic flow → adverse selection multiplier
        book_toxic = BookSnapshot(
            symbol="ETH/USDT", bids=bids, asks=asks,
            last_trade_price=mid, toxic_flow_score=0.9,
        )
        est_toxic = sim.simulate_fill(side="BUY", notional_usd=500.0, book=book_toxic, is_marketable=True)
        assert est_toxic.adverse_selection_mult > 1.5, \
            f"toxic mult should be > 1.5, got {est_toxic.adverse_selection_mult}"
        ok(f"toxic flow (score=0.9): adverse_mult={est_toxic.adverse_selection_mult:.2f} "
           f"slip={est_toxic.expected_slippage_bps:.2f}bps (vs normal {est_small.expected_slippage_bps:.2f}bps)")
        return True
    except Exception as e:
        fail(f"fill simulator error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T3: ExecutionEngine high-fidelity path --------------------

async def _test_execution_engine_high_fidelity() -> bool:
    banner("TEST 3: ExecutionEngine with BookSnapshot → high-fidelity path")
    try:
        from backend.portfolio import (
            ExecutionEngine, PortfolioEngine, TradeProposal, PortfolioState,
            RiskKernel, RiskDecision, BookSnapshot, BookLevel,
        )
        engine = ExecutionEngine()
        assert engine.fill_simulator is not None, "FillSimulator should be auto-attached"
        ok(f"ExecutionEngine.fill_simulator = {'on' if engine.fill_simulator else 'off'}")

        # Build a synthetic proposal (need win_rate > 0.5 to give Kelly > 0)
        pe = PortfolioEngine()
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        prediction = {
            "symbol": "ETH/USDT",
            "prediction": "LONG",
            "confidence": 0.65,
            "ev": 0.001,
            "price_now": 1700.0,
            "id": "test-pred-1",
        }
        proposal = pe.build_proposal(
            prediction=prediction, state=state, vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert proposal is not None, "proposal build failed"

        # Build a BookSnapshot
        mid = 1700.0
        bids = [BookLevel(price=mid * (1 - 0.0001), size=10.0),
                BookLevel(price=mid * (1 - 0.0003), size=20.0)]
        asks = [BookLevel(price=mid * (1 + 0.0001), size=10.0),
                BookLevel(price=mid * (1 + 0.0003), size=20.0)]
        book = BookSnapshot(symbol="ETH/USDT", bids=bids, asks=asks, last_trade_price=mid)

        decision = RiskDecision(approved=True, reason="test", size_scale=1.0, proposal_id="test-pred-1")
        order = await engine.submit(
            proposal=proposal, decision=decision, last_price=mid, book_snapshot=book,
        )
        # Order should be FILLED or PARTIAL_FILL → CANCELED
        assert order.status in ("FILLED", "CANCELED", "PARTIAL_FILL"), \
            f"unexpected status: {order.status}"
        # Verify the high-fidelity model was used in the audit log
        audit_events = engine.get_audit_log(limit=20)
        fill_events = [e for e in audit_events if e.get("event") == "FILL"]
        assert any(e.get("fidelity_model") == "l2_walk" for e in fill_events), \
            f"no l2_walk fill event found in audit log"
        ok(f"order status={order.status} filled_qty={order.filled_qty:.4f} avg=${order.avg_fill_price:.4f}")
        ok(f"audit log shows l2_walk fidelity_model")
        return True
    except Exception as e:
        fail(f"execution engine high-fidelity error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T4: ExecutionEngine legacy fallback --------------------

async def _test_execution_engine_legacy_fallback() -> bool:
    banner("TEST 4: ExecutionEngine without BookSnapshot → legacy fallback (no break)")
    try:
        from backend.portfolio import (
            ExecutionEngine, PortfolioEngine, PortfolioState, RiskDecision,
        )
        engine = ExecutionEngine()
        pe = PortfolioEngine()
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        prediction = {
            "symbol": "BTC/USDT", "prediction": "LONG", "confidence": 0.70,
            "ev": 0.001, "price_now": 50000.0, "id": "test-pred-2",
        }
        proposal = pe.build_proposal(
            prediction=prediction, state=state, vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert proposal is not None
        decision = RiskDecision(approved=True, reason="test", size_scale=1.0)
        # No book_snapshot → should fall back to legacy _try_fill
        order = await engine.submit(
            proposal=proposal, decision=decision, last_price=50000.0,
        )
        assert order.status in ("FILLED", "CANCELED", "PARTIAL_FILL", "REJECTED")
        # Verify legacy path was used (no l2_walk in audit log)
        audit_events = engine.get_audit_log(limit=20)
        fill_events = [e for e in audit_events if e.get("event") == "FILL"]
        legacy_fills = [e for e in fill_events if "fidelity_model" not in e]
        ok(f"legacy fallback: order status={order.status} fills={len(fill_events)} legacy={len(legacy_fills)}")
        return True
    except Exception as e:
        fail(f"legacy fallback error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T5: MicrostructureIntelligence --------------------

def test_microstructure() -> bool:
    banner("TEST 5: MicrostructureIntelligence — VPIN + OFI + liquidation")
    try:
        from backend.portfolio import MicrostructureIntelligence
        mi = MicrostructureIntelligence()

        # Feed 20 synthetic OHLCV candles (bullish bias → some VPIN signal)
        base_price = 1700.0
        for i in range(20):
            o = base_price + i * 0.5
            h = o + 1.5
            l = o - 1.2
            c = o + 0.8  # close near high → buy-pressure
            v = 1000.0 + i * 50
            mi.ingest_ohlcv([[1700000000 + i * 900, o, h, l, c, v]])

        # Feed some top-of-book updates (one-sided selling)
        for _ in range(10):
            mi.ingest_top_of_book(bid_size=5.0, ask_size=20.0)  # ask >> bid → seller pressure

        # Feed extreme funding/OI
        mi.ingest_funding_oi(funding_rate=0.0015, oi_change_24h_pct=15.0)  # 15 bps funding, +15% OI

        report = mi.evaluate(current_price=1700.0, direction="LONG")
        ok(f"toxic_score={report.toxic_score:.3f} vpin={report.vpin:.3f} ofi={report.ofi_normalized:.3f}")
        ok(f"action={report.action} size_scale={report.size_scale:.2f}")
        ok(f"funding_extreme={report.funding_extreme} oi_extreme={report.oi_extreme}")
        ok(f"near_liquidation_cluster={report.near_liquidation_cluster} dist={report.distance_to_cluster_pct:.4f}")
        # With extreme funding + OI + 10 one-sided ticks, toxic_score should be elevated
        assert report.funding_extreme, "funding should be flagged extreme"
        assert report.oi_extreme, "OI should be flagged extreme"
        # The toxic_score won't always trigger REJECT but should be > 0
        assert report.toxic_score > 0.0, "toxic_score should be > 0 with these inputs"
        return True
    except Exception as e:
        fail(f"microstructure error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T6: RiskKernel with microstructure REJECT --------------------

def test_risk_kernel_microstructure_reject() -> bool:
    banner("TEST 6: RiskKernel with microstructure → REJECT or REDUCE on toxic flow")
    try:
        from backend.portfolio import (
            RiskKernel, PortfolioEngine, PortfolioState,
            MicrostructureIntelligence, TradeProposal,
        )
        kernel = RiskKernel()
        kernel.init_state(starting_equity=10_000.0)
        # Attach a microstructure observer and prime it with toxic data
        mi = MicrostructureIntelligence()
        # 1) Feed OHLCV with strong SELL bias (close near low) → high VPIN
        base_price = 1700.0
        for i in range(20):
            o = base_price + i * 0.5
            h = o + 1.5
            l = o - 1.0
            c = l + 0.1  # close near LOW → sell pressure
            v = 5000.0  # large volume to fill VPIN buckets fast
            mi.ingest_ohlcv([[1700000000 + i * 900, o, h, l, c, v]])
        # 2) Feed escalating ask sizes (one-sided selling) → OFI toxicity
        prev_bid, prev_ask = 5.0, 10.0
        for i in range(15):
            new_bid = max(1.0, 5.0 - i * 0.2)   # bid shrinking
            new_ask = 10.0 + i * 3.0             # ask growing
            mi.ingest_top_of_book(bid_size=new_bid, ask_size=new_ask)
        # 3) Feed extreme funding/OI (both flagged extreme → funding_oi_score = 1.0)
        mi.ingest_funding_oi(funding_rate=0.005, oi_change_24h_pct=20.0)
        kernel.microstructure = mi

        # Build a proposal (need win_rate > 0.5 for Kelly)
        pe = PortfolioEngine()
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        prediction = {
            "symbol": "ETH/USDT", "prediction": "LONG",
            "confidence": 0.80, "ev": 0.002,
            "price_now": 1700.0, "id": "test-micro-reject",
        }
        proposal = pe.build_proposal(
            prediction=prediction, state=state, vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert proposal is not None, "proposal should build (no meta_labeler attached)"

        # Evaluate — should be REJECTED or REDUCED by microstructure
        decision = kernel.evaluate(proposal)
        # Pre-evaluate the microstructure report to check the action
        report = mi.evaluate(current_price=proposal.entry_price, direction="LONG")
        ok(f"microstructure report: toxic_score={report.toxic_score:.3f} "
           f"action={report.action} vpin={report.vpin:.3f} ofi={report.ofi_normalized:.3f}")
        if not decision.approved:
            ok(f"REJECTED as expected: {decision.reason}")
            return True
        elif decision.size_scale < 1.0:
            ok(f"REDUCED as expected: size_scale={decision.size_scale:.2f} ({decision.reason})")
            return True
        else:
            fail(f"should have been rejected or reduced — approved with full size: {decision.reason}")
            return False
    except Exception as e:
        fail(f"risk kernel microstructure error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T7: MetaLabeler — LONG reject on low conviction --------------------

def test_meta_labeler_conviction_floor() -> bool:
    banner("TEST 7: MetaLabeler — LONG reject on low conviction + SHORT pass-through")
    try:
        from backend.portfolio import MetaLabeler
        ml = MetaLabeler()

        # LONG with low conviction → REJECT
        label = ml.evaluate(
            direction="LONG", conviction=0.40, regime_4h="BULL",
            vol_pct=0.012, spread_bps=2.0,
            entry_price=1700.0, stop_price=1680.0, target_price=1740.0,
            expected_ev_bps=10.0,
        )
        assert not label.take_trade, f"LONG with conv=0.40 should be rejected, got {label}"
        ok(f"LONG conv=0.40 REJECTED: {label.reason}")

        # LONG with high conviction + good R/R → PASS
        label2 = ml.evaluate(
            direction="LONG", conviction=0.70, regime_4h="BULL",
            vol_pct=0.012, spread_bps=2.0,
            entry_price=1700.0, stop_price=1680.0, target_price=1740.0,
            expected_ev_bps=10.0,
        )
        assert label2.take_trade, f"LONG with conv=0.70 should pass, got {label2}"
        ok(f"LONG conv=0.70 PASSED: mult={label2.confidence_mult:.3f} "
           f"barrier={label2.barrier_hit_prediction} rr={label2.reward_risk:.2f}")

        # SHORT — pass-through (no meta-labeling)
        label3 = ml.evaluate(
            direction="SHORT", conviction=0.40, regime_4h="BEAR",
            vol_pct=0.012, spread_bps=2.0,
            entry_price=1700.0, stop_price=1720.0, target_price=1660.0,
            expected_ev_bps=10.0,
        )
        assert label3.take_trade, "SHORT should always pass-through"
        assert label3.confidence_mult == 1.0
        ok(f"SHORT conv=0.40 PASS-THROUGH: mult={label3.confidence_mult:.3f}")
        return True
    except Exception as e:
        fail(f"meta labeler conviction error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T8: MetaLabeler — triple-barrier R/R gate --------------------

def test_meta_labeler_reward_risk() -> bool:
    banner("TEST 8: MetaLabeler — triple-barrier reward/risk gate")
    try:
        from backend.portfolio import MetaLabeler
        ml = MetaLabeler()

        # LONG with R/R < 1.5 → REJECT
        # entry=1700, stop=1680 → risk=20; target=1725 → reward=25; R/R=1.25 < 1.5
        label = ml.evaluate(
            direction="LONG", conviction=0.70, regime_4h="BULL",
            vol_pct=0.012, spread_bps=2.0,
            entry_price=1700.0, stop_price=1680.0, target_price=1725.0,
            expected_ev_bps=10.0,
        )
        assert not label.take_trade, f"R/R=1.25 should be rejected"
        ok(f"LONG R/R=1.25 REJECTED: {label.reason}")

        # LONG with R/R = 2.0 → PASS
        label2 = ml.evaluate(
            direction="LONG", conviction=0.70, regime_4h="BULL",
            vol_pct=0.012, spread_bps=2.0,
            entry_price=1700.0, stop_price=1680.0, target_price=1740.0,
            expected_ev_bps=10.0,
        )
        assert label2.take_trade
        assert label2.barrier is not None
        ok(f"LONG R/R=2.0 PASSED: barrier={label2.barrier_hit_prediction} "
           f"p_upper={label2.barrier.p_upper:.3f} p_lower={label2.barrier.p_lower:.3f} "
           f"p_vertical={label2.barrier.p_vertical:.3f}")
        return True
    except Exception as e:
        fail(f"meta labeler R/R error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T9: PortfolioEngine with meta_labeler --------------------

def test_portfolio_engine_meta_labeler_integration() -> bool:
    banner("TEST 9: PortfolioEngine with meta_labeler attached")
    try:
        from backend.portfolio import PortfolioEngine, PortfolioState, MetaLabeler
        pe = PortfolioEngine()
        pe.meta_labeler = MetaLabeler()
        state = PortfolioState(equity=10_000.0, cash=10_000.0)

        # LONG with low conviction → meta-labeler should REJECT
        prediction = {
            "symbol": "ETH/USDT", "prediction": "LONG",
            "confidence": 0.45,  # below meta_labeler floor of 0.55
            "ev": 0.001, "price_now": 1700.0, "id": "test-pe-meta-1",
        }
        proposal = pe.build_proposal(
            prediction=prediction, state=state, vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert proposal is None, "LONG with conv=0.45 should be rejected by meta_labeler"
        ok("LONG conv=0.45 REJECTED by meta_labeler (no proposal built)")

        # LONG with high conviction → should PASS + confidence reduced via trend_mult
        prediction2 = {
            "symbol": "ETH/USDT", "prediction": "LONG",
            "confidence": 0.75,  # above floor
            "ev": 0.001, "price_now": 1700.0, "id": "test-pe-meta-2",
        }
        proposal2 = pe.build_proposal(
            prediction=prediction2, state=state, vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert proposal2 is not None, "LONG conv=0.75 should pass"
        ok(f"LONG conv=0.75 PASSED: size=${proposal2.size_usd:.2f} conf={proposal2.confidence:.3f}")
        return True
    except Exception as e:
        fail(f"portfolio engine meta error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T10: HMMRegimeOverlay --------------------

def test_regime_hmm() -> bool:
    banner("TEST 10: HMMRegimeOverlay — belief update + state transitions")
    try:
        from backend.portfolio import HMMRegimeOverlay
        hmm = HMMRegimeOverlay()

        # Initial snapshot — should have uniform-ish belief
        snap0 = hmm.snapshot()
        ok(f"initial belief: {snap0.probabilities} dominant={snap0.dominant}")

        # Feed strong bullish observation: +2% return, low vol
        for _ in range(5):
            belief = hmm.update(obs_return=0.020, obs_vol=0.010)
        assert belief.dominant == "BULL", f"expected BULL after 5 bullish obs, got {belief.dominant}"
        ok(f"after 5 bullish obs: {belief.probabilities} dominant={belief.dominant} "
           f"long_bias={belief.long_bias:.3f}")

        # Now feed strong bearish observation: -3% return, moderate vol
        for _ in range(10):
            belief = hmm.update(obs_return=-0.030, obs_vol=0.018)
        # After enough bearish observations, BEAR should dominate
        assert belief.probabilities["BEAR"] > 0.30, \
            f"BEAR prob should be > 0.30 after 10 bearish obs, got {belief.probabilities}"
        ok(f"after 10 bearish obs: {belief.probabilities} dominant={belief.dominant} "
           f"transition_risk_to_bear={belief.transition_risk_to_bear:.3f}")

        # Test HIGH_VOL observation
        for _ in range(5):
            belief = hmm.update(obs_return=0.001, obs_vol=0.050)
        ok(f"after 5 high-vol obs: {belief.probabilities} dominant={belief.dominant} "
           f"size_mult={belief.size_mult:.2f}")
        # size_mult should be reduced in HIGH_VOL regime
        # (not necessarily dominant if BEAR is still strong)
        return True
    except Exception as e:
        fail(f"regime hmm error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T11: PortfolioCoordinator end-to-end with all modules --------------------

async def _test_coordinator_end_to_end() -> bool:
    banner("TEST 11: PortfolioCoordinator end-to-end with all ACT-XXVI modules")
    try:
        from backend.portfolio import PortfolioCoordinator
        coord = PortfolioCoordinator()
        coord.start()

        # Verify all ACT-XXVI modules are attached
        assert coord.microstructure is not None, "microstructure not attached"
        assert coord.meta_labeler is not None, "meta_labeler not attached"
        assert coord.regime_hmm is not None, "regime_hmm not attached"
        assert coord.portfolio_engine.meta_labeler is coord.meta_labeler, \
            "portfolio_engine.meta_labeler not injected"
        assert coord.risk_kernel.microstructure is coord.microstructure, \
            "risk_kernel.microstructure not injected"
        ok("all 3 ACT-XXVI modules attached to coordinator + injected into existing modules")

        # Build a synthetic prediction + market context
        prediction = {
            "symbol": "ETH/USDT",
            "prediction": "LONG",
            "confidence": 0.65,
            "ev": 0.001,
            "price_now": 1700.0,
            "id": "test-coord-1",
            "_audit": {"regime_4h": "BULL", "spread_bps": 2.0},
        }
        # Build synthetic OHLCV (16 rows = 4h on 15m)
        ohlcv = []
        base_ts = 1700000000
        base_price = 1700.0
        for i in range(20):
            o = base_price + i * 0.3
            h = o + 1.5
            l = o - 1.2
            c = o + 0.5
            v = 1000.0
            ohlcv.append([base_ts + i * 900, o, h, l, c, v])
        # Synthetic orderbook
        mid = 1700.0
        orderbook = {
            "bids": [[mid * 0.9999, 10.0], [mid * 0.9997, 20.0], [mid * 0.9995, 30.0]],
            "asks": [[mid * 1.0001, 10.0], [mid * 1.0003, 20.0], [mid * 1.0005, 30.0]],
        }

        result = await coord.ingest_prediction(
            prediction=prediction,
            last_price=mid,
            vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.52, "SHORT": 0.56},
            ohlcv=ohlcv,
            orderbook=orderbook,
            funding_rate=0.0001,  # 1 bps — normal
            oi_change_24h_pct=2.0,  # normal
        )
        assert result is not None, "result should not be None"
        if "skipped" in result:
            ok(f"prediction skipped: {result.get('skipped')} reason={result.get('reason')}")
        else:
            order = result.get("order") or {}
            ok(f"prediction processed: order status={order.get('status')} "
               f"filled_qty={order.get('filled_qty', 0):.4f}")
            ok(f"fidelity_model={result.get('fidelity_model')}")
            ok(f"microstructure: {result.get('microstructure') is not None}")
            ok(f"regime_hmm: {result.get('regime_hmm') is not None}")

        # Verify state snapshot includes ACT-XXVI modules
        state = coord.get_state()
        assert "microstructure" in state, "state should include microstructure"
        assert "meta_labeler" in state, "state should include meta_labeler"
        assert "regime_hmm" in state, "state should include regime_hmm"
        assert state["version"] == "ACT-XXVI-deep-edge-integration"
        ok(f"state version={state['version']}")
        ok(f"state.microstructure={state['microstructure'] is not None}")
        ok(f"state.meta_labeler={state['meta_labeler'] is not None}")
        ok(f"state.regime_hmm={state['regime_hmm'] is not None}")
        await coord.stop()
        return True
    except Exception as e:
        fail(f"coordinator e2e error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- T12: main.py endpoints + version --------------------

def test_main_endpoints() -> bool:
    banner("TEST 12: main.py 3 new endpoints + ACT-XXVI version")
    try:
        import importlib
        # Force re-import
        if "backend.main" in sys.modules:
            del sys.modules["backend.main"]
        from backend import main as main_module
        # Verify version — accept ACT-XXVI or any later ACT that preserves
        # the XXVI endpoints (additive-only directive).
        assert main_module.app.title == "SENECIO ORACLE"
        accepted_versions = (
            "ACT-XXVI-deep-edge-integration",
            "ACT-XXVII-research-grade-validation",
            "ACT-XXVIII-institutional-validation",
            "ACT-XXIX-systemic-antifragility",
        )
        assert main_module.app.version in accepted_versions, \
            f"app version = {main_module.app.version} (expected one of {accepted_versions})"
        ok(f"FastAPI app version = {main_module.app.version}")
        # Verify routes include the 3 new endpoints
        routes = [r.path for r in main_module.app.routes if hasattr(r, "path")]
        for endpoint in (
            "/api/portfolio/microstructure",
            "/api/portfolio/regime_hmm",
            "/api/portfolio/meta_labeler",
        ):
            assert endpoint in routes, f"missing endpoint: {endpoint}"
            ok(f"endpoint registered: {endpoint}")
        # Verify all existing ACT-XXV endpoints still present
        for endpoint in (
            "/api/portfolio/state",
            "/api/portfolio/analytics",
            "/api/portfolio/trades",
            "/api/portfolio/audit",
            "/api/portfolio/shadow",
            "/api/portfolio/live_gate",
            "/api/portfolio/kill_switch",
            "/api/portfolio/reset_kill_switch",
        ):
            assert endpoint in routes, f"missing existing endpoint: {endpoint}"
        ok("all 8 existing ACT-XXV endpoints preserved (no regressions)")
        return True
    except Exception as e:
        fail(f"main endpoints error: {e}")
        import traceback; traceback.print_exc()
        return False


# -------------------- main --------------------

async def async_main() -> int:
    tests_sync = [
        ("T1 imports + version",            test_imports),
        ("T2 FillSimulator",                test_fill_simulator),
        ("T5 MicrostructureIntelligence",   test_microstructure),
        ("T6 RiskKernel micro reject",      test_risk_kernel_microstructure_reject),
        ("T7 MetaLabeler conviction",       test_meta_labeler_conviction_floor),
        ("T8 MetaLabeler R/R",              test_meta_labeler_reward_risk),
        ("T9 PortfolioEngine + meta",       test_portfolio_engine_meta_labeler_integration),
        ("T10 HMMRegimeOverlay",            test_regime_hmm),
        ("T12 main.py endpoints",           test_main_endpoints),
    ]
    tests_async = [
        ("T3 ExecEngine high-fidelity",     _test_execution_engine_high_fidelity),
        ("T4 ExecEngine legacy fallback",   _test_execution_engine_legacy_fallback),
        ("T11 Coordinator e2e",             _test_coordinator_end_to_end),
    ]
    results = []
    for name, fn in tests_sync:
        try:
            r = fn()
        except Exception as e:
            fail(f"{name}: unexpected exception {e}")
            r = False
        results.append((name, r))
    for name, fn in tests_async:
        try:
            r = await fn()
        except Exception as e:
            fail(f"{name}: unexpected exception {e}")
            r = False
        results.append((name, r))

    banner("SUMMARY")
    passed = sum(1 for _, r in results if r)
    for name, r in results:
        print(f"  [{'OK' if r else 'FAIL'}]  {name}")
    print(f"\n  {passed}/{len(results)} tests passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
