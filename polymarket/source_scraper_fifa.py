"""
SENECIO source_scraper_fifa.py — FIFA WC 2026 Edge Detection
=============================================================
CORRECTED pipeline per Council directive C1 (DeepSeek).
Migrated to The Odds API per Council directive ODDS2.

Data sources (priority order):
  1. The Odds API (https://the-odds-api.com) — PRIMARY
     Bookmakers: Pinnacle (principal, lowest vig), Betfair Exchange,
                 DraftKings (tertiary for triangulation)
     Sport key:  soccer_fifa_world_cup_winner (outright)
                 soccer_fifa_world_cup (match-level when available)
  2. ESPN/Caesars scraping — FALLBACK (if Odds API unreachable)

Corrected methodology (8 steps):
  1. Obtain 1X2 decimal odds from sportsbook
  2. Convert to P_impl = 1/odds for each outcome
  3. Adjust vig: P_real = P_impl / sum(P_impl)
  4. Convert 1X2 → binary: P_binary(win) = P_real(win) / (P_real(win) + P_real(lose))
     EXCLUDE draw from denominator
  5. Obtain P_market from Polymarket (3 binary markets: win, draw, lose)
  6. Adjust vig Polymarket: P_market_real = P_market / sum(P_market_win + P_market_draw + P_market_lose)
  7. Convert PM 1X2 → binary: P_pm_binary(win) = P_market_real(win) / (P_market_real(win) + P_market_real(lose))
  8. Calculate diff = |P_pm_binary(win) - P_binary(win)| in pp
     NEVER compare raw P_market against raw P_sportsbook. NEVER.

Reviewer: InternLM + Qwen
"""
from __future__ import annotations
import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx


# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

# Load .env — walk up from this file to find project root containing .env
_ENV_PATH: Optional[Path] = None
_candidate = Path(__file__).resolve().parent
for _ in range(8):  # walk up at most 8 levels
    _check = _candidate / ".env"
    if _check.exists():
        _ENV_PATH = _check
        break
    _candidate = _candidate.parent
_ENV_VARS: dict[str, str] = {}
if _ENV_PATH and _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            _ENV_VARS[k.strip()] = v.strip()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", _ENV_VARS.get("ODDS_API_KEY", ""))
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Bookmaker priority for Odds API (lower index = higher priority)
# Pinnacle: lowest vig, most efficient market
# Betfair: exchange, near-zero vig
# DraftKings: retail book, higher vig but useful for triangulation
BOOKMAKER_PRIORITY = ["pinnacle", "betfair_exchange", "draftkings"]

# Odds API sport keys
SPORT_KEY_OUTRIGHT = "soccer_fifa_world_cup_winner"
SPORT_KEY_MATCHES = "soccer_fifa_world_cup"

# Thresholds
SIGNAL_THRESHOLD_PP = 10.0


# ═══════════════════════════════════════════════════════════════════════
# Core Math Functions (UNCHANGED — Council-approved)
# ═══════════════════════════════════════════════════════════════════════

def american_to_decimal(odds_american: int | float) -> float:
    """Convert American odds to decimal odds."""
    odds_american = int(odds_american) if isinstance(odds_american, float) and odds_american.is_integer() else odds_american
    if odds_american > 0:
        return (odds_american / 100.0) + 1.0
    elif odds_american < 0:
        return (100.0 / abs(odds_american)) + 1.0
    else:
        raise ValueError("American odds cannot be 0")


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds back to American odds."""
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100))
    elif decimal_odds > 1.0:
        return int(round(-100.0 / (decimal_odds - 1.0)))
    else:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")


def implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability: P_impl = 1/odds."""
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")
    return 1.0 / decimal_odds


def vig_adjust(p_impl_home: float, p_impl_draw: float, p_impl_away: float) -> tuple[float, float, float]:
    """
    Remove bookmaker vig / overround.
    P_real = P_impl / sum(P_impl)
    Returns (P_real_home, P_real_draw, P_real_away) that sum to 1.0
    """
    total = p_impl_home + p_impl_draw + p_impl_away
    if total <= 0:
        raise ValueError(f"Total implied probability must be > 0, got {total}")
    return (
        p_impl_home / total,
        p_impl_draw / total,
        p_impl_away / total,
    )


