"""
SENECIO H-011 V3 — Orthogonal semantic status model.

Five INDEPENDENT dimensions. No dimension implies another:
  - OBSERVED does not imply FRESH
  - FRESH does not imply VERIFIED
  - VERIFIED does not imply SHADOW_EXECUTABLE
  - SHADOW_EXECUTABLE does not imply real fill
  - SIMULATED can never be labeled OBSERVED
  - STALE can never be shown as FRESH
  - n=0 can never produce CALIBRATED

Integrates with EvidenceState (existing) — does NOT replace it.
EvidenceState = knowledge and validity of an individual evidence.
SemanticStatus = operational dimensions for display and control.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataOrigin(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    SIMULATED = "SIMULATED"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"
    CONTRADICTORY = "CONTRADICTORY"


class ExecutionStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    HISTORICAL_SIGNAL_ONLY = "HISTORICAL_SIGNAL_ONLY"
    QUOTED = "QUOTED"
    SHADOW_EXECUTABLE = "SHADOW_EXECUTABLE"
    SHADOW_REJECTED = "SHADOW_REJECTED"
    REAL_EXECUTION_DISABLED = "REAL_EXECUTION_DISABLED"


class CalibrationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED = "CALIBRATED"
    DRIFTING = "DRIFTING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class SemanticStatus:
    """Orthogonal operational dimensions. Each is independent."""
    origin: DataOrigin
    freshness: FreshnessStatus
    validation: ValidationStatus
    execution: ExecutionStatus
    calibration: CalibrationStatus

    def to_dict(self) -> dict:
        return {
            "origin": self.origin.value,
            "freshness": self.freshness.value,
            "validation": self.validation.value,
            "execution": self.execution.value,
            "calibration": self.calibration.value,
        }


# ── Factory helpers ──────────────────────────────────────────────────

def default_unknown() -> SemanticStatus:
    return SemanticStatus(
        origin=DataOrigin.UNKNOWN,
        freshness=FreshnessStatus.UNKNOWN,
        validation=ValidationStatus.UNVERIFIED,
        execution=ExecutionStatus.NOT_EVALUATED,
        calibration=CalibrationStatus.NOT_APPLICABLE,
    )


def historical_signal_available() -> SemanticStatus:
    return SemanticStatus(
        origin=DataOrigin.OBSERVED,
        freshness=FreshnessStatus.FRESH,
        validation=ValidationStatus.VERIFIED,
        execution=ExecutionStatus.HISTORICAL_SIGNAL_ONLY,
        calibration=CalibrationStatus.NOT_APPLICABLE,
    )


def shadow_executable() -> SemanticStatus:
    return SemanticStatus(
        origin=DataOrigin.OBSERVED,
        freshness=FreshnessStatus.FRESH,
        validation=ValidationStatus.VERIFIED,
        execution=ExecutionStatus.SHADOW_EXECUTABLE,
        calibration=CalibrationStatus.NOT_APPLICABLE,
    )


def shadow_rejected(reason: str = "") -> SemanticStatus:
    return SemanticStatus(
        origin=DataOrigin.OBSERVED,
        freshness=FreshnessStatus.FRESH,
        validation=ValidationStatus.VERIFIED,
        execution=ExecutionStatus.SHADOW_REJECTED,
        calibration=CalibrationStatus.NOT_APPLICABLE,
    )
