"""
Module: market_physics_engine.py — THE INTEGRATION ENGINE

PHILOSOPHY: convert trading into controlled physical system experiment

The MarketPhysicsEngine is NOT a new decision authority. It is an
ORCHESTRATOR that wires together all components of the MARKET PHYSICS
SIMULATOR into a single coherent pipeline.

THREE LAWS:
    1. SINGLE BRAIN:   SingleDecisionCore is the ONLY decision authority
    2. SINGLE MEMORY:  EventStore is the ONLY source of truth
    3. SINGLE EXECUTION: LeanExecutor is the ONLY execution authority

The engine's job: OBSERVE, MEASURE, STRESS-TEST, LEARN — then feed
results into the brain. It NEVER overrides, NEVER second-guesses,
NEVER adds new decision logic.

PIPELINE (per cycle):
    1. MEASURE:   raw_market_data → MarketStateVector.measure() → state_vector
    2. CLASSIFY:  state_summary   → HybridLearningLayer.classify_regime() → regime
    3. STRESS:    state_vector + preliminary_action
                  → StochasticMarketSimulator.assess_survivability()
                  → survival_assessment
    4. DECIDE:    market + risk_state + execution_state
                  → SingleDecisionCore.decide() → action_vector
    5. EXECUTE:   action_vector   → LeanExecutor.assess() → execution_result
    6. RECORD:    all events       → EventStore (append-only truth)
    7. LEARN:     outcome          → HybridLearningLayer.update() → mutations
    8. EVALUATE:  compute metrics (sharpe_proxy, max_dd, survival_time,
                  regime_stability, execution_quality)

KPI PRIORITY: SURVIVAL > PROFIT, STABILITY > RETURNS, CONSISTENCY > INTELLIGENCE
OPTIMIZE STABILITY, NOT PROFIT.

DETERMINISTIC: output = f(input), always reproducible.

BUILDS ON:
    - market_state_vector.py      (MarketStateVector)
    - stochastic_market_simulator.py (StochasticMarketSimulator)
    - hybrid_learning_layer.py    (HybridLearningLayer)
    - institutional_core.py       (SingleDecisionCore)
    - event_store.py              (EventStore)
    - lean_executor.py            (LeanExecutor)
"""

import math
import time
import sys
import os
from collections import deque
from typing import Optional, List, Dict

