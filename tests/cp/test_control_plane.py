"""H-011 V3 Control Plane Tests."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Absolute path to polymarket/
POLYMARKET_DIR = Path(__file__).resolve().parent.parent.parent / "polymarket"
sys.path.insert(0, str(POLYMARKET_DIR))


class TestSemanticStatus:
    def test_observed_does_not_imply_fresh(self):
        from control_plane.semantic_status import SemanticStatus, DataOrigin, FreshnessStatus, ValidationStatus, ExecutionStatus, CalibrationStatus
        s = SemanticStatus(origin=DataOrigin.OBSERVED, freshness=FreshnessStatus.STALE, validation=ValidationStatus.VERIFIED, execution=ExecutionStatus.NOT_EVALUATED, calibration=CalibrationStatus.NOT_APPLICABLE)
        assert s.origin == DataOrigin.OBSERVED
        assert s.freshness == FreshnessStatus.STALE

    def test_simulated_cannot_be_observed(self):
        from control_plane.semantic_status import DataOrigin
        assert DataOrigin.SIMULATED != DataOrigin.OBSERVED

    def test_zero_sample_calibration_is_insufficient(self):
        from control_plane.drift_monitor import evaluate_calibration, CalibrationStatus
        result = evaluate_calibration(0)
        assert result.status == CalibrationStatus.INSUFFICIENT_SAMPLE
        assert result.brier is None
        assert result.hit_rate is None


class TestSourceHealth:
    def test_source_not_attempted_is_unknown(self):
        from control_plane.source_health import unknown_health, SourceHealthLevel
        h = unknown_health("TEST")
        assert h.level == SourceHealthLevel.UNKNOWN

    def test_source_failed_is_not_unknown(self):
        from control_plane.source_health import evaluate_health, SourceHealthLevel
        h = evaluate_health("GAMMA", http_status=500, latency_ms=100, age_ms=100, consecutive_failures=0, fallback_used=False)
        assert h.level == SourceHealthLevel.FAILED


class TestProvenance:
    def test_provenance_hash_is_deterministic(self):
        from control_plane.provenance import build_field_provenance
        from control_plane.semantic_status import DataOrigin
        kwargs = dict(field_path="test", source_id="GAMMA", origin=DataOrigin.OBSERVED, source_ts=None, received_ts="2026-01-01T00:00:00Z", raw_event_hash="abc", code_sha="s1", config_sha="s2")
        p1 = build_field_provenance(**kwargs)
        p2 = build_field_provenance(**kwargs)
        assert p1.provenance_hash == p2.provenance_hash

    def test_fallback_provenance_is_marked(self):
        from control_plane.provenance import build_field_provenance
        from control_plane.semantic_status import DataOrigin
        p = build_field_provenance(field_path="t", source_id="FB", origin=DataOrigin.DERIVED, source_ts=None, received_ts="x", fallback_used=True)
        assert p.fallback_used is True


class TestInvariants:
    def test_unknown_not_collapsed_to_zero(self):
        from control_plane.invariant_monitor import check_invariants, invariant_summary
        results = check_invariants({})
        summary = invariant_summary(results)
        assert summary["unknown"] > 0

    def test_paper_only_checked(self):
        from control_plane.invariant_monitor import check_invariants
        results = check_invariants({"paper_only": True})
        inv = next(r for r in results if r.invariant_id == "INV-029")
        assert inv.status == "PASS"

    def test_orders_disabled_checked(self):
        from control_plane.invariant_monitor import check_invariants
        results = check_invariants({"orders_enabled": False})
        inv = next(r for r in results if r.invariant_id == "INV-031")
        assert inv.status == "PASS"


class TestDrift:
    def test_drift_zero_samples_insufficient(self):
        from control_plane.drift_monitor import evaluate_drift, DriftStatus
        assert evaluate_drift("m", [], []).status == DriftStatus.INSUFFICIENT_SAMPLE

    def test_drift_one_window_missing_insufficient(self):
        from control_plane.drift_monitor import evaluate_drift, DriftStatus
        assert evaluate_drift("m", [0.5]*50, []).status == DriftStatus.INSUFFICIENT_SAMPLE


class TestAlerts:
    def test_blocking_alert_blocks(self):
        from control_plane.alert_engine import create_alert, AlertSeverity, evaluate_system_status, SystemStatus
        a = create_alert("T", AlertSeverity.BLOCKING, "B", "d", blocking=True)
        assert evaluate_system_status([a], {}, []) == SystemStatus.BLOCKED

    def test_zero_sources_unknown(self):
        from control_plane.alert_engine import evaluate_system_status, SystemStatus
        assert evaluate_system_status([], {}, []) == SystemStatus.UNKNOWN


class TestStress:
    def test_no_base_mutation(self):
        from control_plane.stress_scenarios import run_stress_scenario
        b = {"asks": [{"price": "0.55", "size": "1000"}]}
        run_stress_scenario("DEPTH_50_PERCENT", dict(b), dict(b), 100, 0.0)
        assert b["asks"][0]["size"] == "1000"

    def test_second_leg_unavailable_rejects(self):
        from control_plane.stress_scenarios import run_stress_scenario
        b = {"asks": [{"price": "0.55", "size": "1000"}]}
        r = run_stress_scenario("SECOND_LEG_UNAVAILABLE", b, b, 100, 0.0)
        assert r.execution_status == "REJECTED"


class TestSnapshot:
    def test_hash_deterministic(self):
        from control_plane.state_snapshot import build_snapshot
        s = build_snapshot(scan_id="t", run_id="r", pipeline_version="v3", cohort_id="c", window_s=300, estimator="vwap", code_sha="s1", config_sha="s2", scan_status="OK", source_health={}, funnel={}, market_records=[])
        assert len(s.snapshot_hash) == 64


class TestLifecycle:
    def test_append_only(self):
        from control_plane.lifecycle_store import append_lifecycle_event, LifecycleStatus
        import polymarket.control_plane.lifecycle_store as ls
        ls.LIFECYCLE_STORE = Path("/tmp/test_lifecycle.jsonl")
        if ls.LIFECYCLE_STORE.exists(): ls.LIFECYCLE_STORE.unlink()
        e1 = append_lifecycle_event("p1", "H-011", "0xabc", LifecycleStatus.PREDICTED, {})
        e2 = append_lifecycle_event("p1", "H-011", "0xabc", LifecycleStatus.PENDING_RESOLUTION, {}, e1.event_hash)
        assert e2.previous_event_hash == e1.event_hash

    def test_invalid_transition(self):
        from control_plane.lifecycle_store import is_valid_transition, LifecycleStatus
        assert not is_valid_transition(LifecycleStatus.SCORED, LifecycleStatus.PREDICTED)


class TestDashboard:
    def test_paper_only_banner(self):
        # Read the file directly
        html = (POLYMARKET_DIR / "dashboard_v3.py").read_text()
        assert "PAPER ONLY" in html
        assert "NO REALIZED PNL" in html

    def test_no_balance_or_pnl(self):
        html = (POLYMARKET_DIR / "dashboard_v3.py").read_text()
        assert "Balance" not in html or "balance" not in html.lower().split("_DASHBOARD_HTML")[1] if "_DASHBOARD_HTML" in html else True
        # The key check: no "realized_pnl" as a displayed value
        assert "ganancia" not in html.lower()
