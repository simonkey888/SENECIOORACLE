# H-011 V3 — Raw Artifact Transaction Design

## Status: DESIGN DOCUMENT — Architecture Finalized

**Design base code SHA:** `18f8e6dea12c25a4dc338b0a0fdb2bccc417540b`
**Date:** 2026-07-13
**Branch:** `feat/h011-v3-control-plane-coverage`
**Production:** `2f850353` (untouched)
**PR:** #5 Draft

---

## A1 — Separation: `verify_candidate_logical` vs `verify_candidate_physical`

### `verify_candidate_logical(existing_entries, candidate_entry)`

Pure function. No filesystem access. Checks:

1. `candidate_entry["sequence"] == len(existing_entries)`
2. If `existing_entries` is empty: `candidate_entry["previous_manifest_hash"]` must be `None`.
3. If not empty: `candidate_entry["previous_manifest_hash"] == existing_entries[-1]["manifest_hash"]`.
4. Recompute `manifest_hash` from candidate (exclude `manifest_hash` key, canonical JSON) and compare with stored value.
5. `candidate_entry["filename"]` not in `{e["filename"] for e in existing_entries}`.
6. For each `field` in `("run_id", "scan_id")`: value not in `{e.get(field) for e in existing_entries}`.
7. `candidate_entry["file_sha256"]` is 64-char lowercase hex.
8. `candidate_entry["event_count"]` is int ≥ 0.
9. `candidate_entry["condition_ids"]` is a list of strings.
10. `candidate_entry["canonical_events_sha256"]` is 64-char lowercase hex.

Returns `(True, [])` or `(False, [error_strings])`.

### `verify_candidate_physical(directory, candidate_entry, policy)`

Filesystem checks after artifact + sidecar are on disk, before manifest publication:

1. `directory / candidate_entry["filename"]` exists, is a regular file, not symlink.
2. Sidecar `directory / (filename + ".sha256")` exists, is a regular file.
3. Sidecar content matches regex `^[0-9a-f]{64}\n$`.
4. Sidecar content (stripped) == `candidate_entry["file_sha256"]`.
5. Recompute SHA-256 of artifact file bytes == sidecar content == `candidate_entry["file_sha256"]`.
6. `load_raw_events_strict(artifact_path)` succeeds.
7. `len(disk_events) == candidate_entry["event_count"]`.
8. `sorted({e["requested_condition_id"] for e in disk_events if e.get("requested_condition_id")})` == `candidate_entry["condition_ids"]`.
9. Recompute `canonical_events_sha256` from disk events and compare.
10. For each event: recompute `payload_sha256` from `event["payload"]` using canonical serialization and compare with stored value.
11. `filename` matches `policy.artifact_glob`.
12. No orphan sidecar exists for a filename not in any manifest entry.
13. No unregistered artifact matches `policy.artifact_glob` (excluding `policy.exclude_names`).

Returns `(True, [])` or `(False, [error_strings])`.

### Publication sequence

```
verify_candidate_logical  → in memory, before touching disk
publish artifact          → hardlink
publish sidecar           → hardlink
verify_candidate_physical → read artifact + sidecar from disk
publish manifest          → O_CREAT|O_EXCL
verify_manifest_chain     → full chain reverify
```

---

## A2 — `SealedRawArtifact` Complete

```python
@dataclass(frozen=True)
class SealedRawArtifact:
    version: int                          # Schema version, currently 1
    staging_filename: str                 # Just the filename, not full path
    final_name: str                       # raw_scan_<safe_id>_<hash12>.events.jsonl.gz
    run_id: str
    scan_id: str
    event_count: int
    condition_ids: tuple[str, ...]        # Sorted, deduplicated
    file_sha256: str                      # SHA-256 of staging file bytes (lowercase hex)
    canonical_events_sha256: str          # SHA-256 of canonical events JSON (lowercase hex)
    size_bytes: int                       # File size in bytes at seal time
    sealed_at: str                        # ISO 8601 UTC timestamp when seal() was called
    device_id: int                        # os.fstat(staging_fd).st_dev
    inode: int                            # os.fstat(staging_fd).st_ino
```

