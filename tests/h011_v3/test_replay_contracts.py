import hashlib
import json
import tempfile
from pathlib import Path

from polymarket.control_plane.replay import (
    raw_complete,
    replay_bundle,
    semantic_hash,
    write_bundle,
)
from polymarket.control_plane.state_snapshot import build_snapshot, save_snapshot
from polymarket.h011_v3_pipeline import H011V3Config, process_market_v3


class DataClient:
    def __init__(self, trades):
        self.trades = trades

    def fetch_trades(self, condition_id, window_start, now):
        return json.loads(json.dumps(self.trades))


class BookClient:
    def __init__(self, books):
        self.books = books

    def fetch_book(self, token_id):
        return json.loads(json.dumps(self.books[token_id]))


def fixture():
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
    trades = [
        {"conditionId": "0xabc", "asset": "token-up", "outcomeIndex": 0,
         "timestamp": 990, "price": 0.40, "size": 2},
        {"conditionId": "0xabc", "asset": "token-down", "outcomeIndex": 1,
         "timestamp": 990, "price": 0.40, "size": 2},
    ]
    books = {
        "0xabc": {
            "leg_0": {"asset_id": "token-up", "asks": [{"price": 0.40, "size": 20}]},
            "leg_1": {"asset_id": "token-down", "asks": [{"price": 0.40, "size": 20}]},
        }
    }
    fees = {"0xabc": {"feesEnabled": False, "takerBaseFee": None}}
    config = H011V3Config()
    record = process_market_v3(
        gamma_market=market, now_ts=1000, config=config,
        run_id="original-run", scan_id="original-scan",
        data_api_client=DataClient(trades),
        clob_client=BookClient({
            "token-up": books["0xabc"]["leg_0"],
            "token-down": books["0xabc"]["leg_1"],
        }),
        persist_raw=False,
    )
    record.pop("_raw_bundle", None)
    return market, trades, books, fees, config, record


def create_bundle(directory, *, scan_id="scan-a", run_id="run-a",
                  mutate_trades=None, mutate_books=None, records=None):
    market, trades, books, fees, config, record = fixture()
    if mutate_trades:
        mutate_trades(trades)
    if mutate_books:
        mutate_books(books)
    path = Path(directory) / f"{scan_id}.json"
    bundle = write_bundle(
        path, scan_id=scan_id, run_id=run_id, code_sha="abc123",
        config=config.normalized(), gamma=[market],
        trades={"0xabc": trades}, books=books, fees=fees,
        records=records if records is not None else [record],
        window_end_ts=1000,
    )
    return path, bundle


def test_same_raw_different_scan_and_run_id_same_semantic_hash(tmp_path):
    _, first = create_bundle(tmp_path, scan_id="scan-a", run_id="run-a")
    _, second = create_bundle(tmp_path, scan_id="scan-b", run_id="run-b")
    assert first["semantic_hash"] == second["semantic_hash"]


def test_changed_trade_changes_semantic_hash(tmp_path):
    _, first = create_bundle(tmp_path, scan_id="a")
    _, second = create_bundle(tmp_path, scan_id="b", mutate_trades=lambda rows: rows[0].update(price=0.41))
    assert first["semantic_hash"] != second["semantic_hash"]


def test_changed_book_level_changes_semantic_hash(tmp_path):
    _, first = create_bundle(tmp_path, scan_id="a")
    _, second = create_bundle(
        tmp_path, scan_id="b",
        mutate_books=lambda books: books["0xabc"]["leg_0"]["asks"][0].update(price=0.41),
    )
    assert first["semantic_hash"] != second["semantic_hash"]


def test_empty_captured_trades_differs_from_missing(tmp_path):
    market, _, books, fees, config, _ = fixture()
    captured_path = tmp_path / "captured.json"
    captured = write_bundle(
        captured_path, scan_id="a", code_sha="abc123", config=config.normalized(),
        gamma=[market], trades={"0xabc": []}, books=books, fees=fees, records=[],
    )
    missing_path = tmp_path / "missing.json"
    missing = write_bundle(
        missing_path, scan_id="b", code_sha="abc123", config=config.normalized(),
        gamma=[market], trades={}, books=books, fees=fees, records=[],
    )
    assert captured["capture_status"]["0xabc"]["trades"] == "CAPTURED_EMPTY"
    assert missing["capture_status"]["0xabc"]["trades"] == "NOT_ATTEMPTED"
    assert captured["semantic_hash"] != missing["semantic_hash"]


def test_missing_leg_1_book_is_incomplete(tmp_path):
    path, _ = create_bundle(tmp_path)
    bundle = json.loads(path.read_text())
    del bundle["books"]["0xabc"]["leg_1"]
    bundle["capture_status"]["0xabc"]["book_leg_1"] = "NOT_ATTEMPTED"
    assert raw_complete(bundle) is False


def test_replay_reexecutes_transform_and_matches_records(tmp_path):
    path, _ = create_bundle(tmp_path)
    replay = replay_bundle(path)
    assert replay["transform_reexecuted"] is True
    assert replay["records_match"] is True
    assert replay["semantic_hash_matches"] is True
    assert replay["replay_verified"] is True


def test_tampered_stored_record_fails_match(tmp_path):
    _, _, _, _, _, record = fixture()
    record["record_status"] = "TAMPERED"
    path, _ = create_bundle(tmp_path, records=[record])
    replay = replay_bundle(path)
    assert replay["transform_reexecuted"] is True
    assert replay["records_match"] is False
    assert replay["replay_verified"] is False


def test_file_sha256_is_exact_bytes_on_disk(tmp_path):
    path, result = create_bundle(tmp_path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["file_sha256"] == expected
    assert path.with_suffix(".json.sha256").read_text().strip() == expected


def test_snapshot_semantic_hash_ignores_execution_ids_and_has_exact_sidecar(tmp_path, monkeypatch):
    import polymarket.control_plane.state_snapshot as snapshots

    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path)
    kwargs = dict(
        pipeline_version="v3", cohort_id="btc", window_s=300,
        estimator="vwap", code_sha="code", config_sha="config",
        scan_status="OK", source_health={}, funnel={},
    )
    first = build_snapshot(
        scan_id="scan-a", run_id="run-a",
        market_records=[{"condition_id": "x", "record_hash": "execution-a"}],
        **kwargs,
    )
    second = build_snapshot(
        scan_id="scan-b", run_id="run-b",
        market_records=[{"condition_id": "x", "record_hash": "execution-b"}],
        **kwargs,
    )
    assert first.semantic_hash == second.semantic_hash
    path = save_snapshot(first)
    exact = hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.with_suffix(path.suffix + ".sha256").read_text().strip() == exact
