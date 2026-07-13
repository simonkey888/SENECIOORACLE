"""
SENECIO H-011 V3 — Raw Artifact Transaction Core Primitives (Phase I, F1-F9 hardened).

Implements the foundational layer of the E1-E7 design with F1-F9 hardening:

  F1: Validate marker BEFORE any filesystem operation (prepare_validated_marker_bytes)
  F2: Exact marker↔candidate binding via MarkerValidationPolicy
  F3: Marker ops under lock; update uses renameat2(RENAME_EXCHANGE)
  F4: Path-safe operations with dir_fd, O_NOFOLLOW, O_DIRECTORY
  F5: Authoritative RawChainLockGuard with GuardRecord registry
  F6: Stager fail-closed lifecycle with _fail_with_diagnostic
  F7: Durable diagnostic evidence via hardlink (no rename loop)
  F8: Eligibility monotonic under lock; no unlocked write API
  F9: Strict validators (UUID4, ISO 8601 UTC, device/inode range, Literal status)

NOT implemented (Phase II+):
  - publish_raw_scan() full pipeline
  - recovery state machine
  - real artifact/sidecar/manifest publication
  - integration with run_scan_v3
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import ctypes.util
import errno
import fcntl
import gzip
import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Literal, NoReturn


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
    """Canonical JSON encoding (deterministic, UTF-8, no NaN/Infinity)."""
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
    """Canonical JSON bytes of a manifest entry EXCLUDING manifest_hash."""
    body = {k: v for k, v in entry.items() if k != "manifest_hash"}
    return canonical_json_bytes(body)


def compute_manifest_hash(entry: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of entry EXCLUDING manifest_hash."""
    return hashlib.sha256(manifest_hash_input_bytes(entry)).hexdigest()


def canonical_manifest_file_bytes(entry: dict[str, Any]) -> bytes:
    """Canonical JSON bytes of entry INCLUDING manifest_hash."""
    return canonical_json_bytes(entry)


def compute_marker_integrity_sha256(marker: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of marker EXCLUDING marker_integrity_sha256."""
    body = {k: v for k, v in marker.items() if k != "marker_integrity_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def compute_eligibility_integrity_sha256(state: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of eligibility state EXCLUDING state_sha256."""
    body = {k: v for k, v in state.items() if k != "state_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def compute_diagnostic_integrity_sha256(diag: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON of diagnostic EXCLUDING diagnostic_integrity_sha256."""
    body = {k: v for k, v in diag.items() if k != "diagnostic_integrity_sha256"}
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

MarkerResolution = Literal["ACTIVE", "BLOCKED", "QUARANTINED"]

StagerState = Literal[
    "OPEN",
    "SEALED",
    "TRANSFERRED",
    "ABORTED_BEFORE_TRANSFER",
    "ABORTED_WITH_DIAGNOSTIC_EVIDENCE",
    "BLOCKED_DIAGNOSTIC_PERSISTENCE",
]

PublishResultStatus = Literal["PUBLISHED", "RECOVERABLE_ERROR", "BLOCKED"]

EvidenceLocation = Literal["PENDING", "QUARANTINE"]

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
    "BLOCKED_DIAGNOSTIC_PERSISTENCE",
})
PUBLISH_RESULT_STATUSES: Final[frozenset[str]] = frozenset({
    "PUBLISHED", "RECOVERABLE_ERROR", "BLOCKED",
})


class RawTransactionError(Exception):
    """Base class for the raw transaction subsystem."""


class RawEventPersistenceError(RawTransactionError):
    """Raised when appending or fsyncing a raw event to staging fails."""


class RawArtifactTransactionError(RawTransactionError):
    """Raised inside the publish pipeline (Phase II)."""


class IdentityCollisionError(RawTransactionError):
    """Raised when run_id/scan_id collide with an existing manifest entry."""


class MarkerValidationError(RawTransactionError):
    """Raised when a marker fails schema, type, or integrity validation."""


class MarkerIntegrityError(MarkerValidationError):
    """Raised when marker_integrity_sha256 does not match."""


class CandidateManifestMismatchError(MarkerValidationError):
    """Raised when the E7 five-check candidate manifest validation fails."""


class MarkerCandidateBindingError(MarkerValidationError):
    """Raised when marker fields do not exactly match candidate_manifest fields (F2)."""


class EligibilityCorruptionError(RawTransactionError):
    """Raised when .eligibility_state.json is present but corrupt."""


class EligibilityMonotonicityError(RawTransactionError):
    """Raised when an attempt is made to revert first_eligible_scan_seen."""


class LockAcquisitionError(RawTransactionError):
    """Raised when fcntl.flock fails."""


class NestedLockingError(RawTransactionError):
    """Raised when a second lock is attempted for the same (directory, prefix)."""


class GuardValidationError(RawTransactionError):
    """Raised when a guard fails validation."""


class StagerStateError(RawTransactionError):
    """Raised when a RawScanStager method is called from the wrong state."""


class PathSafetyError(RawTransactionError):
    """Raised when a path contains forbidden components."""


class AtomicMarkerUpdateUnsupportedError(RawTransactionError):
    """Raised when renameat2(RENAME_EXCHANGE) is not available (F3)."""


class DiagnosticPersistenceError(RawTransactionError):
    """Raised when diagnostic evidence cannot be persisted (F7)."""



# ═══════════════════════════════════════════════════════════════════════
# Section 3 — Path safety with dir_fd (F4)
# ═══════════════════════════════════════════════════════════════════════

_FORBIDDEN_NAME_PATTERNS: Final[tuple[str, ...]] = ("/", "\\", "..")


def validate_bare_filename(name: str) -> None:
    """Validate that `name` is a bare filename (no path components)."""
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
    parts = Path(name).parts
    if len(parts) != 1:
        raise PathSafetyError(
            f"filename has multiple path components: {name!r} -> {parts}"
        )


def open_trusted_dir(directory: Path) -> int:
    """Open a directory with O_RDONLY | O_DIRECTORY | O_NOFOLLOW.

    Returns the fd. Raises PathSafetyError if the path is a symlink or not a
    directory. Raises OSError if the directory does not exist.

    F4: This is the canonical way to open a trusted directory. All subsequent
    file operations should use dir_fd relative to this fd.
    """
    fd = os.open(
        str(directory),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    return fd


def validate_real_directory(path: Path) -> None:
    """Validate that `path` is a real directory (not a symlink).

    F4: Uses os.lstat to avoid following symlinks. Raises PathSafetyError if
    the path is a symlink, does not exist, or is not a directory.
    """
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        raise PathSafetyError(f"directory does not exist: {path}")
    except OSError as exc:
        raise PathSafetyError(f"cannot lstat {path}: {exc}") from exc
    import stat as statmod
    if statmod.S_ISLNK(st.st_mode):
        raise PathSafetyError(f"symlink forbidden for directory: {path}")
    if not statmod.S_ISDIR(st.st_mode):
        raise PathSafetyError(f"not a directory: {path}")


def open_file_no_follow(dir_fd: int, name: str, flags: int, mode: int = 0o644) -> int:
    """Open a file relative to dir_fd with O_NOFOLLOW.

    F4: All file opens must use O_NOFOLLOW to reject symlinks.
    """
    validate_bare_filename(name)
    full_flags = flags | os.O_NOFOLLOW
    return os.open(name, full_flags, mode, dir_fd=dir_fd)


def lstat_file(dir_fd: int, name: str) -> os.stat_result:
    """os.lstat a file relative to dir_fd, without following symlinks."""
    validate_bare_filename(name)
    return os.lstat(name, dir_fd=dir_fd)


def reject_symlink_path(path: Path) -> None:
    """Raise PathSafetyError if `path` is a symlink (by name)."""
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PathSafetyError(f"cannot lstat {path}: {exc}") from exc
    import stat as statmod
    if statmod.S_ISLNK(st.st_mode):
        raise PathSafetyError(f"symlink forbidden: {path}")


# ═══════════════════════════════════════════════════════════════════════
# Section 4 — Marker schema v2 with F2 binding and F9 strict validators
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

# Required fields in candidate_manifest (F9: exact types and fields)
REQUIRED_CANDIDATE_MANIFEST_FIELDS: Final[tuple[str, ...]] = (
    "sequence",
    "run_id",
    "scan_id",
    "filename",
    "file_sha256",
    "canonical_events_sha256",
    "event_count",
    "condition_ids",
    "previous_manifest_hash",
    "created_at",
    "manifest_hash",
)


@dataclass(frozen=True)
class MarkerValidationPolicy:
    """F2 — Policy for marker validation.

    Attributes:
        manifest_prefix: prefix for marker/manifest filenames (e.g., "manifest")
        artifact_filename_pattern: compiled regex that final_name must match
    """
    manifest_prefix: str
    artifact_filename_pattern: re.Pattern[str]


# Default pattern for raw scan artifacts
DEFAULT_ARTIFACT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^raw_scan_[A-Za-z0-9_.-]+_[0-9a-f]{12}\.events\.jsonl\.gz$"
)

