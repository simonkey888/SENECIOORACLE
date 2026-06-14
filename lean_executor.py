"""
Module: lean_executor.py — LEAN-STYLE EXECUTION ENGINE

PHILOSOPHY: execution_is_law_not_signal

The executor is NOT a signal generator. It is a RULE ENGINE that
determines whether a proposed action can actually be executed
given current market conditions.

Components:
    1. order_manager    — position tracking, order routing
    2. slippage_model   — market impact estimation (deterministic)
    3. fill_model       — partial fill estimation
    4. latency_model    — signal decay from time delay

RULES:
    - Execution NEVER improves a signal. Reality only degrades.
    - Slippage is always positive (you always pay the spread).
    - Latency always reduces edge (information decays).
    - Partial fills are the norm, not the exception.
    - If execution costs > expected edge → NO TRADE.

DETERMINISTIC: same inputs → same execution assessment
"""

import math
import time
import sys
import os
from collections import deque
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# Slippage Model
# ---------------------------------------------------------------------------

class SlippageModel:
    """Deterministic slippage estimation.

    Slippage = base_slippage + market_impact + volatility_adjustment

    Where:
    - base_slippage: minimum slippage (spread + commission equivalent)
    - market_impact: proportional to position_size / orderbook_depth
    - volatility_adjustment: higher vol → higher slippage

    Slippage is ALWAYS positive (you always pay).
    """

    def __init__(
        self,
        base_slippage_bps: float = 2.0,     # 2 bps = 0.02%
        impact_coefficient: float = 0.1,     # How much size affects price
        vol_adjustment_factor: float = 0.5,  # Vol multiplier on slippage
        max_slippage_bps: float = 50.0,      # Hard cap on slippage
    ):
        self.base_slippage_bps = base_slippage_bps
        self.impact_coefficient = impact_coefficient
        self.vol_adjustment_factor = vol_adjustment_factor
        self.max_slippage_bps = max_slippage_bps

        # Track realized slippage for feedback
        self._realized_slippage = deque(maxlen=50)

    def estimate_slippage(
        self,
        position_usdt: float,
        orderbook_depth_usdt: float = 500000.0,
        volatility_pct: float = 2.0,
        spread_bps: float = 1.0,
    ) -> dict:
        """Estimate slippage for a proposed order.

        Args:
            position_usdt: Size of the proposed position in USDT.
            orderbook_depth_usdt: Available depth within 0.5% of mid.
            volatility_pct: Current volatility as percentage.
            spread_bps: Current bid-ask spread in basis points.

        Returns:
            Dict with slippage estimates.
        """
        # Base: max of configured base and actual spread
        base = max(self.base_slippage_bps, spread_bps)

        # Market impact: proportional to size/depth
        if orderbook_depth_usdt > 0:
            participation_rate = position_usdt / orderbook_depth_usdt
        else:
            participation_rate = 1.0

        impact_bps = participation_rate * self.impact_coefficient * 10000
        impact_bps = min(impact_bps, self.max_slippage_bps * 0.5)

        # Volatility adjustment: higher vol → wider spreads → more slippage
        vol_adj = (volatility_pct / 2.0) * self.vol_adjustment_factor

        # Total slippage
        total_bps = base + impact_bps + vol_adj
        total_bps = min(total_bps, self.max_slippage_bps)

        # Slippage as percentage
        slippage_pct = total_bps / 10000.0

        return {
            "slippage_bps": round(total_bps, 2),
            "slippage_pct": round(slippage_pct, 8),
            "base_bps": round(base, 2),
            "impact_bps": round(impact_bps, 2),
            "vol_adj_bps": round(vol_adj, 2),
            "participation_rate": round(participation_rate, 6),
        }

    def record_realized_slippage(self, slippage_bps: float):
        """Record realized slippage for feedback."""
        self._realized_slippage.append(slippage_bps)

    def get_avg_realized_slippage(self) -> float:
        """Get average realized slippage."""
        if not self._realized_slippage:
            return self.base_slippage_bps
        return sum(self._realized_slippage) / len(self._realized_slippage)


# ---------------------------------------------------------------------------
# Fill Model
# ---------------------------------------------------------------------------

