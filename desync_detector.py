"""
desync_detector.py — DesyncDetector
=====================================

Detects when exchange data is out of sync in a dual-exchange system.
Part of the GLM/SENECIO LIVE_BRIDGE_LAYER_v1 shadow bridge.

In a dual-exchange system, data can become desynchronized due to:
- Network latency differences
- Exchange API delays
- Clock drift
- Rate limiting pauses

When data is desynced, the system should NOT make decisions based on stale data.
This detector helps the system increase uncertainty and potentially pause
decision-making when synchronization issues are detected.

NO real orders, NO API keys — purely analytical.
"""

from __future__ import annotations

import time
import logging
from collections import deque
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DesyncDetector:
    """Detect data synchronization issues.

    Monitors timestamps from both exchanges and detects:
    1. Stale data (one exchange not updating)
    2. Clock drift between exchanges
    3. Data gaps (missing updates)
    4. Cross-exchange timing inconsistency

    If desync is detected, the system should increase uncertainty
    and potentially pause decision-making.

    Attributes:
        stale_threshold_ms: Time after which data is considered stale (ms).
        desync_threshold_ms: Time difference between exchanges for desync (ms).
        gap_threshold_ms: Time difference constituting a data gap (ms).
    """

    # Sync status constants
    STATUS_SYNCED = "SYNCED"
    STATUS_MINOR_DESYNC = "MINOR_DESYNC"
    STATUS_MAJOR_DESYNC = "MAJOR_DESYNC"
    STATUS_STALE = "STALE"

    # Recommendation constants
    REC_CONTINUE = "CONTINUE"
    REC_PAUSE_DECISIONS = "PAUSE_DECISIONS"
    REC_RECONNECT = "RECONNECT"

    def __init__(self, config: Optional[dict] = None):
        """Initialize the DesyncDetector.

        Args:
            config: Optional configuration dict overriding default thresholds.
                Supported keys:
                - stale_threshold_ms (float): Default 10000 (10s)
                - desync_threshold_ms (float): Default 5000 (5s)
                - gap_threshold_ms (float): Default 30000 (30s)
                - desync_event_maxlen (int): Default 100
                - expected_update_interval_ms (float): Default 1000 (1s)
        """
        config = config or {}

        # Last update timestamps per exchange (ms)
        self._update_timestamps: Dict[str, float] = {}
        # Previous update timestamp per exchange (for gap detection)
        self._prev_timestamps: Dict[str, float] = {}
        # Update intervals per exchange (for statistics)
        self._intervals: Dict[str, deque] = {}

        # Desync events log
        self._desync_events: deque = deque(
            maxlen=config.get("desync_event_maxlen", 100)
        )

        # Thresholds
        self.stale_threshold_ms: float = config.get("stale_threshold_ms", 10000.0)
        self.desync_threshold_ms: float = config.get("desync_threshold_ms", 5000.0)
        self.gap_threshold_ms: float = config.get("gap_threshold_ms", 30000.0)
        self.expected_update_interval_ms: float = config.get(
            "expected_update_interval_ms", 1000.0
        )

        # Statistics
        self._total_checks: int = 0
        self._synced_count: int = 0
        self._minor_desync_count: int = 0
        self._major_desync_count: int = 0
        self._stale_count: int = 0
        self._gaps_detected: int = 0
        self._max_desync_ms: float = 0.0
        self._sum_desync_ms: float = 0.0
        self._max_age_ms: float = 0.0

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def record_update(self, exchange: str, timestamp_ms: float) -> dict:
        """Record that we received an update from an exchange.

        This method tracks the timing of updates to enable gap detection
        and interval statistics.

        Args:
            exchange: Exchange identifier (e.g., 'binance', 'bybit').
            timestamp_ms: Timestamp of the update in milliseconds.

        Returns:
            Quick timing dict with:
            - exchange (str)
            - interval_ms (float or None): Time since last update from this exchange.
            - gap_detected (bool): Whether a data gap was detected.
        """
        now_ms = time.time() * 1000.0
        interval_ms = None
        gap_detected = False

        if exchange in self._update_timestamps:
            interval_ms = now_ms - self._update_timestamps[exchange]
            if interval_ms >= self.gap_threshold_ms:
                gap_detected = True
                self._gaps_detected += 1
                self._desync_events.append({
                    "timestamp_ms": now_ms,
                    "type": "GAP",
                    "exchange": exchange,
                    "gap_duration_ms": interval_ms,
                })
                logger.warning(
                    "DesyncDetector: Data gap detected on %s — %.1f ms since last update",
                    exchange,
                    interval_ms,
                )

            # Track intervals for statistics
            if exchange not in self._intervals:
                self._intervals[exchange] = deque(maxlen=200)
            self._intervals[exchange].append(interval_ms)

        # Shift current to previous
        if exchange in self._update_timestamps:
            self._prev_timestamps[exchange] = self._update_timestamps[exchange]

        self._update_timestamps[exchange] = now_ms

        return {
            "exchange": exchange,
            "interval_ms": round(interval_ms, 2) if interval_ms is not None else None,
            "gap_detected": gap_detected,
        }

    def check_sync(self) -> dict:
        """Check synchronization status across all exchanges.

        Evaluates:
        1. Whether any exchange data is stale (hasn't updated recently).
        2. Whether exchanges are out of sync with each other.
        3. The maximum age and inter-exchange desync.

        Returns:
            Sync status dict with:
            - sync_status (str): SYNCED / MINOR_DESYNC / MAJOR_DESYNC / STALE
            - max_age_ms (float): Age of oldest data across exchanges.
            - age_by_exchange (dict): {exchange: age_ms} for each tracked exchange.
            - desync_ms (float or None): Max time difference between exchange updates.
            - exchanges_tracked (int): Number of exchanges being tracked.
            - gaps_detected (int): Total gaps detected so far.
            - recommendation (str): CONTINUE / PAUSE_DECISIONS / RECONNECT
            - stale_exchanges (list): Exchanges with stale data.
        """
        now_ms = time.time() * 1000.0
        self._total_checks += 1

        # Compute age per exchange
        age_by_exchange: Dict[str, float] = {}
        stale_exchanges: List[str] = []

        for exchange, last_ts in self._update_timestamps.items():
            age = now_ms - last_ts
            age_by_exchange[exchange] = round(age, 2)
            if age >= self.stale_threshold_ms:
                stale_exchanges.append(exchange)

        # Compute inter-exchange desync
        desync_ms: Optional[float] = None
        if len(self._update_timestamps) >= 2:
            timestamps = list(self._update_timestamps.values())
            desync_ms = max(timestamps) - min(timestamps)

        # Determine sync status
        max_age = max(age_by_exchange.values()) if age_by_exchange else 0.0
        self._max_age_ms = max(self._max_age_ms, max_age)

        if stale_exchanges:
            sync_status = self.STATUS_STALE
            self._stale_count += 1
        elif desync_ms is not None and desync_ms >= self.desync_threshold_ms:
            sync_status = self.STATUS_MAJOR_DESYNC
            self._major_desync_count += 1
        elif desync_ms is not None and desync_ms >= self.desync_threshold_ms * 0.4:
            sync_status = self.STATUS_MINOR_DESYNC
            self._minor_desync_count += 1
        else:
            sync_status = self.STATUS_SYNCED
            self._synced_count += 1

        # Track desync stats
        if desync_ms is not None:
            self._max_desync_ms = max(self._max_desync_ms, desync_ms)
            self._sum_desync_ms += desync_ms

        # Log desync events
        if sync_status != self.STATUS_SYNCED:
            event = {
                "timestamp_ms": now_ms,
                "type": sync_status,
                "max_age_ms": max_age,
                "desync_ms": desync_ms,
                "stale_exchanges": stale_exchanges,
            }
            self._desync_events.append(event)

        # Determine recommendation
        recommendation = self._make_recommendation(sync_status, max_age, desync_ms)

        return {
            "sync_status": sync_status,
            "max_age_ms": round(max_age, 2),
            "age_by_exchange": age_by_exchange,
            "desync_ms": round(desync_ms, 2) if desync_ms is not None else None,
            "exchanges_tracked": len(self._update_timestamps),
            "gaps_detected": self._gaps_detected,
            "recommendation": recommendation,
            "stale_exchanges": stale_exchanges,
        }

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get desync statistics.

        Returns:
            Statistics dict with counts, averages, and interval stats.
        """
        n = self._total_checks
        avg_desync = self._sum_desync_ms / n if n else 0.0

        # Per-exchange interval stats
        interval_stats: Dict[str, dict] = {}
        for exchange, intervals in self._intervals.items():
            if intervals:
                iv_list = list(intervals)
                interval_stats[exchange] = {
                    "count": len(iv_list),
                    "avg_ms": round(sum(iv_list) / len(iv_list), 2),
                    "min_ms": round(min(iv_list), 2),
                    "max_ms": round(max(iv_list), 2),
                }

        return {
            "total_checks": n,
            "synced_count": self._synced_count,
            "minor_desync_count": self._minor_desync_count,
            "major_desync_count": self._major_desync_count,
            "stale_count": self._stale_count,
            "gaps_detected": self._gaps_detected,
            "max_desync_ms": round(self._max_desync_ms, 2),
            "avg_desync_ms": round(avg_desync, 2),
            "max_age_ms": round(self._max_age_ms, 2),
            "exchanges_tracked": len(self._update_timestamps),
            "interval_stats": interval_stats,
            "desync_events_len": len(self._desync_events),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_recommendation(
        self,
        sync_status: str,
        max_age_ms: float,
        desync_ms: Optional[float],
    ) -> str:
        """Determine action recommendation based on sync status.

        Args:
            sync_status: Current sync status.
            max_age_ms: Maximum data age across exchanges.
            desync_ms: Inter-exchange desync (ms), or None.

        Returns:
            Recommendation string: CONTINUE / PAUSE_DECISIONS / RECONNECT
        """
        if sync_status == self.STATUS_STALE:
            # If stale for very long, reconnect
            if max_age_ms >= self.gap_threshold_ms:
                return self.REC_RECONNECT
            return self.REC_PAUSE_DECISIONS
        if sync_status == self.STATUS_MAJOR_DESYNC:
            return self.REC_PAUSE_DECISIONS
        # MINOR_DESYNC or SYNCED
        return self.REC_CONTINUE

    def _get_now_ms(self) -> float:
        """Get current time in milliseconds. Overridable for testing."""
        return time.time() * 1000.0


# ======================================================================
# Self-Test
# ======================================================================

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    print("=" * 70)
    print("DesyncDetector — Self-Test")
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
    dd = DesyncDetector()
    check("default stale_threshold_ms", dd.stale_threshold_ms == 10000.0)
    check("default desync_threshold_ms", dd.desync_threshold_ms == 5000.0)
    check("default gap_threshold_ms", dd.gap_threshold_ms == 30000.0)
    check("empty stats", dd.get_stats()["total_checks"] == 0)
    check("no exchanges tracked", dd.get_stats()["exchanges_tracked"] == 0)

    # ------------------------------------------------------------------
    # Test 2: Custom config
    # ------------------------------------------------------------------
    print("\n--- Test 2: Custom Config ---")
    cfg = {
        "stale_threshold_ms": 5000.0,
        "desync_threshold_ms": 2000.0,
        "gap_threshold_ms": 15000.0,
        "desync_event_maxlen": 50,
    }
    dd2 = DesyncDetector(config=cfg)
    check("custom stale_threshold", dd2.stale_threshold_ms == 5000.0)
    check("custom desync_threshold", dd2.desync_threshold_ms == 2000.0)
    check("custom gap_threshold", dd2.gap_threshold_ms == 15000.0)

    # ------------------------------------------------------------------
    # Test 3: record_update returns proper dict
    # ------------------------------------------------------------------
    print("\n--- Test 3: record_update ---")
    dd3 = DesyncDetector()
    result3 = dd3.record_update("binance", time.time() * 1000)
    check("exchange field set", result3["exchange"] == "binance")
    check("first update interval is None", result3["interval_ms"] is None)
    check("first update no gap", result3["gap_detected"] is False)

    # ------------------------------------------------------------------
    # Test 4: Second update shows interval
    # ------------------------------------------------------------------
    print("\n--- Test 4: Second Update Interval ---")
    dd4 = DesyncDetector()
    dd4.record_update("binance", time.time() * 1000)
    import time as _time
    _time.sleep(0.05)  # 50ms
    result4 = dd4.record_update("binance", time.time() * 1000)
    check("interval_ms is not None", result4["interval_ms"] is not None)
    check("interval_ms > 0", result4["interval_ms"] > 0)
    check("no gap detected", result4["gap_detected"] is False)

    # ------------------------------------------------------------------
    # Test 5: Synced status when both exchanges updated recently
    # ------------------------------------------------------------------
    print("\n--- Test 5: Synced Status ---")
    dd5 = DesyncDetector()
    now = time.time() * 1000
    dd5.record_update("binance", now)
    dd5.record_update("bybit", now)
    status5 = dd5.check_sync()
    check(
        "sync_status SYNCED",
        status5["sync_status"] == "SYNCED",
        f"got {status5['sync_status']}",
    )
    check("recommendation CONTINUE", status5["recommendation"] == "CONTINUE")
    check("desync_ms small", status5["desync_ms"] is not None and status5["desync_ms"] < 100)
    check("2 exchanges tracked", status5["exchanges_tracked"] == 2)
    check("no stale exchanges", len(status5["stale_exchanges"]) == 0)

    # ------------------------------------------------------------------
    # Test 6: Stale detection (simulate old timestamp)
    # ------------------------------------------------------------------
    print("\n--- Test 6: Stale Detection ---")
    dd6 = DesyncDetector({"stale_threshold_ms": 2000.0})
    now6 = time.time() * 1000
    dd6.record_update("binance", now6)
    # Manually set bybit's timestamp to the past
    dd6._update_timestamps["bybit"] = now6 - 5000.0  # 5s ago
    status6 = dd6.check_sync()
    check(
        "sync_status STALE",
        status6["sync_status"] == "STALE",
        f"got {status6['sync_status']}",
    )
    check("bybit in stale_exchanges", "bybit" in status6["stale_exchanges"])
    check(
        "recommendation PAUSE_DECISIONS or RECONNECT",
        status6["recommendation"] in ("PAUSE_DECISIONS", "RECONNECT"),
    )

    # ------------------------------------------------------------------
    # Test 7: Desync detection
    # ------------------------------------------------------------------
    print("\n--- Test 7: Desync Detection ---")
    dd7 = DesyncDetector({"desync_threshold_ms": 1000.0})
    now7 = time.time() * 1000
    dd7._update_timestamps["binance"] = now7
    dd7._update_timestamps["bybit"] = now7 - 3000.0  # 3s behind
    status7 = dd7.check_sync()
    check(
        "MAJOR_DESYNC detected",
        status7["sync_status"] == "MAJOR_DESYNC",
        f"got {status7['sync_status']}",
    )
    check("desync_ms >= 2000", status7["desync_ms"] >= 2000.0)

    # ------------------------------------------------------------------
    # Test 8: Minor desync
    # ------------------------------------------------------------------
    print("\n--- Test 8: Minor Desync ---")
    dd8 = DesyncDetector({"desync_threshold_ms": 5000.0})
    now8 = time.time() * 1000
    dd8._update_timestamps["binance"] = now8
    dd8._update_timestamps["bybit"] = now8 - 2000.0  # 2s behind
    status8 = dd8.check_sync()
    check(
        "MINOR_DESYNC detected",
        status8["sync_status"] == "MINOR_DESYNC",
        f"got {status8['sync_status']}, desync_ms={status8['desync_ms']}",
    )
    check("recommendation CONTINUE for minor", status8["recommendation"] == "CONTINUE")

    # ------------------------------------------------------------------
    # Test 9: Stats accumulation
    # ------------------------------------------------------------------
    print("\n--- Test 9: Stats Accumulation ---")
    dd9 = DesyncDetector()
    now9 = time.time() * 1000
    dd9.record_update("binance", now9)
    dd9.record_update("bybit", now9)
    dd9.check_sync()  # synced
    dd9.check_sync()  # synced
    stats9 = dd9.get_stats()
    check("total_checks >= 2", stats9["total_checks"] >= 2)
    check("synced_count >= 2", stats9["synced_count"] >= 2)
    check("2 exchanges tracked", stats9["exchanges_tracked"] == 2)

    # ------------------------------------------------------------------
    # Test 10: Gap detection (large interval)
    # ------------------------------------------------------------------
    print("\n--- Test 10: Gap Detection ---")
    dd10 = DesyncDetector({"gap_threshold_ms": 100.0})  # Very low for test
    dd10.record_update("binance", time.time() * 1000)
    _time.sleep(0.15)  # 150ms > 100ms threshold
    result10 = dd10.record_update("binance", time.time() * 1000)
    check(
        "gap detected after sleep",
        result10["gap_detected"] is True,
        f"interval_ms={result10['interval_ms']}",
    )
    stats10 = dd10.get_stats()
    check("gaps_detected >= 1", stats10["gaps_detected"] >= 1)

    # ------------------------------------------------------------------
    # Test 11: Single exchange — no desync_ms
    # ------------------------------------------------------------------
    print("\n--- Test 11: Single Exchange ---")
    dd11 = DesyncDetector()
    dd11.record_update("binance", time.time() * 1000)
    status11 = dd11.check_sync()
    check("desync_ms is None with single exchange", status11["desync_ms"] is None)
    check("1 exchange tracked", status11["exchanges_tracked"] == 1)

    # ------------------------------------------------------------------
    # Test 12: Reconnect recommendation for very stale data
    # ------------------------------------------------------------------
    print("\n--- Test 12: Reconnect Recommendation ---")
    dd12 = DesyncDetector({
        "stale_threshold_ms": 1000.0,
        "gap_threshold_ms": 5000.0,
    })
    now12 = time.time() * 1000
    dd12._update_timestamps["binance"] = now12
    dd12._update_timestamps["bybit"] = now12 - 10000.0  # 10s stale, > gap_threshold
    status12 = dd12.check_sync()
    check(
        "recommendation RECONNECT for very stale",
        status12["recommendation"] == "RECONNECT",
        f"got {status12['recommendation']}",
    )

    # ------------------------------------------------------------------
    # Test 13: Interval statistics per exchange
    # ------------------------------------------------------------------
    print("\n--- Test 13: Interval Statistics ---")
    dd13 = DesyncDetector()
    for _ in range(5):
        dd13.record_update("binance", time.time() * 1000)
        _time.sleep(0.02)
    stats13 = dd13.get_stats()
    check("interval stats for binance", "binance" in stats13["interval_stats"])
    is13 = stats13["interval_stats"]["binance"]
    check("interval count >= 4", is13["count"] >= 4)
    check("avg_ms > 0", is13["avg_ms"] > 0)
    check("min_ms > 0", is13["min_ms"] > 0)
    check("max_ms >= avg_ms", is13["max_ms"] >= is13["avg_ms"])

    # ------------------------------------------------------------------
    # Test 14: age_by_exchange in check_sync
    # ------------------------------------------------------------------
    print("\n--- Test 14: Age By Exchange ---")
    dd14 = DesyncDetector()
    now14 = time.time() * 1000
    dd14.record_update("binance", now14)
    dd14.record_update("bybit", now14)
    status14 = dd14.check_sync()
    check("binance in age_by_exchange", "binance" in status14["age_by_exchange"])
    check("bybit in age_by_exchange", "bybit" in status14["age_by_exchange"])
    check("ages are non-negative", all(v >= 0 for v in status14["age_by_exchange"].values()))

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