def convert_1x2_to_binary(p_real_home: float, p_real_draw: float, p_real_away: float) -> tuple[float, float]:
    """
    Convert 1X2 probabilities to binary (conditional on decisive result).
    P_binary(home) = P_real(home) / (P_real(home) + P_real(away))
    P_binary(away) = P_real(away) / (P_real(home) + P_real(away))
    Draw is EXCLUDED from the denominator.
    """
    decisive = p_real_home + p_real_away
    if decisive <= 0:
        raise ValueError(f"Decisive probability must be > 0, got {decisive}")
    return (
        p_real_home / decisive,
        p_real_away / decisive,
    )


# ═══════════════════════════════════════════════════════════════════════
# CORRECTED compute_fifa_diff() (UNCHANGED — Council-approved)
# ═══════════════════════════════════════════════════════════════════════

def compute_fifa_diff(
    sb_odds_home: int,
    sb_odds_draw: int,
    sb_odds_away: int,
    pm_price_home: Optional[float],
    pm_price_draw: Optional[float],
    pm_price_away: Optional[float],
    threshold_pp: float = SIGNAL_THRESHOLD_PP,
    bookmaker: str = "unknown",
) -> dict:
    """
    CORRECTED FIFA diff computation per Council directive C1.

    Vig-adjust BOTH sides. Convert 1X2 → binary on BOTH sides.
    Compare binary probabilities only.

    Parameters:
        sb_odds_home:  American odds for home win (e.g. -195, +125)
        sb_odds_draw:  American odds for draw (e.g. +265)
        sb_odds_away:  American odds for away win (e.g. +425)
        pm_price_home: Polymarket YES price for home win (0.0-1.0)
        pm_price_draw: Polymarket YES price for draw (0.0-1.0)
        pm_price_away: Polymarket YES price for away win (0.0-1.0)
        threshold_pp:  Signal threshold in percentage points (default 10.0)
        bookmaker:     Source bookmaker identifier for auditability

    Returns:
        dict with full calculation trace for auditability.
    """
    result: dict = {
        "sb_1x2": None,
        "sb_binary": None,
        "pm_1x2_raw": None,
        "pm_1x2_real": None,
        "pm_binary": None,
        "diff_binary_pp": None,
        "diff_1x2_pp": None,
        "signal": None,
        "error": None,
        "bookmaker": bookmaker,
    }

    # ─── Step 1-3: Sportsbook 1X2 with vig adjustment ──────────────
    try:
        dec_home = american_to_decimal(sb_odds_home)
        dec_draw = american_to_decimal(sb_odds_draw)
        dec_away = american_to_decimal(sb_odds_away)

        p_impl_home = implied_prob(dec_home)
        p_impl_draw = implied_prob(dec_draw)
        p_impl_away = implied_prob(dec_away)

        sb_margin = p_impl_home + p_impl_draw + p_impl_away - 1.0

        p_real_home, p_real_draw, p_real_away = vig_adjust(
            p_impl_home, p_impl_draw, p_impl_away
        )

        result["sb_1x2"] = {
            "odds_american": {"home": sb_odds_home, "draw": sb_odds_draw, "away": sb_odds_away},
            "odds_decimal": {"home": round(dec_home, 4), "draw": round(dec_draw, 4), "away": round(dec_away, 4)},
            "p_impl": {"home": round(p_impl_home, 4), "draw": round(p_impl_draw, 4), "away": round(p_impl_away, 4)},
            "margin": round(sb_margin, 4),
            "p_real": {"home": round(p_real_home, 4), "draw": round(p_real_draw, 4), "away": round(p_real_away, 4)},
        }
    except Exception as e:
        result["error"] = f"SB 1X2 conversion failed: {e}"
        return result

    # ─── Step 4: Sportsbook 1X2 → binary ───────────────────────────
    p_binary_home, p_binary_away = convert_1x2_to_binary(
        p_real_home, p_real_draw, p_real_away
    )
    result["sb_binary"] = {
        "home_win": round(p_binary_home, 4),
        "away_win": round(p_binary_away, 4),
    }

    # ─── Step 5-6: Polymarket vig adjustment ───────────────────────
    if pm_price_home is None or pm_price_draw is None or pm_price_away is None:
        result["error"] = "Missing PM data for one or more outcomes"
        result["pm_1x2_raw"] = {"home": pm_price_home, "draw": pm_price_draw, "away": pm_price_away}
        return result

    result["pm_1x2_raw"] = {
        "home": round(pm_price_home, 4),
        "draw": round(pm_price_draw, 4),
        "away": round(pm_price_away, 4),
    }

    pm_total = pm_price_home + pm_price_draw + pm_price_away
    pm_margin = pm_total - 1.0
    pm_real_home = pm_price_home / pm_total
    pm_real_draw = pm_price_draw / pm_total
    pm_real_away = pm_price_away / pm_total

    result["pm_1x2_real"] = {
        "home": round(pm_real_home, 4),
        "draw": round(pm_real_draw, 4),
        "away": round(pm_real_away, 4),
        "margin": round(pm_margin, 4),
    }

    # ─── Step 7: PM 1X2 → binary ───────────────────────────────────
    pm_binary_home, pm_binary_away = convert_1x2_to_binary(
        pm_real_home, pm_real_draw, pm_real_away
    )
    result["pm_binary"] = {
        "home_win": round(pm_binary_home, 4),
        "away_win": round(pm_binary_away, 4),
    }

    # ─── Step 8: Calculate diffs ────────────────────────────────────
    # Primary: binary diff (CORRECT methodology)
    diff_binary = abs(pm_binary_home - p_binary_home) * 100  # in pp
    result["diff_binary_pp"] = round(diff_binary, 2)

    # Also compute 1X2 diff (vig-adjusted) for reference
    diff_1x2 = abs(pm_real_home - p_real_home) * 100
    result["diff_1x2_pp"] = round(diff_1x2, 2)

    # Signal
    result["signal"] = "STOP" if diff_binary >= threshold_pp else "OK"

    return result


