"""Raw capture manifest and transform-reexecuting H-011 replay."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

TRANSFORM_VERSION = "h011-v3-transform-v2"
EPHEMERAL_RECORD_KEYS = {"run_id", "scan_id"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def config_sha(config: dict[str, Any]) -> str:
    return sha256(canonical_bytes(config))


def capture_status(value: Any, present: bool) -> str:
    if not present:
        return "NOT_ATTEMPTED"
    if value is None:
        return "CAPTURE_FAILED"
    return "CAPTURED_EMPTY" if value in ({}, []) else "CAPTURED_NONEMPTY"


def canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    """Remove execution/persistence identity while retaining the decision."""
    result = json.loads(json.dumps(record))
    for key in EPHEMERAL_RECORD_KEYS:
        result.pop(key, None)
    result.pop("_raw_bundle", None)
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        evidence.pop("record_hash", None)
    liquidity = result.get("quoted_liquidity")
    if isinstance(liquidity, dict):
        liquidity.pop("leg_0_received_ts", None)
        liquidity.pop("leg_1_received_ts", None)
        liquidity.pop("snapshot_delta_ms", None)
    return result


def _status_manifest(gamma: list[dict], trades: dict[str, Any],
                     books: dict[str, Any], fees: dict[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    for market in gamma:
        cid = str(market.get("conditionId") or market.get("condition_id") or "")
        market_books = books.get(cid) if cid in books else None
        manifest[cid] = {
            "gamma": capture_status(market, True),
            "trades": capture_status(trades.get(cid), cid in trades),
            "book_leg_0": capture_status(
                market_books.get("leg_0") if isinstance(market_books, dict) else None,
                isinstance(market_books, dict) and "leg_0" in market_books,
            ),
            "book_leg_1": capture_status(
                market_books.get("leg_1") if isinstance(market_books, dict) else None,
                isinstance(market_books, dict) and "leg_1" in market_books,
            ),
            "fees": capture_status(fees.get(cid), cid in fees),
        }
    return manifest


def raw_complete(bundle: dict[str, Any]) -> bool:
    if not isinstance(bundle.get("config"), dict) or not bundle["config"]:
        return False
    if not bundle.get("code_sha") or bundle.get("code_sha") == "unknown":
        return False
    gamma = bundle.get("gamma")
    if not isinstance(gamma, list) or not gamma:
        return False
    allowed = {"CAPTURED_EMPTY", "CAPTURED_NONEMPTY"}
    statuses = bundle.get("capture_status")
    if not isinstance(statuses, dict):
        return False
    for market in gamma:
        cid = str(market.get("conditionId") or market.get("condition_id") or "")
        state = statuses.get(cid, {})
        if not cid or any(state.get(key) not in allowed for key in (
            "gamma", "trades", "book_leg_0", "book_leg_1", "fees"
        )):
            return False
    return True


def semantic_material(bundle: dict[str, Any], records: list[dict] | None = None) -> dict[str, Any]:
    """Decision material; deliberately independent of scan/run/write identity."""
    return {
        "schema_version": bundle["schema_version"],
        "transform_version": bundle["transform_version"],
        "code_sha": bundle["code_sha"],
        "config_sha": bundle["config_sha"],
        "cohort_identity": bundle["cohort_identity"],
        "config": bundle["config"],
        "gamma": bundle["gamma"],
        "trades": bundle["trades"],
        "books": bundle["books"],
        "fees": bundle["fees"],
        "capture_status": bundle["capture_status"],
        "records": [canonical_record(record) for record in (records if records is not None else bundle["records"])],
    }


def semantic_hash(bundle: dict[str, Any], records: list[dict] | None = None) -> str:
    return sha256(canonical_bytes(semantic_material(bundle, records)))


def write_bundle(path: Path, *, scan_id: str, code_sha: str, config: dict[str, Any],
                 gamma: list[dict], trades: dict[str, list[dict]],
                 books: dict[str, dict], fees: dict[str, Any],
                 records: list[dict], run_id: str | None = None,
                 cohort_identity: str = "h011-v3-btc-5m-15m",
                 window_end_ts: int | None = None) -> dict[str, Any]:
    normalized_config = json.loads(json.dumps(config, sort_keys=True, separators=(",", ":")))
    bundle = {
        "schema_version": "h011-v3-raw-bundle-v2",
        "transform_version": TRANSFORM_VERSION,
        "scan_id": scan_id,
        "run_id": run_id or scan_id,
        "window_end_ts": window_end_ts,
        "code_sha": code_sha,
        "config_sha": config_sha(normalized_config),
        "cohort_identity": cohort_identity,
        "config": normalized_config,
        "gamma": gamma,
        "trades": trades,
        "books": books,
        "fees": fees,
        "capture_status": _status_manifest(gamma, trades, books, fees),
        "records": records,
    }
    bundle["semantic_hash"] = semantic_hash(bundle)
    bundle["canonical_content_hash"] = sha256(canonical_bytes(bundle))
    path.parent.mkdir(parents=True, exist_ok=True)
    final_bytes = canonical_bytes(bundle)
    path.write_bytes(final_bytes)
    file_sha = sha256(final_bytes)
    path.with_suffix(path.suffix + ".sha256").write_text(file_sha + "\n", encoding="ascii")
    return {**bundle, "file_sha256": file_sha}


class _ReplayDataClient:
    def __init__(self, trades: dict[str, list[dict]]):
        self.trades = trades

    def fetch_trades(self, condition_id: str, window_start: int, now: int) -> list[dict]:
        return json.loads(json.dumps(self.trades[condition_id]))


class _ReplayBookClient:
    def __init__(self, books: dict[str, dict], gamma: list[dict]):
        self.by_token: dict[str, dict] = {}
        for market in gamma:
            cid = str(market.get("conditionId") or market.get("condition_id") or "")
            tokens = market.get("clobTokenIds", [])
            tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
            if len(tokens) == 2 and cid in books:
                self.by_token[str(tokens[0])] = books[cid]["leg_0"]
                self.by_token[str(tokens[1])] = books[cid]["leg_1"]

    def fetch_book(self, token_id: str) -> dict:
        return json.loads(json.dumps(self.by_token[token_id]))


def _reexecute(bundle: dict[str, Any]) -> list[dict]:
    from h011_v3_pipeline import H011V3Config, process_market_v3

    allowed = set(H011V3Config.__dataclass_fields__)
    config = H011V3Config(**{k: v for k, v in bundle["config"].items() if k in allowed})
    data_client = _ReplayDataClient(bundle["trades"])
    book_client = _ReplayBookClient(bundle["books"], bundle["gamma"])
    now_ts = bundle.get("window_end_ts")
    if now_ts is None:
        timestamps = [
            int(trade.get("timestamp", 0))
            for trades in bundle["trades"].values() for trade in trades
            if isinstance(trade.get("timestamp"), (int, float))
        ]
        now_ts = max(timestamps, default=0) + 1
    records = []
    with tempfile.TemporaryDirectory():
        for market in bundle["gamma"]:
            market = json.loads(json.dumps(market))
            cid = str(market.get("conditionId") or market.get("condition_id") or "")
            fee_capture = bundle["fees"][cid]
            if isinstance(fee_capture, dict):
                if "feesEnabled" in fee_capture:
                    market["feesEnabled"] = fee_capture["feesEnabled"]
                if "takerBaseFee" in fee_capture:
                    market["takerBaseFee"] = fee_capture["takerBaseFee"]
            records.append(process_market_v3(
                gamma_market=market, now_ts=int(now_ts), config=config,
                run_id="REPLAY", scan_id="REPLAY",
                data_api_client=data_client, clob_client=book_client,
                persist_raw=False,
            ))
    return [{k: v for k, v in record.items() if k != "_raw_bundle"} for record in records]


def replay_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_bytes())
    complete = raw_complete(bundle)
    replayed_records: list[dict] = []
    transform_reexecuted = False
    error = None
    if complete:
        try:
            replayed_records = _reexecute(bundle)
            transform_reexecuted = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
    original_records = [canonical_record(record) for record in bundle.get("records", [])]
    replayed_canonical = [canonical_record(record) for record in replayed_records]
    records_match = transform_reexecuted and original_records == replayed_canonical
    original_hash = bundle.get("semantic_hash")
    replayed_hash = semantic_hash(bundle, replayed_records) if transform_reexecuted else None
    semantic_matches = bool(replayed_hash and original_hash == replayed_hash)
    config_matches = config_sha(bundle.get("config", {})) == bundle.get("config_sha")
    file_sha = sha256(path.read_bytes())
    sidecar = path.with_suffix(path.suffix + ".sha256")
    file_matches = sidecar.exists() and sidecar.read_text(encoding="ascii").strip() == file_sha
    verified = all((transform_reexecuted, records_match, semantic_matches, config_matches, complete))
    return {
        "scan_id": bundle.get("scan_id"),
        "transform_reexecuted": transform_reexecuted,
        "records_match": records_match,
        "original_semantic_hash": original_hash,
        "replayed_semantic_hash": replayed_hash,
        "semantic_hash_matches": semantic_matches,
        "config_sha_matches": config_matches,
        "raw_complete": complete,
        "file_sha256": file_sha,
        "file_sha256_matches": file_matches,
        "replay_verified": verified,
        "records": len(bundle.get("records", [])),
        "error": error,
    }
