"""Phase I tests for h011_v3_raw_transaction core primitives.

Covers all required test scenarios from the Phase I brief plus a small
number of additional tests for edge cases that are too important to skip.

Tests are deterministic, use tmp_path, and have no network or credential
dependencies.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

import h011_v3_raw_transaction as rt
from h011_v3_raw_transaction import (
    CandidateManifestMismatchError,
    DiagnosticEvidence,
    EligibilityCorruptionError,
    EligibilityMonotonicityError,
    EligibilityState,
    GuardValidationError,
    IdentityCollisionError,
    LockAcquisitionError,
    MarkerIntegrityError,
    MarkerValidationError,
    NestedLockingError,
    PathSafetyError,
    PublishResult,
    RawArtifactTransactionError,
    RawArtifactTransfer,
    RawChainLock,
    RawChainLockGuard,
    RawEventPersistenceError,
    RawScanStager,
    RawTransactionError,
    SealedRawArtifact,
    StagerStateError,
    canonical_events_sha256,
    canonical_json_bytes,
    canonical_manifest_file_bytes,
    canonical_payload_sha256,
    compute_diagnostic_integrity_sha256,
    compute_eligibility_integrity_sha256,
    compute_manifest_hash,
    compute_marker_integrity_sha256,
    create_marker_no_replace,
    load_raw_events_strict,
    marker_filename,
    parse_marker,
    read_eligibility_state,
    update_existing_marker_atomic,
    validate_bare_filename,
    validate_candidate_manifest_exact,
    validate_marker,
    write_eligibility_state,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures and helpers
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    return d


def _make_event(cid: str = "0xabc", trades: list[dict] | None = None) -> dict[str, Any]:
    payload = trades if trades is not None else [{"price": 0.5, "size": 1}]
    payload_sha = canonical_payload_sha256(payload)
    return {
        "received_at_utc": "2026-07-13T10:00:00Z",
        "source": "polymarket_data_api",
        "endpoint": "/trades",
        "request_params": {"market": cid},
        "requested_condition_id": cid,
        "payload": payload,
        "payload_sha256": payload_sha,
        "cohort_id": "300s",
        "schema_version": "raw_trade_event_v1",
    }


def _make_candidate_manifest(
    *,
    sequence: int = 0,
    previous_manifest_hash: str | None = None,
    run_id: str = "r1",
    scan_id: str = "s1",
    final_name: str = "raw_scan_s1_abcdef012345.events.jsonl.gz",
    file_sha256: str = hashlib.sha256(b"test").hexdigest(),
    canonical_events_sha256: str = hashlib.sha256(b"events").hexdigest(),
    event_count: int = 1,
    condition_ids: list[str] | None = None,
    manifest_hash: str | None = None,
) -> dict[str, Any]:
    """Build a candidate_manifest dict with a correct manifest_hash."""
    entry: dict[str, Any] = {
        "sequence": sequence,
        "run_id": run_id,
        "scan_id": scan_id,
        "filename": final_name,
        "file_sha256": file_sha256,
        "canonical_events_sha256": canonical_events_sha256,
        "event_count": event_count,
        "condition_ids": condition_ids if condition_ids is not None else ["0xabc"],
        "previous_manifest_hash": previous_manifest_hash,
    }
    entry["manifest_hash"] = manifest_hash if manifest_hash else compute_manifest_hash(entry)
    return entry


def _make_marker_body(
    *,
    candidate_manifest: dict[str, Any] | None = None,
    status: str = "STAGED",
    resolution: str = "ACTIVE",
    sequence: int = 0,
    transaction_uuid: str | None = None,
    ownership_token: str | None = None,
    recoverable: bool = True,
) -> dict[str, Any]:
    """Build a complete marker body with all required fields and a correct
    marker_integrity_sha256."""
    import uuid as _uuid
    cm = candidate_manifest if candidate_manifest is not None else _make_candidate_manifest()
    canonical_cm_bytes = canonical_manifest_file_bytes(cm)
    b64 = base64.b64encode(canonical_cm_bytes).decode("ascii")
    cm_sha = hashlib.sha256(canonical_cm_bytes).hexdigest()
    body: dict[str, Any] = {
        "transaction_version": "h011-artifact-txn-v2",
        "transaction_uuid": transaction_uuid or str(_uuid.uuid4()),
        "ownership_token": ownership_token or str(_uuid.uuid4()),
        "status": status,
        "resolution": resolution,
        "sequence": sequence,
        "run_id": "r1",
        "scan_id": "s1",
        "staging_filename": "raw_scan_s1_abc123.jsonl.gz.tmp",
        "final_name": "raw_scan_s1_abcdef012345.events.jsonl.gz",
        "sidecar_name": "raw_scan_s1_abcdef012345.events.jsonl.gz.sha256",
        "manifest_name": f"manifest_{sequence:06d}.json",
        "device_id": 0,
        "inode": 0,
        "size_bytes": 100,
        "file_sha256": hashlib.sha256(b"test").hexdigest(),
        "canonical_events_sha256": hashlib.sha256(b"events").hexdigest(),
        "event_count": 1,
        "condition_ids": ["0xabc"],
        "previous_manifest_hash": None,
        "candidate_manifest": cm,
        "candidate_manifest_bytes_base64": b64,
        "candidate_manifest_bytes_sha256": cm_sha,
        "manifest_created_at": "2026-07-13T10:00:00Z",
        "failure_stage": None,
        "failure_type": None,
        "failure_message": None,
        "recoverable": recoverable,
    }
    return body


# ═══════════════════════════════════════════════════════════════════════
# Section 1 — Canonicalization
# ═══════════════════════════════════════════════════════════════════════

def test_canonical_payload_deterministic():
    """Two calls with the same input must produce identical hashes."""
    payload = {"b": 2, "a": 1, "c": [3, 2, 1]}
    h1 = canonical_payload_sha256(payload)
    h2 = canonical_payload_sha256(payload)
    assert h1 == h2
    assert len(h1) == 64
    # All lowercase hex
    assert all(c in "0123456789abcdef" for c in h1)


def test_canonical_payload_preserves_list_order():
    """List order must be preserved (different order → different hash)."""
    payload_a = {"items": [1, 2, 3]}
    payload_b = {"items": [3, 2, 1]}
    ha = canonical_payload_sha256(payload_a)
    hb = canonical_payload_sha256(payload_b)
    assert ha != hb, "list order must affect canonical hash"


def test_canonical_payload_rejects_nan():
    """NaN must be rejected (allow_nan=False)."""
    import math
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_payload_sha256({"x": math.nan})


def test_canonical_payload_rejects_infinity():
    """Infinity must be rejected."""
    import math
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_payload_sha256({"x": math.inf})


def test_canonical_json_bytes_is_sorted_keys():
    """canonical_json_bytes must sort keys (verified by byte inspection)."""
    raw = canonical_json_bytes({"b": 1, "a": 2})
    # Keys appear in sorted order: a before b
    assert raw == b'{"a":2,"b":1}'


def test_canonical_events_sha256_preserves_order():
    """Event list order must affect canonical_events_sha256."""
    e1 = [_make_event(cid="A"), _make_event(cid="B")]
    e2 = [_make_event(cid="B"), _make_event(cid="A")]
    assert canonical_events_sha256(e1) != canonical_events_sha256(e2)


def test_manifest_hash_excludes_manifest_hash():
    """compute_manifest_hash must exclude the manifest_hash key from input."""
    entry = _make_candidate_manifest()
    # Verify: removing manifest_hash and recomputing gives the same hash
    # as compute_manifest_hash(entry) (which excludes manifest_hash internally).
    body_without = {k: v for k, v in entry.items() if k != "manifest_hash"}
    direct = hashlib.sha256(canonical_json_bytes(body_without)).hexdigest()
    assert compute_manifest_hash(entry) == direct
    # And the manifest_hash stored in the entry must equal this value
    assert entry["manifest_hash"] == direct


def test_marker_integrity_detects_mutation():
    """Mutating any marker field must invalidate marker_integrity_sha256."""
    body = _make_marker_body()
    integrity = compute_marker_integrity_sha256(body)
    body["marker_integrity_sha256"] = integrity
    # Valid
    assert compute_marker_integrity_sha256(body) == integrity
    # Mutate a field
    body["status"] = "COMMITTED"
    assert compute_marker_integrity_sha256(body) != integrity


def test_eligibility_integrity_excludes_state_sha256():
    """compute_eligibility_integrity_sha256 must exclude state_sha256."""
    state = {
        "schema_version": "h011-eligibility-v1",
        "first_eligible_scan_seen": True,
        "first_eligible_scan_id": "2026-07-13T10:00:00Z",
        "first_persistible_data_api_request_at": "2026-07-13T10:00:01Z",
        "state_sha256": "deadbeef" * 8,
    }
    body_without = {k: v for k, v in state.items() if k != "state_sha256"}
    direct = hashlib.sha256(canonical_json_bytes(body_without)).hexdigest()
    assert compute_eligibility_integrity_sha256(state) == direct


# ═══════════════════════════════════════════════════════════════════════
# Section 2 — Path safety
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [
    "",
    "foo/bar",
    "foo\\bar",
    "..",
    "../etc/passwd",
    "foo/../bar",
    "/etc/passwd",
    ".",
])
def test_unsafe_filenames_rejected(bad: str):
    with pytest.raises(PathSafetyError):
        validate_bare_filename(bad)


@pytest.mark.parametrize("good", [
    "raw_scan_s1_abc123.events.jsonl.gz",
    "manifest_000001.json",
    "marker_000001_abc.marker",
    "raw_scan_s1_abc123.jsonl.gz.tmp",
    "raw_scan_s1_abc123.events.jsonl.gz.sha256",
])
def test_safe_filenames_accepted(good: str):
    validate_bare_filename(good)  # Should not raise


def test_symlink_rejected(raw_dir: Path):
    """reject_symlink must raise PathSafetyError on a symlink."""
    target = raw_dir / "real.txt"
    target.write_text("hi")
    link = raw_dir / "link.txt"
    os.symlink(target, link)
    with pytest.raises(PathSafetyError, match="symlink"):
        rt.reject_symlink(link)


def test_symlink_rejection_passes_when_missing(raw_dir: Path):
    """reject_symlink is a no-op if the path doesn't exist."""
    rt.reject_symlink(raw_dir / "does_not_exist")


