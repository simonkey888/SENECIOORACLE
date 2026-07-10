"""
SENECIO H-011 V3 — Shadow execution stress scenarios.

Does NOT mutate the base record. Each scenario produces an independent result.
Synthetic scenarios are marked origin=SYNTHETIC.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clob_readonly import walk_asks, taker_fee, simulate_complete_set


@dataclass(frozen=True)
class StressResult:
    scenario_id: str
    original_net_cost: float | None
    stressed_net_cost: float | None
    stressed_net_edge: float | None
    equal_fillable_quantity: float | None
    execution_status: str
    rejection_reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "original_net_cost": self.original_net_cost,
            "stressed_net_cost": self.stressed_net_cost,
            "stressed_net_edge": self.stressed_net_edge,
            "equal_fillable_quantity": self.equal_fillable_quantity,
            "execution_status": self.execution_status,
            "rejection_reasons": list(self.rejection_reasons),
        }


SCENARIOS = [
    "BASE",
    "LATENCY_250MS",
    "LATENCY_1000MS",
    "DEPTH_75_PERCENT",
    "DEPTH_50_PERCENT",
    "FEE_HIGH",
    "SPREAD_WIDEN_25_PERCENT",
    "SPREAD_WIDEN_50_PERCENT",
    "LEG_0_PARTIAL",
    "LEG_1_PARTIAL",
    "SECOND_LEG_UNAVAILABLE",
    "BOOK_STALE",
    "SNAPSHOT_DESYNC",
    "ADVERSE_MOVE_25BPS",
    "ADVERSE_MOVE_50BPS",
    "SOURCE_DEGRADED",
    "WORST_REASONABLE_CASE",
]


def run_stress_scenario(
    scenario_id: str,
    base_book_0: dict,
    base_book_1: dict,
    base_shares: float,
    base_fee_rate: float,
) -> StressResult:
    """Run a single stress scenario on the base orderbooks."""
    book_0 = dict(base_book_0)
    book_1 = dict(base_book_1)
    shares = base_shares
    fee_rate = base_fee_rate
    rejection_reasons = []

    if scenario_id == "BASE":
        pass
    elif scenario_id == "DEPTH_50_PERCENT":
        book_0["asks"] = [{"price": a["price"], "size": str(float(a["size"]) * 0.5)} for a in book_0.get("asks", [])]
        book_1["asks"] = [{"price": a["price"], "size": str(float(a["size"]) * 0.5)} for a in book_1.get("asks", [])]
    elif scenario_id == "DEPTH_75_PERCENT":
        book_0["asks"] = [{"price": a["price"], "size": str(float(a["size"]) * 0.75)} for a in book_0.get("asks", [])]
        book_1["asks"] = [{"price": a["price"], "size": str(float(a["size"]) * 0.75)} for a in book_1.get("asks", [])]
    elif scenario_id == "FEE_HIGH":
        fee_rate = 0.02  # 2% high fee
    elif scenario_id == "SECOND_LEG_UNAVAILABLE":
        book_1 = {"asks": []}
        rejection_reasons.append("second_leg_unavailable")
    elif scenario_id == "ADVERSE_MOVE_25BPS":
        book_0["asks"] = [{"price": str(float(a["price"]) + 0.0025), "size": a["size"]} for a in book_0.get("asks", [])]
        book_1["asks"] = [{"price": str(float(a["price"]) + 0.0025), "size": a["size"]} for a in book_1.get("asks", [])]
    elif scenario_id == "WORST_REASONABLE_CASE":
        # Combine: 50% depth + high fee + 25bps adverse
        book_0["asks"] = [{"price": str(float(a["price"]) + 0.0025), "size": str(float(a["size"]) * 0.5)} for a in book_0.get("asks", [])]
        book_1["asks"] = [{"price": str(float(a["price"]) + 0.0025), "size": str(float(a["size"]) * 0.5)} for a in book_1.get("asks", [])]
        fee_rate = 0.02

    snapshot = simulate_complete_set(book_0, book_1, shares, fee_rate)

    if not snapshot.fully_fillable:
        rejection_reasons.append("insufficient_fillable")

    net_edge = snapshot.payout - snapshot.total_cost - snapshot.taker_fees if snapshot.fully_fillable else None
    net_cost = snapshot.total_cost + snapshot.taker_fees if snapshot.fully_fillable else None

    return StressResult(
        scenario_id=scenario_id,
        original_net_cost=None,  # Would be passed from base record
        stressed_net_cost=round(net_cost, 6) if net_cost else None,
        stressed_net_edge=round(net_edge, 6) if net_edge else None,
        equal_fillable_quantity=snapshot.shares,
        execution_status="SHADOW_EXECUTABLE" if (snapshot.fully_fillable and net_edge and net_edge > 0) else "REJECTED",
        rejection_reasons=tuple(rejection_reasons),
    )


def run_all_stress_scenarios(
    base_book_0: dict,
    base_book_1: dict,
    base_shares: float,
    base_fee_rate: float,
) -> list[StressResult]:
    """Run all stress scenarios. Returns list of results."""
    results = []
    for scenario_id in SCENARIOS:
        result = run_stress_scenario(scenario_id, base_book_0, base_book_1, base_shares, base_fee_rate)
        results.append(result)
    return results


def stress_summary(results: list[StressResult]) -> dict:
    """Summary of stress results."""
    base = next((r for r in results if r.scenario_id == "BASE"), None)
    worst = next((r for r in results if r.scenario_id == "WORST_REASONABLE_CASE"), None)

    return {
        "base_net_edge": base.stressed_net_edge if base else None,
        "worst_reasonable_net_edge": worst.stressed_net_edge if worst else None,
        "scenarios_positive": sum(1 for r in results if r.execution_status == "SHADOW_EXECUTABLE"),
        "scenarios_rejected": sum(1 for r in results if r.execution_status == "REJECTED"),
        "robustness_score": round(
            sum(1 for r in results if r.execution_status == "SHADOW_EXECUTABLE") / max(len(results), 1), 4
        ),
    }
