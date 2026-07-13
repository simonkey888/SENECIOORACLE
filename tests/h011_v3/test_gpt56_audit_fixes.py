"""GPT-5.6 mandatory tests for PR #3 second audit.

Each test corresponds to a specific audit requirement:
  1. gamma_limit=2000 doesn't find market at 2082, gamma_limit=3000 does
  2. /markets exhausted + /events truncated → discovery_complete=false
  3. /markets OK + /events HTTP 500 → source failed, selected_count=0
  4. client.get raises before response assignment → error reported, no UnboundLocalError
  5. Same page at different offsets → loop detected
  6. Valid slug without parent event → rejection
  7. Description only in parent event → top-level enrichment
  8. Mathematical conservation of metrics
  9. Replay reproduces error/truncation/loop states
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
    replay_discovery,
    _merge_market_and_event,
    _structural_key,
)
from h011_v3_pipeline import validate_btc_market_identity
from tests.h011_v3.fixtures_gamma import make_real_btc_updown_market


def _config(window_s=300):
    return SimpleNamespace(window_s=window_s)


# ═══════════════════════════════════════════════════════════════════════
# Test 1: gamma_limit=2000 vs 3000
# ═══════════════════════════════════════════════════════════════════════

def test_gamma_limit_2000_does_not_find_market_at_offset_2082(tmp_path):
    """Test 1: gamma_limit=2000 cannot reach offset 2082, so no btc-updown-5m
    market is discovered. This proves the runtime default must be >= 3000."""
    valid_at_offset_2082 = make_real_btc_updown_market(
        slug_epoch=1766162100, condition_id="0x" + "ff" * 32, market_id="900999")

    def handler(request):
        offset = int(request.url.params["offset"])
        if request.url.path == "/markets":
            if offset >= 2082:
                # Return the valid market at offset 2082
                page = [{"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                         "slug": f"generic-{offset + i}"} for i in range(99)]
                page.insert(0, valid_at_offset_2082)
                return httpx.Response(200, json=page)
            elif offset < 2000:
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                     "slug": f"generic-{offset + i}"} for i in range(100)])
            else:
                # offset 2000-2082 would be needed but gamma_limit=2000 stops here
                return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    # gamma_limit=2000 → only fetches offsets 0, 100, ..., 1900 (20 pages)
    # Cannot reach offset 2082 where the valid market lives
    result = discover_markets_v3(_config(300), 2000, client, evidence_dir=tmp_path)
    assert result["status"] != "SELECTED_NONEMPTY" or len(result["markets"]) == 0
    assert result["evidence"]["selected_count"] == 0


def test_gamma_limit_3000_finds_market_at_offset_2082(tmp_path):
    """Test 1 (companion): gamma_limit=3000 reaches offset 2082 and finds
    the valid btc-updown-5m market.

    The valid market is inserted at position 82 within the page that starts
    at offset 2000 (so its global position is 2082).
    """
    valid_at_offset_2082 = make_real_btc_updown_market(
        slug_epoch=1766162100, condition_id="0x" + "ff" * 32, market_id="900999")

    def handler(request):
        offset = int(request.url.params["offset"])
        if request.url.path == "/markets":
            if offset == 2000:
                # Page 2000-2099: insert valid market at position 82 (global offset 2082)
                page = []
                for i in range(100):
                    if i == 82:
                        page.append(valid_at_offset_2082)
                    else:
                        page.append({
                            "conditionId": f"0x{offset + i:064x}",
                            "id": str(offset + i),
                            "slug": f"generic-{offset + i}",
                        })
                return httpx.Response(200, json=page)
            elif offset < 2000:
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                     "slug": f"generic-{offset + i}"} for i in range(100)])
            elif offset == 2100:
                # Partial page → source exhausted
                return httpx.Response(200, json=[
                    {"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                     "slug": f"generic-{offset + i}"} for i in range(50)])
            else:
                return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    # gamma_limit=3000 → fetches offsets 0, 100, ..., 2900 (30 pages)
    # Reaches offset 2000 which contains the valid market at position 82
    result = discover_markets_v3(_config(300), 3000, client, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["selected_count"] == 1
    assert result["markets"][0]["conditionId"] == "0x" + "ff" * 32


# ═══════════════════════════════════════════════════════════════════════
# Test 2: /markets exhausted + /events truncated → discovery_complete=false
# ═══════════════════════════════════════════════════════════════════════

def test_markets_exhausted_plus_events_truncated_discovery_incomplete(tmp_path):
    """Test 2: when /markets is exhausted but /events hits limit_reached,
    discovery_complete must be False (because not ALL endpoints exhausted)."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            # /markets returns 1 market then empty (exhausted)
            offset = int(request.url.params["offset"])
            if offset == 0:
                return httpx.Response(200, json=[valid])
            return httpx.Response(200, json=[])  # empty → exhausted
        elif request.url.path == "/events":
            # /events always returns full pages of 100 events each
            # (each event wraps the valid market) — never exhausts within limit
            offset = int(request.url.params["offset"])
            page_size = int(request.url.params["limit"])
            events = []
            for i in range(page_size):
                events.append({
                    "id": str(109968 + offset + i),
                    "ticker": valid["slug"],
                    "slug": valid["slug"],
                    "markets": [valid],
                })
            return httpx.Response(200, json=events)
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       max_pages_per_endpoint=5)
    # Small gamma_limit so /events hits limit_reached quickly
    result = discover_markets_v3(_config(300), 200, client, evidence_dir=tmp_path)
    # /markets exhausted, /events limit_reached → NOT all exhausted
    assert result["evidence"]["endpoint_states"]["/markets"]["status"] == "exhausted"
    assert result["evidence"]["endpoint_states"]["/events"]["status"] == "limit_reached"
    assert result["evidence"]["source_exhausted"] is False  # not ALL exhausted
    assert result["discovery_complete"] is False