`seal()` captures `os.fstat()` on the staging file descriptor before closing it. These values are informational; the publisher re-validates `file_sha256` under lock.

---

## A3 — Canonicalization Normative

### Payload SHA-256

```python
def canonical_payload_sha256(payload: Any) -> str:
    """Compute the canonical SHA-256 of a raw event payload."""
    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()
```

Rules:
- `sort_keys=True` — deterministic key order.
- `separators=(",", ":")` — no whitespace.
- `ensure_ascii=False` — preserve UTF-8.
- `allow_nan=False` — reject NaN/Infinity (raises `ValueError`).
- List order is preserved (JSON arrays are ordered; `sort_keys` only sorts dict keys, not list elements).
- Output is 64-char lowercase hexadecimal.

### Canonical Events SHA-256

```python
def canonical_events_sha256(events: list[dict]) -> str:
    canonical_bytes = json.dumps(
        events,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()
```

Same rules. The list of events is serialized as a JSON array. Event order within the list is the order they were appended to the staging file.

### Payload SHA-256 Verification

During `verify_candidate_physical`, for each event in the artifact:
1. Extract `event["payload"]`.
2. Extract `event["payload_sha256"]`.
3. Recompute `canonical_payload_sha256(event["payload"])`.
4. If recomputed != stored: `CHAIN_INVALID`.

---

## A4 — Hash Differentiation

### `manifest_hash_input_bytes`

The canonical JSON bytes of the manifest entry **excluding** the `manifest_hash` key:

```python
manifest_for_hash = {k: v for k, v in entry.items() if k != "manifest_hash"}
manifest_hash_input_bytes = json.dumps(
    manifest_for_hash,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
manifest_hash = hashlib.sha256(manifest_hash_input_bytes).hexdigest()
```

### `manifest_file_bytes`

The complete canonical JSON bytes of the manifest entry **including** `manifest_hash`:

```python
manifest_file_bytes = json.dumps(
    entry,  # includes manifest_hash
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

### `candidate_manifest_bytes_sha256`

SHA-256 of `manifest_file_bytes`:

```python
candidate_manifest_bytes_sha256 = hashlib.sha256(manifest_file_bytes).hexdigest()
```

### Usage

- `manifest_hash` is stored in `entry["manifest_hash"]` and verified by `verify_manifest_chain`.
- `manifest_file_bytes` is what gets written to disk as the manifest file.
- `candidate_manifest_bytes_sha256` is stored in the transaction marker so recovery can verify it's publishing the exact same bytes.
- During recovery: read manifest file from disk, compute SHA-256, compare with `candidate_manifest_bytes_sha256`. If different → `BLOCK`.

---

## A5 — Sidecar Normative

### Format

The sidecar file contains exactly:

```
<64 lowercase hexadecimal characters>\n
```

That is: 64 characters of `[0-9a-f]`, followed by a single newline (`\n`). Total: 65 bytes.

No leading whitespace. No trailing whitespace beyond the newline. No uppercase. No comments. No additional lines.

### Validation

```python
import re
SIDECAR_PATTERN = re.compile(rb'^[0-9a-f]{64}\n$')

def validate_sidecar(sidecar_path: Path) -> str:
    content = sidecar_path.read_bytes()
    if not SIDECAR_PATTERN.match(content):
        raise ValueError(f"Sidecar {sidecar_path.name} does not match format")
    return content[:64].decode("ascii")
