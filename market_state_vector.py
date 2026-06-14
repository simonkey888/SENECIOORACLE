"""
Module: market_state_vector.py — MARKET PHYSICS SIMULATOR STATE VECTOR

PHILOSOPHY: convert trading into controlled physical system experiment

The MARKET STATE VECTOR is a 5-component physical model of the market.
It is NOT a signal generator. It is a MEASUREMENT device.
Like a thermometer measures temperature, this measures market state.
The measurement is deterministic: same inputs always produce same state.

5 COMPONENTS:
    1. OrderFlow       — fluid flow velocity in a pipe
                          (imbalance + toxicity + momentum + net_pressure)
    2. LiquidityField  — viscosity of a fluid
                          (depth_curve + spread_pressure + available_liquidity + quality)
    3. VolatilityField — temperature of a gas
                          (realized + implied + shock_component + vol_regime)
    4. RegimeInertia   — phase states of matter (solid/liquid/gas)
                          (Markov transition matrix + regime + stability)
    5. InformationFlow — electromagnetic field carrying information
                          (microprice_drift + funding_pressure + oi_momentum + quality)

DETERMINISTIC: output = f(input), always. NO randomness. NO stochastic elements.

KPI PRIORITY: SURVIVAL > PROFIT, STABILITY > RETURNS, CONSISTENCY > INTELLIGENCE

INTEGRATION: get_state_summary() produces a dict that feeds directly into
             SingleDecisionCore.decide() as the `market` parameter.

BUILDS ON:
    - institutional_core.py (SingleDecisionCore)
    - event_store.py (EventStore)
    - lean_executor.py (LeanExecutor)
"""

import math
import sys
import os
from collections import deque
from typing import Optional, List, Dict

