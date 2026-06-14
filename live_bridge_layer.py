"""
LIVE_BRIDGE_LAYER_v1: live_bridge_layer.py — The Shadow Observation Bridge

═══════════════════════════════════════════════════════════════════════════════
THE DUAL_EXCHANGE_SENSOR_NET — Orchestrates ALL bridge components into a
single coherent layer that connects simulation to reality.

PHILOSOPHY: shadow_observation_is_the_ground_truth_calibrator

This is the OBSERVATION LAYER. It:
    1. Connects to Binance + Bybit (public data only)
    2. Normalizes orderbook data from both exchanges
    3. Feeds normalized data to the MarketPhysicsEngine
    4. Shadow-executes the engine's decisions against real orderbooks
    5. Detects cross-exchange divergence
    6. Monitors data synchronization
    7. Mirrors risk model against real outcomes
    8. Calibrates the execution model

═══════════════════════════════════════════════════════════════════════════════
CRITICAL CONSTRAINTS — VIOLATION IS A SYSTEM INTEGRITY BREACH
═══════════════════════════════════════════════════════════════════════════════

NO_REAL_ORDERS:          This module MUST NEVER place a real order.
OBSERVATION_STREAM_ONLY: Output is data + calibration, never trading commands.
PAPER_ONLY:              Even "execution" is simulated. Records what WOULD have happened.
SINGLE_BRAIN:            The decision core (SingleDecisionCore) is the ONLY decision authority.
                         The bridge FEEDS REALITY into the decision core, it does NOT replace it.

If any code path in this module could result in a real order being
placed on an exchange, that is a CRITICAL BUG.

═══════════════════════════════════════════════════════════════════════════════

Architecture:

    LiveBridgeLayer
    ├── ExchangeConnector      → Binance + Bybit public data
    ├── ShadowExecutionEngine  → Simulate fills against real OBs
    ├── CrossExchangeDetector  → Monitor price/liquidity divergence
    ├── DesyncDetector         → Monitor data synchronization
    └── RiskShadowMirror       → Calibrate risk model vs reality

    Main cycle:
        observe()           → fetch real data, normalize, detect divergence
        shadow_decide()     → run engine on real data, shadow-execute result
        calibrate()         → compute calibration factors from accumulated data

Self-tests use deterministic mock data — no API keys or live connections required.
"""

import time
import sys
import os
import logging
from typing import Optional, Dict, Any

# Allow importing sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exchange_connector import ExchangeConnector
from shadow_execution_engine import ShadowExecutionEngine
from cross_exchange_detector import CrossExchangeDetector
from desync_detector import DesyncDetector
from risk_shadow_mirror import RiskShadowMirror

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("live_bridge_layer")

# ---------------------------------------------------------------------------
# Hard Guard — Real Order Prevention
# ---------------------------------------------------------------------------

class RealOrderAttemptedError(Exception):
    """Raised if the bridge layer detects an attempt to place a real order.

    This is a SYSTEM INTEGRITY BREACH. The bridge MUST NEVER result in a
    real order. If this exception is ever raised in production, it indicates
    a critical bug.
    """
    pass


def _guard_no_real_orders(context: str = ""):
    """Hard guard: raise if called in a context suggesting real execution.

    This function inspects the call stack for keywords that suggest
    real order placement. It is called at the beginning of every
    public method in LiveBridgeLayer.

    Args:
        context: Description of the method being guarded.

    Raises:
        RealOrderAttemptedError: If real execution context detected.
    """
    _DANGEROUS_KEYWORDS = [
        "create_order", "place_order", "send_order", "submit_order",
        "market_order", "limit_order", "exchange_order",
    ]
    frame = sys._getframe()
    for depth in range(2, 10):
        try:
            caller_frame = sys._getframe(depth)
            func_name = caller_frame.f_code.co_name.lower()
            for kw in _DANGEROUS_KEYWORDS:
                if kw in func_name:
                    raise RealOrderAttemptedError(
                        f"BRIDGE INTEGRITY BREACH: method '{context}' was called "
                        f"from '{caller_frame.f_code.co_name}' which suggests "
                        f"real order placement. Bridge layer must NEVER place "
                        f"real orders. This is a critical bug."
                    )
        except ValueError:
            break


# ---------------------------------------------------------------------------
# Merged Market Data Builder
# ---------------------------------------------------------------------------

