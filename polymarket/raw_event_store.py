"""
SENECIO — Immutable raw event store and deterministic H-011 replay.

Stores every API response (trade data) in compressed append-only JSONL.gz
files for full reproducibility. Two replays of the same file MUST produce
identical output and SHA-256.

Storage path: polymarket/results/raw/YYYY-MM-DD.events.jsonl.gz

Each record schema:
  {
    "received_at_utc": "ISO-8601",
    "source": "polymarket_data_api",
    "endpoint": "/trades",
    "request_params": {},
    "requested_condition_id": "str",
    "payload": {},
    "payload_sha256": "str",
    "cohort_id": "str",
    "schema_version": "raw_trade_event_v1"
  }
"""
from __future__ import annotations

import gzip
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.validation_semantics import classify_window_cohort

RAW_DIR = Path(__file__).parent / "results" / "raw"


def append_raw_event(
    path: Path,
    event: dict[str, Any],
) -> None:
    """Append a raw event to a gzipped JSONL file (atomic line write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


def create_raw_event(
    condition_id: str,
    payload: list[dict] | dict,
    request_params: dict | None = None,
    window_s: int = 300,
    endpoint: str = "/trades",
) -> dict[str, Any]:
    """Create a raw event record from an API response."""
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    return {
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "polymarket_data_api",
        "endpoint": endpoint,
        "request_params": request_params or {},
        "requested_condition_id": condition_id,
        "payload": payload,
        "payload_sha256": payload_hash,
        "cohort_id": classify_window_cohort(window_s),
        "schema_version": "raw_trade_event_v1",
    }


def save_raw_events(
    condition_id: str,
    trades: list[dict],
    request_params: dict | None = None,
    window_s: int = 300,
) -> Path:
    """Save raw trades for a market to the daily gzip file."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = RAW_DIR / f"{date_str}.events.jsonl.gz"

    event = create_raw_event(
        condition_id=condition_id,
        payload=trades,
        request_params=request_params,
        window_s=window_s,
    )
    append_raw_event(path, event)
    return path


def load_raw_events(path: Path) -> list[dict]:
    """Load all raw events from a gzipped JSONL file."""
    events = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def replay_file(
    path: Path,
    window_s: int = 300,
) -> dict:
    """
    Deterministic replay of raw events.

    Two calls with the same input file MUST produce identical output.
    Returns a dict with:
      - total_events: int
      - total_trades: int
      - markets_processed: int
      - output_sha256: str (hash of the canonical output)
    """
    events = load_raw_events(path)
    events.sort(key=lambda e: e.get("received_at_utc", ""))

    total_trades = 0
    markets_processed = 0
    market_summaries = []

    for event in events:
        payload = event.get("payload", [])
        if isinstance(payload, list):
            total_trades += len(payload)
            markets_processed += 1
            cid = event.get("requested_condition_id", "")
            market_summaries.append({
                "condition_id": cid,
                "trade_count": len(payload),
                "payload_sha256": event.get("payload_sha256", ""),
            })

    # Canonical output (sorted, compact) for deterministic hash
    canonical = json.dumps(
        {
            "total_events": len(events),
            "total_trades": total_trades,
            "markets_processed": markets_processed,
            "market_summaries": sorted(market_summaries, key=lambda m: m["condition_id"]),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    output_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {
        "total_events": len(events),
        "total_trades": total_trades,
        "markets_processed": markets_processed,
        "market_summaries": sorted(market_summaries, key=lambda m: m["condition_id"]),
        "output_sha256": output_hash,
    }
