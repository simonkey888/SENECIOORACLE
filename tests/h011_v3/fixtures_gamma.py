"""Sanitized fixtures based on real Polymarket Gamma API payloads.

All conditionIds, clobTokenIds, market IDs, and questionIDs are synthetic
or sanitized to avoid leaking real identifiers in test artifacts. The
STRUCTURE of each fixture mirrors what Gamma returns in production.

Source of structural truth:
  - 500 active markets fetched from https://gamma-api.polymarket.com/markets
    on 2026-07-13 03:44 UTC
  - All 4 BTC markets returned outcomes=["Yes","No"] (universal Polymarket
    convention for binary markets; "UP"/"DOWN" labels never appear)
  - clobTokenIds[i] positionally corresponds to outcomes[i] (Polymarket
    schema guarantee)
  - Real BTC 5-minute up/down markets do NOT currently exist in the active
    set; the closest analog is multi-month price-target markets
"""
from __future__ import annotations

# Each fixture is a complete Gamma market dict. Synthetic IDs are used to
# avoid tying tests to specific real markets that may resolve or delist.

FIXTURE_VALID_BTC_UP_DOWN_300S = {
    "conditionId": "0x" + "a" * 64,
    "id": "900001",
    "question": "Bitcoin 5-Minute Directional — Up or Down?",
    "slug": "bitcoin-5min-up-or-down-900001",
    "title": "Bitcoin 5-Minute Up or Down",
    "description": "This market resolves to Yes if the Binance BTCUSDT 1-minute candle "
                   "closing at the end of the 5-minute window has a High price strictly "
                   "greater than the open price of the window. Otherwise resolves No.",
    "resolutionSource": "Binance BTCUSDT 1-minute candles",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": [
        "synthetic-yes-token-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "synthetic-no-token-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    ],
    "outcomePrices": "[\"0.48\", \"0.52\"]",
    "startDate": "2026-07-13T03:00:00Z",
    "endDate": "2026-07-13T03:05:00Z",
    "startDateIso": "2026-07-13",
    "endDateIso": "2026-07-13",
    "active": True,
    "closed": False,
    "acceptingOrders": True,
    "feesEnabled": True,
    "volumeNum": 5234.50,
    "negRisk": False,
    "event": {
        "slug": "bitcoin-5min-series",
        "title": "Bitcoin 5-Minute Up or Down",
    },
}

FIXTURE_VALID_BTC_UP_DOWN_900S = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "b" * 64,
    "id": "900002",
    "slug": "bitcoin-15min-up-or-down-900002",
    "question": "Bitcoin 15-Minute Directional — Up or Down?",
    "description": "This market resolves to Yes if the Binance BTCUSDT 1-minute candle "
                   "closing at the end of the 15-minute window has a High price strictly "
                   "greater than the open price of the window. Otherwise resolves No.",
    "startDate": "2026-07-13T03:00:00Z",
    "endDate": "2026-07-13T03:15:00Z",
}

# Variant with UP/DOWN literal labels (not produced by Polymarket today but
# accepted by the validator for forward compatibility).
FIXTURE_VALID_BTC_UP_DOWN_LITERAL_LABELS = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "c" * 64,
    "id": "900003",
    "outcomes": ["UP", "DOWN"],
}

# Variant with swapped outcomes order — labels still form a valid binary
# superset {"YES","NO"} so identity is proven. Token binding is positional.
FIXTURE_BTC_OUTCOMES_ORDER_SWAPPED = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "d" * 64,
    "id": "900004",
    "outcomes": ["No", "Yes"],
    "clobTokenIds": [
        # Swapped to maintain positional correspondence with swapped outcomes
        "synthetic-no-token-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        "synthetic-yes-token-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ],
    "outcomePrices": "[\"0.52\", \"0.48\"]",
}

# Variant with token IDs swapped but outcomes NOT swapped — this creates a
# mismatch with the canonical positional mapping. The validator should still
# accept this because it does NOT verify semantic token-outcome binding
# beyond positional correspondence (which is a Polymarket schema guarantee,
# not something we can re-derive from the payload alone).
FIXTURE_BTC_TOKENS_SWAPPED = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "e" * 64,
    "id": "900005",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": [
        "synthetic-no-token-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        "synthetic-yes-token-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ],
}

