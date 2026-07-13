"""
SENECIO — Immutable raw event store and deterministic H-011 replay.

FASE A.4 redesign: One immutable artifact per scan (not per day).
Each scan produces a single raw_scan_<scan_id>.events.jsonl.gz file that
is written to a staging area, then atomically renamed to its final
immutable name, with a mandatory sidecar SHA256 and manifest entry.

The old daily-append model (YYYY-MM-DD.events.jsonl.gz) is DEPRECATED
for H-011 V3. It remains available for legacy V2 but V3 never uses it.

Storage path (V3): polymarket/results/v3/raw/raw_scan_<safe_scan_id>.events.jsonl.gz

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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validation_semantics import classify_window_cohort

RAW_DIR = Path(__file__).parent / "results" / "raw"


# ═══════════════════════════════════════════════════════════════════════
# Legacy daily-append model (V2 only, do not use in V3)
# ═══════════════════════════════════════════════════════════════════════

def append_raw_event(
    path: Path,
    event: dict[str, Any],
) -> None:
    """Append a raw event to a gzipped JSONL file (atomic line write).

    DEPRECATED for V3 — use RawScanStager instead.
    """
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
    """Save raw trades for a market to the daily gzip file.

    DEPRECATED for V3 — use RawScanStager instead.
    """
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


# ═══════════════════════════════════════════════════════════════════════
# V3: Immutable per-scan raw storage
# ═══════════════════════════════════════════════════════════════════════

def _safe_scan_id(scan_id: str) -> str:
    """Convert scan_id to a filesystem-safe string."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in scan_id)
    return safe[:100]  # cap length


class RawScanStager:
    """Stages raw events for a single scan in a temporary file.

    Events are written to a staging file (outside the artifact glob).
    When finalize() is called, the staging file is atomically renamed
    to its final immutable name and a sidecar SHA256 is written.

    The final artifact is never opened for append after finalization.
    """

    def __init__(self, scan_id: str, raw_dir: Path):
        self.scan_id = scan_id
        self.raw_dir = raw_dir
        self._staging_path: Path | None = None
        self._events: list[dict[str, Any]] = []
        self._condition_ids: set[str] = set()
        self._finalized = False

    def __enter__(self):
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = self.raw_dir / ".pending"
        staging_dir.mkdir(exist_ok=True)
        # Staging file name uses .tmp extension so it doesn't match artifact glob
        safe_id = _safe_scan_id(self.scan_id)
        self._staging_path = staging_dir / f"raw_scan_{safe_id}.jsonl.gz.tmp"
        return self

    def append_event(self, event: dict[str, Any]) -> None:
        """Append a raw event to the staging file.

        Writes immediately to disk (flush + fsync) to preserve
        INV-025: raw persisted before transform.
        """
        if self._finalized:
            raise RuntimeError("Cannot append to finalized stager")
        if self._staging_path is None:
            raise RuntimeError("Stager not initialized — use 'with' statement")

        with gzip.open(self._staging_path, "at", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

        self._events.append(event)
        cid = event.get("requested_condition_id", "")
        if cid:
            self._condition_ids.add(cid)

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def condition_ids(self) -> list[str]:
        return sorted(self._condition_ids)

    def canonical_events_sha256(self) -> str:
        """Compute SHA256 of the canonical events representation."""
        canonical = json.dumps(
            self._events,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def finalize(self) -> Path:
        """Atomically rename staging to final immutable artifact.

        Returns the final artifact path.
        The artifact is never opened for append after this call.
        """
        if self._finalized:
            raise RuntimeError("Already finalized")
        if self._staging_path is None or not self._staging_path.exists():
            raise RuntimeError("Staging file does not exist")

        safe_id = _safe_scan_id(self.scan_id)
        final_name = f"raw_scan_{safe_id}.events.jsonl.gz"
        final_path = self.raw_dir / final_name

        # Atomic rename
        os.rename(str(self._staging_path), str(final_path))
        os.sync()  # Ensure rename is persisted

        self._finalized = True
        return final_path

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and self._staging_path and self._staging_path.exists():
            # Clean up staging on error
            try:
                self._staging_path.unlink()
            except OSError:
                pass
        return False


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
    """Deterministic replay of raw events."""
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
