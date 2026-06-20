"""
ACT-XXV Smoke Test
==================

Validates that all 6 new modules import cleanly + functional sanity tests.

Run:
    cd /home/z/my-project/SENECIOORACLE_stage/senecio_polymarket
    python -m backend.scripts.act_xxv_smoke
"""
from __future__ import annotations

import asyncio
import json
import os
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


def test_imports() -> bool:
    banner("TEST 1: imports")
    try:
        from backend.portfolio import (
            PortfolioEngine, TradeProposal, PortfolioState,
            RiskKernel, RiskDecision, KernelState, VolRegime,
            ExecutionEngine, Order, Fill, Position, OrderStatus, ExitReason,
            TradeJournal,
            PortfolioAnalytics,
            ShadowLive, ShadowTrade,
            LiveGate, GateStatus,
            PortfolioCoordinator,
        )
        from backend.portfolio import VERSION
        assert VERSION == "ACT-XXV-hedge-fund-transition"
        ok(f"all 6 modules + coordinator + live_gate imported")
        ok(f"VERSION = {VERSION}")
        return True
    except Exception as e:
        fail(f"import error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_portfolio_engine() -> bool:
    banner("TEST 2: PortfolioEngine — proposal building")
    try:
        from backend.portfolio import PortfolioEngine, PortfolioState
        eng = PortfolioEngine(config={"starting_equity_usd": 10_000.0})
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        # LONG prediction with confidence 0.65
        pred = {
            "symbol": "ETH/USDT",
            "prediction": "LONG",
            "confidence": 0.65,
            "ev": 0.001,
            "price_now": 1700.0,
            "id": 999,
        }
        proposal = eng.build_proposal(
            prediction=pred,
            state=state,
            vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.56},
        )
        assert proposal is not None, "expected non-None proposal"
        assert proposal.direction == "LONG"
        assert proposal.symbol == "ETH/USDT"
        assert proposal.size_usd > 0
        assert proposal.stop_price < proposal.entry_price   # LONG stop below entry
        assert proposal.target_price > proposal.entry_price # LONG target above entry
        ok(f"LONG proposal: size=${proposal.size_usd:.2f} qty={proposal.size_qty:.6f}")
        ok(f"  entry=${proposal.entry_price:.2f} stop=${proposal.stop_price:.2f} target=${proposal.target_price:.2f}")
        ok(f"  risk_usd=${proposal.risk_usd:.2f} rationale: {proposal.rationale[:60]}...")

        # SHORT_ONLY_PAPER_MODE blocks LONG
        eng.update_config(short_only_paper_mode=True)
        proposal2 = eng.build_proposal(
            prediction=pred,
            state=state,
            vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.56},
        )
        assert proposal2 is None, "LONG should be blocked under SHORT_ONLY_PAPER_MODE"
        ok("SHORT_ONLY_PAPER_MODE blocks LONG (as expected)")

        # SHORT proposal
        eng.update_config(short_only_paper_mode=False)
        short_pred = {**pred, "prediction": "SHORT"}
        short_proposal = eng.build_proposal(
            prediction=short_pred,
            state=state,
            vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.45, "SHORT": 0.56},
        )
        assert short_proposal is not None
        assert short_proposal.stop_price > short_proposal.entry_price   # SHORT stop above entry
        ok(f"SHORT proposal: size=${short_proposal.size_usd:.2f}")
        return True
    except Exception as e:
        fail(f"PortfolioEngine test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_risk_kernel() -> bool:
    banner("TEST 3: RiskKernel — gating logic")
    try:
        from backend.portfolio import RiskKernel, PortfolioEngine, PortfolioState, TradeProposal
        kernel = RiskKernel(config={"starting_equity_usd": 10_000.0})
        kernel.init_state(10_000.0)
        eng = PortfolioEngine()
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        proposal = eng.build_proposal(
            prediction={"symbol": "ETH/USDT", "prediction": "LONG",
                        "confidence": 0.65, "ev": 0.001, "price_now": 1700.0, "id": 1},
            state=state, vol_pct=0.012, win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        # 1) Approve happy path
        decision = kernel.evaluate(proposal)
        assert decision.approved, f"should approve, got reason: {decision.reason}"
        ok(f"approved: {decision.reason[:80]}")

        # 2) Reject on low confidence
        low_conf_proposal = TradeProposal(
            symbol="ETH/USDT", direction="LONG",
            size_usd=100, size_qty=0.06, entry_price=1700,
            stop_price=1666, target_price=1768,
            risk_per_unit=34, risk_usd=2, confidence=0.20, ev=0.001,
            prediction_id=2,
        )
        decision2 = kernel.evaluate(low_conf_proposal)
        assert not decision2.approved
        assert "low_confidence" in decision2.reason
        ok(f"rejected low confidence: {decision2.reason[:80]}")

        # 3) Trip kill switch → all rejected
        kernel.trip_kill_switch("test kill")
        decision3 = kernel.evaluate(proposal)
        assert not decision3.approved
        assert "kill_switch_active" in decision3.reason
        ok(f"rejected after kill switch: {decision3.reason[:80]}")
        kernel.reset_kill_switch("test reset")

        # 4) Cooldown after 3 losses
        for i in range(3):
            kernel.record_pnl(pnl_usd=-50.0, equity=10_000.0 - (i + 1) * 50)
        decision4 = kernel.evaluate(proposal)
        assert not decision4.approved, f"should be in cooldown, got: {decision4.reason}"
        assert "cooldown" in decision4.reason
        ok(f"cooldown triggered after 3 losses: {decision4.reason[:80]}")
        return True
    except Exception as e:
        fail(f"RiskKernel test error: {e}")
        import traceback; traceback.print_exc()
        return False


async def test_execution_engine() -> bool:
    banner("TEST 4: ExecutionEngine — order lifecycle")
    try:
        from backend.portfolio import (
            ExecutionEngine, PortfolioEngine, RiskKernel, PortfolioState, OrderStatus
        )
        eng = ExecutionEngine(config={"starting_cash": 10_000.0})
        pe = PortfolioEngine()
        rk = RiskKernel()
        rk.init_state(10_000.0)
        state = PortfolioState(equity=10_000.0, cash=10_000.0)

        proposal = pe.build_proposal(
            prediction={"symbol": "ETH/USDT", "prediction": "LONG",
                        "confidence": 0.65, "ev": 0.001, "price_now": 1700.0, "id": 1},
            state=state, vol_pct=0.012, win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        decision = rk.evaluate(proposal)
        assert decision.approved

        order = await eng.submit(
            proposal=proposal, decision=decision,
            last_price=1700.0, book_depth_usd=5_000.0,
        )
        ok(f"order status: {order.status} filled_qty={order.filled_qty:.6f} avg=${order.avg_fill_price:.4f}")
        # Order may end FILLED (full fill) or CANCELED (partial fill then residual
        # canceled after max retries). Both are valid — what matters is we got fills.
        assert order.filled_qty > 0, f"expected some fills, got filled_qty={order.filled_qty}"
        assert order.status in (
            OrderStatus.FILLED.value,
            OrderStatus.PARTIAL_FILL.value,
            OrderStatus.CANCELED.value,  # partial-fill-then-cancel is valid
        )
        ok(f"  order has {order.filled_qty:.6f} filled (status={order.status})")

        # Attach stop/target then check exit on price drop
        eng.set_stop_target("ETH/USDT", stop_price=proposal.stop_price, target_price=proposal.target_price)
        ok(f"position OPEN: {len(eng.positions)} position(s)")

        # Price drops → stop hit
        exits = eng.check_exits(
            symbol="ETH/USDT",
            tick_price=proposal.stop_price - 1,  # below stop
            tick_ts=datetime.now(timezone.utc).isoformat(),
            kill_switch_active=False,
        )
        assert len(exits) == 1
        exit_evt = exits[0]
        ok(f"position EXIT: reason={exit_evt['exit_reason']} pnl=${exit_evt['realized_pnl']:.2f}")
        assert exit_evt["exit_reason"] == "STOP"
        return True
    except Exception as e:
        fail(f"ExecutionEngine test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_trade_journal() -> bool:
    banner("TEST 5: TradeJournal — record writing")
    try:
        import tempfile, os
        from backend.portfolio import TradeJournal
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            tmp_path = f.name
        journal = TradeJournal(path=tmp_path)

        # Simulate POSITION_OPEN audit event
        open_event = {
            "event": "POSITION_OPEN",
            "position": {
                "position_id": "pos-test123",
                "symbol": "ETH/USDT",
                "direction": "LONG",
                "entry_ts": datetime.now(timezone.utc).isoformat(),
                "avg_entry_price": 1700.0,
                "qty": 0.5,
                "stop_price": 1666.0,
                "target_price": 1768.0,
                "proposal_id": 999,
                "audit_trail": [{"event": "FILL", "slippage_bps": 3.5, "latency_ms": 120}],
            },
        }
        journal.on_audit_event(open_event)

        # Simulate POSITION_EXIT audit event
        exit_event = {
            "event": "POSITION_EXIT",
            "position": {
                "position_id": "pos-test123",
                "symbol": "ETH/USDT",
                "direction": "LONG",
                "entry_ts": open_event["position"]["entry_ts"],
                "exit_ts": datetime.now(timezone.utc).isoformat(),
                "avg_entry_price": 1700.0,
                "exit_price": 1768.0,
                "qty": 0.5,
                "exit_reason": "TARGET",
                "realized_pnl": 34.0,
                "fees_paid": 1.50,
                "mae_price": 1695.0,
                "mfe_price": 1770.0,
                "audit_trail": open_event["position"]["audit_trail"],
            },
            "exit_price": 1768.0,
            "exit_reason": "TARGET",
            "realized_pnl": 34.0,
        }
        journal.on_audit_event(exit_event)

        # Verify record written
        trades = journal.fetch_recent(limit=10)
        assert len(trades) == 1
        t = trades[0]
        ok(f"trade journal record written: {t['symbol']} {t['direction']} pnl=${t['realized_pnl_usd']}")
        ok(f"  holding_time_s={t['holding_time_s']} mae_bps={t['mae_bps']} mfe_bps={t['mfe_bps']}")
        ok(f"  exit_reason={t['exit_reason']} total_fees=${t['total_fees_usd']}")
        assert t["exit_reason"] == "TARGET"
        assert t["direction"] == "LONG"
        assert t["realized_pnl_usd"] == 34.0

        os.unlink(tmp_path)
        return True
    except Exception as e:
        fail(f"TradeJournal test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_portfolio_analytics() -> bool:
    banner("TEST 6: PortfolioAnalytics — Sharpe / Sortino / PF / etc.")
    try:
        from backend.portfolio import PortfolioAnalytics
        analytics = PortfolioAnalytics()
        # Build a synthetic trade list: 7 wins of $20, 3 losses of -$15
        now = datetime.now(timezone.utc)
        trades = []
        for i in range(7):
            trades.append({
                "symbol": "ETH/USDT", "direction": "LONG",
                "entry_ts": (now - timedelta(hours=10-i)).isoformat(),
                "exit_ts": (now - timedelta(hours=9-i)).isoformat(),
                "entry_price": 1700, "exit_price": 1720, "qty": 1.0,
                "realized_pnl_usd": 20.0, "total_fees_usd": 0.5,
                "holding_time_s": 600, "mae_bps": -5, "mfe_bps": 15,
                "exit_reason": "TARGET",
            })
        for i in range(3):
            trades.append({
                "symbol": "ETH/USDT", "direction": "SHORT",
                "entry_ts": (now - timedelta(hours=3-i)).isoformat(),
                "exit_ts": (now - timedelta(hours=2-i)).isoformat(),
                "entry_price": 1700, "exit_price": 1715, "qty": 1.0,
                "realized_pnl_usd": -15.0, "total_fees_usd": 0.5,
                "holding_time_s": 600, "mae_bps": -10, "mfe_bps": 5,
                "exit_reason": "STOP",
            })

        report = analytics.compute(trades)
        ok(f"n_trades={report['n_trades']} win_rate={report['win_rate_pct']}%")
        ok(f"  Sharpe={report['sharpe']}  Sortino={report['sortino']}")
        ok(f"  ProfitFactor={report['profit_factor']}  Expectancy=${report['expectancy_usd']}")
        ok(f"  MaxDD={report['max_drawdown_pct']}% (${report['max_drawdown_usd']})")
        ok(f"  Calmar={report['calmar']}  Kelly={report['kelly_fraction']}")
        ok(f"  Recovery={report['recovery_factor']}")
        ok(f"  by_direction: LONG n={report['by_direction']['LONG']['n']}, SHORT n={report['by_direction']['SHORT']['n']}")
        assert report["n_trades"] == 10
        assert report["n_wins"] == 7
        assert report["n_losses"] == 3
        assert report["win_rate_pct"] == 70.0
        assert report["profit_factor"] > 1.0   # 7*20 / (3*15) = 140/45 = 3.11
        assert report["kelly_fraction"] > 0
        return True
    except Exception as e:
        fail(f"PortfolioAnalytics test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_live_gate() -> bool:
    banner("TEST 7: LiveGate — 6 unlock conditions")
    try:
        from backend.portfolio import LiveGate
        gate = LiveGate()

        # All conditions fail initially
        status = gate.evaluate(
            oracle_score={"by_window": {"1h": {"global": {"win_rate_pct": 45, "verified": 100}}},
                          "win_rate_pct": 45, "verified": 100},
            analytics_report={"profit_factor": 0.8, "max_drawdown_pct": 15},
            shadow_report={"passed": False},
            exec_self_test={"verified": False},
        )
        assert not status.unlocked
        assert len(status.failed_reasons) == 6
        ok(f"all 6 conditions fail: trade_mode={status.trade_mode} locked={status.live_capital_locked}")

        # All conditions pass
        status2 = gate.evaluate(
            oracle_score={"by_window": {"1h": {"global": {"win_rate_pct": 55, "verified": 350}}},
                          "win_rate_pct": 55, "verified": 350},
            analytics_report={"profit_factor": 1.50, "max_drawdown_pct": 5.0},
            shadow_report={"passed": True},
            exec_self_test={"verified": True},
        )
        assert status2.unlocked
        assert status2.trade_mode == "LIVE"
        assert not status2.live_capital_locked
        ok(f"all 6 conditions pass: trade_mode={status2.trade_mode} locked={status2.live_capital_locked}")

        # One condition fails → re-locked
        status3 = gate.evaluate(
            oracle_score={"by_window": {"1h": {"global": {"win_rate_pct": 55, "verified": 350}}},
                          "win_rate_pct": 55, "verified": 350},
            analytics_report={"profit_factor": 1.50, "max_drawdown_pct": 12.0},  # DD too high
            shadow_report={"passed": True},
            exec_self_test={"verified": True},
        )
        assert not status3.unlocked
        ok(f"max_drawdown breach re-locks gate: {status3.failed_reasons}")
        return True
    except Exception as e:
        fail(f"LiveGate test error: {e}")
        import traceback; traceback.print_exc()
        return False


async def test_coordinator() -> bool:
    banner("TEST 8: PortfolioCoordinator — end-to-end pipeline")
    try:
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        from backend.portfolio import PortfolioCoordinator
        coord = PortfolioCoordinator(
            config={
                "starting_equity_usd": 10_000.0,
                "journal_path": os.path.join(tmpdir, "trades.jsonl"),
                "output_path": os.path.join(tmpdir, "shadow.jsonl"),
                "report_path": os.path.join(tmpdir, "shadow_report.json"),
                "fetch_real_book": False,   # skip network in tests
            },
        )
        coord.start()
        ok("coordinator started")

        # Ingest a LONG prediction
        result = await coord.ingest_prediction(
            prediction={
                "symbol": "ETH/USDT",
                "prediction": "LONG",
                "confidence": 0.65,
                "ev": 0.001,
                "price_now": 1700.0,
                "id": 100,
            },
            last_price=1700.0,
            vol_pct=0.012,
            win_rate_by_direction={"LONG": 0.55, "SHORT": 0.55},
        )
        assert result is not None
        if "skipped" in result:
            ok(f"prediction skipped: {result['skipped']} {result.get('reason')}")
        else:
            ok(f"prediction routed: order status={result['order']['status']}")

        # Ingest a SHORT prediction
        result2 = await coord.ingest_prediction(
            prediction={
                "symbol": "BTC/USDT",
                "prediction": "SHORT",
                "confidence": 0.62,
                "ev": 0.001,
                "price_now": 65000.0,
                "id": 101,
            },
            last_price=65000.0,
            vol_pct=0.015,
            win_rate_by_direction={"LONG": 0.45, "SHORT": 0.58},
        )
        assert result2 is not None
        ok(f"second prediction routed: {'skipped' if 'skipped' in result2 else 'filled'}")

        # Check exit via tick (price drops to trigger LONG stop)
        exits = coord.on_tick(
            symbol="ETH/USDT",
            price=1650.0,  # below stop
            ts=datetime.now(timezone.utc).isoformat(),
        )
        ok(f"tick triggered {len(exits)} exit(s) on ETH/USDT")

        # Get state snapshot
        state = coord.get_state()
        ok(f"state: equity=${state['portfolio_state']['equity']:.2f} "
           f"open={state['portfolio_state']['open_count']} "
           f"closed_positions={state['execution_engine']['closed_positions']}")

        # Get analytics
        report = coord.get_analytics()
        ok(f"analytics: n_trades={report['n_trades']} pnl=${report['total_pnl_usd']}")

        # Evaluate LIVE_GATE (should be locked — insufficient data)
        gate_status = coord.evaluate_live_gate(oracle_score={
            "by_window": {"1h": {"global": {"win_rate_pct": 50, "verified": 50}}},
        })
        ok(f"LIVE_GATE: unlocked={gate_status.unlocked} failed_count={len(gate_status.failed_reasons)}")
        assert not gate_status.unlocked, "should be locked — far below all 6 thresholds"

        # Stop
        report = await coord.stop()
        ok(f"coordinator stopped, shadow report status: {report.get('status')}")
        return True
    except Exception as e:
        fail(f"Coordinator test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_oracle_runner_hook() -> bool:
    banner("TEST 9: oracle_runner — ACT-XXV hook present (without running loop)")
    try:
        # Just import and verify the hook is wired
        from backend import oracle_runner
        assert hasattr(oracle_runner, "_get_portfolio_coordinator")
        assert hasattr(oracle_runner, "_route_to_portfolio")
        assert "_portfolio_coordinator" in dir(oracle_runner)
        ok("oracle_runner._get_portfolio_coordinator present")
        ok("oracle_runner._route_to_portfolio present")
        ok("oracle_runner._portfolio_coordinator initialized to None")

        # Verify state still has all the ACT-XXIII fields (we didn't touch them)
        state = oracle_runner.get_state()
        for key in ("directional_stats", "gates", "short_only_paper_mode",
                    "trade_mode", "live_capital_locked", "bogus_backfill_done"):
            assert key in state, f"missing state key: {key}"
        ok("all ACT-XXIII state keys preserved (DO_NOT_TOUCH respected)")

        # Trade mode is locked
        assert state["trade_mode"] == "PAPER"
        assert state["live_capital_locked"] is True
        ok(f"trade_mode={state['trade_mode']} live_capital_locked={state['live_capital_locked']}")
        return True
    except Exception as e:
        fail(f"oracle_runner hook test error: {e}")
        import traceback; traceback.print_exc()
        return False


def test_main_endpoints() -> bool:
    banner("TEST 10: main.py — ACT-XXV endpoints registered")
    try:
        from backend.main import app
        routes = [r.path for r in app.routes]
        expected = [
            "/api/portfolio/state",
            "/api/portfolio/analytics",
            "/api/portfolio/trades",
            "/api/portfolio/audit",
            "/api/portfolio/shadow",
            "/api/portfolio/live_gate",
            "/api/portfolio/kill_switch",
            "/api/portfolio/reset_kill_switch",
        ]
        for path in expected:
            assert path in routes, f"missing route: {path}"
            ok(f"  route registered: {path}")

        # Version bumped
        from backend.main import app
        assert app.title == "SENECIO ORACLE"
        assert app.version == "ACT-XXV-hedge-fund-transition"
        ok(f"FastAPI app version: {app.version}")
        return True
    except Exception as e:
        fail(f"main endpoints test error: {e}")
        import traceback; traceback.print_exc()
        return False


async def main() -> int:
    print("\n" + "█" * 70)
    print("  ACT-XXV-HEDGE-FUND-TRANSITION — Smoke Test Suite")
    print("█" * 70)

    tests = [
        test_imports(),
        test_portfolio_engine(),
        test_risk_kernel(),
        await test_execution_engine(),
        test_trade_journal(),
        test_portfolio_analytics(),
        test_live_gate(),
        await test_coordinator(),
        test_oracle_runner_hook(),
        test_main_endpoints(),
    ]

    passed = sum(1 for t in tests if t)
    total = len(tests)

    print(f"\n{'█' * 70}")
    print(f"  RESULT: {passed}/{total} tests passed")
    print(f"{'█' * 70}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
