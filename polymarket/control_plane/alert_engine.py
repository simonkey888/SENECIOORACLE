"""
SENECIO H-011 V3 — Alert engine and system status.

Never generates irrelevant alerts (cash drag, portfolio concentration, etc.).
Those belong to a portfolio manager, not to H-011.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    BLOCKING = "BLOCKING"


class SystemStatus(str, Enum):
    BLOCKED = "BLOCKED"
    CRITICAL = "CRITICAL"
    DEGRADED = "DEGRADED"
    HEALTHY = "HEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ControlAlert:
    alert_id: str
    severity: AlertSeverity
    category: str
    code: str
    title: str
    detail: str
    recommended_action: str
    created_at: str
    evidence_hashes: tuple[str, ...]
    blocking: bool

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "category": self.category,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "recommended_action": self.recommended_action,
            "created_at": self.created_at,
            "evidence_hashes": list(self.evidence_hashes),
            "blocking": self.blocking,
        }


def create_alert(
    code: str,
    severity: AlertSeverity,
    title: str,
    detail: str,
    recommended_action: str = "",
    category: str = "system",
    blocking: bool = False,
) -> ControlAlert:
    return ControlAlert(
        alert_id=f"{code}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        severity=severity,
        category=category,
        code=code,
        title=title,
        detail=detail,
        recommended_action=recommended_action,
        created_at=datetime.now(timezone.utc).isoformat(),
        evidence_hashes=(),
        blocking=blocking,
    )


def evaluate_system_status(
    alerts: list[ControlAlert],
    source_healths: dict,
    invariants: list[dict],
) -> SystemStatus:
    """Determine overall system status from alerts, sources, and invariants."""
    if not alerts and not source_healths and not invariants:
        return SystemStatus.UNKNOWN

    if any(a.blocking for a in alerts):
        return SystemStatus.BLOCKED

    if any(a.severity == AlertSeverity.CRITICAL for a in alerts):
        return SystemStatus.CRITICAL

    if any(a.severity == AlertSeverity.WARNING for a in alerts):
        return SystemStatus.DEGRADED

    # Check invariants
    failed_invariants = [i for i in invariants if i.get("status") == "FAIL"]
    if any(i.get("severity") == "BLOCKING" for i in failed_invariants):
        return SystemStatus.BLOCKED

    return SystemStatus.HEALTHY
