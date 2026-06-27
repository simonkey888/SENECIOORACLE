"""
SENECIO Polymarket Connector — H-010 Edge Detection
====================================================
Read-only connector to Polymarket Gamma API.
Fetches active election markets with P > 0.70 (favorite-longshot bias signal).

Dependencies: httpx (stdlib + httpx only)
Lines: < 100
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from typing import Optional

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
ELECTION_KW = ["election", "president", "vote", "candidate", "congress",
               "senate", "governor", "parliament", "mayor", "prime minister"]
P_THRESHOLD = 0.70       # H-010 signal threshold
MIN_VOLUME = 10_000      # H-010 minimum volume (USD)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://okgxqapbldtldmvjvzfh.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_ND41HJx4ef7JtjoDetI7RQ_P9JU-Y7Z")


def fetch_election_events(limit: int = 50) -> list[dict]:
    """Fetch active events that match election keywords."""
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{GAMMA_BASE}/events", params={"limit": limit, "active": "true", "closed": "false"})
        r.raise_for_status()
        events = r.json()
    return [e for e in events if any(kw in (e.get("title", "") + e.get("slug", "")).lower() for kw in ELECTION_KW)]


def extract_signal_markets(events: list[dict]) -> list[dict]:
    """Extract markets where YES probability > P_THRESHOLD (favorite-longshot signal)."""
    signals = []
    for ev in events:
        for m in ev.get("markets", []):
            try:
                prices = json.loads(m.get("outcomePrices", "[]"))
                if len(prices) < 2:
                    continue
                p_yes = float(prices[0])
                vol = float(m.get("volumeNum", 0))
                if p_yes >= P_THRESHOLD and vol >= MIN_VOLUME and m.get("active") and not m.get("closed"):
                    signals.append({
                        "market_id": m.get("id"), "question": m.get("question", "")[:200],
                        "p_yes": round(p_yes, 4), "p_no": round(1 - p_yes, 4),
                        "volume_usd": round(vol, 2), "end_date": m.get("endDateIso", ""),
                        "signal": "FADE_YES", "event_title": ev.get("title", "")[:100],
                        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
                        "fee_bps": int(m.get("takerBaseFee", 1000)),
                    })
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    return signals


def persist_to_supabase(signals: list[dict]) -> int:
    """Insert signal markets into Supabase polymarket_markets table."""
    if not signals:
        return 0
    with httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }, timeout=15.0) as c:
        rows = [{
            "market_id": s["market_id"], "question": s["question"],
            "p_yes": s["p_yes"], "p_no": s["p_no"],
            "volume_usd": s["volume_usd"], "end_date": s["end_date"],
            "signal": s["signal"], "event_title": s["event_title"],
            "snapshot_utc": s["snapshot_utc"], "fee_bps": s["fee_bps"],
            "outcome": None, "pnl_net": None,
        } for s in signals]
        r = c.post("/polymarket_markets", json=rows)
        r.raise_for_status()
    return len(rows)


if __name__ == "__main__":
    print("H-010 Polymarket Connector — fetching election markets...")
    events = fetch_election_events(limit=50)
    print(f"  Election events found: {len(events)}")
    signals = extract_signal_markets(events)
    print(f"  Signal markets (P_YES >= {P_THRESHOLD}, vol >= {MIN_VOLUME}): {len(signals)}")
    for s in signals[:10]:
        print(f"    {s['p_yes']:.2f} | vol={s['volume_usd']:.0f} | {s['question'][:70]}")
    if signals:
        n = persist_to_supabase(signals)
        print(f"  Persisted to Supabase: {n}")
    else:
        print("  No signals to persist.")
