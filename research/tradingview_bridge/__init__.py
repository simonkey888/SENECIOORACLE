"""Local-only, non-authoritative TradingView research bridge for SENEX."""

from .adapter import (
    BridgeSecurityError,
    BridgeValidationError,
    ValidationResult,
    associate_research_context,
    compute_window_context,
    payload_sha256,
    safe_import_context,
    validate_envelope,
    validate_tool_name,
)

__all__ = [
    "BridgeSecurityError",
    "BridgeValidationError",
    "ValidationResult",
    "associate_research_context",
    "compute_window_context",
    "payload_sha256",
    "safe_import_context",
    "validate_envelope",
    "validate_tool_name",
]
