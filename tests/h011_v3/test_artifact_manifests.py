"""Tests for artifact manifest system (FASE A.4).

Tests the manifest chain verification, atomic writing, tampering detection,
and fail-closed behavior for both raw events and snapshots.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "polymarket"))

from control_plane.artifact_manifest import (
    create_manifest_entry,
    write_manifest_atomic,
    verify_manifest_chain,
    get_last_manifest_hash,
    get_next_sequence,
    _compute_manifest_hash,
)


@pytest.fixture
def clean_dir(tmp_path):
    """Empty directory for manifest tests."""
    return tmp_path


@pytest.fixture
def artifact_file(clean_dir):
    """Create a dummy artifact file."""
    p = clean_dir / "raw_2026-07-13.events.jsonl.gz"
    p.write_bytes(b"test artifact content")
    return p


# ═══════════════════════════════════════════════════════════════════════
# Empty chain
# ═══════════════════════════════════════════════════════════════════════

def test_empty_chain_no_artifacts(clean_dir):
    """Empty directory with no artifacts — chain is valid (empty)."""
    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="*.events.jsonl.gz")
    assert result["valid"] is True
    assert result["sequence_count"] == 0


def test_artifacts_without_manifest_is_valid_empty_chain(clean_dir, artifact_file):
    """Artifacts exist but no manifests — chain is valid (empty), but
    verify returns valid=True with empty entries (not FAIL).
    The caller (INV-005/006) is responsible for checking manifest count."""
    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="*.events.jsonl.gz",
                                   exclude_names={"latest.json", "latest.json.sha256"})
    assert result["valid"] is True  # Empty chain is valid
    assert result["sequence_count"] == 0
    # artifact_file is unregistered (no manifest references it)
    # Note: verify_manifest_chain with empty chain has no entries to compare against,
    # so unregistered_files is only populated when entries exist.
    # This is correct behavior — the caller checks manifest count separately.


# ═══════════════════════════════════════════════════════════════════════
# Valid chain
# ═══════════════════════════════════════════════════════════════════════

def test_valid_chain_three_entries(clean_dir):
    """Valid chain of three entries — all checks pass."""
    for i in range(3):
        artifact = clean_dir / f"artifact_{i}.bin"
        artifact.write_bytes(f"content_{i}".encode())
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest",
                              extra_fields={"run_id": f"run_{i}", "scan_id": f"scan_{i}"})

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin",
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is True
    assert result["sequence_count"] == 3
    assert len(result["errors"]) == 0


# ═══════════════════════════════════════════════════════════════════════
# Tampering tests
# ═══════════════════════════════════════════════════════════════════════

def test_sequence_gap_detected(clean_dir):
    """Sequence gap (0, 1, 3) is detected."""
    for i in range(2):
        artifact = clean_dir / f"artifact_{i}.bin"
        artifact.write_bytes(f"content_{i}".encode())
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Manually create manifest with sequence=3 (skipping 2)
    artifact3 = clean_dir / "artifact_3.bin"
    artifact3.write_bytes(b"content_3")
    prev_hash = get_last_manifest_hash(clean_dir, "manifest")
    entry = create_manifest_entry(sequence=3, filename="artifact_3.bin",
                                  file_sha256="x" * 64, previous_manifest_hash=prev_hash)
    (clean_dir / "manifest_000003.json").write_text(json.dumps(entry))

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False
    assert "Sequence gap" in result["errors"][0]


def test_previous_hash_altered_detected(clean_dir):
    """Altered previous_manifest_hash is detected."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Tamper with previous_manifest_hash (should be null for seq=0)
    manifest_file = clean_dir / "manifest_000000.json"
    entry = json.loads(manifest_file.read_text())
    entry["previous_manifest_hash"] = "tampered"
    entry["manifest_hash"] = _compute_manifest_hash(entry)
    manifest_file.write_text(json.dumps(entry))

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False


def test_manifest_hash_altered_detected(clean_dir):
    """Altered manifest_hash is detected."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Tamper with manifest_hash
    manifest_file = clean_dir / "manifest_000000.json"
    entry = json.loads(manifest_file.read_text())
    entry["manifest_hash"] = "tampered_hash"
    manifest_file.write_text(json.dumps(entry))

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False
    assert "Manifest hash mismatch" in result["errors"][0]


def test_artifact_modified_detected(clean_dir):
    """Modified artifact file (hash mismatch) is detected."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Modify the artifact
    artifact.write_bytes(b"modified_content")

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False
    assert "File hash mismatch" in result["errors"][0]