# ═══════════════════════════════════════════════════════════════════════
# The Odds API — PRIMARY data source
# ═══════════════════════════════════════════════════════════════════════

def fetch_odds_api_upcoming(sport_key: str = SPORT_KEY_MATCHES) -> list[dict]:
    """
    Fetch upcoming FIFA match odds from The Odds API.
    Returns list of fixture dicts with 1X2 odds per bookmaker.

    API docs: https://the-odds-api.com/liveapi/guides/v4/
    Endpoint: GET /v4/sports/{sport_key}/odds
    Params:   apiKey, regions, markets, oddsFormat, bookmakers
    """
    if not ODDS_API_KEY or ODDS_API_KEY == "REPLACE_WITH_YOUR_KEY":
        raise ValueError(
            "ODDS_API_KEY not configured. "
            "Get a free key at https://the-odds-api.com/ and set it in .env"
        )

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu,uk",           # US + EU + UK bookmakers
        "markets": "h2h,totals",          # h2h = 1X2 (head-to-head), totals = over/under
        "oddsFormat": "decimal",           # Get decimal odds directly (no American conversion needed)
        "bookmakers": ",".join(BOOKMAKER_PRIORITY),
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{ODDS_API_BASE}/sports/{sport_key}/odds", params=params)
        r.raise_for_status()
        data = r.json()

        # Track remaining API credits
        remaining = r.headers.get("x-requests-remaining", "?")
        used = r.headers.get("x-requests-used", "?")
        print(f"  [Odds API] Credits: {remaining} remaining, {used} used")

    return data