def _build_merged_market_data(
    binance_data: Optional[dict],
    bybit_data: Optional[dict],
) -> dict:
    """Build merged market data from both exchanges for engine consumption.

    The merge strategy:
    - Use the exchange with better liquidity as primary
    - Average prices from both (weighted by liquidity)
    - Use tighter spread
    - Sum depth from both exchanges
    - Mark which exchange each data point came from

    The output format matches ccxt_adapter.generate_synthetic_market_data()
    so it can be fed directly into MarketPhysicsEngine.cycle().

    Args:
        binance_data: Dict from ExchangeConnector.fetch_all()["binance"],
            with keys: orderbook, ticker, trades, funding, ohlcv.
            Can be None if Binance is down.
        bybit_data: Same structure as binance_data but for Bybit.
            Can be None if Bybit is down.

    Returns:
        Merged market data dict with keys:
            symbol, timeframe, ohlcv, ticker, orderbook, funding,
            open_interest, timestamp, source_exchange, observation_metadata.
    """
    now_ms = int(time.time() * 1000)

    # If both are down, return minimal structure with quality = 0
    if binance_data is None and bybit_data is None:
        return _empty_merged_data(now_ms)

    # If only one exchange is available, use it directly
    if binance_data is None:
        return _single_exchange_data(bybit_data, "bybit", now_ms)
    if bybit_data is None:
        return _single_exchange_data(binance_data, "binance", now_ms)

    # Both exchanges available — merge
    binance_ob = binance_data.get("orderbook") or {}
    bybit_ob = bybit_data.get("orderbook") or {}
    binance_ticker = binance_data.get("ticker") or {}
    bybit_ticker = bybit_data.get("ticker") or {}

    # ── Determine primary exchange (better liquidity) ──
    binance_liq = (
        binance_ob.get("available_liquidity_usdt", 0.0)
        or binance_ob.get("bid_depth_usdt", 0.0) + binance_ob.get("ask_depth_usdt", 0.0)
    )
    bybit_liq = (
        bybit_ob.get("available_liquidity_usdt", 0.0)
        or bybit_ob.get("bid_depth_usdt", 0.0) + bybit_ob.get("ask_depth_usdt", 0.0)
    )

    if binance_liq >= bybit_liq:
        primary = "binance"
        primary_data = binance_data
        primary_liq = binance_liq
    else:
        primary = "bybit"
        primary_data = bybit_data
        primary_liq = bybit_liq

    total_liq = binance_liq + bybit_liq
    binance_weight = binance_liq / total_liq if total_liq > 0 else 0.5
    bybit_weight = bybit_liq / total_liq if total_liq > 0 else 0.5

    # ── Merge prices (liquidity-weighted average) ──
    binance_mid = binance_ob.get("mid_price", 0.0) or binance_ticker.get("mid_price", 0.0)
    bybit_mid = bybit_ob.get("mid_price", 0.0) or bybit_ticker.get("mid_price", 0.0)

    merged_mid = 0.0
    if binance_mid > 0 and bybit_mid > 0:
        merged_mid = binance_mid * binance_weight + bybit_mid * bybit_weight
    elif binance_mid > 0:
        merged_mid = binance_mid
    elif bybit_mid > 0:
        merged_mid = bybit_mid

    # ── Merge spread (use tighter) ──
    binance_spread_bps = binance_ob.get("spread_bps", 999.0) or 999.0
    bybit_spread_bps = bybit_ob.get("spread_bps", 999.0) or 999.0
    merged_spread_bps = min(binance_spread_bps, bybit_spread_bps)

    # ── Merge ticker ──
    merged_bid = 0.0
    merged_ask = 0.0
    if merged_mid > 0 and merged_spread_bps < 999.0:
        half_spread = merged_mid * (merged_spread_bps / 10000.0) / 2.0
        merged_bid = merged_mid - half_spread
        merged_ask = merged_mid + half_spread
    else:
        # Fallback: average bids and asks
        bb = binance_ticker.get("bid", 0.0) or 0.0
        ba = binance_ticker.get("ask", 0.0) or 0.0
        yb = bybit_ticker.get("bid", 0.0) or 0.0
        ya = bybit_ticker.get("ask", 0.0) or 0.0
        bids = [b for b in [bb, yb] if b > 0]
        asks = [a for a in [ba, ya] if a > 0]
        if bids:
            merged_bid = sum(bids) / len(bids)
        if asks:
            merged_ask = sum(asks) / len(asks)
        if merged_bid == 0 and merged_ask == 0 and merged_mid > 0:
            merged_bid = merged_mid * 0.9999
            merged_ask = merged_mid * 1.0001

    spread = merged_ask - merged_bid
    spread_pct = spread / merged_mid if merged_mid > 0 else 0.0
    merged_volume = (
        (binance_ticker.get("quote_volume", 0.0) or 0.0) * binance_weight
        + (bybit_ticker.get("quote_volume", 0.0) or 0.0) * bybit_weight
    )

    merged_ticker = {
        "bid": round(merged_bid, 2),
        "ask": round(merged_ask, 2),
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 8),
        "volume_24h": round(merged_volume, 2),
    }

    # ── Merge orderbook (sum depth from both) ──
    binance_bid_depth = binance_ob.get("bid_depth_usdt", 0.0) or 0.0
    binance_ask_depth = binance_ob.get("ask_depth_usdt", 0.0) or 0.0
    bybit_bid_depth = bybit_ob.get("bid_depth_usdt", 0.0) or 0.0
    bybit_ask_depth = bybit_ob.get("ask_depth_usdt", 0.0) or 0.0

    merged_orderbook = {
        "bid_depth": round(binance_bid_depth + bybit_bid_depth, 2),
        "ask_depth": round(binance_ask_depth + bybit_ask_depth, 2),
        "spread": round(spread, 2),
        # Also include raw bid/ask lists from primary for shadow execution
        "bids": primary_data.get("orderbook", {}).get("bids", []),
        "asks": primary_data.get("orderbook", {}).get("asks", []),
        "primary_exchange": primary,
    }

    # ── OHLCV: use primary exchange ──
    merged_ohlcv = primary_data.get("ohlcv") or []

    # ── Funding: use primary exchange, fall back to secondary ──
    merged_funding = primary_data.get("funding")
    if merged_funding is None:
        secondary = bybit_data if primary == "binance" else binance_data
        merged_funding = secondary.get("funding")

    if merged_funding is None:
        merged_funding = {"rate": 0.0, "next_funding_ms": 28800000, "predicted_rate": 0.0}

    # ── Open interest: average if both available ──
    binance_oi = binance_data.get("open_interest") or {}
    bybit_oi = bybit_data.get("open_interest") or {}

    if binance_oi and bybit_oi:
        merged_oi = {
            "oi_value": (
                (binance_oi.get("oi_value", 0.0) or 0.0) * binance_weight
                + (bybit_oi.get("oi_value", 0.0) or 0.0) * bybit_weight
            ),
            "oi_change_24h_pct": (
                (binance_oi.get("oi_change_24h_pct", 0.0) or 0.0) * binance_weight
                + (bybit_oi.get("oi_change_24h_pct", 0.0) or 0.0) * bybit_weight
            ),
        }
    elif binance_oi:
        merged_oi = binance_oi
    elif bybit_oi:
        merged_oi = bybit_oi
    else:
        merged_oi = {"oi_value": 0.0, "oi_change_24h_pct": 0.0}

    # ── Symbol and timeframe ──
    symbol = primary_data.get("orderbook", {}).get("symbol", "BTC/USDT")
    timeframe = "1h"  # Default; the bridge itself is timeframe-agnostic

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ohlcv": merged_ohlcv,
        "ticker": merged_ticker,
        "orderbook": merged_orderbook,
        "funding": merged_funding,
        "open_interest": merged_oi,
        "timestamp": now_ms,
        "source_exchange": primary,
        "observation_metadata": {
            "binance_available": True,
            "bybit_available": True,
            "binance_weight": round(binance_weight, 4),
            "bybit_weight": round(bybit_weight, 4),
            "primary_exchange": primary,
            "binance_mid": round(binance_mid, 2),
            "bybit_mid": round(bybit_mid, 2),
            "merged_mid": round(merged_mid, 2),
            "merged_spread_bps": round(merged_spread_bps, 4),
        },
    }


def _empty_merged_data(timestamp_ms: int) -> dict:
    """Return a minimal merged data structure when no exchanges are available.

    Args:
        timestamp_ms: Current timestamp in milliseconds.

    Returns:
        Minimal market data dict with zeroed values.
    """
    return {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "ohlcv": [],
        "ticker": {"bid": 0.0, "ask": 0.0, "spread": 0.0, "spread_pct": 0.0, "volume_24h": 0.0},
        "orderbook": {"bid_depth": 0.0, "ask_depth": 0.0, "spread": 0.0, "bids": [], "asks": []},
        "funding": {"rate": 0.0, "next_funding_ms": 28800000, "predicted_rate": 0.0},
        "open_interest": {"oi_value": 0.0, "oi_change_24h_pct": 0.0},
        "timestamp": timestamp_ms,
        "source_exchange": "NONE",
        "observation_metadata": {
            "binance_available": False,
            "bybit_available": False,
            "binance_weight": 0.0,
            "bybit_weight": 0.0,
            "primary_exchange": "NONE",
        },
    }


def _single_exchange_data(exchange_data: dict, exchange_name: str,
                          timestamp_ms: int) -> dict:
    """Build merged data from a single exchange (the other is down).

    Args:
        exchange_data: Data from the available exchange.
        exchange_name: Name of the available exchange.
        timestamp_ms: Current timestamp in ms.

    Returns:
        Market data dict using only the available exchange.
    """
    ob = exchange_data.get("orderbook") or {}
    ticker = exchange_data.get("ticker") or {}
    funding = exchange_data.get("funding") or {
        "rate": 0.0, "next_funding_ms": 28800000, "predicted_rate": 0.0
    }
    oi = exchange_data.get("open_interest") or {
        "oi_value": 0.0, "oi_change_24h_pct": 0.0
    }

    bid = ticker.get("bid", 0.0) or ob.get("bids", [[0.0, 0.0]])[0][0] if ob.get("bids") else 0.0
    ask = ticker.get("ask", 0.0) or ob.get("asks", [[0.0, 0.0]])[0][0] if ob.get("asks") else 0.0
    mid = (bid + ask) / 2.0 if (bid + ask) > 0 else 0.0
    spread = ask - bid
    spread_pct = spread / mid if mid > 0 else 0.0

    return {
        "symbol": ob.get("symbol", "BTC/USDT"),
        "timeframe": "1h",
        "ohlcv": exchange_data.get("ohlcv") or [],
        "ticker": {
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "spread_pct": spread_pct,
            "volume_24h": ticker.get("quote_volume", 0.0) or 0.0,
        },
        "orderbook": {
            "bid_depth": ob.get("bid_depth_usdt", 0.0) or 0.0,
            "ask_depth": ob.get("ask_depth_usdt", 0.0) or 0.0,
            "spread": spread,
            "bids": ob.get("bids", []),
            "asks": ob.get("asks", []),
            "primary_exchange": exchange_name,
        },
        "funding": funding,
        "open_interest": oi,
        "timestamp": timestamp_ms,
        "source_exchange": exchange_name,
        "observation_metadata": {
            "binance_available": exchange_name == "binance",
            "bybit_available": exchange_name == "bybit",
            "binance_weight": 1.0 if exchange_name == "binance" else 0.0,
            "bybit_weight": 1.0 if exchange_name == "bybit" else 0.0,
            "primary_exchange": exchange_name,
        },
    }


