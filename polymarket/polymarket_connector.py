"""
SENECIO Polymarket Connector — H-010 Edge Detection
====================================================
Read-only connector to Polymarket Gamma API.
Fetches active markets across configurable categories.
Signal: abs(P_our_estimate - P_market) >= 0.10 (10pp difference).

Dependencies: httpx only
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
DEFAULT_CATEGORIES = ["Sports", "Politics", "Business"]
CATEGORY_KEYWORDS = {
    "Sports": ["nfl ", " mlb", " nba", " nhl", "super bowl", "world series",
               "tour de france", "wimbledon", "ufc ", "bellator",
               "home run", "touchdown", "pennant", "cy young",
               "all-star game", "stanley cup",
               "premier league", "la liga", "champions league",
               "f1 ", "formula 1", "motogp", "world cup",
               "tush push"],
    "Politics": ["election", "president", "vote", "candidate", "congress",
                 "senate", "governor", "parliament", "mayor", "prime minister"],
    "Business": ["ipo", "fda", "acquisition", "merger", "approve", "regulation",
                 "sec", "fed", "interest rate", "launch", "release date"],
}
MIN_VOLUME = 10_000      # H-010 minimum volume (USD)
SIGNAL_THRESHOLD = 0.10  # H-010: 10pp difference vs market
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://okgxqapbldtldmvjvzfh.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_ND41HJx4ef7JtjoDetI7RQ_P9JU-Y7Z")


def fetch_events(limit: int = 100, offset: int = 0) -> list[dict]:
    """Fetch active events from Gamma API with pagination."""
    with httpx.Client(timeout=30.0) as c:
        r = c.get(f"{GAMMA_BASE}/events", params={
            "limit": limit, "offset": offset, "active": "true", "closed": "false",
        })
        r.raise_for_status()
        return r.json()


def fetch_all_events(page_size: int = 100, max_pages: int = 5) -> list[dict]:
    """Fetch events with pagination — continues until empty page or max_pages."""
    all_events, page = [], 0
    while page < max_pages:
        batch = fetch_events(limit=page_size, offset=page * page_size)
        if not batch:
            break
        all_events.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return all_events


def classify_event(event: dict, categories: list[str] | None = None) -> str | None:
    """Return category name if event matches any category keyword list."""
    cats = categories or DEFAULT_CATEGORIES
    text = (event.get("title", "") + " " + event.get("slug", "")).lower()
    for cat in cats:
        kws = CATEGORY_KEYWORDS.get(cat, [cat.lower()])
        if any(kw in text for kw in kws):
            return cat
    return None


def classify_market(market: dict, categories: list[str] | None = None) -> str | None:
    """Return category if market question matches any category keyword list.
    Used as secondary filter to avoid false positives from event-level matches."""
    cats = categories or DEFAULT_CATEGORIES
    text = market.get("question", "").lower()
    # Also accept if event was already classified (broader match)
    for cat in cats:
        kws = CATEGORY_KEYWORDS.get(cat, [cat.lower()])
        if any(kw in text for kw in kws):
            return cat
    return None


def extract_markets(events: list[dict], categories: list[str] | None = None) -> list[dict]:
    """Extract active markets from classified events with volume >= MIN_VOLUME."""
    cats = categories or DEFAULT_CATEGORIES
    results = []
    for ev in events:
        ev_cat = classify_event(ev, cats)
        for m in ev.get("markets", []):
            try:
                # For Sports: require market-level match (stricter to avoid false positives)
                # For Politics/Business: event-level match is sufficient
                mkt_cat = classify_market(m, cats)
                if ev_cat == "Sports" and mkt_cat is None:
                    continue  # Skip: event title matched but question doesn't
                cat = mkt_cat or ev_cat
                if cat is None:
                    continue
                prices = json.loads(m.get("outcomePrices", "[]"))
                if len(prices) < 2:
                    continue
                p_yes = float(prices[0])
                vol = float(m.get("volumeNum", 0))
                if not (m.get("active") and not m.get("closed") and vol >= MIN_VOLUME):
                    continue
                results.append({
                    "market_id": m.get("id"), "question": m.get("question", "")[:200],
                    "p_yes": round(p_yes, 4), "p_no": round(1 - p_yes, 4),
                    "volume_usd": round(vol, 2), "end_date": m.get("endDateIso", ""),
                    "signal": "PENDING_RESEARCH", "event_title": ev.get("title", "")[:100],
                    "category": cat,
                    "signal_strength": round(abs(p_yes - 0.50), 4),
                    "snapshot_utc": datetime.now(timezone.utc).isoformat(),
                    "fee_bps": int(m.get("takerBaseFee", 1000)),
                })
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    return results


def persist_to_supabase(markets: list[dict], batch_size: int = 100) -> int:
    """Bulk upsert markets into Supabase polymarket_markets table."""
    if not markets:
        return 0
    inserted = 0
    with httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }, timeout=30.0) as c:
        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]
            rows = [{
                "market_id": s["market_id"], "question": s["question"],
                "p_yes": s["p_yes"], "p_no": s["p_no"],
                "volume_usd": s["volume_usd"], "end_date": s["end_date"],
                "signal": s["signal"], "event_title": s["event_title"],
                "snapshot_utc": s["snapshot_utc"], "fee_bps": s["fee_bps"],
                "outcome": None, "pnl_net": None,
            } for s in batch]
            r = c.post("/polymarket_markets", json=rows,
                       params={"on_conflict": "market_id,snapshot_utc"})
            if r.status_code in (200, 201):
                inserted += len(batch)
            else:
                # Fallback: insert one by one to handle partial conflicts
                for row in rows:
                    r2 = c.post("/polymarket_markets", json=row,
                                params={"on_conflict": "market_id,snapshot_utc"})
                    if r2.status_code in (200, 201):
                        inserted += 1
    return inserted


if __name__ == "__main__":
    cats = os.environ.get("POLYMARKET_CATEGORIES", "Sports,Politics,Business").split(",")
    print(f"H-010 Polymarket Connector — categories: {cats}")
    events = fetch_all_events(page_size=100, max_pages=5)
    print(f"  Total events fetched: {len(events)}")
    markets = extract_markets(events, categories=cats)
    print(f"  Active markets (vol >= {MIN_VOLUME}): {len(markets)}")
    # Group by category
    by_cat = {}
    for m in markets:
        by_cat.setdefault(m["category"], []).append(m)
    for cat, ms in sorted(by_cat.items()):
        print(f"  [{cat}] {len(ms)} markets — top: {max(ms, key=lambda x: x['volume_usd'])['question'][:60]} (vol={max(ms, key=lambda x: x['volume_usd'])['volume_usd']:,.0f})")
    for s in sorted(markets, key=lambda x: -x["signal_strength"])[:10]:
        print(f"    {s['signal_strength']:.3f} | P={s['p_yes']:.3f} | vol={s['volume_usd']:,.0f} | {s['question'][:60]}")
