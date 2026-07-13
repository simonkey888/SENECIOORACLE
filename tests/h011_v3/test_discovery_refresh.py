import hashlib
import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from polymarket.discovery_v3 import (
    discover_markets_v3,
    HttpxGammaDiscoveryClient,
    monitor_discovery_loop,
    replay_discovery,
)


def market(*, cid="0xbtc", duration=300, slug="bitcoin-up-or-down-5m",
           resolution="Bitcoin price oracle", outcomes=None):
    return {
        "conditionId": cid,
        "slug": slug,
        "question": "Bitcoin Up or Down",
        "resolutionSource": resolution,
        "startDate": 1000,
        "endDate": 1000 + duration,
        "outcomes": outcomes or ["UP", "DOWN"],
        "clobTokenIds": [f"{cid}-up", f"{cid}-down"],
        "outcomePrices": ["0.4", "0.6"],
        "volumeNum": 1000,
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
    gamma = SequenceGamma([[market(duration=900)]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["window_duration_mismatch"] == 1


def test_rejection_histogram_preserves_all_reasons(tmp_path):
    # outcomes uses non-canonical labels ("Higher"/"Lower") so the
    # up_down_token_identity_unproven rejection still fires after the fix
    # that accepts Yes/No and Up/Down as valid binary conventions.
    invalid = {
        "slug": "ethereum-market",
        "startDate": None,
        "endDate": None,
        "outcomes": ["Higher", "Lower"],
        "clobTokenIds": ["a", "b"],
        "outcomePrices": ["0.4", "0.6"],
    }
    gamma = SequenceGamma([[invalid]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    histogram = result["evidence"]["rejection_histogram"]
    assert histogram["missing_condition_id"] == 1
    assert histogram["btc_event_identity_unproven"] == 1
    assert histogram["resolution_rule_unproven"] == 1
    assert histogram["window_timestamps_unproven"] == 1
    assert histogram["up_down_token_identity_unproven"] == 1


def test_valid_market_after_position_200_is_discovered(tmp_path):
    generic = [
        {
            "conditionId": f"0x{i}", "slug": f"generic-{i}",
            "outcomes": ["YES", "NO"], "clobTokenIds": [f"a{i}", f"b{i}"],
            "outcomePrices": ["0.4", "0.6"],
        }
        for i in range(220)
    ]
    gamma = SequenceGamma([generic + [market()]])
    result = discover_markets_v3(config(), 500, gamma, evidence_dir=tmp_path)
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["evidence"]["total_received"] == 221
    assert result["markets"][0]["conditionId"] == "0xbtc"


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
    generic = [{"conditionId": f"0x{i}", "slug": f"generic-{i}"} for i in range(200)]

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        if offset < 200:
            return httpx.Response(200, json=generic[offset:offset + 100])
        return httpx.Response(200, json=[market()])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(config(), 500, client, evidence_dir=tmp_path)
    assert offsets == [0, 100, 200]
    assert [page["offset"] for page in result["evidence"]["pages"]] == offsets
    assert result["status"] == "SELECTED_NONEMPTY"
    assert result["markets"][0]["conditionId"] == "0xbtc"
    assert result["evidence"]["source_exhausted"] is True


def test_full_pages_until_limit_are_truncated(tmp_path):
    calls = []

    def handler(request):
        calls.append(int(request.url.params["offset"]))
        return httpx.Response(200, json=[{"conditionId": f"x{n}"} for n in range(100)])

    client = HttpxGammaDiscoveryClient(page_size=100, transport=httpx.MockTransport(handler))
    result = discover_markets_v3(config(), 2000, client, evidence_dir=tmp_path)
    assert len(calls) == 20
    assert result["status"] == "DISCOVERY_TRUNCATED"
    assert result["discovery_complete"] is False
    assert result["evidence"]["source_exhausted"] is False
    assert result["evidence"]["limit_reached"] is True
    assert result["evidence"]["next_offset"] == 2000


def test_evidence_is_compressed_atomic_and_replay_verified(tmp_path):
    result = discover_markets_v3(config(), 500, SequenceGamma([[market()]]), evidence_dir=tmp_path)
    artifact = tmp_path / result["artifact_path"]
    assert str(artifact).endswith(".json.gz")
    assert not list(tmp_path.glob("*.tmp"))
    evidence = json.loads(gzip.decompress(artifact.read_bytes()))
    assert evidence["raw_gamma"][0]["conditionId"] == "0xbtc"
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
    for index in range(4):
        result = discover_markets_v3(
            config(), 500, SequenceGamma([[market(cid=f"0x{index}")]]),
            evidence_dir=tmp_path, retention_count=2, retention_bytes=1,
        )
    artifacts = list(tmp_path.glob("discovery_*.json.gz"))
    assert len(artifacts) == 1
    assert artifacts[0] == tmp_path / result["artifact_path"]
    assert artifacts[0].with_suffix(".gz.sha256").exists()


def test_v3_dockerfile_packages_discovery_module():
    dockerfile = (__import__("pathlib").Path(__file__).parents[2] / "polymarket" / "Dockerfile.h011-v3").read_text()
    assert "polymarket/discovery_v3.py" in dockerfile


@pytest.mark.parametrize("prices", [
    None, [], ["0.4"], ["0.2", "0.3", "0.5"], ["NaN", "0.5"],
    ["Infinity", "0.5"], ["-0.1", "1.1"], ["1.1", "-0.1"], ["nope", "1.0"],
])
def test_invalid_outcome_prices_are_rejected(tmp_path, prices):
    candidate = market()
    if prices is None:
        candidate.pop("outcomePrices")
    else:
        candidate["outcomePrices"] = prices
    result = discover_markets_v3(config(), 500, SequenceGamma([[candidate]]), evidence_dir=tmp_path)
    assert result["status"] == "EMPTY_SELECTED_COHORT"
    assert result["evidence"]["rejection_histogram"]["invalid_outcome_prices"] == 1


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
