"""
SENECIO Portfolio Trader — H-010_PORTFOLIO
============================================
Multi-domain portfolio strategy using fractional Kelly sizing.

Sakana-approved parameters:
  - Kelly fraction: 1/4 (quarter-Kelly)
  - Position size: 1-2.5% of bankroll per trade
  - Signal thresholds by domain:
      Sports:       5 pp
      Politics:     6-7 pp
      Entertainment: 3-4 pp
  - n=50 trades for statistical validation
  - PAPER TRADING ONLY — no real capital

Signal sources:
  1. source_scraper_fifa.py  → sports (FIFA WC 1X2 → binary edge)
  2. polymarket_connector.py → politics (favorite-longshot bias)
  3. Entertainment markets   → future integration

Dependencies: httpx, source_scraper_fifa, polymarket_connector
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx


# ═══════════════════════════════════════════════════════════════════════
# Domain Configuration — Sakana Parameters
# ═══════════════════════════════════════════════════════════════════════

class Domain(Enum):
    SPORTS = "sports"
    POLITICS = "politics"
    ENTERTAINMENT = "entertainment"


# Per-domain thresholds and confidence factors
DOMAIN_CONFIG = {
    Domain.SPORTS: {
        "threshold_pp": 5.0,
        "threshold_pp_max": 10.0,      # beyond this, signal strength doesn't increase
        "confidence_factor": 0.80,      # sports markets are fairly efficient
        "max_position_pct": 2.5,       # max % of bankroll per trade
        "min_position_pct": 1.0,       # min % of bankroll per trade
        "description": "FIFA WC, major leagues — moderate efficiency",
    },
    Domain.POLITICS: {
        "threshold_pp": 6.5,
        "threshold_pp_max": 12.0,
        "confidence_factor": 0.70,      # political markets have more noise
        "max_position_pct": 2.0,
        "min_position_pct": 1.0,
        "description": "National elections — favorite-longshot bias documented",
    },
    Domain.ENTERTAINMENT: {
        "threshold_pp": 3.5,
        "threshold_pp_max": 8.0,
        "confidence_factor": 0.60,      # least efficient, most volatile
        "max_position_pct": 1.5,
        "min_position_pct": 0.5,
        "description": "Awards, reality TV — low liquidity, high edge potential",
    },
}

# Kelly fraction (quarter-Kelly per Sakana)
KELLY_FRACTION = 0.25

# Default bankroll for paper trading (USD)
DEFAULT_BANKROLL = 10_000.0

# Minimum number of trades for validation
N_MIN_VALIDATION = 50

# Polymarket fee (default taker fee in bps)
DEFAULT_FEE_BPS = 1000  # 10%


# ═══════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """A single trading signal from any source."""
    source: str                     # e.g. "fifa_pipeline", "election_fade"
    domain: Domain
    market_id: str                  # Polymarket market ID or fixture ID
    description: str                # Human-readable description
    diff_pp: float                  # Edge in percentage points
    p_our: float                    # Our estimated probability
    p_market: float                 # Market implied probability
    direction: str                  # "BUY_YES" or "BUY_NO"
    bookmaker: str = ""            # Source bookmaker (for sports)
    snapshot_utc: str = ""
    fee_bps: int = DEFAULT_FEE_BPS
    volume_usd: float = 0.0
    raw_data: dict = field(default_factory=dict)


@dataclass
class Position:
    """A paper trade position."""
    signal: Signal
    size_usd: float                 # Position size in USD
    size_pct_bankroll: float        # Position size as % of bankroll
    kelly_full: float               # Full Kelly fraction computed
    kelly_quarter: float            # Quarter-Kelly used
    entry_price: float              # Price at entry (0-1)
    status: str = "OPEN"            # OPEN, CLOSED_WIN, CLOSED_LOSS, VOIDED
    exit_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    closed_utc: Optional[str] = None


@dataclass
class PortfolioState:
    """Current state of the paper trading portfolio."""
    bankroll: float = DEFAULT_BANKROLL
    initial_bankroll: float = DEFAULT_BANKROLL
    positions: list[Position] = field(default_factory=list)
    closed_positions: list[Position] = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0


# ═══════════════════════════════════════════════════════════════════════
# Core Sizing Logic — Fractional Kelly
# ═══════════════════════════════════════════════════════════════════════

def compute_kelly_fraction(
    p_our: float,
    p_market: float,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> float:
    """
    Compute full Kelly fraction for a binary bet.

    Kelly formula for binary outcomes:
      f* = (b*p - q) / b
    where:
      p = our estimated probability of winning
      q = 1 - p
      b = net odds received (payout per unit bet)

    For Polymarket binary markets:
      If buying YES at price P_market:
        b = (1 - P_market - fee) / P_market
        p = P_our
    """
    fee = fee_bps / 10_000.0  # convert bps to decimal

    # Net payout if we buy YES at p_market and win
    payout_if_win = 1.0 - p_market - fee
    payout_if_lose = -p_market

    if payout_if_win <= 0:
        return 0.0  # no edge after fees

    b = payout_if_win / p_market  # net odds

    # Kelly: f* = (b*p - q) / b
    p = p_our
    q = 1.0 - p
    kelly = (b * p - q) / b

    return max(0.0, kelly)


def compute_position_size(
    signal: Signal,
    bankroll: float,
) -> Position:
    """
    Compute position size using quarter-Kelly with domain confidence factor.

    Steps:
    1. Compute full Kelly fraction from edge
    2. Apply quarter-Kelly (f_used = kelly * 1/4)
    3. Apply domain confidence factor (f_used *= confidence_factor)
    4. Clamp to domain min/max position size
    5. Convert to USD position size
    """
    domain_cfg = DOMAIN_CONFIG[signal.domain]

    # Step 1: Full Kelly
    kelly_full = compute_kelly_fraction(
        p_our=signal.p_our,
        p_market=signal.p_market,
        fee_bps=signal.fee_bps,
    )

    # Step 2: Quarter-Kelly
    kelly_quarter = kelly_full * KELLY_FRACTION

    # Step 3: Domain confidence factor
    f_adjusted = kelly_quarter * domain_cfg["confidence_factor"]

    # Step 4: Clamp to domain min/max
    size_pct = f_adjusted * 100.0  # convert to percentage
    size_pct = max(domain_cfg["min_position_pct"],
                   min(domain_cfg["max_position_pct"], size_pct))

    # Edge-based scaling: if edge is just at threshold, use minimum;
    # scale up linearly to max as edge approaches threshold_pp_max
    threshold = domain_cfg["threshold_pp"]
    threshold_max = domain_cfg["threshold_pp_max"]
    if signal.diff_pp < threshold:
        # Below threshold — no trade
        size_pct = 0.0
    elif signal.diff_pp < threshold_max:
        # Linear interpolation between min and max
        edge_ratio = (signal.diff_pp - threshold) / (threshold_max - threshold)
        scaled_pct = domain_cfg["min_position_pct"] + \
                     edge_ratio * (domain_cfg["max_position_pct"] - domain_cfg["min_position_pct"])
        size_pct = min(size_pct, scaled_pct)

    # Step 5: Convert to USD
    size_usd = bankroll * (size_pct / 100.0)

    # Entry price is the market price
    entry_price = signal.p_market if signal.direction == "BUY_YES" else (1.0 - signal.p_market)

    return Position(
        signal=signal,
        size_usd=round(size_usd, 2),
        size_pct_bankroll=round(size_pct, 4),
        kelly_full=round(kelly_full, 6),
        kelly_quarter=round(kelly_quarter, 6),
        entry_price=round(entry_price, 4),
    )


# ═══════════════════════════════════════════════════════════════════════
# Signal Sources — FIFA Pipeline Integration
# ═══════════════════════════════════════════════════════════════════════

def fetch_fifa_signals() -> list[Signal]:
    """
    Fetch signals from the corrected FIFA pipeline (source_scraper_fifa.py).

    Uses the Odds API as primary source, fallback to hardcoded ESPN/Caesars.
    Converts compute_fifa_diff() results into Signal objects for the portfolio.
    """
    from source_scraper_fifa import (
        compute_fifa_diff,
        run_pipeline_live,
        fetch_odds_api_upcoming,
        extract_1x2_from_odds_api,
        fetch_polymarket_1x2,
        FALLBACK_ESPN_1X2,
        FALLBACK_PM_1X2,
        SIGNAL_THRESHOLD_PP,
    )

    signals: list[Signal] = []

    # ─── Try Odds API first ──────────────────────────────────────────
    try:
        fixtures = fetch_odds_api_upcoming()
        for fixture in fixtures:
            match_name = f"{fixture.get('home_team', '?')} vs {fixture.get('away_team', '?')}"
            extracted = extract_1x2_from_odds_api(fixture, "pinnacle")
            if extracted is None:
                extracted = extract_1x2_from_odds_api(fixture, "draftkings")
            if extracted is None:
                continue

            pm_h, pm_d, pm_a = fetch_polymarket_1x2(match_name)

            result = compute_fifa_diff(
                sb_odds_home=extracted["american"]["home"],
                sb_odds_draw=extracted["american"]["draw"],
                sb_odds_away=extracted["american"]["away"],
                pm_price_home=pm_h,
                pm_price_draw=pm_d,
                pm_price_away=pm_a,
                bookmaker=extracted["bookmaker"],
            )

            if result.get("error") is not None:
                continue

            diff_pp = result.get("diff_binary_pp", 0) or 0
            if diff_pp < DOMAIN_CONFIG[Domain.SPORTS]["threshold_pp"]:
                continue  # below sports threshold

            # Determine direction: if PM overestimates home, buy NO (away);
            # if PM underestimates home, buy YES (home)
            sb_bin = result.get("sb_binary", {})
            pm_bin = result.get("pm_binary", {})
            sb_home = sb_bin.get("home_win", 0)
            pm_home = pm_bin.get("home_win", 0)

            if sb_home > pm_home:
                # Sportsbook thinks home is more likely than PM → buy YES home
                direction = "BUY_YES"
                p_our = sb_home
                p_market = pm_home
            else:
                # PM thinks home is more likely → buy NO home (i.e. away)
                direction = "BUY_NO"
                p_our = 1.0 - pm_home
                p_market = 1.0 - sb_home

            signals.append(Signal(
                source="fifa_odds_api",
                domain=Domain.SPORTS,
                market_id=fixture.get("id", match_name),
                description=f"FIFA WC: {match_name}",
                diff_pp=diff_pp,
                p_our=round(p_our, 4),
                p_market=round(p_market, 4),
                direction=direction,
                bookmaker=extracted["bookmaker"],
                snapshot_utc=datetime.now(timezone.utc).isoformat(),
                volume_usd=0.0,  # PM volume not easily available per fixture
                raw_data={
                    "sb_1x2": result.get("sb_1x2"),
                    "pm_1x2_real": result.get("pm_1x2_real"),
                    "sb_binary": sb_bin,
                    "pm_binary": pm_bin,
                    "odds_api_decimal": extracted["decimal"],
                },
            ))

    except Exception as e:
        print(f"  [FIFA Odds API] Error: {e}")
        print("  Falling back to hardcoded data...")

        # Fallback: use hardcoded ESPN/Caesars data
        for match_name, (ml_h, ml_d, ml_a) in FALLBACK_ESPN_1X2.items():
            pm_h, pm_d, pm_a = FALLBACK_PM_1X2.get(match_name, (None, None, None))
            if pm_h is None:
                continue

            result = compute_fifa_diff(ml_h, ml_d, ml_a, pm_h, pm_d, pm_a,
                                       bookmaker="espn_caesars_fallback")

            if result.get("error") is not None:
                continue

            diff_pp = result.get("diff_binary_pp", 0) or 0
            if diff_pp < DOMAIN_CONFIG[Domain.SPORTS]["threshold_pp"]:
                continue

            sb_bin = result.get("sb_binary", {})
            pm_bin = result.get("pm_binary", {})
            sb_home = sb_bin.get("home_win", 0)
            pm_home = pm_bin.get("home_win", 0)

            if sb_home > pm_home:
                direction = "BUY_YES"
                p_our = sb_home
                p_market = pm_home
            else:
                direction = "BUY_NO"
                p_our = 1.0 - pm_home
                p_market = 1.0 - sb_home

            signals.append(Signal(
                source="fifa_fallback",
                domain=Domain.SPORTS,
                market_id=match_name,
                description=f"FIFA WC (fallback): {match_name}",
                diff_pp=diff_pp,
                p_our=round(p_our, 4),
                p_market=round(p_market, 4),
                direction=direction,
                bookmaker="espn_caesars_fallback",
                snapshot_utc=datetime.now(timezone.utc).isoformat(),
                raw_data={
                    "sb_1x2": result.get("sb_1x2"),
                    "pm_1x2_real": result.get("pm_1x2_real"),
                    "sb_binary": sb_bin,
                    "pm_binary": pm_bin,
                },
            ))

    return signals


def fetch_election_signals() -> list[Signal]:
    """
    Fetch signals from the Polymarket election connector.

    The election connector uses a P_THRESHOLD of 0.70 for favorite-longshot
    bias detection. We convert these to portfolio signals with domain=POLITICS.
    """
    from polymarket_connector import fetch_election_events, extract_signal_markets

    signals: list[Signal] = []

    try:
        events = fetch_election_events(limit=50)
        market_signals = extract_signal_markets(events)

        for ms in market_signals:
            # For favorite-longshot: fade the favorite (buy NO)
            # Our estimate: P_our = 1 - p_yes (we think the favorite is overpriced)
            p_market_yes = ms["p_yes"]
            p_our_no = 1.0 - p_market_yes  # our estimate for NO

            # Edge in pp: difference between our estimate and market
            diff_pp = abs(p_market_yes - (1.0 - p_our_no)) * 100

            if diff_pp < DOMAIN_CONFIG[Domain.POLITICS]["threshold_pp"]:
                continue

            signals.append(Signal(
                source="election_fade",
                domain=Domain.POLITICS,
                market_id=ms["market_id"],
                description=ms["question"][:100],
                diff_pp=round(diff_pp, 2),
                p_our=round(p_our_no, 4),
                p_market=round(1.0 - p_market_yes, 4),
                direction="BUY_NO",  # always fade the favorite
                snapshot_utc=ms["snapshot_utc"],
                fee_bps=ms.get("fee_bps", DEFAULT_FEE_BPS),
                volume_usd=ms.get("volume_usd", 0.0),
                raw_data=ms,
            ))

    except Exception as e:
        print(f"  [Election] Error: {e}")

    return signals


# ═══════════════════════════════════════════════════════════════════════
# Portfolio Manager
# ═══════════════════════════════════════════════════════════════════════

class PortfolioManager:
    """
    Paper trading portfolio manager.

    Manages positions across multiple domains using fractional Kelly sizing.
    Tracks PnL, win rate, and validation progress toward n=50.
    """

    def __init__(self, bankroll: float = DEFAULT_BANKROLL,
                 state_path: Optional[str] = None):
        self.state_path = state_path or str(
            Path(__file__).parent / "portfolio_state.json"
        )
        self.state = self._load_state(bankroll)

    def _load_state(self, bankroll: float) -> PortfolioState:
        """Load portfolio state from disk, or initialize new."""
        p = Path(self.state_path)
        if p.exists():
            try:
                data = json.loads(p.read_text())
                state = PortfolioState(
                    bankroll=data.get("bankroll", bankroll),
                    initial_bankroll=data.get("initial_bankroll", bankroll),
                    total_trades=data.get("total_trades", 0),
                    winning_trades=data.get("winning_trades", 0),
                    total_pnl=data.get("total_pnl", 0.0),
                )
                # Reconstruct closed positions
                for cp in data.get("closed_positions", []):
                    sig_data = cp.get("signal", {})
                    sig = Signal(
                        source=sig_data.get("source", ""),
                        domain=Domain(sig_data.get("domain", "sports")),
                        market_id=sig_data.get("market_id", ""),
                        description=sig_data.get("description", ""),
                        diff_pp=sig_data.get("diff_pp", 0),
                        p_our=sig_data.get("p_our", 0),
                        p_market=sig_data.get("p_market", 0),
                        direction=sig_data.get("direction", ""),
                        bookmaker=sig_data.get("bookmaker", ""),
                        snapshot_utc=sig_data.get("snapshot_utc", ""),
                        fee_bps=sig_data.get("fee_bps", DEFAULT_FEE_BPS),
                        volume_usd=sig_data.get("volume_usd", 0),
                    )
                    pos = Position(
                        signal=sig,
                        size_usd=cp.get("size_usd", 0),
                        size_pct_bankroll=cp.get("size_pct_bankroll", 0),
                        kelly_full=cp.get("kelly_full", 0),
                        kelly_quarter=cp.get("kelly_quarter", 0),
                        entry_price=cp.get("entry_price", 0),
                        status=cp.get("status", "OPEN"),
                        exit_price=cp.get("exit_price"),
                        pnl_usd=cp.get("pnl_usd"),
                        pnl_pct=cp.get("pnl_pct"),
                        closed_utc=cp.get("closed_utc"),
                    )
                    state.closed_positions.append(pos)
                return state
            except Exception:
                pass

        return PortfolioState(bankroll=bankroll, initial_bankroll=bankroll)

    def save_state(self) -> None:
        """Persist portfolio state to disk."""
        data = {
            "bankroll": self.state.bankroll,
            "initial_bankroll": self.state.initial_bankroll,
            "total_trades": self.state.total_trades,
            "winning_trades": self.state.winning_trades,
            "total_pnl": self.state.total_pnl,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "open_positions": [
                {
                    "signal": asdict(pos.signal),
                    "size_usd": pos.size_usd,
                    "size_pct_bankroll": pos.size_pct_bankroll,
                    "kelly_full": pos.kelly_full,
                    "kelly_quarter": pos.kelly_quarter,
                    "entry_price": pos.entry_price,
                    "status": pos.status,
                }
                for pos in self.state.positions
            ],
            "closed_positions": [
                {
                    "signal": asdict(pos.signal),
                    "size_usd": pos.size_usd,
                    "size_pct_bankroll": pos.size_pct_bankroll,
                    "kelly_full": pos.kelly_full,
                    "kelly_quarter": pos.kelly_quarter,
                    "entry_price": pos.entry_price,
                    "status": pos.status,
                    "exit_price": pos.exit_price,
                    "pnl_usd": pos.pnl_usd,
                    "pnl_pct": pos.pnl_pct,
                    "closed_utc": pos.closed_utc,
                }
                for pos in self.state.closed_positions
            ],
        }
        Path(self.state_path).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def process_signals(self, signals: list[Signal]) -> list[Position]:
        """
        Process a batch of signals, compute position sizes, and open positions.

        Rules:
        - Skip signals below domain threshold
        - Skip if already have an open position on same market
        - Size using quarter-Kelly with domain confidence factor
        - Max total exposure: 10% of bankroll
        """
        new_positions: list[Position] = []

        # Current total exposure
        total_exposure = sum(p.size_usd for p in self.state.positions)
        max_total_exposure = self.state.bankroll * 0.10

        # Existing open market IDs
        open_markets = {p.signal.market_id for p in self.state.positions}

        for signal in signals:
            # Skip if already have position on this market
            if signal.market_id in open_markets:
                continue

            # Compute position size
            position = compute_position_size(signal, self.state.bankroll)

            # Skip if size is zero (below threshold)
            if position.size_usd <= 0:
                continue

            # Check total exposure limit
            if total_exposure + position.size_usd > max_total_exposure:
                # Reduce size to fit within limit
                available = max_total_exposure - total_exposure
                if available < 1.0:  # minimum position $1
                    continue
                position.size_usd = round(available, 2)
                position.size_pct_bankroll = round(available / self.state.bankroll * 100, 4)

            self.state.positions.append(position)
            open_markets.add(signal.market_id)
            total_exposure += position.size_usd
            new_positions.append(position)

        return new_positions

    def close_position(self, market_id: str, outcome: str,
                       exit_price: float) -> Optional[Position]:
        """
        Close a position with the given outcome.

        Args:
            market_id: Market to close
            outcome: "WIN", "LOSS", or "VOID"
            exit_price: Price at exit (0-1)
        """
        for i, pos in enumerate(self.state.positions):
            if pos.signal.market_id != market_id:
                continue

            pos.exit_price = round(exit_price, 4)
            pos.closed_utc = datetime.now(timezone.utc).isoformat()

            if outcome == "VOID":
                pos.status = "VOIDED"
                pos.pnl_usd = 0.0
                pos.pnl_pct = 0.0
            elif outcome == "WIN":
                pos.status = "CLOSED_WIN"
                fee = pos.signal.fee_bps / 10_000.0
                payout = pos.size_usd * (1.0 - fee)
                profit = payout - pos.size_usd * pos.entry_price
                pos.pnl_usd = round(profit, 4)
                pos.pnl_pct = round(profit / pos.size_usd * 100, 4) if pos.size_usd > 0 else 0
                self.state.winning_trades += 1
            else:  # LOSS
                pos.status = "CLOSED_LOSS"
                loss = -(pos.size_usd * pos.entry_price)
                pos.pnl_usd = round(loss, 4)
                pos.pnl_pct = round(loss / pos.size_usd * 100, 4) if pos.size_usd > 0 else 0

            self.state.total_trades += 1
            self.state.total_pnl += pos.pnl_usd or 0
            self.state.bankroll += pos.pnl_usd or 0

            # Move to closed
            self.state.positions.pop(i)
            self.state.closed_positions.append(pos)
            self.save_state()
            return pos

        return None

    def get_summary(self) -> dict:
        """Compute portfolio summary statistics."""
        total = self.state.total_trades
        wins = self.state.winning_trades
        pnl = self.state.total_pnl
        initial = self.state.initial_bankroll
        current = self.state.bankroll

        open_count = len(self.state.positions)
        open_exposure = sum(p.size_usd for p in self.state.positions)

        # Per-domain breakdown
        domain_stats = {}
        for domain in Domain:
            closed = [p for p in self.state.closed_positions
                      if p.signal.domain == domain]
            d_wins = sum(1 for p in closed if p.status == "CLOSED_WIN")
            d_total = len(closed)
            d_pnl = sum(p.pnl_usd or 0 for p in closed)
            domain_stats[domain.value] = {
                "total": d_total,
                "wins": d_wins,
                "win_rate": round(d_wins / d_total, 4) if d_total > 0 else None,
                "pnl_usd": round(d_pnl, 2),
                "avg_size_usd": round(
                    sum(p.size_usd for p in closed) / d_total, 2
                ) if d_total > 0 else None,
            }

        return {
            "bankroll_current": round(current, 2),
            "bankroll_initial": round(initial, 2),
            "return_pct": round((current - initial) / initial * 100, 4),
            "total_trades": total,
            "winning_trades": wins,
            "win_rate": round(wins / total, 4) if total > 0 else None,
            "total_pnl": round(pnl, 2),
            "avg_pnl_per_trade": round(pnl / total, 4) if total > 0 else None,
            "open_positions": open_count,
            "open_exposure_usd": round(open_exposure, 2),
            "open_exposure_pct": round(open_exposure / current * 100, 2),
            "validation_progress": f"{total}/{N_MIN_VALIDATION}",
            "validation_complete": total >= N_MIN_VALIDATION,
            "domain_breakdown": domain_stats,
        }

    def print_dashboard(self) -> None:
        """Print a portfolio dashboard to stdout."""
        summary = self.get_summary()

        print("=" * 65)
        print("SENECIO H-010_PORTFOLIO — Paper Trading Dashboard")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 65)

        print(f"\n  Bankroll:   ${summary['bankroll_current']:,.2f} "
              f"(initial: ${summary['bankroll_initial']:,.2f}, "
              f"return: {summary['return_pct']:+.2f}%)")
        print(f"  Total PnL:  ${summary['total_pnl']:,.2f}")
        print(f"  Trades:     {summary['total_trades']} "
              f"(W:{summary['winning_trades']} "
              f"WR:{summary['win_rate'] or 'N/A'})")
        print(f"  Open:       {summary['open_positions']} positions, "
              f"${summary['open_exposure_usd']:,.2f} exposure "
              f"({summary['open_exposure_pct']}%)")
        print(f"  Validation: {summary['validation_progress']} "
              f"{'✓ COMPLETE' if summary['validation_complete'] else ''}")

        # Open positions
        if self.state.positions:
            print(f"\n  Open Positions:")
            for pos in self.state.positions:
                s = pos.signal
                print(f"    [{s.domain.value:13}] {s.description[:40]:<40} "
                      f"${pos.size_usd:>7.2f} ({pos.size_pct_bankroll:.2f}%) "
                      f"edge={s.diff_pp:.1f}pp {s.direction}")

        # Domain breakdown
        print(f"\n  Domain Breakdown:")
        for domain, stats in summary["domain_breakdown"].items():
            wr = f"{stats['win_rate']:.1%}" if stats['win_rate'] else "N/A"
            print(f"    {domain:13}: {stats['total']} trades, "
                  f"WR={wr}, PnL=${stats['pnl_usd']:,.2f}")


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("SENECIO H-010_PORTFOLIO — Portfolio Trader (Paper Trading Only)")
    print("=" * 65)

    pm = PortfolioManager()

    # Fetch signals from all sources
    print("\n[1] Fetching FIFA signals...")
    fifa_signals = fetch_fifa_signals()
    print(f"    FIFA signals above threshold: {len(fifa_signals)}")

    print("\n[2] Fetching election signals...")
    election_signals = fetch_election_signals()
    print(f"    Election signals above threshold: {len(election_signals)}")

    # Combine all signals
    all_signals = fifa_signals + election_signals
    print(f"\n[3] Total signals: {len(all_signals)}")

    # Process signals
    if all_signals:
        new_positions = pm.process_signals(all_signals)
        print(f"    New positions opened: {len(new_positions)}")
        for pos in new_positions:
            s = pos.signal
            print(f"      [{s.domain.value}] {s.description[:40]} "
                  f"${pos.size_usd:.2f} ({pos.size_pct_bankroll:.2f}%) "
                  f"edge={s.diff_pp:.1f}pp Kelly={pos.kelly_full:.4f}")

    # Print dashboard
    pm.print_dashboard()

    # Save state
    pm.save_state()
    print(f"\nState saved to: {pm.state_path}")

    # Validation progress
    summary = pm.get_summary()
    if summary["validation_complete"]:
        print("\n*** VALIDATION COMPLETE — Ready for GO/NO-GO evaluation ***")
    else:
        remaining = N_MIN_VALIDATION - summary["total_trades"]
        print(f"\n    {remaining} trades remaining for validation (n={N_MIN_VALIDATION})")
