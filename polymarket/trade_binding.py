"""
SENECIO — Trade-to-token binding verification and fill deduplication.

Links each trade from data-api.polymarket.com/trades to its canonical
OutcomeLeg via token_id (asset field). Validates that:
  1. The trade's conditionId matches the market's conditionId
  2. The trade's asset (token_id) matches the expected leg's token_id

Deduplication is NOT solely by transactionHash — a single transaction
can contain multiple fills. Uses a composite dedup key.
"""
from __future__ import annotations

from market_structure import (
    MarketStructure,
    MarketStructureError,
    canonical_hash,
)


def trade_token_id(trade: dict) -> str:
    """Extract the token ID from a trade dict."""
    return str(
        trade.get("asset")
        or trade.get("assetId")
        or trade.get("tokenId")
        or ""
    ).strip()


def trade_dedup_key(trade: dict) -> str:
    """
    Generate a deduplication key for a trade.

    NOT solely by transactionHash — a single transaction can contain
    multiple fills with different prices, sizes, or outcome indices.

    Priority:
      1. Explicit trade ID (id/tradeId) if present
      2. Composite hash of: transactionHash + asset + conditionId +
         outcomeIndex + timestamp + price + size + side
    """
    explicit_id = trade.get("id") or trade.get("tradeId")
    if explicit_id:
        return f"id:{explicit_id}"

    fields = {
        "transactionHash": trade.get("transactionHash"),
        "asset": trade_token_id(trade),
        "conditionId": trade.get("conditionId"),
        "outcomeIndex": trade.get("outcomeIndex"),
        "timestamp": trade.get("timestamp"),
        "price": trade.get("price"),
        "size": trade.get("size"),
        "side": trade.get("side"),
    }
    return canonical_hash(fields)


def validate_trade_binding(
    trade: dict,
    structure: MarketStructure,
) -> tuple[bool, str]:
    """
    Verify that a trade is correctly bound to its market leg.

    Checks:
      1. trade.conditionId == structure.condition_id
      2. trade.asset == structure.leg_for_index(outcomeIndex).token_id

    Returns (True, "trade_token_binding_verified_v1") if valid.
    Returns (False, reason) if invalid — trade is kept in raw event store
    but NOT used for VWAP calculation.
    """
    returned_condition = str(
        trade.get("conditionId") or ""
    ).lower()

    if returned_condition != structure.condition_id:
        return False, "foreign_condition_id"

    try:
        index = int(trade.get("outcomeIndex", -1))
        expected_leg = structure.leg_for_index(index)
    except (TypeError, ValueError, MarketStructureError):
        return False, "invalid_outcome_index"

    observed_token = trade_token_id(trade)

    if not observed_token:
        return False, "trade_token_id_missing"

    if observed_token != expected_leg.token_id:
        return False, "trade_token_binding_mismatch"

    return True, "trade_token_binding_verified_v1"


def compute_vwap_by_index(
    trades: list[dict],
) -> dict[int, dict[str, float | int | None]]:
    """
    Compute VWAP per outcome index (0 and 1).

    Generic — does NOT assume YES/NO labels. Uses outcomeIndex field.

    Returns:
      {0: {"vwap": float|None, "volume": float, "count": int},
       1: {"vwap": float|None, "volume": float, "count": int}}
    """
    accum = {
        0: {"px_size": 0.0, "size": 0.0, "count": 0},
        1: {"px_size": 0.0, "size": 0.0, "count": 0},
    }

    for trade in trades:
        try:
            index = int(trade["outcomeIndex"])
            price = float(trade["price"])
            size = float(trade["size"])
        except (KeyError, TypeError, ValueError):
            continue

        if index not in accum or price <= 0 or size <= 0:
            continue

        accum[index]["px_size"] += price * size
        accum[index]["size"] += size
        accum[index]["count"] += 1

    result = {}
    for index, values in accum.items():
        total_size = float(values["size"])
        result[index] = {
            "vwap": (
                round(float(values["px_size"]) / total_size, 6)
                if total_size > 0
                else None
            ),
            "volume": round(total_size, 6),
            "count": int(values["count"]),
        }

    return result
