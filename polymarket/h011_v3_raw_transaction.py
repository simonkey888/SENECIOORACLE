"""
SENECIO H-011 V3 — Raw Artifact Transaction Core Primitives (Phase I).

Implements the foundational layer of the E1-E7 design:

  1. Canonicalization helpers (payload, events, manifest, marker, eligibility)
  2. Error hierarchy and status/resolution/stager-state enums
  3. Path safety (bare filename, containment, symlink rejection)
  4. Marker schema v2 (parse, validate, integrity hash, E7 exact manifest validation)
  5. Marker persistence (create_marker_no_replace, update_existing_marker_atomic)
  6. Locking (RawChainLock / RawChainLockGuard, no thread-local, no nested)
  7. RawScanStager isolated (OPEN/SEALED/TRANSFERRED/ABORTED_*; correct seal order;
     diagnostic quarantine with durable diagnostic JSON)
  8. Eligibility state (fail-closed read, atomic write, monotonic false→true)

NOT implemented in Phase I (deferred to Phase II+):
  - publish_raw_scan() full pipeline
  - recovery state machine
  - real artifact/sidecar/manifest publication
  - integration with run_scan_v3

All public APIs are typed, fail-closed, and free of network/credential dependencies.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import gzip
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal


# ═══════════════════════════════════════════════════════════════════════
# Section 1 — Canonicalization
# ═══════════════════════════════════════════════════════════════════════

_HEX64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_ISO_8601_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
_UUID4_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding (deterministic, UTF-8, no NaN/Infinity).

    Rules: sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    allow_nan=False. List order is preserved.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_payload_sha256(payload: Any) -> str:
    """SHA-256 of canonical JSON encoding of a single event payload."""
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_events_sha256(events: list[dict[str, Any]]) -> str:
    """SHA-256 of canonical JSON encoding of a list of events (order preserved)."""
    return hashlib.sha256(canonical_json_bytes(events)).hexdigest()


def manifest_hash_input_bytes(entry: dict[str, Any]) -> bytes:
    """Canonical JSON bytes of a manifest entry EXCLUDING the `manifest_hash` key.

    This is the input to `compute_manifest_hash`.
    """
    body = {k: v for k, v in entry.items() if k != "manifest_hash"}
    return canonical_json_bytes(body)


def compute_manifest_hash(entry: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of entry EXCLUDING `manifest_hash` key."""
    return hashlib.sha256(manifest_hash_input_bytes(entry)).hexdigest()


def canonical_manifest_file_bytes(entry: dict[str, Any]) -> bytes:
    """Canonical JSON bytes of a manifest entry INCLUDING `manifest_hash` key.

    This is the exact byte sequence that must appear in the manifest file on disk.
    """
    return canonical_json_bytes(entry)