def test_artifact_deleted_detected(clean_dir):
    """Deleted artifact file is detected."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    artifact.unlink()  # Delete the artifact

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False
    assert "Artifact file missing" in result["errors"][0]


def test_unregistered_artifact_detected(clean_dir):
    """Extra artifact not in any manifest is detected."""
    for i in range(2):
        artifact = clean_dir / f"artifact_{i}.bin"
        artifact.write_bytes(f"content_{i}".encode())
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Add unregistered artifact
    extra = clean_dir / "artifact_99.bin"
    extra.write_bytes(b"unregistered")

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert "artifact_99.bin" in result["unregistered_files"]


def test_duplicate_run_id_detected(clean_dir):
    """Duplicate run_id in snapshot manifests is detected."""
    for i in range(2):
        artifact = clean_dir / f"snapshot_{i}.json"
        artifact.write_text(f'{{"snapshot_hash": "hash_{i}"}}')
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="smanifest",
                              extra_fields={"run_id": "same_run_id", "scan_id": f"scan_{i}"})

    result = verify_manifest_chain(clean_dir, manifest_prefix="smanifest",
                                   artifact_glob="snapshot_*.json",
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is False
    assert "Duplicate run_id" in result["errors"][0]


def test_duplicate_scan_id_detected(clean_dir):
    """Duplicate scan_id in snapshot manifests is detected."""
    for i in range(2):
        artifact = clean_dir / f"snapshot_{i}.json"
        artifact.write_text(f'{{"snapshot_hash": "hash_{i}"}}')
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="smanifest",
                              extra_fields={"run_id": f"run_{i}", "scan_id": "same_scan_id"})

    result = verify_manifest_chain(clean_dir, manifest_prefix="smanifest",
                                   artifact_glob="snapshot_*.json",
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is False
    assert "Duplicate scan_id" in result["errors"][0]


def test_corrupt_manifest_json_detected(clean_dir):
    """Corrupt manifest JSON is detected."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Corrupt the manifest file
    manifest_file = clean_dir / "manifest_000000.json"
    manifest_file.write_text("{ corrupt json")

    result = verify_manifest_chain(clean_dir, manifest_prefix="manifest",
                                   artifact_glob="artifact_*.bin")
    assert result["valid"] is False
    assert "Cannot read manifest" in result["errors"][0]


# ═══════════════════════════════════════════════════════════════════════
# Atomic writing tests
# ═══════════════════════════════════════════════════════════════════════

def test_manifest_overwrite_prevented(clean_dir, artifact_file):
    """Writing a manifest that already exists raises FileExistsError."""
    write_manifest_atomic(clean_dir, artifact_file, manifest_prefix="manifest")

    # Try to write the same sequence again with a different artifact
    artifact2 = clean_dir / "raw_2026-07-14.events.jsonl.gz"
    artifact2.write_bytes(b"second artifact")
    with pytest.raises((FileExistsError, RuntimeError)):
        write_manifest_atomic(clean_dir, artifact2, manifest_prefix="manifest")


def test_get_next_sequence_corrupt_chain_returns_none(clean_dir):
    """get_next_sequence returns None when chain is corrupt (fail closed)."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Corrupt the manifest
    manifest_file = clean_dir / "manifest_000000.json"
    manifest_file.write_text("{ corrupt")

    assert get_next_sequence(clean_dir, "manifest") is None


def test_get_last_manifest_hash_corrupt_returns_none(clean_dir):
    """get_last_manifest_hash returns None when chain is corrupt."""
    artifact = clean_dir / "artifact_0.bin"
    artifact.write_bytes(b"content_0")
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="manifest")

    # Corrupt the manifest
    manifest_file = clean_dir / "manifest_000000.json"
    manifest_file.write_text("{ corrupt")

    assert get_last_manifest_hash(clean_dir, "manifest") is None


# ═══════════════════════════════════════════════════════════════════════
# Exclude and filter tests
# ═══════════════════════════════════════════════════════════════════════

def test_latest_json_excluded(clean_dir):
    """latest.json is excluded from unregistered artifact check."""
    artifact = clean_dir / "snapshot_0.json"
    artifact.write_text('{"snapshot_hash": "hash_0"}')
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="smanifest",
                          extra_fields={"run_id": "r0", "scan_id": "s0"})

    # Create latest.json (should be excluded)
    (clean_dir / "latest.json").write_text('{"latest": true}')

    result = verify_manifest_chain(clean_dir, manifest_prefix="smanifest",
                                   artifact_glob="snapshot_*.json",
                                   exclude_names={"latest.json", "latest.json.sha256"},
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is True
    assert "latest.json" not in result.get("unregistered_files", [])


def test_manifest_files_not_counted_as_artifacts(clean_dir):
    """Manifest files themselves are not counted as unregistered artifacts."""
    artifact = clean_dir / "snapshot_0.json"
    artifact.write_text('{"snapshot_hash": "hash_0"}')
    write_manifest_atomic(clean_dir, artifact, manifest_prefix="smanifest",
                          extra_fields={"run_id": "r0", "scan_id": "s0"})

    result = verify_manifest_chain(clean_dir, manifest_prefix="smanifest",
                                   artifact_glob="snapshot_*.json",
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is True
    # smanifest_000000.json should NOT be in unregistered_files
    assert all("smanifest" not in f for f in result.get("unregistered_files", []))


# ═══════════════════════════════════════════════════════════════════════
# Two consecutive writes
# ═══════════════════════════════════════════════════════════════════════

def test_two_consecutive_writes_produce_valid_chain(clean_dir):
    """Two consecutive manifest writes produce a valid chain of 2 entries."""
    for i in range(2):
        artifact = clean_dir / f"snapshot_{i}.json"
        artifact.write_text(f'{{"snapshot_hash": "hash_{i}", "run_id": "run_{i}", "scan_id": "scan_{i}"}}')
        write_manifest_atomic(clean_dir, artifact, manifest_prefix="smanifest",
                              extra_fields={"run_id": f"run_{i}", "scan_id": f"scan_{i}",
                                            "snapshot_hash": f"hash_{i}"})

    result = verify_manifest_chain(clean_dir, manifest_prefix="smanifest",
                                   artifact_glob="snapshot_*.json",
                                   exclude_names={"latest.json", "latest.json.sha256"},
                                   identity_fields=("run_id", "scan_id"))
    assert result["valid"] is True
    assert result["sequence_count"] == 2
    # Verify chain links
    entries = result["entries"]
    assert entries[0]["previous_manifest_hash"] is None
    assert entries[1]["previous_manifest_hash"] == entries[0]["manifest_hash"]