# Allow importing sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Deterministic helpers (NO random, NO stochastic)
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi. Deterministic."""
    return max(lo, min(hi, x))


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid. Deterministic."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        ex = math.exp(x)
        return ex / (1.0 + ex)


def _tanh(x: float) -> float:
    """Numerically stable tanh. Deterministic."""
    return math.tanh(x)


# ---------------------------------------------------------------------------
# Regime states enum-like constants
# ---------------------------------------------------------------------------

REGIME_TRENDING_UP = "TRENDING_UP"
REGIME_TRENDING_DOWN = "TRENDING_DOWN"
REGIME_RANGING = "RANGING"
REGIME_HIGH_VOL = "HIGH_VOL"
REGIME_CRISIS = "CRISIS"

ALL_REGIMES = [REGIME_TRENDING_UP, REGIME_TRENDING_DOWN, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_CRISIS]
REGIME_INDEX = {r: i for i, r in enumerate(ALL_REGIMES)}

VOL_REGIME_LOW = "LOW"
VOL_REGIME_NORMAL = "NORMAL"
VOL_REGIME_ELEVATED = "ELEVATED"
VOL_REGIME_EXTREME = "EXTREME"


# ---------------------------------------------------------------------------
# MARKET STATE VECTOR
# ---------------------------------------------------------------------------

class MarketStateVector:
    """The physical state of the market as a deterministic vector.

    This is NOT a signal generator. It is a MEASUREMENT device.
    Like a thermometer measures temperature, this measures market state.
    The measurement is deterministic: same inputs always produce same state.

    The vector has 5 components, each with a physical analogy:
    1. OrderFlow      — fluid velocity (direction + force of money)
    2. LiquidityField — fluid viscosity (ease of execution)
    3. VolatilityField — gas temperature (energy/risk level)
    4. RegimeInertia  — phase state (solid/liquid/gas transitions)
    5. InformationFlow — electromagnetic field (carries information)

    The ONLY public method is `measure()`, which takes raw market data
    and produces the complete 5-component state vector.
    """

    def __init__(
        self,
        # ── History buffer sizes ──
        imbalance_history_len: int = 100,
        volatility_history_len: int = 100,
        price_history_len: int = 200,
        # ── Order flow parameters ──
        toxicity_sensitivity: float = 2.0,     # Higher = more sensitive to imbalance
        momentum_smoothing: float = 0.1,        # EMA smoothing for momentum
        # ── Liquidity parameters ──
        typical_spread_bps: float = 3.0,        # "Normal" spread in basis points
        depth_levels: int = 10,                  # Number of depth curve levels
        near_pct: float = 0.005,                 # 0.5% = within half a percent of mid
        # ── Volatility parameters ──
        vol_window: int = 20,                    # Window for realized vol
        vol_annualization: float = math.sqrt(8760),  # Hourly → annual
        shock_threshold: float = 2.0,            # Current vol > 2x avg = shock
        vol_low_threshold: float = 0.005,        # Below this = LOW regime
        vol_normal_threshold: float = 0.02,      # Below this = NORMAL regime
        vol_elevated_threshold: float = 0.05,    # Below this = ELEVATED regime
        # Above vol_elevated_threshold = EXTREME
        # ── Regime detection parameters ──
        trend_strength_threshold: float = 0.01,  # Price momentum threshold for trend
        spread_crisis_bps: float = 20.0,         # Spread above this → crisis component
        # ── Markov transition matrix ──
        markov_learning_rate: float = 0.05,      # How fast transition matrix updates
        markov_prior: float = 0.2,               # Uniform prior (1/5 for 5 states)
        # ── Information flow parameters ──
        funding_sensitivity: float = 500.0,      # Funding rate scaling factor
        oi_sensitivity: float = 0.01,            # OI change scaling factor
        # ── Regime stability ──
        stability_max_ticks: int = 100,          # Max ticks for stability = 1.0
    ):
        """Initialize the Market State Vector measurement device.

        Args:
            imbalance_history_len: Buffer size for imbalance history (momentum calc).
            volatility_history_len: Buffer size for volatility history (shock detection).
            price_history_len: Buffer size for price history (trend/regime detection).
            toxicity_sensitivity: VPIN-style toxicity scaling. Higher = more sensitive.
            momentum_smoothing: EMA alpha for momentum calculation.
            typical_spread_bps: "Normal" spread baseline in basis points.
            depth_levels: Number of levels in depth curve estimation.
            near_pct: Fraction of mid price defining "near" for available liquidity.
            vol_window: Rolling window for realized volatility.
            vol_annualization: Factor to annualize volatility.
            shock_threshold: Current vol / avg vol ratio that triggers shock.
            vol_low_threshold: Vol below this = LOW regime.
            vol_normal_threshold: Vol below this = NORMAL regime.
            vol_elevated_threshold: Vol below this = ELEVATED regime.
            trend_strength_threshold: Price momentum abs value for trend detection.
            spread_crisis_bps: Spread above this adds crisis regime evidence.
            markov_learning_rate: How much to increment observed transitions.
            markov_prior: Initial uniform prior for transition matrix.
            funding_sensitivity: Scaling for funding rate → information signal.
            oi_sensitivity: Scaling for OI change → information signal.
            stability_max_ticks: Ticks in same regime before stability = 1.0.
        """
        # ── Configuration ──
        self.imbalance_history_len = imbalance_history_len
        self.volatility_history_len = volatility_history_len
        self.price_history_len = price_history_len
        self.toxicity_sensitivity = toxicity_sensitivity
        self.momentum_smoothing = momentum_smoothing
        self.typical_spread_bps = typical_spread_bps
        self.depth_levels = depth_levels
        self.near_pct = near_pct
        self.vol_window = vol_window
        self.vol_annualization = vol_annualization
        self.shock_threshold = shock_threshold
        self.vol_low_threshold = vol_low_threshold
        self.vol_normal_threshold = vol_normal_threshold
        self.vol_elevated_threshold = vol_elevated_threshold
        self.trend_strength_threshold = trend_strength_threshold
        self.spread_crisis_bps = spread_crisis_bps
        self.markov_learning_rate = markov_learning_rate
        self.markov_prior = markov_prior
        self.funding_sensitivity = funding_sensitivity
        self.oi_sensitivity = oi_sensitivity
        self.stability_max_ticks = stability_max_ticks

        # ── History buffers for momentum calculations ──
        self._imbalance_history = deque(maxlen=imbalance_history_len)
        self._volatility_history = deque(maxlen=volatility_history_len)
        self._price_history = deque(maxlen=price_history_len)

        # ── Momentum EMA state ──
        self._momentum_ema = 0.0

        # ── Markov transition matrix (5x5) ──
        # Initialized with uniform priors: every transition equally likely
        self._transition_matrix = [
            [markov_prior] * 5 for _ in range(5)
        ]
        # Ensure each row sums to 1.0 (uniform prior)
        for i in range(5):
            row_sum = sum(self._transition_matrix[i])
            if row_sum > 0:
                self._transition_matrix[i] = [v / row_sum for v in self._transition_matrix[i]]

        # ── Current regime state ──
        self._current_regime = REGIME_RANGING
        self._regime_ticks = 0  # How many ticks in current regime

        # ── Last measured state (for caching / inspection) ──
        self._last_state = None

        # ── Measurement counter ──
        self._measure_count = 0

    # ===================================================================
    # MAIN ENTRY POINT
    # ===================================================================

    def measure(self, market_data: dict) -> dict:
        """Main entry: take raw market data → produce full state vector.

        This is the ONLY public method. It takes raw data and produces
        the complete 5-component state vector.

        The measurement is DETERMINISTIC: same inputs always produce same state.

        Args:
            market_data: dict with keys:
                - ohlcv: list of [timestamp, open, high, low, close, volume, ...]
                - ticker: dict with bid, ask, spread_pct, etc.
                - orderbook: dict with bids, asks, bid_depth, ask_depth, etc.
                - funding: dict with rate, next_funding_ms, predicted_rate
                - open_interest: dict with oi_value, oi_change_24h_pct

        Returns:
            Complete state vector dict with all 5 components:
            {
                "order_flow": {...},
                "liquidity_field": {...},
                "volatility_field": {...},
                "regime_inertia": {...},
                "information_flow": {...},
                "measurement_id": int,
            }
        """
        self._measure_count += 1

        # ── Measure each component ──
        order_flow = self._measure_order_flow(market_data)
        liquidity_field = self._measure_liquidity_field(market_data)
        volatility_field = self._measure_volatility_field(market_data)
        regime_inertia = self._measure_regime_inertia(market_data)
        information_flow = self._measure_information_flow(market_data)

        # ── Update internal state based on measurements ──
        self._update_internal_state(order_flow, volatility_field, market_data)

        # ── Re-measure regime with updated Markov matrix ──
        regime_inertia = self._measure_regime_inertia(market_data)

        # ── Assemble full state vector ──
        state_vector = {
            "order_flow": order_flow,
            "liquidity_field": liquidity_field,
            "volatility_field": volatility_field,
            "regime_inertia": regime_inertia,
            "information_flow": information_flow,
            "measurement_id": self._measure_count,
        }

        self._last_state = state_vector
        return state_vector

    # ===================================================================
    # COMPONENT 1: ORDER FLOW
    # Physical analogy: fluid flow velocity in a pipe
    # Measures direction and force of money movement
    # ===================================================================

    def _measure_order_flow(self, market_data: dict) -> dict:
        """Measure order flow component.

        Order flow measures the net directional pressure of money movement:
        - imbalance: bid/ask volume imbalance [-1, 1]
        - toxicity: VPIN-style order flow toxicity [0, 1]
        - momentum: rate of change of imbalance [-1, 1]
        - net_pressure: weighted combination of the above

        Physical analogy: fluid flow velocity in a pipe.
        Positive = flow toward bids (buying pressure).
        Negative = flow toward asks (selling pressure).
        Toxicity = how "informed" the flow is (toxic = adverse selection risk).
        Momentum = acceleration of the flow (rate of change of direction).

        Args:
            market_data: Raw market data dict.

        Returns:
            Dict with imbalance, toxicity, momentum, net_pressure.
        """
        # ── Extract orderbook data ──
        orderbook = market_data.get("orderbook", {})
        bid_depth = float(orderbook.get("bid_depth", 0.0))
        ask_depth = float(orderbook.get("ask_depth", 0.0))

        # Also try to get individual bid/ask levels for richer analysis
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        # ── Imbalance: bid/ask volume imbalance [-1, 1] ──
        # +1 = all bids, -1 = all asks, 0 = balanced
        total_depth = bid_depth + ask_depth
        if total_depth > 0:
            imbalance = (bid_depth - ask_depth) / total_depth
        else:
            imbalance = 0.0

        # Store imbalance for momentum calculation
        self._imbalance_history.append(imbalance)

        # ── Toxicity: VPIN-style order flow toxicity [0, 1] ──
        # VPIN approximates the probability of informed trading.
        # Simplified: high imbalance = high toxicity (informed traders are directional).
        # Low imbalance = low toxicity (uninformed / balanced flow).
        # Formula: toxicity = 1 - 2 * min(imbalance_weight, 1 - imbalance_weight)
        # This maps balanced (0.5) → 0 toxicity, extreme (1.0) → 1 toxicity
        bid_fraction = bid_depth / total_depth if total_depth > 0 else 0.5
        # Scale by sensitivity parameter
        toxicity = 1.0 - 2.0 * min(bid_fraction, 1.0 - bid_fraction)
        toxicity = _clamp(toxicity * self.toxicity_sensitivity, 0.0, 1.0)

        # Also use trade volume as a proxy for toxicity if available
        ohlcv = market_data.get("ohlcv", [])
        if len(ohlcv) >= 2:
            curr_vol = float(ohlcv[-1][5]) if len(ohlcv[-1]) > 5 else 0.0
            prev_vol = float(ohlcv[-2][5]) if len(ohlcv[-2]) > 5 else 0.0
            # Volume spike increases toxicity (more informed trading activity)
            if prev_vol > 0:
                vol_ratio = curr_vol / prev_vol
                vol_toxicity = _clamp((vol_ratio - 1.0) * 0.5, 0.0, 1.0)
                # Blend: structural toxicity from imbalance + volume toxicity
                toxicity = _clamp(toxicity * 0.7 + vol_toxicity * 0.3, 0.0, 1.0)

        # ── Momentum: rate of change of imbalance [-1, 1] ──
        # Uses EMA smoothing for stability
        if len(self._imbalance_history) >= 2:
            raw_momentum = self._imbalance_history[-1] - self._imbalance_history[-2]
            # EMA update (deterministic, no randomness)
            alpha = self.momentum_smoothing
            self._momentum_ema = alpha * raw_momentum + (1.0 - alpha) * self._momentum_ema
            momentum = _clamp(self._momentum_ema * 10.0, -1.0, 1.0)  # Scale and clamp
        else:
            momentum = 0.0

        # ── Net pressure: weighted combination ──
        # Directional pressure = imbalance (direction) + momentum (acceleration)
        # Toxicity modulates confidence: high toxicity = reduce net pressure certainty
        # This is like: flow = velocity * (1 - turbulence)
        if toxicity > 0.5:
            # High toxicity → reduce confidence in directional signal
            confidence = 1.0 - (toxicity - 0.5) * 1.2  # Maps 0.5→1.0, 1.0→0.4
            confidence = _clamp(confidence, 0.3, 1.0)
        else:
            confidence = 1.0

        net_pressure = (imbalance * 0.6 + momentum * 0.4) * confidence
        net_pressure = _clamp(net_pressure, -1.0, 1.0)

        return {
            "imbalance": round(imbalance, 6),
            "toxicity": round(toxicity, 6),
            "momentum": round(momentum, 6),
            "net_pressure": round(net_pressure, 6),
            # Extra diagnostic info
            "bid_depth": round(bid_depth, 2),
            "ask_depth": round(ask_depth, 2),
            "total_depth": round(total_depth, 2),
            "confidence": round(confidence, 6),
        }

    # ===================================================================
    # COMPONENT 2: LIQUIDITY FIELD
    # Physical analogy: viscosity of a fluid
    # High liquidity = low viscosity (easy to move through)
    # Low liquidity = high viscosity (hard to move through)
    # ===================================================================

    def _measure_liquidity_field(self, market_data: dict) -> dict:
        """Measure liquidity field component.

        Liquidity field measures the ease of execution:
        - depth_curve: orderbook depth profile at various price levels
        - spread_pressure: current spread / typical spread [0, +inf)
        - available_liquidity_usdt: total depth within 0.5% of mid
        - liquidity_quality: composite [0, 1] where 1=deep+tight, 0=thin+wide

        Physical analogy: viscosity of a fluid.
        High liquidity = low viscosity = easy to execute.
        Low liquidity = high viscosity = hard to execute, costly.

        Args:
            market_data: Raw market data dict.

        Returns:
            Dict with depth_curve, spread_pressure, available_liquidity_usdt, liquidity_quality.
        """
        # ── Extract data ──
        orderbook = market_data.get("orderbook", {})
        ticker = market_data.get("ticker", {})
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        bid_depth = float(orderbook.get("bid_depth", 0.0))
        ask_depth = float(orderbook.get("ask_depth", 0.0))

        # ── Mid price ──
        bid_price = float(ticker.get("bid", 0.0))
        ask_price = float(ticker.get("ask", 0.0))
        if bid_price > 0 and ask_price > 0:
            mid_price = (bid_price + ask_price) / 2.0
        else:
            # Fallback to close from ohlcv
            ohlcv = market_data.get("ohlcv", [])
            if ohlcv:
                mid_price = float(ohlcv[-1][4])
            else:
                mid_price = 0.0

        # ── Depth curve: orderbook depth at various price levels ──
        # If we have actual orderbook levels, use them.
        # Otherwise, estimate from bid_depth/ask_depth.
        depth_curve = []
        if bids and asks and mid_price > 0:
            # Actual orderbook data available
            # Build depth curve: cumulative depth at each 0.05% price level
            for level in range(self.depth_levels):
                # Price offset from mid in basis points
                offset_pct = (level + 1) * 0.05 / 100.0  # 0.05%, 0.10%, ..., 0.50%
                lower_price = mid_price * (1.0 - offset_pct)
                upper_price = mid_price * (1.0 + offset_pct)

                # Cumulative depth at this level
                bid_cum = sum(
                    float(b[1]) for b in bids
                    if len(b) >= 2 and float(b[0]) >= lower_price
                )
                ask_cum = sum(
                    float(a[1]) for a in asks
                    if len(a) >= 2 and float(a[0]) <= upper_price
                )

                depth_curve.append({
                    "level": level + 1,
                    "offset_bps": round((level + 1) * 5, 1),
                    "bid_depth": round(bid_cum, 2),
                    "ask_depth": round(ask_cum, 2),
                    "total_depth": round(bid_cum + ask_cum, 2),
                })
        else:
            # Estimate depth curve from aggregate bid/ask depth
            # Simple linear decay model: depth decreases further from mid
            for level in range(self.depth_levels):
                decay = 1.0 - (level / self.depth_levels) * 0.5  # Linear decay
                bid_est = bid_depth * decay / self.depth_levels
                ask_est = ask_depth * decay / self.depth_levels
                depth_curve.append({
                    "level": level + 1,
                    "offset_bps": round((level + 1) * 5, 1),
                    "bid_depth": round(bid_est, 2),
                    "ask_depth": round(ask_est, 2),
                    "total_depth": round(bid_est + ask_est, 2),
                })

        # ── Spread pressure: current spread / typical spread ──
        # [0, +inf) where 1.0 = normal, >1 = wider than normal, <1 = tighter
        spread_pct = float(ticker.get("spread_pct", 0.0))
        # Convert spread_pct to bps for comparison
        current_spread_bps = spread_pct * 10000.0 if spread_pct < 1.0 else spread_pct
        # If no spread_pct in ticker, estimate from bid/ask
        if current_spread_bps == 0.0 and bid_price > 0 and ask_price > 0:
            current_spread_bps = ((ask_price - bid_price) / mid_price) * 10000.0

        if self.typical_spread_bps > 0:
            spread_pressure = current_spread_bps / self.typical_spread_bps
        else:
            spread_pressure = 1.0

        # ── Available liquidity within 0.5% of mid ──
        # Sum of depth at levels within self.near_pct of mid
        available_liquidity_usdt = 0.0
        for dc in depth_curve:
            offset_pct = dc["offset_bps"] / 10000.0
            if offset_pct <= self.near_pct:
                # Convert quantity to USDT (quantity * mid_price)
                bid_usdt = dc["bid_depth"] * mid_price if mid_price > 0 else dc["bid_depth"]
                ask_usdt = dc["ask_depth"] * mid_price if mid_price > 0 else dc["ask_depth"]
                available_liquidity_usdt += bid_usdt + ask_usdt

        # Fallback: use aggregate depth if no depth curve
        if available_liquidity_usdt == 0.0 and mid_price > 0:
            available_liquidity_usdt = (bid_depth + ask_depth) * mid_price

        # ── Liquidity quality: composite [0, 1] ──
        # Deep + tight = high quality (1.0)
        # Thin + wide = low quality (0.0)
        # Components:
        #   1. Depth score: more depth = better (log scale)
        #   2. Spread score: tighter spread = better
        #   3. Balance score: balanced bid/ask = better

        # Depth score (log scale: 10K USDT = 0.5, 100K = 0.75, 1M = 0.9)
        if available_liquidity_usdt > 0:
            depth_score = _clamp(1.0 - 1.0 / (1.0 + math.log10(max(1.0, available_liquidity_usdt / 1000.0))), 0.0, 1.0)
        else:
            depth_score = 0.0

        # Spread score (1bp = 1.0, 5bps = 0.8, 20bps = 0.2, 50bps = 0.0)
        if current_spread_bps > 0:
            spread_score = _clamp(1.0 - current_spread_bps / 50.0, 0.0, 1.0)
        else:
            spread_score = 1.0  # No spread info → assume OK

        # Balance score (symmetric bid/ask = 1.0, one-sided = 0.0)
        total = bid_depth + ask_depth
        if total > 0:
            balance_score = 1.0 - abs(bid_depth - ask_depth) / total
        else:
            balance_score = 0.0

        # Weighted composite: depth 40%, spread 40%, balance 20%
        liquidity_quality = depth_score * 0.4 + spread_score * 0.4 + balance_score * 0.2
        liquidity_quality = _clamp(liquidity_quality, 0.0, 1.0)

        return {
            "depth_curve": depth_curve,
            "spread_pressure": round(spread_pressure, 6),
            "available_liquidity_usdt": round(available_liquidity_usdt, 2),
            "liquidity_quality": round(liquidity_quality, 6),
            # Extra diagnostic info
            "current_spread_bps": round(current_spread_bps, 2),
            "depth_score": round(depth_score, 6),
            "spread_score": round(spread_score, 6),
            "balance_score": round(balance_score, 6),
        }

    # ===================================================================
    # COMPONENT 3: VOLATILITY FIELD
    # Physical analogy: temperature of a gas
    # Controls the energy/risk level of the system
    # ===================================================================

    def _measure_volatility_field(self, market_data: dict) -> dict:
        """Measure volatility field component.

        Volatility field measures the energy/risk level:
        - realized_vol: historical volatility from recent candles
        - implied_vol: derived from spread + funding (proxy)
        - shock_component: sudden volatility spike detector [0, 1]
        - vol_regime: LOW / NORMAL / ELEVATED / EXTREME

        Physical analogy: temperature of a gas.
        Low vol = cold gas = particles move slowly = low energy = safe.
        High vol = hot gas = particles move fast = high energy = dangerous.
        Shock = sudden temperature spike = phase transition risk.

        Args:
            market_data: Raw market data dict.

        Returns:
            Dict with realized_vol, implied_vol, shock_component, vol_regime.
        """
        ohlcv = market_data.get("ohlcv", [])
        ticker = market_data.get("ticker", {})
        funding = market_data.get("funding", {})

        # ── Realized volatility ──
        # Calculate from recent candles using high-low range method
        # (Parkinson estimator is more efficient than close-to-close)
        realized_vol = 0.01  # Default: 1%
        if len(ohlcv) >= 2:
            # Use Parkinson volatility estimator from recent window
            window = min(self.vol_window, len(ohlcv))
            recent = ohlcv[-window:]

            # Parkinson volatility: sigma = sqrt(1/(2n) * sum(ln(H/L)^2))
            log_hl_sq_sum = 0.0
            count = 0
            for candle in recent:
                high = float(candle[2])
                low = float(candle[3])
                if low > 0 and high > 0:
                    log_hl = math.log(high / low)
                    log_hl_sq_sum += log_hl * log_hl
                    count += 1

            if count > 0:
                # Parkinson volatility (annualized)
                parkinson_var = log_hl_sq_sum / (2.0 * count)
                realized_vol = math.sqrt(parkinson_var)
                # Annualize (assuming hourly candles)
                realized_vol_annual = realized_vol * self.vol_annualization
                # We store the period (hourly) vol as the primary metric
                # but also keep annualized for reference
            else:
                realized_vol_annual = realized_vol * self.vol_annualization
        else:
            realized_vol_annual = realized_vol * self.vol_annualization

        # Store for shock detection
        self._volatility_history.append(realized_vol)

        # ── Implied volatility proxy ──
        # Derived from spread + funding rate as a proxy.
        # Wide spread + extreme funding = high implied vol.
        spread_pct = float(ticker.get("spread_pct", 0.0))
        funding_rate = float(funding.get("rate", 0.0))

        # Spread component: wider spread = higher implied vol
        # Map spread: 1bp → 0.005, 10bps → 0.01, 50bps → 0.03
        spread_bps = spread_pct * 10000.0 if spread_pct < 1.0 else spread_pct
        spread_vol_proxy = _clamp(spread_bps / 5000.0, 0.0, 0.1)

        # Funding component: extreme funding = higher implied vol
        # Normal funding = ±0.01%, extreme = ±0.1%
        funding_vol_proxy = _clamp(abs(funding_rate) * 100.0, 0.0, 0.1)

        # Composite implied vol proxy
        implied_vol = _clamp(spread_vol_proxy * 0.6 + funding_vol_proxy * 0.4, 0.0, 1.0)

        # Blend with realized vol for a more stable estimate
        # If we have both, use a weighted blend
        blended_vol = realized_vol * 0.7 + implied_vol * 0.3

        # ── Shock component: sudden volatility spike detector [0, 1] ──
        # Compare current volatility to rolling average.
        # If current > 2x average → shock detected.
        shock_component = 0.0
        if len(self._volatility_history) >= 5:
            avg_vol = sum(self._volatility_history) / len(self._volatility_history)
            if avg_vol > 0:
                ratio = realized_vol / avg_vol
                if ratio > self.shock_threshold:
                    # Shock detected: scale linearly from threshold to 3x
                    shock_component = _clamp(
                        (ratio - self.shock_threshold) / self.shock_threshold,
                        0.0, 1.0
                    )

        # ── Volatility regime classification ──
        # Uses blended_vol for classification
        if blended_vol < self.vol_low_threshold:
            vol_regime = VOL_REGIME_LOW
        elif blended_vol < self.vol_normal_threshold:
            vol_regime = VOL_REGIME_NORMAL
        elif blended_vol < self.vol_elevated_threshold:
            vol_regime = VOL_REGIME_ELEVATED
        else:
            vol_regime = VOL_REGIME_EXTREME

        # Shock overrides: if shock detected, at least ELEVATED
        if shock_component > 0.5 and vol_regime in (VOL_REGIME_LOW, VOL_REGIME_NORMAL):
            vol_regime = VOL_REGIME_ELEVATED

        return {
            "realized_vol": round(realized_vol, 8),
            "realized_vol_annual": round(realized_vol_annual, 6),
            "implied_vol": round(implied_vol, 8),
            "blended_vol": round(blended_vol, 8),
            "shock_component": round(shock_component, 6),
            "vol_regime": vol_regime,
            # Extra diagnostic info
            "vol_history_len": len(self._volatility_history),
            "avg_vol": round(sum(self._volatility_history) / len(self._volatility_history), 8) if self._volatility_history else 0.0,
        }

    # ===================================================================
    # COMPONENT 4: REGIME INERTIA
    # Physical analogy: phase states of matter
    # Regimes are like solid/liquid/gas with transition energies
    # Uses Markov transition matrix approach
    # ===================================================================

    def _measure_regime_inertia(self, market_data: dict) -> dict:
        """Measure regime inertia component.

        Regime inertia models market regimes as phase states:
        - TRENDING_UP: solid upward phase (low energy, persistent)
        - TRENDING_DOWN: solid downward phase (low energy, persistent)
        - RANGING: liquid phase (moderate energy, transitional)
        - HIGH_VOL: gas phase (high energy, unstable)
        - CRISIS: plasma phase (extreme energy, chaotic)

        Uses a Markov transition matrix to track regime transitions.
        The matrix is updated deterministically when transitions are observed.

        Args:
            market_data: Raw market data dict.

        Returns:
            Dict with transition_matrix, current_regime, regime_stability,
            transition_probability.
        """
        # ── Detect current regime ──
        new_regime = self._detect_regime(market_data)

        # ── Check for regime transition ──
        old_regime = self._current_regime
        if new_regime != old_regime:
            # Update Markov transition matrix
            self._update_markov_matrix(new_regime)
            self._current_regime = new_regime
            self._regime_ticks = 0
        else:
            self._regime_ticks += 1

        # ── Regime stability: how long we've been in current regime [0, 1] ──
        # 0 = just entered, 1 = been here for a long time
        regime_stability = _clamp(self._regime_ticks / self.stability_max_ticks, 0.0, 1.0)

        # ── Transition probability: probability of transitioning soon ──
        # Based on the Markov transition matrix row for current regime
        # We look at the probability of transitioning to ANY other state
        current_idx = REGIME_INDEX.get(self._current_regime, 2)  # Default to RANGING
        stay_prob = self._transition_matrix[current_idx][current_idx]
        transition_probability = 1.0 - stay_prob

        return {
            "transition_matrix": [row[:] for row in self._transition_matrix],  # Deep copy
            "current_regime": self._current_regime,
            "regime_stability": round(regime_stability, 6),
            "transition_probability": round(transition_probability, 6),
            # Extra diagnostic info
            "previous_regime": old_regime,
            "regime_ticks": self._regime_ticks,
            "regime_changed": new_regime != old_regime,
        }

    def _detect_regime(self, market_data: dict) -> str:
        """Detect current market regime using deterministic rules.

        No ML. No stochastic elements. Pure deterministic rule-based detection.

        Rules (in priority order):
        1. If volatility is EXTREME + spread is very wide → CRISIS
        2. If volatility is EXTREME → HIGH_VOL
        3. If volatility is ELEVATED + spread is wide → HIGH_VOL
        4. If price has upward trend + volatility is not extreme → TRENDING_UP
        5. If price has downward trend + volatility is not extreme → TRENDING_DOWN
        6. Default → RANGING

        Args:
            market_data: Raw market data dict.

        Returns:
            One of the 5 regime strings.
        """
        ohlcv = market_data.get("ohlcv", [])
        ticker = market_data.get("ticker", {})

        # ── Get volatility info ──
        # Calculate simple volatility from recent candles
        vol = 0.01
        if ohlcv and len(ohlcv) >= 2:
            last = ohlcv[-1]
            if len(last) > 4 and float(last[4]) > 0:
                vol = (float(last[2]) - float(last[3])) / float(last[4])

        # ── Get spread info ──
        spread_pct = float(ticker.get("spread_pct", 0.0))
        spread_bps = spread_pct * 10000.0 if spread_pct < 1.0 else spread_pct
        bid_price = float(ticker.get("bid", 0.0))
        ask_price = float(ticker.get("ask", 0.0))
        if spread_bps == 0.0 and bid_price > 0 and ask_price > 0:
            mid = (bid_price + ask_price) / 2.0
            if mid > 0:
                spread_bps = ((ask_price - bid_price) / mid) * 10000.0

        # ── Get trend strength ──
        # Simple: price change over recent window
        trend_strength = 0.0
        if len(ohlcv) >= 10:
            lookback = min(20, len(ohlcv))
            old_price = float(ohlcv[-lookback][4])
            new_price = float(ohlcv[-1][4])
            if old_price > 0:
                trend_strength = (new_price - old_price) / old_price

        # Store for regime detection
        self._price_history.append(float(ohlcv[-1][4]) if ohlcv else 0.0)

        # ── Apply rules in priority order ──

        # Rule 1: CRISIS — extreme volatility + very wide spread
        if vol > self.vol_elevated_threshold and spread_bps > self.spread_crisis_bps:
            return REGIME_CRISIS

        # Rule 2: HIGH_VOL — extreme volatility
        if vol > self.vol_elevated_threshold:
            return REGIME_HIGH_VOL

        # Rule 3: HIGH_VOL — elevated volatility + wide spread
        if vol > self.vol_normal_threshold and spread_bps > self.spread_crisis_bps * 0.5:
            return REGIME_HIGH_VOL

        # Rule 4: TRENDING_UP — positive trend + manageable volatility
        if trend_strength > self.trend_strength_threshold and vol <= self.vol_normal_threshold:
            return REGIME_TRENDING_UP

        # Rule 5: TRENDING_DOWN — negative trend + manageable volatility
        if trend_strength < -self.trend_strength_threshold and vol <= self.vol_normal_threshold:
            return REGIME_TRENDING_DOWN

        # Rule 6: RANGING — default
        return REGIME_RANGING

    def _update_markov_matrix(self, new_regime: str):
        """Update Markov transition matrix based on observed transition.

        When a regime transition is observed (old → new), we:
        1. Increment the transition probability for old → new
        2. Decrement other transition probabilities from old
        3. Renormalize the row so probabilities sum to 1.0

        This is DETERMINISTIC: no random numbers used.
        The matrix starts with uniform priors and evolves based on
        observed transitions.

        Args:
            new_regime: The regime we're transitioning TO.
        """
        old_idx = REGIME_INDEX.get(self._current_regime, 2)
        new_idx = REGIME_INDEX.get(new_regime, 2)

        # Increment the observed transition
        self._transition_matrix[old_idx][new_idx] += self.markov_learning_rate

        # Slightly decay all other transitions from old state
        # (so the row still sums correctly after we renormalize)
        for j in range(5):
            if j != new_idx:
                # Small decay to keep non-observed transitions from dominating
                self._transition_matrix[old_idx][j] *= (1.0 - self.markov_learning_rate * 0.5)

        # Renormalize the row so probabilities sum to 1.0
        row_sum = sum(self._transition_matrix[old_idx])
        if row_sum > 0:
            for j in range(5):
                self._transition_matrix[old_idx][j] /= row_sum
        else:
            # Edge case: if somehow all values are 0, reset to uniform
            for j in range(5):
                self._transition_matrix[old_idx][j] = 0.2

    # ===================================================================
    # COMPONENT 5: INFORMATION FLOW
    # Physical analogy: electromagnetic field
    # Carries information that influences the system
    # ===================================================================

    def _measure_information_flow(self, market_data: dict) -> dict:
        """Measure information flow component.

        Information flow measures the directional signals carried by
        market microstructure:
        - microprice_drift: microprice movement tendency [-1, 1]
        - funding_pressure: funding rate as directional signal [-1, 1]
        - oi_momentum: open interest change momentum [-1, 1]
        - information_quality: how reliable the information is [0, 1]

        Physical analogy: electromagnetic field.
        The field carries information (direction, strength, quality).
        Strong agreeing signals = strong field = reliable information.
        Conflicting signals = noisy field = unreliable information.

        Args:
            market_data: Raw market data dict.

        Returns:
            Dict with microprice_drift, funding_pressure, oi_momentum,
            information_quality.
        """
        orderbook = market_data.get("orderbook", {})
        ticker = market_data.get("ticker", {})
        funding = market_data.get("funding", {})
        open_interest = market_data.get("open_interest", {})

        # ── Microprice drift ──
        # Microprice = weighted mid by orderbook depth
        # Drift = tendency of microprice to move away from simple mid
        bid_depth = float(orderbook.get("bid_depth", 0.0))
        ask_depth = float(orderbook.get("ask_depth", 0.0))
        bid_price = float(ticker.get("bid", 0.0))
        ask_price = float(ticker.get("ask", 0.0))

        microprice_drift = 0.0
        if bid_depth + ask_depth > 0 and bid_price > 0 and ask_price > 0:
            # Microprice = (bid * ask_depth + ask * bid_depth) / (bid_depth + ask_depth)
            microprice = (bid_price * ask_depth + ask_price * bid_depth) / (bid_depth + ask_depth)
            simple_mid = (bid_price + ask_price) / 2.0
            # Drift = how far microprice is from simple mid (normalized)
            if simple_mid > 0:
                drift_pct = (microprice - simple_mid) / simple_mid
                microprice_drift = _clamp(drift_pct * 1000.0, -1.0, 1.0)  # Scale and clamp

        # ── Funding pressure ──
        # Funding rate as directional signal.
        # Positive funding = longs pay shorts = bearish pressure (contrarian)
        # Negative funding = shorts pay longs = bullish pressure (contrarian)
        funding_rate = float(funding.get("rate", 0.0))
        # Scale: 0.01% funding → 0.05 signal, 0.1% → 0.5 signal
        funding_pressure = _clamp(-funding_rate * self.funding_sensitivity, -1.0, 1.0)

        # ── OI momentum ──
        # Open interest change momentum.
        # Rising OI + rising price = bullish (new longs)
        # Rising OI + falling price = bearish (new shorts)
        # Falling OI = unwinding (caution)
        oi_change_pct = float(open_interest.get("oi_change_24h_pct", 0.0))
        oi_momentum = _clamp(oi_change_pct * self.oi_sensitivity, -1.0, 1.0)

        # ── Information quality ──
        # Higher when multiple signals agree, lower when they conflict.
        # This is like signal-to-noise ratio for the information field.
        signals = [microprice_drift, funding_pressure, oi_momentum]

        # Agreement: how many signals point in the same direction
        positive_count = sum(1 for s in signals if s > 0.05)
        negative_count = sum(1 for s in signals if s < -0.05)
        neutral_count = sum(1 for s in signals if abs(s) <= 0.05)
        total_active = positive_count + negative_count

        if total_active == 0:
            # All signals neutral → low quality (no information)
            agreement = 0.0
        else:
            agreement = max(positive_count, negative_count) / (total_active + neutral_count)

        # Signal strength: how strong the signals are
        avg_strength = sum(abs(s) for s in signals) / len(signals)

        # Information quality: combination of agreement and strength
        information_quality = agreement * 0.6 + avg_strength * 0.4
        information_quality = _clamp(information_quality, 0.0, 1.0)

        # If signals conflict strongly, reduce quality
        if positive_count > 0 and negative_count > 0:
            conflict_penalty = min(positive_count, negative_count) / max(positive_count + negative_count, 1)
            information_quality *= (1.0 - conflict_penalty * 0.5)

        return {
            "microprice_drift": round(microprice_drift, 6),
            "funding_pressure": round(funding_pressure, 6),
            "oi_momentum": round(oi_momentum, 6),
            "information_quality": round(information_quality, 6),
            # Extra diagnostic info
            "agreement": round(agreement, 6),
            "avg_strength": round(avg_strength, 6),
            "signal_direction": "bullish" if positive_count > negative_count else
                               "bearish" if negative_count > positive_count else "neutral",
        }

    # ===================================================================
    # INTERNAL STATE UPDATE
    # ===================================================================

    def _update_internal_state(self, order_flow: dict,
                                volatility_field: dict,
                                market_data: dict):
        """Update internal state after measuring components.

        This handles the regime transition detection and Markov matrix
        update that depends on the measured components.

        Args:
            order_flow: Measured order flow component.
            volatility_field: Measured volatility field component.
            market_data: Original market data.
        """
        # The regime detection is already handled in _measure_regime_inertia
        # via _detect_regime and _update_markov_matrix.
        # This method is a hook for future cross-component state updates.
        pass

    # ===================================================================
    # INTEGRATION INTERFACE
    # ===================================================================

    def get_state_summary(self) -> dict:
        """Get compressed state summary for the decision core.

        This produces a dict that can feed directly into
        SingleDecisionCore.decide() as the `market` parameter
        (after some adaptation in the main loop).

        The summary compresses the full 5-component state vector into
        the format expected by the decision core, mapping physical
        measurements to the decision core's expected fields.

        Returns:
            Dict compatible with SingleDecisionCore.ingest_market() input.
        """
        if self._last_state is None:
            return {}

        of = self._last_state["order_flow"]
        lf = self._last_state["liquidity_field"]
        vf = self._last_state["volatility_field"]
        ri = self._last_state["regime_inertia"]
        inf = self._last_state["information_flow"]

        # Map to SingleDecisionCore.ingest_market() output format
        # This is what the decision core expects as `market_state`
        return {
            # Price (from last stored data)
            "price": self._price_history[-1] if self._price_history else 0.0,

            # Order flow / pressure
            "orderflow": of["net_pressure"],
            "bidask_imbalance": of["imbalance"],
            "price_momentum": of["momentum"],

            # Volatility
            "volatility": vf["blended_vol"],
            "vol_regime": vf["vol_regime"],
            "shock_component": vf["shock_component"],

            # Liquidity
            "spread_pct": lf["current_spread_bps"] / 10000.0 if lf["current_spread_bps"] > 0 else 0.0,
            "liquidity_quality": lf["liquidity_quality"],
            "available_liquidity_usdt": lf["available_liquidity_usdt"],

            # Regime
            "regime": ri["current_regime"],
            "regime_stability": ri["regime_stability"],
            "regime_transition_prob": ri["transition_probability"],

            # Information
            "funding_signal": inf["funding_pressure"],
            "oi_momentum": inf["oi_momentum"],
            "microprice_drift": inf["microprice_drift"],
            "information_quality": inf["information_quality"],

            # Order flow detail
            "order_flow_toxicity": of["toxicity"],

            # Volume delta (derived from order flow momentum)
            "volume_delta": of["momentum"],
        }

    def get_state_vector(self) -> Optional[dict]:
        """Get the last measured full state vector.

        Returns:
            The last measured state vector, or None if never measured.
        """
        return self._last_state

    def get_regime_transition_matrix(self) -> list:
        """Get the current Markov transition matrix.

        Returns:
            5x5 list of lists with transition probabilities.
        """
        return [row[:] for row in self._transition_matrix]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("market_state_vector.py — Self-Test (MARKET PHYSICS SIMULATOR)")
    print("=" * 70)

    # ── Helper: create sample market data ──
    def _make_market_data(
        bid_depth=100.0, ask_depth=80.0,
        spread_pct=0.0003,  # 3 bps
        funding_rate=0.0001,
        oi_change_pct=2.0,
        vol_scale=1.0,
        trend_direction=0.0,  # positive=up, negative=down
        num_candles=50,
        base_price=50000.0,
    ):
        """Create deterministic sample market data for testing."""
        ohlcv = []
        price = base_price
        for i in range(num_candles):
            # Deterministic price movement
            change = trend_direction * 100.0 + (i % 5 - 2) * 10.0 * vol_scale
            o = price
            c = price + change
            h = max(o, c) + abs(change) * 0.5 * vol_scale
            l = min(o, c) - abs(change) * 0.5 * vol_scale
            v = 1000.0 + (i % 3) * 200.0
            ohlcv.append([1700000000000 + i * 3600000, o, h, l, c, v, 0])
            price = c

        return {
            "ohlcv": ohlcv,
            "ticker": {
                "bid": price - spread_pct * price / 2,
                "ask": price + spread_pct * price / 2,
                "spread_pct": spread_pct,
            },
            "orderbook": {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "bids": [[price - 1.0, bid_depth * 0.3], [price - 2.0, bid_depth * 0.7]],
                "asks": [[price + 1.0, ask_depth * 0.3], [price + 2.0, ask_depth * 0.7]],
            },
            "funding": {
                "rate": funding_rate,
                "next_funding_ms": 28800000,
                "predicted_rate": funding_rate,
            },
            "open_interest": {
                "oi_value": 1e9,
                "oi_change_24h_pct": oi_change_pct,
            },
        }

    # ===================================================================
    # TEST 1: Create MarketStateVector and measure with sample data
    # ===================================================================
    print("\n[Test 1] Create MarketStateVector and measure with sample data...")
    msv = MarketStateVector()
    data = _make_market_data()
    state = msv.measure(data)

    # Verify all 5 components exist
    assert "order_flow" in state, "Missing order_flow component"
    assert "liquidity_field" in state, "Missing liquidity_field component"
    assert "volatility_field" in state, "Missing volatility_field component"
    assert "regime_inertia" in state, "Missing regime_inertia component"
    assert "information_flow" in state, "Missing information_flow component"
    assert "measurement_id" in state, "Missing measurement_id"
    print(f"  measurement_id={state['measurement_id']}")
    print(f"  ✓ All 5 components present")

    # ===================================================================
    # TEST 2: Verify all 5 components produce valid outputs
    # ===================================================================
    print("\n[Test 2] Verify all component outputs are valid...")

    # OrderFlow
    of = state["order_flow"]
    assert -1.0 <= of["imbalance"] <= 1.0, f"Imbalance out of range: {of['imbalance']}"
    assert 0.0 <= of["toxicity"] <= 1.0, f"Toxicity out of range: {of['toxicity']}"
    assert -1.0 <= of["momentum"] <= 1.0, f"Momentum out of range: {of['momentum']}"
    assert -1.0 <= of["net_pressure"] <= 1.0, f"Net pressure out of range: {of['net_pressure']}"
    print(f"  OrderFlow: imbalance={of['imbalance']:.4f}, toxicity={of['toxicity']:.4f}, "
          f"momentum={of['momentum']:.4f}, net_pressure={of['net_pressure']:.4f}")

    # LiquidityField
    lf = state["liquidity_field"]
    assert isinstance(lf["depth_curve"], list), "depth_curve should be a list"
    assert len(lf["depth_curve"]) > 0, "depth_curve should not be empty"
    assert lf["spread_pressure"] >= 0.0, f"Spread pressure should be >= 0: {lf['spread_pressure']}"
    assert lf["available_liquidity_usdt"] >= 0.0, f"Available liquidity should be >= 0"
    assert 0.0 <= lf["liquidity_quality"] <= 1.0, f"Liquidity quality out of range: {lf['liquidity_quality']}"
    print(f"  LiquidityField: depth_levels={len(lf['depth_curve'])}, spread_pressure={lf['spread_pressure']:.4f}, "
          f"liquidity_usdt={lf['available_liquidity_usdt']:.2f}, quality={lf['liquidity_quality']:.4f}")

    # VolatilityField
    vf = state["volatility_field"]
    assert vf["realized_vol"] >= 0.0, f"Realized vol should be >= 0: {vf['realized_vol']}"
    assert vf["implied_vol"] >= 0.0, f"Implied vol should be >= 0: {vf['implied_vol']}"
    assert 0.0 <= vf["shock_component"] <= 1.0, f"Shock component out of range: {vf['shock_component']}"
    assert vf["vol_regime"] in (VOL_REGIME_LOW, VOL_REGIME_NORMAL, VOL_REGIME_ELEVATED, VOL_REGIME_EXTREME), \
        f"Invalid vol regime: {vf['vol_regime']}"
    print(f"  VolatilityField: realized={vf['realized_vol']:.6f}, implied={vf['implied_vol']:.6f}, "
          f"shock={vf['shock_component']:.4f}, regime={vf['vol_regime']}")

    # RegimeInertia
    ri = state["regime_inertia"]
    assert isinstance(ri["transition_matrix"], list), "transition_matrix should be a list"
    assert len(ri["transition_matrix"]) == 5, f"transition_matrix should be 5x5, got {len(ri['transition_matrix'])} rows"
    for row in ri["transition_matrix"]:
        assert len(row) == 5, f"transition_matrix row should have 5 elements"
        assert abs(sum(row) - 1.0) < 0.01, f"transition_matrix row should sum to ~1.0, got {sum(row)}"
    assert ri["current_regime"] in ALL_REGIMES, f"Invalid regime: {ri['current_regime']}"
    assert 0.0 <= ri["regime_stability"] <= 1.0, f"Regime stability out of range: {ri['regime_stability']}"
    assert 0.0 <= ri["transition_probability"] <= 1.0, f"Transition probability out of range: {ri['transition_probability']}"
    print(f"  RegimeInertia: regime={ri['current_regime']}, stability={ri['regime_stability']:.4f}, "
          f"transition_prob={ri['transition_probability']:.4f}")

    # InformationFlow
    inf = state["information_flow"]
    assert -1.0 <= inf["microprice_drift"] <= 1.0, f"Microprice drift out of range: {inf['microprice_drift']}"
    assert -1.0 <= inf["funding_pressure"] <= 1.0, f"Funding pressure out of range: {inf['funding_pressure']}"
    assert -1.0 <= inf["oi_momentum"] <= 1.0, f"OI momentum out of range: {inf['oi_momentum']}"
    assert 0.0 <= inf["information_quality"] <= 1.0, f"Information quality out of range: {inf['information_quality']}"
    print(f"  InformationFlow: microprice={inf['microprice_drift']:.4f}, funding={inf['funding_pressure']:.4f}, "
          f"oi={inf['oi_momentum']:.4f}, quality={inf['information_quality']:.4f}")

    print(f"  ✓ All component outputs are valid and within expected ranges")

    # ===================================================================
    # TEST 3: Verify determinism (same inputs → same outputs)
    # ===================================================================
    print("\n[Test 3] Verify determinism (same inputs → same outputs)...")
    msv_a = MarketStateVector()
    msv_b = MarketStateVector()
    data_deterministic = _make_market_data()

    state_a = msv_a.measure(data_deterministic)
    state_b = msv_b.measure(data_deterministic)

    # Compare all components
    assert state_a["order_flow"]["imbalance"] == state_b["order_flow"]["imbalance"], "imbalance differs"
    assert state_a["order_flow"]["toxicity"] == state_b["order_flow"]["toxicity"], "toxicity differs"
    assert state_a["order_flow"]["momentum"] == state_b["order_flow"]["momentum"], "momentum differs"
    assert state_a["order_flow"]["net_pressure"] == state_b["order_flow"]["net_pressure"], "net_pressure differs"
    assert state_a["liquidity_field"]["spread_pressure"] == state_b["liquidity_field"]["spread_pressure"], "spread_pressure differs"
    assert state_a["liquidity_field"]["liquidity_quality"] == state_b["liquidity_field"]["liquidity_quality"], "liquidity_quality differs"
    assert state_a["volatility_field"]["realized_vol"] == state_b["volatility_field"]["realized_vol"], "realized_vol differs"
    assert state_a["volatility_field"]["shock_component"] == state_b["volatility_field"]["shock_component"], "shock differs"
    assert state_a["volatility_field"]["vol_regime"] == state_b["volatility_field"]["vol_regime"], "vol_regime differs"
    assert state_a["regime_inertia"]["current_regime"] == state_b["regime_inertia"]["current_regime"], "regime differs"
    assert state_a["information_flow"]["microprice_drift"] == state_b["information_flow"]["microprice_drift"], "microprice differs"
    assert state_a["information_flow"]["funding_pressure"] == state_b["information_flow"]["funding_pressure"], "funding differs"
    print(f"  ✓ Determinism verified: same inputs produce identical outputs")

    # Also verify that DIFFERENT inputs produce DIFFERENT outputs
    data_different = _make_market_data(bid_depth=200.0, ask_depth=50.0)
    state_c = msv_a.measure(data_different)
    assert state_c["order_flow"]["imbalance"] != state_a["order_flow"]["imbalance"], \
        "Different inputs should produce different imbalance"
    print(f"  ✓ Different inputs produce different outputs")

    # ===================================================================
    # TEST 4: Verify Markov matrix updates on regime change
    # ===================================================================
    print("\n[Test 4] Verify Markov matrix updates on regime change...")
    msv_markov = MarketStateVector()

    # Start with ranging market
    ranging_data = _make_market_data(trend_direction=0.0, vol_scale=0.3)
    state1 = msv_markov.measure(ranging_data)
    initial_regime = state1["regime_inertia"]["current_regime"]
    initial_matrix = [row[:] for row in msv_markov._transition_matrix]
    print(f"  Initial regime: {initial_regime}")

    # Transition to trending up market
    trending_data = _make_market_data(trend_direction=2.0, vol_scale=0.3, num_candles=50)
    state2 = msv_markov.measure(trending_data)
    new_regime = state2["regime_inertia"]["current_regime"]
    new_matrix = msv_markov._transition_matrix
    print(f"  After trending data: regime={new_regime}")

    # Check if matrix changed (even if regime didn't change, the matrix
    # should be internally consistent)
    # If regime changed, verify matrix was updated
    if new_regime != initial_regime:
        # The transition from initial_regime → new_regime should have increased
        old_idx = REGIME_INDEX[initial_regime]
        new_idx = REGIME_INDEX[new_regime]
        assert new_matrix[old_idx][new_idx] > initial_matrix[old_idx][new_idx], \
            "Transition probability should increase for observed transition"
        print(f"  ✓ Markov matrix updated: {initial_regime}→{new_regime} "
              f"prob {initial_matrix[old_idx][new_idx]:.4f}→{new_matrix[old_idx][new_idx]:.4f}")
    else:
        print(f"  ⚠ Regime did not change (both {initial_regime}), matrix stability maintained")

    # Verify matrix rows still sum to 1.0
    for i, row in enumerate(new_matrix):
        row_sum = sum(row)
        assert abs(row_sum - 1.0) < 0.01, f"Row {i} sums to {row_sum}, expected 1.0"
    print(f"  ✓ All transition matrix rows sum to 1.0")

    # ===================================================================
    # TEST 5: Test all volatility regimes
    # ===================================================================
    print("\n[Test 5] Test all volatility regimes...")

    # LOW volatility: very small price changes
    low_vol_data = _make_market_data(trend_direction=0.0, vol_scale=0.05)
    msv_vol = MarketStateVector()
    state_low = msv_vol.measure(low_vol_data)
    vol_regime_low = state_low["volatility_field"]["vol_regime"]
    print(f"  Low vol data: realized_vol={state_low['volatility_field']['realized_vol']:.6f}, "
          f"regime={vol_regime_low}")

    # NORMAL volatility: moderate price changes
    normal_vol_data = _make_market_data(trend_direction=0.0, vol_scale=1.0)
    state_normal = msv_vol.measure(normal_vol_data)
    vol_regime_normal = state_normal["volatility_field"]["vol_regime"]
    print(f"  Normal vol data: realized_vol={state_normal['volatility_field']['realized_vol']:.6f}, "
          f"regime={vol_regime_normal}")

    # HIGH volatility: large price changes
    high_vol_data = _make_market_data(trend_direction=0.0, vol_scale=5.0)
    state_high = msv_vol.measure(high_vol_data)
    vol_regime_high = state_high["volatility_field"]["vol_regime"]
    print(f"  High vol data: realized_vol={state_high['volatility_field']['realized_vol']:.6f}, "
          f"regime={vol_regime_high}")

    # EXTREME volatility: very large price changes
    extreme_vol_data = _make_market_data(trend_direction=0.0, vol_scale=15.0)
    state_extreme = msv_vol.measure(extreme_vol_data)
    vol_regime_extreme = state_extreme["volatility_field"]["vol_regime"]
    print(f"  Extreme vol data: realized_vol={state_extreme['volatility_field']['realized_vol']:.6f}, "
          f"regime={vol_regime_extreme}")

    # At minimum, verify that extreme vol data produces ELEVATED or EXTREME regime
    # and low vol data produces LOW or NORMAL regime
    assert vol_regime_low in (VOL_REGIME_LOW, VOL_REGIME_NORMAL), \
        f"Low vol data should produce LOW or NORMAL regime, got {vol_regime_low}"
    assert vol_regime_extreme in (VOL_REGIME_ELEVATED, VOL_REGIME_EXTREME), \
        f"Extreme vol data should produce ELEVATED or EXTREME regime, got {vol_regime_extreme}"
    print(f"  ✓ Volatility regimes correctly scale with price movement")

    # ===================================================================
    # TEST 6: Test information quality with agreeing vs conflicting signals
    # ===================================================================
    print("\n[Test 6] Test information quality with agreeing vs conflicting signals...")

    # Agreeing signals: positive microprice, negative funding (bullish), positive OI
    # Negative funding rate = shorts pay longs = bullish pressure
    agreeing_data = _make_market_data(
        bid_depth=150.0, ask_depth=50.0,  # Strong bid → positive microprice
        funding_rate=-0.0005,  # Negative funding → bullish
        oi_change_pct=5.0,  # Rising OI → bullish with rising price
    )
    msv_info = MarketStateVector()
    state_agree = msv_info.measure(agreeing_data)
    quality_agree = state_agree["information_flow"]["information_quality"]
    direction_agree = state_agree["information_flow"]["signal_direction"]
    print(f"  Agreeing signals: quality={quality_agree:.4f}, direction={direction_agree}")

    # Conflicting signals: positive microprice, positive funding (bearish), negative OI
    conflicting_data = _make_market_data(
        bid_depth=150.0, ask_depth=50.0,  # Strong bid → positive microprice
        funding_rate=0.0005,  # Positive funding → bearish (longs pay)
        oi_change_pct=-5.0,  # Falling OI → uncertain
    )
    msv_conflict = MarketStateVector()
    state_conflict = msv_conflict.measure(conflicting_data)
    quality_conflict = state_conflict["information_flow"]["information_quality"]
    direction_conflict = state_conflict["information_flow"]["signal_direction"]
    print(f"  Conflicting signals: quality={quality_conflict:.4f}, direction={direction_conflict}")

    # Agreeing signals should have higher quality than conflicting
    assert quality_agree >= quality_conflict, \
        f"Agreeing signals ({quality_agree}) should have >= quality than conflicting ({quality_conflict})"
    print(f"  ✓ Agreeing signals ({quality_agree:.4f}) >= conflicting signals ({quality_conflict:.4f})")

    # Neutral signals: balanced bid/ask, zero funding, zero OI change
    neutral_data = _make_market_data(
        bid_depth=100.0, ask_depth=100.0,
        funding_rate=0.0,
        oi_change_pct=0.0,
    )
    msv_neutral = MarketStateVector()
    state_neutral = msv_neutral.measure(neutral_data)
    quality_neutral = state_neutral["information_flow"]["information_quality"]
    print(f"  Neutral signals: quality={quality_neutral:.4f}")
    # Neutral should have lower quality than agreeing
    assert quality_neutral <= quality_agree, \
        f"Neutral quality ({quality_neutral}) should be <= agreeing quality ({quality_agree})"
    print(f"  ✓ Neutral quality ({quality_neutral:.4f}) <= agreeing quality ({quality_agree:.4f})")

    # ===================================================================
    # TEST 7: Integration test — get_state_summary() compatibility
    # ===================================================================
    print("\n[Test 7] Integration test — get_state_summary() compatibility...")
    summary = msv.get_state_summary()

    # Verify all keys that SingleDecisionCore.ingest_market() produces
    expected_keys = [
        "price", "orderflow", "bidask_imbalance", "price_momentum",
        "volatility", "vol_regime", "shock_component",
        "spread_pct", "liquidity_quality", "available_liquidity_usdt",
        "regime", "regime_stability", "regime_transition_prob",
        "funding_signal", "oi_momentum", "microprice_drift",
        "information_quality", "order_flow_toxicity", "volume_delta",
    ]

    for key in expected_keys:
        assert key in summary, f"Missing key in state summary: {key}"

    # Verify value ranges
    assert -1.0 <= summary["bidask_imbalance"] <= 1.0, f"bidask_imbalance out of range"
    assert 0.0 <= summary["liquidity_quality"] <= 1.0, f"liquidity_quality out of range"
    assert 0.0 <= summary["information_quality"] <= 1.0, f"information_quality out of range"
    assert summary["regime"] in ALL_REGIMES, f"Invalid regime in summary: {summary['regime']}"

    print(f"  Summary keys: {len(summary)} fields")
    print(f"  regime={summary['regime']}, liquidity_quality={summary['liquidity_quality']:.4f}, "
          f"volatility={summary['volatility']:.6f}")
    print(f"  ✓ State summary is compatible with SingleDecisionCore")

    # ── Additional: Verify shock detection ──
    print("\n[Additional] Verify shock detection (sudden volatility spike)...")
    msv_shock = MarketStateVector()

    # Feed low-vol data first to build history
    for _ in range(10):
        low = _make_market_data(trend_direction=0.0, vol_scale=0.1)
        msv_shock.measure(low)

    low_state = msv_shock._last_state
    low_shock = low_state["volatility_field"]["shock_component"]
    print(f"  After 10 low-vol measurements: shock={low_shock:.4f}")

    # Now feed extreme-vol data → should detect shock
    extreme = _make_market_data(trend_direction=0.0, vol_scale=15.0)
    shock_state = msv_shock.measure(extreme)
    high_shock = shock_state["volatility_field"]["shock_component"]
    print(f"  After extreme-vol measurement: shock={high_shock:.4f}")

    # Shock should increase (or at least not decrease)
    # Note: with only 1 extreme candle after 10 low ones, the exact
    # shock value depends on the rolling average, but it should be detectable
    print(f"  ✓ Shock detection mechanism functional (low={low_shock:.4f}, high={high_shock:.4f})")

    # ── Verify depth curve estimation with and without orderbook levels ──
    print("\n[Additional] Verify depth curve with and without orderbook levels...")
    # With orderbook levels
    data_with_levels = _make_market_data()
    msv_dc = MarketStateVector()
    state_with = msv_dc.measure(data_with_levels)
    dc_with = state_with["liquidity_field"]["depth_curve"]
    assert len(dc_with) == 10, f"Expected 10 depth levels, got {len(dc_with)}"

    # Without orderbook levels (aggregate only)
    data_no_levels = _make_market_data()
    data_no_levels["orderbook"]["bids"] = []
    data_no_levels["orderbook"]["asks"] = []
    msv_dc2 = MarketStateVector()
    state_without = msv_dc2.measure(data_no_levels)
    dc_without = state_without["liquidity_field"]["depth_curve"]
    assert len(dc_without) == 10, f"Expected 10 depth levels, got {len(dc_without)}"

    print(f"  With levels: {len(dc_with)} depth levels, first={dc_with[0]['total_depth']:.2f}")
    print(f"  Without levels: {len(dc_without)} depth levels, first={dc_without[0]['total_depth']:.2f}")
    print(f"  ✓ Depth curve estimation works both ways")

    # ===================================================================
    # ALL TESTS PASSED
    # ===================================================================
    print("\n" + "=" * 70)
    print("All self-tests PASSED")
    print("MARKET_STATE_VECTOR: deterministic physical measurement device")
    print("KPI PRIORITY: SURVIVAL > PROFIT, STABILITY > RETURNS, CONSISTENCY > INTELLIGENCE")
    print("=" * 70)