# ═══════════════════════════════════════════════════════════════════════
# Section 3 — Marker schema v2
# ═══════════════════════════════════════════════════════════════════════

def test_marker_requires_every_mandatory_field():
    """Missing any required field must raise MarkerValidationError."""
    body = _make_marker_body()
    # Valid baseline
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    validate_marker(body)
    # Remove each required field one by one
    for field_name in rt.REQUIRED_MARKER_FIELDS:
        if field_name == "marker_integrity_sha256":
            continue  # already tested separately
        bad = dict(body)
        bad.pop(field_name)
        # Need to recompute integrity without the missing field
        if "marker_integrity_sha256" in bad:
            bad["marker_integrity_sha256"] = compute_marker_integrity_sha256(bad)
        with pytest.raises(MarkerValidationError, match="missing required"):
            validate_marker(bad)


def test_recoverable_must_be_boolean():
    """recoverable must be bool — not null, not int, not string."""
    body = _make_marker_body()
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    for bad_val in [None, 0, 1, "true", "false", 1.0]:
        bad = dict(body)
        bad["recoverable"] = bad_val
        bad["marker_integrity_sha256"] = compute_marker_integrity_sha256(bad)
        with pytest.raises(MarkerValidationError, match="recoverable must be bool"):
            validate_marker(bad)


