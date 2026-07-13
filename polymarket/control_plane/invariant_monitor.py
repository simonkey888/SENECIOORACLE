"""
SENECIO H-011 V3 — Invariant monitor (legacy compatibility shim).

This module previously contained its own independent catalog of 31 invariants.
As of h011-v3-invariants-v2, the SINGLE SOURCE OF TRUTH is
control_plane.coverage. This file re-exports from coverage.py for backward
compatibility with any code that still imports from invariant_monitor.

Do NOT add new invariant definitions here. All definitions live in coverage.py.
"""
from __future__ import annotations

from control_plane.coverage import (
    INVARIANT_CATALOG,
    CATALOG_VERSION,
    invariant_catalog_hash,
    invariant_summary,
    evaluate_all_invariants,
    ScanContext,
)

# Re-export for backward compatibility
# Format: list of (id, description, severity) — matching the old format
INVARIANTS = [(inv_id, desc, sev) for inv_id, desc, sev, _ in INVARIANT_CATALOG]

# Old InvariantResult class — replaced by dict in coverage.py
# but we provide a thin wrapper for any code that still references it
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InvariantResult:
    """Legacy compatibility — prefer dict results from coverage.evaluate_all_invariants."""
    invariant_id: str
    status: str
    severity: str
    reason: str
    evidence_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "evidence_hashes": list(self.evidence_hashes),
        }


def check_invariants(scan_data: dict) -> list[InvariantResult]:
    """Legacy compatibility — use coverage.evaluate_all_invariants instead.

    This function converts the old-style scan_data dict into a ScanContext
    and delegates to coverage.evaluate_all_invariants. Results are wrapped
    in InvariantResult for backward compatibility.
    """
    # This is a best-effort conversion — most callers should migrate to
    # using ScanContext directly.
    results = evaluate_all_invariants(
        ScanContext(
            run_id=scan_data.get("run_id", ""),
            scan_id=scan_data.get("scan_id", ""),
            pipeline_version=scan_data.get("pipeline_version", "h011-integrity-v3"),
            window_s=scan_data.get("window_s", 300),
            paper_only=scan_data.get("paper_only", True),
            live_capital_locked=scan_data.get("live_capital_locked", True),
            orders_enabled=scan_data.get("orders_enabled", False),
            funnel=scan_data.get("funnel", {}),
            market_records=scan_data.get("market_records", []),
            records=[],
            source_health=scan_data.get("source_health", {}),
        )
    )
    # Wrap in InvariantResult for backward compat
    return [
        InvariantResult(
            invariant_id=r["invariant_id"],
            status=r["status"],
            severity=r["severity"],
            reason=r["reason"],
            evidence_hashes=tuple(),
        )
        for r in results
    ]
