"""
SENECIO H-011 — VWAP Cross-Leg Arbitrage Detector (FASE_0, READ-ONLY)
=====================================================================
Hipótesis: |VWAP(YES) + VWAP(NO) - 1.00| >= umbral → edge mecánico potencial.

Inspiración: paper arxiv 2508.03474 — midió $40M en arbitraje real en Polymarket
usando VWAP en vez de last-tick price.

Endpoint: GET https://data-api.polymarket.com/trades
  - Público, sin auth
  - Filtros: conditionId, after (unix epoch), limit, offset
  - Campos clave: conditionId, outcomeIndex (0=YES, 1=NO), price, size, timestamp, side

REGLAS FASE_0 ABSOLUTAS:
  - NO órdenes de compra/venta
  - NO modificar estado en Polymarket
  - NO tocar oracle crypto
  - NO mezclar con H-010 (archivado)
  - SOLO detector de lectura

PRE-REGISTRO (inmutable una vez commiteado):
  - ventana_default = 3600s (1h)
  - umbral_deteccion = 0.02 (2 centavos) → flag inicial
  - umbral_sostenido = 0.05 (5 centavos) → justifica FASE_1
  - exclude_leg_above = 0.95 (mercados ya resueltos)
  - min_trades_per_leg = 1 (mínimo para calcular VWAP válido)
  - criterio GO día 8: >= 5 mercados con desviación >= 5pp sostenida
                        (en 3+ scans distintos a lo largo de 7 días)
  - criterio NO-GO día 8: < 5 mercados con esa condición

Dependencies: httpx (stdlib + httpx only)
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# Reuse existing connector for market fetching
sys.path.insert(0, str(Path(__file__).parent))
from polymarket_connector import GAMMA_BASE, fetch_all_active_markets

# ═══════════════════════════════════════════════════════════════════════
# Configuration (PRE-REGISTRADA — NO MODIFICAR sin invalidar pre-registro)
# ═══════════════════════════════════════════════════════════════════════

DATA_API_BASE = "https://data-api.polymarket.com"

# Ventana de tiempo para VWAP (segundos). Default 1h.
VWAP_WINDOW_SEC = int(os.environ.get("H011_VWAP_WINDOW", "3600"))

# Umbral de detección: desviación >= 2 centavos para flag inicial
THRESHOLD_DETECTION = float(os.environ.get("H011_THRESHOLD_DETECTION", "0.02"))

# Umbral sostenido: desviación >= 5 centavos para justificar FASE_1
THRESHOLD_SUSTAINED = float(os.environ.get("H011_THRESHOLD_SUSTAINED", "0.05"))

# Excluir mercados donde cualquier leg > 0.95 (ya resueltos)
EXCLUDE_LEG_ABOVE = float(os.environ.get("H011_EXCLUDE_LEG_ABOVE", "0.95"))

# Mínimo de trades por leg para considerar VWAP válido
MIN_TRADES_PER_LEG = int(os.environ.get("H011_MIN_TRADES_PER_LEG", "1"))

# Límite de trades a fetchear por mercado (suficiente para 1h de actividad)
TRADES_FETCH_LIMIT = int(os.environ.get("H011_TRADES_LIMIT", "500"))

# Sleep entre requests para respetar Cloudflare rate limiting
REQUEST_DELAY_SEC = float(os.environ.get("H011_REQUEST_DELAY", "0.15"))

# Máximo de mercados a escanear por ciclo (default 30 para Día 1 manual run)
MAX_MARKETS_PER_SCAN = int(os.environ.get("H011_MAX_MARKETS", "30"))

# Output paths
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class VWAPResult:
    """Resultado de VWAP para un mercado individual."""
    condition_id: str
    question: str
    event_slug: str
    # VWAP YES (outcomeIndex=0)
    vwap_yes: Optional[float]
    trades_yes: int
    volume_yes: float  # sum of size
    # VWAP NO (outcomeIndex=1)
    vwap_no: Optional[float]
    trades_no: int
    volume_no: float
    # Combined metrics
    sum_vwap: Optional[float]  # vwap_yes + vwap_no
    deviation: Optional[float]  # |sum_vwap - 1.00|
    # Flags
    is_flagged: bool  # deviation >= THRESHOLD_DETECTION
    is_sustained: bool  # deviation >= THRESHOLD_SUSTAINED
    excluded_reason: Optional[str]  # why excluded if any
    # Metadata
    snapshot_utc: str
    window_sec: int
    gamma_p_yes: Optional[float] = None  # from Gamma API outcomePrices
    gamma_p_no: Optional[float] = None
    volume_usd: Optional[float] = None


@dataclass
class ScanReport:
    """Reporte consolidado de un scan completo."""
    scan_id: str  # ISO timestamp
    scan_type: str  # "H-011_VWAP_DETECTOR_FASE0"
    started_at: str
    finished_at: str
    duration_sec: float
    # Config
    window_sec: int
    threshold_detection: float
    threshold_sustained: float
    exclude_leg_above: float
    max_markets: int
    # Counts
    markets_fetched: int
    binary_markets: int
    markets_scanned: int
    markets_with_trades: int
    markets_excluded_no_trades: int
    markets_excluded_resolved: int
    markets_flagged_detection: int
    markets_flagged_sustained: int
    # Distribution of deviations (for stats)
    deviation_stats: dict
    # Top results
    top_deviations: list[dict]
    # All results (for JSONL)
    results: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Core Logic
# ═══════════════════════════════════════════════════════════════════════

def fetch_trades_for_market(condition_id: str, after_ts: int, limit: int = TRADES_FETCH_LIMIT) -> list[dict]:
    """
    Fetch trades for a single market from data-api.polymarket.com/trades.

    IMPORTANT: The API silently ignores the `conditionId=` query parameter and
    returns the global trade stream instead. The correct filter is `market=`,
    which actually filters by conditionId. This was discovered on Día 1 of
    FASE_0 (2026-06-30) after the initial scan returned identical VWAPs across
    28 markets — a clear artefact of measurement (lesson from H-010 applied).

    Returns raw list of trade dicts. Empty list on error or no trades.
    """
    url = f"{DATA_API_BASE}/trades"
    params = {
        "market": condition_id,  # NOT conditionId= — that's silently ignored
        "after": after_ts,
        "limit": limit,
    }
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
            if not isinstance(data, list):
                return []
            return data
    except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as e:
        print(f"    [data-api] Error fetching trades for {condition_id[:18]}...: {e}")
        return []


def compute_vwap(trades: list[dict]) -> tuple[Optional[float], int, float, Optional[float], int, float]:
    """
    Compute VWAP for YES (outcomeIndex=0) and NO (outcomeIndex=1) legs.

    VWAP = sum(price * size) / sum(size)

    Returns (vwap_yes, n_yes, vol_yes, vwap_no, n_no, vol_no).
    Any leg with no trades returns None for VWAP and 0 for count/volume.
    """
    yes_price_size = 0.0
    yes_size = 0.0
    n_yes = 0

    no_price_size = 0.0
    no_size = 0.0
    n_no = 0

    for t in trades:
        try:
            price = float(t.get("price", 0))
            size = float(t.get("size", 0))
            idx = int(t.get("outcomeIndex", -1))
            if price <= 0 or size <= 0 or idx not in (0, 1):
                continue
            if idx == 0:
                yes_price_size += price * size
                yes_size += size
                n_yes += 1
            else:
                no_price_size += price * size
                no_size += size
                n_no += 1
        except (ValueError, TypeError):
            continue

    vwap_yes = round(yes_price_size / yes_size, 6) if yes_size > 0 else None
    vwap_no = round(no_price_size / no_size, 6) if no_size > 0 else None

    return (vwap_yes, n_yes, round(yes_size, 4), vwap_no, n_no, round(no_size, 4))


def analyze_market(market: dict, after_ts: int) -> VWAPResult:
    """
    Fetch trades + compute VWAP + flag deviation for a single market.
    """
    snapshot = datetime.now(timezone.utc).isoformat()

    condition_id = market.get("conditionId") or market.get("condition_id") or ""
    question = (market.get("question") or "")[:200]
    event_slug = market.get("eventSlug") or market.get("slug") or ""

    # Parse Gamma outcomePrices for cross-reference
    gamma_p_yes = None
    gamma_p_no = None
    try:
        prices_raw = market.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            prices = json.loads(prices_raw)
        else:
            prices = prices_raw
        if isinstance(prices, list) and len(prices) >= 2:
            gamma_p_yes = float(prices[0])
            gamma_p_no = float(prices[1])
    except (ValueError, TypeError, json.JSONDecodeError):
        pass

    volume_usd = None
    try:
        volume_usd = float(market.get("volumeNum", 0) or market.get("volume", 0))
    except (ValueError, TypeError):
        pass

    # Initialize result
    result = VWAPResult(
        condition_id=condition_id,
        question=question,
        event_slug=event_slug,
        vwap_yes=None, trades_yes=0, volume_yes=0.0,
        vwap_no=None, trades_no=0, volume_no=0.0,
        sum_vwap=None, deviation=None,
        is_flagged=False, is_sustained=False,
        excluded_reason=None,
        snapshot_utc=snapshot,
        window_sec=VWAP_WINDOW_SEC,
        gamma_p_yes=gamma_p_yes,
        gamma_p_no=gamma_p_no,
        volume_usd=volume_usd,
    )

    if not condition_id:
        result.excluded_reason = "no_condition_id"
        return result

    # Fetch trades
    trades = fetch_trades_for_market(condition_id, after_ts, limit=TRADES_FETCH_LIMIT)

    if not trades:
        result.excluded_reason = "no_trades_in_window"
        return result

    # Compute VWAP
    vwap_yes, n_yes, vol_yes, vwap_no, n_no, vol_no = compute_vwap(trades)
    result.vwap_yes = vwap_yes
    result.trades_yes = n_yes
    result.volume_yes = vol_yes
    result.vwap_no = vwap_no
    result.trades_no = n_no
    result.volume_no = vol_no

    # Check minimum trades per leg
    if n_yes < MIN_TRADES_PER_LEG or n_no < MIN_TRADES_PER_LEG:
        result.excluded_reason = f"insufficient_trades_yes={n_yes}_no={n_no}"
        return result

    # Exclusion: leg above 0.95 (already resolved)
    if vwap_yes > EXCLUDE_LEG_ABOVE or vwap_no > EXCLUDE_LEG_ABOVE:
        result.excluded_reason = f"leg_above_{EXCLUDE_LEG_ABOVE}_yes={vwap_yes:.4f}_no={vwap_no:.4f}"
        return result

    # Compute sum and deviation
    sum_vwap = vwap_yes + vwap_no
    deviation = abs(sum_vwap - 1.00)

    result.sum_vwap = round(sum_vwap, 6)
    result.deviation = round(deviation, 6)
    result.is_flagged = deviation >= THRESHOLD_DETECTION
    result.is_sustained = deviation >= THRESHOLD_SUSTAINED

    return result


def run_scan(max_markets: int = MAX_MARKETS_PER_SCAN, fetch_limit_gamma: int = 200) -> ScanReport:
    """
    Run one complete VWAP detection scan.

    Steps:
      1. Fetch active binary markets from Gamma API
      2. Sort by volume descending (liquid markets first)
      3. For each market (up to max_markets):
         - Fetch trades from data-api.polymarket.com/trades
         - Compute VWAP_YES, VWAP_NO
         - Compute deviation |VWAP_YES + VWAP_NO - 1.00|
         - Apply exclusion rules
         - Flag if deviation >= threshold
      4. Save JSONL append-only to results/
      5. Return ScanReport with statistics
    """
    started_at = datetime.now(timezone.utc)
    scan_id = started_at.isoformat()
    start_time = time.time()

    print(f"\n{'=' * 70}")
    print(f"SENECIO H-011 — VWAP Cross-Leg Arbitrage Detector (FASE_0)")
    print(f"Scan ID: {scan_id}")
    print(f"Window: {VWAP_WINDOW_SEC}s | Threshold detection: {THRESHOLD_DETECTION} | Sustained: {THRESHOLD_SUSTAINED}")
    print(f"Exclude leg > {EXCLUDE_LEG_ABOVE} | Max markets: {max_markets}")
    print(f"{'=' * 70}")

    # Step 1: Fetch active markets from Gamma
    print(f"\n[1] Fetching active markets from Gamma (limit={fetch_limit_gamma})...")
    try:
        markets = fetch_all_active_markets(limit=fetch_limit_gamma)
    except Exception as e:
        print(f"    FAILED: {e}")
        # Return empty report on hard failure
        return ScanReport(
            scan_id=scan_id, scan_type="H-011_VWAP_DETECTOR_FASE0",
            started_at=started_at.isoformat(), finished_at=datetime.now(timezone.utc).isoformat(),
            duration_sec=round(time.time() - start_time, 2),
            window_sec=VWAP_WINDOW_SEC, threshold_detection=THRESHOLD_DETECTION,
            threshold_sustained=THRESHOLD_SUSTAINED, exclude_leg_above=EXCLUDE_LEG_ABOVE,
            max_markets=max_markets, markets_fetched=0, binary_markets=0,
            markets_scanned=0, markets_with_trades=0,
            markets_excluded_no_trades=0, markets_excluded_resolved=0,
            markets_flagged_detection=0, markets_flagged_sustained=0,
            deviation_stats={}, top_deviations=[], results=[],
        )
    print(f"    Active markets fetched: {len(markets)}")

    # Step 2: Filter for binary markets with conditionId
    binary_markets = []
    for m in markets:
        condition_id = m.get("conditionId") or m.get("condition_id")
        if not condition_id:
            continue
        # Must have exactly 2 outcomes
        prices_raw = m.get("outcomePrices", "[]")
        try:
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw
            if isinstance(prices, list) and len(prices) == 2:
                binary_markets.append(m)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

    print(f"    Binary markets with conditionId: {len(binary_markets)}")

    # Sort by volume descending
    binary_markets.sort(
        key=lambda m: float(m.get("volumeNum", 0) or 0),
        reverse=True,
    )

    # Pre-filter: skip markets where Gamma outcomePrices indicate already-resolved
    # (either leg > EXCLUDE_LEG_ABOVE). This saves API calls and focuses the scan
    # on live markets where actual price discovery is happening.
    # NOTE: We still apply the VWAP-based exclusion in analyze_market() for rigor —
    # if Gamma says 0.94 but VWAP drifted to 0.96 in the last hour, we still exclude.
    pre_filtered = []
    skipped_resolved = 0
    for m in binary_markets:
        try:
            prices_raw = m.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw
            if isinstance(prices, list) and len(prices) == 2:
                p_yes = float(prices[0])
                p_no = float(prices[1])
                if p_yes > EXCLUDE_LEG_ABOVE or p_no > EXCLUDE_LEG_ABOVE:
                    skipped_resolved += 1
                    continue
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        pre_filtered.append(m)

    print(f"    Pre-filtered (Gamma p > {EXCLUDE_LEG_ABOVE}): {len(pre_filtered)} live, {skipped_resolved} skipped as resolved")

    # Take top N from pre-filtered list
    markets_to_scan = pre_filtered[:max_markets]
    print(f"    Scanning top {len(markets_to_scan)} live markets by volume")

    # Step 3: Scan each market
    print(f"\n[2] Scanning markets (this takes ~{len(markets_to_scan) * REQUEST_DELAY_SEC:.0f}s)...")
    now_ts = int(time.time())
    after_ts = now_ts - VWAP_WINDOW_SEC

    results: list[VWAPResult] = []
    for i, m in enumerate(markets_to_scan, 1):
        condition_id = m.get("conditionId", "")
        question = (m.get("question") or "")[:60]
        vol = float(m.get("volumeNum", 0) or 0)
        print(f"  [{i:3d}/{len(markets_to_scan)}] {question[:55]:<55} vol=${vol:>10.0f} | {condition_id[:14]}...", end="")

        r = analyze_market(m, after_ts)
        results.append(r)

        if r.excluded_reason:
            print(f" → EXCLUDED ({r.excluded_reason[:40]})")
        elif r.deviation is not None:
            flag = " 🚩" if r.is_flagged else (" ⭐" if r.is_sustained else "")
            print(f" → VWAP_Y={r.vwap_yes:.4f} VWAP_N={r.vwap_no:.4f} sum={r.sum_vwap:.4f} dev={r.deviation:.4f}{flag}")

        time.sleep(REQUEST_DELAY_SEC)

    # Step 4: Compile statistics
    duration = round(time.time() - start_time, 2)
    finished_at = datetime.now(timezone.utc)

    markets_with_trades = sum(1 for r in results if r.deviation is not None)
    markets_excluded_no_trades = sum(1 for r in results if r.excluded_reason == "no_trades_in_window")
    markets_excluded_resolved = sum(1 for r in results if r.excluded_reason and r.excluded_reason.startswith("leg_above_"))
    markets_excluded_insufficient = sum(1 for r in results if r.excluded_reason and r.excluded_reason.startswith("insufficient_trades"))
    markets_flagged_detection = sum(1 for r in results if r.is_flagged)
    markets_flagged_sustained = sum(1 for r in results if r.is_sustained)

    # Deviation distribution (only for markets where deviation could be computed)
    deviations = [r.deviation for r in results if r.deviation is not None]
    if deviations:
        deviations_sorted = sorted(deviations)
        n = len(deviations_sorted)
        deviation_stats = {
            "n": n,
            "min": round(min(deviations), 6),
            "max": round(max(deviations), 6),
            "mean": round(sum(deviations) / n, 6),
            "median": round(deviations_sorted[n // 2], 6),
            "p90": round(deviations_sorted[int(n * 0.9)], 6) if n >= 10 else None,
            "above_2pp": sum(1 for d in deviations if d >= 0.02),
            "above_5pp": sum(1 for d in deviations if d >= 0.05),
        }
    else:
        deviation_stats = {"n": 0}

    # Top 10 deviations
    top = sorted(
        [r for r in results if r.deviation is not None],
        key=lambda r: r.deviation,
        reverse=True,
    )[:10]
    top_deviations = [
        {
            "condition_id": r.condition_id,
            "question": r.question,
            "vwap_yes": r.vwap_yes,
            "vwap_no": r.vwap_no,
            "sum_vwap": r.sum_vwap,
            "deviation": r.deviation,
            "trades_yes": r.trades_yes,
            "trades_no": r.trades_no,
            "volume_usd": r.volume_usd,
            "is_flagged": r.is_flagged,
            "is_sustained": r.is_sustained,
        }
        for r in top
    ]

    # Step 5: Save JSONL
    jsonl_path = RESULTS_DIR / f"scan_{started_at.strftime('%Y%m%d_%H%M%S')}.jsonl"
    with open(jsonl_path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")
    print(f"\n[3] JSONL saved: {jsonl_path}")

    # Also append a summary line to a master log
    master_log = RESULTS_DIR / "_master_log.jsonl"
    summary_line = {
        "scan_id": scan_id,
        "timestamp_utc": finished_at.isoformat(),
        "duration_sec": duration,
        "markets_scanned": len(results),
        "markets_with_trades": markets_with_trades,
        "markets_flagged_detection": markets_flagged_detection,
        "markets_flagged_sustained": markets_flagged_sustained,
        "deviation_stats": deviation_stats,
        "jsonl_file": str(jsonl_path.name),
    }
    with open(master_log, "a") as f:
        f.write(json.dumps(summary_line, ensure_ascii=False, default=str) + "\n")
    print(f"    Master log updated: {master_log}")

    # Build report
    report = ScanReport(
        scan_id=scan_id,
        scan_type="H-011_VWAP_DETECTOR_FASE0",
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_sec=duration,
        window_sec=VWAP_WINDOW_SEC,
        threshold_detection=THRESHOLD_DETECTION,
        threshold_sustained=THRESHOLD_SUSTAINED,
        exclude_leg_above=EXCLUDE_LEG_ABOVE,
        max_markets=max_markets,
        markets_fetched=len(markets),
        binary_markets=len(binary_markets),
        markets_scanned=len(results),
        markets_with_trades=markets_with_trades,
        markets_excluded_no_trades=markets_excluded_no_trades,
        markets_excluded_resolved=markets_excluded_resolved,
        markets_flagged_detection=markets_flagged_detection,
        markets_flagged_sustained=markets_flagged_sustained,
        deviation_stats=deviation_stats,
        top_deviations=top_deviations,
        results=[asdict(r) for r in results],
    )

    # Save full report JSON for human inspection
    report_path = Path("/home/z/my-project/download/h011_vwap_scan_report.json")
    with open(report_path, "w") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)
    print(f"    Full report: {report_path}")

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"SCAN SUMMARY — {scan_id}")
    print(f"{'=' * 70}")
    print(f"  Markets fetched (Gamma):    {len(markets)}")
    print(f"  Binary markets:             {len(binary_markets)}")
    print(f"  Markets scanned:            {len(results)}")
    print(f"  Markets with trades:        {markets_with_trades}")
    print(f"  Excluded (no trades):       {markets_excluded_no_trades}")
    print(f"  Excluded (leg > 0.95):      {markets_excluded_resolved}")
    print(f"  Excluded (insuff. trades):  {markets_excluded_insufficient}")
    print(f"  Flagged (dev >= 2pp):       {markets_flagged_detection}")
    print(f"  Sustained (dev >= 5pp):     {markets_flagged_sustained}")
    if deviation_stats.get("n", 0) > 0:
        print(f"\n  Deviation distribution (n={deviation_stats['n']}):")
        print(f"    min:    {deviation_stats['min']:.6f}")
        print(f"    max:    {deviation_stats['max']:.6f}")
        print(f"    mean:   {deviation_stats['mean']:.6f}")
        print(f"    median: {deviation_stats['median']:.6f}")
        if deviation_stats.get("p90") is not None:
            print(f"    p90:    {deviation_stats['p90']:.6f}")
        print(f"    above 2pp: {deviation_stats['above_2pp']}")
        print(f"    above 5pp: {deviation_stats['above_5pp']}")

    if top_deviations:
        print(f"\n  Top 5 deviations:")
        print(f"    {'Question':<40} {'VWAP_Y':>7} {'VWAP_N':>7} {'Sum':>7} {'Dev':>7} {'Flag':>5}")
        print(f"    {'-' * 80}")
        for t in top_deviations[:5]:
            flag = "🚩" if t["is_sustained"] else ("⚠" if t["is_flagged"] else "")
            print(f"    {t['question'][:38]:<38} {t['vwap_yes']:>7.4f} {t['vwap_no']:>7.4f} "
                  f"{t['sum_vwap']:>7.4f} {t['deviation']:>7.4f} {flag:>5}")

    print(f"\n  Duration: {duration}s")
    print(f"  JSONL: {jsonl_path}")
    print(f"  Master log: {master_log}")
    print(f"  Full report: {report_path}")
    print(f"{'=' * 70}\n")

    return report


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SENECIO H-011 VWAP Detector — FASE_0 (READ-ONLY)")
    parser.add_argument("--max-markets", type=int, default=MAX_MARKETS_PER_SCAN,
                        help=f"Max markets to scan (default {MAX_MARKETS_PER_SCAN})")
    parser.add_argument("--gamma-limit", type=int, default=200,
                        help="How many markets to fetch from Gamma (default 200)")
    parser.add_argument("--window", type=int, default=VWAP_WINDOW_SEC,
                        help=f"VWAP window in seconds (default {VWAP_WINDOW_SEC})")
    args = parser.parse_args()

    # Override config from CLI args
    if args.window != VWAP_WINDOW_SEC:
        print(f"⚠ Overriding VWAP_WINDOW_SEC from {VWAP_WINDOW_SEC} to {args.window}")
        VWAP_WINDOW_SEC = args.window

    print("SENECIO H-011 — VWAP Cross-Leg Arbitrage Detector")
    print("FASE_0 — READ-ONLY — NO ORDERS — NO STATE CHANGES")
    print(f"Pre-registro: window={VWAP_WINDOW_SEC}s, det>={THRESHOLD_DETECTION}, "
          f"sust>={THRESHOLD_SUSTAINED}, exclude_leg>{EXCLUDE_LEG_ABOVE}")
    print()

    report = run_scan(max_markets=args.max_markets, fetch_limit_gamma=args.gamma_limit)

    # Exit code: 0 if scan completed, 1 if no markets scanned
    sys.exit(0 if report.markets_scanned > 0 else 1)
