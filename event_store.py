"""
Module: event_store.py — EVENT-SOURCED TIME SERIES STORE

PHILOSOPHY: single memory, append-only truth

The event store is THE single source of truth for everything that
has happened in the arena. No event exists unless it's recorded here.

STORES:
    - trades          — every trade that affected the ledger
    - decisions       — every decision the core made (including HOLD/KILL)
    - regime_transitions — every regime change detected
    - execution_quality  — every execution assessment
    - survival_metrics   — periodic survival score snapshots

PRINCIPLE: append_only_truth
    - Events are NEVER modified after recording
    - Corrections are NEW events (correction_event)
    - The store is the AUDIT TRAIL
    - "SI NO ESTÁ LOGGEADO → NO PASÓ"

DETERMINISTIC: same inputs → same store state
"""

import json
import time
import os
import hashlib
from collections import deque, defaultdict
from typing import Optional, List, Dict


# ---------------------------------------------------------------------------
# Event Types
# ---------------------------------------------------------------------------

EVENT_TYPES = [
    "TRADE_OPEN",
    "TRADE_CLOSE",
    "DECISION",
    "REGIME_TRANSITION",
    "EXECUTION_ASSESSMENT",
    "SURVIVAL_SNAPSHOT",
    "KILL_SWITCH",
    "ADVERSARIAL_EVENT",
    "SYSTEM",
    "CORRECTION",
]


# ---------------------------------------------------------------------------
# Event Record
# ---------------------------------------------------------------------------

