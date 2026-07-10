"""
SENECIO H-011 V3 — Source health registry.

Tracks health of each external data source. A source that was never
attempted is UNKNOWN, not HEALTHY. Zero attempts never produces "0 OK".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceHealthLevel(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    level: SourceHealthLevel
    observed_at: str | None
    received_at: str
    age_ms: int | None
    latency_ms: int | None
    http_status: int | None
    payload_hash: str | None
    consecutive_failures: int
    fallback_used: bool
    reason_code: str | None
    reason_detail: str | None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "level": self.level.value,
            "observed_at": self.observed_at,
            "received_at": self.received_at,
            "age_ms": self.age_ms,
            "latency_ms": self.latency_ms,
            "http_status": self.http_status,
            "payload_hash": self.payload_hash,
            "consecutive_failures": self.consecutive_failures,
            "fallback_used": self.fallback_used,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
        }


@dataclass(frozen=True)
class SourceHealthPolicy:
    fresh_max_age_ms: int
    stale_max_age_ms: int
    failure_threshold: int
    latency_warn_ms: int
    latency_fail_ms: int
    required_for_signal: bool
    required_for_execution: bool


# Default policies per source
DEFAULT_POLICIES: dict[str, SourceHealthPolicy] = {
    "GAMMA": SourceHealthPolicy(
        fresh_max_age_ms=30000, stale_max_age_ms=120000,
        failure_threshold=3, latency_warn_ms=2000, latency_fail_ms=10000,
        required_for_signal=True, required_for_execution=True,
    ),
    "DATA_API": SourceHealthPolicy(
        fresh_max_age_ms=60000, stale_max_age_ms=300000,
        failure_threshold=3, latency_warn_ms=2000, latency_fail_ms=15000,
        required_for_signal=True, required_for_execution=False,
    ),
    "CLOB_LEG_0": SourceHealthPolicy(
        fresh_max_age_ms=3000, stale_max_age_ms=10000,
        failure_threshold=2, latency_warn_ms=500, latency_fail_ms=3000,
        required_for_signal=False, required_for_execution=True,
    ),
    "CLOB_LEG_1": SourceHealthPolicy(
        fresh_max_age_ms=3000, stale_max_age_ms=10000,
        failure_threshold=2, latency_warn_ms=500, latency_fail_ms=3000,
        required_for_signal=False, required_for_execution=True,
    ),
    "FEE_METADATA": SourceHealthPolicy(
        fresh_max_age_ms=60000, stale_max_age_ms=300000,
        failure_threshold=2, latency_warn_ms=1000, latency_fail_ms=5000,
        required_for_signal=False, required_for_execution=True,
    ),
    "RAW_EVENT_STORE": SourceHealthPolicy(
        fresh_max_age_ms=1000, stale_max_age_ms=5000,
        failure_threshold=1, latency_warn_ms=100, latency_fail_ms=1000,
        required_for_signal=True, required_for_execution=True,
    ),
    "CONTROL_STORE": SourceHealthPolicy(
        fresh_max_age_ms=1000, stale_max_age_ms=5000,
        failure_threshold=1, latency_warn_ms=100, latency_fail_ms=1000,
        required_for_signal=False, required_for_execution=True,
    ),
}


def unknown_health(source_id: str) -> SourceHealth:
    """A source that was never attempted."""
    return SourceHealth(
        source_id=source_id,
        level=SourceHealthLevel.UNKNOWN,
        observed_at=None,
        received_at=datetime.now(timezone.utc).isoformat(),
        age_ms=None,
        latency_ms=None,
        http_status=None,
        payload_hash=None,
        consecutive_failures=0,
        fallback_used=False,
        reason_code="never_attempted",
        reason_detail="Source was not queried in this scan",
    )


def evaluate_health(
    source_id: str,
    http_status: int | None,
    latency_ms: int | None,
    age_ms: int | None,
    consecutive_failures: int,
    fallback_used: bool,
    payload_hash: str | None = None,
    observed_at: str | None = None,
) -> SourceHealth:
    """Evaluate the health of a source after an attempt."""
    policy = DEFAULT_POLICIES.get(source_id)

    if http_status is None or http_status >= 500:
        level = SourceHealthLevel.FAILED
        reason = f"http_{http_status or 'no_response'}"
    elif http_status >= 400:
        level = SourceHealthLevel.FAILED
        reason = f"http_{http_status}"
    elif consecutive_failures >= (policy.failure_threshold if policy else 3):
        level = SourceHealthLevel.FAILED
        reason = f"consecutive_failures_{consecutive_failures}"
    elif age_ms is not None and policy and age_ms > policy.stale_max_age_ms:
        level = SourceHealthLevel.STALE
        reason = f"age_{age_ms}ms_exceeds_{policy.stale_max_age_ms}ms"
    elif age_ms is not None and policy and age_ms > policy.fresh_max_age_ms:
        level = SourceHealthLevel.DEGRADED
        reason = f"age_{age_ms}ms_exceeds_{policy.fresh_max_age_ms}ms"
    elif latency_ms is not None and policy and latency_ms > policy.latency_fail_ms:
        level = SourceHealthLevel.DEGRADED
        reason = f"latency_{latency_ms}ms_exceeds_{policy.latency_fail_ms}ms"
    else:
        level = SourceHealthLevel.HEALTHY
        reason = None

    return SourceHealth(
        source_id=source_id,
        level=level,
        observed_at=observed_at,
        received_at=datetime.now(timezone.utc).isoformat(),
        age_ms=age_ms,
        latency_ms=latency_ms,
        http_status=http_status,
        payload_hash=payload_hash,
        consecutive_failures=consecutive_failures,
        fallback_used=fallback_used,
        reason_code=reason,
        reason_detail=None,
    )


def required_sources_healthy(
    healths: dict[str, SourceHealth],
    for_execution: bool = False,
) -> bool:
    """Check if all required sources are healthy."""
    for source_id, policy in DEFAULT_POLICIES.items():
        if for_execution and not policy.required_for_execution:
            continue
        if not for_execution and not policy.required_for_signal:
            continue
        health = healths.get(source_id)
        if health is None or health.level != SourceHealthLevel.HEALTHY:
            return False
    return True