def test_recoverable_absent_rejected():
    """recoverable is REQUIRED (E3), not optional."""
    body = _make_marker_body()
    del body["recoverable"]
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="missing required"):
        validate_marker(body)


def test_marker_integrity_sha256_absent_rejected():
    """marker_integrity_sha256 is REQUIRED (E3)."""
    body = _make_marker_body()
    # _make_marker_body does NOT inject marker_integrity_sha256 (it's added
    # separately by the canonical-bytes helper), so the body is already
    # missing the field here.
    assert "marker_integrity_sha256" not in body
    with pytest.raises(MarkerValidationError, match="missing required"):
        validate_marker(body)


def test_marker_integrity_mismatch_detected():
    """A wrong marker_integrity_sha256 value must raise MarkerIntegrityError."""
    body = _make_marker_body()
    body["marker_integrity_sha256"] = "0" * 64  # Wrong
    with pytest.raises(MarkerIntegrityError, match="mismatch"):
        validate_marker(body)


def test_parse_marker_rejects_invalid_json():
    with pytest.raises(MarkerValidationError, match="not valid JSON"):
        parse_marker(b"not json at all")


def test_parse_marker_rejects_non_object_root():
    with pytest.raises(MarkerValidationError, match="root must be a JSON object"):
        parse_marker(b"[1, 2, 3]")


def test_validate_marker_rejects_unknown_fields():
    body = _make_marker_body()
    body["unknown_field"] = "value"
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="unknown fields"):
        validate_marker(body)


def test_validate_marker_rejects_bad_transaction_version():
    body = _make_marker_body()
    body["transaction_version"] = "h011-artifact-txn-v1"  # wrong
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="transaction_version"):
        validate_marker(body)


def test_validate_marker_rejects_bad_status():
    body = _make_marker_body()
    body["status"] = "INVENTED"
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="status must be"):
        validate_marker(body)


def test_validate_marker_rejects_unsafe_staging_filename():
    body = _make_marker_body()
    body["staging_filename"] = "../etc/passwd"
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="staging_filename"):
        validate_marker(body)


def test_validate_marker_rejects_non_tmp_staging_filename():
    body = _make_marker_body()
    body["staging_filename"] = "raw_scan_s1.jsonl.gz"  # missing .tmp
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="staging_filename must end with .tmp"):
        validate_marker(body)


def test_validate_marker_rejects_non_sha256_sidecar_name():
    body = _make_marker_body()
    body["sidecar_name"] = "raw_scan_s1.json"  # missing .sha256
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError, match="sidecar_name must end with .sha256"):
        validate_marker(body)


# ═══════════════════════════════════════════════════════════════════════
# Section 4 — E7 candidate manifest exact validation
# ═══════════════════════════════════════════════════════════════════════

def test_candidate_base64_rejects_invalid_encoding():
    """Invalid base64 must fail check 1 of E7."""
    body = _make_marker_body()
    body["candidate_manifest_bytes_base64"] = "not!valid!base64!!"
    # Need to recompute marker integrity since we changed a field
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    errors = validate_candidate_manifest_exact(body)
    assert any("base64 decode" in e for e in errors)


def test_candidate_decoded_json_equals_candidate_manifest():
    """Check 3 of E7: json.loads(decoded) == candidate_manifest dict."""
    body = _make_marker_body()  # _make_marker_body already produces a correct body
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    # Sanity: no errors
    errors = validate_candidate_manifest_exact(body)
    assert errors == [], f"expected no errors, got: {errors}"

    # Now corrupt: modify candidate_manifest in a way that doesn't affect b64
    bad = dict(body)
    bad["candidate_manifest"] = dict(body["candidate_manifest"])
    bad["candidate_manifest"]["event_count"] = 999  # diverges from b64-encoded bytes
    bad["marker_integrity_sha256"] = compute_marker_integrity_sha256(bad)
    errors = validate_candidate_manifest_exact(bad)
    assert any("candidate_manifest dict != decoded" in e for e in errors)


