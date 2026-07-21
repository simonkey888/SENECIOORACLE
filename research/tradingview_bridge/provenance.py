"""Provenance records for local TradingView research captures.

This module deliberately contains no TradingView, CDP, network, runtime, or
SENEX transaction-chain integration.  It only derives immutable metadata from
an already validated research envelope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

UPSTREAM_REPOSITORY = "https://github.com/tradesdontlie/tradingview-mcp"
UPSTREAM_COMMIT = "55534aab8c11f24655b7d8d4de82e6bece14c8b4"
UPSTREAM_VERSION = "1.0.0"
UPSTREAM_LICENSE = "MIT with additional TradingView/terms notice"


@dataclass(frozen=True)
class ProvenanceRecord:
    schema_version: str
    source: str
    authoritative: bool
    symbol: str
    timeframe: str
    captured_at: str
    tradingview_app_version: str
    tradingview_mcp_commit: str
    capture_type: str
    payload_sha256: str
    upstream_repository: str = UPSTREAM_REPOSITORY
    upstream_commit_inspected: str = UPSTREAM_COMMIT
    upstream_version_inspected: str = UPSTREAM_VERSION
    upstream_license: str = UPSTREAM_LICENSE
    local_only: bool = True
    research_only: bool = True
    production_dependency: bool = False
    northflank_dependency: bool = False
    raw_chain_input: bool = False
    resolution_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_provenance(envelope: Mapping[str, Any]) -> ProvenanceRecord:
    """Build a provenance record from a validated envelope.

    The caller is responsible for running ``validate_envelope`` first.  This
    function intentionally does not infer or upgrade authority.
    """

    return ProvenanceRecord(
        schema_version=str(envelope["schema_version"]),
        source=str(envelope["source"]),
        authoritative=False,
        symbol=str(envelope["symbol"]),
        timeframe=str(envelope["timeframe"]),
        captured_at=str(envelope["captured_at"]),
        tradingview_app_version=str(envelope["tradingview_app_version"]),
        tradingview_mcp_commit=str(envelope["tradingview_mcp_commit"]),
        capture_type=str(envelope["capture_type"]),
        payload_sha256=str(envelope["payload_sha256"]),
    )
