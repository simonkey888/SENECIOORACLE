"""Tests for the conservative fix to up_down_token_identity_unproven rejection.

Context:
  Before the fix, validate_btc_market_identity required outcomes=["UP","DOWN"]
  literally. Polymarket's Gamma API ALWAYS returns outcomes=["Yes","No"] for
  binary markets (verified 2026-07-13 across 500 active markets), so 100% of
  markets were rejected with `up_down_token_identity_unproven`.

After the fix:
  - outcomes=["Yes","No"] is accepted (Polymarket's universal binary convention)
  - outcomes=["UP","DOWN"] is still accepted (forward compatibility)
  - outcomes=["UP","DOWN"] in any order is accepted (superset check)
  - Non-canonical labels (e.g., "Higher"/"Lower") are still rejected
  - Non-binary markets (3+ outcomes) are still rejected
  - Missing/duplicate/non-unique clobTokenIds are still rejected
  - All parsing errors fail closed with up_down_token_identity_unproven

The fix is conservative:
  - Does NOT infer UP/DOWN semantics from question text
  - Does NOT swap token positions
  - Does NOT accept labels outside the canonical {"UP","DOWN"} ∪ {"YES","NO"} set
  - Directional UP/DOWN semantics are still established by the combination of
    (a) BTC identity in slug/title, (b) resolution rule mentioning BTC price
    oracle, and (c) the window_duration check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make the polymarket package importable (matches Dockerfile WORKDIR).
sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

from h011_v3_pipeline import validate_btc_market_identity
from discovery_v3 import discover_markets_v3

from tests.h011_v3.fixtures_gamma import (
    FIXTURE_VALID_BTC_UP_DOWN_300S,
    FIXTURE_VALID_BTC_UP_DOWN_900S,
    FIXTURE_VALID_BTC_UP_DOWN_LITERAL_LABELS,
    FIXTURE_BTC_OUTCOMES_ORDER_SWAPPED,
    FIXTURE_BTC_TOKENS_SWAPPED,
    FIXTURE_MISSING_CONDITION_ID,
    FIXTURE_MISSING_OUTCOMES,
    FIXTURE_NON_BINARY_3_OUTCOMES,
    FIXTURE_SINGLE_TOKEN,
    FIXTURE_DUPLICATE_TOKENS,
    FIXTURE_NON_CANONICAL_LABELS,
    FIXTURE_RESOLVED_EXTREME_PRICES,
    FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW,
    FIXTURE_NON_BTC_MARKET,
    FIXTURE_AMBIGUOUS_BTC_NO_ORACLE,
    FIXTURE_MISSING_WINDOW_TIMESTAMPS,
    ALL_FIXTURES,
    make_paginated_responses,
    make_duplicated_responses,
)


def _identity_ok(market, window=300):
    return validate_btc_market_identity(market, window)


# ─────────────────────────────────────────────────────────────────────
# Happy path: Yes/No binary market is now accepted
# ─────────────────────────────────────────────────────────────────────

def test_yes_no_outcomes_pass_identity_check():
    """The primary fix: Yes/No outcomes (Polymarket's universal binary
    convention) should pass the identity check."""
    ok, reasons = _identity_ok(FIXTURE_VALID_BTC_UP_DOWN_300S, window=300)
    assert ok is True
    assert reasons == []


def test_literal_up_down_outcomes_still_pass():
    """Forward compatibility: literal ["UP","DOWN"] labels still pass."""
    ok, reasons = _identity_ok(FIXTURE_VALID_BTC_UP_DOWN_LITERAL_LABELS, window=300)
    assert ok is True
    assert reasons == []


def test_outcomes_order_swapped_passes():
    """Outcomes in either order form a valid binary superset."""
    ok, reasons = _identity_ok(FIXTURE_BTC_OUTCOMES_ORDER_SWAPPED, window=300)
    assert ok is True
    assert reasons == []


def test_tokens_swapped_passes_identity():
    """The validator does not verify semantic token-outcome binding beyond
    positional correspondence. Token order swap is accepted because
    Polymarket's schema guarantees outcomes[i] ↔ clobTokenIds[i]."""
    ok, reasons = _identity_ok(FIXTURE_BTC_TOKENS_SWAPPED, window=300)
    assert ok is True
    assert reasons == []


def test_window_900_passes_with_900s_window():
    """A 900s market passes the identity check when expected_window_s=900."""
    ok, reasons = _identity_ok(FIXTURE_VALID_BTC_UP_DOWN_900S, window=900)
    assert ok is True
    assert reasons == []


