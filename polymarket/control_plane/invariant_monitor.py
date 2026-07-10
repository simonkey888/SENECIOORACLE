"""
SENECIO H-011 V3 — Invariant monitor.

31 invariants. Never present "0 failures" if invariants were not run.
Use UNKNOWN / NOT_RUN instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InvariantResult:
    invariant_id: str
    status: str  # PASS | FAIL | NOT_APPLICABLE | UNKNOWN
    severity: str  # INFO | WARNING | CRITICAL | BLOCKING
    reason: str
    evidence_hashes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "invariant_id": self.invariant_id,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "evidence_hashes": list(self.evidence_hashes),
        }


# All 31 invariants
INVARIANTS = [
    ("INV-001", "run_id unique", "CRITICAL"),
    ("INV-002", "scan_id unique", "CRITICAL"),
    ("INV-003", "prediction_id unique", "CRITICAL"),
    ("INV-004", "lifecycle event_id unique", "CRITICAL"),
    ("INV-005", "raw events append-only", "BLOCKING"),
    ("INV-006", "historical snapshots append-only", "BLOCKING"),
    ("INV-007", "no hidden rejected records", "WARNING"),
    ("INV-008", "UNKNOWN not collapsed to 0", "BLOCKING"),
    ("INV-009", "UNKNOWN not collapsed to False", "BLOCKING"),
    ("INV-010", "n=0 produces no numeric metric", "BLOCKING"),
    ("INV-011", "conditionId not used as token_id", "BLOCKING"),
    ("INV-012", "token leg_0 != token leg_1", "BLOCKING"),
    ("INV-013", "both tokens belong to MarketTruthContract", "BLOCKING"),
    ("INV-014", "V3 never accepts [ACTIVE] stub", "BLOCKING"),
    ("INV-015", "V3 never writes legacy ledger", "BLOCKING"),
    ("INV-016", "V3 no fallback to V2", "BLOCKING"),
    ("INV-017", "W=300 for confirmatory cohort", "BLOCKING"),
    ("INV-018", "W=3600 always legacy", "BLOCKING"),
    ("INV-019", "realized_pnl null without real fills", "BLOCKING"),
    ("INV-020", "balance/NAV absent in H-011 V3", "BLOCKING"),
    ("INV-021", "shadow executable requires two books", "BLOCKING"),
    ("INV-022", "shadow executable requires equal fillable", "BLOCKING"),
    ("INV-023", "shadow executable requires known fee", "BLOCKING"),
    ("INV-024", "shadow executable requires net_edge > 0", "BLOCKING"),
    ("INV-025", "raw payload persisted before transform", "BLOCKING"),
    ("INV-026", "snapshot_hash verifiable", "WARNING"),
    ("INV-027", "lifecycle hash chain valid", "WARNING"),
    ("INV-028", "dashboard and API use same snapshot_hash", "WARNING"),
    ("INV-029", "paper_only = true", "BLOCKING"),
    ("INV-030", "live_capital_locked = true", "BLOCKING"),
    ("INV-031", "orders_enabled = false", "BLOCKING"),
]


def check_invariants(scan_data: dict) -> list[InvariantResult]:
    """Check all invariants against scan data. Returns results."""
    results = []

    for inv_id, description, severity in INVARIANTS:
        # Default: UNKNOWN (not run)
        result = InvariantResult(
            invariant_id=inv_id,
            status="UNKNOWN",
            severity=severity,
            reason=f"Not evaluated: {description}",
            evidence_hashes=(),
        )

        # Check specific invariants that can be verified from scan_data
        if inv_id == "INV-029":
            result = InvariantResult(inv_id, "PASS" if scan_data.get("paper_only") is True else "FAIL", severity,
                                     f"paper_only={scan_data.get('paper_only')}", ())
        elif inv_id == "INV-030":
            result = InvariantResult(inv_id, "PASS" if scan_data.get("live_capital_locked") is True else "FAIL", severity,
                                     f"live_capital_locked={scan_data.get('live_capital_locked')}", ())
        elif inv_id == "INV-031":
            result = InvariantResult(inv_id, "PASS" if scan_data.get("orders_enabled") is False else "FAIL", severity,
                                     f"orders_enabled={scan_data.get('orders_enabled')}", ())
        elif inv_id == "INV-017":
            result = InvariantResult(inv_id, "PASS" if scan_data.get("window_s") == 300 else "FAIL", severity,
                                     f"window_s={scan_data.get('window_s')}", ())
        elif inv_id == "INV-019":
            records = scan_data.get("market_records", [])
            all_null = all(r.get("realized_outcome", {}).get("realized_pnl") is None for r in records)
            result = InvariantResult(inv_id, "PASS" if all_null else "FAIL", severity,
                                     "All realized_pnl are null" if all_null else "Found non-null realized_pnl", ())
        elif inv_id == "INV-020":
            has_balance = any("balance" in r or "realized_pnl" in r for r in scan_data.get("market_records", []))
            result = InvariantResult(inv_id, "PASS" if not has_balance else "FAIL", severity,
                                     "No balance/NAV in records" if not has_balance else "Found balance/NAV", ())

        results.append(result)

    return results


def invariant_summary(results: list[InvariantResult]) -> dict:
    """Summary: pass/fail/unknown counts. Never '0 failures' if not run."""
    return {
        "pass": sum(1 for r in results if r.status == "PASS"),
        "fail": sum(1 for r in results if r.status == "FAIL"),
        "unknown": sum(1 for r in results if r.status == "UNKNOWN"),
        "not_applicable": sum(1 for r in results if r.status == "NOT_APPLICABLE"),
        "total": len(results),
    }
