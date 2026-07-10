"""
SENECIO H-011 V3 — Immutable scan state snapshot.

Single source of truth consumed by dashboard, API, replay, and monitor.
Historical snapshots are append-only. latest.json can be replaced atomically.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScanStateSnapshot:
    """Immutable snapshot of a complete scan state."""
    schema_version: str
    scan_id: str
    run_id: str
    generated_at: str
    pipeline_version: str
    cohort_id: str
    window_s: int
    estimator: str
    code_sha: str
    config_sha: str
    paper_only: bool
    live_capital_locked: bool
    orders_enabled: bool
    scan_status: str
    source_health: dict
    funnel: dict
    market_records: tuple[dict, ...]
    lifecycle: dict
    invariants: dict
    drift: dict
    alerts: tuple[dict, ...]
    aggregate_metrics: dict
    snapshot_hash: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "scan_id": self.scan_id,
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "pipeline_version": self.pipeline_version,
            "cohort_id": self.cohort_id,
            "window_s": self.window_s,
            "estimator": self.estimator,
            "code_sha": self.code_sha,
            "config_sha": self.config_sha,
            "paper_only": self.paper_only,
            "live_capital_locked": self.live_capital_locked,
            "orders_enabled": self.orders_enabled,
            "scan_status": self.scan_status,
            "source_health": self.source_health,
            "funnel": self.funnel,
            "market_records": list(self.market_records),
            "lifecycle": self.lifecycle,
            "invariants": self.invariants,
            "drift": self.drift,
            "alerts": list(self.alerts),
            "aggregate_metrics": self.aggregate_metrics,
            "snapshot_hash": self.snapshot_hash,
        }


def build_snapshot(
    *,
    scan_id: str,
    run_id: str,
    pipeline_version: str,
    cohort_id: str,
    window_s: int,
    estimator: str,
    code_sha: str,
    config_sha: str,
    scan_status: str,
    source_health: dict,
    funnel: dict,
    market_records: list[dict],
    lifecycle: dict | None = None,
    invariants: dict | None = None,
    drift: dict | None = None,
    alerts: list[dict] | None = None,
    aggregate_metrics: dict | None = None,
) -> ScanStateSnapshot:
    """Build a snapshot with auto-computed hash."""
    generated_at = datetime.now(timezone.utc).isoformat()

    # Build hash from everything except snapshot_hash
    hash_input = json.dumps({
        "schema_version": "h011-v3-snapshot-v1",
        "scan_id": scan_id,
        "run_id": run_id,
        "generated_at": generated_at,
        "pipeline_version": pipeline_version,
        "cohort_id": cohort_id,
        "window_s": window_s,
        "estimator": estimator,
        "code_sha": code_sha,
        "config_sha": config_sha,
        "paper_only": True,
        "live_capital_locked": True,
        "orders_enabled": False,
        "scan_status": scan_status,
        "source_health": source_health,
        "funnel": funnel,
        "market_records": market_records,
        "lifecycle": lifecycle or {},
        "invariants": invariants or {},
        "drift": drift or {},
        "alerts": alerts or [],
        "aggregate_metrics": aggregate_metrics or {},
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    return ScanStateSnapshot(
        schema_version="h011-v3-snapshot-v1",
        scan_id=scan_id,
        run_id=run_id,
        generated_at=generated_at,
        pipeline_version=pipeline_version,
        cohort_id=cohort_id,
        window_s=window_s,
        estimator=estimator,
        code_sha=code_sha,
        config_sha=config_sha,
        paper_only=True,
        live_capital_locked=True,
        orders_enabled=False,
        scan_status=scan_status,
        source_health=source_health,
        funnel=funnel,
        market_records=tuple(market_records),
        lifecycle=lifecycle or {},
        invariants=invariants or {},
        drift=drift or {},
        alerts=tuple(alerts or []),
        aggregate_metrics=aggregate_metrics or {},
        snapshot_hash=snapshot_hash,
    )


SNAPSHOT_DIR = Path(__file__).parent.parent / "results" / "v3" / "state"


def save_snapshot(snapshot: ScanStateSnapshot) -> Path:
    """Save snapshot as append-only historical + atomic latest.json."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Historical: append-only
    hist_path = SNAPSHOT_DIR / f"state_{snapshot.generated_at.replace(':', '')}_{snapshot.scan_id[:8]}.json"
    hist_path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    # Latest: atomic replace
    latest_path = SNAPSHOT_DIR / "latest.json"
    tmp_path = SNAPSHOT_DIR / "latest.json.tmp"
    tmp_path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.rename(latest_path)

    return hist_path


def load_latest_snapshot() -> dict | None:
    """Load latest.json or return None if not found."""
    latest = SNAPSHOT_DIR / "latest.json"
    if not latest.exists():
        return None
    return json.loads(latest.read_text(encoding="utf-8"))
