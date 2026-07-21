from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from research.tradingview_bridge.adapter import (
    BridgeSecurityError,
    BridgeValidationError,
    associate_research_context,
    compute_window_context,
    payload_sha256,
    safe_import_context,
    validate_envelope,
    validate_output_path,
    validate_tool_name,
)
from research.tradingview_bridge.provenance import (
    UPSTREAM_COMMIT,
    UPSTREAM_LICENSE,
    UPSTREAM_REPOSITORY,
    build_provenance,
)

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "valid_ohlcv.json"
NOW = datetime(2026, 7, 21, 12, 6, tzinfo=timezone.utc)


def load_valid() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def rehash(envelope: dict) -> dict:
    envelope["payload_sha256"] = payload_sha256(envelope["payload"])
    return envelope


def test_schema_document_is_valid_json_and_non_authoritative():
    schema = json.loads((HERE.parent / "schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["authoritative"]["const"] is False
    assert schema["properties"]["schema_version"]["const"] == "senex-tradingview-context-v1"
    assert schema["additionalProperties"] is False


def test_valid_envelope_and_window_metrics():
    result = validate_envelope(
        load_valid(),
        expected_symbol="BINANCE:BTCUSDT",
        expected_timeframe="5",
        expected_window_start="2026-07-21T12:00:00Z",
        expected_window_end="2026-07-21T12:05:00Z",
        now=NOW,
    )
    assert result.accepted is True
    assert result.warnings == ()
    metrics = compute_window_context(
        result,
        market_window_start="2026-07-21T12:00:00Z",
        market_window_end="2026-07-21T12:05:00Z",
    )
    assert metrics["authoritative"] is False
    assert metrics["bar_count"] == 2
    assert metrics["ohlc"] == {
        "open": 100000.0,
        "high": 100200.0,
        "low": 99950.0,
        "close": 100150.0,
    }
    assert metrics["range"] == 250.0
    assert metrics["volume"] == 12.5
    assert metrics["return"] == pytest.approx(0.0015)
    assert metrics["maximum_bar_movement"] > 0


def test_authoritative_true_rejected():
    envelope = load_valid()
    envelope["authoritative"] = True
    with pytest.raises(BridgeSecurityError, match="authoritative"):
        validate_envelope(envelope, now=NOW)


def test_invalid_hash_rejected():
    envelope = load_valid()
    envelope["payload_sha256"] = "0" * 64
    with pytest.raises(BridgeValidationError, match="payload_sha256 mismatch"):
        validate_envelope(envelope, now=NOW)


@pytest.mark.parametrize("field", ["symbol", "timeframe"])
def test_missing_identity_field_rejected(field):
    envelope = load_valid()
    envelope.pop(field)
    with pytest.raises(BridgeValidationError, match="missing fields"):
        validate_envelope(envelope, now=NOW)


def test_stale_capture_flagged_and_not_auto_accepted():
    envelope = load_valid()
    envelope["captured_at"] = "2026-07-20T12:00:00Z"
    result = validate_envelope(envelope, now=NOW, stale_after_seconds=900)
    assert result.stale is True
    assert result.accepted is False
    assert "stale_capture" in result.warnings


def test_symbol_mismatch_flagged():
    result = validate_envelope(load_valid(), expected_symbol="COINBASE:BTCUSD", now=NOW)
    assert result.symbol_mismatch is True
    assert result.accepted is False
    assert "symbol_mismatch" in result.warnings


def test_timeframe_mismatch_flagged():
    result = validate_envelope(load_valid(), expected_timeframe="1", now=NOW)
    assert result.timeframe_mismatch is True
    assert result.accepted is False
    assert "timeframe_mismatch" in result.warnings


def test_timestamp_mismatch_flagged():
    result = validate_envelope(
        load_valid(),
        expected_window_start="2026-07-21T13:00:00Z",
        expected_window_end="2026-07-21T13:05:00Z",
        now=NOW,
    )
    assert result.timestamp_mismatch is True
    assert result.accepted is False


def test_malformed_ohlcv_rejected():
    envelope = load_valid()
    envelope["payload"]["bars"][0]["high"] = 90000.0
    rehash(envelope)
    with pytest.raises(BridgeValidationError, match="high is inconsistent"):
        validate_envelope(envelope, now=NOW)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinity_rejected(bad):
    envelope = load_valid()
    envelope["payload"]["bars"][0]["close"] = bad
    with pytest.raises(BridgeValidationError, match="NaN or Infinity"):
        payload_sha256(envelope["payload"])


def test_zero_values_preserved():
    result = validate_envelope(load_valid(), now=NOW)
    assert result.envelope["payload"]["bars"][1]["volume"] == 0.0


def test_unknown_values_preserved_for_non_ohlcv_payload():
    envelope = load_valid()
    envelope["capture_type"] = "quote"
    envelope["payload"] = {"last": None, "market_state": "unknown", "change": 0}
    rehash(envelope)
    result = validate_envelope(envelope, now=NOW)
    assert result.envelope["payload"]["last"] is None
    assert result.envelope["payload"]["market_state"] == "unknown"
    assert result.envelope["payload"]["change"] == 0


def test_read_allowlist_accepts_exact_read_tool():
    assert validate_tool_name("data_get_ohlcv") == "data_get_ohlcv"
    assert validate_tool_name("capture_screenshot") == "capture_screenshot"


@pytest.mark.parametrize(
    "tool",
    [
        "ui_eval",
        "ui_click",
        "alert_create",
        "pine_save",
        "watchlist_add",
        "replay_trade",
        "chart_set_symbol",
        "indicator_add",
        "drawing_create",
        "unknown_tool",
    ],
)
def test_mutation_or_unknown_tool_rejected(tool):
    with pytest.raises(BridgeSecurityError):
        validate_tool_name(tool)


def test_raw_chain_and_runtime_paths_rejected(tmp_path):
    for path in (
        tmp_path / "results/h011_v3/raw_chain_v1/capture.json",
        tmp_path / "results/v3/raw/capture.json",
        tmp_path / "results/v3/state/capture.json",
        tmp_path / "results/v3/scans/capture.json",
    ):
        with pytest.raises(BridgeSecurityError):
            validate_output_path(path, repo_root=tmp_path)


def test_safe_research_path_accepted_and_written(tmp_path):
    output = tmp_path / "research/tradingview_context/capture.json"
    record = safe_import_context(
        load_valid(),
        output_path=output,
        repo_root=tmp_path,
        now=NOW,
        expected_symbol="BINANCE:BTCUSDT",
        expected_timeframe="5",
    )
    assert output.exists()
    assert record["classification"]["authoritative"] is False
    assert record["classification"]["raw_chain_input"] is False
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored["provenance"]["upstream_commit_inspected"] == UPSTREAM_COMMIT


def test_provenance_is_complete_and_non_authoritative():
    result = validate_envelope(load_valid(), now=NOW)
    provenance = build_provenance(result.envelope).to_dict()
    assert provenance["upstream_repository"] == UPSTREAM_REPOSITORY
    assert provenance["upstream_commit_inspected"] == UPSTREAM_COMMIT
    assert provenance["upstream_license"] == UPSTREAM_LICENSE
    assert provenance["local_only"] is True
    assert provenance["authoritative"] is False
    assert provenance["production_dependency"] is False
    assert provenance["raw_chain_input"] is False
    assert provenance["resolution_source"] is False


def test_tradingview_context_cannot_modify_authoritative_senex_fields():
    result = validate_envelope(load_valid(), now=NOW)
    original = {
        "record_status": "VALID",
        "invariants": {"pass": 31, "fail": 0, "unknown": 0},
        "scan_status": "COMMITTED",
        "manifest": {"sequence": 7, "manifest_hash": "a" * 64},
        "committed_snapshot": {"snapshot_sha256": "b" * 64},
        "market_identity": {"condition_id": "0xabc"},
        "resolution_outcome": "UNKNOWN",
        "shadow_execution_eligibility": False,
    }
    before = copy.deepcopy(original)
    associated = associate_research_context(
        original,
        result,
        scan_id="scan-1",
        condition_id="0xabc",
    )
    for field in (
        "record_status",
        "invariants",
        "scan_status",
        "manifest",
        "committed_snapshot",
        "market_identity",
        "resolution_outcome",
        "shadow_execution_eligibility",
    ):
        assert associated[field] == before[field]
    assert original == before
    assert associated["research_context"]["tradingview"]["classification"] == (
        "NON_AUTHORITATIVE_RESEARCH_CONTEXT"
    )
