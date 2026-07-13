"""
SENECIO H-011 V3 — Artifact Manifest System.

Provides append-only verification through chained manifests for raw events
and snapshots. Each manifest entry links to the previous via
`previous_manifest_hash`, creating a tamper-evident chain.

FASE A.4: Atomic/immutable writing, artifact filtering, run_id/scan_id
verification in snapshot manifests, fail-closed on corrupt chains.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _compute_manifest_hash(entry: dict[str, Any]) -> str:
    """Compute the hash of a manifest entry (excluding manifest_hash itself)."""
    copy = {k: v for k, v in entry.items() if k != "manifest_hash"}
    raw = json.dumps(copy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def create_manifest_entry(
    *,
    sequence: int,
    filename: str,
    file_sha256: str,
    previous_manifest_hash: str | None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a manifest entry with computed manifest_hash."""
    entry: dict[str, Any] = {
        "sequence": sequence,
        "filename": filename,
        "file_sha256": file_sha256,
        "previous_manifest_hash": previous_manifest_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra_fields:
        entry.update(extra_fields)
    entry["manifest_hash"] = _compute_manifest_hash(entry)
    return entry


def write_manifest_atomic(
    directory: Path,
    artifact_path: Path,
    *,
    manifest_prefix: str = "manifest",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a manifest entry atomically with exclusive creation.

    FASE A.4: Uses O_CREAT | O_EXCL to prevent overwriting existing manifests.
    Verifies the existing chain before getting the next sequence.
    Fails closed if the chain is corrupt.

    Returns the manifest entry dict.
    Raises FileExistsError if manifest already exists.
    Raises RuntimeError if existing chain is corrupt.
    """
    # Verify existing chain before proceeding
    verification = verify_manifest_chain(directory, manifest_prefix=manifest_prefix)
    if not verification["valid"]:
        raise RuntimeError(
            f"Cannot write manifest: existing chain is corrupt: {'; '.join(verification['errors'])}"
        )

    # Get next sequence from verified chain
    sequence = len(verification["entries"])
    previous_hash = verification["entries"][-1]["manifest_hash"] if verification["entries"] else None

    # Compute file SHA256 from the artifact
    file_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    entry = create_manifest_entry(
        sequence=sequence,
        filename=artifact_path.name,
        file_sha256=file_sha256,
        previous_manifest_hash=previous_hash,
        extra_fields=extra_fields,
    )

    manifest_path = directory / f"{manifest_prefix}_{sequence:06d}.json"
    manifest_content = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()

    # Atomic exclusive creation: O_CREAT | O_EXCL
    fd = os.open(str(manifest_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, manifest_content)
        os.fsync(fd)
    finally:
        os.close(fd)

    # Re-read and verify the full chain
    recheck = verify_manifest_chain(directory, manifest_prefix=manifest_prefix)
    if not recheck["valid"]:
        raise RuntimeError(
            f"Manifest chain corrupt after write: {'; '.join(recheck['errors'])}"
        )

    return entry


def verify_manifest_chain(
    directory: Path,
    manifest_prefix: str = "manifest",
    artifact_glob: str = "*.jsonl.gz",
    exclude_names: set[str] | None = None,
    identity_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Verify a manifest chain in a directory.

    Args:
        directory: Directory containing artifacts and manifests
        manifest_prefix: Prefix for manifest files (e.g. "manifest" or "smanifest")
        artifact_glob: Glob pattern for artifact files (e.g. "*.jsonl.gz" or "snapshot_*.json")
        exclude_names: Set of filenames to exclude from unregistered check
                       (e.g. {"latest.json", "latest.json.sha256"})
        identity_fields: Fields that must be present and unique across manifest entries
                         (e.g. ("run_id", "scan_id") for snapshot manifests)

    Returns a dict with:
      - valid: bool — entire chain is valid
      - entries: list of manifest entries in sequence order
      - errors: list of error strings
      - unregistered_files: list of artifact files not in any manifest
      - sequence_count: int
    """
    if exclude_names is None:
        exclude_names = set()

    manifest_files = sorted(directory.glob(f"{manifest_prefix}_*.json"))
    entries: list[dict[str, Any]] = []
    errors: list[str] = []

    # Load all manifests
    for mf in manifest_files:
        try:
            entry = json.loads(mf.read_text())
            entries.append(entry)
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"Cannot read manifest {mf.name}: {e}")
            return {"valid": False, "entries": [], "errors": errors,
                    "unregistered_files": [], "sequence_count": 0}

    if not entries:
        return {"valid": True, "entries": [], "errors": [], "unregistered_files": [],
                "sequence_count": 0, "note": "No manifests found — empty chain is valid"}

    # Sort by sequence
    entries.sort(key=lambda e: e.get("sequence", -1))

    # Check sequence continuity (0, 1, 2, ...)
    for i, entry in enumerate(entries):
        seq = entry.get("sequence")
        if seq != i:
            errors.append(f"Sequence gap or duplicate: expected {i}, got {seq}")
            return {"valid": False, "entries": entries, "errors": errors,
                    "unregistered_files": [], "sequence_count": len(entries)}

    # Verify chain links
    prev_hash = None
    seen_filenames: set[str] = set()
    seen_identities: dict[str, set[str]] = {f: set() for f in identity_fields}

    for entry in entries:
        seq = entry["sequence"]

        # Check previous_manifest_hash
        entry_prev = entry.get("previous_manifest_hash")
        if seq == 0:
            if entry_prev is not None:
                errors.append(f"First entry (seq=0) has non-null previous_manifest_hash: {entry_prev}")
                return {"valid": False, "entries": entries, "errors": errors,
                        "unregistered_files": [], "sequence_count": len(entries)}
        else:
            if entry_prev != prev_hash:
                errors.append(f"Chain broken at seq={seq}: expected prev={prev_hash[:16] if prev_hash else 'None'}, "
                              f"got={entry_prev[:16] if entry_prev else 'None'}")
                return {"valid": False, "entries": entries, "errors": errors,
                        "unregistered_files": [], "sequence_count": len(entries)}

        # Verify manifest_hash
        recomputed = _compute_manifest_hash(entry)
        if entry.get("manifest_hash") != recomputed:
            errors.append(f"Manifest hash mismatch at seq={seq}")
            return {"valid": False, "entries": entries, "errors": errors,
                    "unregistered_files": [], "sequence_count": len(entries)}

        # Check filename uniqueness
        fname = entry.get("filename", "")
        if fname in seen_filenames:
            errors.append(f"Duplicate filename in manifest: {fname}")
            return {"valid": False, "entries": entries, "errors": errors,
                    "unregistered_files": [], "sequence_count": len(entries)}
        seen_filenames.add(fname)

        # Check identity field uniqueness (run_id, scan_id, etc.)
        for field in identity_fields:
            val = entry.get(field)
            if val is None:
                errors.append(f"Manifest seq={seq} missing required field '{field}'")
                return {"valid": False, "entries": entries, "errors": errors,
                        "unregistered_files": [], "sequence_count": len(entries)}
            if val in seen_identities[field]:
                errors.append(f"Duplicate {field} in manifest: {val}")
                return {"valid": False, "entries": entries, "errors": errors,
                        "unregistered_files": [], "sequence_count": len(entries)}
            seen_identities[field].add(val)

        # Verify the artifact file exists and matches file_sha256
        artifact_path = directory / fname
        if not artifact_path.exists():
            errors.append(f"Artifact file missing: {fname} (referenced by manifest seq={seq})")
            return {"valid": False, "entries": entries, "errors": errors,
                    "unregistered_files": [], "sequence_count": len(entries)}

        actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_sha != entry.get("file_sha256"):
            errors.append(f"File hash mismatch for {fname}: manifest={entry.get('file_sha256', '?')[:16]}, "
                          f"actual={actual_sha[:16]}")
            return {"valid": False, "entries": entries, "errors": errors,
                    "unregistered_files": [], "sequence_count": len(entries)}

        prev_hash = entry.get("manifest_hash")

    # Check for unregistered artifact files using the glob pattern
    registered = {e["filename"] for e in entries}
    all_artifacts = set()
    for f in directory.glob(artifact_glob):
        if f.is_file() and f.name not in exclude_names:
            all_artifacts.add(f.name)

    unregistered = all_artifacts - registered
    if unregistered:
        errors.append(f"Unregistered artifact files: {sorted(unregistered)}")

    return {
        "valid": len(errors) == 0,
        "entries": entries,
        "errors": errors,
        "unregistered_files": sorted(unregistered),
        "sequence_count": len(entries),
    }


def get_last_manifest_hash(directory: Path, manifest_prefix: str = "manifest") -> str | None:
    """Get the manifest_hash of the last entry in the chain, or None if empty.

    Fails closed: returns None if chain is corrupt (does NOT return a potentially
    invalid hash).
    """
    verification = verify_manifest_chain(directory, manifest_prefix=manifest_prefix)
    if not verification["valid"]:
        return None  # Fail closed — don't return a hash from a corrupt chain
    entries = verification["entries"]
    if not entries:
        return None
    return entries[-1].get("manifest_hash")


def get_next_sequence(directory: Path, manifest_prefix: str = "manifest") -> int | None:
    """Get the next sequence number for a new manifest entry.

    FASE A.4: Returns None if chain is corrupt (fail closed).
    """
    verification = verify_manifest_chain(directory, manifest_prefix=manifest_prefix)
    if not verification["valid"]:
        return None  # Fail closed
    return len(verification["entries"])
