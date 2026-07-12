import hashlib
import json

import polymarket.control_plane.state_snapshot as snapshots
import polymarket.h011_v3_pipeline as pipeline
import control_plane.state_snapshot as runtime_snapshots
from polymarket.control_plane.replay import replay_bundle


class DataClient:
    def fetch_trades(self, condition_id, window_start, now):
        return [
            {"conditionId": condition_id, "asset": "token-up", "outcomeIndex": 0,
             "timestamp": now - 10, "price": 0.40, "size": 2},
            {"conditionId": condition_id, "asset": "token-down", "outcomeIndex": 1,
             "timestamp": now - 10, "price": 0.40, "size": 2},
        ]


class BookClient:
    def fetch_book(self, token_id):
        return {"asset_id": token_id, "asks": [{"price": 0.40, "size": 20}]}


def test_run_scan_writes_replayable_bundle_and_snapshot(tmp_path, monkeypatch):
    results = tmp_path / "results" / "v3"
    monkeypatch.setattr(pipeline, "V3_RESULTS_DIR", results)
    monkeypatch.setattr(pipeline, "V3_RAW_DIR", results / "raw")
    monkeypatch.setattr(pipeline, "V3_SCANS_DIR", results / "scans")
    monkeypatch.setattr(pipeline, "V3_REPLAY_DIR", results / "replay")
    monkeypatch.setattr(pipeline, "V3_MASTER_LOG", results / "_master_log_v3.jsonl")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", results / "state")
    monkeypatch.setattr(runtime_snapshots, "SNAPSHOT_DIR", results / "state")
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    deployment_sha = "43fc9f02e60167ae83d6b01d7f0615a4ae5e71b6"
    monkeypatch.setenv("NF_DEPLOYMENT_SHA", deployment_sha)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("SENECIO_CODE_SHA", raising=False)

    market = {
        "conditionId": "0xabc",
        "id": "market-1",
        "question": "Bitcoin Up or Down",
        "slug": "bitcoin-up-or-down-5m",
        "resolutionSource": "Bitcoin price oracle",
        "startDate": "2026-07-11T00:00:00Z",
        "endDate": "2026-07-11T00:05:00Z",
        "outcomes": ["UP", "DOWN"],
        "clobTokenIds": ["token-up", "token-down"],
        "outcomePrices": ["0.40", "0.40"],
        "active": True,
        "closed": False,
        "feesEnabled": False,
    }
    result = pipeline.run_scan_v3(
        markets=[market], now_ts=1000, config=pipeline.H011V3Config(),
        data_api_client=DataClient(), clob_client=BookClient(),
        persist_raw=False,
    )

    summary = result["scan"]
    assert summary["semantic_hash"]
    assert summary["canonical_content_hash"]
    assert summary["file_sha256"]
    assert "artifact_hash" not in summary

    latest = snapshots.SNAPSHOT_DIR / "latest.json"
    state = json.loads(latest.read_text())
    assert state["code_sha"] == deployment_sha
    assert state["config_sha"] != "unknown"
    assert state["config_sha"]
    exact_state_sha = hashlib.sha256(latest.read_bytes()).hexdigest()
    assert (snapshots.SNAPSHOT_DIR / "latest.json.sha256").read_text().strip() == exact_state_sha

    bundle = pipeline.V3_RAW_DIR / summary["raw_bundle"]
    exact_bundle_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert bundle.with_suffix(bundle.suffix + ".sha256").read_text().strip() == exact_bundle_sha
    replay = replay_bundle(bundle)
    assert replay["transform_reexecuted"] is True
    assert replay["records_match"] is True
    assert replay["file_sha256_matches"] is True
    assert replay["replay_verified"] is True