```

### Publication

Sidecar is created in `.pending/` with `O_CREAT | O_EXCL`, written with `flush + fsync`, then hardlinked to the final path (no-overwrite). The hardlink is verified by checking that final and staging refer to the same inode.

### Verification in Chain

For each manifest entry, `verify_raw_chain` checks:
1. Sidecar file exists at `directory / (filename + ".sha256")`.
2. Sidecar content matches `SIDECAR_PATTERN`.
3. Sidecar content (stripped) == `entry["file_sha256"]`.
4. Sidecar content (stripped) == recomputed SHA-256 of artifact file.

If any check fails: `CHAIN_INVALID`.

---

## A6 — Recovery Matrix

Single action per cell. No ambiguity.

| Marker Status | Artifact | Sidecar | Manifest | Chain | Action |
|---|---|---|---|---|---|
| STAGED | absent | absent | absent | n/a | CONTINUE (publish from STAGED) |
| STAGED | present | absent | absent | n/a | BLOCK (unexpected artifact) |
| STAGED | absent | present | absent | n/a | BLOCK (unexpected sidecar) |
| STAGED | absent | absent | present | n/a | BLOCK (unexpected manifest) |
| STAGED | present | present | absent | n/a | BLOCK (contradictory) |
| STAGED | * | * | * | invalid | BLOCK |
| STAGED | staging corrupt | n/a | n/a | n/a | QUARANTINE |
| ARTIFACT_PUBLISHED | present | absent | absent | n/a | CONTINUE (publish sidecar) |
| ARTIFACT_PUBLISHED | absent | absent | absent | n/a | BLOCK (missing artifact) |
| ARTIFACT_PUBLISHED | present | present | absent | n/a | BLOCK (unexpected sidecar) |
| ARTIFACT_PUBLISHED | present | absent | present | n/a | BLOCK (unexpected manifest) |
| SIDECAR_PUBLISHED | present | present | absent | n/a | CONTINUE (publish manifest) |
| SIDECAR_PUBLISHED | absent | * | * | n/a | BLOCK (missing artifact) |
| SIDECAR_PUBLISHED | present | absent | * | n/a | BLOCK (missing sidecar) |
| SIDECAR_PUBLISHED | present | present | present | n/a | BLOCK (unexpected manifest) |
| MANIFEST_PUBLISHED | present | present | present | valid | COMMIT |
| MANIFEST_PUBLISHED | present | present | present | invalid | BLOCK |
| MANIFEST_PUBLISHED | absent | * | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | absent | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | * | absent | * | BLOCK |
| COMMITTED | * | * | * | * | CLEAN (remove marker + staging) |
| QUARANTINED | * | * | * | * | BLOCK (report unresolved) |
| corrupt marker | * | * | * | * | QUARANTINE |
| no marker, orphan artifact | present | * | * | * | BLOCK (orphan) |
| no marker, orphan sidecar | * | present | * | * | BLOCK (orphan) |

Actions defined:
- **CONTINUE**: Resume publication from the current marker state.
- **COMMIT**: Verify chain is valid, mark COMMITTED, clean up marker + staging.
- **BLOCK**: Preserve all evidence. Do not move or delete files. Report as unresolved. New publications refused.
- **QUARANTINE**: Marker is corrupt or evidence is contradictory. Move marker to `.quarantine/`. Report as unresolved. New publications refused.
- **CLEAN**: Transaction completed successfully. Remove marker and staging file.

---

## A7 — Fault Injection via `subprocess` + `os._exit()`

### Mechanism

Fault injection uses real process termination, not Python exceptions:

```python
import subprocess, sys, json

