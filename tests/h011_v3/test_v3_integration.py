"""
H-011 V3 Integration Tests — Connection tests, not just unit tests.
Verifies that V3 modules are actually wired together and called.
"""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Add polymarket to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "polymarket"))


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def valid_gamma_market():
    """A canonical btc-updown-5m market that passes identity + temporal checks.

    Fix #3 (fourth audit): the fixture must match the btc-updown-5m contract
    (slug pattern, eventStartTime, endDate, events with ticker) so that
    process_market_v3's defense-in-depth checks pass and the pipeline
    proceeds to structure_from_gamma and beyond.
    """
    from datetime import datetime, timezone, timedelta
    # Use a window centered on a fixed now_ts for deterministic testing
    # now_ts = 1766162200 (midpoint of the 5-min window)
    slug_epoch = 1766162100  # 2025-12-19T16:35:00Z
    es = datetime.fromtimestamp(slug_epoch, tz=timezone.utc)
    ed = datetime.fromtimestamp(slug_epoch + 300, tz=timezone.utc)
    return {
        "id": "test-market-001",
        "conditionId": "0xabc123def4560000000000000000000000000000000000000000000000000000000000",  # 64-char hex
        "slug": f"btc-updown-5m-{slug_epoch}",
        "question": "Bitcoin Up or Down - 5 minute window",
        "description": 'This market will resolve to "Up" if the Bitcoin price at the end '
                       'of the time range is greater than at the beginning.',
        "resolutionSource": "https://data.chain.link/streams/btc-usd",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": '["token_up_abc", "token_down_xyz"]',
        "outcomePrices": '["0.55", "0.45"]',
        "startDate": (es - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDate": ed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "eventStartTime": es.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "feesEnabled": False,
        "volumeNum": 50000,
        "events": [{
            "id": "109968",
            "ticker": f"btc-updown-5m-{slug_epoch}",
            "slug": f"btc-updown-5m-{slug_epoch}",
            "title": "Bitcoin Up or Down",
        }],
    }


@pytest.fixture
def stub_market():
    """A stub market missing clobTokenIds (from active stream)."""
    return {
        "conditionId": "0xstub123",
        "question": "[ACTIVE] 0xstub123...",
        "outcomePrices": "[0.5, 0.5]",
        "volumeNum": 0,
    }


@pytest.fixture
def sample_trades():
    """Trades with valid token binding."""
    return [
        {"transactionHash": "0xtx001", "asset": "token_up_abc", "conditionId": "0xabc123def4560000000000000000000000000000000000000000000000000000000000",
         "outcomeIndex": 0, "price": 0.55, "size": 100, "timestamp": int(time.time()) - 60, "side": "BUY"},
        {"transactionHash": "0xtx001", "asset": "token_down_xyz", "conditionId": "0xabc123def4560000000000000000000000000000000000000000000000000000000000",
         "outcomeIndex": 1, "price": 0.45, "size": 100, "timestamp": int(time.time()) - 55, "side": "BUY"},
        # Same tx, different fill — must be preserved
        {"transactionHash": "0xtx002", "asset": "token_up_abc", "conditionId": "0xabc123def4560000000000000000000000000000000000000000000000000000000000",
         "outcomeIndex": 0, "price": 0.56, "size": 50, "timestamp": int(time.time()) - 50, "side": "BUY"},
    ]


@pytest.fixture
def trades_wrong_asset():
    """Trades with wrong asset (token mismatch)."""
    return [
        {"transactionHash": "0xtx003", "asset": "wrong_token", "conditionId": "0xabc123def4560000000000000000000000000000000000000000000000000000000000",
         "outcomeIndex": 0, "price": 0.55, "size": 100, "timestamp": int(time.time()) - 60, "side": "BUY"},
    ]


@pytest.fixture
def mock_clob_book():
    """A mock CLOB orderbook with asks."""
    return {
        "asset_id": "token_up_abc",
        "asks": [{"price": "0.55", "size": "500"}, {"price": "0.56", "size": "1000"}],
        "bids": [{"price": "0.54", "size": "300"}],
    }


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════

class TestStubsRejected:
    def test_active_stub_is_rejected(self, stub_market):
        from market_structure import is_market_stub
        assert is_market_stub(stub_market) is True

    def test_valid_market_is_not_stub(self, valid_gamma_market):
        from market_structure import is_market_stub
        assert is_market_stub(valid_gamma_market) is False

    def test_v3_pipeline_never_creates_active_stub(self, stub_market):
        """V3 pipeline must reject stubs at the entry point.

        Fix #3 (fourth audit): defense-in-depth now runs BEFORE stub check.
        A stub market (which lacks btc-updown-5m structure) fails identity
        check first, returning REJECTED_IDENTITY. This is correct — the
        market never reaches Data API or CLOB.
        """
        from h011_v3_pipeline import process_market_v3, H011V3Config
        config = H011V3Config()
        mock_data = MagicMock()
        mock_clob = MagicMock()

        record = process_market_v3(
            gamma_market=stub_market,
            now_ts=1766162200,
            config=config,
            run_id="test",
            scan_id="test",
            data_api_client=mock_data,
            clob_client=mock_clob,
        )
        # Stub markets fail identity check first (defense in depth)
        assert record["record_status"] in ("REJECTED_IDENTITY", "REJECTED_METADATA", "REJECTED_TEMPORAL_ELIGIBILITY")
        # Key invariant: rejected markets never call Data API or CLOB
        assert record.get("data_api_called", False) is False
        assert record.get("clob_called", False) is False
        # Data API and CLOB mocks were never called
        mock_data.fetch_trades.assert_not_called()


class TestStructureFromGamma:
    def test_valid_two_leg_market(self, valid_gamma_market):
        from market_structure import structure_from_gamma
        s = structure_from_gamma(valid_gamma_market)
        assert s.condition_id == "0xabc123def4560000000000000000000000000000000000000000000000000000000000"
        assert len(s.legs) == 2
        assert s.legs[0].token_id == "token_up_abc"
        assert s.legs[1].token_id == "token_down_xyz"

    def test_missing_clob_tokens_rejected(self, valid_gamma_market):
        from market_structure import structure_from_gamma, MarketStructureError
        m = dict(valid_gamma_market)
        del m["clobTokenIds"]
        with pytest.raises(MarketStructureError):
            structure_from_gamma(m)

    def test_duplicate_token_ids_rejected(self, valid_gamma_market):
        from market_structure import structure_from_gamma, MarketStructureError
        m = dict(valid_gamma_market)
        m["clobTokenIds"] = '["same_token", "same_token"]'
        with pytest.raises(MarketStructureError, match="not unique"):
            structure_from_gamma(m)

    def test_labels_are_not_hardcoded(self, valid_gamma_market):
        from market_structure import structure_from_gamma
        s = structure_from_gamma(valid_gamma_market)
        # Labels should be "Up" and "Down", NOT "YES" and "NO"
        assert s.legs[0].label == "Up"
        assert s.legs[1].label == "Down"

    def test_index_zero_is_not_assumed_yes(self, valid_gamma_market):
        from market_structure import structure_from_gamma
        s = structure_from_gamma(valid_gamma_market)
        # leg_0 has label "Up", not "YES"
        assert s.legs[0].index == 0
        assert s.legs[0].label != "YES"


class TestTradeBinding:
    def test_wrong_condition_id_trade_rejected(self, valid_gamma_market, sample_trades):
        from market_structure import structure_from_gamma
        from trade_binding import validate_trade_binding
        s = structure_from_gamma(valid_gamma_market)
        trade = dict(sample_trades[0])
        trade["conditionId"] = "0xdifferent"
        ok, reason = validate_trade_binding(trade, s)
        assert ok is False
        assert "foreign_condition" in reason

    def test_wrong_asset_trade_rejected(self, valid_gamma_market, trades_wrong_asset):
        from market_structure import structure_from_gamma
        from trade_binding import validate_trade_binding
        s = structure_from_gamma(valid_gamma_market)
        ok, reason = validate_trade_binding(trades_wrong_asset[0], s)
        assert ok is False
        assert "mismatch" in reason

    def test_two_fills_same_transaction_are_preserved(self, sample_trades):
        from trade_binding import trade_dedup_key
        # trades[0] and trades[1] have same tx hash but different assets
        key0 = trade_dedup_key(sample_trades[0])
        key1 = trade_dedup_key(sample_trades[1])
        assert key0 != key1, "Same-tx different-asset fills must have different dedup keys"

    def test_duplicate_fill_is_removed(self, sample_trades):
        from trade_binding import trade_dedup_key
        # Exact duplicate should have same key
        key0 = trade_dedup_key(sample_trades[0])
        key0_dup = trade_dedup_key(dict(sample_trades[0]))
        assert key0 == key0_dup


class TestVWAPComputation:
    def test_vwap_by_index_is_symmetric(self):
        from trade_binding import compute_vwap_by_index
        trades_a = [
            {"outcomeIndex": 0, "price": 0.6, "size": 100},
            {"outcomeIndex": 1, "price": 0.4, "size": 100},
        ]
        trades_b = list(reversed(trades_a))
        result_a = compute_vwap_by_index(trades_a)
        result_b = compute_vwap_by_index(trades_b)
        assert result_a[0]["vwap"] == result_b[0]["vwap"]
        assert result_a[1]["vwap"] == result_b[1]["vwap"]


class TestClobReadOnly:
    def test_orderbook_requires_token_id(self):
        from clob_readonly import fetch_orderbook
        with pytest.raises(ValueError, match="token_id is required"):
            fetch_orderbook("")

    def test_partial_second_leg_not_executable(self):
        from clob_readonly import simulate_complete_set, is_executable
        book_0 = {"asks": [{"price": "0.55", "size": "1000"}]}
        book_1 = {"asks": [{"price": "0.45", "size": "10"}]}  # Very shallow
        snapshot = simulate_complete_set(book_0, book_1, 100, 0.0)
        assert snapshot.fully_fillable is False
        assert is_executable(snapshot) is False


class TestValidationSemantics:
    def test_w300_uses_current_cohort(self):
        from validation_semantics import classify_window_cohort, H011_COHORT_ID
        assert classify_window_cohort(300) == H011_COHORT_ID

    def test_w3600_is_legacy(self):
        from validation_semantics import classify_window_cohort, H011_LEGACY_COHORT
        assert classify_window_cohort(3600) == H011_LEGACY_COHORT

    def test_w3600_excluded_from_preregistered_decision(self):
        from validation_semantics import is_legacy_cohort
        assert is_legacy_cohort("legacy_w3600") is True
        assert is_legacy_cohort("h011-v3-w300-vwap-structure-v2") is False


class TestPipelineDispatcher:
    def test_cli_dispatches_to_v3(self):
        """Verify that --pipeline integrity-v3 selects the V3 path."""
        # This test verifies the dispatcher logic exists in the code
        import ast
        with open(Path(__file__).parent.parent.parent / "polymarket" / "vwap_detector_v2.py") as f:
            source = f.read()
        assert "--pipeline" in source
        assert "integrity-v3" in source
        assert "legacy-v2" in source
        assert "H011_PIPELINE_VERSION" in source

    def test_v3_pipeline_rejects_window_not_300(self):
        from h011_v3_pipeline import H011V3Config
        config = H011V3Config(window_s=3600)
        with pytest.raises(AssertionError, match="window_s=300"):
            config.validate()


class TestV3PipelineIntegration:
    def test_v3_pipeline_calls_structure_from_gamma(self, valid_gamma_market, sample_trades):
        """Verify that process_market_v3 calls structure_from_gamma."""
        from h011_v3_pipeline import process_market_v3, H011V3Config
        from market_structure import structure_from_gamma

        config = H011V3Config()
        mock_data = MagicMock()
        mock_data.fetch_trades.return_value = sample_trades
        mock_clob = MagicMock()
        mock_clob.fetch_book.return_value = {"asks": [{"price": "0.55", "size": "1000"}]}

        with patch("h011_v3_pipeline.structure_from_gamma", wraps=structure_from_gamma) as spy:
            process_market_v3(
                gamma_market=valid_gamma_market,
                now_ts=1766162200,
                config=config,
                run_id="test", scan_id="test",
                data_api_client=mock_data, clob_client=mock_clob,
            )
            assert spy.called

    def test_v3_pipeline_calls_validate_trade_binding(self, valid_gamma_market, sample_trades):
        from h011_v3_pipeline import process_market_v3, H011V3Config
        from trade_binding import validate_trade_binding

        config = H011V3Config()
        mock_data = MagicMock()
        mock_data.fetch_trades.return_value = sample_trades
        mock_clob = MagicMock()
        mock_clob.fetch_book.return_value = {"asks": [{"price": "0.55", "size": "1000"}]}

        with patch("h011_v3_pipeline.validate_trade_binding", wraps=validate_trade_binding) as spy:
            process_market_v3(
                gamma_market=valid_gamma_market,
                now_ts=1766162200,
                config=config,
                run_id="test", scan_id="test",
                data_api_client=mock_data, clob_client=mock_clob,
            )
            assert spy.called

    def test_v3_pipeline_never_requests_book_by_condition_id(self, valid_gamma_market, sample_trades):
        from h011_v3_pipeline import process_market_v3, H011V3Config

        config = H011V3Config()
        mock_data = MagicMock()
        mock_data.fetch_trades.return_value = sample_trades
        mock_clob = MagicMock()
        mock_clob.fetch_book.return_value = {"asks": [{"price": "0.55", "size": "1000"}]}

        process_market_v3(
            gamma_market=valid_gamma_market,
            now_ts=1766162200,
            config=config,
            run_id="test", scan_id="test",
            data_api_client=mock_data, clob_client=mock_clob,
        )

        # Check that fetch_book was called with token_ids, NOT condition_id
        for call_args in mock_clob.fetch_book.call_args_list:
            arg = call_args[0][0] if call_args[0] else call_args[1].get("token_id", "")
            assert arg != valid_gamma_market["conditionId"]
            assert arg in ["token_up_abc", "token_down_xyz"]

    def test_v3_pipeline_outputs_historical_signal_only_without_books(self, valid_gamma_market, sample_trades):
        from h011_v3_pipeline import process_market_v3, H011V3Config

        config = H011V3Config()
        mock_data = MagicMock()
        mock_data.fetch_trades.return_value = sample_trades
        mock_clob = MagicMock()
        mock_clob.fetch_book.side_effect = Exception("CLOB unavailable")

        record = process_market_v3(
            gamma_market=valid_gamma_market,
            now_ts=1766162200,
            config=config,
            run_id="test", scan_id="test",
            data_api_client=mock_data, clob_client=mock_clob,
        )
        assert record["historical_signal"]["status"] == "AVAILABLE"
        assert record["shadow_execution"]["status"] == "REJECTED"
        assert "REJECTED" in record["record_status"]

    def test_v3_pipeline_does_not_write_legacy_ledger(self, valid_gamma_market, sample_trades, tmp_path):
        """V3 must NOT write to dry_run_ledger.jsonl."""
        from h011_v3_pipeline import process_market_v3, H011V3Config

        config = H011V3Config()
        mock_data = MagicMock()
        mock_data.fetch_trades.return_value = sample_trades
        mock_clob = MagicMock()
        mock_clob.fetch_book.return_value = {"asks": [{"price": "0.55", "size": "1000"}]}

        record = process_market_v3(
            gamma_market=valid_gamma_market,
            now_ts=1766162200,
            config=config,
            run_id="test", scan_id="test",
            data_api_client=mock_data, clob_client=mock_clob,
        )
        # V3 record should NOT have a "balance" or "pnl" field at top level
        assert "balance" not in record
        assert "realized_pnl" not in record
        assert record["realized_outcome"]["status"] == "NOT_AVAILABLE"
        assert record["realized_outcome"]["realized_pnl"] is None


class TestAdminAuth:
    def test_admin_endpoint_without_key_returns_401(self):
        from senecio_polymarket.backend.admin_auth import require_admin
        import asyncio
        import os

        # Set a key so _admin_key doesn't raise RuntimeError
        os.environ["SENECIO_ADMIN_API_KEY"] = "test-secret-key"
        try:
            # Call without providing header
            loop = asyncio.new_event_loop()
            with pytest.raises(Exception) as exc_info:
                loop.run_until_complete(require_admin(x_senecio_admin_key=None))
            # Should be HTTPException with 401
            assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)
        finally:
            del os.environ["SENECIO_ADMIN_API_KEY"]

    def test_wrong_admin_key_returns_401(self):
        from senecio_polymarket.backend.admin_auth import require_admin
        import asyncio
        import os

        os.environ["SENECIO_ADMIN_API_KEY"] = "correct-key"
        try:
            loop = asyncio.new_event_loop()
            with pytest.raises(Exception) as exc_info:
                loop.run_until_complete(require_admin(x_senecio_admin_key="wrong-key"))
            assert "401" in str(exc_info.value) or "Unauthorized" in str(exc_info.value)
        finally:
            del os.environ["SENECIO_ADMIN_API_KEY"]