def fetch_odds_api_outright(sport_key: str = SPORT_KEY_OUTRIGHT) -> list[dict]:
    """
    Fetch FIFA WC outright winner odds from The Odds API.
    Returns list of outright market entries per bookmaker.
    """
    if not ODDS_API_KEY or ODDS_API_KEY == "REPLACE_WITH_YOUR_KEY":
        raise ValueError("ODDS_API_KEY not configured.")

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,eu,uk",
        "markets": "outright",
        "oddsFormat": "decimal",
        "bookmakers": ",".join(BOOKMAKER_PRIORITY),
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{ODDS_API_BASE}/sports/{sport_key}/odds", params=params)
        r.raise_for_status()
        data = r.json()

        remaining = r.headers.get("x-requests-remaining", "?")
        used = r.headers.get("x-requests-used", "?")
        print(f"  [Odds API] Credits: {remaining} remaining, {used} used")

    return data


def extract_1x2_from_odds_api(fixture: dict, preferred_bookmaker: str = "pinnacle") -> Optional[dict]:
    """
    Extract 1X2 (h2h) odds from an Odds API fixture.
    Returns dict with decimal odds for home/draw/away, or None.

    The Odds API returns h2h market as [home_win, draw, away_win] in decimal.
    Falls back to next bookmaker in priority if preferred is unavailable.
    """
    bookmakers = fixture.get("bookmakers", [])

    # Build priority order with preferred first
    priority = [preferred_bookmaker] + [b for b in BOOKMAKER_PRIORITY if b != preferred_bookmaker]

    for bk_key in priority:
        for bk in bookmakers:
            bk_key_norm = bk.get("key", "").lower().replace(" ", "_")
            if bk_key_norm != bk_key:
                continue

            for market in bk.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                outcomes = market.get("outcomes", [])
                if len(outcomes) < 3:
                    continue

                # Odds API h2h: outcomes are typically [Team1, Draw, Team2]
                # but order is not guaranteed — sort by name
                odds_map = {}
                for o in outcomes:
                    name = o.get("name", "").lower()
                    price = o.get("price")
                    if price is not None:
                        odds_map[name] = float(price)

                # Identify home/draw/away
                home_team = fixture.get("home_team", "").lower()
                away_team = fixture.get("away_team", "").lower()

                home_odds = None
                draw_odds = None
                away_odds = None

                for name, price in odds_map.items():
                    if name == "draw":
                        draw_odds = price
                    elif home_team and home_team in name:
                        home_odds = price
                    elif away_team and away_team in name:
                        away_odds = price
                    else:
                        # Fallback: first non-draw is home, second is away
                        if home_odds is None and name != "draw":
                            home_odds = price
                        elif away_odds is None and name != "draw":
                            away_odds = price

                if home_odds and draw_odds and away_odds:
                    # Convert decimal odds to American for compute_fifa_diff()
                    return {
                        "bookmaker": bk_key,
                        "decimal": {"home": home_odds, "draw": draw_odds, "away": away_odds},
                        "american": {
                            "home": decimal_to_american(home_odds),
                            "draw": decimal_to_american(draw_odds),
                            "away": decimal_to_american(away_odds),
                        },
                        "home_team": fixture.get("home_team", ""),
                        "away_team": fixture.get("away_team", ""),
                        "commence_time": fixture.get("commence_time", ""),
                    }

    return None


# ═══════════════════════════════════════════════════════════════════════
# Polymarket — market data retrieval
# ═══════════════════════════════════════════════════════════════════════

