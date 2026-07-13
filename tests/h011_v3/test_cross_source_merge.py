"""Tests for cross-source merge: keyset events + canonical /markets/slug.

Fix #1 (third audit): the client now uses keyset pagination on /events/keyset
and fetches canonical metadata via /markets/slug/{slug} for each candidate.
The old offset-based /markets + /events merge tests no longer apply.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

from discovery_v3 import (
    HttpxGammaDiscoveryClient,
    discover_markets_v3,
    _structural_key,
    _merge_market_and_event,
    _MARKET_PRIORITY_FIELDS,
)
from tests.h011_v3.fixtures_gamma import make_real_btc_updown_market


def _config(window_s=300):
    return SimpleNamespace(window_s=window_s)


_AS_OF_TS = "2025-12-19T16:37:30Z"  # midpoint of default market window


# ═══════════════════════════════════════════════════════════════════════
# _structural_key
# ═══════════════════════════════════════════════════════════════════════

def test_structural_key_prefers_conditionId():
    market = {"conditionId": "0xABC", "id": "123"}
    assert _structural_key(market) == "cid:0xabc"


def test_structural_key_falls_back_to_id_when_no_conditionId():
    market = {"id": "123"}
    assert _structural_key(market) == "mid:123"


def test_structural_key_returns_none_when_both_missing():
    market = {"slug": "anonymous"}
    assert _structural_key(market) is None


def test_structural_key_normalizes_empty_string_as_missing():
    market = {"conditionId": "", "id": ""}
    assert _structural_key(market) is None


def test_structural_key_handles_condition_id_underscore_fallback():
    market = {"condition_id": "0xDEF"}
    assert _structural_key(market) == "cid:0xdef"


# ═══════════════════════════════════════════════════════════════════════
# _merge_market_and_event — happy path
# ═══════════════════════════════════════════════════════════════════════

def test_merge_fills_missing_market_fields_from_event():
    market = {
        "conditionId": "0xabc", "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
    }
    event_market = {
        "conditionId": "0xabc", "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
        "endDate": "2025-12-19T16:40:00Z",
        "active": True, "closed": False,
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }
    parent_event = {"id": "109968", "ticker": "btc-updown-5m-1766162100",
                    "slug": "btc-updown-5m-1766162100"}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None
    assert merged["eventStartTime"] == "2025-12-19T16:35:00Z"
    assert merged["endDate"] == "2025-12-19T16:40:00Z"


def test_merge_does_not_overwrite_with_null_or_empty():
    market = {"conditionId": "0xabc", "id": "123", "slug": "x",
              "outcomes": '["Up","Down"]', "clobTokenIds": '["t1","t2"]',
              "resolutionSource": "https://data.chain.link/streams/btc-usd",
              "active": True}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x",
                    "outcomes": '["Up","Down"]', "clobTokenIds": '["t1","t2"]',
                    "resolutionSource": "", "active": None}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None
    assert merged["resolutionSource"] == "https://data.chain.link/streams/btc-usd"
    assert merged["active"] is True


# ═══════════════════════════════════════════════════════════════════════
# _merge_market_and_event — conflict detection
# ═══════════════════════════════════════════════════════════════════════

def test_merge_detects_contradiction_on_slug():
    market = {"conditionId": "0xabc", "id": "123", "slug": "btc-updown-5m-1766162100"}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "btc-updown-5m-1766162400"}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict == "cross_source_identity_conflict"
    assert merged is None


def test_merge_detects_contradiction_on_outcomes():
    market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Up","Down"]'}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Down","Up"]'}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict == "cross_source_identity_conflict"


def test_merge_normalizes_json_strings_before_comparison():
    market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Up","Down"]'}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": ["Up", "Down"]}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: keyset flow
# ═══════════════════════════════════════════════════════════════════════

def test_keyset_finds_btc_updown_candidate(tmp_path):
    """Fix #1: keyset pagination finds a btc-updown-5m market."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(200, json={
                "events": [{
                    "id": "109968",
                    "ticker": valid["slug"],
                    "slug": valid["slug"],
                    "markets": [valid],
                }],
                "next_cursor": None,
            })
        elif request.url.path == f"/markets/slug/{valid['slug']}":
            return httpx.Response(200, json=valid)
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert len(result["markets"]) == 1


def test_keyset_fail_closed_on_events_500(tmp_path):
    """Fix #2: if /events/keyset returns 500, discovery is fail-closed."""
    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["source_health"] == "FAILED"
    assert len(result["markets"]) == 0


def test_keyset_loop_detection_on_repeated_cursor(tmp_path):
    """Fix #4: if the same cursor appears twice, loop is detected."""
    same_cursor = "fixed-cursor-abc"

    def handler(request):
        if request.url.path == "/events/keyset":
            # Always return the same cursor (loop)
            return httpx.Response(200, json={
                "events": [],
                "next_cursor": same_cursor,
            })
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler),
                                       max_pages_per_endpoint=10)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["endpoint_states"]["/events/keyset"]["status"] == "loop_detected"


def test_keyset_exhausted_when_no_next_cursor(tmp_path):
    """Fix #1: when next_cursor is None, source is exhausted."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(200, json={
                "events": [{
                    "id": "109968",
                    "ticker": valid["slug"],
                    "slug": valid["slug"],
                    "markets": [valid],
                }],
                "next_cursor": None,  # exhausted
            })
        elif request.url.path == f"/markets/slug/{valid['slug']}":
            return httpx.Response(200, json=valid)
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["evidence"]["source_exhausted"] is True
    assert result["evidence"]["endpoint_states"]["/events/keyset"]["status"] == "exhausted"
    assert result["discovery_complete"] is True


def test_keyset_enrichment_top_level_description(tmp_path):
    """Fix #6: when /markets/slug returns description but nested event market
    doesn't have it, the merged market has description at top level."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)
    # Nested market lacks description
    nested = {k: v for k, v in valid.items() if k != "description"}
    # Canonical market has description
    canonical = dict(valid)

    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(200, json={
                "events": [{
                    "id": "109968",
                    "ticker": valid["slug"],
                    "slug": valid["slug"],
                    "markets": [nested],
                }],
                "next_cursor": None,
            })
        elif request.url.path == f"/markets/slug/{valid['slug']}":
            return httpx.Response(200, json=canonical)
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "SELECTED_NONEMPTY"
    # The merged market should have description at top level
    assert result["markets"][0].get("description") == canonical["description"]
