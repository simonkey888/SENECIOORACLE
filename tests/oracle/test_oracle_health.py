from datetime import datetime, timedelta, timezone

from senecio_polymarket.backend import oracle_runner


def _set_state(**updates):
    original = dict(oracle_runner._state)
    oracle_runner._state.update(updates)
    return original


def test_health_is_starting_during_first_cycle_grace():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    original = _set_state(
        started_at=(now - timedelta(seconds=60)).isoformat(),
        last_cycle_at=None,
        last_prediction_ts=None,
    )
    try:
        result = oracle_runner.get_health_state(now)
        assert result["ok"] is True
        assert result["status"] == "STARTING"
        assert result["orders_enabled"] is False
        assert result["live_capital_locked"] is True
    finally:
        oracle_runner._state.clear()
        oracle_runner._state.update(original)


def test_health_fails_closed_when_cycle_is_stale():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    original = _set_state(
        started_at=(now - timedelta(hours=2)).isoformat(),
        last_cycle_at=(
            now - timedelta(seconds=oracle_runner.HEALTH_MAX_CYCLE_AGE_S + 1)
        ).isoformat(),
        last_prediction_ts=(now - timedelta(hours=1)).isoformat(),
    )
    try:
        result = oracle_runner.get_health_state(now)
        assert result["ok"] is False
        assert result["status"] == "STALE"
    finally:
        oracle_runner._state.clear()
        oracle_runner._state.update(original)


def test_health_accepts_a_current_prediction_cycle():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    original = _set_state(
        started_at=(now - timedelta(hours=1)).isoformat(),
        last_cycle_at=(now - timedelta(minutes=10)).isoformat(),
        last_prediction_ts=(now - timedelta(minutes=9)).isoformat(),
        last_error=None,
    )
    try:
        result = oracle_runner.get_health_state(now)
        assert result["ok"] is True
        assert result["status"] == "HEALTHY"
        assert result["prediction_age_s"] == 540.0
    finally:
        oracle_runner._state.clear()
        oracle_runner._state.update(original)
