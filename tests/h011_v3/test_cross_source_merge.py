"""Tests for cross-source merge /markets + /events and conflict detection."""
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


# ═══════════════════════════════════════════════════════════════════════
# _structural_key
# ═══════════════════════════════════════════════════════════════════════

def test_structural_key_prefers_conditionId():
    market = {"conditionId": "0xABC", "id": "123"}
    assert _structural_key(market) == "cid:0xabc"  # lowercased


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
    """If /markets is missing a field that /events has, merge fills it."""
    market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        # Missing: eventStartTime, endDate, active, closed, resolutionSource
    }
    event_market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
        "endDate": "2025-12-19T16:40:00Z",
        "active": True,
        "closed": False,
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }
    parent_event = {"id": "109968", "ticker": "btc-updown-5m-1766162100", "slug": "btc-updown-5m-1766162100"}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None
    assert merged["eventStartTime"] == "2025-12-19T16:35:00Z"
    assert merged["endDate"] == "2025-12-19T16:40:00Z"
    assert merged["active"] is True
    assert merged["closed"] is False
    assert merged["resolutionSource"] == "https://data.chain.link/streams/btc-usd"


def test_merge_does_not_overwrite_market_field_with_event_value():
    """If /markets has a field with a value that matches /events, the
    /markets value is kept (priority). No conflict when values are equal."""
    market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
    }
    event_market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',  # same as /markets — no conflict
        "eventStartTime": "2025-12-19T16:35:00Z",
    }
    parent_event = {"id": "109968"}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    # No conflict because values are equal; /markets value kept
    assert conflict is None
    assert "t1" in merged["clobTokenIds"]


def test_merge_contradiction_on_clobTokenIds_is_conflict():
    """If /markets and /events have DIFFERENT clobTokenIds, it IS a
    cross_source_identity_conflict (per GPT-5.6 rule: 'ante contradicción
    material entre fuentes, rechazar')."""
    market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1-from-markets","t2-from-markets"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
    }
    event_market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1-from-events","t2-from-events"]',  # different
        "eventStartTime": "2025-12-19T16:35:00Z",
    }
    parent_event = {"id": "109968"}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    # Contradiction → conflict
    assert conflict == "cross_source_identity_conflict"
    assert merged is None


def test_merge_does_not_overwrite_with_null_or_empty():
    """A non-null market field must not be overwritten by null/empty from event."""
    market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
        "active": True,
    }
    event_market = {
        "conditionId": "0xabc",
        "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "resolutionSource": "",  # empty — must NOT overwrite
        "active": None,  # None — must NOT overwrite
    }
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None
    assert merged["resolutionSource"] == "https://data.chain.link/streams/btc-usd"
    assert merged["active"] is True


# ═══════════════════════════════════════════════════════════════════════
# _merge_market_and_event — conflict detection
# ═══════════════════════════════════════════════════════════════════════

def test_merge_detects_contradiction_on_slug():
    """If /markets and /events have DIFFERENT non-empty slugs, conflict."""
    market = {"conditionId": "0xabc", "id": "123", "slug": "btc-updown-5m-1766162100"}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "btc-updown-5m-1766162400"}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict == "cross_source_identity_conflict"
    assert merged is None


def test_merge_detects_contradiction_on_outcomes():
    """If outcomes differ between sources, conflict."""
    market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Up","Down"]'}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Down","Up"]'}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict == "cross_source_identity_conflict"


def test_merge_detects_contradiction_on_eventStartTime():
    """If eventStartTime differs between sources, conflict."""
    market = {"conditionId": "0xabc", "id": "123", "slug": "x",
              "outcomes": '["Up","Down"]', "eventStartTime": "2025-12-19T16:35:00Z"}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x",
                    "outcomes": '["Up","Down"]', "eventStartTime": "2025-12-19T16:36:00Z"}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict == "cross_source_identity_conflict"


def test_merge_normalizes_json_strings_before_comparison():
    """outcomes='["Up","Down"]' (string) vs ["Up","Down"] (list) should NOT conflict."""
    market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": '["Up","Down"]'}
    event_market = {"conditionId": "0xabc", "id": "123", "slug": "x", "outcomes": ["Up", "Down"]}
    parent_event = {}
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None  # same content after JSON normalization


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: cross_source_identity_conflict rejection
# ═══════════════════════════════════════════════════════════════════════

def test_cross_source_conflict_rejected_in_discovery(tmp_path):
    """A market with contradictory /markets and /events data is rejected
    with cross_source_identity_conflict."""
    cid = "0x" + "ee" * 32
    market_payload = {
        "conditionId": cid, "id": "900999",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
        "endDate": "2025-12-19T16:40:00Z",
        "active": True, "closed": False,
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
        "description": 'Bitcoin Up or Down price comparison start vs end',
        "outcomePrices": '["0.48", "0.52"]',
    }
    # Same conditionId but DIFFERENT slug (conflict)
    event_market_payload = {**market_payload, "slug": "btc-updown-5m-1766162400"}
    event_payload = [{
        "id": "109968",
        "ticker": "btc-updown-5m-1766162400",
        "slug": "btc-updown-5m-1766162400",
        "markets": [event_market_payload],
    }]

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=[market_payload])
        elif request.url.path == "/events":
            return httpx.Response(200, json=event_payload)
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    h = result["evidence"]["rejection_histogram"]
    assert h["cross_source_identity_conflict"] == 1
    assert result["status"] == "EMPTY_SELECTED_COHORT"


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: handler validates path (no blind payload for both endpoints)
# ═══════════════════════════════════════════════════════════════════════

