"""Cross-engine arbiter for the BTC Oracle and H-011 Polymarket scanner.

This module is deliberately decision-only.  It cannot place orders and fails
closed whenever market identity, time horizon, integrity, or execution evidence
is missing.
"""
from __future__ import annotations

from typing import Any

from .engine_contracts import h011_contract, oracle_contract


BTC_MARKERS = ("bitcoin", "btc")


def _is_btc_market(record: dict[str, Any]) -> bool:
    question = str(record.get("question") or "").lower()
    return any(marker in question for marker in BTC_MARKERS)


def arbitrate(oracle: dict[str, Any], h011_state: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    alpha = oracle_contract(oracle)
    execution = h011_contract(h011_state, operations)
    result: dict[str, Any] = {
        "version": "arbiter-shadow-v3.0",
        "mode": "PAPER_ONLY",
        "orders_enabled": False,
        "live_capital_locked": True,
        "decision": "UNKNOWN",
        "action": "FLAT",
        "reasons": [],
        "contracts": {
            "alpha_signal": {**alpha.model_dump(mode="json"), "evidence_hash": alpha.evidence_hash},
            "execution_evidence": {**execution.model_dump(mode="json"), "evidence_hash": execution.evidence_hash},
        },
        "oracle": {
            "action": oracle.get("shadow_action"),
            "gate_status": oracle.get("gate_status"),
            "source_ts": oracle.get("source_ts"),
        },
        "h011": {
            "scan_id": h011_state.get("scan_id"),
            "scan_status": h011_state.get("scan_status"),
            "btc_markets": 0,
            "btc_operations": 0,
        },
    }
    records = h011_state.get("market_records") or []
    btc_records = [record for record in records if _is_btc_market(record)]
    btc_operations = [record for record in operations if _is_btc_market(record)]
    result["h011"]["btc_markets"] = len(btc_records)
    result["h011"]["btc_operations"] = len(btc_operations)

    reasons: list[str] = []
    if oracle.get("gate_status") != "PASS" or oracle.get("shadow_action") not in {"LONG", "SHORT"}:
        reasons.append("ORACLE_DIRECTION_NOT_CALIBRATION_CONFIRMED")
    if not btc_records:
        reasons.append("H011_MARKET_SCOPE_MISMATCH_NO_BTC")
    invariants = (h011_state.get("invariants") or {}).get("summary") or {}
    if int(invariants.get("unknown") or 0) > 0:
        reasons.append("H011_VALIDATION_UNKNOWN")
    source_health = h011_state.get("source_health") or {}
    if not source_health or any((entry or {}).get("level") != "HEALTHY" for entry in source_health.values()):
        reasons.append("H011_SOURCE_HEALTH_NOT_PROVEN")
    if not btc_operations:
        reasons.append("NO_EXECUTABLE_BTC_CLOB_OPERATION")

    if reasons:
        result["reasons"] = reasons
        return result

    # A future compatible H-011 record must explicitly map its executable side.
    side = str(btc_operations[0].get("direction") or btc_operations[0].get("side") or "").upper()
    if side not in {"LONG", "SHORT", "UP", "DOWN"}:
        result["decision"] = "UNKNOWN"
        result["reasons"] = ["H011_EXECUTABLE_SIDE_UNMAPPED"]
        return result
    normalized_side = "LONG" if side in {"LONG", "UP"} else "SHORT"
    if normalized_side != oracle["shadow_action"]:
        result["decision"] = "CONFLICT"
        result["reasons"] = ["ENGINES_DISAGREE"]
        return result

    result["decision"] = "CONFIRM"
    result["action"] = normalized_side
    result["reasons"] = ["CALIBRATED_ORACLE_AND_EXECUTABLE_CLOB_AGREE"]
    return result