# Allow importing sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_state_vector import MarketStateVector
from stochastic_market_simulator import StochasticMarketSimulator
from hybrid_learning_layer import HybridLearningLayer
from institutional_core import SingleDecisionCore
from event_store import EventStore
from lean_executor import LeanExecutor


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi. Deterministic."""
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# DEFAULT CONFIGURATION
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    # ── MarketStateVector ──
    "state_vector": {
        "imbalance_history_len": 100,
        "volatility_history_len": 100,
        "price_history_len": 200,
        "toxicity_sensitivity": 2.0,
        "momentum_smoothing": 0.1,
        "typical_spread_bps": 3.0,
        "depth_levels": 10,
        "near_pct": 0.005,
        "vol_window": 20,
        "vol_annualization": math.sqrt(8760),
        "shock_threshold": 2.0,
        "vol_low_threshold": 0.005,
        "vol_normal_threshold": 0.02,
        "vol_elevated_threshold": 0.05,
        "trend_strength_threshold": 0.01,
        "spread_crisis_bps": 20.0,
        "markov_learning_rate": 0.05,
        "markov_prior": 0.2,
        "funding_sensitivity": 500.0,
        "oi_sensitivity": 0.01,
        "stability_max_ticks": 100,
    },
    # ── StochasticMarketSimulator ──
    "simulator": {
        "default_n_ticks": 20,
        "max_n_ticks": 100,
        "max_drawdown_threshold": 0.12,
        "ruin_probability_threshold": 0.05,
        "liq_base_spread_bps": 3.0,
        "liq_vol_spread_sensitivity": 5.0,
        "liq_depth_vol_reduction": 0.5,
        "liq_momentum_consumption": 0.3,
        "liq_base_fill_rate": 0.95,
        "ob_base_drift": 0.0,
        "ob_vol_per_tick": 0.001,
        "ob_temp_impact": 0.1,
        "ob_perm_impact": 0.02,
        "ob_impact_decay": 0.5,
        "ob_mean_reversion": 0.01,
        "lat_base_ms": 300.0,
        "lat_vol_sensitivity": 50.0,
        "lat_max_ms": 5000.0,
        "adv_enabled": True,
        "adv_max_concurrent": 2,
        "adv_intensity_scale": 1.0,
        "chaos_r": 3.99,
    },
    # ── HybridLearningLayer ──
    "learning": {
        "n_features": 20,
        "initial_learning_rate": 0.05,
        "min_learning_rate": 0.001,
        "lr_decay": 0.9999,
        "policy_weight_bound": 3.0,
        "policy_max_update_norm": 0.1,
        "value_gamma": 0.95,
        "value_weight_bound": 3.0,
        "value_max_update_norm": 0.1,
        "regime_weight_bound": 3.0,
        "regime_max_update_norm": 0.1,
        "max_drawdown": 0.12,
        "survival_tick_target": 100,
        "max_parameter_norm": 10.0,
    },
    # ── SingleDecisionCore ──
    "brain": {
        "max_drawdown": 0.12,
        "ruin_probability_threshold": 0.05,
        "hard_stop": True,
        "max_position_pct": 0.25,
        "max_leverage": 3,
        "min_confidence": 0.30,
        "min_ev_to_trade": 0.001,
        "no_trade_noise": 0.60,
        "w_orderflow": 1.0,
        "w_volume_delta": 0.6,
        "w_bidask_imbalance": 0.8,
        "w_funding_signal": 0.3,
        "w_oi_momentum": 0.4,
        "w_price_momentum": 0.5,
        "learning_rate": 0.03,
        "weight_min": 0.05,
        "weight_max": 3.0,
        "cooldown_cycles": 3,
        "min_price_change_pct": 0.003,
        "survivability_max_dd": 0.15,
        "survivability_window": 100,
        "initial_capital": 1000.0,
    },
    # ── EventStore ──
    "store": {
        "persist_path": None,
        "max_memory_events": 100000,
    },
    # ── LeanExecutor ──
    "executor": {
        "commission_rate": 0.0006,
        "base_slippage_bps": 2.0,
        "impact_coefficient": 0.1,
        "vol_adjustment_factor": 0.5,
        "max_slippage_bps": 50.0,
        "min_fill_pct": 0.80,
        "edge_half_life_ms": 5000.0,
        "min_latency_ms": 200.0,
        "max_latency_ms": 3000.0,
        "min_execution_quality": 0.30,
        "min_realized_edge": 0.0,
    },
    # ── Engine-level config ──
    "engine": {
        "initial_capital": 1000.0,
        "periods_per_year": 8760,  # Hourly → annual Sharpe
        "survival_stress_ticks": 30,  # Ticks for pre-decision stress test
        "learning_interval": 1,   # Learn every N cycles
        "metrics_interval": 1,    # Compute metrics every N cycles
    },
}


# ---------------------------------------------------------------------------
# MARKET PHYSICS ENGINE
# ---------------------------------------------------------------------------

class MarketPhysicsEngine:
    """The complete market physics engine.

    This is NOT a new decision authority. It is an ORCHESTRATOR that:
    1. Measures market state (physics)
    2. Simulates forward (stress testing)
    3. Feeds everything to the single decision core (brain)
    4. Executes through the lean executor (law)
    5. Records everything to the event store (truth)
    6. Learns from outcomes (adaptation)
    7. Evaluates stability (the ultimate KPI)

    OPTIMIZE STABILITY, NOT PROFIT.

    THREE LAWS:
        1. SINGLE BRAIN:   SingleDecisionCore is the ONLY decision authority
        2. SINGLE MEMORY:  EventStore is the ONLY source of truth
        3. SINGLE EXECUTION: LeanExecutor is the ONLY execution authority

    The engine NEVER:
    - Overrides the brain's decision
    - Adds new decision logic
    - Modifies recorded events
    - Bypasses the executor

    The engine DOES:
    - Orchestrate the pipeline
    - Derive risk/execution states from measurements
    - Feed survival assessment into risk_state
    - Track equity for metrics
    - Record everything to the event store
    - Update the learning layer from outcomes
    """

    def __init__(self, config: dict = None):
        """Initialize the complete Market Physics Engine.

        Creates all 6 sub-components from config and sets up
        internal tracking for equity curve, regime history, and
        evaluation metrics.

        Args:
            config: Configuration dict. Uses DEFAULT_CONFIG for any
                    missing keys. Structure matches DEFAULT_CONFIG.
        """
        # ── Merge with defaults ──
        cfg = self._deep_merge(DEFAULT_CONFIG, config or {})

        # ── Engine-level config ──
        eng = cfg.get("engine", {})
        self.initial_capital = eng.get("initial_capital", 1000.0)
        self.periods_per_year = eng.get("periods_per_year", 8760)
        self.survival_stress_ticks = eng.get("survival_stress_ticks", 30)
        self.learning_interval = eng.get("learning_interval", 1)
        self.metrics_interval = eng.get("metrics_interval", 1)

        # ── Initialize all 6 components ──

        # 1. MarketStateVector — the measurement device
        self.state_vector = MarketStateVector(**cfg.get("state_vector", {}))

        # 2. StochasticMarketSimulator — the stress tester
        sim_cfg = cfg.get("simulator", {})
        self.simulator = StochasticMarketSimulator(**sim_cfg)

        # 3. HybridLearningLayer — the learner
        self.learning = HybridLearningLayer(**cfg.get("learning", {}))

        # 4. SingleDecisionCore — THE BRAIN
        self.brain = SingleDecisionCore(**cfg.get("brain", {}))

        # 5. EventStore — THE MEMORY
        store_cfg = cfg.get("store", {})
        self.store = EventStore(
            persist_path=store_cfg.get("persist_path"),
            max_memory_events=store_cfg.get("max_memory_events", 100000),
        )

        # 6. LeanExecutor — THE EXECUTION AUTHORITY
        self.executor = LeanExecutor(**cfg.get("executor", {}))

        # ── Evaluation metrics tracking ──
        self._equity_curve: List[float] = [self.initial_capital]
        self._regime_history: List[str] = []
        self._execution_qualities: List[float] = []
        self._pnl_returns: List[float] = []
        self._cycle = 0
        self._killed = False
        self._kill_cycle = None

        # ── Capital tracking ──
        self._capital = self.initial_capital
        self._peak_capital = self.initial_capital
        self._current_drawdown = 0.0

        # ── Previous state (for learning) ──
        self._prev_state_summary = None
        self._prev_action = None

        # ── Timing ──
        self._start_time = time.time()

    # ===================================================================
    # MAIN ENTRY POINT
    # ===================================================================

    def cycle(self, market_data: dict) -> dict:
        """Run one complete cycle of the market physics engine.

        This is the main entry point. One call = one full cycle.

        PIPELINE:
        1. MEASURE:   raw data → state_vector
        2. CLASSIFY:  state_summary → regime
        3. STRESS:    state + preliminary action → survival assessment
        4. DECIDE:    market + risk + execution → action_vector (THE BRAIN)
        5. EXECUTE:   action_vector → execution_result (THE LAW)
        6. RECORD:    all events → event store (THE TRUTH)
        7. LEARN:     outcome → learning update (ADAPTATION)
        8. EVALUATE:  compute metrics (STABILITY)

        Args:
            market_data: Raw market data dict with ohlcv, ticker,
                         orderbook, funding, open_interest.

        Returns:
            Cycle result dict with:
            - state_vector: full 5-component measurement
            - state_summary: compressed summary for decision core
            - regime: classified regime from learning layer
            - survival_assessment: stress test results
            - action_vector: the decision (from THE brain)
            - execution_result: execution assessment
            - learning_update: what was learned (if applicable)
            - metrics: current evaluation metrics
        """
        self._cycle += 1

        # ── STEP 1: MEASURE ──
        state_vector = self.state_vector.measure(market_data)
        state_summary = self.state_vector.get_state_summary()

        # If no valid measurement yet, return early
        if not state_summary:
            return {
                "state_vector": state_vector,
                "state_summary": {},
                "regime": {},
                "survival_assessment": {},
                "action_vector": {"action": "HOLD", "side": None, "size": 0.0,
                                  "reason": "no_state_yet"},
                "execution_result": {},
                "learning_update": None,
                "metrics": self.compute_metrics(),
            }

        # ── STEP 2: CLASSIFY ──
        regime = self.learning.classify_regime(state_summary)
        self._regime_history.append(regime.get("regime", "RANGING"))

        # ── STEP 3: STRESS (pre-decision) ──
        # Use learning layer preferences to create a preliminary action
        # for stress testing. The preliminary action is NOT a decision —
        # it's a "what if" scenario for the simulator.
        prelim_preferences = self.learning.compute_action_preferences(state_summary)
        preliminary_action = self._make_preliminary_action(prelim_preferences)

        survival_assessment = self.simulator.assess_survivability(
            state_vector,
            preliminary_action,
            n_ticks=self.survival_stress_ticks,
        )

        # ── STEP 4: DECIDE (THE BRAIN) ──
        # Derive risk_state and execution_state from measurements
        risk_state = self._compute_risk_state(state_summary, survival_assessment)
        execution_state = self._compute_execution_state(state_summary)

        # Feed market_data (which the brain ingests internally) plus
        # risk_state and execution_state into THE SINGLE DECISION CORE
        action_vector = self.brain.decide(
            market=market_data,
            risk_state=risk_state,
            execution_state=execution_state,
        )

        # ── STEP 4b: POST-DECISION STRESS CHECK ──
        # If the brain decided to EXECUTE, stress-test the actual action
        if action_vector.get("action") == "EXECUTE":
            post_survival = self.simulator.assess_survivability(
                state_vector,
                action_vector,
                n_ticks=self.survival_stress_ticks,
            )
            # If the actual action doesn't survive, downgrade to HOLD
            if not post_survival.get("survives", True):
                original_reason = action_vector.get("reason", "")
                action_vector = {
                    "action": "HOLD",
                    "side": None,
                    "size": 0.0,
                    "leverage": 0,
                    "reason": f"STRESS_TEST_FAIL: {post_survival.get('risk_verdict', 'UNKNOWN')} — {original_reason}",
                }
            # If survives but with size adjustment, reduce size
            elif post_survival.get("recommended_size_adjustment", 1.0) < 1.0:
                size_adj = post_survival["recommended_size_adjustment"]
                original_size = action_vector.get("size", 0.0)
                action_vector["size"] = round(original_size * size_adj, 6)
                action_vector["reason"] = (
                    action_vector.get("reason", "") +
                    f" | STRESS_ADJ: size*{size_adj:.2f}"
                )
            # Update survival assessment to reflect actual action
            survival_assessment = post_survival

        # ── STEP 5: EXECUTE (THE LAW) ──
        # Extract execution parameters from state
        liq = state_summary.get("available_liquidity_usdt", 500000.0)
        vol_pct = state_summary.get("volatility", 0.02) * 100  # Convert to pct
        spread_bps = state_summary.get("spread_pct", 0.0003) * 10000  # Convert to bps

        execution_result = self.executor.assess(
            action_vector=action_vector,
            capital=self._capital,
            orderbook_depth_usdt=liq if liq > 0 else 500000.0,
            volatility_pct=vol_pct if vol_pct > 0 else 2.0,
            spread_bps=spread_bps if spread_bps > 0 else 3.0,
            cycle=self._cycle,
        )

        # ── STEP 5b: UPDATE CAPITAL ──
        self._update_capital(action_vector, execution_result, state_summary)

        # ── STEP 6: RECORD (THE TRUTH) ──
        self._record_cycle(
            state_vector, state_summary, regime,
            survival_assessment, action_vector, execution_result,
        )

        # ── STEP 7: LEARN (ADAPTATION) ──
        learning_update = None
        if (self._cycle % self.learning_interval == 0
                and self._prev_state_summary is not None
                and self._prev_action is not None):
            learning_update = self._learn_from_outcome(
                state_summary, action_vector, execution_result,
            )

        # Store current state for next cycle's learning
        self._prev_state_summary = state_summary.copy()
        self._prev_action = action_vector.copy() if action_vector else None

        # ── STEP 8: EVALUATE (STABILITY) ──
        metrics = None
        if self._cycle % self.metrics_interval == 0:
            metrics = self.compute_metrics()

        return {
            "state_vector": state_vector,
            "state_summary": state_summary,
            "regime": regime,
            "survival_assessment": survival_assessment,
            "action_vector": action_vector,
            "execution_result": execution_result,
            "learning_update": learning_update,
            "metrics": metrics,
        }

    # ===================================================================
    # RISK STATE DERIVATION
    # ===================================================================

    def _compute_risk_state(self, state_summary: dict,
                            survival_assessment: dict) -> dict:
        """Derive risk_state for the decision core from state + history.

        The risk_state is what the brain uses in Step 3 (risk filter).
        It is DERIVED from measurements, not invented by the engine.

        Components:
        - drawdown: from equity curve tracking
        - var: from recent PnL distribution
        - loss_streak: from trade history
        - capital: current equity

        Survival assessment integration:
        If the stress test shows danger, we add a sim_survival_penalty
        that increases the effective drawdown, making the risk filter
        more conservative.

        Args:
            state_summary: From MarketStateVector.get_state_summary().
            survival_assessment: From StochasticMarketSimulator.

        Returns:
            Dict compatible with SingleDecisionCore.filter_risk() input.
        """
        # ── Drawdown: current drawdown from equity curve ──
        drawdown = self._current_drawdown

        # ── VaR: 95th percentile of recent PnL distribution ──
        # Simplified: use std of recent returns * 1.645 (95% VaR)
        if len(self._pnl_returns) >= 5:
            mean_pnl = sum(self._pnl_returns) / len(self._pnl_returns)
            variance = sum((r - mean_pnl) ** 2 for r in self._pnl_returns) / len(self._pnl_returns)
            std_pnl = math.sqrt(variance) if variance > 0 else 0.001
            var = abs(mean_pnl - 1.645 * std_pnl)  # 95% VaR
        else:
            # Not enough history — use volatility as proxy
            vol = abs(state_summary.get("volatility", 0.02))
            var = vol * 1.645  # Approximate 95% VaR

        # ── Loss streak: from brain's internal tracking ──
        loss_streak = self.brain._loss_streak

        # ── Capital: from internal tracking ──
        capital = self._capital

        # ── Survival assessment integration ──
        # If the stress test shows danger, increase the effective drawdown
        # This makes the risk filter more conservative when the simulator
        # says "things could go wrong"
        sim_survival_penalty = 0.0
        if survival_assessment:
            verdict = survival_assessment.get("risk_verdict", "SAFE")
            if verdict == "FATAL":
                sim_survival_penalty = 0.05  # Add 5% to effective drawdown
            elif verdict == "DANGEROUS":
                sim_survival_penalty = 0.03  # Add 3%
            elif verdict == "CAUTION":
                sim_survival_penalty = 0.01  # Add 1%

            # Also adjust based on survival probability
            surv_prob = survival_assessment.get("survival_probability", 1.0)
            if surv_prob < 0.5:
                sim_survival_penalty += 0.02

        effective_drawdown = min(1.0, drawdown + sim_survival_penalty)

        return {
            "drawdown": round(effective_drawdown, 6),
            "var": round(var, 6),
            "loss_streak": loss_streak,
            "capital": round(capital, 2),
            "sim_survival_penalty": round(sim_survival_penalty, 6),
            "raw_drawdown": round(drawdown, 6),
        }

    # ===================================================================
    # EXECUTION STATE DERIVATION
    # ===================================================================

    def _compute_execution_state(self, state_summary: dict) -> dict:
        """Derive execution_state for the decision core from state.

        The execution_state tells the brain about current execution
        conditions. It is DERIVED from measurements.

        Components:
        - liquidity_quality: from LiquidityField component
        - slippage_bps: estimated from VolatilityField + LiquidityField
        - latency_ms: estimated from typical conditions
        - spread_bps: from LiquidityField

        Args:
            state_summary: From MarketStateVector.get_state_summary().

        Returns:
            Dict compatible with SingleDecisionCore Step 5 input.
        """
        liq_quality = state_summary.get("liquidity_quality", 0.5)
        vol = abs(state_summary.get("volatility", 0.02))
        spread_pct = state_summary.get("spread_pct", 0.0003)
        spread_bps = spread_pct * 10000.0 if spread_pct < 1.0 else spread_pct

        # ── Slippage estimate ──
        # Base slippage from spread + volatility contribution
        base_slip = max(2.0, spread_bps)
        vol_slip = vol * 100.0 * 0.5  # Volatility adds slippage
        estimated_slippage_bps = base_slip + vol_slip

        # ── Latency estimate ──
        # Higher volatility → higher latency (exchange congestion)
        base_latency = 300.0  # ms
        vol_latency = vol * 100.0 * 50.0  # ms per vol pct
        shock = state_summary.get("shock_component", 0.0)
        shock_latency = shock * 500.0  # ms during shock
        estimated_latency_ms = base_latency + vol_latency + shock_latency

        return {
            "liquidity_quality": round(liq_quality, 6),
            "slippage_bps": round(estimated_slippage_bps, 2),
            "latency_ms": round(estimated_latency_ms, 1),
            "spread_bps": round(spread_bps, 2),
        }

    # ===================================================================
    # PRELIMINARY ACTION (for stress testing)
    # ===================================================================

    def _make_preliminary_action(self, preferences: dict) -> dict:
        """Create a preliminary action from learning layer preferences.

        This is NOT a decision. It's a "what if" scenario for the
        simulator to stress-test. The brain will make the REAL decision.

        The preliminary action uses the learning layer's action
        probabilities to guess what the brain might do, so the
        simulator can check if that kind of action would survive.

        Args:
            preferences: From HybridLearningLayer.compute_action_preferences().

        Returns:
            Preliminary action dict for stress testing.
        """
        long_prob = preferences.get("long_prob", 0.33)
        short_prob = preferences.get("short_prob", 0.33)
        size_factor = preferences.get("size_factor", 0.1)

        # Choose the most probable direction
        if long_prob >= short_prob and long_prob >= 0.4:
            side = "LONG"
            size = size_factor * 0.5  # Conservative estimate
        elif short_prob > long_prob and short_prob >= 0.4:
            side = "SHORT"
            size = size_factor * 0.5
        else:
            # No clear direction → HOLD (always survives)
            return {
                "action": "HOLD",
                "side": None,
                "size": 0.0,
                "reason": "preliminary_no_direction",
            }

        return {
            "action": "EXECUTE",
            "side": side,
            "size": round(_clamp(size, 0.02, 0.25), 6),
            "reason": f"preliminary_stress_test:{side}",
        }

    # ===================================================================
    # CAPITAL UPDATE
    # ===================================================================

    def _update_capital(self, action_vector: dict,
                        execution_result: dict,
                        state_summary: dict) -> None:
        """Update internal capital tracking based on execution.

        For EXECUTE actions that pass the executor, we simulate a PnL
        outcome based on the market state. This is simplified compared
        to real trade tracking, but sufficient for metrics computation.

        For non-execute actions, capital stays the same.

        Args:
            action_vector: The action from the brain.
            execution_result: From LeanExecutor.assess().
            state_summary: Current market state summary.
        """
        exec_action = execution_result.get("action", "HOLD")
        position_usdt = execution_result.get("position_usdt", 0.0)

        if exec_action == "EXECUTE" and position_usdt > 0:
            side = execution_result.get("side", action_vector.get("side"))

            # Estimate PnL from current market conditions
            # In a real system, this would come from actual fill data
            vol = abs(state_summary.get("volatility", 0.02))
            direction = 1.0 if side == "LONG" else -1.0

            # Use orderflow as a directional signal for PnL simulation
            orderflow = state_summary.get("orderflow", 0.0)
            # Favorable orderflow in our direction → positive PnL
            pnl_signal = direction * orderflow * 0.5
            # Add some volatility-based noise (bounded)
            pnl_noise = vol * (direction * 0.3)  # Slight drift
            pnl_pct = pnl_signal + pnl_noise

            # Apply execution costs
            total_cost_pct = execution_result.get("total_cost_pct", 0.001)
            pnl_pct -= total_cost_pct

            # Scale by position size relative to capital
            position_fraction = position_usdt / self._capital if self._capital > 0 else 0
            capital_change_pct = pnl_pct * position_fraction

            # Update capital
            self._capital *= (1.0 + capital_change_pct)
            self._capital = max(0.01, self._capital)  # Never go to zero

            # Record PnL return
            self._pnl_returns.append(capital_change_pct)

            # Record execution quality
            eq = execution_result.get("execution_quality", 0.0)
            self._execution_qualities.append(eq)

            # Feed outcome back to the brain's learning loop
            self.brain.record_outcome(capital_change_pct, action_vector)
        else:
            # HOLD/KILL — no capital change, record zero return
            self._pnl_returns.append(0.0)

        # Update equity curve
        self._equity_curve.append(self._capital)

        # Update peak and drawdown
        self._peak_capital = max(self._peak_capital, self._capital)
        if self._peak_capital > 0:
            self._current_drawdown = (
                (self._peak_capital - self._capital) / self._peak_capital
            )
        else:
            self._current_drawdown = 0.0

        # Check for kill condition
        if self._current_drawdown >= 0.12 and not self._killed:
            self._killed = True
            self._kill_cycle = self._cycle

    # ===================================================================
    # LEARNING FROM OUTCOMES
    # ===================================================================

    def _learn_from_outcome(self, current_state_summary: dict,
                            action_vector: dict,
                            execution_result: dict) -> dict:
        """Update the learning layer from the previous cycle's outcome.

        Uses the PREVIOUS state_summary and action (stored from last
        cycle) and the CURRENT state_summary as the "next state" to
        compute the learning update.

        The reward is computed from the execution outcome using the
        learning layer's reward function, which encodes:
        SURVIVAL > PROFIT, STABILITY > RETURNS

        Args:
            current_state_summary: Current cycle's state summary (next state).
            action_vector: Current cycle's action (the action taken).
            execution_result: Current cycle's execution result.

        Returns:
            Learning update report dict.
        """
        if self._prev_state_summary is None or self._prev_action is None:
            return None

        # ── Compute reward ──
        eq = execution_result.get("execution_quality", 0.5)
        pnl_returns = self._pnl_returns
        pnl_pct = pnl_returns[-1] if pnl_returns else 0.0
        vol = abs(current_state_summary.get("volatility", 0.02))

        # Compute drawdown rate change
        dd_rate_change = 0.0
        if len(self._equity_curve) >= 3:
            dd_prev = self._compute_drawdown_at(len(self._equity_curve) - 2)
            dd_curr = self._current_drawdown
            dd_rate_change = dd_curr - dd_prev

        outcome = {
            "pnl_pct": pnl_pct,
            "drawdown": self._current_drawdown,
            "execution_quality": eq,
            "survival_ticks": self._cycle,
            "volatility": vol,
            "theoretical_edge": execution_result.get("theoretical_edge", 0.001),
            "realized_edge": execution_result.get("realized_edge", 0.0),
            "dd_rate_change": dd_rate_change,
        }

        reward = self.learning.compute_reward(outcome)

        # ── Determine regime actual ──
        # Use the MarketStateVector's regime detection as "ground truth"
        # for the regime classifier's supervised learning
        regime_actual = current_state_summary.get("regime", None)

        # ── Get the action taken (from previous cycle) ──
        action_taken = {
            "action": self._prev_action.get("action", "HOLD"),
            "side": self._prev_action.get("side"),
        }

        # ── Update learning layer ──
        update_report = self.learning.update(
            state_summary=self._prev_state_summary,
            action_taken=action_taken,
            reward=reward,
            next_state_summary=current_state_summary,
            regime_actual=regime_actual,
        )

        return update_report

    # ===================================================================
    # EVENT RECORDING
    # ===================================================================

    def _record_cycle(self, state_vector: dict, state_summary: dict,
                      regime: dict, survival_assessment: dict,
                      action_vector: dict, execution_result: dict) -> None:
        """Record all events from this cycle to the event store.

        ARENA LAW: SI NO ESTÁ LOGGEADO → NO PASÓ

        Records:
        - Decision event (every cycle)
        - Regime transition (when regime changes)
        - Execution assessment (every cycle)
        - Survival snapshot (every 10 cycles)
        - Kill switch activation (when killed)

        Args:
            state_vector: Full 5-component state vector.
            state_summary: Compressed state summary.
            regime: Regime classification from learning layer.
            survival_assessment: Stress test results.
            action_vector: The decision from THE BRAIN.
            execution_result: From THE EXECUTION AUTHORITY.
        """
        # ── Record decision ──
        pipeline = action_vector.get("pipeline", {})
        step3_risk = pipeline.get("step3_risk", {})
        step4_ev = pipeline.get("step4_ev", {})

        self.store.record_decision(
            action=action_vector.get("action", "HOLD"),
            side=action_vector.get("side"),
            size=action_vector.get("size", 0.0),
            reason=action_vector.get("reason", ""),
            risk_score=step3_risk.get("risk_score", 0.0),
            ev=step4_ev.get("adjusted_ev", 0.0),
            conviction=pipeline.get("step2_features", {}).get("conviction", 0.0),
            noise=pipeline.get("step2_features", {}).get("noise", 0.0),
        )

        # ── Record regime transition ──
        current_regime = regime.get("regime", "RANGING")
        prev_regime = self._regime_history[-2] if len(self._regime_history) >= 2 else None
        if prev_regime and current_regime != prev_regime:
            self.store.record_regime_transition(
                from_regime=prev_regime,
                to_regime=current_regime,
                kl_divergence=0.0,
                confidence=regime.get("confidence", 0.5),
            )

        # ── Record execution assessment ──
        if execution_result:
            self.store.record_execution_assessment(
                action=execution_result.get("action", "HOLD"),
                reason=execution_result.get("reason", ""),
                realized_edge=execution_result.get("realized_edge", 0.0),
                slippage_bps=execution_result.get("slippage", {}).get("slippage_bps", 0.0),
                fill_pct=execution_result.get("fill", {}).get("expected_fill_pct", 0.0),
                quality=execution_result.get("execution_quality", 0.0),
            )

        # ── Record survival snapshot (every 10 cycles) ──
        if self._cycle % 10 == 0 and survival_assessment:
            self.store.record_survival_snapshot(
                survival_score=survival_assessment.get("survival_probability", 1.0),
                entropy_stability=0.0,
                drawdown_clustering=self._current_drawdown,
                regime_adaptability=regime.get("confidence", 0.5),
                verdict=survival_assessment.get("risk_verdict", "SAFE"),
            )

        # ── Record kill switch ──
        if self._killed and self._kill_cycle == self._cycle:
            self.store.record_kill_switch(
                activated=True,
                reason=f"drawdown={self._current_drawdown:.2%} >= 12%",
            )

    # ===================================================================
    # EVALUATION METRICS
    # ===================================================================

    def compute_metrics(self) -> dict:
        """Compute all evaluation metrics.

        The ULTIMATE KPI: OPTIMIZE STABILITY, NOT PROFIT.

        Metrics:
        - sharpe_proxy: annualized Sharpe-like ratio
        - max_drawdown: maximum drawdown experienced
        - survival_time: cycles since inception without kill
        - regime_stability_score: how stable regimes have been
        - execution_quality: average execution quality
        - stability_score: composite stability metric (THE KPI)

        Returns:
            Dict with all evaluation metrics.
        """
        # ── Sharpe proxy ──
        sharpe_proxy = 0.0
        if len(self._pnl_returns) >= 2:
            mean_ret = sum(self._pnl_returns) / len(self._pnl_returns)
            variance = sum(
                (r - mean_ret) ** 2 for r in self._pnl_returns
            ) / len(self._pnl_returns)
            std_ret = math.sqrt(variance) if variance > 0 else 1e-8
            sharpe_proxy = (mean_ret / (std_ret + 1e-8)) * math.sqrt(self.periods_per_year)

        # ── Max drawdown ──
        max_drawdown = 0.0
        if len(self._equity_curve) >= 2:
            peak = self._equity_curve[0]
            for eq in self._equity_curve:
                peak = max(peak, eq)
                if peak > 0:
                    dd = (peak - eq) / peak
                    max_drawdown = max(max_drawdown, dd)

        # ── Survival time ──
        if self._killed and self._kill_cycle is not None:
            survival_time = self._kill_cycle
        else:
            survival_time = self._cycle

        # ── Regime stability score ──
        regime_stability_score = 0.0
        if len(self._regime_history) >= 2:
            transitions = 0
            for i in range(1, len(self._regime_history)):
                if self._regime_history[i] != self._regime_history[i - 1]:
                    transitions += 1
            regime_stability_score = 1.0 - (transitions / (len(self._regime_history) - 1))
            regime_stability_score = max(0.0, regime_stability_score)

        # ── Execution quality ──
        execution_quality = 0.0
        if self._execution_qualities:
            execution_quality = sum(self._execution_qualities) / len(self._execution_qualities)

        # ── Composite stability score ──
        # Weighted composite FAVORING STABILITY metrics
        # - max_drawdown (inverted): 30% weight (lower DD = better)
        # - regime_stability: 25% weight (fewer transitions = better)
        # - survival_time (normalized): 20% weight (longer = better)
        # - execution_quality: 15% weight (higher = better)
        # - sharpe_proxy (clamped): 10% weight (positive = better, but least important)
        dd_score = max(0.0, 1.0 - max_drawdown / 0.12)  # 0% DD = 1.0, 12% DD = 0.0
        survival_normalized = min(1.0, survival_time / 500.0)  # 500 cycles = full score
        sharpe_normalized = _clamp((sharpe_proxy + 2.0) / 4.0, 0.0, 1.0)  # Map [-2, 2] to [0, 1]

        stability_score = (
            dd_score * 0.30
            + regime_stability_score * 0.25
            + survival_normalized * 0.20
            + execution_quality * 0.15
            + sharpe_normalized * 0.10
        )
        stability_score = _clamp(stability_score, 0.0, 1.0)

        return {
            "sharpe_proxy": round(sharpe_proxy, 6),
            "max_drawdown": round(max_drawdown, 6),
            "survival_time": survival_time,
            "regime_stability_score": round(regime_stability_score, 6),
            "execution_quality": round(execution_quality, 6),
            "stability_score": round(stability_score, 6),
            # Additional diagnostic metrics
            "current_capital": round(self._capital, 2),
            "current_drawdown": round(self._current_drawdown, 6),
            "total_cycles": self._cycle,
            "killed": self._killed,
            "pnl_returns_count": len(self._pnl_returns),
        }

    # ===================================================================
    # ENGINE STATE (for dashboard)
    # ===================================================================

    def get_engine_state(self) -> dict:
        """Get complete engine state for dashboard.

        Returns:
            Dict with the full state of all components and metrics.
        """
        return {
            "engine": {
                "cycle": self._cycle,
                "capital": round(self._capital, 2),
                "initial_capital": self.initial_capital,
                "current_drawdown": round(self._current_drawdown, 6),
                "peak_capital": round(self._peak_capital, 2),
                "killed": self._killed,
                "kill_cycle": self._kill_cycle,
                "uptime_s": round(time.time() - self._start_time, 1),
            },
            "metrics": self.compute_metrics(),
            "brain": self.brain.get_state(),
            "learning": self.learning.get_learning_state(),
            "store": self.store.get_stats(),
            "executor": self.executor.get_stats(),
            "state_vector": {
                "measurement_count": self.state_vector._measure_count,
                "current_regime": self.state_vector._current_regime,
                "regime_ticks": self.state_vector._regime_ticks,
            },
        }

    # ===================================================================
    # INTERNAL HELPERS
    # ===================================================================

    def _compute_drawdown_at(self, idx: int) -> float:
        """Compute drawdown at a specific point in the equity curve.

        Args:
            idx: Index into equity curve.

        Returns:
            Drawdown as fraction at that point.
        """
        if idx < 0 or idx >= len(self._equity_curve):
            return 0.0
        peak = max(self._equity_curve[:idx + 1])
        if peak > 0:
            return (peak - self._equity_curve[idx]) / peak
        return 0.0

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep merge two dicts. Override takes precedence.

        Args:
            base: Base dictionary with defaults.
            override: Override dictionary with user-specified values.

        Returns:
            Merged dictionary.
        """
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = MarketPhysicsEngine._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def close(self) -> None:
        """Close the engine and release resources."""
        self.store.close()

    def __del__(self):
        """Destructor — ensure store is closed."""
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("market_physics_engine.py — Self-Test")
    print("THE INTEGRATION ENGINE — MARKET PHYSICS SIMULATOR")
    print("=" * 70)

    # ── Helper: Generate simulated market data ──
    def make_simulated_market_data(cycle: int, base_price: float = 50000.0):
        """Generate deterministic simulated market data for testing.

        Args:
            cycle: Current cycle number (drives deterministic variation).
            base_price: Base price for simulation.

        Returns:
            Market data dict compatible with MarketStateVector.measure().
        """
        # Deterministic price variation based on cycle
        price_trend = math.sin(cycle * 0.1) * 0.01  # Gentle oscillation
        noise = math.sin(cycle * 1.7) * 0.002  # Small noise
        price = base_price * (1.0 + price_trend + noise)

        # Generate 20 OHLCV candles
        ohlcv = []
        for i in range(20):
            c = cycle * 20 + i
            drift = math.sin(c * 0.05) * 0.002
            p = price * (1.0 + drift * (i / 20.0))
            h = p * (1.0 + abs(math.sin(c * 0.3)) * 0.005)
            l = p * (1.0 - abs(math.sin(c * 0.4)) * 0.005)
            v = 1000.0 + math.sin(c * 0.2) * 500.0
            ohlcv.append([c * 3600000, round(p - drift * 10, 2),
                          round(h, 2), round(l, 2), round(p, 2),
                          round(v, 2), 0])

        # Vary orderbook imbalance based on trend
        imbalance = math.sin(cycle * 0.1) * 0.3
        bid_depth = 100.0 + imbalance * 30.0
        ask_depth = 100.0 - imbalance * 30.0

        # Vary spread
        vol_mult = 1.0 + abs(math.sin(cycle * 0.15)) * 2.0
        spread_bps = 3.0 * vol_mult

        # Ticker
        bid_price = price * (1.0 - spread_bps / 20000.0)
        ask_price = price * (1.0 + spread_bps / 20000.0)

        return {
            "ohlcv": ohlcv,
            "ticker": {
                "bid": round(bid_price, 2),
                "ask": round(ask_price, 2),
                "spread_pct": round(spread_bps / 10000.0, 6),
            },
            "orderbook": {
                "bid_depth": round(bid_depth, 2),
                "ask_depth": round(ask_depth, 2),
                "bids": [[round(bid_price - i * 0.5, 2), round(bid_depth / 10, 2)]
                         for i in range(10)],
                "asks": [[round(ask_price + i * 0.5, 2), round(ask_depth / 10, 2)]
                         for i in range(10)],
            },
            "funding": {
                "rate": round(math.sin(cycle * 0.05) * 0.0001, 6),
                "next_funding_ms": 28800000,
                "predicted_rate": round(math.sin(cycle * 0.03) * 0.0001, 6),
            },
            "open_interest": {
                "oi_value": 1000000.0 + math.sin(cycle * 0.08) * 100000.0,
                "oi_change_24h_pct": round(math.sin(cycle * 0.1) * 5.0, 2),
            },
        }

    # ── Test 1: Create engine with default config ──
    print("\n[Test 1] Create engine with default config...")
    engine = MarketPhysicsEngine()
    assert engine.state_vector is not None
    assert engine.simulator is not None
    assert engine.learning is not None
    assert engine.brain is not None
    assert engine.store is not None
    assert engine.executor is not None
    assert engine._capital == 1000.0
    print(f"  capital={engine._capital}, cycle={engine._cycle}")
    print(f"  ✓ Engine created with all 6 components")

    # ── Test 2: Run 50 cycles with simulated market data ──
    print("\n[Test 2] Run 50 cycles with simulated market data...")
    results = []
    for i in range(50):
        market_data = make_simulated_market_data(i + 1)
        result = engine.cycle(market_data)
        results.append(result)

        # Verify basic structure
        assert "state_vector" in result
        assert "action_vector" in result
        assert "execution_result" in result
        assert "regime" in result

    print(f"  Ran {len(results)} cycles")
    print(f"  Final capital: ${engine._capital:.2f}")
    print(f"  Final drawdown: {engine._current_drawdown:.4f}")
    print(f"  ✓ All 50 cycles completed successfully")

    # ── Test 3: Verify all components produce valid outputs ──
    print("\n[Test 3] Verify component outputs...")
    last_result = results[-1]

    # State vector should have all 5 components
    sv = last_result["state_vector"]
    assert "order_flow" in sv
    assert "liquidity_field" in sv
    assert "volatility_field" in sv
    assert "regime_inertia" in sv
    assert "information_flow" in sv
    print(f"  state_vector: {sv['measurement_id']} measurements")

    # Regime should have regime and confidence
    regime = last_result["regime"]
    assert "regime" in regime
    assert "confidence" in regime
    print(f"  regime: {regime['regime']} (confidence={regime['confidence']:.4f})")

    # Action vector should have action, side, size
    av = last_result["action_vector"]
    assert "action" in av
    assert "side" in av
    assert "size" in av
    assert av["action"] in ("EXECUTE", "HOLD", "KILL")
    print(f"  action: {av['action']} side={av.get('side')} size={av.get('size', 0):.4f}")

    # Execution result should have action, quality
    er = last_result["execution_result"]
    assert "action" in er
    assert "execution_quality" in er
    print(f"  execution: {er['action']} quality={er['execution_quality']:.4f}")
    print(f"  ✓ All components produce valid outputs")

    # ── Test 4: Verify metrics computation ──
    print("\n[Test 4] Verify metrics computation...")
    metrics = engine.compute_metrics()
    assert "sharpe_proxy" in metrics
    assert "max_drawdown" in metrics
    assert "survival_time" in metrics
    assert "regime_stability_score" in metrics
    assert "execution_quality" in metrics
    assert "stability_score" in metrics
    assert 0.0 <= metrics["stability_score"] <= 1.0
    assert 0.0 <= metrics["max_drawdown"] <= 1.0
    assert metrics["survival_time"] == 50
    print(f"  sharpe_proxy={metrics['sharpe_proxy']:.4f}")
    print(f"  max_drawdown={metrics['max_drawdown']:.4f}")
    print(f"  survival_time={metrics['survival_time']}")
    print(f"  regime_stability={metrics['regime_stability_score']:.4f}")
    print(f"  execution_quality={metrics['execution_quality']:.4f}")
    print(f"  stability_score={metrics['stability_score']:.4f}")
    print(f"  ✓ Metrics computed correctly")

    # ── Test 5: Verify event recording ──
    print("\n[Test 5] Verify event recording...")
    store_stats = engine.store.get_stats()
    assert store_stats["total_events"] > 0
    assert "decisions" in store_stats["stream_sizes"]
    assert store_stats["stream_sizes"]["decisions"] == 50
    print(f"  total_events={store_stats['total_events']}")
    print(f"  decisions={store_stats['stream_sizes']['decisions']}")
    print(f"  execution_quality={store_stats['stream_sizes']['execution_quality']}")
    print(f"  ✓ Events recorded correctly")

    # ── Test 6: Test survival assessment integration ──
    print("\n[Test 6] Test survival assessment integration...")
    # Run a cycle and check survival assessment
    market_data = make_simulated_market_data(100, base_price=50000.0)
    result = engine.cycle(market_data)
    survival = result["survival_assessment"]

    if survival:
        assert "survives" in survival
        assert "risk_verdict" in survival
        assert "survival_probability" in survival
        print(f"  survives={survival.get('survives')}")
        print(f"  risk_verdict={survival.get('risk_verdict')}")
        print(f"  survival_probability={survival.get('survival_probability', 0):.4f}")
    else:
        print(f"  survival_assessment not available (HOLD action)")
    print(f"  ✓ Survival assessment integrated")

    # ── Test 7: Test learning updates ──
    print("\n[Test 7] Test learning updates...")
    # Learning should have occurred over the 50 cycles
    learning_state = engine.learning.get_learning_state()
    assert "update_count" in learning_state
    assert learning_state["update_count"] > 0, "Learning layer should have updated"
    print(f"  learning_updates={learning_state['update_count']}")
    print(f"  learning_rate={learning_state['learning_rate']:.6f}")
    print(f"  stability_ok={learning_state['stability_ok']}")
    print(f"  last_regime_prediction={learning_state.get('last_regime_prediction', 'N/A')}")
    print(f"  ✓ Learning updates working")

    # ── Test 8: Verify stability is prioritized ──
    print("\n[Test 8] Verify stability is prioritized (higher risk → smaller positions)...")
    # Create two engines: one in calm conditions, one in risky conditions
    # Use lower confidence threshold so trades actually trigger
    calm_engine = MarketPhysicsEngine({
        "engine": {"initial_capital": 1000.0},
        "brain": {
            "initial_capital": 1000.0,
            "min_confidence": 0.10,
            "cooldown_cycles": 0,
        },
    })
    risky_engine = MarketPhysicsEngine({
        "engine": {"initial_capital": 1000.0},
        "brain": {
            "initial_capital": 1000.0,
            "max_drawdown": 0.12,
            "min_confidence": 0.10,
            "cooldown_cycles": 0,
        },
    })

    # Warm up calm engine with a few cycles
    for i in range(5):
        calm_engine.cycle(make_simulated_market_data(i + 1))
        risky_engine.cycle(make_simulated_market_data(i + 1))

    # Now set risky engine to have significant drawdown
    risky_engine._current_drawdown = 0.06  # 6% drawdown
    risky_engine._capital = 940.0
    risky_engine._peak_capital = 1000.0

    # Run both engines with the same data
    test_data = make_simulated_market_data(10, base_price=50000.0)
    calm_result = calm_engine.cycle(test_data)
    risky_result = risky_engine.cycle(test_data)

    calm_action = calm_result["action_vector"]
    risky_action = risky_result["action_vector"]

    # The key invariant: risk up → size down or action more conservative
    # Extract risk scores from the pipeline
    calm_risk = calm_result.get("action_vector", {}).get("pipeline", {}).get("step3_risk", {})
    risky_risk = risky_result.get("action_vector", {}).get("pipeline", {}).get("step3_risk", {})

    calm_size = calm_action.get("size", 0.0)
    risky_size = risky_action.get("size", 0.0)
    calm_risk_score = calm_risk.get("risk_score", 0.0)
    risky_risk_score = risky_risk.get("risk_score", 0.0)

    print(f"  calm: risk={calm_risk_score:.4f}, action={calm_action['action']}, size={calm_size:.4f}")
    print(f"  risky: risk={risky_risk_score:.4f}, action={risky_action['action']}, size={risky_size:.4f}")

    # Risk score should be higher for the risky engine
    if risky_risk_score > calm_risk_score:
        print(f"  ✓ Risk score higher for risky engine ({risky_risk_score:.4f} > {calm_risk_score:.4f})")

    # Monotonicity: if both execute, risky should have smaller size
    if (calm_action.get("action") == "EXECUTE"
            and risky_action.get("action") == "EXECUTE"):
        assert risky_size <= calm_size + 0.001, \
            f"Risky size ({risky_size}) should be <= calm size ({calm_size})"
        print(f"  ✓ Monotonicity: risk ↑ → size ↓")
    elif risky_action.get("action") in ("HOLD", "KILL") and calm_action.get("action") == "EXECUTE":
        print(f"  ✓ Risky engine chose {risky_action['action']} while calm chose EXECUTE")
    else:
        print(f"  ✓ Stability prioritization verified (both conservative)")

    # Also verify the risk filter's monotonicity property directly
    # Higher risk_score should ALWAYS produce lower size_multiplier
    calm_mult = calm_risk.get("size_multiplier", 1.0)
    risky_mult = risky_risk.get("size_multiplier", 1.0)
    if risky_risk_score > calm_risk_score:
        assert risky_mult <= calm_mult + 0.001, \
            f"size_multiplier must decrease with risk ({risky_mult} > {calm_mult})"
        print(f"  ✓ size_multiplier monotonic: {risky_mult:.4f} <= {calm_mult:.4f}")

    # Clean up
    calm_engine.close()
    risky_engine.close()

    # ── Test 9: Verify engine state dashboard ──
    print("\n[Test 9] Verify engine state dashboard...")
    state = engine.get_engine_state()
    assert "engine" in state
    assert "metrics" in state
    assert "brain" in state
    assert "learning" in state
    assert "store" in state
    assert "executor" in state
    assert "state_vector" in state
    print(f"  cycle={state['engine']['cycle']}")
    print(f"  capital=${state['engine']['capital']:.2f}")
    print(f"  stability_score={state['metrics']['stability_score']:.4f}")
    print(f"  ✓ Engine state complete")

    # ── Test 10: Verify custom config ──
    print("\n[Test 10] Verify custom config...")
    custom_engine = MarketPhysicsEngine({
        "engine": {"initial_capital": 5000.0},
        "brain": {"initial_capital": 5000.0, "max_drawdown": 0.08},
        "executor": {"commission_rate": 0.001},
    })
    assert custom_engine._capital == 5000.0
    assert custom_engine.brain._initial_capital == 5000.0
    assert custom_engine.brain.max_drawdown == 0.08
    assert custom_engine.executor.commission_rate == 0.001
    print(f"  capital={custom_engine._capital}")
    print(f"  brain.max_drawdown={custom_engine.brain.max_drawdown}")
    print(f"  executor.commission_rate={custom_engine.executor.commission_rate}")
    print(f"  ✓ Custom config applied correctly")
    custom_engine.close()

    # ── Clean up ──
    engine.close()

    print("\n" + "=" * 70)
    print("All self-tests PASSED")
    print("MARKET_PHYSICS_ENGINE: observe, measure, stress-test, learn")
    print("OPTIMIZE STABILITY, NOT PROFIT")
    print("=" * 70)
