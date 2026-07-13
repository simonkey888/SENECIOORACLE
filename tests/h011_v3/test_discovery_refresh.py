import hashlib
import gzip
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from polymarket.discovery_v3 import (
    discover_markets_v3,
    HttpxGammaDiscoveryClient,
    monitor_discovery_loop,
    replay_discovery,
)


# Canonical H-011 V3 BTC 5-min Up/Down market fixture.
# Matches the production Polymarket contract (verified 2026-07-13 across
# 13 markets): slug = btc-updown-5m-<10-digit-epoch>, outcomes = ["Up","Down"],
# eventStartTime == slug_epoch, endDate = eventStartTime + 300s.
DEFAULT_SLUG_EPOCH = 1766162100  # 2025-12-19T16:35:00Z
DEFAULT_WINDOW_S = 300


def market(*, cid="0x" + "a" * 64, slug_epoch=DEFAULT_SLUG_EPOCH,
           window_s=DEFAULT_WINDOW_S, outcomes=None,
           resolution_source="https://data.chain.link/streams/btc-usd",
           description=None, ticker=None, active=True, closed=False,
           override_slug=None, override_event_start=None, override_end_date=None,
           override_start_date=None):
    """Build a canonical btc-updown-5m market fixture.

    Defaults produce a market that PASSES validate_btc_market_identity.
    Override parameters to construct invalid variants for rejection tests.
    """
    slug = override_slug or f"btc-updown-5m-{slug_epoch}"
    event_start = override_event_start or datetime.fromtimestamp(
        slug_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_date = override_end_date or datetime.fromtimestamp(
        slug_epoch + window_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # startDate is ~24h before (lifecycle metadata, NOT the H-011 window)
    start_date = override_start_date or datetime.fromtimestamp(
        slug_epoch - 86400, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    desc = description or (
        'This market will resolve to "Up" if the Bitcoin price at the end of '
        'the time range specified in the title is greater than or equal to '
        'the price at the beginning of that range. Otherwise, it will resolve '
        'to "Down".'
    )
    return {
        "conditionId": cid,
        "id": "900001",
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "description": desc,
        "resolutionSource": resolution_source,
        "outcomes": outcomes or ["Up", "Down"],
        "clobTokenIds": [f"{cid}-up-token-synthetic", f"{cid}-down-token-synthetic"],
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
            "id": "109968",
            "ticker": ticker or slug,
            "slug": slug,
            "title": "Bitcoin Up or Down",
            "description": desc,
            "resolutionSource": resolution_source,
        }],
    }


class SequenceGamma:
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


def config():
    return SimpleNamespace(window_s=300)


def test_first_cycle_empty_second_cycle_processes_new_btc_market(tmp_path):
    gamma = SequenceGamma([[], [market()]])
    discovered_counts = []

    def discover():
        return discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)

    results = monitor_discovery_loop(
        discover=discover,
        process=lambda result: discovered_counts.append(len(result["markets"])),
        sleep=lambda _: None,
        max_cycles=2,
    )
    assert gamma.calls == 2
    assert discovered_counts == [0, 1]
    assert results == [None, None]


def test_monitor_refreshes_gamma_every_cycle(tmp_path):
    gamma = SequenceGamma([[], [], []])
    monitor_discovery_loop(
        discover=lambda: discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path),
        process=lambda result: result["status"],
        sleep=lambda _: None,
        max_cycles=3,
    )
    assert gamma.calls == 3


