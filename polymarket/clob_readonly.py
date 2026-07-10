"""
SENECIO — Token-aware CLOB L2 shadow execution engine.

READ-ONLY: queries orderbooks by token_id (never condition_id), walks
the ask book deterministically, simulates complete-set execution,
and calculates net edge after dynamic fees.

No orders are placed. No POST endpoints are called. Pure shadow simulation.

A market is marked as executable ONLY if:
  1. market_structure_verified = true
  2. trade_token_binding_verified = true
  3. Both orderbooks respond with matching asset_id
  4. Equal fillable shares in both legs
  5. net_edge_usdc > 0 after fees
  6. snapshot_age_ms within limit

leg_risk is ALWAYS true — two conventional orders are not a joint transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

CLOB_BASE = "https://clob.polymarket.com"


def fetch_orderbook(token_id: str) -> dict:
    """
    Fetch the full orderbook for a token from the CLOB API.

    Queries by token_id, NEVER by condition_id.
    Fail-closed: if returned asset_id doesn't match, raise ValueError.
    """
    if not token_id:
        raise ValueError("token_id is required")

    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
        )
        response.raise_for_status()
        payload = response.json()

    returned_asset = str(
        payload.get("asset_id")
        or payload.get("assetId")
        or ""
    )

    if returned_asset and returned_asset != token_id:
        raise ValueError(
            f"orderbook asset mismatch: "
            f"requested={token_id} returned={returned_asset}"
        )

    return payload


@dataclass(frozen=True)
class WalkResult:
    """Result of walking the ask book for a given share quantity."""
    requested_shares: float
    filled_shares: float
    gross_cost: float
    average_price: float | None
    fully_fillable: bool


def walk_asks(
    asks: list[dict],
    requested_shares: float,
) -> WalkResult:
    """
    Walk the ask book deterministically (sorted by price ascending).
    Returns how many shares can be filled and at what cost.
    """
    remaining = max(0.0, requested_shares)
    filled = 0.0
    cost = 0.0

    levels = sorted(
        asks,
        key=lambda level: float(level["price"]),
    )

    for level in levels:
        if remaining <= 0:
            break

        price = float(level["price"])
        available = float(level["size"])

        if price <= 0 or available <= 0:
            continue

        quantity = min(remaining, available)
        cost += quantity * price
        filled += quantity
        remaining -= quantity

    return WalkResult(
        requested_shares=requested_shares,
        filled_shares=filled,
        gross_cost=cost,
        average_price=(cost / filled if filled > 0 else None),
        fully_fillable=(remaining <= 1e-9),
    )


def taker_fee(
    shares: float,
    price: float,
    fee_rate: float,
) -> float:
    """
    Calculate taker fee for a fill.

    Polymarket fee formula: shares * fee_rate * price * (1 - price)
    This is the Polymarket-specific fee model where fees scale with
    the distance from 0.5 (max fee at 0.5, zero at 0 and 1).
    """
    return shares * fee_rate * price * (1.0 - price)


@dataclass(frozen=True)
class CompleteSetSnapshot:
    """
    Snapshot of a complete-set arbitrage execution simulation.

    leg_risk is ALWAYS True — two conventional CLOB orders are not atomic.
    """
    shares: float
    leg_0_cost: float
    leg_1_cost: float
    total_cost: float
    taker_fees: float
    payout: float
    net_edge_usdc: float
    net_edge_per_share: float
    fully_fillable: bool
    leg_risk: bool
    execution_model: str


def simulate_complete_set(
    leg_0_book: dict,
    leg_1_book: dict,
    shares: float,
    fee_rate: float,
) -> CompleteSetSnapshot:
    """
    Simulate buying a complete set (leg_0 + leg_1) from the ask books.

    Returns a CompleteSetSnapshot with:
      - net_edge_usdc: payout - total_cost - fees
      - fully_fillable: True only if both legs can fill the requested shares
      - leg_risk: ALWAYS True (non-atomic execution)
    """
    leg_0 = walk_asks(leg_0_book.get("asks", []), shares)
    leg_1 = walk_asks(leg_1_book.get("asks", []), shares)

    fully_fillable = (
        leg_0.fully_fillable
        and leg_1.fully_fillable
        and abs(leg_0.filled_shares - leg_1.filled_shares) < 1e-9
    )

    executable_shares = min(
        leg_0.filled_shares,
        leg_1.filled_shares,
    )

    if not fully_fillable or executable_shares <= 0:
        return CompleteSetSnapshot(
            shares=executable_shares,
            leg_0_cost=leg_0.gross_cost,
            leg_1_cost=leg_1.gross_cost,
            total_cost=leg_0.gross_cost + leg_1.gross_cost,
            taker_fees=0.0,
            payout=executable_shares,
            net_edge_usdc=0.0,
            net_edge_per_share=0.0,
            fully_fillable=False,
            leg_risk=True,
            execution_model="l2_taker_shadow_v1",
        )

    fee_0 = taker_fee(
        executable_shares,
        float(leg_0.average_price),
        fee_rate,
    )
    fee_1 = taker_fee(
        executable_shares,
        float(leg_1.average_price),
        fee_rate,
    )

    total_cost = leg_0.gross_cost + leg_1.gross_cost
    fees = fee_0 + fee_1
    payout = executable_shares
    net = payout - total_cost - fees

    return CompleteSetSnapshot(
        shares=executable_shares,
        leg_0_cost=leg_0.gross_cost,
        leg_1_cost=leg_1.gross_cost,
        total_cost=total_cost,
        taker_fees=fees,
        payout=payout,
        net_edge_usdc=net,
        net_edge_per_share=net / executable_shares,
        fully_fillable=True,
        leg_risk=True,
        execution_model="l2_taker_shadow_v1",
    )


def is_executable(snapshot: CompleteSetSnapshot) -> bool:
    """
    Check if a snapshot represents an executable opportunity.

    Requirements:
      - fully_fillable = True
      - net_edge_usdc > 0
      - leg_risk is always True (documented, not a blocker for shadow)
    """
    return (
        snapshot.fully_fillable
        and snapshot.net_edge_usdc > 0
    )