class FillModel:
    """Estimate fill probability and expected fill percentage.

    Fill quality depends on:
    - Liquidity depth vs position size
    - Volatility (higher vol = more price movement = harder fills)
    - Time available (longer = better fills)
    - Spread (wider = worse fills)
    """

    def __init__(
        self,
        min_fill_pct: float = 0.80,   # Minimum acceptable fill
        depth_coverage_ratio: float = 0.3,  # Max of depth to use
    ):
        self.min_fill_pct = min_fill_pct
        self.depth_coverage_ratio = depth_coverage_ratio

    def estimate_fill(
        self,
        position_usdt: float,
        orderbook_depth_usdt: float = 500000.0,
        volatility_pct: float = 2.0,
        spread_bps: float = 1.0,
    ) -> dict:
        """Estimate fill quality.

        Args:
            position_usdt: Size of the proposed position.
            orderbook_depth_usdt: Available depth.
            volatility_pct: Current volatility.
            spread_bps: Current spread.

        Returns:
            Dict with fill estimates.
        """
        # How much of the depth can we realistically use?
        usable_depth = orderbook_depth_usdt * self.depth_coverage_ratio

        # Base fill = min(position, usable_depth) / position
        if position_usdt > 0:
            fill_pct = min(1.0, usable_depth / position_usdt)
        else:
            fill_pct = 1.0

        # Volatility penalty: high vol → partial fills more likely
        vol_penalty = min(0.3, volatility_pct / 20.0)
        fill_pct = max(0.0, fill_pct - vol_penalty)

        # Spread penalty: wide spread → worse fills
        if spread_bps > 10:
            fill_pct = max(0.0, fill_pct - (spread_bps - 10) / 100.0)

        fill_pct = _clamp(fill_pct, 0.0, 1.0)

        # Fill probability
        fill_prob = fill_pct if fill_pct >= self.min_fill_pct else fill_pct * 0.5

        return {
            "expected_fill_pct": round(fill_pct, 4),
            "fill_probability": round(fill_prob, 4),
            "usable_depth_usdt": round(usable_depth, 2),
            "vol_penalty": round(vol_penalty, 4),
            "acceptable": fill_pct >= self.min_fill_pct,
        }


# ---------------------------------------------------------------------------
# Latency Model
# ---------------------------------------------------------------------------

class LatencyModel:
    """Estimate signal decay from execution latency.

    Edge decays with time. The longer the delay between signal
    and execution, the less edge remains.

    Decay model: edge * exp(-lambda * latency)
    Where lambda = 1 / half_life
    """

    def __init__(
        self,
        edge_half_life_ms: float = 5000.0,  # 5 second edge half-life
        min_latency_ms: float = 200.0,       # Minimum realistic latency
        max_latency_ms: float = 3000.0,      # Maximum acceptable latency
    ):
        self.edge_half_life_ms = edge_half_life_ms
        self.min_latency_ms = min_latency_ms
        self.max_latency_ms = max_latency_ms
        self._signal_time = None
        self._lambda = math.log(2) / edge_half_life_ms

    def set_signal_time(self, timestamp_ms: Optional[float] = None):
        """Record when the signal was generated."""
        self._signal_time = timestamp_ms or time.time() * 1000

    def estimate_latency(self, cycle: int = 0) -> dict:
        """Estimate execution latency.

        Latency varies based on:
        - Base processing time
        - Exchange API response time
        - Network conditions (simulated deterministically)

        Args:
            cycle: Current cycle number (for deterministic variation).

        Returns:
            Dict with latency estimates.
        """
        # Deterministic latency: base + cycle-dependent variation
        variation = (cycle % 100) / 100.0
        latency_ms = self.min_latency_ms + variation * (self.max_latency_ms - self.min_latency_ms)

        # Edge retention: how much edge survives the latency
        edge_retention = math.exp(-self._lambda * latency_ms)

        # Signal age (if signal time was set)
        signal_age_ms = 0.0
        if self._signal_time:
            signal_age_ms = max(0, time.time() * 1000 - self._signal_time)

        total_delay_ms = latency_ms + signal_age_ms
        total_edge_retention = math.exp(-self._lambda * total_delay_ms)

        return {
            "execution_latency_ms": round(latency_ms, 1),
            "signal_age_ms": round(signal_age_ms, 1),
            "total_delay_ms": round(total_delay_ms, 1),
            "edge_retention": round(edge_retention, 6),
            "total_edge_retention": round(total_edge_retention, 6),
            "acceptable": latency_ms <= self.max_latency_ms,
        }


# ---------------------------------------------------------------------------
# LEAN-STYLE EXECUTOR
# ---------------------------------------------------------------------------

