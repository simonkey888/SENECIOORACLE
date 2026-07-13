import hashlib
from types import SimpleNamespace

from polymarket.discovery_v3 import (
    discover_markets_v3,
    monitor_discovery_loop,
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
        return value, [{"offset": 0, "limit": limit, "count": len(value)}]


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
    invalid = {
        "slug": "ethereum-market",
        "startDate": None,
        "endDate": None,
        "outcomes": ["YES", "NO"],
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
