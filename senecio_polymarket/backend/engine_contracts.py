"""Canonical contracts shared by SENECIO decision engines.

Inspired by the alpha-model separation in virattt/ai-hedge-fund v2 (MIT),
adapted for prediction markets: models form views, execution evidence remains
separate, and an arbiter is the only component allowed to combine them.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


Direction = Literal["LONG", "SHORT", "FLAT"]
ValidationState = Literal["PASS", "REJECT", "UNKNOWN"]


class AlphaSignal(BaseModel):
    engine_id: str
    instrument: str
    market_id: str | None = None
    horizon_s: int = Field(gt=0)
    direction: Direction
    confidence_raw: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_calibrated: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_state: ValidationState = "UNKNOWN"
    as_of: str | None = None
    data_cutoff: str | None = None
    abstain_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def evidence_hash(self) -> str:
        body = self.model_dump(mode="json", exclude={"metadata"})
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ExecutionEvidence(BaseModel):
    engine_id: str
    instrument: str
    market_id: str | None = None
    horizon_s: int = Field(gt=0)
    side: Direction = "FLAT"
    executable: bool = False
    identity_verified: bool = False
    source_health_verified: bool = False
    invariants_verified: bool = False
    net_edge: float | None = None
    equal_fillable_quantity: float | None = Field(default=None, ge=0.0)
    as_of: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)

    @property
    def evidence_hash(self) -> str:
        body = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def oracle_contract(payload: dict[str, Any], *, horizon_s: int = 3600) -> AlphaSignal:
    action = str(payload.get("shadow_action") or "FLAT").upper()
    direction: Direction = action if action in {"LONG", "SHORT", "FLAT"} else "FLAT"  # type: ignore[assignment]
    cohort = payload.get("cohort") or {}
    return AlphaSignal(
        engine_id="senecio-oracle-btc-v2",
        instrument="BTCUSD",
        horizon_s=horizon_s,
        direction=direction,
        confidence_raw=payload.get("source_confidence"),
        confidence_calibrated=cohort.get("posterior_accuracy"),
        validation_state=payload.get("gate_status", "UNKNOWN"),
        as_of=payload.get("source_ts"),
        data_cutoff=payload.get("source_ts"),
        abstain_reason=(payload.get("reasons") or [None])[0] if direction == "FLAT" else None,
    )


def h011_contract(state: dict[str, Any], operations: list[dict[str, Any]]) -> ExecutionEvidence:
    btc = [op for op in operations if any(mark in str(op.get("question") or "").lower() for mark in ("btc", "bitcoin"))]
    unknown = int((((state.get("invariants") or {}).get("summary") or {}).get("unknown")) or 0)
    health = state.get("source_health") or {}
    health_ok = bool(health) and all((item or {}).get("level") == "HEALTHY" for item in health.values())
    op = btc[0] if btc else {}
    raw_side = str(op.get("direction") or op.get("side") or "FLAT").upper()
    side: Direction = "LONG" if raw_side in {"LONG", "UP"} else "SHORT" if raw_side in {"SHORT", "DOWN"} else "FLAT"
    return ExecutionEvidence(
        engine_id="senecio-h011-v3",
        instrument="BTCUSD",
        market_id=op.get("condition_id"),
        horizon_s=int(op.get("window_s") or state.get("window_s") or 300),
        side=side,
        executable=bool(btc),
        identity_verified=bool(op.get("condition_id")),
        source_health_verified=health_ok,
        invariants_verified=unknown == 0,
        net_edge=op.get("net_edge"),
        equal_fillable_quantity=op.get("equal_fillable_quantity"),
        as_of=state.get("scan_id"),
        rejection_reasons=[] if btc else ["NO_EXECUTABLE_BTC_CLOB_OPERATION"],
    )