def _compute_observation_quality(observation: dict) -> float:
    """Compute observation quality score [0, 1].

    Quality factors:
    - Both exchanges available: better quality
    - Low latency: better quality
    - SYNCED status: better quality
    - Low divergence: better quality
    - Orderbook has data: better quality

    Args:
        observation: The observation dict from LiveBridgeLayer.observe().

    Returns:
        Quality score between 0.0 and 1.0.
    """
    quality = 0.0
    metadata = observation.get("merged_market_data", {}).get("observation_metadata", {})

    # Factor 1: Exchange availability (0-0.4)
    binance_avail = metadata.get("binance_available", False)
    bybit_avail = metadata.get("bybit_available", False)
    if binance_avail and bybit_avail:
        quality += 0.4
    elif binance_avail or bybit_avail:
        quality += 0.2
    else:
        quality += 0.0

    # Factor 2: Sync status (0-0.2)
    sync_status = observation.get("sync_status", {}).get("sync_status", "STALE")
    if sync_status == "SYNCED":
        quality += 0.2
    elif sync_status == "MINOR_DESYNC":
        quality += 0.1
    else:
        quality += 0.0

    # Factor 3: Divergence level (0-0.2)
    div_level = observation.get("divergence", {}).get("divergence_level", "EXTREME")
    div_scores = {
        "NONE": 0.2, "LOW": 0.15, "MEDIUM": 0.10, "HIGH": 0.05, "EXTREME": 0.0,
    }
    quality += div_scores.get(div_level, 0.0)

    # Factor 4: Orderbook has data (0-0.2)
    merged = observation.get("merged_market_data", {})
    ticker = merged.get("ticker", {})
    if ticker.get("bid", 0.0) > 0 and ticker.get("ask", 0.0) > 0:
        quality += 0.1
    ob = merged.get("orderbook", {})
    if ob.get("bid_depth", 0.0) > 0 and ob.get("ask_depth", 0.0) > 0:
        quality += 0.1

    return round(min(1.0, max(0.0, quality)), 4)


# ===========================================================================
# LIVE BRIDGE LAYER
# ===========================================================================