def test_candidate_decoded_bytes_equal_canonical_bytes():
    """Check 4 of E7: decoded bytes must equal canonical_manifest_file_bytes(candidate_manifest)."""
    body = _make_marker_body()
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    # Sanity
    assert validate_candidate_manifest_exact(body) == []

    # Corrupt: use non-canonical encoding in the base64 (e.g., extra whitespace)
    cm = body["candidate_manifest"]
    # Encode with whitespace (not canonical) — should fail check 4
    non_canonical = (json.dumps(cm, sort_keys=True, indent=2)
                     .encode("utf-8"))
    bad = dict(body)
    bad["candidate_manifest_bytes_base64"] = base64.b64encode(non_canonical).decode("ascii")
    bad["candidate_manifest_bytes_sha256"] = hashlib.sha256(non_canonical).hexdigest()
    bad["marker_integrity_sha256"] = compute_marker_integrity_sha256(bad)
    errors = validate_candidate_manifest_exact(bad)
    assert any("canonical_manifest_file_bytes" in e for e in errors), errors


def test_candidate_sha256_mismatch_detected():
    """Check 2 of E7: SHA-256 of decoded bytes must match stored hash."""
    body = _make_marker_body()
    body["candidate_manifest_bytes_sha256"] = "0" * 64  # wrong
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    errors = validate_candidate_manifest_exact(body)
    assert any("candidate_manifest_bytes_sha256 mismatch" in e for e in errors)


def test_candidate_manifest_hash_mismatch_detected():
    """Check 5 of E7: compute_manifest_hash(candidate_manifest) must match stored manifest_hash."""
    body = _make_marker_body()
    # Tamper with the manifest_hash stored in candidate_manifest
    bad_cm = dict(body["candidate_manifest"])
    bad_cm["manifest_hash"] = "0" * 64  # wrong
    bad = dict(body)
    bad["candidate_manifest"] = bad_cm
    # We need to re-encode because the b64 bytes must match the dict for
    # check 3 to pass; but we want check 5 to fail. So encode the tampered dict.
    canonical = canonical_manifest_file_bytes(bad_cm)
    bad["candidate_manifest_bytes_base64"] = base64.b64encode(canonical).decode("ascii")
    bad["candidate_manifest_bytes_sha256"] = hashlib.sha256(canonical).hexdigest()
    bad["marker_integrity_sha256"] = compute_marker_integrity_sha256(bad)
    errors = validate_candidate_manifest_exact(bad)
    assert any("manifest_hash mismatch" in e for e in errors), errors


def test_validate_marker_runs_e7_checks():
    """validate_marker must run E7 five-check validation and raise on failure."""
    body = _make_marker_body()
    body["candidate_manifest_bytes_sha256"] = "0" * 64  # wrong
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(CandidateManifestMismatchError, match="E7 validation"):
        validate_marker(body)


# ═══════════════════════════════════════════════════════════════════════
# Section 5 — Marker persistence
# ═══════════════════════════════════════════════════════════════════════

def test_create_marker_no_replace_creates_file(raw_dir: Path):
    body = _make_marker_body()
    marker_path = create_marker_no_replace(raw_dir, "test.marker", body)
    assert marker_path.exists()
    # Verify file content round-trips through validate_marker
    raw = marker_path.read_bytes()
    parsed = parse_marker(raw)
    validate_marker(parsed)


def test_create_marker_refuses_overwrite(raw_dir: Path):
    """create_marker_no_replace must raise FileExistsError if marker exists."""
    body = _make_marker_body()
    create_marker_no_replace(raw_dir, "test.marker", body)
    with pytest.raises(FileExistsError):
        create_marker_no_replace(raw_dir, "test.marker", body)


def test_create_marker_leaves_no_temp_residue(raw_dir: Path):
    """After create_marker_no_replace, no .tmp.* files must remain."""
    body = _make_marker_body()
    create_marker_no_replace(raw_dir, "test.marker", body)
    leftover = list(raw_dir.glob("test.marker.tmp.*"))
    assert leftover == [], f"found leftover temp files: {leftover}"


def test_update_marker_requires_existing_marker(raw_dir: Path):
    """update_existing_marker_atomic must raise FileNotFoundError if marker
    does not exist."""
    body = _make_marker_body()
    with pytest.raises(FileNotFoundError):
        update_existing_marker_atomic(raw_dir, "missing.marker", body)


def test_update_marker_atomic_replaces_content(raw_dir: Path):
    """update_existing_marker_atomic must replace marker content atomically."""
    body1 = _make_marker_body(status="STAGED")
    create_marker_no_replace(raw_dir, "test.marker", body1)

    body2 = _make_marker_body(status="COMMITTED")
    update_existing_marker_atomic(raw_dir, "test.marker", body2)

    parsed = parse_marker((raw_dir / "test.marker").read_bytes())
    validate_marker(parsed)
    assert parsed["status"] == "COMMITTED"


def test_atomic_update_leaves_no_valid_temp_residue(raw_dir: Path):
    """After update_existing_marker_atomic, no .tmp.* files must remain."""
    body1 = _make_marker_body()
    create_marker_no_replace(raw_dir, "test.marker", body1)
    body2 = _make_marker_body(status="COMMITTED")
    update_existing_marker_atomic(raw_dir, "test.marker", body2)
    leftover = list(raw_dir.glob("test.marker.tmp.*"))
    assert leftover == [], f"found leftover temp files: {leftover}"


def test_create_marker_no_replace_uses_os_link_not_rename(raw_dir: Path, monkeypatch):
    """Verify that create_marker_no_replace uses os.link, not os.rename, for
    final placement. We monkeypatch os.rename to fail and confirm the marker
    is still created (because os.link is used instead)."""
    body = _make_marker_body()

    # Make os.rename raise — if the function depends on it, marker creation fails.
    def boom_rename(*args, **kwargs):
        raise AssertionError("os.rename should not be called by create_marker_no_replace")
    monkeypatch.setattr(os, "rename", boom_rename)

    marker_path = create_marker_no_replace(raw_dir, "test.marker", body)
    assert marker_path.exists()


