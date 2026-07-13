"""Tests for H-011 V3 market structure — Fix #2 (mutable prices separated).

Verifies that:
  - structure_from_gamma accepts outcomePrices=None
  - same market with different prices has same metadata_hash
  - different tokens/outcomes change the hash
  - missing tokens is still a stub
  - missing prices is NOT a stub
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

from market_structure import structure_from_gamma, is_market_stub, MarketStructureError


def _base_market():
    """A canonical market without outcomePrices."""
    return {
        "conditionId": "0x" + "ab" * 32,
        "id": "12345",
        "outcomes": ["Up", "Down"],
        "clobTokenIds": ["token-up-synthetic-aaa", "token-down-synthetic-bbb"],
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "feesEnabled": True,
        # Note: NO outcomePrices
    }


def test_structure_from_gamma_accepts_none_outcome_prices():
    """Fix #2: outcomePrices=None must NOT raise MarketStructureError."""
    market = _base_market()
    market["outcomePrices"] = None
    structure = structure_from_gamma(market)
    assert structure.condition_id == "0x" + "ab" * 32
    assert len(structure.legs) == 2
    assert structure.legs[0].label == "Up"
    assert structure.legs[1].label == "Down"


def test_structure_from_gamma_accepts_missing_outcome_prices():
    """Fix #2: missing outcomePrices key must NOT raise."""
    market = _base_market()
    # outcomePrices key not present at all
    structure = structure_from_gamma(market)
    assert structure.condition_id == "0x" + "ab" * 32


def test_structure_from_gamma_accepts_empty_outcome_prices():
    """Fix #2: empty outcomePrices must NOT raise."""
    market = _base_market()
    market["outcomePrices"] = []
    structure = structure_from_gamma(market)
    assert structure.condition_id == "0x" + "ab" * 32


def test_same_market_different_prices_same_metadata_hash():
    """Fix #2: two markets with same identity but different prices MUST have
    the same metadata_hash (prices are mutable state, not identity)."""
    market_a = _base_market()
    market_a["outcomePrices"] = ["0.4", "0.6"]

    market_b = _base_market()
    market_b["outcomePrices"] = ["0.5", "0.5"]  # different prices

    structure_a = structure_from_gamma(market_a)
    structure_b = structure_from_gamma(market_b)

    assert structure_a.metadata_hash == structure_b.metadata_hash, (
        "Markets with same identity but different prices must have the same "
        "metadata_hash. Prices are mutable state."
    )


def test_different_tokens_change_metadata_hash():
    """Different clobTokenIds must change the metadata_hash."""
    market_a = _base_market()
    market_a["clobTokenIds"] = ["token-up-aaa", "token-down-bbb"]

    market_b = _base_market()
    market_b["clobTokenIds"] = ["token-up-xxx", "token-down-yyy"]

    structure_a = structure_from_gamma(market_a)
    structure_b = structure_from_gamma(market_b)

    assert structure_a.metadata_hash != structure_b.metadata_hash


def test_different_outcomes_change_metadata_hash():
    """Different outcomes must change the metadata_hash."""
    market_a = _base_market()
    market_a["outcomes"] = ["Up", "Down"]

    market_b = _base_market()
    market_b["outcomes"] = ["Down", "Up"]  # swapped

    structure_a = structure_from_gamma(market_a)
    structure_b = structure_from_gamma(market_b)

    assert structure_a.metadata_hash != structure_b.metadata_hash


def test_missing_tokens_is_stub():
    """Fix #2: missing clobTokenIds is still a stub."""
    market = _base_market()
    market.pop("clobTokenIds")
    assert is_market_stub(market) is True


def test_missing_outcomes_is_stub():
    """Fix #2: missing outcomes is still a stub."""
    market = _base_market()
    market.pop("outcomes")
    assert is_market_stub(market) is True


def test_missing_condition_id_is_stub():
    """Fix #2: missing conditionId is a stub."""
    market = _base_market()
    market.pop("conditionId")
    assert is_market_stub(market) is True


def test_missing_prices_is_not_stub():
    """Fix #2: missing outcomePrices is NOT a stub (prices are mutable state)."""
    market = _base_market()
    # No outcomePrices key at all
    assert is_market_stub(market) is False


def test_none_prices_is_not_stub():
    """Fix #2: outcomePrices=None is NOT a stub."""
    market = _base_market()
    market["outcomePrices"] = None
    assert is_market_stub(market) is False


def test_structure_from_gamma_still_rejects_missing_condition_id():
    """Sanity: missing conditionId still raises."""
    market = _base_market()
    market.pop("conditionId")
    with pytest.raises(MarketStructureError, match="missing conditionId"):
        structure_from_gamma(market)


def test_structure_from_gamma_still_rejects_wrong_outcome_count():
    """Sanity: 3 outcomes still raises."""
    market = _base_market()
    market["outcomes"] = ["Up", "Down", "Flat"]
    market["clobTokenIds"] = ["t1", "t2", "t3"]
    with pytest.raises(MarketStructureError, match="expected 2 outcomes"):
        structure_from_gamma(market)


def test_structure_from_gamma_still_rejects_duplicate_tokens():
    """Sanity: duplicate token IDs still raises."""
    market = _base_market()
    market["clobTokenIds"] = ["same-token", "same-token"]
    with pytest.raises(MarketStructureError, match="not unique"):
        structure_from_gamma(market)