def test_handler_must_distinguish_endpoints(tmp_path):
    """The mock handler MUST validate the request path and return different
    payloads for /markets vs /events. A handler that returns the same
    payload for both is invalid (per GPT-5.6 rule 4)."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)
    paths_seen = []

    def handler(request):
        paths_seen.append(request.url.path)
        if request.url.path == "/markets":
            return httpx.Response(200, json=[valid])
        elif request.url.path == "/events":
            # Return an event wrapping the market
            return httpx.Response(200, json=[{
                "id": "109968",
                "ticker": valid["slug"],
                "slug": valid["slug"],
                "markets": [valid],
            }])
        return httpx.Response(404, json={"error": "not found"})

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    # Both endpoints were called
    assert "/markets" in paths_seen
    assert "/events" in paths_seen
    # Market is deduplicated by conditionId — only one in selected list
    assert len(result["markets"]) == 1


def test_handler_returning_same_payload_for_both_endpoints_still_dedups(tmp_path):
    """Even if a buggy handler returns the same payload for both endpoints,
    deduplication by conditionId ensures only one market is selected."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        # Buggy handler: ignores path, returns market list for both
        if request.url.path in ("/markets", "/events"):
            return httpx.Response(200, json=[valid])
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    # Both endpoints returned the same market; dedup by conditionId → 1 selected
    assert len(result["markets"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: pagination to source exhaustion with loop detection
# ═══════════════════════════════════════════════════════════════════════

def test_pagination_stops_on_partial_page(tmp_path):
    """Pagination stops when a page returns fewer records than requested."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        offset = int(request.url.params["offset"])
        if request.url.path == "/markets":
            if offset == 0:
                # Full page of 100 generic markets
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"generic-{i}"}
                    for i in range(100)
                ])
            elif offset == 100:
                # Partial page (50 records) — source exhausted
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{i + 100:064x}", "id": str(i + 100), "slug": f"generic-{i + 100}"}
                    for i in range(50)
                ])
            else:
                return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path)
    # Source exhausted after 150 markets
    assert result["evidence"]["source_exhausted"] is True
    assert result["evidence"]["total_received"] == 150


def test_pagination_detects_loop_and_stops(tmp_path):
    """If the same page is returned at the same offset twice, the client
    detects the loop and stops."""
    # Pathological handler: always returns the same page
    same_page = [{"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"fixed-{i}"}
                 for i in range(100)]

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=same_page)
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path)
    # Loop detected after 2 pages (page 0 and page 100 both start with same conditionId)
    # Client should not iterate infinitely
    assert result["evidence"]["total_received"] <= 200


def test_pagination_finds_market_at_offset_500(tmp_path):
    """A valid btc-updown-5m market located beyond offset 500 is discovered."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100, condition_id="0x" + "ff" * 32)

    def handler(request):
        offset = int(request.url.params["offset"])
        if request.url.path == "/markets":
            if offset < 500:
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                     "slug": f"generic-{offset + i}"}
                    for i in range(100)
                ])
            elif offset == 500:
                # Page with the valid market at position 0
                page = [{"conditionId": f"0x{500 + i:064x}", "id": str(500 + i),
                         "slug": f"generic-{500 + i}"}
                        for i in range(99)]
                page.insert(0, valid)
                return httpx.Response(200, json=page)
            elif offset == 600:
                # Partial page — source exhausted
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{600 + i:064x}", "id": str(600 + i),
                     "slug": f"generic-{600 + i}"}
                    for i in range(50)
                ])
            else:
                return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert len(result["markets"]) == 1
    assert result["markets"][0]["conditionId"] == "0x" + "ff" * 32


# ═══════════════════════════════════════════════════════════════════════
# Discovery metrics reporting
# ═══════════════════════════════════════════════════════════════════════

def test_discovery_metrics_present_in_evidence(tmp_path):
    """The discovery evidence includes metrics about both endpoints."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=[valid])
        elif request.url.path == "/events":
            return httpx.Response(200, json=[{
                "id": "109968",
                "ticker": valid["slug"],
                "slug": valid["slug"],
                "markets": [valid],
            }])
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    # The evidence should include raw_gamma with the merged market
    assert "raw_gamma" in result["evidence"]
    assert len(result["evidence"]["raw_gamma"]) >= 1


# ═══════════════════════════════════════════════════════════════════════
# /events endpoint as fallback when /markets is unavailable
# ═══════════════════════════════════════════════════════════════════════

def test_events_endpoint_serves_as_fallback_when_markets_fails(tmp_path):
    """If /markets fails, /events can still provide market data."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            # /markets returns error
            return httpx.Response(500, json={"error": "internal server error"})
        elif request.url.path == "/events":
            return httpx.Response(200, json=[{
                "id": "109968",
                "ticker": valid["slug"],
                "slug": valid["slug"],
                "markets": [valid],
            }])
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    # /events provided the market; discovery succeeds
    assert result["status"] == "SELECTED_NONEMPTY"
    assert len(result["markets"]) == 1