DEFAULT_MARKER_POLICY: Final[MarkerValidationPolicy] = MarkerValidationPolicy(
    manifest_prefix="manifest",
    artifact_filename_pattern=DEFAULT_ARTIFACT_PATTERN,
)


# ─── F9: Strict validators ───

def _validate_hex64(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    if not _HEX64_RE.match(value):
        raise MarkerValidationError(
            f"{field_name} must be 64-char lowercase hex, got {value!r}"
        )


def _validate_uuid4_strict(value: Any, field_name: str) -> None:
    """F9 — Use uuid.UUID() and check version == 4."""
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    try:
        u = uuid.UUID(value)
    except ValueError as exc:
        raise MarkerValidationError(
            f"{field_name} invalid UUID: {value!r}: {exc}"
        ) from exc
    if u.version != 4:
        raise MarkerValidationError(
            f"{field_name} must be UUID version 4, got version {u.version}: {value!r}"
        )


def _validate_iso8601_utc_strict(value: Any, field_name: str) -> None:
    """F9 — Strict ISO 8601 UTC validation.

    Rejects: non-UTC offsets, impossible dates, timestamps without timezone.
    """
    if not isinstance(value, str):
        raise MarkerValidationError(
            f"{field_name} must be str, got {type(value).__name__}"
        )
    # Quick regex check first
    if not _ISO_8601_RE.match(value):
        raise MarkerValidationError(
            f"{field_name} must match ISO 8601 pattern, got {value!r}"
        )
    # Parse and verify UTC offset
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MarkerValidationError(
            f"{field_name} invalid ISO 8601 date: {value!r}: {exc}"
        ) from exc
    offset = parsed.utcoffset()
    if offset is None:
        raise MarkerValidationError(
            f"{field_name} missing timezone: {value!r}"
        )
    if offset != timedelta(0):
        raise MarkerValidationError(
            f"{field_name} non-UTC offset {offset}: {value!r}"
        )


def _validate_device_id(value: Any) -> None:
    """F9 — device_id must be a valid unsigned 64-bit integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise MarkerValidationError(
            f"device_id must be int, got {type(value).__name__}"
        )
    if value < 0:
        raise MarkerValidationError(
            f"device_id must be non-negative, got {value}"
        )
    if value > 2**64 - 1:
        raise MarkerValidationError(
            f"device_id exceeds 64-bit range: {value}"
        )


def _validate_inode(value: Any) -> None:
    """F9 — inode must be a valid unsigned 64-bit integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise MarkerValidationError(
            f"inode must be int, got {type(value).__name__}"
        )
    if value < 0:
        raise MarkerValidationError(
            f"inode must be non-negative, got {value}"
        )
    if value > 2**64 - 1:
        raise MarkerValidationError(
            f"inode exceeds 64-bit range: {value}"
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
    """Parse marker bytes into a dict. Strict JSON."""
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


def _validate_candidate_manifest_fields(cm: dict[str, Any]) -> None:
    """F9 — Validate exact types and fields of candidate_manifest."""
    if not isinstance(cm, dict):
        raise MarkerValidationError(
            f"candidate_manifest must be dict, got {type(cm).__name__}"
        )
    missing = [f for f in REQUIRED_CANDIDATE_MANIFEST_FIELDS if f not in cm]
    if missing:
        raise MarkerValidationError(
            f"candidate_manifest missing required fields: {missing}"
        )
    # Check for unknown fields
    allowed = set(REQUIRED_CANDIDATE_MANIFEST_FIELDS)
    unknown = [k for k in cm.keys() if k not in allowed]
    if unknown:
        raise MarkerValidationError(
            f"candidate_manifest has unknown fields: {unknown}"
        )
    # Type checks
    if not isinstance(cm["sequence"], int) or isinstance(cm["sequence"], bool):
        raise MarkerValidationError("candidate_manifest.sequence must be int")
    if cm["sequence"] < 0:
        raise MarkerValidationError("candidate_manifest.sequence must be non-negative")
    _validate_non_empty_str(cm["run_id"], "candidate_manifest.run_id")
    _validate_non_empty_str(cm["scan_id"], "candidate_manifest.scan_id")
    _validate_bare_filename_field(cm["filename"], "candidate_manifest.filename")
    _validate_hex64(cm["file_sha256"], "candidate_manifest.file_sha256")
    _validate_hex64(cm["canonical_events_sha256"], "candidate_manifest.canonical_events_sha256")
    if not isinstance(cm["event_count"], int) or isinstance(cm["event_count"], bool):
        raise MarkerValidationError("candidate_manifest.event_count must be int")
    if cm["event_count"] < 0:
        raise MarkerValidationError("candidate_manifest.event_count must be non-negative")
    if not isinstance(cm["condition_ids"], list):
        raise MarkerValidationError("candidate_manifest.condition_ids must be list")
    for i, c in enumerate(cm["condition_ids"]):
        if not isinstance(c, str):
            raise MarkerValidationError(
                f"candidate_manifest.condition_ids[{i}] must be str"
            )
    # previous_manifest_hash: hex64 or null
    pmh = cm["previous_manifest_hash"]
    if pmh is not None:
        if not isinstance(pmh, str):
            raise MarkerValidationError(
                "candidate_manifest.previous_manifest_hash must be str or null"
            )
        if not _HEX64_RE.match(pmh):
            raise MarkerValidationError(
                f"candidate_manifest.previous_manifest_hash must be 64-char hex or null, got {pmh!r}"
            )
    _validate_iso8601_utc_strict(cm["created_at"], "candidate_manifest.created_at")
    _validate_hex64(cm["manifest_hash"], "candidate_manifest.manifest_hash")


def _validate_marker_candidate_binding(marker: dict[str, Any], policy: MarkerValidationPolicy) -> None:
    """F2 — Exact binding between marker fields and candidate_manifest fields."""
    cm = marker["candidate_manifest"]

    # Validate candidate_manifest structure first (F9)
    _validate_candidate_manifest_fields(cm)

    # Exact field binding
    bindings: list[tuple[str, Any, Any, str]] = [
        ("sequence", cm["sequence"], marker["sequence"], "candidate_manifest.sequence"),
        ("run_id", cm["run_id"], marker["run_id"], "candidate_manifest.run_id"),
        ("scan_id", cm["scan_id"], marker["scan_id"], "candidate_manifest.scan_id"),
        ("filename", cm["filename"], marker["final_name"], "candidate_manifest.filename vs marker.final_name"),
        ("file_sha256", cm["file_sha256"], marker["file_sha256"], "candidate_manifest.file_sha256 vs marker.file_sha256"),
        ("canonical_events_sha256", cm["canonical_events_sha256"], marker["canonical_events_sha256"],
         "candidate_manifest.canonical_events_sha256 vs marker.canonical_events_sha256"),
        ("event_count", cm["event_count"], marker["event_count"],
         "candidate_manifest.event_count vs marker.event_count"),
        ("condition_ids", cm["condition_ids"], marker["condition_ids"],
         "candidate_manifest.condition_ids vs marker.condition_ids"),
        ("previous_manifest_hash", cm["previous_manifest_hash"], marker["previous_manifest_hash"],
         "candidate_manifest.previous_manifest_hash vs marker.previous_manifest_hash"),
        ("created_at", cm["created_at"], marker["manifest_created_at"],
         "candidate_manifest.created_at vs marker.manifest_created_at"),
    ]
    for field_name, cm_val, marker_val, label in bindings:
        if cm_val != marker_val:
            raise MarkerCandidateBindingError(
                f"{label} mismatch: candidate={cm_val!r} marker={marker_val!r}"
            )

    # sidecar_name == final_name + ".sha256"
    expected_sidecar = marker["final_name"] + ".sha256"
    if marker["sidecar_name"] != expected_sidecar:
        raise MarkerCandidateBindingError(
            f"sidecar_name must be final_name + '.sha256': "
            f"expected {expected_sidecar!r}, got {marker['sidecar_name']!r}"
        )

    # manifest_name == f"{prefix}_{sequence:06d}.json"
    expected_manifest_name = f"{policy.manifest_prefix}_{marker['sequence']:06d}.json"
    if marker["manifest_name"] != expected_manifest_name:
        raise MarkerCandidateBindingError(
            f"manifest_name must be '{policy.manifest_prefix}_{{sequence:06d}}.json': "
            f"expected {expected_manifest_name!r}, got {marker['manifest_name']!r}"
        )

    # final_name matches policy.artifact_filename_pattern
    if not policy.artifact_filename_pattern.match(marker["final_name"]):
        raise MarkerCandidateBindingError(
            f"final_name does not match artifact_filename_pattern: {marker['final_name']!r}"
        )

    # condition_ids sorted and deduplicated
    cid = marker["condition_ids"]
    if cid != sorted(set(cid)):
        raise MarkerCandidateBindingError(
            f"condition_ids must be sorted and deduplicated, got {cid}"
        )

    # sequence == 0 → previous_manifest_hash is null
    if marker["sequence"] == 0:
        if marker["previous_manifest_hash"] is not None:
            raise MarkerCandidateBindingError(
                f"sequence=0 requires previous_manifest_hash=null, got {marker['previous_manifest_hash']!r}"
            )
    else:
        # sequence > 0 → previous_manifest_hash is 64-char hex
        pmh = marker["previous_manifest_hash"]
        if not isinstance(pmh, str) or not _HEX64_RE.match(pmh):
            raise MarkerCandidateBindingError(
                f"sequence>0 requires previous_manifest_hash as 64-char hex, got {pmh!r}"
            )


def validate_marker(marker: dict[str, Any], policy: MarkerValidationPolicy) -> None:
    """Validate marker schema, types, integrity hash, E7 candidate equivalence,
    and F2 exact marker↔candidate binding.

    Raises MarkerValidationError (or subclass) on any failure.
    """
    if not isinstance(marker, dict):
        raise MarkerValidationError(
            f"marker must be dict, got {type(marker).__name__}"
        )
    if not isinstance(policy, MarkerValidationPolicy):
        raise MarkerValidationError(
            f"policy must be MarkerValidationPolicy, got {type(policy).__name__}"
        )

    # Required fields present
    missing = [f for f in REQUIRED_MARKER_FIELDS if f not in marker]
    if missing:
        raise MarkerValidationError(
            f"marker missing required fields: {missing}"
        )

    # Unknown top-level keys
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

    # F9: UUID4 strict validation
    _validate_uuid4_strict(marker["transaction_uuid"], "transaction_uuid")
    _validate_uuid4_strict(marker["ownership_token"], "ownership_token")

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

    _validate_non_empty_str(marker["run_id"], "run_id")
    _validate_non_empty_str(marker["scan_id"], "scan_id")

    _validate_bare_filename_field(marker["staging_filename"], "staging_filename")
    _validate_bare_filename_field(marker["final_name"], "final_name")
    _validate_bare_filename_field(marker["sidecar_name"], "sidecar_name")
    _validate_bare_filename_field(marker["manifest_name"], "manifest_name")

    if not marker["staging_filename"].endswith(".tmp"):
        raise MarkerValidationError(
            f"staging_filename must end with .tmp, got {marker['staging_filename']!r}"
        )
    if not marker["sidecar_name"].endswith(".sha256"):
        raise MarkerValidationError(
            f"sidecar_name must end with .sha256, got {marker['sidecar_name']!r}"
        )

    # F9: device_id and inode with valid range
    _validate_device_id(marker["device_id"])
    _validate_inode(marker["inode"])

    # size_bytes
    if not isinstance(marker["size_bytes"], int) or isinstance(marker["size_bytes"], bool):
        raise MarkerValidationError(
            f"size_bytes must be int, got {type(marker['size_bytes']).__name__}"
        )
    if marker["size_bytes"] < 0:
        raise MarkerValidationError(
            f"size_bytes must be >= 0, got {marker['size_bytes']}"
        )

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

    # previous_manifest_hash
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

    # candidate_manifest — basic type check here; full validation in F2 binding
    cm = marker["candidate_manifest"]
    if not isinstance(cm, dict):
        raise MarkerValidationError(
            f"candidate_manifest must be dict, got {type(cm).__name__}"
        )

    # candidate_manifest_bytes_base64
    if not isinstance(marker["candidate_manifest_bytes_base64"], str):
        raise MarkerValidationError(
            "candidate_manifest_bytes_base64 must be str, got "
            f"{type(marker['candidate_manifest_bytes_base64']).__name__}"
        )

    # F9: manifest_created_at strict ISO 8601 UTC
    _validate_iso8601_utc_strict(marker["manifest_created_at"], "manifest_created_at")

    # E3: recoverable REQUIRED boolean
    rec = marker["recoverable"]
    if not isinstance(rec, bool):
        raise MarkerValidationError(
            f"recoverable must be bool (REQUIRED, E3), got {type(rec).__name__}: {rec!r}"
        )

    # Optional fields
    for f in OPTIONAL_MARKER_FIELDS:
        v = marker.get(f)
        if v is not None and not isinstance(v, str):
            raise MarkerValidationError(
                f"{f} must be str or null, got {type(v).__name__}"
            )

    # E3: marker_integrity_sha256 verification
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

    # F2 — exact marker↔candidate binding
    _validate_marker_candidate_binding(marker, policy)


def validate_candidate_manifest_exact(marker: dict[str, Any]) -> list[str]:
    """E7 — five-check candidate manifest validation. Returns list of errors."""
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
        return errors

    # Check 2: SHA-256 of decoded bytes must match stored hash
    computed_sha = hashlib.sha256(decoded).hexdigest()
    if computed_sha != marker.get("candidate_manifest_bytes_sha256"):
        errors.append(
            f"candidate_manifest_bytes_sha256 mismatch: "
            f"computed={computed_sha} stored={marker.get('candidate_manifest_bytes_sha256')}"
        )

    # Check 3: JSON-decoded bytes must equal candidate_manifest dict
    try:
        decoded_dict = json.loads(decoded)
    except json.JSONDecodeError as exc:
        errors.append(f"json decode of base64 bytes failed: {exc}")
        return errors
    if decoded_dict != marker.get("candidate_manifest"):
        errors.append(
            "candidate_manifest dict != decoded base64 bytes"
        )

    # Check 4: decoded bytes must equal canonical_manifest_file_bytes
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

    # Check 5: compute_manifest_hash must equal stored manifest_hash
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
# Section 5 — Marker persistence (F1, F3)
# ═══════════════════════════════════════════════════════════════════════

# F3 — Load renameat2 from libc
_RENAME_EXCHANGE: Final[int] = 2


def _load_renameat2():
    """Try to load renameat2 from libc. Returns function or None."""
    try:
        libc_path = ctypes.util.find_library("c")
        if libc_path is None:
            return None
        libc = ctypes.CDLL(libc_path, use_errno=True)
        if not hasattr(libc, "renameat2"):
            return None
        func = libc.renameat2
        func.restype = ctypes.c_int
        func.argtypes = [
            ctypes.c_int,    # olddirfd
            ctypes.c_char_p, # oldpath
            ctypes.c_int,    # newdirfd
            ctypes.c_char_p, # newpath
            ctypes.c_uint,   # flags
        ]
        return func
    except (OSError, AttributeError):
        return None


_renameat2_func = _load_renameat2()


def _renameat2_exchange(dir_fd: int, old_name: str, new_name: str) -> None:
    """Call renameat2 with RENAME_EXCHANGE flag.

    F3: Uses libc.renameat2. Raises AtomicMarkerUpdateUnsupportedError if
    renameat2 is not available, or OSError on syscall failure.
    """
    if _renameat2_func is None:
        raise AtomicMarkerUpdateUnsupportedError(
            "renameat2 is not available on this platform — cannot perform "
            "atomic marker update via RENAME_EXCHANGE"
        )
    ret = _renameat2_func(
        dir_fd,
        old_name.encode("utf-8"),
        dir_fd,
        new_name.encode("utf-8"),
        _RENAME_EXCHANGE,
    )
    if ret != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), old_name)