def test_marker_filename_format():
    """marker_filename produces the canonical format."""
    name = marker_filename("manifest", 3, "550e8400-e29b-41d4-a716-446655440000")
    assert name == "manifest_txn_000003_550e8400-e29b-41d4-a716-446655440000.marker"


def test_marker_filename_rejects_negative_sequence():
    with pytest.raises(ValueError):
        marker_filename("manifest", -1, "abc")


# ═══════════════════════════════════════════════════════════════════════
# Section 6 — Locking (RawChainLockGuard)
# ═══════════════════════════════════════════════════════════════════════

def test_lock_guard_acquire_and_release(raw_dir: Path):
    """Basic acquire/release cycle works."""
    lock = RawChainLock(raw_dir, "manifest")
    guard = lock.acquire()
    try:
        assert isinstance(guard, RawChainLockGuard)
        assert guard.directory == raw_dir.resolve()
        assert guard.prefix == "manifest"
        assert guard.pid == os.getpid()
        assert not guard._closed
    finally:
        guard.close()
    assert guard._closed


def test_lock_guard_context_manager(raw_dir: Path):
    """The guard works as a context manager."""
    lock = RawChainLock(raw_dir, "manifest")
    with lock.acquire() as g:
        assert not g._closed
    assert g._closed


def test_lock_guard_rejects_wrong_pid(raw_dir: Path):
    """A guard with a wrong PID must be rejected by assert_guard_valid."""
    lock = RawChainLock(raw_dir, "manifest")
    with lock.acquire() as guard:
        # Mutate pid via object.__setattr__ (frozen dataclass escape hatch)
        object.__setattr__(guard, "pid", os.getpid() + 1)
        with pytest.raises(GuardValidationError, match="PID mismatch"):
            rt.assert_guard_valid(guard, raw_dir, "manifest")


def test_lock_guard_rejects_wrong_directory(raw_dir: Path, tmp_path: Path):
    """A guard with a wrong directory must be rejected."""
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    lock = RawChainLock(raw_dir, "manifest")
    with lock.acquire() as guard:
        with pytest.raises(GuardValidationError, match="directory mismatch"):
            rt.assert_guard_valid(guard, other_dir, "manifest")


def test_lock_guard_rejects_wrong_prefix(raw_dir: Path):
    """A guard with a wrong prefix must be rejected."""
    lock = RawChainLock(raw_dir, "manifest")
    with lock.acquire() as guard:
        with pytest.raises(GuardValidationError, match="prefix mismatch"):
            rt.assert_guard_valid(guard, raw_dir, "snapshot")


def test_lock_guard_rejects_inactive_token(raw_dir: Path):
    """A closed guard has an inactive token and must be rejected."""
    lock = RawChainLock(raw_dir, "manifest")
    guard = lock.acquire()
    guard.close()
    with pytest.raises(GuardValidationError, match="closed"):
        rt.assert_guard_valid(guard, raw_dir, "manifest")


def test_lock_guard_rejects_wrong_type(raw_dir: Path):
    """A non-RawChainLockGuard must be rejected."""
    with pytest.raises(GuardValidationError, match="must be RawChainLockGuard"):
        rt.assert_guard_valid("not a guard", raw_dir, "manifest")  # type: ignore[arg-type]


def test_nested_locking_prohibited(raw_dir: Path):
    """Acquiring a second guard while one is active must raise NestedLockingError."""
    lock1 = RawChainLock(raw_dir, "manifest")
    lock2 = RawChainLock(raw_dir, "manifest")
    with lock1.acquire():
        with pytest.raises(NestedLockingError):
            lock2.acquire()


def test_lock_can_be_reacquired_after_release(raw_dir: Path):
    """After close(), a new acquire() must succeed."""
    lock = RawChainLock(raw_dir, "manifest")
    g1 = lock.acquire()
    g1.close()
    # Should not raise
    g2 = lock.acquire()
    g2.close()


def test_lock_acquisition_failure_on_unsupported_fs(tmp_path: Path):
    """If flock raises OSError, LockAcquisitionError must be raised."""
    # We can simulate by monkeypatching fcntl.flock
    import fcntl as _fcntl
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    lock = RawChainLock(bad_dir, "manifest")
    original_flock = _fcntl.flock

    def boom_flock(fd, op):
        if op == _fcntl.LOCK_EX:
            raise OSError(38, "Function not implemented")
        return original_flock(fd, op)

    _fcntl.flock = boom_flock
    try:
        with pytest.raises(LockAcquisitionError):
            lock.acquire()
    finally:
        _fcntl.flock = original_flock
    # After restoring flock, no active tokens must remain
    assert len(rt._ACTIVE_GUARD_TOKENS) == 0


# ═══════════════════════════════════════════════════════════════════════
# Section 7 — RawScanStager (isolated)
# ═══════════════════════════════════════════════════════════════════════

def test_stager_initial_state_open(raw_dir: Path):
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        assert stager.state == "OPEN"
        assert stager.event_count == 0
    # After normal exit without seal → ABORTED_BEFORE_TRANSFER
    assert stager.state == "ABORTED_BEFORE_TRANSFER"