# Inconsistent conditionId (empty string) — should trigger missing_condition_id.
FIXTURE_MISSING_CONDITION_ID = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "",
    "id": "900006",
}

# Incomplete metadata: missing outcomes entirely.
FIXTURE_MISSING_OUTCOMES = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "f" * 64,
    "id": "900007",
}
FIXTURE_MISSING_OUTCOMES.pop("outcomes")
FIXTURE_MISSING_OUTCOMES.pop("clobTokenIds")

# Non-binary market (3 outcomes) — should be rejected.
FIXTURE_NON_BINARY_3_OUTCOMES = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "10" * 32,
    "id": "900008",
    "outcomes": ["Up", "Down", "Flat"],
    "clobTokenIds": ["t1", "t2", "t3"],
    "outcomePrices": "[\"0.3\", \"0.4\", \"0.3\"]",
}

# Single clobTokenId — should be rejected.
FIXTURE_SINGLE_TOKEN = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "11" * 32,
    "id": "900009",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": ["only-one-token-id"],
}

# Duplicate clobTokenIds — should be rejected (not unique).
FIXTURE_DUPLICATE_TOKENS = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "12" * 32,
    "id": "900010",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": ["same-token", "same-token"],
}

# Non-canonical outcome labels ("Higher"/"Lower") — should be rejected
# because we cannot prove these map to UP/DOWN semantics structurally.
FIXTURE_NON_CANONICAL_LABELS = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "13" * 32,
    "id": "900011",
    "outcomes": ["Higher", "Lower"],
}

# Resolved market with extreme prices (>0.95) — should be rejected by
# the resolved_extreme_prices check, not the identity check.
FIXTURE_RESOLVED_EXTREME_PRICES = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "14" * 32,
    "id": "900012",
    "outcomePrices": "[\"0.97\", \"0.03\"]",
}

# Real-shape BTC market (long-window price target) — based on the
# "will-bitcoin-hit-1m-before-gta-vi" structure observed on 2026-07-13.
# Sanitized conditionId, token IDs, and market ID.
FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW = {
    "conditionId": "0x" + "15" * 32,
    "id": "540844",
    "question": "Will bitcoin hit $1m before GTA VI?",
    "slug": "will-bitcoin-hit-1m-before-gta-vi-872-424",
    "description": "This market will resolve to \"Yes\" if any Binance 1 minute candle "
                   "for Bitcoin (BTCUSDT) has a final \"High\" price of $1,000,000 or "
                   "more before the release date of GTA VI. Otherwise resolves No.",
    "resolutionSource": "",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": [
        "105267568073659068217311993901927962476298440625043565106676088842803600775810",
        "91863162118308663069733924043159186005106558783397508844234610341221325526200",
    ],
    "outcomePrices": "[\"0.4965\", \"0.5035\"]",
    "startDate": "2025-05-02T15:48:17.361Z",
    "endDate": "2026-07-31T12:00:00Z",
    "startDateIso": "2025-05-02",
    "endDateIso": "2026-07-31",
    "active": True,
    "closed": False,
    "acceptingOrders": True,
    "feesEnabled": True,
    "volumeNum": 4630496.70,
    "negRisk": False,
    "events": [{
        "id": "23784",
        "ticker": "what-will-happen-before-gta-vi",
        "slug": "what-will-happen-before-gta-vi",
        "title": "What will happen before GTA VI?",
    }],
}

# Non-BTC market — based on a generic sports/political market shape.
FIXTURE_NON_BTC_MARKET = {
    "conditionId": "0x" + "16" * 32,
    "id": "700001",
    "question": "Will the Lakers win the NBA championship?",
    "slug": "lakers-nba-championship-2026",
    "description": "Resolves Yes if the Lakers win the 2026 NBA Finals.",
    "outcomes": ["Yes", "No"],
    "clobTokenIds": ["t-lakers-yes", "t-lakers-no"],
    "outcomePrices": "[\"0.25\", \"0.75\"]",
    "startDate": "2026-06-01T00:00:00Z",
    "endDate": "2026-06-30T00:00:00Z",
    "active": True,
    "closed": False,
}