def _dir_fsync(directory: Path) -> None:
    """fsync a directory by opening it O_RDONLY | O_DIRECTORY | O_NOFOLLOW."""
    fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_validated_marker_bytes(
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy,
) -> bytes:
    """F1 — Prepare canonical marker bytes with validation BEFORE any FS op.

    1. Copy the body, remove any existing marker_integrity_sha256.
    2. Compute and inject marker_integrity_sha256.
    3. Validate the complete marker (schema, types, integrity, E7, F2 binding).
    4. Return canonical JSON bytes.

    An invalid marker NEVER touches disk — not even as a temp file.
    """
    body = dict(marker_body)
    body.pop("marker_integrity_sha256", None)
    body["marker_integrity_sha256"] = compute_marker_integrity_sha256(body)
    validate_marker(body, policy=policy)
    return canonical_json_bytes(body)


def create_marker_no_replace_under_lock(
    guard: "RawChainLockGuard",
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy,
) -> Path:
    """F1, F3 — Create a marker under lock. Refuses to replace existing.

    1. assert_guard_valid(guard, directory, policy.manifest_prefix)
    2. prepare_validated_marker_bytes(marker_body, policy) — validate BEFORE any FS op
    3. Open directory with O_NOFOLLOW | O_DIRECTORY
    4. Check marker doesn't exist (O_NOFOLLOW open)
    5. Write temp (O_CREAT | O_EXCL | O_WRONLY), fsync
    6. os.link(temp, marker) — non-replace
    7. unlink temp name
    8. fsync directory
    """
    assert_guard_valid(guard, directory, policy.manifest_prefix)
    validate_bare_filename(marker_name)

    # F1: Validate BEFORE any filesystem operation
    canonical_bytes = prepare_validated_marker_bytes(marker_body, policy)

    dir_fd = os.open(
        str(directory),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        # Check marker doesn't exist (O_NOFOLLOW)
        try:
            existing_fd = os.open(
                marker_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd
            )
            os.close(existing_fd)
            raise FileExistsError(
                f"marker already exists: {marker_name} — use update_existing_marker_atomic_under_lock"
            )
        except FileNotFoundError:
            pass  # Good — marker doesn't exist
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PathSafetyError(
                    f"existing marker path is a symlink: {marker_name}"
                ) from exc
            raise

        # Write temp
        temp_name = f"{marker_name}.tmp.{uuid.uuid4().hex}"
        temp_fd = os.open(
            temp_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                f.write(canonical_bytes)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise

        # Non-replace placement: os.link, NOT os.rename
        try:
            os.link(temp_name, marker_name,
                    src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except FileExistsError:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass

        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    return directory / marker_name


def update_existing_marker_atomic_under_lock(
    guard: "RawChainLockGuard",
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy,
) -> Path:
    """F1, F3 — Update an existing marker atomically via renameat2(RENAME_EXCHANGE).

    Sequence (F3):
    1. assert_guard_valid
    2. prepare_validated_marker_bytes — validate BEFORE any FS op
    3. Open directory with O_NOFOLLOW | O_DIRECTORY
    4. Open existing marker with O_NOFOLLOW, capture inode/dev
    5. Write temp (O_CREAT | O_EXCL | O_WRONLY), fsync
    6. renameat2(temp, marker, RENAME_EXCHANGE)
    7. Verify temp now has the old marker's inode/dev
    8. unlink temp (now contains old marker)
    9. fsync directory

    Raises AtomicMarkerUpdateUnsupportedError if renameat2 is not available.
    Raises FileNotFoundError if marker does not exist.
    """
    assert_guard_valid(guard, directory, policy.manifest_prefix)
    validate_bare_filename(marker_name)

    # F1: Validate BEFORE any filesystem operation
    canonical_bytes = prepare_validated_marker_bytes(marker_body, policy)

    dir_fd = os.open(
        str(directory),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        # Open existing marker, capture inode/dev
        try:
            existing_fd = os.open(
                marker_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"marker does not exist: {marker_name} — use create_marker_no_replace_under_lock"
            ) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PathSafetyError(
                    f"existing marker is a symlink: {marker_name}"
                ) from exc
            raise

        try:
            existing_stat = os.fstat(existing_fd)
        finally:
            os.close(existing_fd)

        # Write temp
        temp_name = f"{marker_name}.tmp.{uuid.uuid4().hex}"
        temp_fd = os.open(
            temp_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                f.write(canonical_bytes)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise

        # F3: RENAME_EXCHANGE temp ↔ marker
        try:
            _renameat2_exchange(dir_fd, temp_name, marker_name)
        except AtomicMarkerUpdateUnsupportedError:
            # Clean up temp and re-raise
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
        except OSError as exc:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise AtomicMarkerUpdateUnsupportedError(
                f"renameat2 RENAME_EXCHANGE failed: {exc}. "
                f"Temp cleaned up. No silent residue."
            ) from exc

        # Verify temp now contains the OLD marker (inode/dev match)
        verify_fd = os.open(
            temp_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
        try:
            verify_stat = os.fstat(verify_fd)
        finally:
            os.close(verify_fd)

        if verify_stat.st_dev != existing_stat.st_dev or verify_stat.st_ino != existing_stat.st_ino:
            # Inode mismatch — something went wrong. Do NOT unlink temp.
            raise AtomicMarkerUpdateUnsupportedError(
                f"RENAME_EXCHANGE verification failed: temp inode/dev mismatch. "
                f"Expected dev={existing_stat.st_dev} ino={existing_stat.st_ino}, "
                f"got dev={verify_stat.st_dev} ino={verify_stat.st_ino}. "
                f"Temp file left at {temp_name} for inspection."
            )

        # unlink temp (now contains old marker)
        os.unlink(temp_name, dir_fd=dir_fd)

        # fsync directory
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    return directory / marker_name


# ═══════════════════════════════════════════════════════════════════════
# Section 6 — Locking with authoritative GuardRecord registry (F5)
# ═══════════════════════════════════════════════════════════════════════

import stat as _statmod


@dataclass(frozen=True)
class GuardRecord:
    """F5 — Registry record for an active guard.

    Stores all identity attributes of the guard so that assert_guard_valid
    can detect: manually constructed guards, copied tokens, closed/reused fds,
    replaced lock paths, and thread races.
    """
    guard: "RawChainLockGuard"
    pid: int
    directory: Path
    prefix: str
    lock_fd: int
    st_dev: int
    st_ino: int
    lock_path: Path
    token: str


_ACTIVE_GUARDS_LOCK = threading.Lock()
_ACTIVE_GUARDS: dict[str, GuardRecord] = {}


@dataclass(frozen=True)
class RawChainLockGuard:
    """F5 — Proof that the caller holds the raw chain flock.

    Constructed exclusively by RawChainLock.acquire(). The guard carries the
    open lock_fd; the lock is released when close() is called. The guard
    object itself is the proof of holding the lock — there is no thread-local
    fallback. The registry (_ACTIVE_GUARDS) is the authoritative source.
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
        with _ACTIVE_GUARDS_LOCK:
            _ACTIVE_GUARDS.pop(self.token, None)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.lock_fd)
        except OSError:
            pass
        object.__setattr__(self, "_closed", True)


@dataclass(frozen=True)
class RawChainLock:
    """Factory for RawChainLockGuard. The ONLY way to acquire the lock.

    F5: Acquisition is atomic w.r.t. the registry. Nested locking for the
    same (directory, prefix) is prohibited. Independent locks (different
    directory or prefix) are permitted.
    """
    directory: Path
    prefix: str

    def acquire(self) -> RawChainLockGuard:
        directory_resolved = self.directory.resolve()
        lock_path = directory_resolved / f"{self.prefix}.lock"

        with _ACTIVE_GUARDS_LOCK:
            # Check for nested locking on same (directory, prefix)
            for record in _ACTIVE_GUARDS.values():
                if record.directory == directory_resolved and record.prefix == self.prefix:
                    raise NestedLockingError(
                        f"a guard is already active for "
                        f"directory={directory_resolved} prefix={self.prefix}"
                    )

            # Ensure directory exists
            directory_resolved.mkdir(parents=True, exist_ok=True)

            # Open lock file with O_NOFOLLOW
            try:
                lock_fd = os.open(
                    str(lock_path),
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                    0o644,
                )
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise PathSafetyError(
                        f"lock file is a symlink: {lock_path}"
                    ) from exc
                raise LockAcquisitionError(
                    f"cannot open lock file: {exc}"
                ) from exc

            # Take flock
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except OSError as exc:
                os.close(lock_fd)
                raise LockAcquisitionError(
                    f"fcntl.flock(LOCK_EX) failed: {exc}. "
                    f"Filesystem may not support flock."
                ) from exc

            # Capture st_dev/st_ino of the lock file
            try:
                st = os.fstat(lock_fd)
            except OSError as exc:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(lock_fd)
                raise LockAcquisitionError(
                    f"fstat of lock file failed: {exc}"
                ) from exc

            token = str(uuid.uuid4())
            guard = RawChainLockGuard(
                directory=directory_resolved,
                prefix=self.prefix,
                lock_fd=lock_fd,
                pid=os.getpid(),
                token=token,
            )
            record = GuardRecord(
                guard=guard,
                pid=os.getpid(),
                directory=directory_resolved,
                prefix=self.prefix,
                lock_fd=lock_fd,
                st_dev=st.st_dev,
                st_ino=st.st_ino,
                lock_path=lock_path,
                token=token,
            )
            _ACTIVE_GUARDS[token] = record

        return guard


def assert_guard_valid(
    guard: RawChainLockGuard,
    directory: Path,
    prefix: str,
) -> None:
    """F5 — Authoritative guard validation.

    Verifies:
    - guard is RawChainLockGuard
    - guard is not closed
    - PID matches
    - directory matches
    - prefix matches
    - token is in registry
    - registry record's guard IS this guard (detects manually constructed)
    - registry record's fd matches guard's fd
    - fstat(fd) still valid and dev/ino match registry
    - lstat(lock_path) dev/ino match the fd (detects lock path replacement)
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
    directory_resolved = directory.resolve()
    if guard.directory != directory_resolved:
        raise GuardValidationError(
            f"guard directory mismatch: guard.directory={guard.directory} "
            f"expected={directory_resolved}"
        )
    if guard.prefix != prefix:
        raise GuardValidationError(
            f"guard prefix mismatch: guard.prefix={guard.prefix!r} "
            f"expected={prefix!r}"
        )

    with _ACTIVE_GUARDS_LOCK:
        record = _ACTIVE_GUARDS.get(guard.token)
        if record is None:
            raise GuardValidationError(
                f"guard token {guard.token} is not in the active registry "
                f"(inactive or copied token)"
            )
        # The guard object in the registry MUST be the same object
        if record.guard is not guard:
            raise GuardValidationError(
                f"guard object mismatch: registry record.guard is not this guard "
                f"(manually constructed guard?)"
            )
        if record.lock_fd != guard.lock_fd:
            raise GuardValidationError(
                f"guard fd mismatch: registry fd={record.lock_fd} guard fd={guard.lock_fd}"
            )

        # Verify fd is still valid and points to same file
        try:
            current_st = os.fstat(guard.lock_fd)
        except OSError as exc:
            raise GuardValidationError(
                f"guard lock_fd {guard.lock_fd} is not a valid open fd: {exc} "
                f"(closed or reused?)"
            ) from exc
        if current_st.st_dev != record.st_dev or current_st.st_ino != record.st_ino:
            raise GuardValidationError(
                f"guard fd no longer points to the lock file: "
                f"fd dev={current_st.st_dev} ino={current_st.st_ino} vs "
                f"registry dev={record.st_dev} ino={record.st_ino} "
                f"(closed and reused for another file?)"
            )

        # Verify lock_path still points to the same inode
        try:
            path_st = os.lstat(str(record.lock_path))
        except OSError as exc:
            raise GuardValidationError(
                f"lock path lstat failed: {exc}"
            ) from exc
        if _statmod.S_ISLNK(path_st.st_mode):
            raise GuardValidationError(
                f"lock path was replaced with a symlink: {record.lock_path}"
            )
        if path_st.st_dev != record.st_dev or path_st.st_ino != record.st_ino:
            raise GuardValidationError(
                f"lock path was replaced: "
                f"path dev={path_st.st_dev} ino={path_st.st_ino} vs "
                f"registry dev={record.st_dev} ino={record.st_ino}"
            )



# ═══════════════════════════════════════════════════════════════════════
# Section 7 — Types / models
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SealedRawArtifact:
    """A2 — Sealed descriptor returned by RawScanStager.seal()."""
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
    """A8 (D5, E5) — Immutable ownership transfer descriptor."""
    sealed: SealedRawArtifact
    ownership_token: str
    staging_path: Path


@dataclass(frozen=True)
class PublishResult:
    """A8 — Result of publish_raw_scan() (Phase II). F9: status is Literal."""
    status: PublishResultStatus
    manifest_entry: dict[str, Any] | None = None
    failure_stage: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class DiagnosticEvidence:
    """E4, F7 — Durable diagnostic evidence."""
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
    evidence_location: EvidenceLocation
    evidence_filename: str


# ═══════════════════════════════════════════════════════════════════════
# Section 8 — RawScanStager (F6, F7)
# ═══════════════════════════════════════════════════════════════════════

_RAW_EVENT_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset({
    "received_at_utc", "source", "endpoint", "payload",
    "payload_sha256", "schema_version",
})


def _safe_scan_id(scan_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in scan_id)
    return safe[:100]


def load_raw_events_strict(path: Path) -> list[dict[str, Any]]:
    """Load raw events from a gzipped JSONL file with strict validation.

    F6 rule 7: Recomputes and verifies payload_sha256 for every event.
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
            # F6 rule 7: recompute and verify payload_sha256
            payload = event["payload"]
            recomputed = canonical_payload_sha256(payload)
            if recomputed != event["payload_sha256"]:
                raise ValueError(
                    f"payload_sha256 mismatch at line {line_num} in {path.name}: "
                    f"computed={recomputed} stored={event['payload_sha256']}"
                )
            events.append(event)
    return events


@dataclass
class RawScanStager:
    """F6, F7 — Isolated raw scan stager with fail-closed lifecycle.

    States (StagerState):
      OPEN → SEALED → TRANSFERRED → (publisher owns lifecycle)
      OPEN + exception before write_attempted → ABORTED_BEFORE_TRANSFER
      OPEN + exception after write_attempted → ABORTED_WITH_DIAGNOSTIC_EVIDENCE
      OPEN + exception after write_attempted + evidence persistence failure
        → BLOCKED_DIAGNOSTIC_PERSISTENCE
      SEALED + no transfer → ABORTED_BEFORE_TRANSFER
      seal() failure → ABORTED_WITH_DIAGNOSTIC_EVIDENCE (staging preserved)
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
    # F6 flags
    _entered: bool = False
    _write_attempted: bool = False
    _persistence_failure: bool = False
    _seal_started: bool = False
    _diagnostic_evidence: tuple[str, str] | None = None  # (location, filename)

    def __enter__(self) -> "RawScanStager":
        # F6 rule 1: second __enter__ must fail
        if self._entered:
            raise StagerStateError("stager already entered — cannot enter twice")
        self._entered = True
        if self._state != "OPEN":
            raise StagerStateError(f"cannot enter from state {self._state}")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = self.raw_dir / ".pending"
        staging_dir.mkdir(exist_ok=True)
        # F4: validate .pending is a real directory
        validate_real_directory(staging_dir)
        safe_id = _safe_scan_id(self.scan_id)
        unique_suffix = uuid.uuid4().hex[:12]
        staging_name = f"raw_scan_{safe_id}_{unique_suffix}.jsonl.gz.tmp"
        self._staging_path = staging_dir / staging_name
        fd = os.open(
            str(self._staging_path),
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o644,
        )
        os.close(fd)
        self._gzip_handle = gzip.open(self._staging_path, "at", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # Close gzip handle if open
        if self._gzip_handle is not None:
            try:
                self._gzip_handle.close()
            except Exception:
                pass
            self._gzip_handle = None

        # If _fail_with_diagnostic already ran (from append_event or seal),
        # the state is already ABORTED_WITH_DIAGNOSTIC_EVIDENCE or
        # BLOCKED_DIAGNOSTIC_PERSISTENCE. Don't try to preserve evidence again.
        if self._state in ("ABORTED_WITH_DIAGNOSTIC_EVIDENCE",
                           "BLOCKED_DIAGNOSTIC_PERSISTENCE"):
            return False

        if self._state == "TRANSFERRED":
            return False
        if self._state == "SEALED":
            # Sealed but not transferred → orphan cleanup
            try:
                self._delete_staging_safely()
            except RawEventPersistenceError:
                self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
            else:
                self._state = "ABORTED_BEFORE_TRANSFER"
            return False

        # state == OPEN
        if exc_type is not None:
            if self._write_attempted or self._seal_started:
                # Preserve diagnostic evidence
                try:
                    self._preserve_diagnostic_evidence(
                        f"OPEN_EXCEPTION ({exc_type.__name__})",
                        exc_val if isinstance(exc_val, BaseException) else RuntimeError(str(exc_val)),
                    )
                    self._state = "ABORTED_WITH_DIAGNOSTIC_EVIDENCE"
                except Exception:
                    self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
            else:
                try:
                    self._delete_staging_safely()
                except RawEventPersistenceError:
                    self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
                else:
                    self._state = "ABORTED_BEFORE_TRANSFER"
            return False

        # Normal exit from OPEN without seal/transfer → orphan cleanup
        try:
            self._delete_staging_safely()
        except RawEventPersistenceError:
            self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
        else:
            self._state = "ABORTED_BEFORE_TRANSFER"
        return False

    def append_event(self, event: dict[str, Any]) -> None:
        """F6 — Append a raw event with fail-closed lifecycle."""
        if self._state != "OPEN":
            raise StagerStateError(f"cannot append_event from state {self._state}")
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

        # F6 rule 2: set write_attempted BEFORE writing
        self._write_attempted = True

        # F6 rule 6: allow_nan=False
        try:
            line = json.dumps(
                event, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ) + "\n"
        except (ValueError, TypeError) as exc:
            self._fail_with_diagnostic("APPEND_EVENT_SERIALIZE", exc)

        try:
            self._gzip_handle.write(line)
            self._gzip_handle.flush()
            os.fsync(self._gzip_handle.fileno())
        except OSError as exc:
            self._fail_with_diagnostic("APPEND_EVENT_FSYNC", exc)

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
        """F6 — Seal with fail-closed lifecycle. D2 definitive order."""
        if self._state != "OPEN":
            raise StagerStateError(f"cannot seal from state {self._state}")
        if self._gzip_handle is None or self._staging_path is None:
            raise StagerStateError("stager not initialized — use 'with' statement")

        # F6: seal_started flag
        self._seal_started = True

        # 1. flush
        try:
            self._gzip_handle.flush()
        except OSError as exc:
            self._fail_with_diagnostic("SEAL_FLUSH", exc)
        # 2. close
        try:
            self._gzip_handle.close()
        except OSError as exc:
            self._gzip_handle = None
            self._fail_with_diagnostic("SEAL_GZIP_CLOSE", exc)
        self._gzip_handle = None

        staging_path = self._staging_path

        # 3-6. open fd, fsync, fstat, close
        try:
            fd = os.open(str(staging_path), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            self._fail_with_diagnostic("SEAL_OPEN", exc)
        try:
            try:
                os.fsync(fd)
            except OSError as exc:
                self._fail_with_diagnostic("SEAL_FSYNC", exc)
            try:
                st = os.fstat(fd)
            except OSError as exc:
                self._fail_with_diagnostic("SEAL_FSTAT", exc)
        finally:
            os.close(fd)

        # 7. chmod 0o444
        try:
            os.chmod(staging_path, 0o444)
        except OSError as exc:
            self._fail_with_diagnostic("SEAL_CHMOD", exc)

        # 8. fsync .pending directory
        pending_dir = staging_path.parent
        try:
            _dir_fsync(pending_dir)
        except OSError as exc:
            self._fail_with_diagnostic("SEAL_DIR_FSYNC", exc)

        # 9. strict reread (F6 rule 7: recompute payload_sha256)
        try:
            disk_events = load_raw_events_strict(staging_path)
        except (ValueError, OSError, gzip.BadGzipFile) as exc:
            self._fail_with_diagnostic("SEAL_STRICT_REREAD", exc)

        # 10. recalculate from disk
        if len(disk_events) != len(self._events):
            self._fail_with_diagnostic(
                "SEAL_EVENT_COUNT_MISMATCH",
                RuntimeError(
                    f"disk event count ({len(disk_events)}) != memory ({len(self._events)})"
                ),
            )
        disk_condition_ids: set[str] = set()
        for ev in disk_events:
            cid = ev.get("requested_condition_id", "")
            if cid:
                disk_condition_ids.add(cid)
        disk_canonical_sha = canonical_events_sha256(disk_events)

        # 11. file_sha256 from disk
        try:
            file_bytes = staging_path.read_bytes()
        except OSError as exc:
            self._fail_with_diagnostic("SEAL_READ_BYTES", exc)
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
        """D5, E5 — Single SEALED → TRANSFERRED transition."""
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

    # ─── F6: fail-closed internal methods ───

    def _fail_with_diagnostic(self, stage: str, exc: BaseException) -> NoReturn:
        """F6 — Single route for diagnostic preservation.

        Closes handles, preserves staging, writes evidence, raises.
        """
        if self._gzip_handle is not None:
            try:
                self._gzip_handle.close()
            except Exception:
                pass
            self._gzip_handle = None

        self._persistence_failure = True

        # F6 rule 4: applies even if _events is empty, as long as write_attempted or seal_started
        if self._write_attempted or self._seal_started:
            try:
                self._preserve_diagnostic_evidence(stage, exc)
                self._state = "ABORTED_WITH_DIAGNOSTIC_EVIDENCE"
            except Exception as diag_exc:
                self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
                raise DiagnosticPersistenceError(
                    f"failed to persist diagnostic evidence for {stage}: {diag_exc}"
                ) from diag_exc
        else:
            # No write attempted, no seal started — safe to delete
            try:
                self._delete_staging_safely()
            except RawEventPersistenceError as del_exc:
                self._state = "BLOCKED_DIAGNOSTIC_PERSISTENCE"
                raise DiagnosticPersistenceError(
                    f"failed to clean up staging after {stage}: {del_exc}"
                ) from exc
            self._state = "ABORTED_BEFORE_TRANSFER"

        raise RawEventPersistenceError(f"{stage}: {exc}") from exc

    def _delete_staging_safely(self) -> None:
        """F6 rule 8 — Cannot silence errors and declare cleanup successful."""
        if self._staging_path is None:
            return
        if not self._staging_path.exists():
            return
        # Re-chmod to writable if needed (seal may have set 0o444)
        try:
            os.chmod(self._staging_path, 0o644)
        except OSError:
            pass  # chmod failure is OK — unlink might still work
        try:
            self._staging_path.unlink()
        except OSError as exc:
            raise RawEventPersistenceError(
                f"failed to clean up staging file {self._staging_path}: {exc}"
            ) from exc

    def _preserve_diagnostic_evidence(self, stage: str, exc: BaseException) -> None:
        """F7 — Preserve staging and write diagnostic JSON via hardlink (no rename loop).

        Raises on failure. Does NOT raise on success.
        """
        if self._staging_path is None:
            raise OSError("no staging path for diagnostic preservation")
        if not self._staging_path.exists():
            raise OSError("staging file does not exist for diagnostic preservation")

        raw_dir_resolved = self.raw_dir.resolve()
        pending_dir = raw_dir_resolved / ".pending"
        quarantine_dir = raw_dir_resolved / ".quarantine"

        # F4: validate directories are real (not symlinks)
        validate_real_directory(pending_dir)
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        validate_real_directory(quarantine_dir)

        # Compute staging hash + size BEFORE moving
        staging_sha: str | None = None
        staging_size: int | None = None
        try:
            staging_bytes = self._staging_path.read_bytes()
            staging_sha = hashlib.sha256(staging_bytes).hexdigest()
            staging_size = len(staging_bytes)
        except OSError:
            pass

        staging_name = self._staging_path.name
        base_name = staging_name[:-4] if staging_name.endswith(".tmp") else staging_name

        evidence_location: EvidenceLocation = "QUARANTINE"
        evidence_filename: str = ""

        # F7: Try to move staging to quarantine via hardlink
        pending_fd = os.open(str(pending_dir), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        quarantine_fd = os.open(str(quarantine_dir), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            quarantine_name = f"{base_name}.{uuid.uuid4().hex[:8]}.quarantined"

            # F7: hardlink staging → quarantine (no-replace)
            # Staging is 0o444 after seal; hardlink doesn't need writable source
            try:
                os.link(staging_name, quarantine_name,
                        src_dir_fd=pending_fd, dst_dir_fd=quarantine_fd)
            except FileExistsError:
                quarantine_name = f"{base_name}.{uuid.uuid4().hex[:8]}.quarantined"
                os.link(staging_name, quarantine_name,
                        src_dir_fd=pending_fd, dst_dir_fd=quarantine_fd)

            # fsync quarantine dir
            os.fsync(quarantine_fd)

            # unlink staging original (staging stays 0o444 — unlink needs dir write, not file write)
            os.unlink(staging_name, dir_fd=pending_fd)

            # fsync pending dir
            os.fsync(pending_fd)

            evidence_filename = quarantine_name
            evidence_location = "QUARANTINE"
        except OSError:
            # Hardlink/move failed — staging stays in pending
            # Fsync pending to ensure durability
            try:
                os.fsync(pending_fd)
            except OSError:
                raise OSError("cannot ensure staging durability in pending")
            evidence_filename = staging_name
            evidence_location = "PENDING"
        finally:
            os.close(pending_fd)
            os.close(quarantine_fd)

        # Build diagnostic dict
        txn_uuid = str(uuid.uuid4())
        ownership_token = self._ownership_token or str(uuid.uuid4())
        diag_dict: dict[str, Any] = {
            "diagnostic_version": DIAGNOSTIC_SCHEMA_VERSION,
            "transaction_uuid": txn_uuid,
            "ownership_token": ownership_token,
            "diagnostic_created_at": datetime.now(timezone.utc).isoformat(),
            "triggering_state": self._state,
            "failure_stage": stage,
            "failure_type": type(exc).__name__,
            "failure_message": str(exc),
            "staging_filename": staging_name,
            "staging_sha256": staging_sha,
            "staging_size_bytes": staging_size,
            "marker_filename": None,
            "marker_integrity_sha256": None,
            "events_appended_before_failure": len(self._events),
            "events_appended_total_expected": None,
            "recoverable": False,
            "evidence_location": evidence_location,
            "evidence_filename": evidence_filename,
        }
        integrity = compute_diagnostic_integrity_sha256(diag_dict)
        diag_dict["diagnostic_integrity_sha256"] = integrity
        diag_bytes = canonical_json_bytes(diag_dict)

        # F7: Write diagnostic JSON via O_EXCL temp + hardlink (no-replace)
        diag_dir = quarantine_dir if evidence_location == "QUARANTINE" else pending_dir
        diag_dir_fd = os.open(str(diag_dir), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            diag_name = f"diagnostic_{txn_uuid}.json"
            temp_name = f"{diag_name}.tmp.{uuid.uuid4().hex}"

            temp_fd = os.open(
                temp_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o644,
                dir_fd=diag_dir_fd,
            )
            try:
                with os.fdopen(temp_fd, "wb") as f:
                    f.write(diag_bytes)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                try:
                    os.unlink(temp_name, dir_fd=diag_dir_fd)
                except FileNotFoundError:
                    pass
                raise

            # hardlink temp → final (no-replace)
            final_diag_name = diag_name
            try:
                os.link(temp_name, final_diag_name,
                        src_dir_fd=diag_dir_fd, dst_dir_fd=diag_dir_fd)
            except FileExistsError:
                final_diag_name = f"{diag_name}.{uuid.uuid4().hex[:8]}"
                os.link(temp_name, final_diag_name,
                        src_dir_fd=diag_dir_fd, dst_dir_fd=diag_dir_fd)

            # fsync diag dir
            os.fsync(diag_dir_fd)

            # unlink temp
            os.unlink(temp_name, dir_fd=diag_dir_fd)

            # fsync diag dir again
            os.fsync(diag_dir_fd)
        finally:
            os.close(diag_dir_fd)

        self._diagnostic_evidence = (evidence_location, evidence_filename)



# ═══════════════════════════════════════════════════════════════════════
# Section 9 — Eligibility state (F8)
# ═══════════════════════════════════════════════════════════════════════

ELIGIBILITY_FILENAME: Final[str] = ".eligibility_state.json"

# F8: exact required fields for eligibility state (no unknown fields allowed)
ELIGIBILITY_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "first_eligible_scan_seen",
    "first_eligible_scan_id",
    "first_persistible_data_api_request_at",
    "state_sha256",
)


@dataclass(frozen=True)
class EligibilityState:
    """D3 — Persisted eligibility state for INV-005."""
    schema_version: str
    first_eligible_scan_seen: bool
    first_eligible_scan_id: str | None
    first_persistible_data_api_request_at: str | None
    state_sha256: str


def _read_eligibility_via_fd(dir_fd: int) -> EligibilityState | None:
    """F8 — Read eligibility state via fd with O_NOFOLLOW (no TOCTOU).

    Returns None if the file is absent. Raises EligibilityCorruptionError
    if the file is present but corrupt.
    """
    try:
        file_fd = os.open(
            ELIGIBILITY_FILENAME,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=dir_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise EligibilityCorruptionError(
                f"eligibility file is a symlink: {ELIGIBILITY_FILENAME}"
            ) from exc
        raise EligibilityCorruptionError(
            f"cannot open eligibility file: {exc}"
        ) from exc

    try:
        # Read via fd
        raw = b""
        while True:
            chunk = os.read(file_fd, 65536)
            if not chunk:
                break
            raw += chunk
    except OSError as exc:
        raise EligibilityCorruptionError(
            f"cannot read eligibility file: {exc}"
        ) from exc
    finally:
        os.close(file_fd)

    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EligibilityCorruptionError(
            f"eligibility file is not valid JSON: {exc}"
        ) from exc
    if not isinstance(obj, dict):
        raise EligibilityCorruptionError(
            f"eligibility file root must be object, got {type(obj).__name__}"
        )

    # F8: reject unknown fields
    allowed = set(ELIGIBILITY_REQUIRED_FIELDS)
    unknown = [k for k in obj.keys() if k not in allowed]
    if unknown:
        raise EligibilityCorruptionError(
            f"eligibility file has unknown fields: {unknown}"
        )

    # Required fields present
    missing = [f for f in ELIGIBILITY_REQUIRED_FIELDS if f not in obj]
    if missing:
        raise EligibilityCorruptionError(
            f"eligibility file missing keys {missing}"
        )

    if obj["schema_version"] != ELIGIBILITY_SCHEMA_VERSION:
        raise EligibilityCorruptionError(
            f"eligibility schema_version mismatch: got {obj['schema_version']!r}"
        )

    # F8: first_eligible_scan_seen must be exactly true
    if obj["first_eligible_scan_seen"] is not True:
        raise EligibilityCorruptionError(
            f"eligibility file has first_eligible_scan_seen={obj['first_eligible_scan_seen']!r} "
            f"(false should be represented by absent file, not a persisted false)"
        )

    # scan_id must be non-empty string
    sid = obj["first_eligible_scan_id"]
    if not isinstance(sid, str) or not sid:
        raise EligibilityCorruptionError(
            f"first_eligible_scan_id must be non-empty string, got {sid!r}"
        )

    # request timestamp must be ISO 8601 UTC
    rat = obj["first_persistible_data_api_request_at"]
    if not isinstance(rat, str) or not rat:
        raise EligibilityCorruptionError(
            f"first_persistible_data_api_request_at must be non-empty string, got {rat!r}"
        )
    try:
        normalized = rat.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EligibilityCorruptionError(
            f"first_persistible_data_api_request_at invalid ISO 8601: {rat!r}: {exc}"
        ) from exc
    offset = parsed.utcoffset()
    if offset is None or offset != timedelta(0):
        raise EligibilityCorruptionError(
            f"first_persistible_data_api_request_at must be UTC, got offset {offset}: {rat!r}"
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


def read_eligibility_state(directory: Path) -> EligibilityState | None:
    """F8 — Read eligibility state. Convenience wrapper that opens the dir fd.

    Returns None if file absent. Raises EligibilityCorruptionError if corrupt.
    """
    reject_symlink_path(directory)
    dir_fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _read_eligibility_via_fd(dir_fd)
    finally:
        os.close(dir_fd)


def mark_first_eligible_scan_seen_under_lock(
    guard: RawChainLockGuard,
    directory: Path,
    prefix: str,
    first_eligible_scan_id: str,
    first_persistible_data_api_request_at: str,
) -> EligibilityState:
    """F8 — Mark the first eligible scan as seen. Requires RawChainLockGuard.

    Behavior:
    - File absent: create state true via no-replace (O_EXCL)
    - File valid true: return existing state idempotently
    - File corrupt: EligibilityCorruptionError
    - File valid false: EligibilityCorruptionError (false should only be
      represented by absent file)

    F8: No unlocked write API exists. The false state is represented
    exclusively by file absence.
    """
    assert_guard_valid(guard, directory, prefix)

    # Validate inputs
    if not isinstance(first_eligible_scan_id, str) or not first_eligible_scan_id:
        raise ValueError("first_eligible_scan_id must be non-empty string")
    if not isinstance(first_persistible_data_api_request_at, str) or not first_persistible_data_api_request_at:
        raise ValueError("first_persistible_data_api_request_at must be non-empty string")
    # Validate ISO 8601 UTC
    try:
        normalized = first_persistible_data_api_request_at.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"first_persistible_data_api_request_at invalid ISO 8601: {exc}"
        ) from exc
    offset = parsed.utcoffset()
    if offset is None or offset != timedelta(0):
        raise ValueError(
            f"first_persistible_data_api_request_at must be UTC, got offset {offset}"
        )

    directory_resolved = directory.resolve()
    dir_fd = os.open(
        str(directory_resolved),
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        existing = _read_eligibility_via_fd(dir_fd)

        if existing is not None:
            # F8: existing must be true (false is represented by absent file)
            if existing.first_eligible_scan_seen is True:
                return existing  # idempotent
            else:
                raise EligibilityCorruptionError(
                    "eligibility file has first_eligible_scan_seen=false "
                    "(should be represented by absent file)"
                )

        # File absent → create state true via O_EXCL (no-replace)
        body: dict[str, Any] = {
            "schema_version": ELIGIBILITY_SCHEMA_VERSION,
            "first_eligible_scan_seen": True,
            "first_eligible_scan_id": first_eligible_scan_id,
            "first_persistible_data_api_request_at": first_persistible_data_api_request_at,
        }
        integrity = compute_eligibility_integrity_sha256(body)
        body["state_sha256"] = integrity
        canonical = canonical_json_bytes(body)

        temp_name = f"{ELIGIBILITY_FILENAME}.tmp.{uuid.uuid4().hex}"
        temp_fd = os.open(
            temp_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                f.write(canonical)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise

        # O_EXCL no-replace: os.link temp → final (not os.rename)
        try:
            os.link(temp_name, ELIGIBILITY_FILENAME,
                    src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except FileExistsError:
            # Another process created the file concurrently
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            # Re-read and return idempotently or raise
            existing = _read_eligibility_via_fd(dir_fd)
            if existing is not None and existing.first_eligible_scan_seen is True:
                return existing
            raise EligibilityCorruptionError(
                "concurrent eligibility write resulted in unexpected state"
            )
        finally:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass

        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    return EligibilityState(
        schema_version=body["schema_version"],
        first_eligible_scan_seen=body["first_eligible_scan_seen"],
        first_eligible_scan_id=body["first_eligible_scan_id"],
        first_persistible_data_api_request_at=body["first_persistible_data_api_request_at"],
        state_sha256=integrity,
    )


# ═══════════════════════════════════════════════════════════════════════
# Section 10 — Marker filename helper (F9)
# ═══════════════════════════════════════════════════════════════════════

def marker_filename(prefix: str, sequence: int, transaction_uuid: str) -> str:
    """F9 — Compute canonical marker filename with strict validation.

    Format: {prefix}_txn_{sequence:06d}_{transaction_uuid}.marker

    Validates:
    - prefix is safe (alphanumeric + underscore only)
    - sequence is non-negative int
    - transaction_uuid is a real UUID4
    """
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be non-empty string")
    if not all(c.isalnum() or c == "_" for c in prefix):
        raise ValueError(f"prefix contains unsafe characters: {prefix!r}")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ValueError(f"sequence must be non-negative int, got {sequence!r}")
    # F9: validate UUID4 strictly
    try:
        u = uuid.UUID(transaction_uuid)
    except ValueError as exc:
        raise ValueError(f"transaction_uuid invalid UUID: {exc}") from exc
    if u.version != 4:
        raise ValueError(
            f"transaction_uuid must be UUID version 4, got version {u.version}"
        )
    return f"{prefix}_txn_{sequence:06d}_{transaction_uuid}.marker"


# ═══════════════════════════════════════════════════════════════════════
# Backward-compatible wrappers (deprecated — use _under_lock variants)
# ═══════════════════════════════════════════════════════════════════════

def create_marker_no_replace(
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy | None = None,
) -> Path:
    """Deprecated wrapper — acquires its own lock. Prefer create_marker_no_replace_under_lock."""
    if policy is None:
        policy = DEFAULT_MARKER_POLICY
    lock = RawChainLock(directory, policy.manifest_prefix)
    with lock.acquire() as guard:
        return create_marker_no_replace_under_lock(
            guard, directory, marker_name, marker_body, policy
        )


def update_existing_marker_atomic(
    directory: Path,
    marker_name: str,
    marker_body: dict[str, Any],
    policy: MarkerValidationPolicy | None = None,
) -> Path:
    """Deprecated wrapper — acquires its own lock. Prefer update_existing_marker_atomic_under_lock."""
    if policy is None:
        policy = DEFAULT_MARKER_POLICY
    lock = RawChainLock(directory, policy.manifest_prefix)
    with lock.acquire() as guard:
        return update_existing_marker_atomic_under_lock(
            guard, directory, marker_name, marker_body, policy
        )