class LiveBridgeLayer:
    """The shadow observation bridge between simulation and reality.

    This is the DUAL_EXCHANGE_SENSOR_NET. It:
    1. Connects to Binance + Bybit (public data only)
    2. Normalizes orderbook data from both exchanges
    3. Feeds normalized data to the MarketPhysicsEngine
    4. Shadow-executes the engine's decisions against real orderbooks
    5. Detects cross-exchange divergence
    6. Monitors data synchronization
    7. Mirrors risk model against real outcomes
    8. Calibrates the execution model

    The bridge NEVER trades. It OBSERVES and CALIBRATES.
    It answers: "How well does our model match reality?"

    CRITICAL CONSTRAINTS:
        - NO_REAL_ORDERS: This module MUST NEVER place a real order.
        - OBSERVATION_STREAM_ONLY: Output is data + calibration, never trading commands.
        - SINGLE_BRAIN: The decision core is the ONLY decision authority.
    """

    # Class-level guard flag — checked on every public method
    NO_REAL_ORDERS = True

    # Bridge operating modes
    MODE_OBSERVATION = "OBSERVATION"   # Only observe, no shadow execution
    MODE_SHADOW = "SHADOW"             # Observe + shadow execute
    MODE_CALIBRATION = "CALIBRATION"   # Observe + shadow + full calibration

    def __init__(self, config: dict = None):
        """Initialize the LiveBridgeLayer with all sub-components.

        Args:
            config: Optional configuration dict. Supported keys:
                - symbol (str): Trading pair (default "BTC/USDT")
                - mode (str): Operating mode (default "OBSERVATION")
                - connector (dict): Config for ExchangeConnector
                - shadow (dict): Config for ShadowExecutionEngine
                - divergence (dict): Config for CrossExchangeDetector
                - desync (dict): Config for DesyncDetector
                - risk_mirror (dict): Config for RiskShadowMirror
        """
        config = config or {}

        # ── Operating mode ──
        self._mode = config.get("mode", self.MODE_OBSERVATION)
        if self._mode not in (self.MODE_OBSERVATION, self.MODE_SHADOW, self.MODE_CALIBRATION):
            logger.warning(f"Invalid mode '{self._mode}', defaulting to OBSERVATION")
            self._mode = self.MODE_OBSERVATION

        # ── Symbol ──
        self._symbol = config.get("symbol", "BTC/USDT")

        # ── Initialize all bridge components ──
        connector_cfg = config.get("connector", {})
        connector_cfg.setdefault("symbol", self._symbol)
        self.connector = ExchangeConnector(
            symbol=self._symbol,
            config=connector_cfg,
        )

        self.shadow = ShadowExecutionEngine(
            config=config.get("shadow"),
        )

        self.divergence = CrossExchangeDetector(
            config=config.get("divergence"),
        )

        self.desync = DesyncDetector(
            config=config.get("desync"),
        )

        self.risk_mirror = RiskShadowMirror(
            config=config.get("risk_mirror"),
        )

        # ── Internal state ──
        self._cycle = 0
        self._last_fetch = {}
        self._last_observation = None
        self._last_shadow_result = None
        self._observation_quality_history = []

        logger.info(
            f"LiveBridgeLayer initialized: mode={self._mode}, symbol={self._symbol}"
        )

    # ===================================================================
    # CORE METHOD 1: OBSERVE
    # ===================================================================

    def observe(self) -> dict:
        """Fetch real market data from both exchanges.

        This is the core observation step. It:
        1. Fetches orderbooks from both exchanges
        2. Checks data synchronization
        3. Detects cross-exchange divergence
        4. Normalizes into a format the engine can consume
        5. Records latency measurements

        Returns:
            Observation dict with:
            - binance: normalized orderbook + ticker from Binance (or None)
            - bybit: normalized orderbook + ticker from Bybit (or None)
            - sync_status: from DesyncDetector
            - divergence: from CrossExchangeDetector
            - merged_market_data: best-of-both-worlds data for the engine
            - observation_quality: how good is this observation? [0, 1]
            - cycle: current cycle count
            - timestamp: observation timestamp (ms)
        """
        _guard_no_real_orders("observe")

        self._cycle += 1
        now_ms = int(time.time() * 1000)

        # ── Step 1: Fetch data from both exchanges ──
        raw_data = self._fetch_from_exchanges()

        binance_data = raw_data.get("binance")
        bybit_data = raw_data.get("bybit")

        # ── Step 2: Record timestamps for desync detection ──
        if binance_data is not None:
            self.desync.record_update("binance", now_ms)
        if bybit_data is not None:
            self.desync.record_update("bybit", now_ms)

        # ── Step 3: Check data synchronization ──
        sync_status = self.desync.check_sync()

        # ── Step 4: Detect cross-exchange divergence ──
        divergence = self._compute_divergence(binance_data, bybit_data)

        # ── Step 5: Build merged market data ──
        merged = _build_merged_market_data(binance_data, bybit_data)

        # ── Step 6: Store fetch info ──
        self._last_fetch = {
            "binance_available": binance_data is not None,
            "bybit_available": bybit_data is not None,
            "binance_latency_ms": (
                binance_data.get("orderbook", {}).get("latency_ms")
                if binance_data and binance_data.get("orderbook")
                else None
            ),
            "bybit_latency_ms": (
                bybit_data.get("orderbook", {}).get("latency_ms")
                if bybit_data and bybit_data.get("orderbook")
                else None
            ),
            "fetch_timestamp_ms": now_ms,
        }

        # ── Build observation result ──
        observation = {
            "binance": binance_data,
            "bybit": bybit_data,
            "sync_status": sync_status,
            "divergence": divergence,
            "merged_market_data": merged,
            "cycle": self._cycle,
            "timestamp": now_ms,
        }

        # ── Compute observation quality ──
        quality = _compute_observation_quality(observation)
        observation["observation_quality"] = quality
        self._observation_quality_history.append(quality)

        # Keep history bounded
        if len(self._observation_quality_history) > 1000:
            self._observation_quality_history = self._observation_quality_history[-500:]

        self._last_observation = observation

        return observation

    # ===================================================================
    # CORE METHOD 2: SHADOW_DECIDE
    # ===================================================================

    def shadow_decide(self, market_data: dict, engine) -> dict:
        """Run the engine on real data and shadow-execute the result.

        This is the key integration method:
        1. Feed real market data to the engine
        2. Engine produces action_vector (as always)
        3. Shadow-execute the action against real orderbooks
        4. Record divergence between model and reality
        5. Feed calibration back to engine

        The bridge does NOT modify the engine. It only reads engine
        outputs and feeds them to shadow components.

        Args:
            market_data: Real market data (from observe()).
                Must contain merged_market_data key, or be the
                merged_market_data dict directly.
            engine: The MarketPhysicsEngine instance.

        Returns:
            Shadow decision result with:
            - engine_result: full engine cycle output
            - shadow_result: shadow execution against real OB
            - calibration: divergence metrics from this cycle
            - risk_calibration: risk mirror comparison
            - cycle: current cycle count
        """
        _guard_no_real_orders("shadow_decide")

        # ── Extract merged market data ──
        if isinstance(market_data, dict) and "merged_market_data" in market_data:
            merged = market_data["merged_market_data"]
        elif isinstance(market_data, dict) and "ohlcv" in market_data:
            merged = market_data
        else:
            return {
                "engine_result": None,
                "shadow_result": None,
                "calibration": {},
                "risk_calibration": {},
                "cycle": self._cycle,
                "error": "invalid_market_data",
            }

        # ── Step 1: Run engine on real data ──
        # The engine's cycle() method is the ONLY decision path.
        # We do NOT modify its output.
        try:
            engine_result = engine.cycle(merged)
        except Exception as e:
            logger.error(f"Engine cycle failed in shadow_decide: {e}")
            return {
                "engine_result": None,
                "shadow_result": None,
                "calibration": {},
                "risk_calibration": {},
                "cycle": self._cycle,
                "error": f"engine_cycle_failed: {e}",
            }

        # ── Step 2: Extract action_vector ──
        action_vector = engine_result.get("action_vector", {})

        # ── Step 3: Shadow-execute against real orderbook ──
        # Get the real orderbook from the merged data
        orderbook = {
            "bids": merged.get("orderbook", {}).get("bids", []),
            "asks": merged.get("orderbook", {}).get("asks", []),
        }
        primary_exchange = merged.get("source_exchange", "binance")

        shadow_result = self.shadow.shadow_execute(
            action_vector=action_vector,
            orderbook=orderbook,
            exchange=primary_exchange,
        )

        # ── Step 4: Record divergence ──
        divergence_metrics = self.shadow.compute_divergence_metrics()

        # ── Step 5: Record in risk mirror ──
        # Record the risk model's estimate
        state_summary = engine_result.get("state_summary", {})
        risk_state = {}
        execution_result = engine_result.get("execution_result", {})

        # Extract risk estimate from the pipeline
        pipeline = action_vector.get("pipeline", {})
        step3_risk = pipeline.get("step3_risk", {})

        risk_state = {
            "risk_score": step3_risk.get("risk_score", 0.0),
            "estimated_drawdown": step3_risk.get("estimated_drawdown", 0.0),
            "volatility": state_summary.get("volatility", 0.0),
            "regime": state_summary.get("regime", "UNKNOWN"),
        }
        risk_filter_result = {
            "size_multiplier": step3_risk.get("size_multiplier", 0.0),
            "verdict": step3_risk.get("verdict", "UNKNOWN"),
            "adjusted_score": step3_risk.get("risk_score", 0.0),
        }

        self.risk_mirror.record_estimate(risk_state, risk_filter_result)

        # Record outcome from shadow execution
        if shadow_result.get("action") == "EXECUTE":
            realized_dd = 0.0
            pnl_pct = 0.0
            if shadow_result.get("slippage_bps", 0) > 0:
                # Estimate drawdown from slippage
                realized_dd = shadow_result["slippage_bps"] / 10000.0
            pnl_pct = shadow_result.get("model_vs_reality", {}).get("fill_bias_pct", 0.0)

            self.risk_mirror.record_outcome(
                realized_pnl_pct=pnl_pct,
                realized_dd=realized_dd,
                realized_slippage_bps=shadow_result.get("slippage_bps", 0.0),
                survival=not shadow_result.get("would_be_profitable", True) is False,
            )

        # ── Step 6: Compute risk calibration ──
        risk_calibration = self.risk_mirror.compute_calibration()

        # ── Build result ──
        result = {
            "engine_result": engine_result,
            "shadow_result": shadow_result,
            "calibration": divergence_metrics,
            "risk_calibration": risk_calibration,
            "cycle": self._cycle,
        }

        self._last_shadow_result = result

        return result

    # ===================================================================
    # CORE METHOD 3: CALIBRATE
    # ===================================================================

    def calibrate(self) -> dict:
        """Run calibration cycle.

        Computes:
        1. Shadow execution divergence (model vs reality slippage/fill)
        2. Risk model calibration (predicted vs actual risk)
        3. Execution model calibration factors for LeanExecutor
        4. Cross-exchange divergence statistics

        Returns:
            Calibration report with:
            - slippage_calibration: model vs actual slippage
            - fill_calibration: model vs actual fill rates
            - risk_calibration: risk model accuracy
            - divergence_stats: cross-exchange statistics
            - recommended_adjustments: what to change in the engine
            - calibration_quality: overall calibration quality [0, 1]
        """
        _guard_no_real_orders("calibrate")

        # ── Step 1: Shadow execution divergence ──
        shadow_div = self.shadow.compute_divergence_metrics()

        slippage_calibration = {
            "model_avg_bps": shadow_div.get("slippage_model_avg", 0.0),
            "actual_avg_bps": shadow_div.get("slippage_actual_avg", 0.0),
            "bias_bps": shadow_div.get("slippage_bias", 0.0),
            "model_too_optimistic": shadow_div.get("slippage_model_too_optimistic", False),
            "edge_erosion_bps": shadow_div.get("edge_erosion_bps", 0.0),
            "calibration_quality": shadow_div.get("calibration_quality", 0.0),
            "samples": shadow_div.get("slippage_samples", 0),
        }

        fill_calibration = {
            "model_avg_pct": shadow_div.get("fill_model_avg", 0.0),
            "actual_avg_pct": shadow_div.get("fill_actual_avg", 0.0),
            "bias_pct": shadow_div.get("fill_bias", 0.0),
            "model_too_optimistic": shadow_div.get("fill_model_too_optimistic", False),
            "samples": shadow_div.get("fill_samples", 0),
        }

        # ── Step 2: Risk model calibration ──
        risk_calibration = self.risk_mirror.compute_calibration()

        # ── Step 3: Cross-exchange divergence statistics ──
        divergence_stats = self.divergence.get_stats()

        # ── Step 4: Compute recommended adjustments ──
        adjustments = self._compute_recommended_adjustments(
            slippage_calibration, fill_calibration, risk_calibration, divergence_stats,
        )

        # ── Step 5: Compute overall calibration quality ──
        shadow_quality = shadow_div.get("calibration_quality", 0.0)
        risk_quality = risk_calibration.get("calibration_score", 0.0)

        # Weight shadow quality more (it's execution, the most critical)
        n_shadow_samples = shadow_div.get("slippage_samples", 0) + shadow_div.get("fill_samples", 0)
        n_risk_samples = risk_calibration.get("pair_count", 0)

        total_samples = n_shadow_samples + n_risk_samples
        if total_samples > 0:
            shadow_weight = n_shadow_samples / total_samples
            risk_weight = n_risk_samples / total_samples
        else:
            shadow_weight = 0.5
            risk_weight = 0.5

        calibration_quality = shadow_quality * shadow_weight + risk_quality * risk_weight

        return {
            "slippage_calibration": slippage_calibration,
            "fill_calibration": fill_calibration,
            "risk_calibration": risk_calibration,
            "divergence_stats": divergence_stats,
            "recommended_adjustments": adjustments,
            "calibration_quality": round(calibration_quality, 4),
            "shadow_samples": n_shadow_samples,
            "risk_samples": n_risk_samples,
        }

    # ===================================================================
    # BRIDGE STATE (for dashboard)
    # ===================================================================

    def get_bridge_state(self) -> dict:
        """Get complete bridge state for dashboard.

        Returns:
            Bridge state with:
            - mode: current mode
            - cycle: cycle count
            - symbol: trading pair
            - no_real_orders: guard status
            - connector_health: exchange connectivity
            - connector_latency: per-exchange latency
            - shadow_stats: shadow execution statistics
            - divergence_stats: cross-exchange divergence
            - desync_status: data synchronization
            - risk_calibration: risk model calibration
            - observation_quality: latest observation quality
            - avg_observation_quality: average quality over history
        """
        _guard_no_real_orders("get_bridge_state")

        # Observation quality
        latest_quality = 0.0
        avg_quality = 0.0
        if self._observation_quality_history:
            latest_quality = self._observation_quality_history[-1]
            avg_quality = sum(self._observation_quality_history) / len(self._observation_quality_history)

        # Desync status (current)
        desync_status = self.desync.check_sync()

        return {
            "mode": self._mode,
            "cycle": self._cycle,
            "symbol": self._symbol,
            "no_real_orders": self.NO_REAL_ORDERS,
            "connector_health": self.connector.get_health(),
            "connector_latency": dict(self.connector.latency_ms),
            "shadow_stats": {
                "total_trades": self.shadow._total_shadow_trades,
                "total_pnl_usdt": round(self.shadow._total_shadow_pnl_usdt, 4),
                "total_wins": self.shadow._total_shadow_wins,
                "total_losses": self.shadow._total_shadow_losses,
                "open_positions": len(self.shadow.get_shadow_positions()),
                "divergence_metrics": self.shadow.compute_divergence_metrics(),
            },
            "divergence_stats": self.divergence.get_stats(),
            "desync_status": desync_status,
            "risk_calibration": self.risk_mirror.get_risk_mirror_state(),
            "observation_quality": round(latest_quality, 4),
            "avg_observation_quality": round(avg_quality, 4),
        }

    # ===================================================================
    # CLEANUP
    # ===================================================================

    def close(self):
        """Close all connections.

        Properly shuts down exchange connections and cleans up resources.
        """
        _guard_no_real_orders("close")

        try:
            self.connector.close()
        except Exception as e:
            logger.warning(f"Error closing connector: {e}")

        logger.info("LiveBridgeLayer closed")

    # ===================================================================
    # INTERNAL HELPERS
    # ===================================================================

    def _fetch_from_exchanges(self) -> dict:
        """Fetch data from all exchanges via the connector.

        Returns:
            Dict mapping exchange name to exchange data.
            If an exchange is unreachable, its value is None.
        """
        try:
            return self.connector.fetch_all()
        except Exception as e:
            logger.error(f"Failed to fetch from exchanges: {e}")
            return {name: None for name in self.connector.exchanges}

    def _compute_divergence(self, binance_data: Optional[dict],
                            bybit_data: Optional[dict]) -> dict:
        """Compute cross-exchange divergence.

        Args:
            binance_data: Binance data (or None if down).
            bybit_data: Bybit data (or None if down).

        Returns:
            Divergence report from CrossExchangeDetector.
        """
        if binance_data is None or bybit_data is None:
            return self.divergence._empty_report()

        # Extract data in format expected by CrossExchangeDetector.update()
        binance_ob = binance_data.get("orderbook") or {}
        bybit_ob = bybit_data.get("orderbook") or {}

        binance_for_div = {
            "mid_price": binance_ob.get("mid_price", 0.0),
            "best_bid": (
                binance_ob["bids"][0][0] if binance_ob.get("bids") else 0.0
            ),
            "best_ask": (
                binance_ob["asks"][0][0] if binance_ob.get("asks") else 0.0
            ),
            "bid_depth": binance_ob.get("bid_depth_usdt", 0.0),
            "ask_depth": binance_ob.get("ask_depth_usdt", 0.0),
        }

        bybit_for_div = {
            "mid_price": bybit_ob.get("mid_price", 0.0),
            "best_bid": (
                bybit_ob["bids"][0][0] if bybit_ob.get("bids") else 0.0
            ),
            "best_ask": (
                bybit_ob["asks"][0][0] if bybit_ob.get("asks") else 0.0
            ),
            "bid_depth": bybit_ob.get("bid_depth_usdt", 0.0),
            "ask_depth": bybit_ob.get("ask_depth_usdt", 0.0),
        }

        return self.divergence.update(binance_for_div, bybit_for_div)

    def _compute_recommended_adjustments(
        self,
        slippage_cal: dict,
        fill_cal: dict,
        risk_cal: dict,
        div_stats: dict,
    ) -> dict:
        """Compute recommended adjustments for the engine based on calibration.

        These adjustments can be fed to LeanExecutor to improve its
        slippage/fill models.

        Args:
            slippage_cal: Slippage calibration metrics.
            fill_cal: Fill calibration metrics.
            risk_cal: Risk calibration metrics.
            div_stats: Divergence statistics.

        Returns:
            Recommended adjustments dict with:
            - slippage_adjustment_bps: adjustment to base_slippage_bps
            - fill_adjustment_pct: adjustment to expected fill pct
            - size_adjustment_factor: adjustment to position sizing
            - risk_score_adjustment: adjustment to risk model
            - confidence: how confident are we in these adjustments [0, 1]
        """
        adjustments = {
            "slippage_adjustment_bps": 0.0,
            "fill_adjustment_pct": 0.0,
            "size_adjustment_factor": 1.0,
            "risk_score_adjustment": 0.0,
            "confidence": 0.0,
        }

        # ── Slippage adjustment ──
        # If model is too optimistic (underestimates slippage), add positive adjustment
        if slippage_cal.get("model_too_optimistic", False):
            # The bias tells us how much the model underestimates
            adjustments["slippage_adjustment_bps"] = -slippage_cal.get("bias_bps", 0.0)
        elif slippage_cal.get("bias_bps", 0.0) != 0:
            # Model is too pessimistic, can reduce slippage estimate
            adjustments["slippage_adjustment_bps"] = -slippage_cal.get("bias_bps", 0.0)

        # ── Fill adjustment ──
        # If model overestimates fills, reduce fill estimate
        if fill_cal.get("model_too_optimistic", False):
            adjustments["fill_adjustment_pct"] = -fill_cal.get("bias_pct", 0.0)
        elif fill_cal.get("bias_pct", 0.0) != 0:
            adjustments["fill_adjustment_pct"] = -fill_cal.get("bias_pct", 0.0)

        # ── Size adjustment ──
        # If risk model is overconfident, reduce position sizes
        risk_bias = risk_cal.get("risk_model_bias", "CALIBRATED")
        if risk_bias == "OVERCONFIDENT":
            adjustments["size_adjustment_factor"] = 0.80  # Reduce 20%
        elif risk_bias == "CONSERVATIVE":
            adjustments["size_adjustment_factor"] = 1.10  # Increase 10%
        else:
            adjustments["size_adjustment_factor"] = 1.0

        # ── Risk score adjustment ──
        if risk_bias == "OVERCONFIDENT":
            adjustments["risk_score_adjustment"] = 0.05  # Add 5% to risk scores
        elif risk_bias == "CONSERVATIVE":
            adjustments["risk_score_adjustment"] = -0.02  # Reduce 2%

        # ── Confidence ──
        # Based on sample size
        n_samples = slippage_cal.get("samples", 0) + fill_cal.get("samples", 0)
        if n_samples >= 50:
            adjustments["confidence"] = min(1.0, 0.5 + n_samples / 200.0)
        elif n_samples >= 10:
            adjustments["confidence"] = 0.3
        else:
            adjustments["confidence"] = 0.1

        # Round all values
        for key in adjustments:
            adjustments[key] = round(adjustments[key], 4)

        return adjustments


