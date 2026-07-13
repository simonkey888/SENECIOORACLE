"""Sanitized fixtures for H-011 V3 directional market identity tests.

Based on real Polymarket Gamma API payloads captured 2026-07-13 across
13 BTC updown 5m markets. All conditionIds, clobTokenIds, market IDs,
and event IDs are SYNTHETIC — they preserve the structural shape of
production data without leaking real on-chain identifiers.

Statistical validation (13/13 markets, 100% consistent):
    eventStartTime == slug_epoch
    endDate - eventStartTime == 300s
    outcomes == ["Up","Down"]
    clobTokenIds has 2 unique tokens
    events[0].ticker == market.slug

Source contract:
    Opción A (confirmed by GPT-5.6 after statistical validation):
        window_start = eventStartTime = slug_epoch
        window_end   = endDate
        duration     = endDate - eventStartTime = 300s
        startDate    = market listing/lifecycle (NOT the H-011 window)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════
# Factory: canonical valid BTC updown 5m market
# ═══════════════════════════════════════════════════════════════════════

def make_real_btc_updown_market(
    *,
    slug_epoch: int = 1766162100,
    condition_id: str | None = None,
    market_id: str = "900001",
    event_id: str = "109968",
    window_s: int = 300,
    outcomes=None,
    clob_token_ids=None,
    resolution_source: str = "https://data.chain.link/streams/btc-usd",
    description: str | None = None,
    ticker: str | None = None,
    active: bool = True,
    closed: bool = False,
    override_event_start: str | None = None,
    override_end_date: str | None = None,
    override_start_date: str | None = None,
    override_slug: str | None = None,
) -> dict:
    """Build a canonical BTC updown 5m market fixture matching the production contract.

    Defaults produce a market that PASSES validate_btc_market_identity.
    Override parameters to construct invalid variants for rejection tests.

    All identifiers are synthetic but structurally valid (correct length,
    correct format). conditionId is a 0x-prefixed 64-char hex string.
    clobTokenIds are 76-digit numeric strings (matching Polymarket format)
    but with synthetic digit patterns.
    """
    if condition_id is None:
        # Derive a deterministic conditionId from slug_epoch so each
        # fixture has a unique but reproducible identifier.
        condition_id = f"0x{slug_epoch:064x}"

    if clob_token_ids is None:
        # Synthetic 76-digit numeric token IDs. Pattern is deterministic
        # from slug_epoch so each fixture has unique tokens.
        up_token = str(slug_epoch * 10 + 1).rjust(76, "1")
        down_token = str(slug_epoch * 10 + 2).rjust(76, "2")
        clob_token_ids = [up_token, down_token]

    slug = override_slug or f"btc-updown-5m-{slug_epoch}"
    event_start = override_event_start or datetime.fromtimestamp(
        slug_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_date = override_end_date or datetime.fromtimestamp(
        slug_epoch + window_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # startDate is ~24h before the window (lifecycle, NOT H-011 window)
    start_date = override_start_date or datetime.fromtimestamp(
        slug_epoch - 86400, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if description is None:
        desc = (
            'This market will resolve to "Up" if the Bitcoin price at the end of '
            'the time range specified in the title is greater than or equal to '
            'the price at the beginning of that range. Otherwise, it will resolve '
            'to "Down". The resolution source for this market is information '
            'from Chainlink, specifically the BTC/USD price feed.'
        )
    else:
        desc = description

    return {
        "conditionId": condition_id,
        "id": market_id,
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "description": desc,
        "resolutionSource": resolution_source,
        "outcomes": outcomes or ["Up", "Down"],
        "clobTokenIds": clob_token_ids,
        "outcomePrices": '["0.48", "0.52"]',
        "startDate": start_date,
        "endDate": end_date,
        "startDateIso": start_date[:10],
        "endDateIso": end_date[:10],
        "eventStartTime": event_start,
        "active": active,
        "closed": closed,
        "acceptingOrders": True,
        "feesEnabled": True,
        "volumeNum": 5234.50,
        "negRisk": False,
        "events": [{
            "id": event_id,
            "ticker": ticker or slug,
            "slug": slug,
            "title": "Bitcoin Up or Down",
            "description": desc,
            "resolutionSource": resolution_source,
        }],
    }


# ═══════════════════════════════════════════════════════════════════════
# Negative-case fixtures (each fails a SPECIFIC check)
# ═══════════════════════════════════════════════════════════════════════
#
# Each fixture has a UNIQUE conditionId so deduplication tests can
# distinguish them. Format: 0x{fixture_index:064x} where fixture_index
# is a stable identifier for the negative case.

# Fixture 1: BTC long-window price target market.
# Fails directional_market_identity_unproven (slug doesn't match pattern).
# Based on the real "will-bitcoin-hit-1m-before-gta-vi" market structure.
FIXTURE_BTC_LONG_WINDOW_PRICE_TARGET = {
    "conditionId": "0x" + "01" * 32,
    "id": "540844",
    "slug": "will-bitcoin-hit-1m-before-gta-vi-872-424",
    "question": "Will bitcoin hit $1m before GTA VI?",
    "description": "This market will resolve to Yes if any Binance 1 minute candle "
                   "for Bitcoin (BTCUSDT) has a final High price of $1,000,000 or "
                   "more before the release date of GTA VI.",
    "resolutionSource": "",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": [
        "105267568073659068217311993901927962476298440625043565106676088842803600775810",
        "91863162118308663069733924043159186005106558783397508844234610341221325526200",
    ],
    "outcomePrices": '["0.4965", "0.5035"]',
    "startDate": "2025-05-02T15:48:17.361Z",
    "endDate": "2026-07-31T12:00:00Z",
    "active": True,
    "closed": False,
    "events": [{
        "id": "23784",
        "ticker": "what-will-happen-before-gta-vi",
        "slug": "what-will-happen-before-gta-vi",
        "title": "What will happen before GTA VI?",
    }],
}

# Fixture 2: Generic Yes/No market (non-BTC, non-directional).
# Fails directional_market_identity_unproven.
FIXTURE_GENERIC_YES_NO_MARKET = {
    "conditionId": "0x" + "02" * 32,
    "id": "700001",
    "slug": "lakers-nba-championship-2026",
    "question": "Will the Lakers win the 2026 NBA championship?",
    "description": "Resolves Yes if the Lakers win the 2026 NBA Finals.",
    "resolutionSource": "ESPN",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": ["lakers-yes-synthetic-token", "lakers-no-synthetic-token"],
    "outcomePrices": '["0.25", "0.75"]',
    "startDate": "2026-06-01T00:00:00Z",
    "endDate": "2026-06-30T00:00:00Z",
    "active": True,
    "closed": False,
    "events": [{
        "id": "800001",
        "ticker": "lakers-nba-championship-2026",
        "slug": "lakers-nba-championship-2026",
        "title": "Lakers NBA Championship 2026",
    }],
}

# Fixture 3: ETH updown 5m market (correct structure but wrong asset).
# Fails directional_market_identity_unproven (slug is eth-updown-5m, not btc).
FIXTURE_ETH_UPDOWN_5M = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "03" * 32,
    market_id="900010",
    override_slug="eth-updown-5m-1766162100",
)

# Fixture 4: BTC updown 15m market (correct asset, wrong window duration).
# Fails directional_market_identity_unproven (slug is btc-updown-15m, not 5m).
FIXTURE_BTC_UPDOWN_15M = {
    "conditionId": "0x" + "04" * 32,
    "id": "900011",
    "slug": "btc-updown-15m-1766162100",
    "question": "Bitcoin Up or Down - 15 minute window",
    "description": 'This market will resolve to "Up" if the Bitcoin price at the end of '
                   'the time range specified in the title is greater than or equal to '
                   'the price at the beginning of that range. Otherwise, it will resolve '
                   'to "Down". The resolution source is Chainlink BTC/USD.',
    "resolutionSource": "https://data.chain.link/streams/btc-usd",
    "outcomes": ["Up", "Down"],
    "clobTokenIds": ["eth-up-synthetic-token-aaa", "eth-down-synthetic-token-bbb"],
    "outcomePrices": '["0.48", "0.52"]',
    "startDate": "2025-12-18T16:43:11Z",
    "endDate": "2025-12-19T16:50:00Z",  # 900s after eventStartTime
    "eventStartTime": "2025-12-19T16:35:00Z",
    "active": True,
    "closed": False,
    "events": [{
        "id": "109969",
        "ticker": "btc-updown-15m-1766162100",
        "slug": "btc-updown-15m-1766162100",
        "title": "Bitcoin Up or Down - 15 minute",
    }],
}


# ═══════════════════════════════════════════════════════════════════════
# Window duration edge cases (modify the canonical market)
# ═══════════════════════════════════════════════════════════════════════

# Fixture 5: BTC updown 5m with duration 298s (2s short — beyond ±1s tolerance).
# Fails window_duration_mismatch.
# Note: 299s/301s are within the ±1s serialization tolerance and would PASS.
# We use 298s/302s to clearly exceed the tolerance and trigger rejection.
FIXTURE_BTC_UPDOWN_5M_DURATION_299 = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "05" * 32,
    market_id="900020",
    window_s=298,  # 2s short — beyond ±1s tolerance
)

# Fixture 6: BTC updown 5m with duration 302s (2s long — beyond ±1s tolerance).
# Fails window_duration_mismatch.
FIXTURE_BTC_UPDOWN_5M_DURATION_301 = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "06" * 32,
    market_id="900021",
    window_s=302,  # 2s long — beyond ±1s tolerance
)

# Fixture 7: BTC updown 5m with eventStartTime != slug_epoch (60s off).
# Fails window_start_mismatch.
FIXTURE_BTC_UPDOWN_5M_EVENTSTART_MISMATCH = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "07" * 32,
    market_id="900030",
    override_event_start="2025-12-19T16:36:00Z",  # 60s after slug_epoch
    # Keep endDate = slug_epoch + 300 to isolate the mismatch to eventStartTime only
    override_end_date="2025-12-19T16:40:00Z",
)

# Fixture 8: BTC updown 5m with event ticker inconsistent with market slug.
# Fails directional_market_identity_unproven (ticker mismatch).
FIXTURE_BTC_UPDOWN_5M_TICKER_INCONSISTENT = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "08" * 32,
    market_id="900040",
    ticker="some-other-ticker-1766162100",
)


# ═══════════════════════════════════════════════════════════════════════
# Token binding edge cases
# ═══════════════════════════════════════════════════════════════════════

# Fixture 9: BTC updown 5m with outcomes=["Down","Up"] (inverted order).
# Fails token_direction_mapping_unproven.
FIXTURE_BTC_UPDOWN_5M_OUTCOMES_INVERTED = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "09" * 32,
    market_id="900050",
    outcomes=["Down", "Up"],
)

# Fixture 10: BTC updown 5m with outcomes=["Yes","No"] (not directional).
# Fails token_direction_mapping_unproven.
FIXTURE_BTC_UPDOWN_5M_OUTCOMES_YESNO = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "0a" * 32,
    market_id="900051",
    outcomes=["Yes", "No"],
)

# Fixture 11: BTC updown 5m with missing clobTokenIds.
# Fails token_direction_mapping_unproven.
FIXTURE_BTC_UPDOWN_5M_MISSING_TOKENS = {
    **make_real_btc_updown_market(
        slug_epoch=1766162100,
        condition_id="0x" + "0b" * 32,
        market_id="900060",
    ),
    "clobTokenIds": None,
}

# Fixture 12: BTC updown 5m with duplicate clobTokenIds.
# Fails token_direction_mapping_unproven.
FIXTURE_BTC_UPDOWN_5M_DUPLICATE_TOKENS = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "0c" * 32,
    market_id="900061",
    clob_token_ids=["same-token-synthetic", "same-token-synthetic"],
)


# ═══════════════════════════════════════════════════════════════════════
# Market lifecycle state
# ═══════════════════════════════════════════════════════════════════════

# Fixture 13: BTC updown 5m with active=False.
# Fails market_inactive_or_closed.
FIXTURE_BTC_UPDOWN_5M_INACTIVE = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "0d" * 32,
    market_id="900070",
    active=False,
)

# Fixture 14: BTC updown 5m with closed=True.
# Fails market_inactive_or_closed.
FIXTURE_BTC_UPDOWN_5M_CLOSED = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "0e" * 32,
    market_id="900071",
    closed=True,
)


# ═══════════════════════════════════════════════════════════════════════
# Resolution rule edge cases
# ═══════════════════════════════════════════════════════════════════════

# Fixture 15: BTC updown 5m with empty resolutionSource.
# Fails resolution_rule_unproven.
FIXTURE_BTC_UPDOWN_5M_NO_RESOLUTION_SOURCE = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "0f" * 32,
    market_id="900080",
    resolution_source="",
)

# Fixture 16: BTC updown 5m with empty description.
# Fails resolution_rule_unproven.
FIXTURE_BTC_UPDOWN_5M_NO_DESCRIPTION = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "10" * 32,
    market_id="900081",
    description="",
)


# ═══════════════════════════════════════════════════════════════════════
# Window timestamp missing
# ═══════════════════════════════════════════════════════════════════════

# Fixture 17: BTC updown 5m with eventStartTime=None.
# Fails window_start_unproven.
FIXTURE_BTC_UPDOWN_5M_MISSING_EVENT_START = {
    **make_real_btc_updown_market(
        slug_epoch=1766162100,
        condition_id="0x" + "11" * 32,
        market_id="900090",
    ),
    "eventStartTime": None,
}

# Fixture 18: BTC updown 5m with endDate=None.
# Fails window_end_unproven.
FIXTURE_BTC_UPDOWN_5M_MISSING_END_DATE = {
    **make_real_btc_updown_market(
        slug_epoch=1766162100,
        condition_id="0x" + "12" * 32,
        market_id="900091",
    ),
    "endDate": None,
}


# ═══════════════════════════════════════════════════════════════════════
# Slug pattern edge cases
# ═══════════════════════════════════════════════════════════════════════

# Fixture 19: slug matches prefix but lacks the 10-digit epoch.
# Fails directional_market_identity_unproven (regex doesn't match).
FIXTURE_BTC_UPDOWN_5M_SLUG_NO_EPOCH = {
    **make_real_btc_updown_market(
        slug_epoch=1766162100,
        condition_id="0x" + "13" * 32,
        market_id="900100",
    ),
    "slug": "btc-updown-5m-notanepoch",
    # Also update event ticker to match (so we isolate the slug regex failure)
    "events": [{
        "id": "109968",
        "ticker": "btc-updown-5m-notanepoch",
        "slug": "btc-updown-5m-notanepoch",
        "title": "Bitcoin Up or Down",
    }],
}


# ═══════════════════════════════════════════════════════════════════════
# startDate boundary — must NOT affect validation
# ═══════════════════════════════════════════════════════════════════════

# Fixture 20: BTC updown 5m where startDate == eventStartTime (edge case).
# This should still PASS because startDate is not used for the H-011 window.
FIXTURE_BTC_UPDOWN_5M_START_DATE_TODAY = make_real_btc_updown_market(
    slug_epoch=1766162100,
    condition_id="0x" + "14" * 32,
    market_id="900110",
    override_start_date="2025-12-19T16:35:00Z",  # Same as eventStartTime
)


# ═══════════════════════════════════════════════════════════════════════
# Pagination helpers
# ═══════════════════════════════════════════════════════════════════════

def make_paginated_markets(valid_at_offset: int = 600, page_size: int = 100,
                           total_pages: int = 7) -> list[list[dict]]:
    """Build paginated /markets responses with a valid BTC updown 5m market
    at a specific offset (default: 600, beyond the first 6 pages).

    Each page contains `page_size` markets with unique conditionIds.
    The valid market is in the page that contains offset `valid_at_offset`.
    """
    pages = []
    for page_idx in range(total_pages):
        offset = page_idx * page_size
        page_markets = []
        for i in range(page_size):
            market_idx = offset + i
            if market_idx == valid_at_offset:
                # Insert the valid BTC updown 5m market at this position
                page_markets.append(make_real_btc_updown_market(
                    slug_epoch=1766162100,
                    condition_id="0x" + "ff" * 32,  # Unique ID for the valid market
                    market_id="900999",
                ))
            else:
                # Generic non-directional market
                page_markets.append({
                    "conditionId": f"0x{market_idx:064x}",
                    "id": str(1000 + market_idx),
                    "slug": f"generic-market-{market_idx}",
                    "outcomes": ["Yes", "No"],
                    "clobTokenIds": [f"a{market_idx}-synthetic", f"b{market_idx}-synthetic"],
                    "outcomePrices": '["0.4", "0.6"]',
                    "active": True,
                    "closed": False,
                })
        pages.append(page_markets)
    return pages


def make_duplicated_market_responses(condition_id: str = "0x" + "ee" * 32):
    """Build responses where the same conditionId appears in BOTH
    /markets and /events endpoints (for deduplication testing).

    Returns a dict: {"markets": [...], "events": [...]}
    """
    market = make_real_btc_updown_market(
        slug_epoch=1766162100,
        condition_id=condition_id,
        market_id="900888",
    )
    # The /events endpoint returns events with nested markets
    event = {
        "id": "109968",
        "ticker": market["slug"],
        "slug": market["slug"],
        "title": "Bitcoin Up or Down",
        "description": market["description"],
        "active": True,
        "closed": False,
        "markets": [market],
    }
    return {
        "markets": [market],
        "events": [event],
    }


# ═══════════════════════════════════════════════════════════════════════
# Convenience registry
# ═══════════════════════════════════════════════════════════════════════

ALL_NEGATIVE_FIXTURES = {
    "btc_long_window_price_target": FIXTURE_BTC_LONG_WINDOW_PRICE_TARGET,
    "generic_yes_no_market": FIXTURE_GENERIC_YES_NO_MARKET,
    "eth_updown_5m": FIXTURE_ETH_UPDOWN_5M,
    "btc_updown_15m": FIXTURE_BTC_UPDOWN_15M,
    "duration_299": FIXTURE_BTC_UPDOWN_5M_DURATION_299,
    "duration_301": FIXTURE_BTC_UPDOWN_5M_DURATION_301,
    "eventstart_mismatch": FIXTURE_BTC_UPDOWN_5M_EVENTSTART_MISMATCH,
    "ticker_inconsistent": FIXTURE_BTC_UPDOWN_5M_TICKER_INCONSISTENT,
    "outcomes_inverted": FIXTURE_BTC_UPDOWN_5M_OUTCOMES_INVERTED,
    "outcomes_yesno": FIXTURE_BTC_UPDOWN_5M_OUTCOMES_YESNO,
    "missing_tokens": FIXTURE_BTC_UPDOWN_5M_MISSING_TOKENS,
    "duplicate_tokens": FIXTURE_BTC_UPDOWN_5M_DUPLICATE_TOKENS,
    "inactive": FIXTURE_BTC_UPDOWN_5M_INACTIVE,
    "closed": FIXTURE_BTC_UPDOWN_5M_CLOSED,
    "no_resolution_source": FIXTURE_BTC_UPDOWN_5M_NO_RESOLUTION_SOURCE,
    "no_description": FIXTURE_BTC_UPDOWN_5M_NO_DESCRIPTION,
    "missing_event_start": FIXTURE_BTC_UPDOWN_5M_MISSING_EVENT_START,
    "missing_end_date": FIXTURE_BTC_UPDOWN_5M_MISSING_END_DATE,
    "slug_no_epoch": FIXTURE_BTC_UPDOWN_5M_SLUG_NO_EPOCH,
}


def make_real_btc_updown_market_with_offset(slug_epoch: int, offset: int = 0) -> dict:
    """Build a valid market with a conditionId derived from both slug_epoch
    and offset (for tests that need multiple distinct valid markets)."""
    return make_real_btc_updown_market(
        slug_epoch=slug_epoch,
        condition_id=f"0x{(slug_epoch + offset):064x}",
        market_id=str(900000 + offset),
    )
