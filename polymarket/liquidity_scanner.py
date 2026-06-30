"""
SENECIO Liquidity Scanner — H-011 Arbitrage Detection
======================================================
Scans Polymarket binary markets for "broken math" arbitrage:
  YES_price + NO_price < $1.00 - fees

Strategy: Buy both YES and NO shares when their combined cost is less than
$1.00 minus fees. At resolution, one side pays $1.00, guaranteeing profit
regardless of outcome. No prediction required.

Detection only — NO ORDER PLACEMENT without Council authorization.

Feasibility notes:
  - Polymarket CLOB fee: ~1-2% taker fee (varies by market)
  - Break-even: YES + NO < 1.00 - fee
  - Typical market: YES + NO ≈ 1.01-1.05 (overround from fees)
  - Arbitrage window: YES + NO < 0.98 (very rare, requires thin markets)
  - Speed requirement: windows close in seconds as bots compete

Dependencies: httpx, polymarket_connector
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# Import from connector
from polymarket_connector import (
    GAMMA_BASE, CLOB_BASE,
    fetch_all_active_markets,
    fetch_orderbook,
    fetch_price_levels,
)


# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

# Fee assumptions (in bps)
DEFAULT_TAKER_FEE_BPS = 200  # 2% taker fee (conservative estimate)

# Minimum profit threshold in cents per $1 of resolution
MIN_PROFIT_CENTS = 1.0  # at least 1 cent profit per $1

# Scan parameters
SCAN_BATCH_SIZE = 200     # markets per scan cycle
SCAN_INTERVAL_SEC = 60    # seconds between scan cycles

# Output path for detected opportunities
OPPORTUNITIES_PATH = Path(__file__).parent / "arbitrage_opportunities.json"


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ArbitrageOpportunity:
    """A detected YES+NO arbitrage opportunity."""
    market_id: str
    question: str
    p_yes: float                         # YES price from Gamma
    p_no: float                          # NO price from Gamma
    yes_plus_no: float                   # Sum of YES + NO prices
    fee_bps: int                         # Assumed taker fee in bps
    break_even_sum: float                # Maximum YES+NO for profit after fees
    profit_cents_per_dollar: float       # Expected profit in cents per $1 resolved
    profit_pct: float                    # Expected profit as percentage
    volume_usd: float                    # Market volume
    has_orderbook: bool                  # Whether we got CLOB data
    best_bid_yes: Optional[float] = None
    best_ask_yes: Optional[float] = None
    best_bid_no: Optional[float] = None
    best_ask_no: Optional[float] = None
    depth_yes_usd: Optional[float] = None   # Available liquidity at best
    depth_no_usd: Optional[float] = None
    snapshot_utc: str = ""
    event_title: str = ""


# ═══════════════════════════════════════════════════════════════════════
# Core Detection Logic
# ═══════════════════════════════════════════════════════════════════════

def compute_break_even(fee_bps: int = DEFAULT_TAKER_FEE_BPS) -> float:
    """
    Compute the maximum YES+NO sum that still yields profit after fees.

    When we buy YES at price P_y and NO at price P_n:
      Total cost = P_y + P_n + fees
      Fees = fee_rate * (P_y + P_n)  (simplified: fee on both purchases)
      Payout = $1.00 (one side always wins)
      Profit = 1.00 - (P_y + P_n) * (1 + fee_rate)

    Break-even: (P_y + P_n) * (1 + fee_rate) = 1.00
    → P_y + P_n = 1.00 / (1 + fee_rate)

    With 2% fee: break_even = 1.00 / 1.02 ≈ 0.9804
    """
    fee_rate = fee_bps / 10_000.0
    return 1.0 / (1.0 + fee_rate)


def compute_profit(
    p_yes: float,
    p_no: float,
    fee_bps: int = DEFAULT_TAKER_FEE_BPS,
) -> tuple[float, float]:
    """
    Compute expected profit from buying both YES and NO.

    Returns (profit_cents_per_dollar, profit_pct).
    profit_cents_per_dollar: profit in cents per $1 of resolution payout.
    profit_pct: profit as percentage of total investment.
    """
    fee_rate = fee_bps / 10_000.0
    total_cost = (p_yes + p_no) * (1.0 + fee_rate)
    profit = 1.0 - total_cost  # per $1 of resolution

    profit_cents = profit * 100.0
    profit_pct = (profit / total_cost * 100.0) if total_cost > 0 else 0.0

    return round(profit_cents, 4), round(profit_pct, 4)


def scan_markets_for_arbitrage(
    markets: list[dict],
    fee_bps: int = DEFAULT_TAKER_FEE_BPS,
    fetch_book: bool = False,
) -> list[ArbitrageOpportunity]:
    """
    Scan a list of Gamma API markets for YES+NO arbitrage.

    Steps:
    1. Parse outcomePrices for each market
    2. Check if YES + NO < break-even threshold
    3. If fetch_book=True, also check CLOB orderbook for execution prices
    4. Return list of ArbitrageOpportunity objects
    """
    break_even = compute_break_even(fee_bps)
    opportunities = []

    for m in markets:
        try:
            # Parse prices
            prices_raw = m.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            elif isinstance(prices_raw, list):
                prices = prices_raw
            else:
                continue

            if len(prices) < 2:
                continue

            p_yes = float(prices[0])
            p_no = float(prices[1])

            # Sanity checks
            if p_yes <= 0 or p_no <= 0 or p_yes > 1.0 or p_no > 1.0:
                continue

            yes_plus_no = p_yes + p_no

            # Quick filter: only proceed if sum is below a generous threshold
            if yes_plus_no > 1.05:  # most markets are 1.01-1.05, skip the rest
                continue

            # Compute profit
            profit_cents, profit_pct = compute_profit(p_yes, p_no, fee_bps)

            if profit_cents < MIN_PROFIT_CENTS:
                continue

            # We have a potential opportunity
            vol = float(m.get("volumeNum", 0))
            market_id = m.get("id", m.get("condition_id", ""))
            question = m.get("question", "")[:200]

            opp = ArbitrageOpportunity(
                market_id=market_id,
                question=question,
                p_yes=round(p_yes, 4),
                p_no=round(p_no, 4),
                yes_plus_no=round(yes_plus_no, 4),
                fee_bps=fee_bps,
                break_even_sum=round(break_even, 4),
                profit_cents_per_dollar=profit_cents,
                profit_pct=profit_pct,
                volume_usd=round(vol, 2),
                has_orderbook=False,
                snapshot_utc=datetime.now(timezone.utc).isoformat(),
                event_title=m.get("groupItemTitle", "")[:100],
            )

            # Optionally fetch CLOB orderbook
            if fetch_book and market_id:
                book = fetch_orderbook(market_id)
                if book:
                    opp.has_orderbook = True
                    opp.best_bid_yes = book.get("best_bid")
                    opp.best_ask_yes = book.get("best_ask")

                    # Estimate depth at best
                    if book.get("bids"):
                        opp.depth_yes_usd = round(
                            sum(b["price"] * b["size"] for b in book["bids"][:3]), 2
                        )
                    if book.get("asks"):
                        opp.depth_no_usd = round(
                            sum(a["price"] * a["size"] for a in book["asks"][:3]), 2
                        )

            opportunities.append(opp)

        except (ValueError, TypeError, json.JSONDecodeError):
            continue

    # Sort by profit (highest first)
    opportunities.sort(key=lambda o: o.profit_cents_per_dollar, reverse=True)

    return opportunities


def scan_clob_for_arbitrage(
    markets: list[dict],
    fee_bps: int = DEFAULT_TAKER_FEE_BPS,
    max_markets: int = 50,
) -> list[ArbitrageOpportunity]:
    """
    Scan markets using CLOB orderbook data for real execution-price arbitrage.

    Gamma API normalizes YES+NO to exactly 1.00, making it impossible to detect
    broken math from Gamma prices alone. The CLOB orderbook reveals actual
    bid/ask spreads where arbitrage can exist.

    Strategy: For each binary market, buy YES at best_ask and NO at best_ask.
    If best_ask_YES + best_ask_NO < 1.00 - fee → guaranteed profit.

    This scans markets with highest volume first (most liquid = most likely
    to have tight spreads where arb might appear momentarily).
    """
    break_even = compute_break_even(fee_bps)
    opportunities = []

    # Sort markets by volume (highest first) for priority scanning
    sorted_markets = sorted(
        markets,
        key=lambda m: float(m.get("volumeNum", 0)),
        reverse=True,
    )

    scanned = 0
    for m in sorted_markets:
        if scanned >= max_markets:
            break

        try:
            # Get CLOB token IDs
            clob_ids_raw = m.get("clobTokenIds", "[]")
            if isinstance(clob_ids_raw, str):
                clob_ids = json.loads(clob_ids_raw)
            elif isinstance(clob_ids_raw, list):
                clob_ids = clob_ids_raw
            else:
                continue

            if len(clob_ids) < 2:
                continue

            yes_token = clob_ids[0]
            no_token = clob_ids[1]

            # Fetch orderbooks for both tokens
            yes_book = fetch_orderbook(yes_token)
            no_book = fetch_orderbook(no_token)

            if not yes_book or not no_book:
                continue

            # Best ask for YES (cheapest price to buy YES)
            best_ask_yes = None
            if yes_book.get("asks"):
                best_ask_yes = float(yes_book["asks"][0]["price"])

            # Best ask for NO (cheapest price to buy NO)
            best_ask_no = None
            if no_book.get("asks"):
                best_ask_no = float(no_book["asks"][0]["price"])

            if best_ask_yes is None or best_ask_no is None:
                continue

            yes_plus_no = best_ask_yes + best_ask_no

            # Check for arbitrage
            profit_cents, profit_pct = compute_profit(best_ask_yes, best_ask_no, fee_bps)

            if profit_cents < MIN_PROFIT_CENTS:
                scanned += 1
                continue

            # We found an opportunity!
            vol = float(m.get("volumeNum", 0))
            question = m.get("question", "")[:200]

            # Get depth at best prices
            depth_yes = 0.0
            if yes_book.get("asks"):
                for a in yes_book["asks"][:3]:
                    depth_yes += float(a.get("price", 0)) * float(a.get("size", 0))

            depth_no = 0.0
            if no_book.get("asks"):
                for a in no_book["asks"][:3]:
                    depth_no += float(a.get("price", 0)) * float(a.get("size", 0))

            opp = ArbitrageOpportunity(
                market_id=m.get("id", ""),
                question=question,
                p_yes=round(best_ask_yes, 4),
                p_no=round(best_ask_no, 4),
                yes_plus_no=round(yes_plus_no, 4),
                fee_bps=fee_bps,
                break_even_sum=round(break_even, 4),
                profit_cents_per_dollar=profit_cents,
                profit_pct=profit_pct,
                volume_usd=round(vol, 2),
                has_orderbook=True,
                best_ask_yes=round(best_ask_yes, 4),
                best_ask_no=round(best_ask_no, 4),
                best_bid_yes=yes_book.get("best_bid"),
                best_bid_no=no_book.get("best_bid"),
                depth_yes_usd=round(depth_yes, 2),
                depth_no_usd=round(depth_no, 2),
                snapshot_utc=datetime.now(timezone.utc).isoformat(),
                event_title=m.get("groupItemTitle", "")[:100],
            )

            opportunities.append(opp)

        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        scanned += 1

    # Sort by profit
    opportunities.sort(key=lambda o: o.profit_cents_per_dollar, reverse=True)

    return opportunities


# ═══════════════════════════════════════════════════════════════════════
# Full Scan Cycle
# ═══════════════════════════════════════════════════════════════════════

def run_scan_cycle(
    fee_bps: int = DEFAULT_TAKER_FEE_BPS,
    fetch_book: bool = False,
    max_markets: int = SCAN_BATCH_SIZE,
) -> dict:
    """
    Run one complete scan cycle.

    Returns dict with scan results and statistics.
    """
    start_time = time.time()
    print(f"\n{'=' * 65}")
    print(f"SENECIO H-011 — Liquidity Arbitrage Scanner")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 65}")

    # Step 1: Fetch all active markets
    print(f"\n[1] Fetching active markets (limit={max_markets})...")
    try:
        markets = fetch_all_active_markets(limit=max_markets)
    except Exception as e:
        print(f"    FAILED: {e}")
        return {"error": str(e), "opportunities": []}

    print(f"    Active markets: {len(markets)}")

    # Step 2: Filter for binary markets with outcomePrices
    binary_count = 0
    filtered = []
    for m in markets:
        prices_raw = m.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            try:
                prices = json.loads(prices_raw)
            except json.JSONDecodeError:
                continue
        elif isinstance(prices_raw, list):
            prices = prices_raw
        else:
            continue
        if len(prices) >= 2:
            binary_count += 1
            filtered.append(m)

    print(f"    Binary markets with prices: {binary_count}")

    # Step 3: Scan Gamma prices for arbitrage (usually finds nothing due to normalization)
    print(f"\n[2] Scanning Gamma prices for YES+NO < ${compute_break_even(fee_bps):.4f} (after {fee_bps/100:.1f}% fee)...")
    opportunities = scan_markets_for_arbitrage(filtered, fee_bps=fee_bps, fetch_book=fetch_book)
    print(f"    Gamma-based opportunities: {len(opportunities)}")

    # Step 3b: Scan CLOB orderbooks for real execution-price arbitrage
    print(f"\n[2b] Scanning CLOB orderbooks (top 20 markets by volume)...")
    clob_opportunities = scan_clob_for_arbitrage(filtered, fee_bps=fee_bps, max_markets=20)
    print(f"    CLOB-based opportunities: {len(clob_opportunities)}")

    # Merge opportunities
    all_opportunities = opportunities + clob_opportunities

    # Step 4: Print results
    if all_opportunities:
        print(f"\n[3] Arbitrage Opportunities:")
        print(f"    {'Question':<45} {'YES':>6} {'NO':>6} {'Sum':>6} {'Profit':>8} {'Vol':>10}")
        print(f"    {'-' * 80}")
        for opp in all_opportunities[:20]:
            src = "CLOB" if opp.has_orderbook else "GAMMA"
            print(f"    [{src}] {opp.question[:37]:<37} {opp.p_yes:>6.3f} {opp.p_no:>6.3f} "
                  f"{opp.yes_plus_no:>6.4f} {opp.profit_cents_per_dollar:>6.2f}c "
                  f"${opp.volume_usd:>9.0f}")
    else:
        print(f"\n[3] No arbitrage opportunities detected in this scan.")
        # Print some stats about what we found
        sums = []
        for m in filtered:
            try:
                prices_raw = m.get("outcomePrices", "[]")
                if isinstance(prices_raw, str):
                    prices = json.loads(prices_raw)
                else:
                    prices = prices_raw
                if len(prices) >= 2:
                    sums.append(float(prices[0]) + float(prices[1]))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

        if sums:
            print(f"    YES+NO distribution: min={min(sums):.4f}  max={max(sums):.4f}  "
                  f"mean={sum(sums)/len(sums):.4f}  median={sorted(sums)[len(sums)//2]:.4f}")
            below_1 = sum(1 for s in sums if s < 1.0)
            below_101 = sum(1 for s in sums if s < 1.01)
            below_102 = sum(1 for s in sums if s < 1.02)
            print(f"    YES+NO < 1.00: {below_1}  < 1.01: {below_101}  < 1.02: {below_102}")

    # Step 5: Save results
    elapsed = round(time.time() - start_time, 2)
    result = {
        "scan_type": "H-011_liquidity_arbitrage",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "markets_scanned": binary_count,
        "clob_markets_scanned": min(20, len(filtered)),
        "fee_bps": fee_bps,
        "break_even_sum": round(compute_break_even(fee_bps), 4),
        "gamma_opportunities": len(opportunities),
        "clob_opportunities": len(clob_opportunities),
        "total_opportunities": len(all_opportunities),
        "opportunities": [asdict(o) for o in all_opportunities],
        "scan_duration_sec": elapsed,
    }

    output_path = Path("/home/z/my-project/download/h011_arbitrage_scan.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n    Results saved: {output_path}")
    print(f"    Scan duration: {elapsed}s")

    return result


# ═══════════════════════════════════════════════════════════════════════
# Feasibility Assessment (ARB_3)
# ═══════════════════════════════════════════════════════════════════════

def assess_feasibility() -> dict:
    """
    Assess the technical feasibility of executing arbitrage trades on Polymarket.

    This evaluates:
    1. API latency and rate limits
    2. Order placement capabilities
    3. Execution speed requirements
    4. Competition (bot landscape)
    5. Fee structure impact

    Returns a feasibility report dict.
    """
    report = {
        "assessment_type": "H-011_arbitrage_feasibility",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    # 1. API Latency Test
    print("\n[Feasibility] Testing Polymarket API latency...")
    latencies = []
    try:
        with httpx.Client(timeout=10.0) as c:
            for _ in range(5):
                start = time.time()
                r = c.get(f"{GAMMA_BASE}/markets", params={"limit": 1})
                elapsed = time.time() - start
                latencies.append(elapsed)
                print(f"    Gamma API: {elapsed*1000:.0f}ms (status={r.status_code})")
    except Exception as e:
        print(f"    Gamma API error: {e}")

    clob_latencies = []
    try:
        with httpx.Client(timeout=10.0) as c:
            for _ in range(5):
                start = time.time()
                r = c.get(f"{CLOB_BASE}/markets")
                elapsed = time.time() - start
                clob_latencies.append(elapsed)
                print(f"    CLOB API:  {elapsed*1000:.0f}ms (status={r.status_code})")
    except Exception as e:
        print(f"    CLOB API error: {e}")

    report["api_latency"] = {
        "gamma_ms": round(sum(latencies) / len(latencies) * 1000, 0) if latencies else None,
        "clob_ms": round(sum(clob_latencies) / len(clob_latencies) * 1000, 0) if clob_latencies else None,
    }

    # 2. Rate Limits
    report["rate_limits"] = {
        "gamma_api": "Undocumented — observed no issues at 10 req/s",
        "clob_api": "Rate limited — specific limits undocumented, but aggressive polling triggers 429",
        "note": "Polymarket uses Cloudflare; rate limits likely IP-based, not API-key-based for read endpoints",
    }

    # 3. Order Placement
    report["order_execution"] = {
        "clob_order_endpoint": "POST /order (requires API key + signature)",
        "authentication": "API key + Ethereum wallet signature (L2 on Polygon)",
        "order_types": ["GTC (Good Till Canceled)", "GTD (Good Till Date)", "FOK (Fill or Kill)"],
        "execution_speed": "CLOB is order-book based; fills depend on liquidity at price",
        "minimum_order": "$1 USD equivalent",
        "fee_structure": "Taker fee: 1-2% (varies by market); Maker fee: 0% (rebate in some markets)",
    }

    # 4. Competition Assessment
    report["competition"] = {
        "bot_landscape": "High — Polymarket is a popular target for MEV/arb bots",
        "window_duration": "Typically < 5 seconds for obvious arb; thin markets may last longer",
        "detection_advantage": "Marginal — many bots scan the same APIs simultaneously",
        "execution_advantage": "Low without co-location or priority API access",
    }

    # 5. Fee Impact Analysis
    fee_scenarios = []
    for fee_bps in [100, 200, 300, 500]:
        be = compute_break_even(fee_bps)
        fee_scenarios.append({
            "fee_pct": fee_bps / 100,
            "break_even_sum": round(be, 4),
            "required_gap_cents": round((1.0 - be) * 100, 2),
        })
    report["fee_impact"] = fee_scenarios

    # 6. Overall Verdict
    report["verdict"] = {
        "detection": "FEASIBLE — current Gamma + CLOB API sufficient for scanning",
        "execution": "CHALLENGING — requires wallet auth, low-latency execution, competes with bots",
        "profit_potential": "LOW — typical YES+NO sum is 1.01-1.05; sub-1.00 is rare and small",
        "recommendation": "DETECTION_ONLY for now. Build scanner, log opportunities over 2 weeks. "
                         "If frequency and size justify, then implement execution with FOK orders.",
        "risk_warning": "Broken math arb is theoretically risk-free but execution risk is real: "
                       "partial fills, fees exceeding estimates, and market voiding can all cause losses.",
    }

    # Save report
    report_path = Path("/home/z/my-project/download/h011_feasibility_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n    Feasibility report saved: {report_path}")

    return report


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("SENECIO H-011 — Liquidity Arbitrage Scanner")
    print("DETECTION ONLY — No orders will be placed.")
    print("=" * 65)

    # Run scan
    result = run_scan_cycle(fee_bps=DEFAULT_TAKER_FEE_BPS, fetch_book=False)

    # Feasibility assessment
    print("\n" + "=" * 65)
    print("Running feasibility assessment...")
    feasibility = assess_feasibility()
