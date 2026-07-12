import json
import tempfile
import unittest
from pathlib import Path

from polymarket.control_plane.replay import replay_bundle, write_bundle
from polymarket.control_plane.state_snapshot import build_snapshot
from polymarket.h011_v3_pipeline import (
    H011V3Config,
    select_btc_cohort,
    validate_btc_market_identity,
)


class ReplayContractsTest(unittest.TestCase):
    def setUp(self):
        self.market = {
            "conditionId": "0xabc",
            "slug": "bitcoin-up-or-down-5m",
            "resolutionSource": "Bitcoin price oracle",
            "startDate": "2026-07-11T00:00:00Z",
            "endDate": "2026-07-11T00:05:00Z",
            "outcomes": ["UP", "DOWN"],
            "clobTokenIds": ["token-up", "token-down"],
        }

    def test_structured_btc_identity(self):
        self.assertTrue(validate_btc_market_identity(self.market, 300)[0])
        self.assertEqual(len(select_btc_cohort([self.market])), 1)
        invalid = dict(self.market, endDate="2026-07-11T00:10:00Z")
        self.assertFalse(validate_btc_market_identity(invalid, 300)[0])

    def test_config_and_hashes_are_reproducible(self):
        config = H011V3Config()
        self.assertEqual(len(config.config_sha), 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            write_bundle(
                path, scan_id="scan-1", code_sha="code-1",
                config=config.normalized(), gamma=[self.market],
                trades={"0xabc": []},
                books={"0xabc": {"leg_0": {}, "leg_1": {}}},
                fees={"0xabc": {}}, records=[],
            )
            replay = replay_bundle(path)
            self.assertTrue(replay["semantic_hash_matches"])
            self.assertTrue(replay["artifact_hash_matches"])
            self.assertTrue(replay["config_sha_matches"])
            self.assertTrue(replay["raw_complete"])

    def test_semantic_hash_ignores_write_time(self):
        kwargs = dict(
            scan_id="scan", run_id="run", pipeline_version="v3",
            cohort_id="btc", window_s=300, estimator="vwap",
            code_sha="code", config_sha="config", scan_status="OK",
            source_health={}, funnel={}, market_records=[],
        )
        self.assertEqual(build_snapshot(**kwargs).semantic_hash,
                         build_snapshot(**kwargs).semantic_hash)


if __name__ == "__main__":
    unittest.main()