def test_stager_seal_produces_strict_readable_gzip(raw_dir: Path):
    """seal() must produce a gzip file that can be read by load_raw_events_strict."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        sealed = stager.seal()
        assert stager.state == "SEALED"
        # Staging file must be readable
        events = load_raw_events_strict(stager._staging_path)
        assert len(events) == 1
        assert events[0]["requested_condition_id"] == "0xabc"


def test_stager_seal_sets_read_only(raw_dir: Path):
    """After seal(), the staging file must be read-only (0o444)."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        sealed = stager.seal()
        mode = stager._staging_path.stat().st_mode & 0o777
        assert mode == 0o444, f"expected 0o444, got {oct(mode)}"


def test_stager_seal_captures_stable_inode_device_size(raw_dir: Path):
    """SealedRawArtifact must capture device_id, inode, size_bytes from fstat."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.append_event(_make_event(cid="0xdef"))
        sealed = stager.seal()
        st = stager._staging_path.stat()
        assert sealed.device_id == st.st_dev
        assert sealed.inode == st.st_ino
        assert sealed.size_bytes == st.st_size
        assert sealed.size_bytes > 0


def test_stager_seal_captures_file_sha256_from_disk(raw_dir: Path):
    """file_sha256 must match SHA-256 of the actual on-disk bytes."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        sealed = stager.seal()
        disk_bytes = stager._staging_path.read_bytes()
        assert sealed.file_sha256 == hashlib.sha256(disk_bytes).hexdigest()


def test_stager_seal_captures_canonical_events_sha256_from_disk(raw_dir: Path):
    """canonical_events_sha256 must match SHA-256 of canonical JSON of disk events."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.append_event(_make_event(cid="0xdef"))
        sealed = stager.seal()
        disk_events = load_raw_events_strict(stager._staging_path)
        expected = canonical_events_sha256(disk_events)
        assert sealed.canonical_events_sha256 == expected


def test_stager_seal_includes_version_and_staging_filename(raw_dir: Path):
    """SealedRawArtifact must include version=1 and staging_filename (A2)."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        sealed = stager.seal()
        assert sealed.version == 1
        assert sealed.staging_filename == stager._staging_path.name
        assert sealed.run_id == "r1"
        assert sealed.scan_id == "s1"
        assert sealed.sealed_at  # ISO 8601 string


def test_transfer_before_seal_rejected(raw_dir: Path):
    """transfer() called before seal() must raise StagerStateError."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        with pytest.raises(StagerStateError, match="must be SEALED"):
            stager.transfer()


def test_second_transfer_rejected(raw_dir: Path):
    """Calling transfer() twice must raise StagerStateError (either because
    state is no longer SEALED, or because _transferred flag is set)."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.seal()
        t1 = stager.transfer()
        assert isinstance(t1, RawArtifactTransfer)
        assert stager.state == "TRANSFERRED"
        # Second call must raise — state is TRANSFERRED (not SEALED) and
        # _transferred flag is set.
        with pytest.raises(StagerStateError):
            stager.transfer()


def test_transfer_returns_immutable_descriptor(raw_dir: Path):
    """RawArtifactTransfer must be a frozen dataclass with sealed, ownership_token,
    and staging_path."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        sealed = stager.seal()
        transfer = stager.transfer()
        assert transfer.sealed == sealed
        assert isinstance(transfer.ownership_token, str)
        assert len(transfer.ownership_token) == 36  # UUID4
        assert transfer.staging_path == stager._staging_path.resolve()
        # Frozen: cannot reassign
        with pytest.raises(Exception):
            transfer.ownership_token = "x"  # type: ignore[misc]


def test_open_ordinary_abort_cleans_staging(raw_dir: Path):
    """OPEN with no events + exception → ABORTED_BEFORE_TRANSFER, staging deleted."""
    try:
        with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
            raise RuntimeError("test error")
    except RuntimeError:
        pass
    assert stager.state == "ABORTED_BEFORE_TRANSFER"
    pending = list((raw_dir / ".pending").glob("*"))
    assert pending == [], f"staging should be cleaned, found: {pending}"


def test_open_normal_exit_without_seal_cleans_staging(raw_dir: Path):
    """OPEN + normal exit without seal → ABORTED_BEFORE_TRANSFER, staging deleted."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        pass  # No events, no seal
    assert stager.state == "ABORTED_BEFORE_TRANSFER"
    pending = list((raw_dir / ".pending").glob("*"))
    assert pending == []


def test_sealed_not_transferred_cleans_staging(raw_dir: Path):
    """SEALED + context exit without transfer → ABORTED_BEFORE_TRANSFER."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.seal()
    assert stager.state == "ABORTED_BEFORE_TRANSFER"
    pending = list((raw_dir / ".pending").glob("*"))
    assert pending == []


def test_transferred_does_not_clean_staging(raw_dir: Path):
    """TRANSFERRED + context exit → publisher owns lifecycle, staging preserved."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.seal()
        transfer = stager.transfer()
    assert stager.state == "TRANSFERRED"
    # Staging file must still exist (publisher will clean it in Phase II)
    assert transfer.staging_path.exists()


