"""
SENECIO H-011 V3 — Honest drift and calibration status.

n=0 → INSUFFICIENT_SAMPLE (never Brier=0.0000 or hit_rate=50%).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DriftStatus(str, Enum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    STABLE = "STABLE"
    WARNING = "WARNING"
    DRIFTING = "DRIFTING"
    INVALID = "INVALID"


class CalibrationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED = "CALIBRATED"
    DRIFTING = "DRIFTING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DriftResult:
    metric: str
    status: DriftStatus
    recent_sample: int
    reference_sample: int
    mean_shift: float | None
    median_shift: float | None
    rejection_rate_delta: float | None
    threshold: float
    detail: str

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "status": self.status.value,
            "recent_sample": self.recent_sample,
            "reference_sample": self.reference_sample,
            "mean_shift": self.mean_shift,
            "median_shift": self.median_shift,
            "rejection_rate_delta": self.rejection_rate_delta,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CalibrationResult:
    status: CalibrationStatus
    n_verified: int
    brier: float | None
    log_loss: float | None
    hit_rate: float | None
    mae: float | None
    detail: str

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "n_verified": self.n_verified,
            "brier": self.brier,
            "log_loss": self.log_loss,
            "hit_rate": self.hit_rate,
            "mae": self.mae,
            "detail": self.detail,
        }


MIN_SAMPLES_FOR_DRIFT = 30
MIN_SAMPLES_FOR_CALIBRATION = 50


def evaluate_drift(
    metric: str,
    recent_values: list[float],
    reference_values: list[float],
    threshold: float = 0.1,
) -> DriftResult:
    """Evaluate drift between recent and reference windows."""
    if len(recent_values) < MIN_SAMPLES_FOR_DRIFT or len(reference_values) < MIN_SAMPLES_FOR_DRIFT:
        return DriftResult(
            metric=metric,
            status=DriftStatus.INSUFFICIENT_SAMPLE,
            recent_sample=len(recent_values),
            reference_sample=len(reference_values),
            mean_shift=None,
            median_shift=None,
            rejection_rate_delta=None,
            threshold=threshold,
            detail=f"Insufficient samples: recent={len(recent_values)}, reference={len(reference_values)}, min={MIN_SAMPLES_FOR_DRIFT}",
        )

    recent_mean = sum(recent_values) / len(recent_values)
    ref_mean = sum(reference_values) / len(reference_values)
    mean_shift = abs(recent_mean - ref_mean)

    recent_sorted = sorted(recent_values)
    ref_sorted = sorted(reference_values)
    recent_median = recent_sorted[len(recent_sorted) // 2]
    ref_median = ref_sorted[len(ref_sorted) // 2]
    median_shift = abs(recent_median - ref_median)

    if mean_shift > threshold * 2:
        status = DriftStatus.DRIFTING
        detail = f"Mean shift {mean_shift:.4f} exceeds {threshold * 2:.4f}"
    elif mean_shift > threshold:
        status = DriftStatus.WARNING
        detail = f"Mean shift {mean_shift:.4f} exceeds {threshold:.4f}"
    else:
        status = DriftStatus.STABLE
        detail = f"Mean shift {mean_shift:.4f} within threshold {threshold:.4f}"

    return DriftResult(
        metric=metric,
        status=status,
        recent_sample=len(recent_values),
        reference_sample=len(reference_values),
        mean_shift=round(mean_shift, 6),
        median_shift=round(median_shift, 6),
        rejection_rate_delta=None,
        threshold=threshold,
        detail=detail,
    )


def evaluate_calibration(n_verified: int) -> CalibrationResult:
    """Evaluate calibration status. n=0 → INSUFFICIENT_SAMPLE, never numeric metrics."""
    if n_verified == 0:
        return CalibrationResult(
            status=CalibrationStatus.INSUFFICIENT_SAMPLE,
            n_verified=0,
            brier=None,
            log_loss=None,
            hit_rate=None,
            mae=None,
            detail="No verified predictions. All metrics are null (not 0.0000 or 50%).",
        )

    if n_verified < MIN_SAMPLES_FOR_CALIBRATION:
        return CalibrationResult(
            status=CalibrationStatus.INSUFFICIENT_SAMPLE,
            n_verified=n_verified,
            brier=None,
            log_loss=None,
            hit_rate=None,
            mae=None,
            detail=f"Only {n_verified} verified predictions. Need {MIN_SAMPLES_FOR_CALIBRATION} for calibration.",
        )

    # In production: compute actual Brier, log-loss, etc. from verified predictions
    return CalibrationResult(
        status=CalibrationStatus.UNCALIBRATED,
        n_verified=n_verified,
        brier=None,  # Would be computed from actual data
        log_loss=None,
        hit_rate=None,
        mae=None,
        detail=f"{n_verified} verified predictions. Calibration not yet computed.",
    )