# Ambiguous market: BTC in slug but no price oracle in description.
# Should fail resolution_rule_unproven.
FIXTURE_AMBIGUOUS_BTC_NO_ORACLE = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "17" * 32,
    "id": "900013",
    "question": "Bitcoin something something",
    "slug": "bitcoin-something",
    "description": "Resolves based on community vote.",
    "resolutionSource": "",
}

# Window timestamp missing. Note: must also clear startDateIso/endDateIso
# because the validator falls back to those fields when startDate/endDate
# are None.
FIXTURE_MISSING_WINDOW_TIMESTAMPS = {
    **FIXTURE_VALID_BTC_UP_DOWN_300S,
    "conditionId": "0x" + "18" * 32,
    "id": "900014",
    "startDate": None,
    "endDate": None,
    "startDateIso": None,
    "endDateIso": None,
}

# Paginated responses: 250 generic non-BTC markets spread across 3 pages,
# with a valid BTC market on page 3.
def make_paginated_responses():
    """Return a list of 3 page responses simulating Gamma pagination."""
    page1 = [
        {
            "conditionId": f"0x{i:064x}",
            "id": str(1000 + i),
            "slug": f"generic-market-{i}",
            "outcomes": ["Yes", "No"],
            "clobTokenIds": [f"token-a-{i}", f"token-b-{i}"],
            "outcomePrices": "[\"0.4\", \"0.6\"]",
            "startDate": "2026-07-13T00:00:00Z",
            "endDate": "2026-07-13T00:05:00Z",
        }
        for i in range(100)
    ]
    page2 = [
        {
            "conditionId": f"0x{i + 100:064x}",
            "id": str(1100 + i),
            "slug": f"generic-market-{i + 100}",
            "outcomes": ["Yes", "No"],
            "clobTokenIds": [f"token-a-{i + 100}", f"token-b-{i + 100}"],
            "outcomePrices": "[\"0.4\", \"0.6\"]",
            "startDate": "2026-07-13T00:00:00Z",
            "endDate": "2026-07-13T00:05:00Z",
        }
        for i in range(100)
    ]
    page3 = [FIXTURE_VALID_BTC_UP_DOWN_300S]
    return [page1, page2, page3]


# Duplicated market across pages (same conditionId in two pages).
def make_duplicated_responses():
    """Return 2 pages where the same conditionId appears in both."""
    duplicate_market = {
        **FIXTURE_VALID_BTC_UP_DOWN_300S,
        "id": "900001",  # same id, same conditionId
    }
    page1 = [duplicate_market]
    page2 = [duplicate_market]
    return [page1, page2]


ALL_FIXTURES = {
    "valid_btc_up_down_300s": FIXTURE_VALID_BTC_UP_DOWN_300S,
    "valid_btc_up_down_900s": FIXTURE_VALID_BTC_UP_DOWN_900S,
    "valid_btc_literal_up_down_labels": FIXTURE_VALID_BTC_UP_DOWN_LITERAL_LABELS,
    "btc_outcomes_order_swapped": FIXTURE_BTC_OUTCOMES_ORDER_SWAPPED,
    "btc_tokens_swapped": FIXTURE_BTC_TOKENS_SWAPPED,
    "missing_condition_id": FIXTURE_MISSING_CONDITION_ID,
    "missing_outcomes": FIXTURE_MISSING_OUTCOMES,
    "non_binary_3_outcomes": FIXTURE_NON_BINARY_3_OUTCOMES,
    "single_token": FIXTURE_SINGLE_TOKEN,
    "duplicate_tokens": FIXTURE_DUPLICATE_TOKENS,
    "non_canonical_labels": FIXTURE_NON_CANONICAL_LABELS,
    "resolved_extreme_prices": FIXTURE_RESOLVED_EXTREME_PRICES,
    "real_shape_btc_long_window": FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW,
    "non_btc_market": FIXTURE_NON_BTC_MARKET,
    "ambiguous_btc_no_oracle": FIXTURE_AMBIGUOUS_BTC_NO_ORACLE,
    "missing_window_timestamps": FIXTURE_MISSING_WINDOW_TIMESTAMPS,
}