def test_diagnostic_abort_preserves_quarantine_evidence(raw_dir: Path):
    """OPEN with at least one event + exception → ABORTED_WITH_DIAGNOSTIC_EVIDENCE,
    staging moved to .quarantine/, diagnostic JSON written."""
    try:
        with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
            stager.append_event(_make_event())
            stager.append_event(_make_event(cid="0xdef"))
            raise RuntimeError("simulated mid-scan failure")
    except RuntimeError:
        pass
    assert stager.state == "ABORTED_WITH_DIAGNOSTIC_EVIDENCE"

    # .pending must be empty (staging was moved out)
    pending = list((raw_dir / ".pending").glob("*"))
    assert pending == [], f".pending should be empty, found: {pending}"

    # .quarantine must contain a quarantined staging file and a diagnostic JSON
    quarantine = list((raw_dir / ".quarantine").glob("*"))
    assert len(quarantine) >= 2, f"expected at least 2 files in .quarantine, got: {quarantine}"
    quarantined_staging = [p for p in quarantine if p.name.endswith(".quarantined")]
    diagnostic_jsons = [p for p in quarantine if p.name.startswith("diagnostic_") and p.name.endswith(".json")]
    assert len(quarantined_staging) == 1, f"expected 1 quarantined staging file, got: {quarantined_staging}"
    assert len(diagnostic_jsons) >= 1, f"expected >=1 diagnostic JSON, got: {diagnostic_jsons}"

    # Verify diagnostic JSON content
    diag = json.loads(diagnostic_jsons[0].read_bytes())
    assert diag["diagnostic_version"] == "h011-diagnostic-v1"
    assert diag["failure_type"] == "RuntimeError"
    assert diag["failure_message"] == "simulated mid-scan failure"
    assert diag["triggering_state"] == "OPEN"
    assert diag["events_appended_before_failure"] == 2
    assert diag["recoverable"] is False

    # Verify diagnostic integrity hash
    body = {k: v for k, v in diag.items() if k != "diagnostic_integrity_sha256"}
    expected = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    assert diag["diagnostic_integrity_sha256"] == expected

    # Verify staging file was MOVED (not copied) — content matches
    staging_sha_in_diag = diag["staging_sha256"]
    actual_sha = hashlib.sha256(quarantined_staging[0].read_bytes()).hexdigest()
    assert staging_sha_in_diag == actual_sha


def test_diagnostic_abort_writes_staging_filename(raw_dir: Path):
    """The diagnostic JSON must contain staging_filename matching the original."""
    try:
        with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
            stager.append_event(_make_event())
            raise RuntimeError("oops")
    except RuntimeError:
        pass
    diag_jsons = list((raw_dir / ".quarantine").glob("diagnostic_*.json"))
    assert len(diag_jsons) >= 1
    diag = json.loads(diag_jsons[0].read_bytes())
    # staging_filename ends with .tmp (original) — diagnostic stores original name
    assert diag["staging_filename"].endswith(".jsonl.gz.tmp")


def test_append_event_after_seal_rejected(raw_dir: Path):
    """Cannot append_event after seal()."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.seal()
        with pytest.raises(StagerStateError):
            stager.append_event(_make_event())


def test_append_invalid_event_rejected(raw_dir: Path):
    """Events missing required fields must raise RawEventPersistenceError."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        bad_event = {"received_at_utc": "2026-07-13T10:00:00Z"}  # missing most fields
        with pytest.raises(RawEventPersistenceError, match="missing required"):
            stager.append_event(bad_event)


def test_append_non_dict_event_rejected(raw_dir: Path):
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        with pytest.raises(RawEventPersistenceError, match="must be dict"):
            stager.append_event("not a dict")  # type: ignore[arg-type]


def test_seal_idempotency_rejected(raw_dir: Path):
    """Calling seal() twice must raise StagerStateError."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        stager.append_event(_make_event())
        stager.seal()
        with pytest.raises(StagerStateError):
            stager.seal()


def test_seal_without_events_succeeds(raw_dir: Path):
    """seal() with zero events must succeed (empty artifact is valid)."""
    with RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir) as stager:
        sealed = stager.seal()
        assert sealed.event_count == 0
        assert sealed.condition_ids == ()


def test_stager_uuid_staging_exclusive(raw_dir: Path):
    """Two stageters with same scan_id get different staging files (UUID)."""
    s1 = RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir)
    s2 = RawScanStager(run_id="r1", scan_id="s1", raw_dir=raw_dir)
    with s1:
        pass
    with s2:
        pass
    assert s1._staging_path != s2._staging_path


# ═══════════════════════════════════════════════════════════════════════
# Section 8 — Eligibility state
# ═══════════════════════════════════════════════════════════════════════

def test_eligibility_absent_means_unseen(raw_dir: Path):
    """No file → read_eligibility_state returns None (first_eligible_scan_seen=False)."""
    state = read_eligibility_state(raw_dir)
    assert state is None


def test_eligibility_write_and_read_roundtrip(raw_dir: Path):
    """Write true, read it back — fields must match."""
    written = write_eligibility_state(
        raw_dir,
        first_eligible_scan_seen=True,
        first_eligible_scan_id="2026-07-13T10:00:00Z",
        first_persistible_data_api_request_at="2026-07-13T10:00:01Z",
    )
    assert written.first_eligible_scan_seen is True
    read_back = read_eligibility_state(raw_dir)
    assert read_back is not None
    assert read_back.first_eligible_scan_seen is True
    assert read_back.first_eligible_scan_id == "2026-07-13T10:00:00Z"
    assert read_back.state_sha256 == written.state_sha256


def test_eligibility_corruption_fails_closed(raw_dir: Path):
    """A corrupt eligibility file must raise EligibilityCorruptionError (no
    silent fallback to false)."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    path = raw_dir / rt.ELIGIBILITY_FILENAME
    # Corrupt: append garbage
    raw = path.read_bytes()
    path.write_bytes(raw + b"\nGARBAGE")
    with pytest.raises(EligibilityCorruptionError):
        read_eligibility_state(raw_dir)