def test_window_300_rejects_structurally_valid_window_900(tmp_path):
    # Build a market with a 900s window (endDate - eventStartTime = 900s)
    gamma = SequenceGamma([[market(window_s=900)]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["window_duration_mismatch"] == 1


def test_rejection_histogram_preserves_all_reasons(tmp_path):
    # Build a market that fails multiple checks simultaneously:
    #   - slug doesn't match btc-updown-5m pattern → directional_market_identity_unproven
    #   - outcomes are ["Higher","Lower"] (not ["Up","Down"]) → token_direction_mapping_unproven
    #   - resolutionSource is empty → resolution_rule_unproven
    #   - active=False or closed=True → market_inactive_or_closed
    #   - missing conditionId → missing_condition_id
    # Note: includes a valid market `id` so the market reaches the validator
    # (markets without both conditionId AND id are short-circuited with
    # missing_structural_identifier before reaching validate_btc_market_identity).
    invalid = {
        "id": "999999",
        "slug": "ethereum-market",
        "startDate": None,
        "endDate": None,
        "eventStartTime": None,
        "outcomes": ["Higher", "Lower"],
        "clobTokenIds": ["a", "b"],
        "outcomePrices": ["0.4", "0.6"],
        "resolutionSource": "",
        "description": "",
        "active": False,
        "closed": True,
    }
    gamma = SequenceGamma([[invalid]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    histogram = result["evidence"]["rejection_histogram"]
    assert histogram["missing_condition_id"] == 1
    assert histogram["directional_market_identity_unproven"] == 1
    assert histogram["token_direction_mapping_unproven"] == 1
    assert histogram["resolution_rule_unproven"] == 1
    assert histogram["market_inactive_or_closed"] == 1


def test_market_without_conditionId_or_id_rejected_with_missing_structural_identifier(tmp_path):
    """A market missing BOTH conditionId and market id cannot be deduplicated
    structurally — rejected with missing_structural_identifier."""
    invalid = {
        "slug": "anonymous-market",
        "outcomes": ["Up", "Down"],
        "clobTokenIds": ["a", "b"],
        "outcomePrices": ["0.4", "0.6"],
    }
    gamma = SequenceGamma([[invalid]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    histogram = result["evidence"]["rejection_histogram"]
    assert histogram["missing_structural_identifier"] == 1


def test_valid_market_after_position_200_is_discovered(tmp_path):
    generic = [
        {
            "conditionId": f"0x{i:064x}", "slug": f"generic-{i}",
            "outcomes": ["Yes", "No"], "clobTokenIds": [f"a{i}-synthetic", f"b{i}-synthetic"],
            "outcomePrices": '["0.4", "0.6"]',
        }
        for i in range(220)
    ]
    valid_market = market()
    gamma = SequenceGamma([generic + [valid_market]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["total_received"] == 221
    assert result["markets"][0]["conditionId"] == valid_market["conditionId"]


def test_gamma_failure_is_not_empty_cohort(tmp_path):
    gamma = SequenceGamma([RuntimeError("Gamma unavailable")])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_SOURCE_FAILED"
    assert result["discovery_complete"] is False


def test_empty_gamma_is_source_empty(tmp_path):
    gamma = SequenceGamma([[]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "DISCOVERY_SOURCE_EMPTY"
    assert result["discovery_complete"] is True


def test_discovery_sidecar_matches_exact_bytes(tmp_path):
    gamma = SequenceGamma([[market()]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    artifact = result["artifact_path"]
    with open(artifact, "rb") as handle:
        expected = hashlib.sha256(handle.read()).hexdigest()
    with open(artifact + ".sha256", encoding="ascii") as handle:
        sidecar = handle.read().strip()
    assert sidecar == expected
    assert result["file_sha256_matches"] is True


def test_http_client_paginates_offsets_and_finds_third_page_btc(tmp_path):
    offsets = []
    generic = [{"conditionId": f"0x{i:064x}", "slug": f"generic-{i}"} for i in range(200)]
    valid_market = market()

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        if offset < 200:
            return httpx.Response(200, json=generic[offset:offset + 100])
        return httpx.Response(200, json=[valid_market])

    # Use fetch_events=False so the test only hits /markets
    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(config(), 500, client, evidence_dir=tmp_path)
    assert offsets == [0, 100, 200]
    assert [page["offset"] for page in result["evidence"]["pages"]] == offsets
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["markets"][0]["conditionId"] == valid_market["conditionId"]
    assert result["evidence"]["source_exhausted"] is True


def test_full_pages_until_limit_are_truncated(tmp_path):
    calls = []

    def handler(request):
        offset = int(request.url.params["offset"])
        calls.append(offset)
        # Return 100 unique markets per page, indexed by offset so no dups
        return httpx.Response(200, json=[{"conditionId": f"0x{offset + n:064x}"} for n in range(100)])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler),
                                       fetch_events=False)
    result = discover_markets_v3(config(), 2000, client, evidence_dir=tmp_path)
    assert len(calls) == 20
    assert result["status"] == "DISCOVERY_TRUNCATED"
    assert result["discovery_complete"] is False
    assert result["evidence"]["source_exhausted"] is False
    assert result["evidence"]["limit_reached"] is True
    assert result["evidence"]["next_offset"] == 2000


def test_evidence_is_compressed_atomic_and_replay_verified(tmp_path):
    valid_market = market()
    result = discover_markets_v3(config(), 500, SequenceGamma([[valid_market]]), evidence_dir=tmp_path)
    artifact = tmp_path / result["artifact_path"]
    assert str(artifact).endswith(".json.gz")
    assert not list(tmp_path.glob("*.tmp"))
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    assert evidence["raw_gamma"][0]["conditionId"] == valid_market["conditionId"]
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["discovery_replay_verified"] is True
    assert result["discovery_replay_verified"] is True


def test_discovery_replay_detects_tampered_selection(tmp_path):
    result = discover_markets_v3(config(), 500, SequenceGamma([[market()]]), evidence_dir=tmp_path)
    artifact = tmp_path / result["artifact_path"]
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    evidence["selected_condition_ids"] = ["tampered"]
    artifact.write_bytes(gzip.compress(json.dumps(evidence).encode(), mtime=0))
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["selected_ids_match"] is False
    assert replay["discovery_replay_verified"] is False


def test_retention_count_and_bytes_keep_newest(tmp_path):
    last_result = None
    for index in range(4):
        last_result = discover_markets_v3(
            config(), 500, SequenceGamma([[market(cid=f"0x{index:064x}")]]),
            evidence_dir=tmp_path, retention_count=2, retention_bytes=1,
        )
    artifacts = list(tmp_path.glob("discovery_*.json.gz"))
    assert len(artifacts) == 1
    assert artifacts[0] == tmp_path / last_result["artifact_path"]
    assert artifacts[0].with_suffix(".gz.sha256").exists()


def test_v3_dockerfile_packages_discovery_module():
    dockerfile = (__import__("pathlib").Path(__file__).parents[2] / "polymarket" / "Dockerfile.h011-v3").read_text()
    assert "polymarket/discovery_v3.py" in dockerfile


@pytest.mark.parametrize("prices", [
    [], ["0.4"], ["0.2", "0.3", "0.5"], ["NaN", "0.5"],
    ["Infinity", "0.5"], ["-0.1", "1.1"], ["1.1", "-0.1"], ["nope", "1.0"],
])
def test_invalid_outcome_prices_are_rejected(tmp_path, prices):
    candidate = market()
    candidate["outcomePrices"] = prices
    result = discover_markets_v3(config(), 500, SequenceGamma([[candidate]]), evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["invalid_outcome_prices"] == 1


def test_missing_outcome_prices_is_accepted(tmp_path):
    """Missing/None outcomePrices means "no trades yet" — this is valid for
    newly listed markets (e.g., btc-updown-5m markets that have not yet
    seen any trade activity). The market should still be discoverable."""
    candidate = market()
    candidate.pop("outcomePrices")
    result = discover_markets_v3(config(), 500, SequenceGamma([[candidate]]), evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["rejection_histogram"]["invalid_outcome_prices"] == 0


def test_none_outcome_prices_is_accepted(tmp_path):
    """outcomePrices=None (explicit None) is also accepted as "no trades yet"."""
    candidate = market()
    candidate["outcomePrices"] = None
    result = discover_markets_v3(config(), 500, SequenceGamma([[candidate]]), evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["rejection_histogram"]["invalid_outcome_prices"] == 0


def test_valid_and_resolved_outcome_prices_are_distinct(tmp_path):
    valid = discover_markets_v3(config(), 500, SequenceGamma([[market()]]), evidence_dir=tmp_path)
    assert valid["status"] == "SELECTED_NONEMPTY"
    resolved_market = market()
    resolved_market["outcomePrices"] = ["0.96", "0.04"]
    resolved = discover_markets_v3(config(), 500, SequenceGamma([[resolved_market]]), evidence_dir=tmp_path)
    assert resolved["status"] == "EMPTY_SELECTED_COHORT"
    assert resolved["evidence"]["rejection_histogram"]["resolved_extreme_prices"] == 1


@pytest.mark.parametrize("field,value", [
    ("window_s", 900), ("max_markets", 3), ("gamma_limit", 999),
    ("resolved_price_threshold", 0.90),
])
def test_replay_rejects_tampered_selection_configuration(tmp_path, field, value):
    result = discover_markets_v3(config(), 500, SequenceGamma([[market()]]), evidence_dir=tmp_path)
    artifact = tmp_path / result["artifact_path"]
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    original = dict(evidence["selection_config"])
    evidence["selection_config"][field] = value
    artifact.write_bytes(gzip.compress(json.dumps(evidence).encode(), mtime=0))
    replay = replay_discovery(artifact, expected_selection_config=original)
    assert replay["discovery_replay_verified"] is False
    assert replay[{
        "window_s": "window_matches", "max_markets": "max_markets_matches",
        "gamma_limit": "gamma_limit_matches", "resolved_price_threshold": "price_threshold_matches",
    }[field]] is False


@pytest.mark.parametrize("mutation", [
    lambda evidence: evidence["pages"][0].update(count=99),
    lambda evidence: evidence["pages"][0].update(offset=7),
    lambda evidence: evidence.update(limit_reached=True),
    lambda evidence: evidence.update(source_exhausted=False),
])
def test_replay_rejects_tampered_pagination_metadata(tmp_path, mutation):
    result = discover_markets_v3(config(), 500, SequenceGamma([[market()]]), evidence_dir=tmp_path)
    artifact = tmp_path / result["artifact_path"]
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    mutation(evidence)
    artifact.write_bytes(gzip.compress(json.dumps(evidence).encode(), mtime=0))
    replay = replay_discovery(artifact, expected_selection_config=result["evidence"]["selection_config"])
    assert replay["discovery_replay_verified"] is False
