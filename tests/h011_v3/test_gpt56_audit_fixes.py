"""GPT-5.6 third audit tests — keyset pagination + temporal eligibility.

Updated for the keyset-based client (Fix #1) and as_of_ts temporal
eligibility (Fix #3).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

from discovery_v3 import (
    HttpxGammaDiscoveryClient,
    discover_markets_v3,
    replay_discovery,
    _merge_market_and_event,
)
from h011_v3_pipeline import validate_btc_market_identity
from tests.h011_v3.fixtures_gamma import make_real_btc_updown_market


def _config(window_s=300):
    return SimpleNamespace(window_s=window_s)


# as_of_ts inside the default market window (16:35:00Z to 16:40:00Z)
_AS_OF_TS = "2025-12-19T16:37:30Z"
# as_of_ts AFTER the default market window (historical)
_AS_OF_HISTORICAL = "2026-07-13T05:00:00Z"


# ═══════════════════════════════════════════════════════════════════════
# Test 1: keyset finds market, offset-based would miss it
# ═══════════════════════════════════════════════════════════════════════

def test_keyset_finds_btc_updown_market(tmp_path):
    """Test 1: keyset pagination finds the btc-updown-5m market regardless
    of its position in the event list (no offset limit)."""
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
    assert result["evidence"]["selected_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Test 2: keyset exhausted → discovery_complete=true
# ═══════════════════════════════════════════════════════════════════════

def test_keyset_exhausted_discovery_complete(tmp_path):
    """Test 2: when keyset returns no next_cursor, source is exhausted
    and discovery_complete is True."""
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
    assert result["discovery_complete"] is True


def test_keyset_truncated_discovery_incomplete(tmp_path):
    """Test 2 (variant): when keyset hits max_pages, discovery is incomplete."""
    call_count = 0

    def handler(request):
        nonlocal call_count
        if request.url.path == "/events/keyset":
            call_count += 1
            # Always return a next_cursor (never exhausts)
            return httpx.Response(200, json={
                "events": [],
                "next_cursor": f"cursor-{call_count}",
            })
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler),
                                       max_pages_per_endpoint=3)
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["evidence"]["source_exhausted"] is False
    assert result["discovery_complete"] is False
    assert result["evidence"]["endpoint_states"]["/events/keyset"]["status"] == "limit_reached"


# ═══════════════════════════════════════════════════════════════════════
# Test 3: /events/keyset HTTP 500 → source failed
# ═══════════════════════════════════════════════════════════════════════

def test_keyset_500_source_failed(tmp_path):
    """Test 3: /events/keyset returns HTTP 500 → DISCOVERY_SOURCE_FAILED."""
    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(500, json={"error": "internal server error"})
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["source_health"] == "FAILED"
    assert result["evidence"]["selected_count"] == 0
    assert result["evidence"]["endpoint_states"]["/events/keyset"]["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════
# Test 4: client.get raises → no UnboundLocalError
# ═══════════════════════════════════════════════════════════════════════

def test_client_get_raises_no_unbound_local_error(tmp_path):
    """Test 4: if client.get raises before response is assigned, the error
    is reported as a structured endpoint error — NOT UnboundLocalError."""
    transport = httpx.MockTransport(lambda req: (_ for _ in ()).throw(
        httpx.ConnectError("connection refused", request=req)))

    client = HttpxGammaDiscoveryClient(page_size=500, transport=transport)
    try:
        result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                    as_of_ts=_AS_OF_TS)
        assert result["status"] == "DISCOVERY_SOURCE_FAILED"
        assert result["evidence"]["source_health"] == "FAILED"
        endpoint_state = result["evidence"]["endpoint_states"]["/events/keyset"]
        assert endpoint_state["status"] == "error"
        assert "ConnectError" in (endpoint_state["error"] or "")
    except UnboundLocalError as e:
        pytest.fail(f"UnboundLocalError raised instead of structured error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Test 5: cursor loop detection
# ═══════════════════════════════════════════════════════════════════════

def test_cursor_loop_detected(tmp_path):
    """Test 5: if the same cursor is returned twice, loop is detected."""
    same_cursor = "fixed-cursor-xyz"

    def handler(request):
        if request.url.path == "/events/keyset":
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


# ═══════════════════════════════════════════════════════════════════════
# Test 6: valid slug without parent event → rejection
# ═══════════════════════════════════════════════════════════════════════

def test_valid_slug_without_parent_event_rejected():
    """Test 6: market with valid slug but no parent event is rejected."""
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    market.pop("events", None)
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


def test_valid_slug_with_empty_events_list_rejected():
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    market["events"] = []
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


def test_valid_slug_with_event_no_id_rejected():
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    market["events"] = [{"ticker": market["slug"], "slug": market["slug"]}]
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


# ═══════════════════════════════════════════════════════════════════════
# Test 7: description only in parent event → top-level enrichment
# ═══════════════════════════════════════════════════════════════════════

def test_description_only_in_parent_event_enriched_top_level():
    """Test 7: description from parent event is copied to merged market top level."""
    market = {
        "conditionId": "0xabc", "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
        "endDate": "2025-12-19T16:40:00Z",
        "active": True, "closed": False,
    }
    parent_event = {
        "id": "109968",
        "ticker": "btc-updown-5m-1766162100",
        "slug": "btc-updown-5m-1766162100",
        "description": 'This market will resolve to "Up" if Bitcoin price increases.',
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }
    merged, conflict = _merge_market_and_event(market, dict(market), parent_event)
    assert conflict is None
    assert merged.get("description") == parent_event["description"]
    assert merged.get("resolutionSource") == parent_event["resolutionSource"]


# ═══════════════════════════════════════════════════════════════════════
# Test 8: metrics conservation
# ═══════════════════════════════════════════════════════════════════════

def test_metrics_conservation(tmp_path):
    """Test 8: unique_markets_after_dedup <= records_before_dedup."""
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
    metrics = result["evidence"]["discovery_metrics"]
    assert metrics["unique_markets_after_dedup"] <= metrics["records_before_dedup"]


def test_metrics_conservation_assertion_exists():
    """Test 8 (variant): runtime assertion exists in fetch_pages."""
    import inspect
    from discovery_v3 import HttpxGammaDiscoveryClient
    source = inspect.getsource(HttpxGammaDiscoveryClient.fetch_pages)
    assert "assert unique_markets_after_dedup" in source


# ═══════════════════════════════════════════════════════════════════════
# Test 9: replay reproduces states
# ═══════════════════════════════════════════════════════════════════════

def test_replay_reproduces_source_failed_state(tmp_path):
    """Test 9: replay of DISCOVERY_SOURCE_FAILED reproduces the status."""
    def handler(request):
        if request.url.path == "/events/keyset":
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"

    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True


def test_replay_reproduces_truncated_state(tmp_path):
    """Test 9: replay of DISCOVERY_TRUNCATED reproduces the status."""
    call_count = 0

    def handler(request):
        nonlocal call_count
        if request.url.path == "/events/keyset":
            call_count += 1
            return httpx.Response(200, json={
                "events": [],
                "next_cursor": f"cursor-{call_count}",
            })
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=500, transport=httpx.MockTransport(handler),
                                       max_pages_per_endpoint=3)
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "DISCOVERY_TRUNCATED"

    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True


def test_replay_reproduces_loop_detected_state(tmp_path):
    """Test 9: replay of loop_detected reproduces source failed."""
    same_cursor = "fixed-cursor-xyz"

    def handler(request):
        if request.url.path == "/events/keyset":
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

    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True


# ═══════════════════════════════════════════════════════════════════════
# Test 10: Fix #3 — temporal eligibility
# ═══════════════════════════════════════════════════════════════════════

def test_historical_market_not_selected_with_current_as_of_ts(tmp_path):
    """Fix #3: a structurally valid market whose window has expired is NOT
    selected when as_of_ts is after the window. It's counted as
    historical_structural_matches instead."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)  # window: Dec 2025

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
    # as_of_ts is July 2026 — the market window (Dec 2025) has expired
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_HISTORICAL)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["selected_count"] == 0
    # But it's counted as a historical structural match
    assert result["evidence"]["historical_structural_matches_count"] == 1
    assert result["evidence"]["rejection_histogram"]["market_window_expired"] == 1


def test_current_market_selected_with_in_window_as_of_ts(tmp_path):
    """Fix #3: a structurally valid market whose window is open IS selected
    when as_of_ts is inside the window."""
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
    # as_of_ts is inside the window (midpoint)
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["selected_count"] == 1
    assert result["evidence"]["historical_structural_matches_count"] == 0


def test_future_market_not_selected(tmp_path):
    """Fix #3: a market whose window hasn't started yet is rejected with
    market_window_not_open."""
    # Use a future slug_epoch (year 2027)
    future_epoch = 1800000000  # ~2027
    valid = make_real_btc_updown_market(slug_epoch=future_epoch)

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
    # as_of_ts is 2025 — the market window (2027) hasn't started
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["market_window_not_open"] == 1


def test_replay_uses_stored_as_of_ts(tmp_path):
    """Fix #3: replay uses the as_of_ts stored in evidence, NOT current time."""
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
    # Run with as_of_ts inside the window → SELECTED
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path,
                                as_of_ts=_AS_OF_TS)
    assert result["status"] == "SELECTED_NONEMPTY"

    # Replay (which runs at "current time" but uses stored as_of_ts)
    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["discovery_replay_verified"] is True
    assert replay["as_of_ts_matches"] is True