def test_eligibility_corruption_invalid_json_fails_closed(raw_dir: Path):
    """Invalid JSON must raise EligibilityCorruptionError."""
    path = raw_dir / rt.ELIGIBILITY_FILENAME
    path.write_text("not json at all")
    with pytest.raises(EligibilityCorruptionError, match="not valid JSON"):
        read_eligibility_state(raw_dir)


def test_eligibility_corruption_hash_mismatch_fails_closed(raw_dir: Path):
    """Hash mismatch must raise EligibilityCorruptionError."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    path = raw_dir / rt.ELIGIBILITY_FILENAME
    obj = json.loads(path.read_text())
    obj["state_sha256"] = "0" * 64  # wrong hash
    path.write_text(json.dumps(obj))
    with pytest.raises(EligibilityCorruptionError, match="state_sha256 mismatch"):
        read_eligibility_state(raw_dir)


def test_eligibility_true_cannot_revert_to_false(raw_dir: Path):
    """Monotonicity: once true, cannot write false."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    with pytest.raises(EligibilityMonotonicityError, match="cannot revert"):
        write_eligibility_state(raw_dir, first_eligible_scan_seen=False)


def test_eligibility_false_to_true_permitted(raw_dir: Path):
    """Monotonicity: false → true is permitted."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=False)
    # Now write true
    write_eligibility_state(
        raw_dir,
        first_eligible_scan_seen=True,
        first_eligible_scan_id="2026-07-13T10:00:00Z",
    )
    state = read_eligibility_state(raw_dir)
    assert state is not None
    assert state.first_eligible_scan_seen is True


def test_eligibility_corruption_blocks_revert_to_false(raw_dir: Path):
    """If the existing file is corrupt, write must NOT silently overwrite.
    It must re-raise the corruption error (fail-closed)."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    path = raw_dir / rt.ELIGIBILITY_FILENAME
    # Corrupt
    path.write_text("garbage")
    with pytest.raises(EligibilityCorruptionError):
        write_eligibility_state(raw_dir, first_eligible_scan_seen=False)


def test_eligibility_state_is_frozen(raw_dir: Path):
    """EligibilityState must be a frozen dataclass."""
    state = write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    with pytest.raises(Exception):
        state.first_eligible_scan_seen = False  # type: ignore[misc]


def test_eligibility_write_atomic_no_temp_residue(raw_dir: Path):
    """After write_eligibility_state, no .tmp.* files must remain."""
    write_eligibility_state(raw_dir, first_eligible_scan_seen=True)
    leftover = list(raw_dir.glob(f"{rt.ELIGIBILITY_FILENAME}.tmp.*"))
    assert leftover == []


# ═══════════════════════════════════════════════════════════════════════
# Section 9 — PublishResult type smoke tests
# ═══════════════════════════════════════════════════════════════════════

def test_publish_result_published():
    r = PublishResult(status="PUBLISHED", manifest_entry={"sequence": 0})
    assert r.status == "PUBLISHED"
    assert r.manifest_entry == {"sequence": 0}
    assert r.failure_stage is None


def test_publish_result_blocked():
    r = PublishResult(
        status="BLOCKED",
        failure_stage="MANIFEST_PUBLISHED",
        failure_message="hash mismatch",
    )
    assert r.status == "BLOCKED"
    assert r.failure_stage == "MANIFEST_PUBLISHED"


def test_publish_result_is_frozen():
    r = PublishResult(status="PUBLISHED")
    with pytest.raises(Exception):
        r.status = "BLOCKED"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# Section 10 — Error hierarchy
# ═══════════════════════════════════════════════════════════════════════

def test_error_hierarchy():
    """All subsystem errors inherit from RawTransactionError."""
    assert issubclass(RawEventPersistenceError, RawTransactionError)
    assert issubclass(RawArtifactTransactionError, RawTransactionError)
    assert issubclass(IdentityCollisionError, RawTransactionError)
    assert issubclass(MarkerValidationError, RawTransactionError)
    assert issubclass(MarkerIntegrityError, MarkerValidationError)
    assert issubclass(CandidateManifestMismatchError, MarkerValidationError)
    assert issubclass(EligibilityCorruptionError, RawTransactionError)
    assert issubclass(EligibilityMonotonicityError, RawTransactionError)
    assert issubclass(LockAcquisitionError, RawTransactionError)
    assert issubclass(NestedLockingError, RawTransactionError)
    assert issubclass(GuardValidationError, RawTransactionError)
    assert issubclass(StagerStateError, RawTransactionError)
    assert issubclass(PathSafetyError, RawTransactionError)


def test_marker_integrity_error_is_marker_validation_error():
    """MarkerIntegrityError must be catchable as MarkerValidationError."""
    body = _make_marker_body()
    body["marker_integrity_sha256"] = "0" * 64
    with pytest.raises(MarkerValidationError):
        validate_marker(body)


def test_candidate_mismatch_is_marker_validation_error():
    """CandidateManifestMismatchError must be catchable as MarkerValidationError."""
    body = _make_marker_body()
    body["candidate_manifest_bytes_sha256"] = "0" * 64
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    with pytest.raises(MarkerValidationError):
        validate_marker(body)