def compute_marker_integrity_sha256(marker: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of marker EXCLUDING `marker_integrity_sha256` key."""
    body = {k: v for k, v in marker.items() if k != "marker_integrity_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def compute_eligibility_integrity_sha256(state: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of eligibility state EXCLUDING `state_sha256` key."""
    body = {k: v for k, v in state.items() if k != "state_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# Section 2 — Enums (as Literal types) and error hierarchy
# ═══════════════════════════════════════════════════════════════════════

MarkerStatus = Literal[
    "STAGED",
    "ARTIFACT_PUBLISHED",
    "SIDECAR_PUBLISHED",
    "MANIFEST_PUBLISHED",
    "COMMITTED",
]
"""Transaction progress status. Lives in marker["status"]."""

MarkerResolution = Literal["ACTIVE", "BLOCKED", "QUARANTINED"]
"""Recovery outcome. Lives in marker["resolution"]. Recovery sets this,
never `status`."""

StagerState = Literal[
    "OPEN",
    "SEALED",
    "TRANSFERRED",
    "ABORTED_BEFORE_TRANSFER",
    "ABORTED_WITH_DIAGNOSTIC_EVIDENCE",
]
"""RawScanStager lifecycle states (A11 + E4)."""

MARKER_STATUSES: Final[frozenset[str]] = frozenset({
    "STAGED", "ARTIFACT_PUBLISHED", "SIDECAR_PUBLISHED",
    "MANIFEST_PUBLISHED", "COMMITTED",
})
MARKER_RESOLUTIONS: Final[frozenset[str]] = frozenset({
    "ACTIVE", "BLOCKED", "QUARANTINED",
})
STAGER_STATES: Final[frozenset[str]] = frozenset({
    "OPEN", "SEALED", "TRANSFERRED",
    "ABORTED_BEFORE_TRANSFER", "ABORTED_WITH_DIAGNOSTIC_EVIDENCE",
})


class RawTransactionError(Exception):
    """Base class for the raw transaction subsystem."""


class RawEventPersistenceError(RawTransactionError):
    """Raised when appending or fsyncing a raw event to staging fails.

    Per A9: stop scan, BLOCKED_RAW_INTEGRITY, do NOT publish partial artifact.
    """


class RawArtifactTransactionError(RawTransactionError):
    """Raised inside the publish pipeline (Phase II). Marker/staging preserved."""


class IdentityCollisionError(RawTransactionError):
    """Raised when run_id/scan_id collide with an existing manifest entry."""


class MarkerValidationError(RawTransactionError):
    """Raised when a marker fails schema, type, or integrity validation."""


class MarkerIntegrityError(MarkerValidationError):
    """Raised specifically when marker_integrity_sha256 does not match."""


class CandidateManifestMismatchError(MarkerValidationError):
    """Raised when the E7 five-check candidate manifest validation fails."""


class EligibilityCorruptionError(RawTransactionError):
    """Raised when .eligibility_state.json is present but corrupt.

    Per D3: BLOCKED_RAW_INTEGRITY, INV-005 = FAIL (no silent fallback to false).
    """


class EligibilityMonotonicityError(RawTransactionError):
    """Raised when an attempt is made to revert first_eligible_scan_seen
    from true to false."""


class LockAcquisitionError(RawTransactionError):
    """Raised when fcntl.flock fails (e.g., filesystem does not support flock)."""


class NestedLockingError(RawTransactionError):
    """Raised when a second RawChainLock.acquire() is attempted while a guard
    is already active in the same process."""


class GuardValidationError(RawTransactionError):
    """Raised when a *_under_lock helper receives an invalid guard
    (wrong PID, wrong directory, wrong prefix, closed, or fd invalid)."""


class StagerStateError(RawTransactionError):
    """Raised when a RawScanStager method is called from the wrong state."""


class PathSafetyError(RawTransactionError):
    """Raised when a path contains forbidden components (.., /, \\, absolute)."""


# ═══════════════════════════════════════════════════════════════════════
# Section 3 — Path safety
# ═══════════════════════════════════════════════════════════════════════

_FORBIDDEN_NAME_PATTERNS: Final[tuple[str, ...]] = ("/", "\\", "..")


def validate_bare_filename(name: str) -> None:
    """Validate that `name` is a bare filename (no path components).

    Rejects: absolute paths, paths containing "/" or "\\", paths containing
    ".." anywhere, empty strings, and names that resolve to a path with
    directory components when joined.

    Raises PathSafetyError on any violation.
    """
    if not isinstance(name, str):
        raise PathSafetyError(f"filename must be a string, got {type(name).__name__}")
    if not name:
        raise PathSafetyError("filename is empty")
    for pat in _FORBIDDEN_NAME_PATTERNS:
        if pat in name:
            raise PathSafetyError(
                f"filename contains forbidden component {pat!r}: {name!r}"
            )
    if os.path.isabs(name):
        raise PathSafetyError(f"absolute filename forbidden: {name!r}")
    # Final defense: if Path(name).parts has more than one element, reject.
    parts = Path(name).parts
    if len(parts) != 1:
        raise PathSafetyError(
            f"filename has multiple path components: {name!r} -> {parts}"
        )


def validate_contained_path(path: Path, base: Path) -> Path:
    """Validate that `path` resolves to a location inside `base`.

    Both arguments should be absolute (or `base` should be). The function
    resolves symlinks on `base` but NOT on `path` (to avoid TOCTOU); instead
    it uses os.path.commonpath to verify containment.

    Raises PathSafetyError if `path` is not inside `base`.
    """
    if not isinstance(path, Path):
        raise PathSafetyError(f"path must be Path, got {type(path).__name__}")
    if not isinstance(base, Path):
        raise PathSafetyError(f"base must be Path, got {type(base).__name__}")
    base_resolved = base.resolve()
    # Do NOT resolve `path` (symlinks could be malicious). Instead, normalize
    # lexically and check containment.
    path_abs = path if path.is_absolute() else (base_resolved / path)
    # Use os.path.normpath to collapse .. etc., then check prefix.
    norm = os.path.normpath(str(path_abs))
    base_norm = os.path.normpath(str(base_resolved))
    if norm != base_norm and not norm.startswith(base_norm + os.sep):
        raise PathSafetyError(
            f"path {path} is not contained within {base}"
        )
    return Path(norm)


def reject_symlink(path: Path) -> None:
    """Raise PathSafetyError if `path` is a symlink.

    Uses os.lstat to avoid following the symlink. If the path does not exist,
    this function is a no-op (existence is checked elsewhere).
    """
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return  # Existence is checked elsewhere.
    except OSError as exc:
        raise PathSafetyError(f"cannot lstat {path}: {exc}") from exc
    import stat as statmod
    if statmod.S_ISLNK(st.st_mode):
        raise PathSafetyError(f"symlink forbidden: {path}")


def is_safe_filename_component(name: str) -> bool:
    """Predicate form of validate_bare_filename. Returns True/False."""
    try:
        validate_bare_filename(name)
        return True
    except PathSafetyError:
        return False


# ═══════════════════════════════════════════════════════════════════════
# Section 4 — Marker schema v2
# ═══════════════════════════════════════════════════════════════════════

MARKER_VERSION: Final[str] = "h011-artifact-txn-v2"
ELIGIBILITY_SCHEMA_VERSION: Final[str] = "h011-eligibility-v1"
DIAGNOSTIC_SCHEMA_VERSION: Final[str] = "h011-diagnostic-v1"

REQUIRED_MARKER_FIELDS: Final[tuple[str, ...]] = (
    "transaction_version",
    "transaction_uuid",
    "ownership_token",
    "status",
    "resolution",
    "sequence",
    "run_id",
    "scan_id",
    "staging_filename",
    "final_name",
    "sidecar_name",
    "manifest_name",
    "device_id",
    "inode",
    "size_bytes",
    "file_sha256",
    "canonical_events_sha256",
    "event_count",
    "condition_ids",
    "previous_manifest_hash",
    "candidate_manifest",
    "candidate_manifest_bytes_base64",
    "candidate_manifest_bytes_sha256",
    "manifest_created_at",
    "recoverable",
    "marker_integrity_sha256",
)

OPTIONAL_MARKER_FIELDS: Final[tuple[str, ...]] = (
    "failure_stage",
    "failure_type",
    "failure_message",
)


def _validate_hex64(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not _HEX64_RE.match(value):
        raise MarkerValidationError(
            f"{field_name} must be 64-char lowercase hex, got {value!r}"
        )


def _validate_uuid4(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not _UUID4_RE.match(value.lower()):
        raise MarkerValidationError(
            f"{field_name} must be a UUID4 string, got {value!r}"
        )


def _validate_iso8601(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not _ISO_8601_RE.match(value):
        raise MarkerValidationError(
            f"{field_name} must be ISO 8601 UTC, got {value!r}"
        )


def _validate_non_empty_str(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not value:
        raise MarkerValidationError(f"{field_name} must be non-empty")


def _validate_bare_filename_field(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    try:
        validate_bare_filename(value)
    except PathSafetyError as exc:
        raise MarkerValidationError(
            f"{field_name} is not a safe bare filename: {exc}"
        ) from exc


def parse_marker(raw_bytes: bytes) -> dict[str, Any]:
    """Parse marker bytes into a dict. Strict JSON.

    Raises MarkerValidationError on any parse failure.
    """
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise MarkerValidationError(
            f"raw_bytes must be bytes, got {type(raw_bytes).__name__}"
        )
    try:
        obj = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarkerValidationError(f"marker is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise MarkerValidationError(
            f"marker root must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def validate_marker(marker: dict[str, Any]) -> None:
    """Validate marker schema, types, integrity hash, and E7 candidate equivalence.

    Raises MarkerValidationError (or a subclass) on any failure.
    """
    if not isinstance(marker, dict):
        raise MarkerValidationError(
            f"marker must be dict, got {type(marker).__name__}"
        )

    # Required fields present
    missing = [f for f in REQUIRED_MARKER_FIELDS if f not in marker]
    if missing:
        raise MarkerValidationError(
            f"marker missing required fields: {missing}"
        )

    # Unknown top-level keys (only required + optional are allowed)
    allowed = set(REQUIRED_MARKER_FIELDS) | set(OPTIONAL_MARKER_FIELDS)
    unknown = [k for k in marker.keys() if k not in allowed]
    if unknown:
        raise MarkerValidationError(
            f"marker has unknown fields: {unknown}"
        )

    # transaction_version
    if marker["transaction_version"] != MARKER_VERSION:
        raise MarkerValidationError(
            f"transaction_version must be {MARKER_VERSION!r}, "
            f"got {marker['transaction_version']!r}"
        )

    # UUID4 fields
    _validate_uuid4(marker["transaction_uuid"], "transaction_uuid")
    _validate_uuid4(marker["ownership_token"], "ownership_token")

    # status
    if marker["status"] not in MARKER_STATUSES:
        raise MarkerValidationError(
            f"status must be one of {sorted(MARKER_STATUSES)}, "
            f"got {marker['status']!r}"
        )

    # resolution
    if marker["resolution"] not in MARKER_RESOLUTIONS:
        raise MarkerValidationError(
            f"resolution must be one of {sorted(MARKER_RESOLUTIONS)}, "
            f"got {marker['resolution']!r}"
        )

    # sequence
    if not isinstance(marker["sequence"], int) or isinstance(marker["sequence"], bool):
        raise MarkerValidationError(
            f"sequence must be int, got {type(marker['sequence']).__name__}"
        )
    if marker["sequence"] < 0:
        raise MarkerValidationError(
            f"sequence must be non-negative, got {marker['sequence']}"
        )

    # run_id, scan_id
    _validate_non_empty_str(marker["run_id"], "run_id")
    _validate_non_empty_str(marker["scan_id"], "scan_id")

    # filename fields — bare filenames
    _validate_bare_filename_field(marker["staging_filename"], "staging_filename")
    _validate_bare_filename_field(marker["final_name"], "final_name")
    _validate_bare_filename_field(marker["sidecar_name"], "sidecar_name")
    _validate_bare_filename_field(marker["manifest_name"], "manifest_name")

    # staging_filename must end with .tmp
    if not marker["staging_filename"].endswith(".tmp"):
        raise MarkerValidationError(
            f"staging_filename must end with .tmp, got {marker['staging_filename']!r}"
        )
    # sidecar_name must end with .sha256
    if not marker["sidecar_name"].endswith(".sha256"):
        raise MarkerValidationError(
            f"sidecar_name must end with .sha256, got {marker['sidecar_name']!r}"
        )

    # device_id, inode — int (can be 0)
    for f in ("device_id", "inode"):
        v = marker[f]
        if not isinstance(v, int) or isinstance(v, bool):
            raise MarkerValidationError(
                f"{f} must be int, got {type(v).__name__}"
            )

    # size_bytes — int >= 0
    if not isinstance(marker["size_bytes"], int) or isinstance(marker["size_bytes"], bool):
        raise MarkerValidationError(
            f"size_bytes must be int, got {type(marker['size_bytes']).__name__}"
        )
    if marker["size_bytes"] < 0:
        raise MarkerValidationError(
            f"size_bytes must be >= 0, got {marker['size_bytes']}"
        )

    # hex64 fields
    _validate_hex64(marker["file_sha256"], "file_sha256")
    _validate_hex64(marker["canonical_events_sha256"], "canonical_events_sha256")
    _validate_hex64(marker["candidate_manifest_bytes_sha256"], "candidate_manifest_bytes_sha256")
    _validate_hex64(marker["marker_integrity_sha256"], "marker_integrity_sha256")

    # event_count
    if not isinstance(marker["event_count"], int) or isinstance(marker["event_count"], bool):
        raise MarkerValidationError(
            f"event_count must be int, got {type(marker['event_count']).__name__}"
        )
    if marker["event_count"] < 0:
        raise MarkerValidationError(
            f"event_count must be >= 0, got {marker['event_count']}"
        )

    # condition_ids
    cid = marker["condition_ids"]
    if not isinstance(cid, list):
        raise MarkerValidationError(
            f"condition_ids must be list, got {type(cid).__name__}"
        )
    for i, c in enumerate(cid):
        if not isinstance(c, str):
            raise MarkerValidationError(
                f"condition_ids[{i}] must be str, got {type(c).__name__}"
            )

    # previous_manifest_hash — hex64 or null
    pmh = marker["previous_manifest_hash"]
    if pmh is not None:
        if not isinstance(pmh, str):
            raise MarkerValidationError(
                f"previous_manifest_hash must be str or null, got {type(pmh).__name__}"
            )
        if not _HEX64_RE.match(pmh):
            raise MarkerValidationError(
                f"previous_manifest_hash must be 64-char hex or null, got {pmh!r}"
            )

    # candidate_manifest — dict
    cm = marker["candidate_manifest"]
    if not isinstance(cm, dict):
        raise MarkerValidationError(
            f"candidate_manifest must be dict, got {type(cm).__name__}"
        )
    if "manifest_hash" not in cm:
        raise MarkerValidationError(
            "candidate_manifest must contain manifest_hash key"
        )

    # candidate_manifest_bytes_base64 — str
    if not isinstance(marker["candidate_manifest_bytes_base64"], str):
        raise MarkerValidationError(
            "candidate_manifest_bytes_base64 must be str, got "
            f"{type(marker['candidate_manifest_bytes_base64']).__name__}"
        )

    # manifest_created_at — ISO 8601
    _validate_iso8601(marker["manifest_created_at"], "manifest_created_at")

    # recoverable — REQUIRED boolean (E3), not null, not absent
    rec = marker["recoverable"]
    if not isinstance(rec, bool):
        raise MarkerValidationError(
            f"recoverable must be bool (REQUIRED, E3), got {type(rec).__name__}: {rec!r}"
        )

    # Optional fields — if present, must be correct type
    for f in OPTIONAL_MARKER_FIELDS:
        v = marker.get(f)
        if v is not None and not isinstance(v, str):
            raise MarkerValidationError(
                f"{f} must be str or null, got {type(v).__name__}"
            )

    # marker_integrity_sha256 verification (E3)
    recomputed = compute_marker_integrity_sha256(marker)
    if recomputed != marker["marker_integrity_sha256"]:
        raise MarkerIntegrityError(
            f"marker_integrity_sha256 mismatch: computed={recomputed} "
            f"stored={marker['marker_integrity_sha256']}"
        )

    # E7 — five-check candidate manifest exact validation
    errors = validate_candidate_manifest_exact(marker)
    if errors:
        raise CandidateManifestMismatchError(
            "candidate_manifest E7 validation failed: " + "; ".join(errors)
        )


def validate_candidate_manifest_exact(marker: dict[str, Any]) -> list[str]:
    """E7 — five-check candidate manifest validation.

    Returns a list of error strings. Empty list = valid.
    """
    errors: list[str] = []

    b64 = marker.get("candidate_manifest_bytes_base64", "")
    if not isinstance(b64, str):
        errors.append(
            f"candidate_manifest_bytes_base64 must be str, got {type(b64).__name__}"
        )
        return errors

    # Check 1: base64 decode with validation
    try:
        decoded = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        errors.append(f"base64 decode failed: {exc}")
        return errors  # Cannot continue without decoded bytes.

    # Check 2: SHA-256 of decoded bytes must match stored hash
    computed_sha = hashlib.sha256(decoded).hexdigest()
    if computed_sha != marker.get("candidate_manifest_bytes_sha256"):
        errors.append(
            f"candidate_manifest_bytes_sha256 mismatch: "
            f"computed={computed_sha} stored={marker.get('candidate_manifest_bytes_sha256')}"
        )

    # Check 3: JSON-decoded bytes must equal the candidate_manifest dict
    try:
        decoded_dict = json.loads(decoded)
    except json.JSONDecodeError as exc:
        errors.append(f"json decode of base64 bytes failed: {exc}")
        return errors
    if decoded_dict != marker.get("candidate_manifest"):
        errors.append(
            "candidate_manifest dict != decoded base64 bytes (json.loads(decoded) != candidate_manifest)"
        )

    # Check 4: decoded bytes must equal canonical_manifest_file_bytes(candidate_manifest)
    cm = marker.get("candidate_manifest")
    if not isinstance(cm, dict):
        errors.append("candidate_manifest must be dict for check 4")
    else:
        try:
            canonical = canonical_manifest_file_bytes(cm)
        except (TypeError, ValueError) as exc:
            errors.append(f"canonical_manifest_file_bytes failed: {exc}")
        else:
            if decoded != canonical:
                errors.append(
                    "decoded base64 bytes != canonical_manifest_file_bytes(candidate_manifest)"
                )

    # Check 5: compute_manifest_hash(candidate_manifest) must equal stored manifest_hash
    if isinstance(cm, dict) and "manifest_hash" in cm:
        try:
            recomputed = compute_manifest_hash(cm)
        except (TypeError, ValueError) as exc:
            errors.append(f"compute_manifest_hash failed: {exc}")
        else:
            if recomputed != cm["manifest_hash"]:
                errors.append(
                    f"manifest_hash mismatch: computed={recomputed} "
                    f"stored={cm['manifest_hash']}"
                )
    elif isinstance(cm, dict):
        errors.append("candidate_manifest missing manifest_hash key for check 5")

    return errors


# ═══════════════════════════════════════════════════════════════════════
# Section 5 — Marker persistence
# ═══════════════════════════════════════════════════════════════════════

def _dir_fsync(directory: Path) -> None:
    """fsync a directory by opening it O_RDONLY and calling os.fsync.

    Raises OSError on failure.
    """
    dir_fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _canonical_marker_bytes(marker_body: dict[str, Any]) -> bytes:
    """Compute canonical marker bytes INCLUDING marker_integrity_sha256.

    The integrity hash is computed over the body WITHOUT the field, then
    the field is injected, then the body is re-serialized canonically.
    """
    body_without_hash = {k: v for k, v in marker_body.items()
                         if k != "marker_integrity_sha256"}
    canonical_without = canonical_json_bytes(body_without_hash)
    integrity = hashlib.sha256(canonical_without).hexdigest()
    body_with_hash = dict(marker_body)
    body_with_hash["marker_integrity_sha256"] = integrity
    return canonical_json_bytes(body_with_hash)


def create_marker_no_replace(
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
) -> Path:
    """E2 — Create a marker. Refuses to replace an existing marker.

    Final placement uses os.link(temp_path, marker_path), NOT os.rename.
    Raises FileExistsError if marker_path already exists.
    """
    validate_bare_filename(marker_name)
    reject_symlink(directory / marker_name)
    marker_path = directory / marker_name
    if marker_path.exists():
        raise FileExistsError(
            f"marker already exists: {marker_name} — use update_existing_marker_atomic"
        )

    canonical_bytes = _canonical_marker_bytes(marker_body)
    temp_name = f"{marker_name}.tmp.{uuid.uuid4().hex}"
    temp_path = directory / temp_name

    fd = os.open(
        str(temp_path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o644,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_bytes)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # Best-effort cleanup of temp on failure. Specific exceptions are
        # allowed to propagate; we just clean up the temp file first.
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise

    # Non-replace placement: os.link, NOT os.rename.
    try:
        os.link(temp_path, marker_path)
    except FileExistsError:
        # Raced: another process created the marker. Fail-closed.
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    finally:
        # temp_path is now reachable via marker_path (hardlink);
        # unlink the temp_path name only.
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass

    _dir_fsync(directory)
    return marker_path


def update_existing_marker_atomic(
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
) -> Path:
    """E2 — Update an existing marker atomically.

    Requires the marker to already exist (raises FileNotFoundError otherwise).
    Atomic replace via os.rename(temp_path, marker_path) is permitted here
    because the "existing" precondition is explicit.
    """
    validate_bare_filename(marker_name)
    marker_path = directory / marker_name
    # Reject symlink at marker_path (don't follow it).
    reject_symlink(marker_path)
    if not marker_path.exists():
        raise FileNotFoundError(
            f"marker does not exist: {marker_name} — use create_marker_no_replace"
        )

    canonical_bytes = _canonical_marker_bytes(marker_body)
    temp_name = f"{marker_name}.tmp.{uuid.uuid4().hex}"
    temp_path = directory / temp_name

    fd = os.open(
        str(temp_path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o644,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_bytes)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise

    # Atomic replace is permitted here because the precondition is explicit.
    os.rename(temp_path, marker_path)
    _dir_fsync(directory)
    return marker_path


# ═══════════════════════════════════════════════════════════════════════
# Section 6 — Locking (RawChainLockGuard)
# ═══════════════════════════════════════════════════════════════════════

# Process-wide registry of active guard tokens. NOT thread-local — it's a
# class-level frozenset that prevents any second acquire() in the same
# process. This enforces "no nested locking" (E5).
_ACTIVE_GUARD_TOKENS: set[str] = set()


@dataclass(frozen=True)
class RawChainLockGuard:
    """Proof that the caller holds the raw chain flock.

    Constructed exclusively by RawChainLock.acquire(). The guard carries the
    open lock_fd; the lock is released when the guard is closed via close()
    or __exit__. The guard object itself is the proof of holding the lock —
    there is no thread-local fallback (E5).

    Validation fields:
      - pid: PID of the process that acquired the lock. A guard used from a
        different PID is rejected.
      - directory: absolute resolved path of the chain directory.
      - prefix: manifest_prefix from the policy.
      - lock_fd: open file descriptor holding the flock.
      - token: UUID4 generated at acquire() time. Tracked in the
        process-wide _ACTIVE_GUARD_TOKENS set; removed on close().
      - _closed: mutable via object.__setattr__; set True on close().
    """
    directory: Path
    prefix: str
    lock_fd: int
    pid: int
    token: str
    _closed: bool = False

    def __enter__(self) -> "RawChainLockGuard":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        except OSError:
            # fd may already be invalid; best-effort unlock.
            pass
        try:
            os.close(self.lock_fd)
        except OSError:
            pass
        object.__setattr__(self, "_closed", True)
        # Remove token from process-wide registry.
        _ACTIVE_GUARD_TOKENS.discard(self.token)


@dataclass(frozen=True)
class RawChainLock:
    """Factory for RawChainLockGuard. The ONLY way to acquire the lock.

    Construct with the chain directory and the ManifestPolicy. acquire()
    opens the lock file, takes an exclusive flock, and returns a guard. If
    a guard is already active in this process, acquire() raises
    NestedLockingError (preventing the deadlock that would result from a
    second flock on the same file).
    """
    directory: Path
    prefix: str

    def acquire(self) -> RawChainLockGuard:
        # Enforce no nested locking in the same process.
        if _ACTIVE_GUARD_TOKENS:
            raise NestedLockingError(
                f"a RawChainLockGuard is already active in this process "
                f"(tokens={sorted(_ACTIVE_GUARD_TOKENS)}); nested locking prohibited"
            )
        lock_path = self.directory / f"{self.prefix}.lock"
        # Ensure the directory exists (lock file creation needs it).
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_RDWR,
                0o644,
            )
        except OSError as exc:
            raise LockAcquisitionError(
                f"cannot open lock file {lock_path}: {exc}"
            ) from exc
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError as exc:
            os.close(lock_fd)
            raise LockAcquisitionError(
                f"fcntl.flock(LOCK_EX) failed on {lock_path}: {exc}. "
                f"Filesystem may not support flock."
            ) from exc
        token = str(uuid.uuid4())
        _ACTIVE_GUARD_TOKENS.add(token)
        return RawChainLockGuard(
            directory=self.directory.resolve(),
            prefix=self.prefix,
            lock_fd=lock_fd,
            pid=os.getpid(),
            token=token,
        )


def assert_guard_valid(
    guard: RawChainLockGuard,
    directory: Path,
    prefix: str,
) -> None:
    """Validate that a guard is active, matches the caller's PID, and matches
    the expected directory and prefix.

    Called by every *_under_lock helper. Raises GuardValidationError on any
    mismatch.
    """
    if not isinstance(guard, RawChainLockGuard):
        raise GuardValidationError(
            f"guard must be RawChainLockGuard, got {type(guard).__name__}"
        )
    if getattr(guard, "_closed", False):
        raise GuardValidationError("guard is already closed (token inactive)")
    if guard.pid != os.getpid():
        raise GuardValidationError(
            f"guard PID mismatch: guard.pid={guard.pid} os.getpid()={os.getpid()}"
        )
    if guard.directory != directory.resolve():
        raise GuardValidationError(
            f"guard directory mismatch: guard.directory={guard.directory} "
            f"expected={directory.resolve()}"
        )
    if guard.prefix != prefix:
        raise GuardValidationError(
            f"guard prefix mismatch: guard.prefix={guard.prefix!r} "
            f"expected={prefix!r}"
        )
    # fd still open?
    try:
        os.fstat(guard.lock_fd)
    except OSError as exc:
        raise GuardValidationError(
            f"guard lock_fd {guard.lock_fd} is not a valid open fd: {exc}"
        ) from exc
    if guard.token not in _ACTIVE_GUARD_TOKENS:
        raise GuardValidationError(
            f"guard token {guard.token} is not in the active registry "
            f"(inactive token)"
        )


# ═══════════════════════════════════════════════════════════════════════
# Section 7 — Types / models
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SealedRawArtifact:
    """A2 — Sealed descriptor returned by RawScanStager.seal().

    All fields are captured at seal() time from the actual on-disk file
    (after fsync, chmod 0o444, and strict reread). The descriptor is the
    sole source of truth for the publisher; in-memory state is observational
    only.
    """
    version: int
    staging_filename: str
    final_name: str
    run_id: str
    scan_id: str
    event_count: int
    condition_ids: tuple[str, ...]
    file_sha256: str
    canonical_events_sha256: str
    size_bytes: int
    sealed_at: str
    device_id: int
    inode: int


@dataclass(frozen=True)
class RawArtifactTransfer:
    """A8 (D5, E5) — Immutable ownership transfer descriptor.

    No callbacks. No mutable methods. The transfer is an immutable descriptor
    that carries the sealed artifact and the staging path; the marker durable
    (created in Phase II by publish_raw_scan) is the sole authority for
    lifecycle after this point.
    """
    sealed: SealedRawArtifact
    ownership_token: str
    staging_path: Path


@dataclass(frozen=True)
class PublishResult:
    """A8 — Result of publish_raw_scan() (Phase II). Defined here so Phase I
    tests can verify the type is constructible and frozen.

    status: "PUBLISHED" | "RECOVERABLE_ERROR" | "BLOCKED"
    """
    status: str
    manifest_entry: dict[str, Any] | None = None
    failure_stage: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class DiagnosticEvidence:
    """E4 — Durable diagnostic evidence written to .quarantine/ on
    ABORTED_WITH_DIAGNOSTIC_EVIDENCE transitions.

    The diagnostic JSON carries its own `diagnostic_integrity_sha256` field
    computed the same way as `marker_integrity_sha256`.
    """
    diagnostic_version: str
    transaction_uuid: str
    ownership_token: str
    diagnostic_created_at: str
    triggering_state: str
    failure_stage: str
    failure_type: str
    failure_message: str
    staging_filename: str
    staging_sha256: str | None
    staging_size_bytes: int | None
    marker_filename: str | None
    marker_integrity_sha256: str | None
    events_appended_before_failure: int | None
    events_appended_total_expected: int | None
    recoverable: bool
    diagnostic_integrity_sha256: str


def compute_diagnostic_integrity_sha256(diag: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of diagnostic EXCLUDING the integrity field."""
    body = {k: v for k, v in diag.items() if k != "diagnostic_integrity_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _canonical_diagnostic_bytes(diag_body: dict[str, Any]) -> bytes:
    """Compute canonical diagnostic JSON bytes INCLUDING diagnostic_integrity_sha256."""
    body_without = {k: v for k, v in diag_body.items()
                    if k != "diagnostic_integrity_sha256"}
    integrity = hashlib.sha256(canonical_json_bytes(body_without)).hexdigest()
    body_with = dict(diag_body)
    body_with["diagnostic_integrity_sha256"] = integrity
    return canonical_json_bytes(body_with)


def write_diagnostic_evidence(
    quarantine_dir: Path,
    diagnostic: DiagnosticEvidence,
) -> Path:
    """E4 — Write a DiagnosticEvidence record to .quarantine/ atomically.

    The diagnostic JSON is written via O_CREAT|O_EXCL temp + fsync + rename
    + dir fsync. The destination filename is unique per transaction_uuid.
    If a file with the same name already exists, a unique suffix is appended
    (non-replace semantics — never overwrite an existing diagnostic).
    """
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    diag_dict = {
        "diagnostic_version": diagnostic.diagnostic_version,
        "transaction_uuid": diagnostic.transaction_uuid,
        "ownership_token": diagnostic.ownership_token,
        "diagnostic_created_at": diagnostic.diagnostic_created_at,
        "triggering_state": diagnostic.triggering_state,
        "failure_stage": diagnostic.failure_stage,
        "failure_type": diagnostic.failure_type,
        "failure_message": diagnostic.failure_message,
        "staging_filename": diagnostic.staging_filename,
        "staging_sha256": diagnostic.staging_sha256,
        "staging_size_bytes": diagnostic.staging_size_bytes,
        "marker_filename": diagnostic.marker_filename,
        "marker_integrity_sha256": diagnostic.marker_integrity_sha256,
        "events_appended_before_failure": diagnostic.events_appended_before_failure,
        "events_appended_total_expected": diagnostic.events_appended_total_expected,
        "recoverable": diagnostic.recoverable,
    }
    canonical_bytes = _canonical_diagnostic_bytes(diag_dict)

    base_name = (
        f"diagnostic_{diagnostic.transaction_uuid}"
        f".{uuid.uuid4().hex[:8]}.json"
    )
    final_path = quarantine_dir / base_name
    # Non-replace: if the path somehow exists, append another suffix.
    while final_path.exists():
        final_path = quarantine_dir / (
            f"diagnostic_{diagnostic.transaction_uuid}"
            f".{uuid.uuid4().hex[:8]}.json"
        )

    temp_name = f"{final_path.name}.tmp.{uuid.uuid4().hex}"
    temp_path = quarantine_dir / temp_name
    fd = os.open(
        str(temp_path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o644,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_bytes)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    os.rename(temp_path, final_path)
    _dir_fsync(quarantine_dir)
    return final_path


# ═══════════════════════════════════════════════════════════════════════
# Section 8 — RawScanStager (isolated)
# ═══════════════════════════════════════════════════════════════════════

_RAW_EVENT_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset({
    "received_at_utc", "source", "endpoint", "payload",
    "payload_sha256", "schema_version",
})


def _safe_scan_id(scan_id: str) -> str:
    """Convert scan_id to a filesystem-safe string (cap length 100)."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in scan_id)
    return safe[:100]


def load_raw_events_strict(path: Path) -> list[dict[str, Any]]:
    """Load raw events from a gzipped JSONL file with strict validation.

    Fails on:
      - gzip truncation or CRC error
      - invalid JSON lines
      - empty lines (unexpected)
      - non-dict payloads
      - missing required schema fields
    """
    events: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                raise ValueError(f"Empty line {line_num} in {path.name}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at line {line_num} in {path.name}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                raise ValueError(
                    f"Non-dict payload at line {line_num} in {path.name}"
                )
            missing = _RAW_EVENT_REQUIRED_FIELDS - set(event.keys())
            if missing:
                raise ValueError(
                    f"Missing fields {missing} at line {line_num} in {path.name}"
                )
            events.append(event)
    return events


@dataclass
class RawScanStager:
    """A11 + E4 — Isolated raw scan stager.

    Lifecycle states (StagerState):
      OPEN → SEALED → TRANSFERRED → (publisher owns lifecycle)
      OPEN + exception before first event → ABORTED_BEFORE_TRANSFER (delete staging)
      OPEN + exception after first event → ABORTED_WITH_DIAGNOSTIC_EVIDENCE
                                           (preserve staging, write diagnostic)
      SEALED + no transfer → ABORTED_BEFORE_TRANSFER (delete staging)

    seal() follows the D2 definitive order:
      flush → close → fsync → fstat → chmod → dir fsync → strict reread →
      recalculate → build SealedRawArtifact → return

    transfer() is a single SEALED → TRANSFERRED transition. Calling it
    before seal() raises StagerStateError. Calling it twice raises
    StagerStateError.

    This stager does NOT publish anything. Phase II's publish_raw_scan()
    will consume the RawArtifactTransfer.
    """
    run_id: str
    scan_id: str
    raw_dir: Path
    _state: StagerState = "OPEN"
    _staging_path: Path | None = None
    _events: list[dict[str, Any]] = field(default_factory=list)
    _condition_ids: set[str] = field(default_factory=set)
    _sealed_descriptor: SealedRawArtifact | None = None
    _transferred: bool = False
    _ownership_token: str | None = None
    _gzip_handle: Any = None

    # ----- context manager -----

    def __enter__(self) -> "RawScanStager":
        if self._state != "OPEN":
            raise StagerStateError(f"cannot enter from state {self._state}")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = self.raw_dir / ".pending"
        staging_dir.mkdir(exist_ok=True)
        safe_id = _safe_scan_id(self.scan_id)
        unique_suffix = uuid.uuid4().hex[:12]
        staging_name = f"raw_scan_{safe_id}_{unique_suffix}.jsonl.gz.tmp"
        self._staging_path = staging_dir / staging_name
        # Create with O_CREAT | O_EXCL to prevent collision.
        fd = os.open(
            str(self._staging_path),
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o644,
        )
        os.close(fd)
        # Open a gzip handle for appending. We keep it open across append_event
        # calls to amortize the gzip header cost.
        self._gzip_handle = gzip.open(self._staging_path, "at", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # Close the gzip handle if it's still open.
        if self._gzip_handle is not None:
            try:
                self._gzip_handle.close()
            except Exception:
                pass
            self._gzip_handle = None

        if self._state == "TRANSFERRED":
            # Publisher owns lifecycle via marker (Phase II). Do nothing.
            return False
        if self._state == "SEALED":
            # Sealed but not transferred → orphan cleanup.
            self._delete_staging_safely()
            self._state = "ABORTED_BEFORE_TRANSFER"
            return False
        # state == OPEN
        if exc_type is not None:
            # Exception during OPEN.
            if len(self._events) > 0:
                # At least one event persisted → preserve evidence.
                self._diagnostic_abort(
                    failure_stage="OPEN_EXCEPTION",
                    failure_type=exc_type.__name__ if exc_type else "Unknown",
                    failure_message=str(exc_val) if exc_val else "",
                )
            else:
                self._delete_staging_safely()
                self._state = "ABORTED_BEFORE_TRANSFER"
            return False
        # Normal exit from OPEN without seal/transfer → orphan cleanup.
        self._delete_staging_safely()
        self._state = "ABORTED_BEFORE_TRANSFER"
        return False

    # ----- public API -----

    def append_event(self, event: dict[str, Any]) -> None:
        """Append a raw event to the staging file. Flushes + fsyncs each line
        to preserve INV-025 (raw persisted before transform).

        Raises RawEventPersistenceError on any I/O failure.
        Raises StagerStateError if not OPEN.
        """
        if self._state != "OPEN":
            raise StagerStateError(
                f"cannot append_event from state {self._state}"
            )
        if self._gzip_handle is None or self._staging_path is None:
            raise StagerStateError("stager not initialized — use 'with' statement")
        if not isinstance(event, dict):
            raise RawEventPersistenceError(
                f"event must be dict, got {type(event).__name__}"
            )
        missing = _RAW_EVENT_REQUIRED_FIELDS - set(event.keys())
        if missing:
            raise RawEventPersistenceError(
                f"event missing required fields {missing}"
            )
        line = (
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        try:
            self._gzip_handle.write(line)
            self._gzip_handle.flush()
            os.fsync(self._gzip_handle.fileno())
        except OSError as exc:
            # After at least one event has been persisted, raise the error
            # but DO NOT silently delete staging. The context manager will
            # trigger _diagnostic_abort because _events is non-empty.
            raise RawEventPersistenceError(
                f"failed to persist event to {self._staging_path}: {exc}"
            ) from exc
        self._events.append(event)
        cid = event.get("requested_condition_id", "")
        if cid:
            self._condition_ids.add(cid)

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def condition_ids(self) -> list[str]:
        return sorted(self._condition_ids)

    @property
    def state(self) -> StagerState:
        return self._state

    def seal(self) -> SealedRawArtifact:
        """D2 — Seal the stager and return a SealedRawArtifact descriptor.

        Definitive order:
          1. gzip flush
          2. gzip close (writes footer + CRC)
          3. open fd O_RDONLY
          4. fsync fd
          5. fstat fd → capture st_dev, st_ino, st_size
          6. close fd
          7. chmod 0o444
          8. fsync .pending directory
          9. strict reread (load_raw_events_strict)
          10. recalculate event_count, condition_ids, canonical_events_sha256
          11. recalculate file_sha256
          12. build SealedRawArtifact
          13. return

        Raises StagerStateError if not OPEN.
        Raises RawEventPersistenceError on any I/O failure.
        """
        if self._state != "OPEN":
            raise StagerStateError(f"cannot seal from state {self._state}")
        if self._gzip_handle is None or self._staging_path is None:
            raise StagerStateError("stager not initialized — use 'with' statement")

        # 1. flush
        try:
            self._gzip_handle.flush()
        except OSError as exc:
            raise RawEventPersistenceError(f"gzip flush failed: {exc}") from exc
        # 2. close (writes footer + CRC)
        try:
            self._gzip_handle.close()
        except OSError as exc:
            self._gzip_handle = None
            raise RawEventPersistenceError(f"gzip close failed: {exc}") from exc
        self._gzip_handle = None

        staging_path = self._staging_path

        # 3-6. open fd, fsync, fstat, close
        try:
            fd = os.open(str(staging_path), os.O_RDONLY)
        except OSError as exc:
            raise RawEventPersistenceError(
                f"cannot open staging for fsync: {exc}"
            ) from exc
        try:
            try:
                os.fsync(fd)
            except OSError as exc:
                raise RawEventPersistenceError(
                    f"fsync of staging failed: {exc}"
                ) from exc
            try:
                st = os.fstat(fd)
            except OSError as exc:
                raise RawEventPersistenceError(
                    f"fstat of staging failed: {exc}"
                ) from exc
        finally:
            os.close(fd)

        # 7. chmod 0o444
        try:
            os.chmod(staging_path, 0o444)
        except OSError as exc:
            raise RawEventPersistenceError(
                f"chmod 0o444 failed: {exc}"
            ) from exc

        # 8. fsync .pending directory
        pending_dir = staging_path.parent
        try:
            _dir_fsync(pending_dir)
        except OSError as exc:
            raise RawEventPersistenceError(
                f"fsync of .pending failed: {exc}"
            ) from exc

        # 9. strict reread
        try:
            disk_events = load_raw_events_strict(staging_path)
        except (ValueError, OSError, gzip.BadGzipFile) as exc:
            raise RawEventPersistenceError(
                f"strict reread of staging failed: {exc}"
            ) from exc

        # 10. recalculate from disk
        if len(disk_events) != len(self._events):
            raise RawEventPersistenceError(
                f"disk event count ({len(disk_events)}) != memory event count "
                f"({len(self._events)})"
            )
        disk_condition_ids: set[str] = set()
        for ev in disk_events:
            cid = ev.get("requested_condition_id", "")
            if cid:
                disk_condition_ids.add(cid)
        disk_canonical_sha = canonical_events_sha256(disk_events)

        # 11. recalculate file_sha256 from disk bytes
        try:
            file_bytes = staging_path.read_bytes()
        except OSError as exc:
            raise RawEventPersistenceError(
                f"cannot read staging bytes for sha256: {exc}"
            ) from exc
        file_sha = hashlib.sha256(file_bytes).hexdigest()

        # 12. build SealedRawArtifact
        safe_id = _safe_scan_id(self.scan_id)
        scan_id_hash = hashlib.sha256(self.scan_id.encode("utf-8")).hexdigest()[:12]
        final_name = f"raw_scan_{safe_id}_{scan_id_hash}.events.jsonl.gz"
        sealed_at = datetime.now(timezone.utc).isoformat()

        descriptor = SealedRawArtifact(
            version=1,
            staging_filename=staging_path.name,
            final_name=final_name,
            run_id=self.run_id,
            scan_id=self.scan_id,
            event_count=len(disk_events),
            condition_ids=tuple(sorted(disk_condition_ids)),
            file_sha256=file_sha,
            canonical_events_sha256=disk_canonical_sha,
            size_bytes=st.st_size,
            sealed_at=sealed_at,
            device_id=st.st_dev,
            inode=st.st_ino,
        )
        self._sealed_descriptor = descriptor
        self._state = "SEALED"
        return descriptor

    def transfer(self) -> RawArtifactTransfer:
        """D5, E5 — Single SEALED → TRANSFERRED transition.

        After this call, the stager's __exit__ will NOT delete the staging
        file. The marker durable (created in Phase II by publish_raw_scan)
        is the sole authority for lifecycle after this point.

        Raises StagerStateError if called before seal() or twice.
        """
        if self._state != "SEALED":
            raise StagerStateError(
                f"cannot transfer from state {self._state} — must be SEALED"
            )
        if self._transferred:
            raise StagerStateError("already transferred — second transfer rejected")
        if self._sealed_descriptor is None or self._staging_path is None:
            raise StagerStateError("internal: sealed descriptor missing")
        self._transferred = True
        self._ownership_token = str(uuid.uuid4())
        self._state = "TRANSFERRED"
        return RawArtifactTransfer(
            sealed=self._sealed_descriptor,
            ownership_token=self._ownership_token,
            staging_path=self._staging_path.resolve(),
        )

    # ----- internal helpers -----

    def _delete_staging_safely(self) -> None:
        if self._staging_path is None:
            return
        try:
            if self._staging_path.exists():
                # Re-chmod to writable if needed (seal may have set 0o444).
                try:
                    os.chmod(self._staging_path, 0o644)
                except OSError:
                    pass
                self._staging_path.unlink()
        except OSError:
            pass

    def _diagnostic_abort(
        self,
        failure_stage: str,
        failure_type: str,
        failure_message: str,
    ) -> None:
        """E4 — Move staging to .quarantine/ and write diagnostic JSON.

        Called when an error occurs AFTER at least one event has been
        persisted to staging. The staging file is preserved (moved, not
        deleted), and a diagnostic JSON is written alongside in .quarantine/.
        """
        if self._staging_path is None or not self._staging_path.exists():
            # Nothing to preserve; fall back to ordinary abort.
            self._state = "ABORTED_BEFORE_TRANSFER"
            return
        quarantine_dir = self.raw_dir / ".quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        # Compute staging hash + size BEFORE moving (best-effort).
        staging_sha: str | None = None
        staging_size: int | None = None
        try:
            staging_bytes = self._staging_path.read_bytes()
            staging_sha = hashlib.sha256(staging_bytes).hexdigest()
            staging_size = len(staging_bytes)
        except OSError:
            pass

        # Move staging to quarantine (non-replace: if destination exists,
        # append a unique suffix).
        staging_name = self._staging_path.name
        # Strip .tmp suffix for the quarantined name.
        base_name = staging_name
        if base_name.endswith(".tmp"):
            base_name = base_name[: -len(".tmp")]
        dest_name = f"{base_name}.{uuid.uuid4().hex[:8]}.quarantined"
        dest_path = quarantine_dir / dest_name
        while dest_path.exists():
            dest_name = f"{base_name}.{uuid.uuid4().hex[:8]}.quarantined"
            dest_path = quarantine_dir / dest_name
        try:
            # Re-chmod to writable so the rename succeeds even if seal ran.
            try:
                os.chmod(self._staging_path, 0o644)
            except OSError:
                pass
            os.rename(self._staging_path, dest_path)
            _dir_fsync(quarantine_dir)
        except OSError:
            # If rename fails, leave staging in place — evidence preserved
            # in .pending/. Diagnostic is still written.
            dest_path = self._staging_path

        # Build diagnostic.
        txn_uuid = str(uuid.uuid4())
        ownership_token = self._ownership_token or str(uuid.uuid4())
        diag_dict: dict[str, Any] = {
            "diagnostic_version": DIAGNOSTIC_SCHEMA_VERSION,
            "transaction_uuid": txn_uuid,
            "ownership_token": ownership_token,
            "diagnostic_created_at": datetime.now(timezone.utc).isoformat(),
            "triggering_state": self._state,
            "failure_stage": failure_stage,
            "failure_type": failure_type,
            "failure_message": failure_message,
            "staging_filename": staging_name,
            "staging_sha256": staging_sha,
            "staging_size_bytes": staging_size,
            "marker_filename": None,
            "marker_integrity_sha256": None,
            "events_appended_before_failure": len(self._events),
            "events_appended_total_expected": None,
            "recoverable": False,
        }
        integrity = compute_diagnostic_integrity_sha256(diag_dict)
        diag_dict["diagnostic_integrity_sha256"] = integrity
        diag = DiagnosticEvidence(
            diagnostic_version=diag_dict["diagnostic_version"],
            transaction_uuid=diag_dict["transaction_uuid"],
            ownership_token=diag_dict["ownership_token"],
            diagnostic_created_at=diag_dict["diagnostic_created_at"],
            triggering_state=diag_dict["triggering_state"],
            failure_stage=diag_dict["failure_stage"],
            failure_type=diag_dict["failure_type"],
            failure_message=diag_dict["failure_message"],
            staging_filename=diag_dict["staging_filename"],
            staging_sha256=diag_dict["staging_sha256"],
            staging_size_bytes=diag_dict["staging_size_bytes"],
            marker_filename=diag_dict["marker_filename"],
            marker_integrity_sha256=diag_dict["marker_integrity_sha256"],
            events_appended_before_failure=diag_dict["events_appended_before_failure"],
            events_appended_total_expected=diag_dict["events_appended_total_expected"],
            recoverable=diag_dict["recoverable"],
            diagnostic_integrity_sha256=integrity,
        )
        try:
            write_diagnostic_evidence(quarantine_dir, diag)
        except OSError:
            # Best-effort: state transition still happens.
            pass

        self._state = "ABORTED_WITH_DIAGNOSTIC_EVIDENCE"


# ═══════════════════════════════════════════════════════════════════════
# Section 9 — Eligibility state
# ═══════════════════════════════════════════════════════════════════════

ELIGIBILITY_FILENAME: Final[str] = ".eligibility_state.json"


@dataclass(frozen=True)
class EligibilityState:
    """D3 — Persisted eligibility state for INV-005.

    Fields:
      - schema_version: always ELIGIBILITY_SCHEMA_VERSION
      - first_eligible_scan_seen: bool
      - first_eligible_scan_id: str | None
      - first_persistible_data_api_request_at: str | None
      - state_sha256: 64-char hex integrity hash
    """
    schema_version: str
    first_eligible_scan_seen: bool
    first_eligible_scan_id: str | None
    first_persistible_data_api_request_at: str | None
    state_sha256: str


def _eligibility_state_to_dict(state: EligibilityState) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "first_eligible_scan_seen": state.first_eligible_scan_seen,
        "first_eligible_scan_id": state.first_eligible_scan_id,
        "first_persistible_data_api_request_at": state.first_persistible_data_api_request_at,
        "state_sha256": state.state_sha256,
    }


def read_eligibility_state(directory: Path) -> EligibilityState | None:
    """D3 — Read eligibility state from `directory / ELIGIBILITY_FILENAME`.

    Returns:
      - None if the file is absent (means first_eligible_scan_seen = False).
      - EligibilityState if the file is valid.

    Raises EligibilityCorruptionError if the file is present but corrupt
    (invalid JSON, hash mismatch, schema invalid). This is fail-closed —
    there is NO silent fallback to false.
    """
    path = directory / ELIGIBILITY_FILENAME
    if not path.exists():
        return None
    reject_symlink(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EligibilityCorruptionError(
            f"cannot read eligibility file {path}: {exc}"
        ) from exc
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EligibilityCorruptionError(
            f"eligibility file {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(obj, dict):
        raise EligibilityCorruptionError(
            f"eligibility file root must be object, got {type(obj).__name__}"
        )
    # Required keys
    required = {
        "schema_version", "first_eligible_scan_seen",
        "first_eligible_scan_id", "first_persistible_data_api_request_at",
        "state_sha256",
    }
    missing = required - set(obj.keys())
    if missing:
        raise EligibilityCorruptionError(
            f"eligibility file missing keys {missing}"
        )
    if obj["schema_version"] != ELIGIBILITY_SCHEMA_VERSION:
        raise EligibilityCorruptionError(
            f"eligibility schema_version mismatch: got {obj['schema_version']!r}"
        )
    if not isinstance(obj["first_eligible_scan_seen"], bool):
        raise EligibilityCorruptionError(
            "first_eligible_scan_seen must be bool, got "
            f"{type(obj['first_eligible_scan_seen']).__name__}"
        )
    if not isinstance(obj["state_sha256"], str) or not _HEX64_RE.match(obj["state_sha256"]):
        raise EligibilityCorruptionError(
            f"state_sha256 must be 64-char hex, got {obj['state_sha256']!r}"
        )
    # Integrity check
    recomputed = compute_eligibility_integrity_sha256(obj)
    if recomputed != obj["state_sha256"]:
        raise EligibilityCorruptionError(
            f"eligibility state_sha256 mismatch: computed={recomputed} "
            f"stored={obj['state_sha256']}"
        )
    return EligibilityState(
        schema_version=obj["schema_version"],
        first_eligible_scan_seen=obj["first_eligible_scan_seen"],
        first_eligible_scan_id=obj["first_eligible_scan_id"],
        first_persistible_data_api_request_at=obj["first_persistible_data_api_request_at"],
        state_sha256=obj["state_sha256"],
    )


def write_eligibility_state(
    directory: Path,
    first_eligible_scan_seen: bool,
    first_eligible_scan_id: str | None = None,
    first_persistible_data_api_request_at: str | None = None,
) -> EligibilityState:
    """D3 — Atomically write eligibility state.

    Monotonicity: if `first_eligible_scan_seen=True` is already persisted,
    an attempt to write `first_eligible_scan_seen=False` raises
    EligibilityMonotonicityError.

    Atomic write: O_CREAT|O_EXCL temp + fsync + os.rename + dir fsync.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ELIGIBILITY_FILENAME

    # Monotonicity check
    existing = None
    if path.exists():
        try:
            existing = read_eligibility_state(directory)
        except EligibilityCorruptionError:
            # If existing is corrupt, we cannot safely check monotonicity.
            # Re-raise: caller must decide (we do NOT silently overwrite).
            raise
    if (
        existing is not None
        and existing.first_eligible_scan_seen
        and not first_eligible_scan_seen
    ):
        raise EligibilityMonotonicityError(
            "cannot revert first_eligible_scan_seen from true to false"
        )

    body: dict[str, Any] = {
        "schema_version": ELIGIBILITY_SCHEMA_VERSION,
        "first_eligible_scan_seen": first_eligible_scan_seen,
        "first_eligible_scan_id": first_eligible_scan_id,
        "first_persistible_data_api_request_at": first_persistible_data_api_request_at,
    }
    integrity = compute_eligibility_integrity_sha256(body)
    body["state_sha256"] = integrity

    canonical = canonical_json_bytes(body)
    temp_name = f"{ELIGIBILITY_FILENAME}.tmp.{uuid.uuid4().hex}"
    temp_path = directory / temp_name
    fd = os.open(
        str(temp_path),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o644,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
    os.rename(temp_path, path)
    _dir_fsync(directory)
    return EligibilityState(
        schema_version=body["schema_version"],
        first_eligible_scan_seen=body["first_eligible_scan_seen"],
        first_eligible_scan_id=body["first_eligible_scan_id"],
        first_persistible_data_api_request_at=body["first_persistible_data_api_request_at"],
        state_sha256=integrity,
    )


# ═══════════════════════════════════════════════════════════════════════
# Section 10 — Marker filename helper
# ═══════════════════════════════════════════════════════════════════════

def marker_filename(prefix: str, sequence: int, transaction_uuid: str) -> str:
    """Compute the canonical marker filename.

    Format: {prefix}_txn_{sequence:06d}_{transaction_uuid}.marker
    """
    if not isinstance(sequence, int) or sequence < 0:
        raise ValueError(f"sequence must be non-negative int, got {sequence!r}")
    return f"{prefix}_txn_{sequence:06d}_{transaction_uuid}.marker"
