"""
cross_exchange_detector.py — CrossExchangeDetector
===================================================

Detects price, spread, and liquidity divergence between Binance and Bybit
for the same trading pair. This is an OBSERVATION and MONITORING component
for the GLM/SENECIO LIVE_BRIDGE_LAYER_v1 shadow bridge.

This is NOT for arbitrage trading. It provides:
1. Regime validation — do both exchanges agree on regime?
2. Liquidity divergence — is one exchange drying up?
3. Adversarial detection — is someone manipulating one exchange?
4. Execution calibration — which exchange offers better fills?

NO real orders, NO API keys — purely analytical.
"""

from __future__ import annotations

import time
import math
import logging
from collections import deque
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class CrossExchangeDetector:
    """Detect cross-exchange divergence.

    Monitors price, spread, and liquidity differences between
    Binance and Bybit for the same trading pair.

    This is NOT for arbitrage trading. It's for:
    1. Regime validation — do both exchanges agree on regime?
    2. Liquidity divergence — is one exchange drying up?
    3. Adversarial detection — is someone manipulating one exchange?
    4. Execution calibration — which exchange offers better fills?

    Attributes:
        price_divergence_threshold_bps: BPS threshold for notable price divergence.
        liquidity_divergence_threshold: Fractional threshold for liquidity divergence.
        adversarial_sudden_bps: BPS threshold for sudden adversarial divergence.
    """

    # Divergence level constants
    LEVEL_NONE = "NONE"
    LEVEL_LOW = "LOW"
    LEVEL_MEDIUM = "MEDIUM"
    LEVEL_HIGH = "HIGH"
    LEVEL_EXTREME = "EXTREME"

    # Arbitrage signal constants
    SIGNAL_NONE = "NONE"
    SIGNAL_BUY_BINANCE_SELL_BYBIT = "BUY_BINANCE_SELL_BYBIT"
    SIGNAL_BUY_BYBIT_SELL_BINANCE = "BUY_BYBIT_SELL_BINANCE"

    def __init__(self, config: Optional[dict] = None):
        """Initialize the CrossExchangeDetector.

        Args:
            config: Optional configuration dict overriding default thresholds.
                Supported keys:
                - price_divergence_threshold_bps (float)
                - liquidity_divergence_threshold (float)
                - adversarial_sudden_bps (float)
                - history_maxlen (int)
                - divergence_event_maxlen (int)
        """
        config = config or {}

        # Internal histories
        maxlen = config.get("history_maxlen", 1000)
        self._price_history: deque = deque(maxlen=maxlen)  # (ts, binance_mid, bybit_mid)
        self._spread_history: deque = deque(maxlen=maxlen)  # (ts, binance_spread_bps, bybit_spread_bps)
        self._divergence_events: deque = deque(maxlen=config.get("divergence_event_maxlen", 100))

        # Thresholds — configurable
        self.price_divergence_threshold_bps: float = config.get(
            "price_divergence_threshold_bps", 5.0
        )  # 5 bps = notable
        self.liquidity_divergence_threshold: float = config.get(
            "liquidity_divergence_threshold", 0.30
        )  # 30% difference
        self.adversarial_sudden_bps: float = config.get(
            "adversarial_sudden_bps", 20.0
        )  # 20 bps sudden = suspicious

        # Running statistics
        self._total_updates: int = 0
        self._divergence_count: int = 0
        self._adversarial_count: int = 0
        self._sum_price_divergence_bps: float = 0.0
        self._max_price_divergence_bps: float = 0.0
        self._sum_liquidity_divergence: float = 0.0
        self._max_liquidity_divergence: float = 0.0

        # Previous divergence for jump detection (adversarial)
        self._prev_price_divergence_bps: float = 0.0

    # ------------------------------------------------------------------
    # Core update method
    # ------------------------------------------------------------------

    def update(self, binance_data: dict, bybit_data: dict) -> dict:
        """Update with latest data from both exchanges.

        Expects normalized orderbook dicts with at minimum:
            - 'mid_price' (float): Mid price
            - 'best_bid' (float): Best bid
            - 'best_ask' (float): Best ask
            - 'bid_depth' (float or list): Total bid depth or list of [price, qty]
            - 'ask_depth' (float or list): Total ask depth or list of [price, qty]
            - 'timestamp_ms' (float, optional): Exchange timestamp

        Args:
            binance_data: Normalized orderbook from Binance.
            bybit_data: Normalized orderbook from Bybit.

        Returns:
            Divergence report dict with:
            - price_divergence_bps (float)
            - spread_divergence_bps (float)
            - liquidity_divergence (float)
            - dominant_exchange (str): 'BINANCE' / 'BYBIT' / 'EQUAL'
            - arbitrage_signal (str): Signal constant
            - divergence_level (str): Level constant
            - adversarial_suspect (bool)
            - binance_mid (float)
            - bybit_mid (float)
            - timestamp_ms (float)
        """
        ts = time.time() * 1000.0

        # Extract mid prices
        binance_mid = float(binance_data.get("mid_price", 0.0))
        bybit_mid = float(bybit_data.get("mid_price", 0.0))

        if binance_mid <= 0 or bybit_mid <= 0:
            logger.warning("CrossExchangeDetector.update: invalid mid prices, skipping.")
            return self._empty_report()

        # Record price history
        self._price_history.append((ts, binance_mid, bybit_mid))

        # ---- Price divergence (bps) ----
        avg_price = (binance_mid + bybit_mid) / 2.0
        price_divergence_bps = abs(binance_mid - bybit_mid) / avg_price * 10000.0

        # ---- Spread computation ----
        binance_spread_bps = self._compute_spread_bps(binance_data)
        bybit_spread_bps = self._compute_spread_bps(bybit_data)
        self._spread_history.append((ts, binance_spread_bps, bybit_spread_bps))
        spread_divergence_bps = abs(binance_spread_bps - bybit_spread_bps)

        # ---- Liquidity divergence ----
        binance_bid_depth = self._extract_depth(binance_data, "bid_depth")
        binance_ask_depth = self._extract_depth(binance_data, "ask_depth")
        bybit_bid_depth = self._extract_depth(bybit_data, "bid_depth")
        bybit_ask_depth = self._extract_depth(bybit_data, "ask_depth")

        total_depth = (
            binance_bid_depth + binance_ask_depth + bybit_bid_depth + bybit_ask_depth
        )
        if total_depth > 0:
            bid_diff = abs(binance_bid_depth - bybit_bid_depth)
            ask_diff = abs(binance_ask_depth - bybit_ask_depth)
            liquidity_divergence = (bid_diff + ask_diff) / total_depth
        else:
            liquidity_divergence = 0.0

        # ---- Dominant exchange (better liquidity) ----
        binance_total = binance_bid_depth + binance_ask_depth
        bybit_total = bybit_bid_depth + bybit_ask_depth
        if binance_total > bybit_total * 1.10:
            dominant_exchange = "BINANCE"
        elif bybit_total > binance_total * 1.10:
            dominant_exchange = "BYBIT"
        else:
            dominant_exchange = "EQUAL"

        # ---- Arbitrage signal ----
        if price_divergence_bps >= self.price_divergence_threshold_bps:
            if binance_mid < bybit_mid:
                arbitrage_signal = self.SIGNAL_BUY_BINANCE_SELL_BYBIT
            else:
                arbitrage_signal = self.SIGNAL_BUY_BYBIT_SELL_BINANCE
        else:
            arbitrage_signal = self.SIGNAL_NONE

        # ---- Divergence level ----
        divergence_level = self._classify_divergence(
            price_divergence_bps, liquidity_divergence
        )

        # ---- Adversarial detection ----
        # Sudden jump in price divergence relative to previous reading
        divergence_jump = abs(price_divergence_bps - self._prev_price_divergence_bps)
        adversarial_suspect = (
            divergence_jump >= self.adversarial_sudden_bps
            and price_divergence_bps >= self.adversarial_sudden_bps
        )

        # Update previous
        self._prev_price_divergence_bps = price_divergence_bps

        # ---- Update statistics ----
        self._total_updates += 1
        if price_divergence_bps >= self.price_divergence_threshold_bps:
            self._divergence_count += 1
        if adversarial_suspect:
            self._adversarial_count += 1
        self._sum_price_divergence_bps += price_divergence_bps
        self._max_price_divergence_bps = max(
            self._max_price_divergence_bps, price_divergence_bps
        )
        self._sum_liquidity_divergence += liquidity_divergence
        self._max_liquidity_divergence = max(
            self._max_liquidity_divergence, liquidity_divergence
        )

        # ---- Log divergence event if notable ----
        if divergence_level != self.LEVEL_NONE:
            event = {
                "timestamp_ms": ts,
                "price_divergence_bps": price_divergence_bps,
                "spread_divergence_bps": spread_divergence_bps,
                "liquidity_divergence": liquidity_divergence,
                "divergence_level": divergence_level,
                "adversarial_suspect": adversarial_suspect,
                "dominant_exchange": dominant_exchange,
            }
            self._divergence_events.append(event)

        report = {
            "price_divergence_bps": round(price_divergence_bps, 4),
            "spread_divergence_bps": round(spread_divergence_bps, 4),
            "liquidity_divergence": round(liquidity_divergence, 6),
            "dominant_exchange": dominant_exchange,
            "arbitrage_signal": arbitrage_signal,
            "divergence_level": divergence_level,
            "adversarial_suspect": adversarial_suspect,
            "binance_mid": binance_mid,
            "bybit_mid": bybit_mid,
            "timestamp_ms": ts,
        }

        return report

    # ------------------------------------------------------------------
    # History & stats
    # ------------------------------------------------------------------

    def get_divergence_history(self, limit: int = 100) -> List[dict]:
        """Get recent divergence measurements.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of divergence event dicts, most recent last.
        """
        events = list(self._divergence_events)
        return events[-limit:]

    def get_stats(self) -> dict:
        """Get divergence statistics.

        Returns:
            Statistics dict with counts, averages, maxima, and rates.
        """
        n = self._total_updates
        avg_price_div = self._sum_price_divergence_bps / n if n else 0.0
        avg_liq_div = self._sum_liquidity_divergence / n if n else 0.0
        divergence_rate = self._divergence_count / n if n else 0.0
        adversarial_rate = self._adversarial_count / n if n else 0.0

        return {
            "total_updates": n,
            "divergence_count": self._divergence_count,
            "adversarial_count": self._adversarial_count,
            "avg_price_divergence_bps": round(avg_price_div, 4),
            "max_price_divergence_bps": round(self._max_price_divergence_bps, 4),
            "avg_liquidity_divergence": round(avg_liq_div, 6),
            "max_liquidity_divergence": round(self._max_liquidity_divergence, 6),
            "divergence_rate": round(divergence_rate, 6),
            "adversarial_rate": round(adversarial_rate, 6),
            "price_history_len": len(self._price_history),
            "spread_history_len": len(self._spread_history),
            "divergence_events_len": len(self._divergence_events),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_spread_bps(self, data: dict) -> float:
        """Compute spread in basis points from orderbook data.

        Args:
            data: Orderbook dict with 'best_bid' and 'best_ask'.

        Returns:
            Spread in bps, or 0.0 if not computable.
        """
        best_bid = float(data.get("best_bid", 0.0))
        best_ask = float(data.get("best_ask", 0.0))
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return 0.0
        return (best_ask - best_bid) / mid * 10000.0

    def _extract_depth(self, data: dict, key: str) -> float:
        """Extract total depth from orderbook data.

        Handles both float (pre-summed) and list-of-lists formats.

        Args:
            data: Orderbook dict.
            key: Key name for the depth field.

        Returns:
            Total depth as float.
        """
        raw = data.get(key, 0.0)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, list):
            # Assume [[price, qty], ...]
            try:
                return sum(float(row[1]) for row in raw if len(row) >= 2)
            except (IndexError, TypeError, ValueError):
                return 0.0
        return 0.0

    def _classify_divergence(
        self, price_div_bps: float, liq_div: float
    ) -> str:
        """Classify divergence severity.

        Uses combined price and liquidity divergence to assign a level.

        Args:
            price_div_bps: Price divergence in basis points.
            liq_div: Liquidity divergence as a fraction [0, 1].

        Returns:
            One of NONE, LOW, MEDIUM, HIGH, EXTREME.
        """
        # Scoring: weight price and liquidity divergence
        # Price thresholds (bps)
        if price_div_bps < self.price_divergence_threshold_bps and liq_div < self.liquidity_divergence_threshold:
            return self.LEVEL_NONE
        if price_div_bps < 10.0 and liq_div < 0.40:
            return self.LEVEL_LOW
        if price_div_bps < 25.0 and liq_div < 0.60:
            return self.LEVEL_MEDIUM
        if price_div_bps < 50.0 and liq_div < 0.80:
            return self.LEVEL_HIGH
        return self.LEVEL_EXTREME

    def _empty_report(self) -> dict:
        """Return a zeroed-out divergence report."""
        return {
            "price_divergence_bps": 0.0,
            "spread_divergence_bps": 0.0,
            "liquidity_divergence": 0.0,
            "dominant_exchange": "EQUAL",
            "arbitrage_signal": self.SIGNAL_NONE,
            "divergence_level": self.LEVEL_NONE,
            "adversarial_suspect": False,
            "binance_mid": 0.0,
            "bybit_mid": 0.0,
            "timestamp_ms": time.time() * 1000.0,
        }