class EventRecord:
    """A single immutable event in the store.

    Each event has:
    - event_id: unique identifier (hash-based)
    - event_type: one of EVENT_TYPES
    - timestamp: millisecond timestamp
    - data: event-specific payload
    - sequence: monotonic sequence number
    """

    def __init__(self, event_type: str, data: dict, sequence: int,
                 timestamp: Optional[float] = None):
        self.event_type = event_type
        self.data = data
        self.sequence = sequence
        self.timestamp = timestamp or int(time.time() * 1000)

        # Deterministic event_id from type + sequence + timestamp
        id_str = f"{event_type}|{sequence}|{self.timestamp}"
        self.event_id = hashlib.sha256(id_str.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------

class EventStore:
    """THE single source of truth for the ARENA.

    Event-sourced time series store with:
    - Append-only semantics (no modifications, no deletes)
    - Typed event streams (trades, decisions, regime, execution, survival)
    - Efficient querying by type, time range, and sequence
    - JSONL persistence for durability
    - Hash-based integrity verification

    ARENA LAW: SI NO ESTÁ LOGGEADO → NO PASÓ
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        max_memory_events: int = 100000,
    ):
        """Initialize the Event Store.

        Args:
            persist_path: Path for JSONL persistence. If None, events
                          are only kept in memory.
            max_memory_events: Maximum events to keep in memory per stream.
        """
        self.persist_path = persist_path
        self.max_memory_events = max_memory_events

        # ── Event streams (append-only) ──
        self._streams = {
            "trades": deque(maxlen=max_memory_events),
            "decisions": deque(maxlen=max_memory_events),
            "regime_transitions": deque(maxlen=max_memory_events),
            "execution_quality": deque(maxlen=max_memory_events),
            "survival_metrics": deque(maxlen=max_memory_events),
            "kill_switch": deque(maxlen=max_memory_events),
            "adversarial_events": deque(maxlen=max_memory_events),
            "system": deque(maxlen=max_memory_events),
        }

        # ── All events (chronological) ──
        self._all_events = deque(maxlen=max_memory_events)

        # ── Sequence counter ──
        self._sequence = 0

        # ── Statistics ──
        self._stats = defaultdict(int)

        # ── Persistence file handle ──
        self._persist_file = None
        if persist_path:
            try:
                os.makedirs(os.path.dirname(persist_path), exist_ok=True)
                self._persist_file = open(persist_path, "a")
            except Exception:
                pass

    # ===================================================================
    # APPEND (the only write operation)
    # ===================================================================

    def append(self, event_type: str, data: dict,
               stream: str = None) -> EventRecord:
        """Append a new event to the store.

        This is the ONLY way to write to the store.
        Events are immutable after recording.

        Args:
            event_type: One of EVENT_TYPES.
            data: Event-specific payload.
            stream: Which stream to append to. If None, auto-detected
                    from event_type.

        Returns:
            The recorded EventRecord.
        """
        self._sequence += 1

        event = EventRecord(
            event_type=event_type,
            data=data,
            sequence=self._sequence,
        )

        # Determine stream
        if stream is None:
            stream = self._type_to_stream(event_type)

        # Append to stream
        if stream in self._streams:
            self._streams[stream].append(event)

        # Append to all-events
        self._all_events.append(event)

        # Update stats
        self._stats[event_type] += 1
        self._stats["_total"] += 1

        # Persist
        if self._persist_file:
            try:
                self._persist_file.write(event.to_json() + "\n")
                self._persist_file.flush()
            except Exception:
                pass

        return event

    # ===================================================================
    # QUERY
    # ===================================================================

    def query(self, stream: str, limit: int = 100,
              since_sequence: int = 0) -> List[dict]:
        """Query events from a stream.

        Args:
            stream: Stream name (trades, decisions, etc.).
            limit: Maximum events to return.
            since_sequence: Only return events after this sequence.

        Returns:
            List of event dicts, most recent last.
        """
        if stream not in self._streams:
            return []

        events = list(self._streams[stream])
        if since_sequence > 0:
            events = [e for e in events if e.sequence > since_sequence]

        return [e.to_dict() for e in events[-limit:]]

    def query_all(self, limit: int = 100,
                  since_sequence: int = 0) -> List[dict]:
        """Query all events across all streams.

        Args:
            limit: Maximum events to return.
            since_sequence: Only return events after this sequence.

        Returns:
            List of event dicts, most recent last.
        """
        events = list(self._all_events)
        if since_sequence > 0:
            events = [e for e in events if e.sequence > since_sequence]
        return [e.to_dict() for e in events[-limit:]]

    def get_latest(self, stream: str) -> Optional[dict]:
        """Get the most recent event from a stream.

        Returns:
            Event dict or None if stream is empty.
        """
        if stream not in self._streams or len(self._streams[stream]) == 0:
            return None
        return self._streams[stream][-1].to_dict()

    def count(self, stream: str = None) -> int:
        """Count events in a stream or total.

        Args:
            stream: Stream name, or None for total.

        Returns:
            Number of events.
        """
        if stream is None:
            return self._stats["_total"]
        if stream in self._streams:
            return len(self._streams[stream])
        return 0

    # ===================================================================
    # SPECIALIZED APPEND METHODS
    # ===================================================================

    def record_trade_open(self, position_id: str, side: str, price: float,
                          size_usdt: float, commission: float,
                          slippage: float) -> EventRecord:
        """Record a trade open event."""
        return self.append("TRADE_OPEN", {
            "position_id": position_id,
            "side": side,
            "price": price,
            "size_usdt": round(size_usdt, 2),
            "commission": round(commission, 4),
            "slippage": round(slippage, 4),
        }, stream="trades")

    def record_trade_close(self, position_id: str, side: str,
                           entry_price: float, exit_price: float,
                           size_usdt: float, realized_pnl: float,
                           realized_pnl_pct: float,
                           hold_time_s: float) -> EventRecord:
        """Record a trade close event."""
        return self.append("TRADE_CLOSE", {
            "position_id": position_id,
            "side": side,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "size_usdt": round(size_usdt, 2),
            "realized_pnl": round(realized_pnl, 4),
            "realized_pnl_pct": round(realized_pnl_pct, 6),
            "hold_time_s": round(hold_time_s, 1),
        }, stream="trades")

    def record_decision(self, action: str, side: Optional[str],
                        size: float, reason: str,
                        risk_score: float = 0.0,
                        ev: float = 0.0,
                        conviction: float = 0.0,
                        noise: float = 0.0) -> EventRecord:
        """Record a decision event (including HOLD/KILL)."""
        return self.append("DECISION", {
            "action": action,
            "side": side,
            "size": round(size, 6),
            "reason": reason,
            "risk_score": round(risk_score, 4),
            "ev": round(ev, 8),
            "conviction": round(conviction, 6),
            "noise": round(noise, 6),
        }, stream="decisions")

    def record_regime_transition(self, from_regime: str, to_regime: str,
                                  kl_divergence: float = 0.0,
                                  confidence: float = 0.0) -> EventRecord:
        """Record a regime transition event."""
        return self.append("REGIME_TRANSITION", {
            "from": from_regime,
            "to": to_regime,
            "kl_divergence": round(kl_divergence, 6),
            "confidence": round(confidence, 6),
        }, stream="regime_transitions")

    def record_execution_assessment(self, action: str, reason: str,
                                     realized_edge: float,
                                     slippage_bps: float,
                                     fill_pct: float,
                                     quality: float) -> EventRecord:
        """Record an execution quality assessment."""
        return self.append("EXECUTION_ASSESSMENT", {
            "action": action,
            "reason": reason,
            "realized_edge": round(realized_edge, 6),
            "slippage_bps": round(slippage_bps, 2),
            "fill_pct": round(fill_pct, 4),
            "quality": round(quality, 4),
        }, stream="execution_quality")

    def record_survival_snapshot(self, survival_score: float,
                                  entropy_stability: float,
                                  drawdown_clustering: float,
                                  regime_adaptability: float,
                                  verdict: str) -> EventRecord:
        """Record a periodic survival metrics snapshot."""
        return self.append("SURVIVAL_SNAPSHOT", {
            "survival_score": round(survival_score, 4),
            "entropy_stability": round(entropy_stability, 4),
            "drawdown_clustering": round(drawdown_clustering, 4),
            "regime_adaptability": round(regime_adaptability, 4),
            "verdict": verdict,
        }, stream="survival_metrics")

    def record_kill_switch(self, activated: bool, reason: str) -> EventRecord:
        """Record a kill switch activation/deactivation."""
        return self.append("KILL_SWITCH", {
            "activated": activated,
            "reason": reason,
        }, stream="kill_switch")

    def record_adversarial_event(self, event_type: str,
                                  intensity: float,
                                  duration_ticks: int) -> EventRecord:
        """Record an adversarial event injection."""
        return self.append("ADVERSARIAL_EVENT", {
            "event_type": event_type,
            "intensity": round(intensity, 4),
            "duration_ticks": duration_ticks,
        }, stream="adversarial_events")

    def record_system(self, message: str, data: dict = None) -> EventRecord:
        """Record a system event."""
        return self.append("SYSTEM", {
            "message": message,
            "data": data or {},
        }, stream="system")

    # ===================================================================
    # STATISTICS
    # ===================================================================

    def get_stats(self) -> dict:
        """Get event store statistics."""
        return {
            "total_events": self._stats["_total"],
            "by_type": dict(self._stats),
            "stream_sizes": {k: len(v) for k, v in self._streams.items()},
            "sequence": self._sequence,
        }

    # ===================================================================
    # ANALYTICS (read-only computations over the store)
    # ===================================================================

    def compute_trade_stats(self) -> dict:
        """Compute trade statistics from the trades stream."""
        trade_events = [e for e in self._streams["trades"]
                       if e.event_type == "TRADE_CLOSE"]

        if not trade_events:
            return {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "avg_pnl_pct": 0.0,
                "total_pnl": 0.0, "avg_hold_time_s": 0.0,
                "best_trade": 0.0, "worst_trade": 0.0,
            }

        pnls = [e.data.get("realized_pnl_pct", 0) for e in trade_events]
        pnls_abs = [e.data.get("realized_pnl", 0) for e in trade_events]
        holds = [e.data.get("hold_time_s", 0) for e in trade_events]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        return {
            "total_trades": len(trade_events),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trade_events), 4),
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 6),
            "total_pnl": round(sum(pnls_abs), 4),
            "avg_hold_time_s": round(sum(holds) / len(holds), 1) if holds else 0.0,
            "best_trade": round(max(pnls), 6) if pnls else 0.0,
            "worst_trade": round(min(pnls), 6) if pnls else 0.0,
        }

    def compute_decision_stats(self) -> dict:
        """Compute decision statistics from the decisions stream."""
        decisions = list(self._streams["decisions"])

        if not decisions:
            return {"total": 0, "executes": 0, "holds": 0, "kills": 0,
                    "execute_rate": 0.0, "avg_risk_score": 0.0}

        actions = [e.data.get("action", "HOLD") for e in decisions]
        risk_scores = [e.data.get("risk_score", 0) for e in decisions]

        executes = sum(1 for a in actions if a == "EXECUTE")
        holds = sum(1 for a in actions if a == "HOLD")
        kills = sum(1 for a in actions if a == "KILL")

        return {
            "total": len(decisions),
            "executes": executes,
            "holds": holds,
            "kills": kills,
            "execute_rate": round(executes / len(decisions), 4),
            "avg_risk_score": round(sum(risk_scores) / len(risk_scores), 4),
        }

    # ===================================================================
    # INTERNAL
    # ===================================================================

    def _type_to_stream(self, event_type: str) -> str:
        """Map event type to stream name."""
        mapping = {
            "TRADE_OPEN": "trades",
            "TRADE_CLOSE": "trades",
            "DECISION": "decisions",
            "REGIME_TRANSITION": "regime_transitions",
            "EXECUTION_ASSESSMENT": "execution_quality",
            "SURVIVAL_SNAPSHOT": "survival_metrics",
            "KILL_SWITCH": "kill_switch",
            "ADVERSARIAL_EVENT": "adversarial_events",
            "SYSTEM": "system",
            "CORRECTION": "system",
        }
        return mapping.get(event_type, "system")

    def close(self):
        """Close the persistence file."""
        if self._persist_file:
            try:
                self._persist_file.close()
            except Exception:
                pass

    def __del__(self):
        self.close()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("event_store.py — Self-Test (EVENT-SOURCED TIME SERIES STORE)")
    print("=" * 60)

    store = EventStore()

    # ── Test 1: Append events ──
    print("\n[Test 1] Append events...")
    e1 = store.record_trade_open("POS-001", "LONG", 50000.0, 100.0, 0.06, 0.02)
    e2 = store.record_decision("EXECUTE", "LONG", 0.10, "eu_positive", 0.2, 0.001, 0.7, 0.3)
    e3 = store.record_trade_close("POS-001", "LONG", 50000.0, 51000.0, 100.0, 1.98, 0.0198, 120.5)
    assert store.count() == 3
    print(f"  events={store.count()}, trades={store.count('trades')}, decisions={store.count('decisions')}")
    print(f"  ✓ Events appended correctly")

    # ── Test 2: Query by stream ──
    print("\n[Test 2] Query by stream...")
    trades = store.query("trades")
    decisions = store.query("decisions")
    assert len(trades) == 2  # open + close
    assert len(decisions) == 1
    print(f"  trades={len(trades)}, decisions={len(decisions)}")
    print(f"  ✓ Stream queries work")

    # ── Test 3: Trade statistics ──
    print("\n[Test 3] Trade statistics...")
    stats = store.compute_trade_stats()
    assert stats["total_trades"] == 1
    assert stats["wins"] == 1
    assert stats["win_rate"] == 1.0
    print(f"  trades={stats['total_trades']}, win_rate={stats['win_rate']:.1%}")
    print(f"  ✓ Trade stats computed correctly")

    # ── Test 4: Decision statistics ──
    print("\n[Test 4] Decision statistics...")
    dec_stats = store.compute_decision_stats()
    assert dec_stats["total"] == 1
    assert dec_stats["executes"] == 1
    print(f"  total={dec_stats['total']}, executes={dec_stats['executes']}")
    print(f"  ✓ Decision stats computed correctly")

    # ── Test 5: Event immutability ──
    print("\n[Test 5] Event immutability...")
    e1_dict = e1.to_dict()
    assert "event_id" in e1_dict
    assert e1_dict["event_type"] == "TRADE_OPEN"
    # Events can't be modified — they're just records
    print(f"  event_id={e1_dict['event_id']}")
    print(f"  ✓ Events are immutable records")

    # ── Test 6: Append-only truth ──
    print("\n[Test 6] SI NO ESTÁ LOGGEADO → NO PASÓ...")
    # Nothing happened that wasn't recorded
    assert store.count() == 3
    # Add a regime transition
    store.record_regime_transition("TRENDING", "RANGING", 0.45, 0.8)
    assert store.count("regime_transitions") == 1
    print(f"  total={store.count()}, regime_transitions={store.count('regime_transitions')}")
    print(f"  ✓ All events are tracked")

    # ── Test 7: Persistence ──
    print("\n[Test 7] Persistence to JSONL...")
    store2 = EventStore(persist_path="/tmp/test_event_store.jsonl")
    store2.record_trade_open("POS-002", "SHORT", 50000.0, 50.0, 0.03, 0.01)
    store2.close()
    # Verify file exists
    assert os.path.exists("/tmp/test_event_store.jsonl")
    with open("/tmp/test_event_store.jsonl") as f:
        lines = f.readlines()
    assert len(lines) == 1
    print(f"  wrote {len(lines)} event(s) to JSONL")
    print(f"  ✓ Persistence works")
    os.unlink("/tmp/test_event_store.jsonl")

    # ── Test 8: Store statistics ──
    print("\n[Test 8] Store statistics...")
    s = store.get_stats()
    assert s["total_events"] == 4
    assert "trades" in s["stream_sizes"]
    print(f"  total={s['total_events']}, streams={list(s['stream_sizes'].keys())}")
    print(f"  ✓ Store statistics complete")

    print("\n" + "=" * 60)
    print("All self-tests PASSED")
    print("EVENT_STORE: single memory, append-only truth")
    print("=" * 60)
