from senecio_polymarket.backend.arbiter_shadow_v3 import arbitrate


def _state(records=None, unknown=0, healthy=True):
    level = "HEALTHY" if healthy else "UNKNOWN"
    return {
        "scan_id": "scan-1", "scan_status": "COMPLETE",
        "market_records": records or [],
        "invariants": {"summary": {"unknown": unknown}},
        "source_health": {"clob": {"level": level}},
    }


def test_real_current_scope_mismatch_fails_closed():
    oracle = {"gate_status": "PASS", "shadow_action": "LONG"}
    state = _state([{"question": "Will France win the World Cup?"}], unknown=31, healthy=False)
    result = arbitrate(oracle, state, [])
    assert result["decision"] == "UNKNOWN"
    assert result["action"] == "FLAT"
    assert "H011_MARKET_SCOPE_MISMATCH_NO_BTC" in result["reasons"]


def test_agreement_can_confirm_only_with_complete_evidence():
    oracle = {"gate_status": "PASS", "shadow_action": "SHORT"}
    record = {"question": "Bitcoin Up or Down 5 minute", "side": "DOWN"}
    result = arbitrate(oracle, _state([record]), [record])
    assert result["decision"] == "CONFIRM"
    assert result["action"] == "SHORT"


def test_disagreement_returns_conflict_and_flat():
    oracle = {"gate_status": "PASS", "shadow_action": "LONG"}
    record = {"question": "BTC Up or Down 5 minute", "side": "DOWN"}
    result = arbitrate(oracle, _state([record]), [record])
    assert result["decision"] == "CONFLICT"
    assert result["action"] == "FLAT"