# ======================================================================
# Self-Test
# ======================================================================

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    print("=" * 70)
    print("CrossExchangeDetector — Self-Test")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        global passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}  — {detail}")

    # ------------------------------------------------------------------
    # Test 1: Basic initialization
    # ------------------------------------------------------------------
    print("\n--- Test 1: Initialization ---")
    det = CrossExchangeDetector()
    check("default price_divergence_threshold_bps", det.price_divergence_threshold_bps == 5.0)
    check("default liquidity_divergence_threshold", det.liquidity_divergence_threshold == 0.30)
    check("empty stats total_updates", det.get_stats()["total_updates"] == 0)
    check("empty divergence history", len(det.get_divergence_history()) == 0)

    # ------------------------------------------------------------------
    # Test 2: Custom config
    # ------------------------------------------------------------------
    print("\n--- Test 2: Custom Config ---")
    cfg = {
        "price_divergence_threshold_bps": 10.0,
        "liquidity_divergence_threshold": 0.50,
        "adversarial_sudden_bps": 30.0,
        "history_maxlen": 500,
        "divergence_event_maxlen": 50,
    }
    det2 = CrossExchangeDetector(config=cfg)
    check("custom price threshold", det2.price_divergence_threshold_bps == 10.0)
    check("custom liquidity threshold", det2.liquidity_divergence_threshold == 0.50)
    check("custom adversarial threshold", det2.adversarial_sudden_bps == 30.0)

    # ------------------------------------------------------------------
    # Test 3: Identical data → no divergence
    # ------------------------------------------------------------------
    print("\n--- Test 3: Identical Data → No Divergence ---")
    det3 = CrossExchangeDetector()
    same_data = {
        "mid_price": 50000.0,
        "best_bid": 49999.0,
        "best_ask": 50001.0,
        "bid_depth": 100.0,
        "ask_depth": 100.0,
    }
    report = det3.update(same_data, same_data)
    check("price_divergence_bps == 0", report["price_divergence_bps"] == 0.0)
    check("divergence_level NONE", report["divergence_level"] == "NONE")
    check("arbitrage_signal NONE", report["arbitrage_signal"] == "NONE")
    check("adversarial_suspect False", report["adversarial_suspect"] is False)
    check("dominant_exchange EQUAL", report["dominant_exchange"] == "EQUAL")

    # ------------------------------------------------------------------
    # Test 4: Small divergence → LOW
    # ------------------------------------------------------------------
    print("\n--- Test 4: Small Price Divergence → LOW ---")
    det4 = CrossExchangeDetector()
    binance = {
        "mid_price": 50000.0,
        "best_bid": 49999.0,
        "best_ask": 50001.0,
        "bid_depth": 100.0,
        "ask_depth": 100.0,
    }
    bybit = {
        "mid_price": 50005.0,  # 1 bps
        "best_bid": 50004.0,
        "best_ask": 50006.0,
        "bid_depth": 100.0,
        "ask_depth": 100.0,
    }
    report4 = det4.update(binance, bybit)
    check("small divergence > 0", report4["price_divergence_bps"] > 0.0)
    check("small divergence detected", report4["divergence_level"] != "NONE" or report4["price_divergence_bps"] < 5.0)

    # ------------------------------------------------------------------
    # Test 5: Large divergence → HIGH/EXTREME
    # ------------------------------------------------------------------
    print("\n--- Test 5: Large Price Divergence → HIGH/EXTREME ---")
    det5 = CrossExchangeDetector()
    binance5 = {
        "mid_price": 50000.0,
        "best_bid": 49999.0,
        "best_ask": 50001.0,
        "bid_depth": 100.0,
        "ask_depth": 100.0,
    }
    bybit5 = {
        "mid_price": 50150.0,  # ~30 bps divergence
        "best_bid": 50149.0,
        "best_ask": 50151.0,
        "bid_depth": 100.0,
        "ask_depth": 100.0,
    }
    report5 = det5.update(binance5, bybit5)
    check(
        "large divergence level HIGH or above",
        report5["divergence_level"] in ("HIGH", "MEDIUM", "EXTREME"),
        f"got {report5['divergence_level']}",
    )
    check(
        "arbitrage signal present",
        report5["arbitrage_signal"] != "NONE",
        f"got {report5['arbitrage_signal']}",
    )

    # ------------------------------------------------------------------
    # Test 6: Arbitrage direction
    # ------------------------------------------------------------------
    print("\n--- Test 6: Arbitrage Direction ---")
    det6 = CrossExchangeDetector({"price_divergence_threshold_bps": 3.0})
    bin6 = {"mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0, "bid_depth": 100.0, "ask_depth": 100.0}
    byb6 = {"mid_price": 50050.0, "best_bid": 50049.0, "best_ask": 50051.0, "bid_depth": 100.0, "ask_depth": 100.0}  # ~10 bps
    report6 = det6.update(bin6, byb6)
    check(
        "buy binance sell bybit",
        report6["arbitrage_signal"] == "BUY_BINANCE_SELL_BYBIT",
        f"got {report6['arbitrage_signal']}",
    )

    # Reverse
    det6b = CrossExchangeDetector({"price_divergence_threshold_bps": 3.0})
    report6b = det6b.update(byb6, bin6)
    check(
        "buy bybit sell binance",
        report6b["arbitrage_signal"] == "BUY_BYBIT_SELL_BINANCE",
        f"got {report6b['arbitrage_signal']}",
    )

    # ------------------------------------------------------------------
    # Test 7: Liquidity divergence & dominant exchange
    # ------------------------------------------------------------------
    print("\n--- Test 7: Liquidity Divergence & Dominant Exchange ---")
    det7 = CrossExchangeDetector()
    bin7 = {
        "mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0,
        "bid_depth": 500.0, "ask_depth": 500.0,
    }
    byb7 = {
        "mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0,
        "bid_depth": 100.0, "ask_depth": 100.0,
    }
    report7 = det7.update(bin7, byb7)
    check(
        "dominant exchange BINANCE",
        report7["dominant_exchange"] == "BINANCE",
        f"got {report7['dominant_exchange']}",
    )
    check("liquidity divergence > 0", report7["liquidity_divergence"] > 0.0)

    # ------------------------------------------------------------------
    # Test 8: Adversarial detection (sudden jump)
    # ------------------------------------------------------------------
    print("\n--- Test 8: Adversarial Detection ---")
    det8 = CrossExchangeDetector({"adversarial_sudden_bps": 15.0})
    # First update: aligned
    aligned = {"mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0, "bid_depth": 100.0, "ask_depth": 100.0}
    det8.update(aligned, aligned)
    # Second update: sudden large divergence
    sudden_bybit = {"mid_price": 50100.0, "best_bid": 50099.0, "best_ask": 50101.0, "bid_depth": 100.0, "ask_depth": 100.0}
    report8 = det8.update(aligned, sudden_bybit)
    check(
        "adversarial suspect detected",
        report8["adversarial_suspect"] is True,
        f"got {report8['adversarial_suspect']}, price_div={report8['price_divergence_bps']}",
    )

    # ------------------------------------------------------------------
    # Test 9: Invalid data → empty report
    # ------------------------------------------------------------------
    print("\n--- Test 9: Invalid Data Handling ---")
    det9 = CrossExchangeDetector()
    report9 = det9.update({"mid_price": 0}, {"mid_price": 0})
    check("empty report on zero prices", report9["price_divergence_bps"] == 0.0)
    check("NONE divergence on invalid", report9["divergence_level"] == "NONE")

    # ------------------------------------------------------------------
    # Test 10: Stats accumulation
    # ------------------------------------------------------------------
    print("\n--- Test 10: Stats Accumulation ---")
    det10 = CrossExchangeDetector()
    base = {"mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0, "bid_depth": 100.0, "ask_depth": 100.0}
    for i in range(10):
        bybit_d = {
            "mid_price": 50000.0 + i * 5,
            "best_bid": 49999.0 + i * 5,
            "best_ask": 50001.0 + i * 5,
            "bid_depth": 100.0,
            "ask_depth": 100.0,
        }
        det10.update(base, bybit_d)
    stats10 = det10.get_stats()
    check("total_updates == 10", stats10["total_updates"] == 10)
    check("max_price_divergence_bps > 0", stats10["max_price_divergence_bps"] > 0.0)
    check("avg_price_divergence_bps > 0", stats10["avg_price_divergence_bps"] > 0.0)
    check("divergence_events_len > 0", stats10["divergence_events_len"] > 0)

    # ------------------------------------------------------------------
    # Test 11: Divergence history limit
    # ------------------------------------------------------------------
    print("\n--- Test 11: Divergence History Limit ---")
    det11 = CrossExchangeDetector({"divergence_event_maxlen": 5})
    for i in range(10):
        bybit_d = {
            "mid_price": 50000.0 + i * 10,
            "best_bid": 49999.0 + i * 10,
            "best_ask": 50001.0 + i * 10,
            "bid_depth": 100.0,
            "ask_depth": 100.0,
        }
        det11.update(base, bybit_d)
    history = det11.get_divergence_history(limit=3)
    check("history limited to 3", len(history) <= 3, f"got {len(history)}")
    full_history = det11.get_divergence_history()
    check("full history capped at 5", len(full_history) <= 5, f"got {len(full_history)}")

    # ------------------------------------------------------------------
    # Test 12: List-based depth format
    # ------------------------------------------------------------------
    print("\n--- Test 12: List-Based Depth Format ---")
    det12 = CrossExchangeDetector()
    bin12 = {
        "mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0,
        "bid_depth": [[49999.0, 50.0], [49998.0, 50.0]],
        "ask_depth": [[50001.0, 50.0], [50002.0, 50.0]],
    }
    byb12 = {
        "mid_price": 50000.0, "best_bid": 49999.0, "best_ask": 50001.0,
        "bid_depth": [[49999.0, 30.0], [49998.0, 30.0]],
        "ask_depth": [[50001.0, 30.0], [50002.0, 30.0]],
    }
    report12 = det12.update(bin12, byb12)
    check("list depth processed", report12["liquidity_divergence"] > 0.0)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"Self-Test Complete: {passed} passed, {failed} failed")
    print("=" * 70)
    if failed:
        print("⚠  Some tests FAILED — review output above.")
    else:
        print("✓  All tests PASSED.")