def fetch_polymarket_1x2(match_name: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Fetch 1X2 Polymarket prices for a given match.
    Searches Gamma API for FIFA match markets (win/draw/lose contracts).

    Returns (pm_home, pm_draw, pm_away) as raw YES prices (0.0-1.0).
    """
    # Normalize match name for search
    parts = match_name.lower().replace(" vs ", " ").split()
    if len(parts) < 2:
        return None, None, None

    team1 = parts[0]
    team2 = parts[1]

    pm_home = None
    pm_draw = None
    pm_away = None

    try:
        with httpx.Client(timeout=30.0) as c:
            # Search for FIFA markets matching the teams
            r = c.get(f"{GAMMA_BASE}/markets", params={
                "limit": 50,
                "active": "true",
                "closed": "false",
            })
            if r.status_code != 200:
                return None, None, None

            markets = r.json()
            for m in markets:
                slug = m.get("slug", "").lower()
                q = m.get("question", "").lower()

                # Check if this market relates to our match
                if "fifwc" not in slug and "fifa" not in q and "world cup" not in q:
                    continue

                # Match by team names in slug/question
                team1_in = team1 in slug or team1 in q
                team2_in = team2 in slug or team2 in q
                if not (team1_in or team2_in):
                    continue

                # Extract price
                try:
                    prices = json.loads(m.get("outcomePrices", "[]"))
                    p_yes = float(prices[0]) if prices else None
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue

                if p_yes is None:
                    continue

                # Classify market type
                if "draw" in slug or "draw" in q:
                    pm_draw = p_yes
                elif team1 in q and ("win" in q or "advance" in q):
                    pm_home = p_yes
                elif team2 in q and ("win" in q or "advance" in q):
                    pm_away = p_yes
                elif slug.endswith("-home") or slug.endswith("-eng"):
                    pm_home = p_yes
                elif slug.endswith("-away"):
                    pm_away = p_yes

    except Exception as e:
        print(f"  [PM] Error fetching markets for {match_name}: {e}")

    return pm_home, pm_draw, pm_away


# ═══════════════════════════════════════════════════════════════════════
# FALLBACK — Hardcoded ESPN/Caesars data (used when Odds API is unavailable)
# ═══════════════════════════════════════════════════════════════════════

FALLBACK_ESPN_1X2 = {
    "Brazil vs Japan":              (+125, +265, +425),
    "Netherlands vs Morocco":       (+195, +105, +300),
    "Germany vs Paraguay":          (-125, +155, +700),
    "France vs Sweden":             (-155, +190, +750),
    "Belgium vs Senegal":           (+185, +110, +300),
    "USA vs Bosnia-Herzegovina":    (-125, +155, +700),
    "England vs DR Congo":          (-150, +160, +1100),
    "Portugal vs Croatia":          (+140, +120, +400),
    "Spain vs Austria":             (-140, +155, +900),
    "Switzerland vs Algeria":       (+170, +115, +330),
    "Australia vs Egypt":           (+310, -110, +230),
    "Argentina vs Cape Verde":      (-195, +195, +1400),
    "Colombia vs Ghana":            (+105, +125, +600),
}

FALLBACK_PM_1X2 = {
    "Brazil vs Japan":              (0.5750, 0.2550, 0.1750),
    "Netherlands vs Morocco":       (0.4250, 0.3150, 0.2650),
    "Germany vs Paraguay":          (0.7250, 0.1850, 0.0950),
    "France vs Sweden":             (0.7750, 0.1450, 0.0750),
    "Belgium vs Senegal":           (0.4350, 0.2950, 0.2650),
    "USA vs Bosnia-Herzegovina":    (0.7150, 0.1850, 0.0950),
    "England vs DR Congo":          (0.7650, 0.1750, 0.0650),
    "Portugal vs Croatia":          (0.5350, 0.2750, 0.1950),
    "Spain vs Austria":             (0.7550, 0.1750, 0.0750),
    "Switzerland vs Algeria":       (None,  None,     None),
    "Australia vs Egypt":           (0.2850, 0.3350, 0.3850),
    "Argentina vs Cape Verde":      (0.8550, 0.1050, 0.0435),
    "Colombia vs Ghana":            (0.6350, 0.2450, 0.1250),
}


# ═══════════════════════════════════════════════════════════════════════
# Main Pipeline — odds_api_first with fallback
# ═══════════════════════════════════════════════════════════════════════

def run_pipeline_live() -> dict:
    """
    Run the corrected FIFA edge detection pipeline with The Odds API
    as primary data source, falling back to hardcoded ESPN/Caesars data.

    Returns a dict with:
      - source: "odds_api" or "fallback"
      - matches: list of compute_fifa_diff() results
      - summary: counts and stats
    """
    print("=" * 70)
    print("SENECIO H-010 — FIFA Edge Detection Pipeline (Odds API Primary)")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    # ─── Try Odds API first ──────────────────────────────────────────
    odds_api_fixtures = []
    source = "odds_api"

    try:
        print("\n[1] Fetching odds from The Odds API...")
        odds_api_fixtures = fetch_odds_api_upcoming(SPORT_KEY_MATCHES)
        print(f"    Fixtures found: {len(odds_api_fixtures)}")
    except Exception as e:
        print(f"    Odds API failed: {e}")
        print("    Falling back to hardcoded ESPN/Caesars data...")
        source = "fallback"

    # ─── Process matches ─────────────────────────────────────────────
    results = []

    if source == "odds_api" and odds_api_fixtures:
        # Process each fixture from Odds API
        print("\n[2] Processing Odds API fixtures...")
        for fixture in odds_api_fixtures:
            match_name = f"{fixture.get('home_team', '?')} vs {fixture.get('away_team', '?')}"
            extracted = extract_1x2_from_odds_api(fixture)

            if extracted is None:
                print(f"    {match_name}: No 1X2 odds available, skipping")
                continue

            # Get PM prices
            pm_h, pm_d, pm_a = fetch_polymarket_1x2(match_name)

            # Compute diff using corrected methodology
            r = compute_fifa_diff(
                sb_odds_home=extracted["american"]["home"],
                sb_odds_draw=extracted["american"]["draw"],
                sb_odds_away=extracted["american"]["away"],
                pm_price_home=pm_h,
                pm_price_draw=pm_d,
                pm_price_away=pm_a,
                bookmaker=extracted["bookmaker"],
            )
            r["match"] = match_name
            r["sb_source"] = "odds_api"
            r["odds_api_decimal"] = extracted["decimal"]
            r["commence_time"] = extracted.get("commence_time", "")
            results.append(r)

    else:
        # Fallback: hardcoded ESPN/Caesars data
        print("\n[2] Processing fallback ESPN/Caesars data...")
        for match_name, (ml_h, ml_d, ml_a) in FALLBACK_ESPN_1X2.items():
            pm_h, pm_d, pm_a = FALLBACK_PM_1X2.get(match_name, (None, None, None))

            r = compute_fifa_diff(
                sb_odds_home=ml_h,
                sb_odds_draw=ml_d,
                sb_odds_away=ml_a,
                pm_price_home=pm_h,
                pm_price_draw=pm_d,
                pm_price_away=pm_a,
                bookmaker="espn_caesars_fallback",
            )
            r["match"] = match_name
            r["sb_source"] = "fallback"
            results.append(r)

    # ─── Summary ─────────────────────────────────────────────────────
    stop = sum(1 for r in results if r.get("signal") == "STOP")
    ok = sum(1 for r in results if r.get("signal") == "OK")
    err = sum(1 for r in results if r.get("error") is not None)

    valid_diffs = [r["diff_binary_pp"] for r in results if r.get("diff_binary_pp") is not None]

    summary = {
        "source": source,
        "matches_total": len(results),
        "stop_signals": stop,
        "ok_signals": ok,
        "errors": err,
        "max_diff_pp": round(max(valid_diffs), 2) if valid_diffs else None,
        "mean_diff_pp": round(sum(valid_diffs) / len(valid_diffs), 2) if valid_diffs else None,
        "threshold_pp": SIGNAL_THRESHOLD_PP,
    }

    # ─── Print table ─────────────────────────────────────────────────
    print(f"\n{'Match':<30} {'Bookmaker':<12} {'Diff(bin)':>10} {'Diff(1X2)':>10} {'Signal':>8}")
    print("-" * 75)
    for r in results:
        diff_bin = f"{r['diff_binary_pp']:.2f}pp" if r.get("diff_binary_pp") is not None else "N/A"
        diff_1x2 = f"{r['diff_1x2_pp']:.2f}pp" if r.get("diff_1x2_pp") is not None else "N/A"
        signal = r.get("signal") or "ERR"
        bk = r.get("bookmaker", "?")[:12]
        name = r.get("match", "?")[:30]
        print(f"  {name:<28} {bk:<12} {diff_bin:>10} {diff_1x2:>10} {signal:>8}")

    print(f"\nSUMMARY: STOP={stop}  OK={ok}  ERR={err}  Source={source}")
    if valid_diffs:
        print(f"  Max diff: {summary['max_diff_pp']}pp  Mean: {summary['mean_diff_pp']}pp")

    # ─── Save output ─────────────────────────────────────────────────
    output = {
        "pipeline": "SENECIO_H010_FIFA",
        "methodology": "8-step corrected (vig-adj both sides, 1X2→binary both sides)",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "results": results,
        "summary": summary,
    }

    output_path = Path("/home/z/my-project/download/h010_fifa_pipeline_output.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nOutput saved: {output_path}")

    return output


# ═══════════════════════════════════════════════════════════════════════
# Consistency verification (ODDS3) — compare manual vs Odds API diffs
# ═══════════════════════════════════════════════════════════════════════

def verify_consistency(odds_api_results: list[dict]) -> dict:
    """
    Compare diffs computed from Odds API data vs manual (fallback) data.
    For each match present in both, report:
      - diff_manual (from fallback ESPN/Caesars)
      - diff_odds_api (from Odds API)
      - delta (difference between the two)
      - consistent (within 2pp tolerance)

    This addresses ODDS3: verify that Odds API diffs are consistent
    with manually corrected diffs.
    """
    # Compute manual diffs for all fallback matches
    manual_diffs = {}
    for match_name, (ml_h, ml_d, ml_a) in FALLBACK_ESPN_1X2.items():
        pm_h, pm_d, pm_a = FALLBACK_PM_1X2.get(match_name, (None, None, None))
        if pm_h is None:
            continue
        r = compute_fifa_diff(ml_h, ml_d, ml_a, pm_h, pm_d, pm_a)
        manual_diffs[match_name] = r.get("diff_binary_pp")

    # Compare with Odds API results
    comparisons = []
    for r in odds_api_results:
        match_name = r.get("match", "")
        diff_api = r.get("diff_binary_pp")
        diff_manual = manual_diffs.get(match_name)

        if diff_api is not None and diff_manual is not None:
            delta = round(diff_api - diff_manual, 2)
            consistent = abs(delta) <= 2.0  # 2pp tolerance
        else:
            delta = None
            consistent = None

        comparisons.append({
            "partido": match_name,
            "diff_manual_pp": diff_manual,
            "diff_odds_api_pp": diff_api,
            "delta_pp": delta,
            "consistent": consistent,
        })

    return {
        "verification_type": "ODDS3_consistency_check",
        "tolerance_pp": 2.0,
        "comparisons": comparisons,
        "consistent_count": sum(1 for c in comparisons if c["consistent"] is True),
        "inconsistent_count": sum(1 for c in comparisons if c["consistent"] is False),
        "no_match_count": sum(1 for c in comparisons if c["consistent"] is None),
    }


# ═══════════════════════════════════════════════════════════════════════
# Batch recalculation from existing monitoring data (legacy support)
# ═══════════════════════════════════════════════════════════════════════

def recalculate_r32_matches(
    data_path: str = "/home/z/my-project/download/h010_fifa_r32_monitoring_final.json",
) -> list[dict]:
    """
    Recalculate all R32 matches from existing monitoring data using corrected methodology.
    Produces C2 table: partido, P_sportsbook_binario, P_market_real, diff_corregido,
    diff_reportado_anterior, error_detectado.
    """
    p = Path(data_path)
    if not p.exists():
        print(f"  [WARN] Data file not found: {data_path}")
        return []

    with open(p) as f:
        data = json.load(f)

    results = []
    for match in data["results"]:
        name = match["match"]
        sb = match["sb_1x2"]
        pm = match["pm_1x2"]
        old_max = match.get("max_diff_pp")

        # Skip if no PM data
        if pm["home"] is None or pm["draw"] is None or pm["away"] is None:
            results.append({
                "partido": name,
                "P_sportsbook_binario": None,
                "P_market_real": None,
                "diff_corregido": None,
                "diff_reportado_anterior": old_max,
                "error_detectado": None,
                "signal": "N/A",
            })
            continue

        # SB P_real (already vig-adjusted in source)
        p_sb_h, p_sb_d, p_sb_a = sb["home"], sb["draw"], sb["away"]

        # SB 1X2 → binary
        p_sb_bin_h = p_sb_h / (p_sb_h + p_sb_a)

        # PM vig-adjust
        pm_h, pm_d, pm_a = pm["home"], pm["draw"], pm["away"]
        pm_total = pm_h + pm_d + pm_a
        pm_real_h = pm_h / pm_total
        pm_real_d = pm_d / pm_total
        pm_real_a = pm_a / pm_total

        # PM 1X2 → binary
        pm_bin_h = pm_real_h / (pm_real_h + pm_real_a)

        # Diffs
        diff_corrected = round(abs(pm_bin_h - p_sb_bin_h) * 100, 2)
        diff_old = old_max if old_max else 0
        error = round(diff_old - diff_corrected, 2)

        results.append({
            "partido": name,
            "P_sportsbook_binario": round(p_sb_bin_h, 4),
            "P_market_real": round(pm_real_h, 4),
            "diff_corregido": diff_corrected,
            "diff_reportado_anterior": diff_old,
            "error_detectado": error,
            "signal": "STOP" if diff_corrected >= 10.0 else "OK",
        })

    return results


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Demo: single match with corrected methodology
    print("SENECIO source_scraper_fifa.py — Corrected + Odds API Pipeline")
    print("=" * 60)

    print("\nDemo: Argentina vs Cape Verde (fallback data)")
    r = compute_fifa_diff(
        sb_odds_home=-195,
        sb_odds_draw=195,
        sb_odds_away=1400,
        pm_price_home=0.855,
        pm_price_draw=0.105,
        pm_price_away=0.0435,
    )
    print(f"  SB 1X2 (vig-adj): {r['sb_1x2']['p_real']}")
    print(f"  SB binary:        {r['sb_binary']}")
    print(f"  PM 1X2 (vig-adj): {r['pm_1x2_real']}")
    print(f"  PM binary:        {r['pm_binary']}")
    print(f"  Diff binary:      {r['diff_binary_pp']}pp")
    print(f"  Diff 1X2:         {r['diff_1x2_pp']}pp")
    print(f"  Signal:           {r['signal']}")

    # Run full pipeline (Odds API or fallback)
    print("\n\n" + "=" * 60)
    output = run_pipeline_live()

    # If we have Odds API data, verify consistency
    if output["source"] == "odds_api" and output["results"]:
        print("\n\nODDS3: Consistency verification")
        print("-" * 60)
        verify = verify_consistency(output["results"])
        for c in verify["comparisons"]:
            status = "OK" if c["consistent"] else "MISMATCH" if c["consistent"] is False else "N/A"
            dm = f"{c['diff_manual_pp']:.2f}" if c["diff_manual_pp"] is not None else "N/A"
            da = f"{c['diff_odds_api_pp']:.2f}" if c["diff_odds_api_pp"] is not None else "N/A"
            dl = f"{c['delta_pp']:+.2f}" if c["delta_pp"] is not None else "N/A"
            print(f"  {c['partido']:<28} manual={dm:>7}pp  api={da:>7}pp  delta={dl:>7}pp  [{status}]")
    else:
        # Show legacy C2/C3 batch recalculation
        print("\n\nC2/C3: Batch recalculation from legacy data")
        print("-" * 60)
        results = recalculate_r32_matches()
        if results:
            stop = sum(1 for r in results if r["signal"] == "STOP")
            ok = sum(1 for r in results if r["signal"] == "OK")
            na = sum(1 for r in results if r["signal"] == "N/A")

            for r in results:
                if r.get("diff_corregido") is not None:
                    print(f"  {r['partido']:<28} diff_corr={r['diff_corregido']:>6.2f}pp  old={r['diff_reportado_anterior']:>6.2f}pp  error={r['error_detectado']:>6.2f}pp  {r['signal']}")
                else:
                    print(f"  {r['partido']:<28} NO PM DATA")

            print(f"\nC3: STOP={stop}  OK={ok}  N/A={na}")
            print(f"VERDICT: {'ARCHIVAR' if stop == 0 else 'INVESTIGAR MAS'}")
        else:
            print("  No legacy data file found. Run with Odds API instead.")