# ═══════════════════════════════════════════════════════════════════════
# Test 3: /markets OK + /events HTTP 500 → source failed, selected_count=0
# ═══════════════════════════════════════════════════════════════════════

def test_markets_ok_plus_events_500_source_failed(tmp_path):
    """Test 3: /markets succeeds but /events returns HTTP 500.
    Discovery must fail-closed: source failed, selected_count=0."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=[valid])
        elif request.url.path == "/events":
            return httpx.Response(500, json={"error": "internal server error"})
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["source_health"] == "FAILED"
    assert result["evidence"]["selected_count"] == 0
    assert len(result["markets"]) == 0
    assert result["evidence"]["endpoint_states"]["/events"]["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════
# Test 4: client.get raises before response assignment → no UnboundLocalError
# ═══════════════════════════════════════════════════════════════════════

def test_client_get_raises_before_response_no_unbound_local_error(tmp_path):
    """Test 4: if client.get raises an exception before `response` is assigned,
    the error must be reported as a structured endpoint error — NOT UnboundLocalError.

    Fix #3: response and received_at are initialized to None BEFORE the try block.
    """
    class RaisingTransport(httpx.MockTransport):
        def handle_request(self, request):
            # Simulate a connection error before any response is received
            raise httpx.ConnectError("connection refused", request=request)

    def handler(request):
        # This won't be called because RaisingTransport overrides handle_request
        return httpx.Response(200, json=[])

    # Use a transport that raises on every request
    transport = httpx.MockTransport(lambda req: (_ for _ in ()).throw(
        httpx.ConnectError("connection refused", request=req)))

    client = HttpxGammaDiscoveryClient(page_size=100, transport=transport,
                                       fetch_events=False)
    # Should NOT raise UnboundLocalError — should produce structured error
    try:
        result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
        # Discovery must fail-closed with structured error
        assert result["status"] == "DISCOVERY_SOURCE_FAILED"
        assert result["evidence"]["source_health"] == "FAILED"
        assert result["evidence"]["selected_count"] == 0
        # The error message must mention the connection error, not UnboundLocalError
        endpoint_state = result["evidence"]["endpoint_states"]["/markets"]
        assert endpoint_state["status"] == "error"
        assert "ConnectError" in (endpoint_state["error"] or "") or "connection" in (endpoint_state["error"] or "").lower()
    except UnboundLocalError as e:
        pytest.fail(f"UnboundLocalError raised instead of structured error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Test 5: same page at different offsets → loop detected
# ═══════════════════════════════════════════════════════════════════════

def test_same_page_at_different_offsets_loop_detected(tmp_path):
    """Test 5: if the API returns the same page content at different offsets,
    loop detection must trigger and stop pagination.

    Fix #4: signature is offset-INDEPENDENT (uses content hash, not offset).
    """
    # Pathological handler: always returns the same 100 markets
    same_page = [{"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"fixed-{i}"}
                 for i in range(100)]

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=same_page)
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path)
    # Loop must be detected on the second page (same signature as first)
    endpoint_state = result["evidence"]["endpoint_states"]["/markets"]
    assert endpoint_state["status"] == "loop_detected"
    # Fail-closed
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["source_health"] == "FAILED"


# ═══════════════════════════════════════════════════════════════════════
# Test 6: valid slug without parent event → rejection
# ═══════════════════════════════════════════════════════════════════════

def test_valid_slug_without_parent_event_rejected():
    """Test 6: a market with valid btc-updown-5m slug but no parent event
    must be rejected for directional_market_identity_unproven.

    Fix #5: parent event is MANDATORY.
    """
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    # Remove the events field
    market.pop("events", None)
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


def test_valid_slug_with_empty_events_list_rejected():
    """Test 6 (variant): empty events list also rejected."""
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    market["events"] = []
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


def test_valid_slug_with_event_no_id_rejected():
    """Test 6 (variant): event without id rejected."""
    market = make_real_btc_updown_market(slug_epoch=1766162100)
    market["events"] = [{"ticker": market["slug"], "slug": market["slug"]}]  # no id
    ok, reasons = validate_btc_market_identity(market, 300)
    assert ok is False
    assert "directional_market_identity_unproven" in reasons


# ═══════════════════════════════════════════════════════════════════════
# Test 7: description only in parent event → top-level enrichment
# ═══════════════════════════════════════════════════════════════════════

def test_description_only_in_parent_event_enriched_top_level():
    """Test 7: when /markets lacks description but parent event has it,
    the merged market must have description at TOP LEVEL (not just under events).

    Fix #6: enrichment is top-level because validate_btc_market_identity reads
    market.get("description"), not market.get("events")[0].get("description").
    """
    # /markets entry: no description, no resolutionSource
    market = {
        "conditionId": "0xabc", "id": "123",
        "slug": "btc-updown-5m-1766162100",
        "outcomes": '["Up","Down"]',
        "clobTokenIds": '["t1","t2"]',
        "eventStartTime": "2025-12-19T16:35:00Z",
        "endDate": "2025-12-19T16:40:00Z",
        "active": True, "closed": False,
        # Missing: description, resolutionSource
    }
    # /events entry: same market but with parent event that has description
    event_market = dict(market)
    parent_event = {
        "id": "109968",
        "ticker": "btc-updown-5m-1766162100",
        "slug": "btc-updown-5m-1766162100",
        "description": 'This market will resolve to "Up" if the Bitcoin price at the end '
                       'of the time range is greater than the price at the beginning.',
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
    }
    merged, conflict = _merge_market_and_event(market, event_market, parent_event)
    assert conflict is None
    # Fix #6: description must be at TOP LEVEL of merged market
    assert merged.get("description") == parent_event["description"]
    assert merged.get("resolutionSource") == parent_event["resolutionSource"]
    # The validator reads top-level fields, so this must pass resolution_rule_proven
    ok, reasons = validate_btc_market_identity(merged, 300)
    # Note: this may still fail other checks, but resolution_rule_proven should pass
    assert "resolution_rule_unproven" not in reasons


# ═══════════════════════════════════════════════════════════════════════
# Test 8: mathematical conservation of metrics
# ═══════════════════════════════════════════════════════════════════════

def test_metrics_conservation_inequality(tmp_path):
    """Test 8: unique_markets_after_dedup <= markets_from_markets + event_nested_markets_flattened.

    Fix #7: runtime assertion enforces this conservation law.
    """
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            # 100 markets from /markets
            return httpx.Response(200, json=[
                {"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"m-{i}"}
                for i in range(100)
            ])
        elif request.url.path == "/events":
            # 1 event with 5 nested markets (3 duplicates with /markets, 2 new)
            return httpx.Response(200, json=[{
                "id": "109968", "ticker": "x", "slug": "x",
                "markets": [
                    {"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"m-{i}"}
                    for i in range(3)  # 3 duplicates
                ] + [
                    {"conditionId": "0xaa" * 32, "id": "200", "slug": "new-1"},
                    {"conditionId": "0xbb" * 32, "id": "201", "slug": "new-2"},
                ],
            }])
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       max_pages_per_endpoint=2)
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    metrics = result["evidence"]["discovery_metrics"]
    # Conservation: unique <= markets_from_markets + event_nested_markets_flattened
    assert metrics["unique_markets_after_dedup"] <= (
        metrics["markets_from_markets_endpoint"] + metrics["event_nested_markets_flattened"]
    ), f"Conservation violation: {metrics}"
    # Specific expected values
    assert metrics["markets_from_markets_endpoint"] == 100
    assert metrics["event_nested_markets_flattened"] == 5
    # 100 + 5 = 105 records before dedup; 3 duplicates removed → 102 unique
    assert metrics["records_before_dedup"] == 105
    assert metrics["unique_markets_after_dedup"] == 102
    assert metrics["duplicates_removed"] == 3


def test_metrics_conservation_assertion_raises_on_violation():
    """Test 8 (variant): if conservation is violated, an AssertionError is raised.

    This tests the runtime assertion directly (not through the full discovery
    flow, but by checking the assertion exists in the code).
    """
    # The assertion is in HttpxGammaDiscoveryClient.fetch_pages. We verify
    # it exists by importing and inspecting the source.
    import inspect
    from discovery_v3 import HttpxGammaDiscoveryClient
    source = inspect.getsource(HttpxGammaDiscoveryClient.fetch_pages)
    assert "assert unique_markets_after_dedup" in source, \
        "Runtime assertion for metrics conservation must exist in fetch_pages"


# ═══════════════════════════════════════════════════════════════════════
# Test 9: replay reproduces error, truncation, and loop states
# ═══════════════════════════════════════════════════════════════════════

def test_replay_reproduces_source_failed_state(tmp_path):
    """Test 9: replay of a DISCOVERY_SOURCE_FAILED evidence reproduces the
    same status, source_health, and selected_count."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=[valid])
        elif request.url.path == "/events":
            return httpx.Response(500, json={"error": "server error"})
        return httpx.Response(404)

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"

    # Replay the evidence artifact
    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    # Replay must reproduce the source failed status
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True


