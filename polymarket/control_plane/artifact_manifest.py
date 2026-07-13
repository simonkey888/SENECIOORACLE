"""
SENECIO H-011 V3 — Artifact Manifest System.

Provides append-only verification through chained manifests for raw events
and snapshots. Each manifest entry links to the previous via
`previous_manifest_hash`, creating a tamper-evident chain.

Manifest format (stored as .manifest.json sidecar):
{
  "sequence": 0,
  "filename": "raw_2026-07-13.jsonl.gz",
  "file_sha256": "...",
  "previous_manifest_hash": null,  // null for first entry
  "created_at": "2026-07-13T...",
  "manifest_hash": "..."  // hash of this manifest entry (excluding itself)
}
"""
from __future__ import annotations

import hashlib
import json
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


def write_manifest(
    directory: Path,
    artifact_path: Path,
    *,
    sequence: int,
    previous_manifest_hash: str | None,
    extra_fields: dict[str, Any] | None = None,
    manifest_prefix: str = "manifest",
) -> dict[str, Any]:
    """Write a manifest entry for an artifact file.

    Computes the SHA256 of the artifact, creates the manifest entry,
    and writes it as {manifest_prefix}_{sequence}.json next to the artifact.

    Returns the manifest entry dict.
    """
    file_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    entry = create_manifest_entry(
        sequence=sequence,
        filename=artifact_path.name,
        file_sha256=file_sha256,
        previous_manifest_hash=previous_manifest_hash,
        extra_fields=extra_fields,
    )
    manifest_path = directory / f"{manifest_prefix}_{sequence:06d}.json"
    manifest_path.write_text(json.dumps(entry, sort_keys=True, separators=(",", ":")))
    return entry


def verify_manifest_chain(directory: Path, manifest_prefix: str = "manifest") -> dict[str, Any]:
    """Verify a manifest chain in a directory.

    Returns a dict with:
      - valid: bool — entire chain is valid
      - entries: list of manifest entries in sequence order
      - errors: list of error strings
      - unregistered_files: list of artifact files not in any manifest
    """
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
            return {"valid": False, "entries": [], "errors": errors, "unregistered_files": []}

    if not entries:
        return {"valid": True, "entries": [], "errors": [], "unregistered_files": [],
                "note": "No manifests found — empty chain is valid"}

    # Sort by sequence
    entries.sort(key=lambda e: e.get("sequence", -1))

    # Check sequence continuity (0, 1, 2, ...)
    for i, entry in enumerate(entries):
        seq = entry.get("sequence")
        if seq != i:
            errors.append(f"Sequence gap or duplicate: expected {i}, got {seq}")
            return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}

    # Verify chain links
    prev_hash = None
    seen_filenames = set()
    for entry in entries:
        seq = entry["sequence"]

        # Check previous_manifest_hash
        entry_prev = entry.get("previous_manifest_hash")
        if seq == 0:
            if entry_prev is not None:
                errors.append(f"First entry (seq=0) has non-null previous_manifest_hash: {entry_prev}")
                return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}
        else:
            if entry_prev != prev_hash:
                errors.append(f"Chain broken at seq={seq}: expected prev={prev_hash[:16] if prev_hash else 'None'}, "
                              f"got={entry_prev[:16] if entry_prev else 'None'}")
                return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}

        # Verify manifest_hash
        recomputed = _compute_manifest_hash(entry)
        if entry.get("manifest_hash") != recomputed:
            errors.append(f"Manifest hash mismatch at seq={seq}: stored={entry.get('manifest_hash', '?')[:16]}, "
                          f"recomputed={recomputed[:16]}")
            return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}

        # Check filename uniqueness
        fname = entry.get("filename", "")
        if fname in seen_filenames:
            errors.append(f"Duplicate filename in manifest: {fname}")
            return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}
        seen_filenames.add(fname)

        # Verify the artifact file exists and matches file_sha256
        artifact_path = directory / fname
        if not artifact_path.exists():
            errors.append(f"Artifact file missing: {fname} (referenced by manifest seq={seq})")
            return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}

        actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_sha != entry.get("file_sha256"):
            errors.append(f"File hash mismatch for {fname}: manifest={entry.get('file_sha256', '?')[:16]}, "
                          f"actual={actual_sha[:16]}")
            return {"valid": False, "entries": entries, "errors": errors, "unregistered_files": []}

        prev_hash = entry.get("manifest_hash")

    # Check for unregistered artifact files
    # (files that exist but aren't in any manifest)
    registered = {e["filename"] for e in entries}
    # Get all artifact files (exclude manifest files and sidecars)
    all_files = set()
    for f in directory.iterdir():
        if f.is_file() and not f.name.startswith(manifest_prefix) and not f.name.endswith(".sha256"):
            if f.name != "latest.json":
                all_files.add(f.name)

    unregistered = all_files - registered
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
    """Get the manifest_hash of the last entry in the chain, or None if empty."""
    manifest_files = sorted(directory.glob(f"{manifest_prefix}_*.json"))
    if not manifest_files:
        return None
    try:
        last = json.loads(manifest_files[-1].read_text())
        return last.get("manifest_hash")
    except (json.JSONDecodeError, OSError):
        return None


def get_next_sequence(directory: Path, manifest_prefix: str = "manifest") -> int:
    """Get the next sequence number for a new manifest entry."""
    manifest_files = sorted(directory.glob(f"{manifest_prefix}_*.json"))
    if not manifest_files:
        return 0
    try:
        last = json.loads(manifest_files[-1].read_text())
        return last.get("sequence", -1) + 1
    except (json.JSONDecodeError, OSError):
        return 0