def test_window_900_rejected_with_300s_window():
    """A 900s market is rejected for window_duration_mismatch (NOT for
    identity) when expected_window_s=300. This proves the identity check
    is now decoupled from the window check."""
    ok, reasons = _identity_ok(FIXTURE_VALID_BTC_UP_DOWN_900S, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" not in reasons
    assert "window_duration_mismatch" in reasons


# ─────────────────────────────────────────────────────────────────────
# Rejections: identity check still fails closed
# ─────────────────────────────────────────────────────────────────────

def test_non_binary_3_outcomes_rejected():
    """A 3-outcome market is rejected for identity (not just window)."""
    ok, reasons = _identity_ok(FIXTURE_NON_BINARY_3_OUTCOMES, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_missing_outcomes_rejected():
    """Missing outcomes entirely is rejected for identity."""
    ok, reasons = _identity_ok(FIXTURE_MISSING_OUTCOMES, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_single_token_rejected():
    """A single clobTokenId is rejected for identity."""
    ok, reasons = _identity_ok(FIXTURE_SINGLE_TOKEN, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_duplicate_tokens_rejected():
    """Duplicate clobTokenIds (not unique) are rejected for identity."""
    ok, reasons = _identity_ok(FIXTURE_DUPLICATE_TOKENS, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_non_canonical_labels_rejected():
    """Labels outside {"UP","DOWN"} ∪ {"YES","NO"} are rejected.
    This proves the fix does NOT over-accept arbitrary binary labels."""
    ok, reasons = _identity_ok(FIXTURE_NON_CANONICAL_LABELS, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_outcomes_as_json_string_parsed_correctly():
    """Polymarket returns outcomes as a JSON string. The parser must handle
    both list and string forms (existing behavior, must be preserved)."""
    market = dict(FIXTURE_VALID_BTC_UP_DOWN_300S)
    market["outcomes"] = json.dumps(["Yes", "No"])
    market["clobTokenIds"] = json.dumps(["t1", "t2"])
    ok, reasons = _identity_ok(market, window=300)
    assert ok is True
    assert reasons == []


def test_malformed_outcomes_json_rejected():
    """Malformed JSON in outcomes fails closed with identity rejection."""
    market = dict(FIXTURE_VALID_BTC_UP_DOWN_300S)
    market["outcomes"] = "not valid json"
    ok, reasons = _identity_ok(market, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


def test_outcomes_null_rejected():
    """outcomes=None fails closed with identity rejection."""
    market = dict(FIXTURE_VALID_BTC_UP_DOWN_300S)
    market["outcomes"] = None
    ok, reasons = _identity_ok(market, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" in reasons


# ─────────────────────────────────────────────────────────────────────
# Real-shape fixture tests (based on production Gamma payloads)
# ─────────────────────────────────────────────────────────────────────

def test_real_shape_btc_long_window_passes_identity_but_fails_window():
    """A real-shape BTC market (multi-month price target) should pass
    the identity check but fail the window_duration check. Before the
    fix, this market would have been rejected for identity — masking
    the actual reason (window mismatch)."""
    ok, reasons = _identity_ok(FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW, window=300)
    assert ok is False
    assert "up_down_token_identity_unproven" not in reasons, \
        "Real Polymarket Yes/No markets must NOT be rejected for identity"
    assert "window_duration_mismatch" in reasons


def test_non_btc_market_does_not_get_identity_rejection():
    """A non-BTC market with valid Yes/No outcomes should fail btc_event
    but NOT fail identity. Before the fix, every market including
    non-BTC ones was getting identity rejection — polluting the histogram."""
    ok, reasons = _identity_ok(FIXTURE_NON_BTC_MARKET, window=300)
    assert ok is False
    assert "btc_event_identity_unproven" in reasons
    assert "up_down_token_identity_unproven" not in reasons, \
        "Non-BTC markets with valid Yes/No outcomes must NOT pollute the " \
        "identity rejection histogram"


def test_ambiguous_btc_no_oracle_fails_resolution_rule_only():
    """A market with BTC in slug but no price oracle in description fails
    resolution_rule_unproven but not identity."""
    ok, reasons = _identity_ok(FIXTURE_AMBIGUOUS_BTC_NO_ORACLE, window=300)
    assert ok is False
    assert "resolution_rule_unproven" in reasons
    assert "up_down_token_identity_unproven" not in reasons


def test_missing_window_timestamps_fails_timestamps_only():
    """Missing window timestamps fails window_timestamps_unproven but
    not identity."""
    ok, reasons = _identity_ok(FIXTURE_MISSING_WINDOW_TIMESTAMPS, window=300)
    assert ok is False
    assert "window_timestamps_unproven" in reasons
    assert "up_down_token_identity_unproven" not in reasons


def test_missing_condition_id_fails_condition_id_only():
    """Missing conditionId fails missing_condition_id but not identity
    (assuming other fields are valid)."""
    ok, reasons = _identity_ok(FIXTURE_MISSING_CONDITION_ID, window=300)
    assert ok is False
    assert "missing_condition_id" in reasons
    assert "up_down_token_identity_unproven" not in reasons


def test_resolved_extreme_prices_does_not_fail_identity():
    """A resolved market (price > 0.95) should fail resolved_extreme_prices
    in the price check, not identity."""
    ok, reasons = _identity_ok(FIXTURE_RESOLVED_EXTREME_PRICES, window=300)
    # Identity check itself doesn't check prices — only the discovery
    # flow's _outcome_price_reason does.
    assert "up_down_token_identity_unproven" not in reasons


# ─────────────────────────────────────────────────────────────────────
# End-to-end discovery tests using fixtures
# ─────────────────────────────────────────────────────────────────────

class _SequenceGamma:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def fetch_pages(self, limit):
        value = self.responses[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return {
            "markets": value,
            "pages": [{"offset": 0, "limit": limit, "count": len(value)}],
            "source_exhausted": True,
            "limit_reached": False,
            "next_offset": None,
        }


def _config(window_s=300):
    return SimpleNamespace(window_s=window_s)


def test_discovery_finds_valid_btc_5min_market(tmp_path):
    """End-to-end: a valid BTC 5-min up/down market is now discovered.
    Before the fix, this would have been rejected for identity."""
    gamma = _SequenceGamma([[FIXTURE_VALID_BTC_UP_DOWN_300S]])
    result = discover_markets_v3(_config(300), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert len(result["markets"]) == 1
    assert result["evidence"]["rejection_histogram"]["up_down_token_identity_unproven"] == 0


def test_discovery_rejects_non_canonical_labels(tmp_path):
    """End-to-end: a market with Higher/Lower labels is rejected for
    identity, proving the fix is conservative."""
    gamma = _SequenceGamma([[FIXTURE_NON_CANONICAL_LABELS]])
    result = discover_markets_v3(_config(300), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["up_down_token_identity_unproven"] == 1


def test_discovery_pagination_finds_btc_on_page_3(tmp_path):
    """End-to-end: pagination across 3 pages with BTC market on page 3.
    Uses HttpxGammaDiscoveryClient with MockTransport to properly simulate
    multi-page fetching (the _SequenceGamma helper only returns a single
    concatenated response)."""
    import httpx
    from discovery_v3 import HttpxGammaDiscoveryClient

    pages = make_paginated_responses()
    all_markets = pages[0] + pages[1] + pages[2]
    offsets_seen = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets_seen.append(offset)
        page_size = int(request.url.params["limit"])
        return httpx.Response(200, json=all_markets[offset:offset + page_size])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["total_received"] == 201
    assert offsets_seen == [0, 100, 200]
    # The non-BTC generic markets should not pollute identity histogram
    assert result["evidence"]["rejection_histogram"]["up_down_token_identity_unproven"] == 0
    assert result["evidence"]["rejection_histogram"]["btc_event_identity_unproven"] == 200


def test_discovery_duplicated_market_across_pages(tmp_path):
    """End-to-end: duplicated conditionId across pages. The current code
    does NOT deduplicate, so both copies are processed. This test
    documents the existing behavior (not necessarily desirable) so any
    future dedup change is intentional.

    Uses HttpxGammaDiscoveryClient with MockTransport to serve the same
    market on two consecutive offsets."""
    import httpx
    from discovery_v3 import HttpxGammaDiscoveryClient

    duplicate_market = FIXTURE_VALID_BTC_UP_DOWN_300S
    offsets_seen = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets_seen.append(offset)
        page_size = int(request.url.params["limit"])
        # Page 1 returns a full page (page_size markets), page 2 returns
        # a short page to signal source exhaustion.
        if offset == 0:
            return httpx.Response(200, json=[duplicate_market] * page_size)
        return httpx.Response(200, json=[duplicate_market])  # 1 < page_size → exhausted

    client = HttpxGammaDiscoveryClient(page_size=2, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 4, client, evidence_dir=tmp_path)
    # Page1 returns 2 copies, page2 returns 1 copy → 3 raw markets, all duplicates.
    # The current code does NOT deduplicate, so all 3 are processed and selected.
    assert result["status"] == "SELECTED_NONEMPTY"
    assert len(result["evidence"]["raw_gamma"]) == 3
    assert len(result["markets"]) == 3  # no dedup — all 3 copies selected
    assert result["evidence"]["rejection_histogram"]["up_down_token_identity_unproven"] == 0
    assert result["evidence"]["source_exhausted"] is True


def test_discovery_real_shape_btc_long_window_rejected_for_window(tmp_path):
    """End-to-end: real-shape BTC long-window market is rejected for
    window_duration_mismatch, NOT for identity. This is the key behavior
    change — the rejection histogram will now show the TRUE reason."""
    gamma = _SequenceGamma([[FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW]])
    result = discover_markets_v3(_config(300), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    h = result["evidence"]["rejection_histogram"]
    assert h["up_down_token_identity_unproven"] == 0
    assert h["window_duration_mismatch"] == 1


def test_discovery_mixed_cohort_rejects_for_correct_reasons(tmp_path):
    """End-to-end: a mixed cohort where each market is rejected for a
    DIFFERENT reason. After the fix, the histogram accurately reflects
    the true rejection causes (no identity-rejection pollution).

    Markets and their expected rejection reasons:
      - FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW: window_duration_mismatch
        (BTC identity OK, resolution rule OK, Yes/No identity OK, but
        endDate-startDate is multi-month, not 300s)
      - FIXTURE_NON_BTC_MARKET: btc_event_identity_unproven +
        resolution_rule_unproven + window_duration_mismatch
        (slug has no bitcoin/btc, description has no BTC price oracle,
        29-day window)
      - FIXTURE_AMBIGUOUS_BTC_NO_ORACLE: resolution_rule_unproven
        (BTC in slug but description has no oracle)
      - FIXTURE_MISSING_WINDOW_TIMESTAMPS: window_timestamps_unproven
      - FIXTURE_MISSING_CONDITION_ID: missing_condition_id
      - FIXTURE_NON_CANONICAL_LABELS: up_down_token_identity_unproven
      - FIXTURE_NON_BINARY_3_OUTCOMES: up_down_token_identity_unproven
      - FIXTURE_VALID_BTC_UP_DOWN_300S: PASSES
    """
    markets = [
        FIXTURE_REAL_SHAPE_BTC_LONG_WINDOW,
        FIXTURE_NON_BTC_MARKET,
        FIXTURE_AMBIGUOUS_BTC_NO_ORACLE,
        FIXTURE_MISSING_WINDOW_TIMESTAMPS,
        FIXTURE_MISSING_CONDITION_ID,
        FIXTURE_NON_CANONICAL_LABELS,
        FIXTURE_NON_BINARY_3_OUTCOMES,
        FIXTURE_VALID_BTC_UP_DOWN_300S,
    ]
    gamma = _SequenceGamma([markets])
    result = discover_markets_v3(_config(300), 500, gamma, evidence_dir=tmp_path)
    h = result["evidence"]["rejection_histogram"]
    assert h["window_duration_mismatch"] == 2  # real_shape + non_btc
    assert h["btc_event_identity_unproven"] == 1  # non_btc only
    assert h["resolution_rule_unproven"] == 2  # non_btc + ambiguous
    assert h["window_timestamps_unproven"] == 1  # missing timestamps
    assert h["missing_condition_id"] == 1
    assert h["up_down_token_identity_unproven"] == 2  # non-canonical + 3-outcome
    assert len(result["markets"]) == 1


# ─────────────────────────────────────────────────────────────────────
# Fixture integrity: every fixture is well-formed
# ─────────────────────────────────────────────────────────────────────

def test_all_fixtures_have_condition_id_or_intentionally_omit():
    """Every fixture either has a non-empty conditionId or is explicitly
    testing the missing-conditionId case."""
    missing_cid_fixtures = {"missing_condition_id"}
    for name, fixture in ALL_FIXTURES.items():
        if name in missing_cid_fixtures:
            assert fixture.get("conditionId", "") == "", \
                f"Fixture {name} should have empty conditionId"
        else:
            assert fixture.get("conditionId"), \
                f"Fixture {name} should have non-empty conditionId"


def test_fixtures_do_not_leak_real_token_ids():
    """Synthetic token IDs only. Real Polymarket token IDs are 76-digit
    numeric strings; our synthetic ones use repeated digits or short strings."""
    real_token_pattern_substr = "105267568073659068217311993901927962476298440625043565106676088842803600775810"
    # The real_shape fixture intentionally uses a real token ID structure
    # to test against production payload shape. This is documented in the
    # fixture module docstring. The token ID itself is a public on-chain
    # identifier (not a secret).
    for name, fixture in ALL_FIXTURES.items():
        if name == "real_shape_btc_long_window":
            continue
        tokens = fixture.get("clobTokenIds", [])
        if isinstance(tokens, list):
            for t in tokens:
                assert not (isinstance(t, str) and len(t) >= 70 and t.isdigit()), \
                    f"Fixture {name} appears to contain a real 76-digit token ID"