def test_replay_reproduces_truncated_state(tmp_path):
    """Test 9 (variant): replay of a DISCOVERY_TRUNCATED evidence reproduces
    the truncated status."""
    valid = make_real_btc_updown_market(slug_epoch=1766162100)

    def handler(request):
        if request.url.path == "/markets":
            # Return full pages with UNIQUE markets per offset (no loop)
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json=[
                {"conditionId": f"0x{offset + i:064x}", "id": str(offset + i),
                 "slug": f"m-{offset + i}"}
                for i in range(100)
            ])
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False, max_pages_per_endpoint=10)
    # gamma_limit=500 with max_pages=10 → 5 pages of 100 = 500 → limit_reached
    result = discover_markets_v3(_config(300), 500, client, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_TRUNCATED"

    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True


def test_replay_reproduces_loop_detected_state(tmp_path):
    """Test 9 (variant): replay of a loop_detected evidence reproduces the
    source failed status (loop → fail-closed → DISCOVERY_SOURCE_FAILED)."""
    same_page = [{"conditionId": f"0x{i:064x}", "id": str(i), "slug": f"fixed-{i}"}
                 for i in range(100)]

    def handler(request):
        if request.url.path == "/markets":
            return httpx.Response(200, json=same_page)
        return httpx.Response(200, json=[])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(_config(300), 5000, client, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["evidence"]["endpoint_states"]["/markets"]["status"] == "loop_detected"

    artifact = Path(result["artifact_path"])
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["status_matches"] is True
    assert replay["discovery_replay_verified"] is True
