"""
SENECIO — Canonical Polymarket market structure registry.

Parses Gamma API market metadata into a frozen, hashable MarketStructure
dataclass. Validates that the market has exactly 2 outcomes, 2 unique
token IDs, and 2 prices. No assumptions about YES/NO labels — uses
leg_0 and leg_1 with official labels preserved.

Market stubs (active markets from the global stream without full metadata)
are REJECTED. A market can only enter the scan pipeline when its complete
metadata has been resolved and validated.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


class MarketStructureError(ValueError):
    """Raised when market metadata is invalid or incomplete."""
    pass


def parse_list(value: Any, field: str) -> list:
    """Parse a value that might be a JSON string or a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise MarketStructureError(f"{field}: invalid JSON") from exc
        if isinstance(parsed, list):
            return parsed
    raise MarketStructureError(f"{field}: expected list")


def canonical_hash(value: dict) -> str:
    """Deterministic SHA-256 of a dict (sorted keys, compact separators)."""
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class OutcomeLeg:
    """A single outcome leg of a binary market."""
    index: int
    label: str
    token_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketStructure:
    """
    Canonical, immutable representation of a Polymarket binary market.

    Created from Gamma API market data via structure_from_gamma().
    Validates: 2 outcomes, 2 unique token IDs, 2 prices.
    """
    condition_id: str
    market_id: str | None
    question: str
    legs: tuple[OutcomeLeg, OutcomeLeg]
    active: bool
    closed: bool
    accepting_orders: bool | None
    fees_enabled: bool | None
    metadata_hash: str

    def leg_for_index(self, outcome_index: int) -> OutcomeLeg:
        """Get the leg for a given outcome index (0 or 1)."""
        if outcome_index not in (0, 1):
            raise MarketStructureError(f"unsupported outcomeIndex={outcome_index}")
        return self.legs[outcome_index]

    def token_ids(self) -> set[str]:
        """Return the set of token IDs for both legs."""
        return {leg.token_id for leg in self.legs}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["legs"] = [leg.to_dict() for leg in self.legs]
        return data


def structure_from_gamma(market: dict) -> MarketStructure:
    """
    Parse a Gamma API market dict into a MarketStructure.

    Raises MarketStructureError if:
      - conditionId is missing
      - outcomes != 2
      - clobTokenIds != 2
      - outcomePrices != 2
      - token IDs are empty or not unique
    """
    condition_id = str(
        market.get("conditionId") or market.get("condition_id") or ""
    ).strip().lower()

    if not condition_id:
        raise MarketStructureError("missing conditionId")

    outcomes = parse_list(market.get("outcomes"), "outcomes")
    token_ids = parse_list(market.get("clobTokenIds"), "clobTokenIds")
    prices = parse_list(market.get("outcomePrices"), "outcomePrices")

    if len(outcomes) != 2:
        raise MarketStructureError(f"expected 2 outcomes, got {len(outcomes)}")
    if len(token_ids) != 2:
        raise MarketStructureError(f"expected 2 token IDs, got {len(token_ids)}")
    if len(prices) != 2:
        raise MarketStructureError(f"expected 2 prices, got {len(prices)}")

    normalized_tokens = [str(token).strip() for token in token_ids]

    if not all(normalized_tokens):
        raise MarketStructureError("empty token ID")
    if len(set(normalized_tokens)) != 2:
        raise MarketStructureError("token IDs are not unique")

    legs = tuple(
        OutcomeLeg(
            index=index,
            label=str(outcomes[index]),
            token_id=normalized_tokens[index],
        )
        for index in range(2)
    )

    source = {
        "conditionId": condition_id,
        "outcomes": outcomes,
        "clobTokenIds": normalized_tokens,
        "outcomePrices": prices,
        "active": market.get("active"),
        "closed": market.get("closed"),
        "acceptingOrders": market.get("acceptingOrders"),
        "feesEnabled": market.get("feesEnabled"),
    }

    return MarketStructure(
        condition_id=condition_id,
        market_id=(
            str(market.get("id"))
            if market.get("id") is not None
            else None
        ),
        question=str(market.get("question") or "")[:500],
        legs=legs,
        active=bool(market.get("active", True)),
        closed=bool(market.get("closed", False)),
        accepting_orders=market.get("acceptingOrders"),
        fees_enabled=market.get("feesEnabled"),
        metadata_hash=canonical_hash(source),
    )


def is_market_stub(market: dict) -> bool:
    """
    Check if a market dict is a stub (incomplete metadata).

    Stubs are markets detected from the global trade stream that haven't
    been resolved via the Gamma API. They have a conditionId but lack
    clobTokenIds, outcomes, or outcomePrices.
    """
    has_tokens = market.get("clobTokenIds") is not None
    has_outcomes = market.get("outcomes") is not None
    has_prices = market.get("outcomePrices") is not None
    return not (has_tokens and has_outcomes and has_prices)


# ═══════════════════════════════════════════════════════════════════════
# Cross-source Market Truth Contract
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MarketTruthContract:
    """
    Cross-source validation contract for a market.

    Gamma determines: conditionId, outcomes, clobTokenIds, metadata.
    CLOB determines: token books exist, ticksize, fees, depth.
    Data API determines: trades belong to the conditionId, asset matches a leg.

    No source alone constitutes full validation.
    """
    condition_id: str
    structure: MarketStructure
    gamma_payload_hash: str
    token_book_verified: tuple[bool, bool]
    trade_assets_verified: bool
    contract_status: str  # EvidenceStatus value
    reasons: tuple[str, ...]
    contract_hash: str
