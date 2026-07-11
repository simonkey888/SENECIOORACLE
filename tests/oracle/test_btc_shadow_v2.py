from senecio_polymarket.backend.btc_shadow_v2 import evaluate_btc_shadow


def _rows(n, wins, direction="LONG", confidence=0.65):
    return [
        {"prediction": direction, "confidence": confidence, "outcome": "WIN" if i < wins else "LOSS"}
        for i in range(n)
    ]


def test_insufficient_cohort_fails_closed():
    result = evaluate_btc_shadow({"prediction": "LONG", "confidence": 0.65}, _rows(20, 15))
    assert result["gate_status"] == "UNKNOWN"
    assert result["shadow_action"] == "FLAT"


def test_recent_losing_cohort_is_rejected():
    result = evaluate_btc_shadow({"prediction": "SHORT", "confidence": 0.65}, _rows(60, 29, "SHORT"))
    assert result["gate_status"] == "REJECT"
    assert result["shadow_action"] == "FLAT"


def test_strong_recent_cohort_can_confirm_without_orders():
    result = evaluate_btc_shadow({"prediction": "LONG", "confidence": 0.65}, _rows(80, 60))
    assert result["gate_status"] == "PASS"
    assert result["shadow_action"] == "LONG"
    assert result["orders_enabled"] is False
    assert result["live_capital_locked"] is True


def test_flat_source_stays_flat():
    result = evaluate_btc_shadow({"prediction": "FLAT", "confidence": 0.9}, _rows(80, 70))
    assert result["shadow_action"] == "FLAT"
    assert result["gate_status"] == "UNKNOWN"