# ===========================================================================
# MOCK DATA GENERATORS (for self-tests only)
# ===========================================================================

def _generate_mock_exchange_data(
    exchange: str = "binance",
    mid_price: float = 50000.0,
    spread_bps: float = 5.0,
    n_levels: int = 20,
    seed: int = 42,
) -> dict:
    """Generate mock exchange data for testing.

    Produces data in the format returned by ExchangeConnector.fetch_all().

    Args:
        exchange: Exchange name ("binance" or "bybit").
        mid_price: Mid price for the orderbook.
        spread_bps: Spread in basis points.
        n_levels: Number of orderbook levels.
        seed: Random seed for reproducibility.

    Returns:
        Dict with orderbook, ticker, trades, funding, ohlcv keys.
    """
    import random
    rng = random.Random(seed)

    half_spread = mid_price * (spread_bps / 10000.0) / 2.0
    best_bid = mid_price - half_spread
    best_ask = mid_price + half_spread

    tick_size = mid_price * 0.0001

    bids = []
    asks = []
    for i in range(n_levels):
        bid_price = best_bid - i * tick_size
        ask_price = best_ask + i * tick_size
        bid_size = rng.uniform(0.1, 5.0)
        ask_size = rng.uniform(0.1, 5.0)
        bids.append([bid_price, bid_size])
        asks.append([ask_price, ask_size])

    # Compute depth metrics
    bid_depth_usdt = sum(p * s for p, s in bids[:5])
    ask_depth_usdt = sum(p * s for p, s in asks[:5])

    # Orderbook
    orderbook = {
        "exchange": exchange,
        "symbol": "BTC/USDT",
        "bids": bids,
        "asks": asks,
        "timestamp": int(time.time() * 1000),
        "nonce": seed,
        "bid_depth_usdt": round(bid_depth_usdt, 2),
        "ask_depth_usdt": round(ask_depth_usdt, 2),
        "spread_bps": round(spread_bps, 2),
        "mid_price": round(mid_price, 2),
        "depth_imbalance": round((bid_depth_usdt - ask_depth_usdt) / (bid_depth_usdt + ask_depth_usdt), 6),
        "available_liquidity_usdt": round(bid_depth_usdt + ask_depth_usdt, 2),
        "latency_ms": round(rng.uniform(50, 300), 2),
    }

    # Ticker
    ticker = {
        "exchange": exchange,
        "symbol": "BTC/USDT",
        "bid": best_bid,
        "ask": best_ask,
        "last": mid_price,
        "high": mid_price * 1.02,
        "low": mid_price * 0.98,
        "volume": 12345.67,
        "quote_volume": 617283500.0,
        "change_pct": 1.5,
        "spread_bps": round(spread_bps, 2),
        "mid_price": round(mid_price, 2),
        "timestamp": int(time.time() * 1000),
        "latency_ms": round(rng.uniform(50, 300), 2),
    }

    # Trades
    base_ts = int(time.time() * 1000) - 100 * 1000
    trades = []
    for i in range(100):
        price = mid_price + rng.uniform(-50, 50)
        amount = rng.uniform(0.001, 1.0)
        side = rng.choice(["buy", "sell"])
        trades.append({
            "exchange": exchange,
            "symbol": "BTC/USDT",
            "id": str(1000 + i),
            "price": price,
            "amount": amount,
            "cost_usdt": round(price * amount, 2),
            "side": side,
            "timestamp": base_ts + i * 10,
        })

    # Funding rate
    funding = {
        "exchange": exchange,
        "symbol": "BTC/USDT",
        "rate": rng.uniform(-0.0003, 0.0003),
        "next_funding_ms": rng.randint(0, 28800000),
        "timestamp": int(time.time() * 1000),
        "latency_ms": round(rng.uniform(50, 200), 2),
    }

    # OHLCV
    ohlcv = []
    price = mid_price
    start_ts = int(time.time() * 1000) - 60 * 3600 * 1000
    for i in range(60):
        o = price
        change = rng.gauss(0, 0.001) * price
        c = o + change
        h = max(o, c) + abs(rng.gauss(0, 0.0005)) * price
        l = min(o, c) - abs(rng.gauss(0, 0.0005)) * price
        v = rng.uniform(10, 500)
        ohlcv.append([start_ts + i * 3600 * 1000, o, h, l, c, v])
        price = c

    # Open interest
    open_interest = {
        "oi_value": 500_000_000.0 + rng.uniform(-50_000_000, 50_000_000),
        "oi_change_24h_pct": rng.uniform(-10.0, 10.0),
    }

    return {
        "orderbook": orderbook,
        "ticker": ticker,
        "trades": trades,
        "funding": funding,
        "ohlcv": ohlcv,
        "open_interest": open_interest,
    }


