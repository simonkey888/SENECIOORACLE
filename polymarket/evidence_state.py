"""
SENECIO — Explicit evidence states and abstention semantics.

Prevents UNKNOWN from silently becoming 0, None, 0.5, False, success, or verified.
Every external data point must be classified into one of 5 statuses before use.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTORY = "CONTRADICTORY"


@dataclass(frozen=True)
class EvidenceState:
    """
    Immutable evidence record. Once created, cannot be mutated.

    status: classification of the evidence
    value: the actual data value (None if UNKNOWN/INVALID)
    reason: human-readable explanation
    source: where the evidence came from (e.g. "gamma_api", "data_api", "clob")
    source_ts: timestamp from the source (may be None)
    received_ts: when we received it (ISO-8601 UTC)
    evidence_hash: SHA-256 of the value for integrity
    parent_hashes: hashes of upstream evidence this depends on
    """
    status: EvidenceStatus
    value: Any | None
    reason: str | None
    source: str
    source_ts: str | None
    received_ts: str
    evidence_hash: str
    parent_hashes: tuple[str, ...] = ()

    @property
    def operable(self) -> bool:
        """True only if status is KNOWN — safe to use for decisions."""
        return self.status is EvidenceStatus.KNOWN

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "value": self.value,
            "reason": self.reason,
            "source": self.source,
            "source_ts": self.source_ts,
            "received_ts": self.received_ts,
            "evidence_hash": self.evidence_hash,
            "parent_hashes": list(self.parent_hashes),
        }


def make_evidence(
    status: EvidenceStatus,
    value: Any | None,
    source: str,
    reason: str | None = None,
    source_ts: str | None = None,
    received_ts: str | None = None,
    parent_hashes: tuple[str, ...] = (),
) -> EvidenceState:
    """Factory function to create an EvidenceState with auto-hash."""
    from datetime import datetime, timezone
    if received_ts is None:
        received_ts = datetime.now(timezone.utc).isoformat()

    # Hash the value for integrity (None → empty string)
    if value is None:
        evidence_hash = hashlib.sha256(b"__none__").hexdigest()
    elif isinstance(value, (dict, list)):
        evidence_hash = hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    else:
        evidence_hash = hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    return EvidenceState(
        status=status,
        value=value,
        reason=reason,
        source=source,
        source_ts=source_ts,
        received_ts=received_ts,
        evidence_hash=evidence_hash,
        parent_hashes=parent_hashes,
    )


def require_known(states: list[EvidenceState]) -> tuple[bool, list[str]]:
    """
    Check if all evidence states are operable (KNOWN).

    Returns (all_known, reasons_for_failure).
    If all_known is False, reasons contains a list of failure descriptions.
    """
    reasons = [
        f"{state.source}:{state.status.value}:{state.reason or 'no reason'}"
        for state in states
        if not state.operable
    ]
    return not reasons, reasons