def fault_injected_publish(
    directory: Path,
    sealed: SealedRawArtifact,
    policy: ManifestPolicy,
    fault_after: str,  # "STAGED" | "ARTIFACT_PUBLISHED" | "SIDECAR_PUBLISHED" | "MANIFEST_PUBLISHED"
) -> None:
    """Run publish in a subprocess that exits hard at the specified stage."""
    script = f'''
import sys, os
sys.path.insert(0, "{directory.parent}")
from control_plane.raw_artifact_transaction import _publish_raw_scan_with_fault_hook
_publish_raw_scan_with_fault_hook(
    directory={directory!r},
    sealed={sealed!r},
    policy={policy!r},
    fault_after="{fault_after}",
)
# If we reach here, fault hook was not triggered (shouldn't happen)
os._exit(0)
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
        cwd=str(directory.parent),
    )
    # Process is killed by os._exit() inside the fault hook
    # exit code will be non-zero (killed)
```

### Fault Hook in Publisher

```python
def _publish_raw_scan_with_fault_hook(
    *, directory, sealed, policy, fault_after
):
    """Internal publisher with fault injection hook."""
    # ... normal publish logic ...
    # At each state transition:
    if fault_after == "STAGED":
        os._exit(99)  # Hard exit, no except blocks, no cleanup
    # ... publish artifact ...
    if fault_after == "ARTIFACT_PUBLISHED":
        os._exit(99)
    # ... publish sidecar ...
    if fault_after == "SIDECAR_PUBLISHED":
        os._exit(99)
    # ... publish manifest ...
    if fault_after == "MANIFEST_PUBLISHED":
        os._exit(99)
    # ... normal completion ...
```

### Test Pattern

```python
def test_fault_injection_artifact_published(raw_dir):
    sealed = _stage_and_seal(raw_dir)
    # Run publish in subprocess that crashes after ARTIFACT_PUBLISHED
    fault_injected_publish(raw_dir, sealed, RAW_MANIFEST_POLICY, "ARTIFACT_PUBLISHED")
    # Now run recovery in a new process
    recovery_results = recover_incomplete_transactions(raw_dir, RAW_MANIFEST_POLICY)
    # Recovery should continue: publish sidecar + manifest
    assert any(r["action"] == "COMMIT" or r["action"] == "CONTINUE" for r in recovery_results)
    # Chain should be valid
    result = verify_raw_chain(raw_dir, RAW_MANIFEST_POLICY)
    assert result["chain_status"] == "VALID_CHAIN"
```

---

## A8 — API Without Identity Duplication

### Canonical API

```python
publish_raw_scan(
    directory: Path,           # V3_RAW_CHAIN_DIR
    sealed: SealedRawArtifact, # contains run_id, scan_id
    policy: ManifestPolicy,    # RAW_MANIFEST_POLICY
) -> dict[str, Any]           # manifest entry
```

**No `identity_fields` parameter.** Identity comes exclusively from `sealed.run_id` and `sealed.scan_id`.

The manifest entry is built from `sealed` fields:

```python
entry = {
    "sequence": sequence,
    "filename": sealed.final_name,
    "file_sha256": sealed.file_sha256,
    "previous_manifest_hash": previous_hash,
    "created_at": frozen_timestamp,
    "run_id": sealed.run_id,
    "scan_id": sealed.scan_id,
    "event_count": sealed.event_count,
    "condition_ids": list(sealed.condition_ids),
    "canonical_events_sha256": sealed.canonical_events_sha256,
}
entry["manifest_hash"] = compute_manifest_hash(entry)
```

### Extra Manifest Fields

If future scan metadata needs to be included in the manifest (e.g., `code_sha`, `config_sha`), it goes into `SealedRawArtifact` as additional fields, not as a separate parameter. This ensures the sealed descriptor is the single source of truth.

---

## A9 — Runtime Edge Cases

### Zero Markets

If discovery returns zero markets: `run_scan_v3` does not create a stager. No raw artifact is produced. INV-005 returns `NOT_APPLICABLE` (no raw events to verify).

### Zero Data API Queries

If all markets are rejected before Data API (identity, temporal, metadata): no `append_event()` is called. The stager is sealed with `event_count=0`. The artifact contains an empty gzip.

Decision: **Publish the empty artifact.** An empty scan is a valid scan. The manifest records `event_count=0`. INV-005 can verify the empty gzip. This preserves the chain continuity (every scan produces exactly one artifact).

### Empty Data API Response

A valid HTTP 200 with `[]` trades is a normal response. `append_event()` stores the empty payload. `payload_sha256` is computed from `[]`. This is a valid event.

### Partial Failures

If `process_market_v3` raises for market 3 of 5: the first 3 events are already in the staging file (flushed + fsynced). The exception propagates to `run_scan_v3`. Decision: **catch the exception, continue processing remaining markets, then seal with whatever events were collected.** The stager accumulates all successful events.

### Exception Before First Raw Event

If `process_market_v3` raises before any Data API call (identity rejection): no events appended. Stager seals with `event_count=0`. Published as empty artifact.

### Exception After First Raw Event

Events already in staging are preserved (flushed + fsynced). Remaining markets may or may not produce events. Stager seals with whatever was collected.

### Zero Raw Events Total

Same as "Zero Data API Queries" — empty artifact published.

### Duplicate Condition IDs

If two markets have the same `conditionId`, both events are stored. `condition_ids` in the manifest is a list (may contain duplicates from the raw events, but the `SealedRawArtifact.condition_ids` is a deduplicated sorted tuple). The manifest stores the deduplicated list.

### Publication Failure

If `publish_raw_scan` raises:
- Marker persists at last successful state with `failure_stage` and `recoverable` fields.
- `run_scan_v3` catches the error, logs it, and continues to snapshot generation.
- INV-005 will be `FAIL` (BLOCKED or INVALID chain).
- Next scan cycle's recovery will attempt to resolve.

---

## A10 — Legacy Strategy

### Directory Separation

```
results/h011_v3/raw/          ← Legacy daily-append files (DEPRECATED for V3)
results/h011_v3/raw_chain_v1/  ← New immutable per-scan chain
```

### No Automatic Migration

Legacy files in `raw/` are not moved, not migrated, not manifests'd. They remain for audit purposes. The new chain in `raw_chain_v1/` starts empty.

### INV-005 Configuration

`V3_RAW_DIR` in `h011_v3_pipeline.py` changes from:
```python
V3_RAW_DIR = V3_RESULTS_DIR / "raw"
```
to:
```python
V3_RAW_CHAIN_DIR = V3_RESULTS_DIR / "raw_chain_v1"
```

`INV-005` checks `raw_chain_v1/`, not `raw/`.

### Bootstrap

First scan in `raw_chain_v1/`:
- Directory is empty → `EMPTY_CHAIN` → `UNKNOWN` for INV-005.
- First `publish_raw_scan` creates artifact + manifest → `VALID_CHAIN` → `PASS` for INV-005.

No `BOOTSTRAP_REQUIRED` because the directory starts clean.

---

## A11 — Ownership and States

### Stager States

```
OPEN                         — Stager created, staging file open for append
  ↓ seal()
SEALED                       — Staging file closed, SealedRawArtifact returned
  ↓ publish_raw_scan() called
TRANSFERRED                  — Ownership transferred to publisher
  ↓ publish success
PUBLISHED                    — Staging file removed, marker COMMITTED
  ↓ publish failure (recoverable)
RECOVERABLE_ERROR_AFTER_TRANSFER — Marker at failure_stage, recovery will complete
  ↓ publish failure (unrecoverable)
BLOCKED_AFTER_TRANSFER       — Marker BLOCKED, evidence preserved, manual intervention needed
```

```
OPEN                         — Stager created
  ↓ exception before seal()
ABORTED_BEFORE_TRANSFER      — Staging file deleted by context manager
```

### Context Manager Behavior

```python
with RawScanStager(run_id, scan_id, raw_dir) as stager:
    # state = OPEN
    stager.append_event(event)
    # state = OPEN
    sealed = stager.seal()
    # state = SEALED

# On __exit__:
#   if state == OPEN and exception: delete staging, state = ABORTED_BEFORE_TRANSFER
#   if state == SEALED and not transferred: delete staging (orphan), state = ABORTED_BEFORE_TRANSFER
#   if state == TRANSFERRED: do nothing (publisher owns lifecycle)
#   if state == PUBLISHED: do nothing (already cleaned up)
#   if state == RECOVERABLE_ERROR_AFTER_TRANSFER: do nothing (marker owns recovery)
#   if state == BLOCKED_AFTER_TRANSFER: do nothing (evidence preserved)
```

### Transfer Semantics

`publish_raw_scan()` receives the `sealed` descriptor. This constitutes transfer. The stager's `__exit__` will not delete the staging file if it was transferred (checked via a `_transferred` flag set by `seal()` when the descriptor is passed to the publisher).

Implementation: `seal()` sets `self._sealed = True`. `publish_raw_scan()` is called by the runtime, which means the stager is no longer in a `with` block — `__exit__` has already run. If `__exit__` runs while `_sealed` is True and `_transferred` is False, the staging file is deleted as an orphan.

To avoid this, the runtime pattern is:

```python
with RawScanStager(...) as stager:
    for market in markets:
        process_market_v3(..., raw_event_sink=stager)
    sealed = stager.seal()
    # Transfer happens here — stager marks _transferred = True
    publish_raw_scan(directory, sealed, policy)
    # state = PUBLISHED or RECOVERABLE_ERROR
```

`publish_raw_scan()` sets `stager._transferred = True` before doing anything. If it raises, the stager is in `RECOVERABLE_ERROR_AFTER_TRANSFER` state and `__exit__` does not delete the staging file.

---

## A12 — Concurrency Contract

### Lock

```python
lock_path = directory / f"{policy.manifest_prefix}.lock"
lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
```

### Properties

- **Multi-process**: `fcntl.flock` is advisory but works across processes on the same host.
- **Recovery under same lock**: `recover_incomplete_transactions()` is called inside the lock by `publish_raw_scan()`. No separate lock acquisition.
- **No nested locking**: `publish_raw_scan()` acquires the lock once. All operations (recovery, validation, publication, verification) happen under that single lock acquisition. No function called from within the lock tries to acquire it again.
- **Filesystem without flock**: If `fcntl.flock` is not supported (e.g., NFS without locking), `flock` raises `OSError`. The publisher catches this and raises `RuntimeError("flock not supported on this filesystem")`. Publication is refused. INV-005 returns `UNKNOWN`.
- **Timeout**: No explicit timeout. `fcntl.flock(LOCK_EX)` blocks indefinitely. If a process crashes while holding the lock, the kernel releases it automatically (flock is associated with the process, not the file descriptor). If a process hangs, manual intervention is needed.

Decision: No timeout. A timeout would introduce a race condition where the lock is released while the previous holder is still writing. The kernel's automatic release on process death is sufficient.

### Concurrent Publisher Behavior

Two processes/threads call `publish_raw_scan()` simultaneously:
1. Process A acquires lock.
2. Process B blocks on `flock`.
3. Process A recovers (nothing to recover), validates, publishes sequence 0, releases lock.
4. Process B acquires lock, recovers (nothing — A cleaned up), validates, publishes sequence 1, releases lock.
5. Both succeed. No `time.sleep`. No retries.

If Process A crashes mid-publication:
1. Kernel releases A's lock.
2. Process B acquires lock.
3. B runs recovery, finds A's incomplete transaction, completes or blocks it.
4. B then publishes its own sequence.

---

## A13 — INV-005 Semantics

```
EMPTY_CHAIN:
    UNKNOWN
    (No manifests, no artifacts. First scan hasn't run yet.)
    Condition: zero manifests AND zero artifacts in raw_chain_v1/.

BOOTSTRAP_REQUIRED:
    FAIL
    (Artifacts exist but no manifests. Should not happen with clean start.)
    Condition: zero manifests AND artifacts exist.

VALID_CHAIN:
    PASS
    (Manifest chain verified. All sidecars present and correct.
     No unresolved markers. No quarantine. No orphan artifacts/sidecars.)
    Condition: verify_raw_chain() returns VALID_CHAIN
    AND no unresolved markers
    AND no files in .quarantine/
    AND no orphan artifacts
    AND no orphan sidecars.

INVALID_CHAIN:
    FAIL
    (Chain verification failed: hash mismatch, missing file, corrupt content, etc.)

BLOCKED (unresolved transactions):
    FAIL
    (Recovery found BLOCKED transactions. Chain cannot be trusted.)

QUARANTINED (unresolved):
    FAIL
    (Recovery found QUARANTINED transactions. Evidence is corrupt.)

NOT_APPLICABLE:
    NOT_APPLICABLE
    (No raw events in this scan — zero markets reached Data API.
     No artifact produced. Cannot verify append-only of nothing.)
    Condition: scan produced zero raw events AND directory is EMPTY_CHAIN.
```

### Implementation

```python
def _eval_raw_events_append_only(ctx: ScanContext) -> tuple[str, str, dict]:
    from control_plane.raw_artifact_transaction import verify_raw_chain, recover_incomplete_transactions
    from control_plane.artifact_manifest import RAW_MANIFEST_POLICY

    raw_chain_dir = Path(ctx.raw_dir) if ctx.raw_dir else None
    if not raw_chain_dir or not raw_chain_dir.exists():
        return ("UNKNOWN", "Raw chain directory not accessible", {})

    # Check for unresolved markers
    recovery = recover_incomplete_transactions(raw_chain_dir, RAW_MANIFEST_POLICY)
    unresolved = [r for r in recovery if r.get("action") in ("BLOCK", "QUARANTINE")]
    if unresolved:
        return ("FAIL", f"Unresolved transactions: {len(unresolved)}", {"unresolved": unresolved})

    # Verify chain
    result = verify_raw_chain(raw_chain_dir, RAW_MANIFEST_POLICY)
    status = result["chain_status"]

    if status == "VALID_CHAIN":
        # Check for orphans
        if result.get("unregistered_files") or result.get("orphan_sidecars"):
            return ("FAIL", f"Orphan artifacts/sidecars: {result.get('unregistered_files', [])} {result.get('orphan_sidecars', [])}", {})
        # Check quarantine
        quarantine_dir = raw_chain_dir / ".quarantine"
        if quarantine_dir.exists() and any(quarantine_dir.iterdir()):
            return ("FAIL", "Quarantine directory not empty", {})
        return ("PASS", f"Raw chain verified: {result['sequence_count']} entries", {"sequence_count": result["sequence_count"]})

    elif status == "EMPTY_CHAIN":
        return ("UNKNOWN", "Empty chain — no manifests or artifacts", {})

    elif status == "BOOTSTRAP_REQUIRED":
        return ("FAIL", f"Bootstrap required: {result.get('unregistered_files', [])}", {})

    else:  # INVALID_CHAIN
        return ("FAIL", f"Chain invalid: {'; '.join(result['errors'])}", {"errors": result["errors"]})
```

---

## A14 — Metadata

### Design Base Code SHA

```
Design base code SHA:
18f8e6dea12c25a4dc338b0a0fdb2bccc417540b
```

This is the code SHA on which this design is based. It is not the SHA of this commit.

### PR Body Template

After committing this design doc:

```
Current head: <SHA COMPLETO NUEVO>
Design base code SHA: 18f8e6dea12c25a4dc338b0a0fdb2bccc417540b
Phase: transaction redesign — architecture finalized
Code implementation paused
Tests: 247/247 existing
Production: 2f850353 untouched
PR: Draft
```

---

## Summary: A1-A14 Status

| ID | Topic | Status |
|---|---|---|
| A1 | verify_candidate_logical vs verify_candidate_physical | ✅ Resolved |
| A2 | SealedRawArtifact with version, device_id, inode, size_bytes, sealed_at, staging_filename | ✅ Resolved |
| A3 | Canonicalization: allow_nan=False, list order preserved, UTF-8, sort_keys, separators, lowercase SHA-256 | ✅ Resolved |
| A4 | manifest_hash_input_bytes vs manifest_file_bytes vs candidate_manifest_bytes_sha256 | ✅ Resolved |
| A5 | Sidecar: exactly `<64 lowercase hex>\n` | ✅ Resolved |
| A6 | Recovery matrix: single action per cell (CONTINUE/COMMIT/BLOCK/QUARANTINE/CLEAN) | ✅ Resolved |
| A7 | Fault injection: subprocess + os._exit() | ✅ Resolved |
| A8 | API: publish_raw_scan(directory, sealed, policy) — identity from sealed only | ✅ Resolved |
| A9 | Runtime edge cases: zero markets, zero queries, empty response, partial failures, exceptions, zero events, duplicate IDs, publication failure | ✅ Resolved |
| A10 | Legacy: raw/ (legacy) vs raw_chain_v1/ (new), no automatic migration | ✅ Resolved |
| A11 | Ownership: OPEN/SEALED/TRANSFERRED/PUBLISHED/ABORTED_BEFORE_TRANSFER/RECOVERABLE_ERROR_AFTER_TRANSFER/BLOCKED_AFTER_TRANSFER | ✅ Resolved |
| A12 | Concurrency: flock multi-process, recovery under same lock, no nested locking, no flock → refuse, no timeout | ✅ Resolved |
| A13 | INV-005: EMPTY_CHAIN=UNKNOWN, BOOTSTRAP_REQUIRED=FAIL, VALID_CHAIN=PASS (with orphan/quarantine checks), INVALID_CHAIN=FAIL, BLOCKED=FAIL, QUARANTINED=FAIL | ✅ Resolved |
| A14 | Metadata: design base SHA in doc, PR body template | ✅ Resolved |

**Zero open decisions.**
