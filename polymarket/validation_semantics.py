"""
SENECIO H-011 — Validation semantics and experiment cohort definitions.

Classification levels for market validation:
  1. market_identity_match_v1     — conditionId matches (minimum, not sufficient)
  2. market_structure_verified_v2 — full Gamma metadata resolved (outcomes, tokens, prices)
  3. trade_token_binding_verified_v1 — each trade's asset matches the expected leg's token_id
  4. l2_executable_snapshot_v1    — both CLOB orderbooks respond, equal fillable, net edge > 0

Legacy records (condition_id_match_v1) are treated as market_identity_match_v1 ONLY.
Never as full validation.

Cohort ID for new scans (W=300, VWAP estimator, structure v2):
  h011-v3-w300-vwap-structure-v2

Legacy scans (W=3600) are classified as:
  legacy_w3600
and excluded from the W=300 pre-registered decision.
"""
from __future__ import annotations

# Validation levels (ordered by increasing confidence)
VALIDATION_CONDITION_ONLY = "market_identity_match_v1"
VALIDATION_STRUCTURE = "market_structure_verified_v2"
VALIDATION_TRADE_BINDING = "trade_token_binding_verified_v1"
VALIDATION_EXECUTION = "l2_executable_snapshot_v1"

# Cohort identifiers
H011_COHORT_ID = "h011-v3-w300-vwap-structure-v2"
H011_LEGACY_COHORT = "legacy_w3600"

# All validation levels in order
VALIDATION_LEVELS = [
    VALIDATION_CONDITION_ONLY,
    VALIDATION_STRUCTURE,
    VALIDATION_TRADE_BINDING,
    VALIDATION_EXECUTION,
]


def classify_window_cohort(window_s: int) -> str:
    """Classify a scan into the correct cohort based on window size."""
    if window_s == 300:
        return H011_COHORT_ID
    elif window_s == 3600:
        return H011_LEGACY_COHORT
    else:
        return f"legacy_w{window_s}"


def is_legacy_cohort(cohort_id: str) -> bool:
    """Check if a cohort is legacy (not the current pre-registered W=300 cohort)."""
    return cohort_id != H011_COHORT_ID


def is_full_validation(validation_level: str) -> bool:
    """Check if a validation level constitutes full validation.
    condition_only is NEVER full validation."""
    return validation_level in (
        VALIDATION_TRADE_BINDING,
        VALIDATION_EXECUTION,
    )


def new_scan_metadata(
    window_s: int,
    estimator: str = "vwap",
    market_identity_verified: bool = True,
    market_structure_verified: bool = False,
    trade_token_binding_verified: bool = False,
    execution_verified: bool = False,
) -> dict:
    """Generate metadata block for new scan/ledger entries."""
    return {
        "cohort_id": classify_window_cohort(window_s),
        "window_s": window_s,
        "estimator": estimator,
        "market_identity_verified": market_identity_verified,
        "market_structure_verified": market_structure_verified,
        "trade_token_binding_verified": trade_token_binding_verified,
        "execution_verified": execution_verified,
    }