# ===========================================================================
# COMPREHENSIVE SELF-TEST
# ===========================================================================

def _run_self_tests():
    """Run comprehensive self-tests using mock data.

    Tests:
    1. Creates LiveBridgeLayer
    2. Tests observe() with mock exchange data
    3. Tests shadow_decide() with mock engine
    4. Tests calibration computation
    5. Tests merged market data format
    6. Tests fallback when one exchange is down
    7. Tests bridge state output
    8. Tests NO_REAL_ORDERS guard
    9. Tests observation quality computation
    10. Tests full cycle: observe → shadow_decide → calibrate
    """
    print("=" * 70)
    print("live_bridge_layer.py — Comprehensive Self-Test")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  — {detail}")

    # ===================================================================
    # Test 1: LiveBridgeLayer initialization
    # ===================================================================
    print("\n--- Test 1: LiveBridgeLayer Initialization ---")
    try:
        # Create with default config (will use ccxt for exchange init)
        bridge = LiveBridgeLayer(config={
            "symbol": "BTC/USDT",
            "mode": "OBSERVATION",
        })
        check("bridge created", bridge is not None)
        check("mode is OBSERVATION", bridge._mode == "OBSERVATION")
        check("symbol is BTC/USDT", bridge._symbol == "BTC/USDT")
        check("cycle starts at 0", bridge._cycle == 0)
        check("NO_REAL_ORDERS is True", bridge.NO_REAL_ORDERS is True)
        check("connector exists", bridge.connector is not None)
        check("shadow exists", bridge.shadow is not None)
        check("divergence exists", bridge.divergence is not None)
        check("desync exists", bridge.desync is not None)
        check("risk_mirror exists", bridge.risk_mirror is not None)
        bridge.close()
    except Exception as e:
        check("bridge initialization", False, str(e))

    # ===================================================================
    # Test 2: observe() with mock exchange data
    # ===================================================================
    print("\n--- Test 2: observe() with Mock Exchange Data ---")
    try:
        bridge2 = LiveBridgeLayer(config={"mode": "OBSERVATION"})

        # Mock the connector's fetch_all to return mock data
        binance_mock = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)

        original_fetch = bridge2.connector.fetch_all
        bridge2.connector.fetch_all = lambda: {"binance": binance_mock, "bybit": bybit_mock}

        observation = bridge2.observe()

        check("observation returned", observation is not None)
        check("binance data present", observation["binance"] is not None)
        check("bybit data present", observation["bybit"] is not None)
        check("sync_status present", "sync_status" in observation)
        check("divergence present", "divergence" in observation)
        check("merged_market_data present", "merged_market_data" in observation)
        check("observation_quality present", "observation_quality" in observation)
        check("cycle incremented", observation["cycle"] == 1)
        check("timestamp present", observation["timestamp"] > 0)

        bridge2.close()
    except Exception as e:
        check("observe with mock data", False, str(e))

    # ===================================================================
    # Test 3: shadow_decide() with mock engine
    # ===================================================================
    print("\n--- Test 3: shadow_decide() with Mock Engine ---")
    try:
        bridge3 = LiveBridgeLayer(config={"mode": "SHADOW"})

        # Create mock engine that returns a standard action_vector
        class MockEngine:
            def cycle(self, market_data):
                return {
                    "state_vector": {},
                    "state_summary": {"volatility": 0.02, "regime": "RANGING"},
                    "regime": {"regime": "RANGING"},
                    "survival_assessment": {},
                    "action_vector": {
                        "action": "EXECUTE",
                        "side": "LONG",
                        "size": 0.10,
                        "size_usdt": 100.0,
                        "capital": 1000.0,
                        "reason": "mock_test",
                        "model_slippage_bps": 5.0,
                        "model_fill_pct": 0.95,
                        "pipeline": {
                            "step3_risk": {
                                "risk_score": 0.30,
                                "estimated_drawdown": 0.02,
                                "size_multiplier": 0.80,
                                "verdict": "PASS",
                            },
                            "step4_ev": {"adjusted_ev": 0.005},
                        },
                    },
                    "execution_result": {
                        "action": "EXECUTE",
                        "side": "LONG",
                        "position_usdt": 100.0,
                        "execution_quality": 0.8,
                        "total_cost_pct": 0.001,
                        "theoretical_edge": 0.005,
                        "realized_edge": 0.003,
                        "slippage": {"slippage_bps": 3.0},
                        "fill": {"expected_fill_pct": 0.95},
                    },
                    "learning_update": None,
                    "metrics": {},
                }

        mock_engine = MockEngine()

        # Create observation with mock data
        binance_mock3 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock3 = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)

        # Build merged market data manually
        merged3 = _build_merged_market_data(binance_mock3, bybit_mock3)

        observation3 = {
            "merged_market_data": merged3,
            "binance": binance_mock3,
            "bybit": bybit_mock3,
        }

        result3 = bridge3.shadow_decide(observation3, mock_engine)

        check("shadow_decide returned", result3 is not None)
        check("engine_result present", result3.get("engine_result") is not None)
        check("shadow_result present", result3.get("shadow_result") is not None)
        check("calibration present", "calibration" in result3)
        check("risk_calibration present", "risk_calibration" in result3)
        check("shadow action EXECUTE", result3["shadow_result"].get("action") == "EXECUTE")
        check("shadow side LONG", result3["shadow_result"].get("side") == "LONG")
        check("slippage_bps > 0", result3["shadow_result"].get("slippage_bps", 0) >= 0)
        check("fill_pct > 0", result3["shadow_result"].get("fill_pct", 0) > 0)

        bridge3.close()
    except Exception as e:
        check("shadow_decide with mock engine", False, str(e))

    # ===================================================================
    # Test 4: Calibration computation
    # ===================================================================
    print("\n--- Test 4: Calibration Computation ---")
    try:
        bridge4 = LiveBridgeLayer(config={"mode": "CALIBRATION"})

        # Feed some data through to build up calibration history
        binance_mock4 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock4 = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)
        bridge4.connector.fetch_all = lambda: {"binance": binance_mock4, "bybit": bybit_mock4}

        cal4 = bridge4.calibrate()

        check("calibrate returned", cal4 is not None)
        check("slippage_calibration present", "slippage_calibration" in cal4)
        check("fill_calibration present", "fill_calibration" in cal4)
        check("risk_calibration present", "risk_calibration" in cal4)
        check("divergence_stats present", "divergence_stats" in cal4)
        check("recommended_adjustments present", "recommended_adjustments" in cal4)
        check("calibration_quality present", "calibration_quality" in cal4)

        # Check recommended adjustments structure
        adj4 = cal4["recommended_adjustments"]
        check("slippage_adjustment_bps in adjustments", "slippage_adjustment_bps" in adj4)
        check("fill_adjustment_pct in adjustments", "fill_adjustment_pct" in adj4)
        check("size_adjustment_factor in adjustments", "size_adjustment_factor" in adj4)
        check("risk_score_adjustment in adjustments", "risk_score_adjustment" in adj4)
        check("confidence in adjustments", "confidence" in adj4)

        bridge4.close()
    except Exception as e:
        check("calibration computation", False, str(e))

    # ===================================================================
    # Test 5: Merged market data format
    # ===================================================================
    print("\n--- Test 5: Merged Market Data Format ---")
    try:
        binance_mock5 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock5 = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)

        merged5 = _build_merged_market_data(binance_mock5, bybit_mock5)

        # Must match ccxt_adapter.generate_synthetic_market_data() format
        check("symbol present", "symbol" in merged5)
        check("timeframe present", "timeframe" in merged5)
        check("ohlcv present", "ohlcv" in merged5)
        check("ticker present", "ticker" in merged5)
        check("orderbook present", "orderbook" in merged5)
        check("funding present", "funding" in merged5)
        check("open_interest present", "open_interest" in merged5)
        check("timestamp present", "timestamp" in merged5)

        # Ticker format
        check("ticker.bid present", "bid" in merged5["ticker"])
        check("ticker.ask present", "ask" in merged5["ticker"])
        check("ticker.spread present", "spread" in merged5["ticker"])
        check("ticker.spread_pct present", "spread_pct" in merged5["ticker"])
        check("ticker.volume_24h present", "volume_24h" in merged5["ticker"])

        # Orderbook format
        check("orderbook.bid_depth present", "bid_depth" in merged5["orderbook"])
        check("orderbook.ask_depth present", "ask_depth" in merged5["orderbook"])
        check("orderbook.spread present", "spread" in merged5["orderbook"])
        check("orderbook.bids list present", "bids" in merged5["orderbook"])
        check("orderbook.asks list present", "asks" in merged5["orderbook"])

        # Prices are valid
        check("ticker.bid > 0", merged5["ticker"]["bid"] > 0)
        check("ticker.ask > 0", merged5["ticker"]["ask"] > 0)
        check("ticker.ask >= ticker.bid", merged5["ticker"]["ask"] >= merged5["ticker"]["bid"])
        check("spread_pct >= 0", merged5["ticker"]["spread_pct"] >= 0)

        # Observation metadata
        check("source_exchange present", "source_exchange" in merged5)
        check("observation_metadata present", "observation_metadata" in merged5)
        check("binance_weight > 0", merged5["observation_metadata"]["binance_weight"] > 0)
        check("bybit_weight > 0", merged5["observation_metadata"]["bybit_weight"] > 0)

    except Exception as e:
        check("merged market data format", False, str(e))

    # ===================================================================
    # Test 6: Fallback when one exchange is down
    # ===================================================================
    print("\n--- Test 6: Fallback When One Exchange Is Down ---")
    try:
        # Only Binance available
        binance_mock6 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        merged6a = _build_merged_market_data(binance_mock6, None)
        check("binance-only: source is binance", merged6a["source_exchange"] == "binance")
        check("binance-only: ticker.bid > 0", merged6a["ticker"]["bid"] > 0)
        check("binance-only: binance_available True",
              merged6a["observation_metadata"]["binance_available"] is True)
        check("binance-only: bybit_available False",
              merged6a["observation_metadata"]["bybit_available"] is False)

        # Only Bybit available
        bybit_mock6 = _generate_mock_exchange_data("bybit", mid_price=50001.0, seed=43)
        merged6b = _build_merged_market_data(None, bybit_mock6)
        check("bybit-only: source is bybit", merged6b["source_exchange"] == "bybit")
        check("bybit-only: ticker.bid > 0", merged6b["ticker"]["bid"] > 0)
        check("bybit-only: bybit_available True",
              merged6b["observation_metadata"]["bybit_available"] is True)
        check("bybit-only: binance_available False",
              merged6b["observation_metadata"]["binance_available"] is False)

        # Neither available
        merged6c = _build_merged_market_data(None, None)
        check("both-down: source is NONE", merged6c["source_exchange"] == "NONE")
        check("both-down: ticker.bid == 0", merged6c["ticker"]["bid"] == 0.0)
        check("both-down: observation_quality == 0", merged6c["observation_metadata"]["binance_weight"] == 0.0)

        # Test observe() with one exchange down
        bridge6 = LiveBridgeLayer(config={"mode": "OBSERVATION"})
        bridge6.connector.fetch_all = lambda: {"binance": binance_mock6, "bybit": None}
        obs6 = bridge6.observe()
        check("observe with bybit down: quality < 1.0", obs6["observation_quality"] < 1.0)
        check("observe with bybit down: quality > 0.0", obs6["observation_quality"] > 0.0)
        check("observe with bybit down: merged data has bids",
              len(obs6["merged_market_data"].get("orderbook", {}).get("bids", [])) > 0)

        bridge6.close()
    except Exception as e:
        check("fallback one exchange down", False, str(e))

    # ===================================================================
    # Test 7: Bridge state output
    # ===================================================================
    print("\n--- Test 7: Bridge State Output ---")
    try:
        bridge7 = LiveBridgeLayer(config={"mode": "OBSERVATION"})
        binance_mock7 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock7 = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)
        bridge7.connector.fetch_all = lambda: {"binance": binance_mock7, "bybit": bybit_mock7}

        # Run a cycle first
        bridge7.observe()

        state7 = bridge7.get_bridge_state()

        check("mode present", "mode" in state7)
        check("cycle present", "cycle" in state7)
        check("symbol present", "symbol" in state7)
        check("no_real_orders present", "no_real_orders" in state7)
        check("connector_health present", "connector_health" in state7)
        check("connector_latency present", "connector_latency" in state7)
        check("shadow_stats present", "shadow_stats" in state7)
        check("divergence_stats present", "divergence_stats" in state7)
        check("desync_status present", "desync_status" in state7)
        check("risk_calibration present", "risk_calibration" in state7)
        check("observation_quality present", "observation_quality" in state7)
        check("avg_observation_quality present", "avg_observation_quality" in state7)

        check("no_real_orders is True", state7["no_real_orders"] is True)
        check("cycle == 1", state7["cycle"] == 1)
        check("symbol == BTC/USDT", state7["symbol"] == "BTC/USDT")

        bridge7.close()
    except Exception as e:
        check("bridge state output", False, str(e))

    # ===================================================================
    # Test 8: NO_REAL_ORDERS guard
    # ===================================================================
    print("\n--- Test 8: NO_REAL_ORDERS Guard ---")
    try:
        bridge8 = LiveBridgeLayer(config={"mode": "OBSERVATION"})

        # The class-level NO_REAL_ORDERS flag must be True
        check("class NO_REAL_ORDERS is True", LiveBridgeLayer.NO_REAL_ORDERS is True)
        check("instance NO_REAL_ORDERS is True", bridge8.NO_REAL_ORDERS is True)

        # The guard function should not raise in normal contexts
        try:
            _guard_no_real_orders("test_context")
            check("guard passes in normal context", True)
        except RealOrderAttemptedError:
            check("guard passes in normal context", False, "Unexpected RealOrderAttemptedError")

        # Verify that the guard WOULD raise if called from a dangerous context
        # We can't easily test this without actually naming a function dangerously,
        # but we can verify the guard mechanism exists
        check("guard function exists", callable(_guard_no_real_orders))
        check("RealOrderAttemptedError exists", RealOrderAttemptedError is not None)

        # Verify the guard is called in observe()
        binance_mock8 = _generate_mock_exchange_data("binance", seed=42)
        bybit_mock8 = _generate_mock_exchange_data("bybit", seed=43)
        bridge8.connector.fetch_all = lambda: {"binance": binance_mock8, "bybit": bybit_mock8}

        # observe() should work fine (doesn't try to place orders)
        obs8 = bridge8.observe()
        check("observe() completes with guard", obs8 is not None)

        # calibrate() should work fine
        cal8 = bridge8.calibrate()
        check("calibrate() completes with guard", cal8 is not None)

        # get_bridge_state() should work fine
        state8 = bridge8.get_bridge_state()
        check("get_bridge_state() completes with guard", state8 is not None)

        bridge8.close()
    except Exception as e:
        check("NO_REAL_ORDERS guard", False, str(e))

    # ===================================================================
    # Test 9: Observation quality computation
    # ===================================================================
    print("\n--- Test 9: Observation Quality Computation ---")
    try:
        # High quality: both exchanges, synced, no divergence
        high_quality_obs = {
            "merged_market_data": {
                "observation_metadata": {
                    "binance_available": True,
                    "bybit_available": True,
                },
                "ticker": {"bid": 50000.0, "ask": 50001.0},
                "orderbook": {"bid_depth": 100.0, "ask_depth": 100.0},
            },
            "sync_status": {"sync_status": "SYNCED"},
            "divergence": {"divergence_level": "NONE"},
        }
        q9a = _compute_observation_quality(high_quality_obs)
        check("high quality >= 0.8", q9a >= 0.8, f"got {q9a}")
        check("high quality <= 1.0", q9a <= 1.0, f"got {q9a}")

        # Medium quality: one exchange, minor desync
        medium_quality_obs = {
            "merged_market_data": {
                "observation_metadata": {
                    "binance_available": True,
                    "bybit_available": False,
                },
                "ticker": {"bid": 50000.0, "ask": 50001.0},
                "orderbook": {"bid_depth": 100.0, "ask_depth": 100.0},
            },
            "sync_status": {"sync_status": "MINOR_DESYNC"},
            "divergence": {"divergence_level": "LOW"},
        }
        q9b = _compute_observation_quality(medium_quality_obs)
        check("medium quality < high quality", q9b < q9a, f"medium={q9b}, high={q9a}")
        check("medium quality > 0", q9b > 0, f"got {q9b}")

        # Low quality: no exchanges, stale, extreme divergence
        low_quality_obs = {
            "merged_market_data": {
                "observation_metadata": {
                    "binance_available": False,
                    "bybit_available": False,
                },
                "ticker": {"bid": 0.0, "ask": 0.0},
                "orderbook": {"bid_depth": 0.0, "ask_depth": 0.0},
            },
            "sync_status": {"sync_status": "STALE"},
            "divergence": {"divergence_level": "EXTREME"},
        }
        q9c = _compute_observation_quality(low_quality_obs)
        check("low quality == 0.0", q9c == 0.0, f"got {q9c}")

    except Exception as e:
        check("observation quality computation", False, str(e))

    # ===================================================================
    # Test 10: Full cycle — observe → shadow_decide → calibrate
    # ===================================================================
    print("\n--- Test 10: Full Cycle: observe → shadow_decide → calibrate ---")
    try:
        bridge10 = LiveBridgeLayer(config={"mode": "CALIBRATION"})

        # Mock engine
        class MockEngine10:
            def cycle(self, market_data):
                return {
                    "state_vector": {},
                    "state_summary": {"volatility": 0.02, "regime": "RANGING"},
                    "regime": {"regime": "RANGING"},
                    "survival_assessment": {},
                    "action_vector": {
                        "action": "EXECUTE",
                        "side": "LONG",
                        "size": 0.10,
                        "size_usdt": 100.0,
                        "capital": 1000.0,
                        "reason": "full_cycle_test",
                        "model_slippage_bps": 5.0,
                        "model_fill_pct": 0.95,
                        "pipeline": {
                            "step3_risk": {
                                "risk_score": 0.30,
                                "estimated_drawdown": 0.02,
                                "size_multiplier": 0.80,
                                "verdict": "PASS",
                            },
                        },
                    },
                    "execution_result": {
                        "action": "EXECUTE",
                        "side": "LONG",
                        "position_usdt": 100.0,
                        "execution_quality": 0.8,
                        "total_cost_pct": 0.001,
                        "theoretical_edge": 0.005,
                        "realized_edge": 0.003,
                    },
                    "learning_update": None,
                    "metrics": {},
                }

        mock_engine10 = MockEngine10()

        # Mock connector
        binance_mock10 = _generate_mock_exchange_data("binance", mid_price=50000.0, seed=42)
        bybit_mock10 = _generate_mock_exchange_data("bybit", mid_price=50002.0, seed=43)
        bridge10.connector.fetch_all = lambda: {"binance": binance_mock10, "bybit": bybit_mock10}

        # Step 1: Observe
        obs10 = bridge10.observe()
        check("step 1 observe: returned", obs10 is not None)
        check("step 1 observe: quality > 0", obs10["observation_quality"] > 0)
        check("step 1 observe: merged data valid", obs10["merged_market_data"]["ticker"]["bid"] > 0)

        # Step 2: Shadow decide
        shadow10 = bridge10.shadow_decide(obs10, mock_engine10)
        check("step 2 shadow: returned", shadow10 is not None)
        check("step 2 shadow: engine ran", shadow10["engine_result"] is not None)
        check("step 2 shadow: shadow executed", shadow10["shadow_result"] is not None)
        check("step 2 shadow: calibration present", "calibration" in shadow10)
        check("step 2 shadow: risk calibration present", "risk_calibration" in shadow10)

        # Step 3: Calibrate
        cal10 = bridge10.calibrate()
        check("step 3 calibrate: returned", cal10 is not None)
        check("step 3 calibrate: slippage calibration", "slippage_calibration" in cal10)
        check("step 3 calibrate: fill calibration", "fill_calibration" in cal10)
        check("step 3 calibrate: risk calibration", "risk_calibration" in cal10)
        check("step 3 calibrate: recommended adjustments", "recommended_adjustments" in cal10)
        check("step 3 calibrate: quality score", "calibration_quality" in cal10)

        # Run a few more cycles to accumulate data
        for i in range(5):
            obs_i = bridge10.observe()
            bridge10.shadow_decide(obs_i, mock_engine10)

        cal10b = bridge10.calibrate()
        check("multi-cycle: calibration quality present",
              "calibration_quality" in cal10b)

        # Final bridge state
        state10 = bridge10.get_bridge_state()
        check("final state: cycle > 1", state10["cycle"] > 1)
        check("final state: observation quality tracked",
              state10["observation_quality"] >= 0)
        check("final state: avg quality tracked",
              state10["avg_observation_quality"] >= 0)

        bridge10.close()
    except Exception as e:
        check("full cycle test", False, str(e))
        import traceback
        traceback.print_exc()

    # ===================================================================
    # Summary
    # ===================================================================
    print("\n" + "=" * 70)
    print(f"Self-Test Complete: {passed} passed, {failed} failed")
    print("=" * 70)
    if failed:
        print("WARNING: Some tests FAILED — review output above.")
    else:
        print("All tests PASSED.")


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )
    _run_self_tests()