class LeanExecutor:
    """THE execution authority.

    execution_is_law_not_signal

    The executor takes a proposed action_vector from the Decision Core
    and determines:
    1. Can it be executed? (liquidity, slippage, fill quality)
    2. At what cost? (commission, slippage, latency decay)
    3. Is it still profitable after costs? (realized edge > 0)
    4. What's the final execution quality? (audit trail)

    The executor NEVER improves a signal. Reality only degrades.
    If costs exceed edge → NO TRADE.

    This is LEAN-style: execution is a constraint, not an optimization.
    """

    def __init__(
        self,
        # ── Commission ──
        commission_rate: float = 0.0002,  # 0.02% maker fee
        # ── Slippage model ──
        base_slippage_bps: float = 2.0,
        impact_coefficient: float = 0.1,
        vol_adjustment_factor: float = 0.5,
        max_slippage_bps: float = 50.0,
        # ── Fill model ──
        min_fill_pct: float = 0.80,
        # ── Latency model ──
        edge_half_life_ms: float = 5000.0,
        min_latency_ms: float = 200.0,
        max_latency_ms: float = 3000.0,
        # ── Quality thresholds ──
        min_execution_quality: float = 0.30,
        min_realized_edge: float = 0.0,    # Must be positive after costs
    ):
        """Initialize the LEAN Executor.

        Args:
            commission_rate: Trading commission rate.
            base_slippage_bps: Base slippage in basis points.
            impact_coefficient: Market impact coefficient.
            vol_adjustment_factor: Volatility slippage multiplier.
            max_slippage_bps: Maximum acceptable slippage.
            min_fill_pct: Minimum acceptable fill percentage.
            edge_half_life_ms: Edge decay half-life in milliseconds.
            min_latency_ms: Minimum execution latency.
            max_latency_ms: Maximum acceptable latency.
            min_execution_quality: Minimum quality score to execute.
            min_realized_edge: Minimum realized edge after costs.
        """
        self.commission_rate = commission_rate
        self.min_execution_quality = min_execution_quality
        self.min_realized_edge = min_realized_edge

        # Sub-models
        self.slippage = SlippageModel(
            base_slippage_bps=base_slippage_bps,
            impact_coefficient=impact_coefficient,
            vol_adjustment_factor=vol_adjustment_factor,
            max_slippage_bps=max_slippage_bps,
        )
        self.fill = FillModel(min_fill_pct=min_fill_pct)
        self.latency = LatencyModel(
            edge_half_life_ms=edge_half_life_ms,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
        )

        # Execution history
        self._execution_log = deque(maxlen=500)
        self._total_commission_paid = 0.0
        self._total_slippage_paid = 0.0

    def assess(
        self,
        action_vector: dict,
        capital: float,
        orderbook_depth_usdt: float = 500000.0,
        volatility_pct: float = 2.0,
        spread_bps: float = 1.0,
        cycle: int = 0,
    ) -> dict:
        """Assess whether an action_vector can be executed.

        This is the main execution assessment. It determines:
        1. Position size in USDT
        2. Estimated slippage
        3. Expected fill quality
        4. Latency impact on edge
        5. Realized edge after all costs
        6. Final execution quality score
        7. EXECUTE / HOLD decision

        Args:
            action_vector: From SingleDecisionCore.produce_action().
            capital: Current available capital.
            orderbook_depth_usdt: Available orderbook depth.
            volatility_pct: Current volatility.
            spread_bps: Current spread in bps.
            cycle: Current cycle (for deterministic latency).

        Returns:
            Execution assessment dict.
        """
        action = action_vector.get("action", "HOLD")
        size_pct = action_vector.get("size", 0.0)
        side = action_vector.get("side")

        # Non-execute actions pass through
        if action != "EXECUTE":
            return {
                "action": action,
                "reason": f"core_verdict_{action.lower()}",
                "position_usdt": 0.0,
                "realized_edge": 0.0,
                "slippage": self.slippage.estimate_slippage(0, orderbook_depth_usdt, volatility_pct, spread_bps),
                "fill": self.fill.estimate_fill(0, orderbook_depth_usdt, volatility_pct, spread_bps),
                "latency": self.latency.estimate_latency(cycle),
                "execution_quality": 0.0,
                "commission_usdt": 0.0,
            }

        if not side or size_pct <= 0:
            return {
                "action": "HOLD",
                "reason": "no_side_or_size",
                "position_usdt": 0.0,
                "realized_edge": 0.0,
                "slippage": self.slippage.estimate_slippage(0, orderbook_depth_usdt, volatility_pct, spread_bps),
                "fill": self.fill.estimate_fill(0, orderbook_depth_usdt, volatility_pct, spread_bps),
                "latency": self.latency.estimate_latency(cycle),
                "execution_quality": 0.0,
                "commission_usdt": 0.0,
            }

        # ── Position sizing ──
        position_usdt = capital * size_pct

        # ── Slippage estimation ──
        slip = self.slippage.estimate_slippage(
            position_usdt, orderbook_depth_usdt, volatility_pct, spread_bps
        )

        # ── Fill estimation ──
        fill_est = self.fill.estimate_fill(
            position_usdt, orderbook_depth_usdt, volatility_pct, spread_bps
        )

        # ── Latency estimation ──
        lat = self.latency.estimate_latency(cycle)

        # ── Cost calculation ──
        commission_usdt = position_usdt * self.commission_rate
        slippage_usdt = position_usdt * slip["slippage_pct"]
        total_cost_usdt = commission_usdt + slippage_usdt
        total_cost_pct = total_cost_usdt / position_usdt if position_usdt > 0 else 0

        # ── Edge after costs ──
        theoretical_edge = action_vector.get("pipeline", {}).get("step4_ev", {}).get("adjusted_ev", 0)
        if theoretical_edge == 0:
            theoretical_edge = action_vector.get("step4_ev", {}).get("adjusted_ev", 0)
        latency_decay = lat.get("edge_retention", 1.0)
        realized_edge = theoretical_edge * latency_decay - total_cost_pct

        # ── Execution quality score ──
        # Composite: fill * edge_retention * (1 - slippage_ratio)
        slippage_ratio = min(1.0, slip["slippage_pct"] / 0.005)  # 50bps = terrible
        quality = fill_est["expected_fill_pct"] * latency_decay * (1.0 - slippage_ratio * 0.5)
        quality = _clamp(quality, 0.0, 1.0)

        # ── EXECUTION DECISION ──
        # Rule 1: Quality too low → HOLD
        if quality < self.min_execution_quality:
            final_action = "HOLD"
            final_reason = f"quality_too_low: {quality:.4f} < {self.min_execution_quality}"
        # Rule 2: Realized edge negative → HOLD
        elif realized_edge < self.min_realized_edge:
            final_action = "HOLD"
            final_reason = f"negative_realized_edge: {realized_edge:.8f}"
        # Rule 3: Fill unacceptable → HOLD
        elif not fill_est["acceptable"]:
            final_action = "HOLD"
            final_reason = f"fill_unacceptable: {fill_est['expected_fill_pct']:.2%}"
        # Rule 4: Latency too high → HOLD
        elif not lat.get("acceptable", True):
            final_action = "HOLD"
            final_reason = f"latency_too_high: {lat['execution_latency_ms']:.0f}ms"
        # Rule 5: EXECUTE
        else:
            final_action = "EXECUTE"
            final_reason = f"execution_feasible: quality={quality:.4f} edge={realized_edge:.6f}"

        # Adjust position for fill quality
        adjusted_position = position_usdt * fill_est["expected_fill_pct"] if final_action == "EXECUTE" else 0.0

        result = {
            "action": final_action,
            "reason": final_reason,
            "side": side,
            "position_usdt": round(adjusted_position, 2),
            "realized_edge": round(realized_edge, 8),
            "execution_quality": round(quality, 4),
            "commission_usdt": round(commission_usdt, 4),
            "slippage_usdt": round(slippage_usdt, 4),
            "total_cost_pct": round(total_cost_pct, 6),
            "slippage": slip,
            "fill": fill_est,
            "latency": lat,
            "theoretical_edge": round(theoretical_edge, 8),
        }

        # Log execution
        self._execution_log.append({
            "timestamp": int(time.time() * 1000),
            "action": final_action,
            "quality": quality,
            "realized_edge": realized_edge,
            "slippage_bps": slip["slippage_bps"],
        })

        # Track costs
        if final_action == "EXECUTE":
            self._total_commission_paid += commission_usdt
            self._total_slippage_paid += slippage_usdt

        return result

    def get_stats(self) -> dict:
        """Get executor statistics."""
        return {
            "total_executions": len(self._execution_log),
            "total_commission_paid": round(self._total_commission_paid, 4),
            "total_slippage_paid": round(self._total_slippage_paid, 4),
            "avg_slippage_realized": round(self.slippage.get_avg_realized_slippage(), 2),
        }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("lean_executor.py — Self-Test (LEAN-STYLE EXECUTOR)")
    print("=" * 60)

    executor = LeanExecutor()

    # ── Test 1: Assess a valid EXECUTE action ──
    print("\n[Test 1] Assess valid EXECUTE action...")
    action = {
        "action": "EXECUTE",
        "side": "LONG",
        "size": 0.10,
        "pipeline": {
            "step4_ev": {"adjusted_ev": 0.005},
        },
    }
    result = executor.assess(action, capital=1000.0, cycle=1)
    assert result["action"] in ("EXECUTE", "HOLD")
    print(f"  action={result['action']}, quality={result['execution_quality']:.4f}")
    print(f"  slippage={result['slippage']['slippage_bps']:.1f}bps, realized_edge={result['realized_edge']:.6f}")
    print(f"  ✓ Execution assessment complete")

    # ── Test 2: HOLD action passes through ──
    print("\n[Test 2] HOLD action passes through...")
    hold_action = {"action": "HOLD", "side": None, "size": 0.0}
    result2 = executor.assess(hold_action, capital=1000.0)
    assert result2["action"] == "HOLD"
    print(f"  action={result2['action']}")
    print(f"  ✓ HOLD passes through correctly")

    # ── Test 3: Slippage model ──
    print("\n[Test 3] Slippage model...")
    slip = executor.slippage.estimate_slippage(
        position_usdt=100.0,
        orderbook_depth_usdt=500000.0,
        volatility_pct=2.0,
        spread_bps=1.0,
    )
    assert slip["slippage_bps"] > 0
    print(f"  slippage={slip['slippage_bps']:.2f}bps ({slip['slippage_pct']:.6f}%)")
    print(f"  base={slip['base_bps']:.1f}, impact={slip['impact_bps']:.2f}, vol_adj={slip['vol_adj_bps']:.2f}")
    print(f"  ✓ Slippage model works")

    # ── Test 4: Fill model ──
    print("\n[Test 4] Fill model...")
    fill = executor.fill.estimate_fill(
        position_usdt=100.0,
        orderbook_depth_usdt=500000.0,
    )
    assert fill["expected_fill_pct"] > 0
    print(f"  fill={fill['expected_fill_pct']:.2%}, prob={fill['fill_probability']:.2%}")
    print(f"  ✓ Fill model works")

    # ── Test 5: Latency model ──
    print("\n[Test 5] Latency model...")
    lat = executor.latency.estimate_latency(cycle=50)
    assert lat["execution_latency_ms"] > 0
    assert lat["edge_retention"] > 0
    print(f"  latency={lat['execution_latency_ms']:.1f}ms, edge_retention={lat['edge_retention']:.4f}")
    print(f"  ✓ Latency model works")

    # ── Test 6: Execution is law, not signal ──
    print("\n[Test 6] Execution is law: reality degrades signals...")
    # Compare high-quality vs low-quality execution
    good = executor.assess(
        {"action": "EXECUTE", "side": "LONG", "size": 0.05,
         "pipeline": {"step4_ev": {"adjusted_ev": 0.01}}},
        capital=1000.0, orderbook_depth_usdt=1000000.0,
        volatility_pct=1.0, spread_bps=0.5, cycle=1,
    )
    bad = executor.assess(
        {"action": "EXECUTE", "side": "LONG", "size": 0.20,
         "pipeline": {"step4_ev": {"adjusted_ev": 0.01}}},
        capital=1000.0, orderbook_depth_usdt=100000.0,
        volatility_pct=8.0, spread_bps=20.0, cycle=99,
    )
    print(f"  good: quality={good['execution_quality']:.4f}, edge={good['realized_edge']:.6f}")
    print(f"  bad:  quality={bad['execution_quality']:.4f}, edge={bad['realized_edge']:.6f}")
    assert good["execution_quality"] >= bad["execution_quality"], "Good conditions should produce better quality"
    print(f"  ✓ Reality degrades: bad conditions = lower quality")

    # ── Test 7: Determinism ──
    print("\n[Test 7] Deterministic: same inputs → same assessment...")
    e1 = LeanExecutor()
    e2 = LeanExecutor()
    a = {"action": "EXECUTE", "side": "LONG", "size": 0.10,
         "pipeline": {"step4_ev": {"adjusted_ev": 0.005}}}
    r1 = e1.assess(a, capital=1000.0, cycle=42)
    r2 = e2.assess(a, capital=1000.0, cycle=42)
    assert r1["action"] == r2["action"]
    assert abs(r1["execution_quality"] - r2["execution_quality"]) < 1e-6
    print(f"  ✓ Deterministic execution assessment")

    print("\n" + "=" * 60)
    print("All self-tests PASSED")
    print("LEAN_EXECUTOR: execution is law, not signal")
    print("=" * 60)
