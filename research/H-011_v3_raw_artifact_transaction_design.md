# H-011 V3 — Raw Artifact Transaction Design

## Status: DESIGN DOCUMENT — Architecture Corrected (C1–C14)

**Design base code SHA:** `18f8e6dea12c25a4dc338b0a0fdb2bccc417540b`
**Date:** 2026-07-13
**Branch:** `feat/h011-v3-control-plane-coverage`
**Production:** `2f850353` (untouched)
**PR:** #5 Draft

---

## A1 — verify_candidate_logical vs verify_candidate_physical (C4 corrected)

### verify_candidate_logical(existing_entries, candidate_entry)

Pure function. No filesystem access. Checks:

1. `candidate_entry["sequence"] == len(existing_entries)`
2. If empty: `previous_manifest_hash` must be `None`. Else: must equal `existing_entries[-1]["manifest_hash"]`.
3. Recompute `manifest_hash` from candidate (exclude `manifest_hash` key, canonical JSON) and compare.
4. `filename` not in `{e["filename"] for e in existing_entries}`.
5. `run_id` not in `{e.get("run_id") for e in existing_entries}`.
6. `scan_id` not in `{e.get("scan_id") for e in existing_entries}`.
7. `file_sha256` is 64-char lowercase hex.
8. `event_count` is int ≥ 0.
9. `condition_ids` is a list of strings.
10. `canonical_events_sha256` is 64-char lowercase hex.

Returns `(True, [])` or `(False, [errors])`.

### verify_candidate_physical(directory, candidate_entry, policy, allowed_candidate_filename)

Filesystem checks after artifact + sidecar are on disk, before manifest publication. Accepts `allowed_candidate_filename` so the candidate artifact and its sidecar are NOT flagged as unregistered/orphan.

Checks:
1. Artifact `directory / candidate_entry["filename"]` exists, is a regular file, not symlink.
2. Sidecar `directory / (filename + ".sha256")` exists, is a regular file.
3. Sidecar content matches `^[0-9a-f]{64}\n$`.
4. Sidecar content (stripped) == `candidate_entry["file_sha256"]`.
5. Recompute SHA-256 of artifact file bytes == sidecar content == `candidate_entry["file_sha256"]`.
6. `load_raw_events_strict(artifact_path)` succeeds.
7. `len(disk_events) == candidate_entry["event_count"]`.
8. `sorted({e["requested_condition_id"] for e in disk_events if e.get("requested_condition_id")})` == `candidate_entry["condition_ids"]`.
9. Recompute `canonical_events_sha256` from disk events and compare.
10. For each event: recompute `payload_sha256` from `event["payload"]` using canonical serialization and compare.
11. `filename` matches `policy.artifact_glob`.
12. No unregistered artifacts OTHER THAN `allowed_candidate_filename`.
13. No orphan sidecars OTHER THAN sidecar of `allowed_candidate_filename`.

Returns `(True, [])` or `(False, [errors])`.

### verify_raw_chain(directory, policy)

Full chain verification after manifest publication. This function does NOT accept `allowed_candidate_filename` — it demands zero orphans, zero unregistered, zero unresolved markers.

Checks (per entry + global):
1. All `verify_candidate_physical` checks for every entry (no exceptions).
2. `manifest_hash` recalculated correctly for every entry.
3. `previous_manifest_hash` links correct for every entry.
4. `sequence` continuous (0, 1, 2, ...).
5. No unregistered artifacts matching `policy.artifact_glob`.
6. No orphan sidecars (sidecar without matching artifact or manifest entry).
7. No unresolved markers (`*_txn_*.marker` files in directory).
8. No files in `.quarantine/` directory.
9. No files in `.pending/` directory (staging files must be cleaned up).

Returns `{"chain_status": "VALID_CHAIN" | "EMPTY_CHAIN" | "BOOTSTRAP_REQUIRED" | "INVALID_CHAIN", "errors": [...], "unregistered_files": [...], "orphan_sidecars": [...], "unresolved_markers": [...], "sequence_count": N}`.

---

## A2 — SealedRawArtifact (C5 corrected)

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

### seal() Behavior (C5)

1. Close gzip handle.
2. `os.fstat(staging_fd)` → capture `st_dev`, `st_ino`, `st_size`.
3. `os.chmod(staging_path, 0o444)` — set read-only.
4. `os.fsync(staging_fd)`.
5. Re-read gzip from disk with `load_raw_events_strict()`.
6. Recalculate all metadata from disk content.
7. Return `SealedRawArtifact` with all fields populated.

### Under-lock Validation (C5)

After acquiring lock, before hardlink:
1. `stat(staging_path)` → compare `st_dev`, `st_ino`, `st_size` with sealed values.
2. `stat(target_directory)` → compare `st_dev` with staging `st_dev` (must be same filesystem for hardlink).
3. Verify staging is not a symlink (`os.path.islink` → False).
4. Recompute `file_sha256` from staging bytes → compare with sealed.
5. Re-read staging with `load_raw_events_strict()` → compare event_count, condition_ids, canonical_events_sha256.

After hardlink (staging → final):
1. `stat(final_path)` → compare `st_dev`, `st_ino`, `st_size` with staging.
2. `stat(staging_path)` → must still have same `st_dev`, `st_ino` (hardlink = same inode).
3. Recompute `file_sha256` from final → must match.

Any difference: `BLOCK` before manifest publication. Do not publish manifest. Preserve all evidence.

---

## A3 — Canonicalization (unchanged, confirmed)

```python
def canonical_payload_sha256(payload: Any) -> str:
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()
```

Rules: `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, list order preserved, output is 64-char lowercase hex.

---

## A4 — Hash Differentiation (unchanged, confirmed)

- **manifest_hash_input_bytes**: canonical JSON of entry excluding `manifest_hash` key.
- **manifest_file_bytes**: canonical JSON of entry including `manifest_hash` key.
- **candidate_manifest_bytes_sha256**: SHA-256 of `manifest_file_bytes`. Stored in marker. Recovery verifies manifest file on disk has this exact SHA.

---

## A5 — Sidecar (unchanged, confirmed)

Format: exactly `<64 lowercase hex chars>\n` (65 bytes). Validated with `re.compile(rb'^[0-9a-f]{64}\n$')`.

---

## A6 — Recovery Matrix (C2, C3, C7 corrected)

### Rules (C2)

The marker may be one state behind the filesystem. "Exacto" means names, hashes, inode (when applicable), and candidate bytes all match the marker.

If a component is present but does not match exactly: `BLOCK`.

The presence of the next component is NOT automatically a contradiction — it may indicate the marker wasn't updated before crash.

### Complete Matrix (C3, C7)

| Marker Status | Artifact | Sidecar | Manifest | Chain | Action |
|---|---|---|---|---|---|
| STAGED | absent | absent | absent | n/a | CONTINUE (publish from STAGED) |
| STAGED | exact present | absent | absent | n/a | CONTINUE (resume from ARTIFACT_PUBLISHED) |
| STAGED | exact present | exact present | absent | n/a | CONTINUE (resume from SIDECAR_PUBLISHED) |
| STAGED | exact present | exact present | exact present | n/a | CONTINUE (resume from MANIFEST_PUBLISHED) |
| STAGED | present but not exact | * | * | * | BLOCK |
| STAGED | absent | present | * | * | BLOCK |
| STAGED | absent | absent | present | * | BLOCK |
| STAGED | staging corrupt/unreadable | n/a | n/a | n/a | QUARANTINE |
| ARTIFACT_PUBLISHED | exact present | absent | absent | n/a | CONTINUE (publish sidecar) |
| ARTIFACT_PUBLISHED | exact present | exact present | absent | n/a | CONTINUE (resume from SIDECAR_PUBLISHED) |
| ARTIFACT_PUBLISHED | exact present | exact present | exact present | n/a | CONTINUE (resume from MANIFEST_PUBLISHED) |
| ARTIFACT_PUBLISHED | absent | * | * | * | BLOCK |
| ARTIFACT_PUBLISHED | present but not exact | * | * | * | BLOCK |
| ARTIFACT_PUBLISHED | exact present | present but not exact | * | * | BLOCK |
| SIDECAR_PUBLISHED | exact present | exact present | absent | n/a | CONTINUE (publish manifest) |
| SIDECAR_PUBLISHED | exact present | exact present | exact present | n/a | CONTINUE (resume from MANIFEST_PUBLISHED) |
| SIDECAR_PUBLISHED | absent | * | * | * | BLOCK |
| SIDECAR_PUBLISHED | present but not exact | * | * | * | BLOCK |
| SIDECAR_PUBLISHED | exact present | absent | * | * | BLOCK |
| SIDECAR_PUBLISHED | exact present | present but not exact | * | * | BLOCK |
| MANIFEST_PUBLISHED | exact present | exact present | exact present | valid | COMMIT |
| MANIFEST_PUBLISHED | exact present | exact present | exact present | invalid | BLOCK |
| MANIFEST_PUBLISHED | absent | * | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | absent | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | * | absent | * | BLOCK |
| MANIFEST_PUBLISHED | present but not exact | * | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | present but not exact | * | * | BLOCK |
| MANIFEST_PUBLISHED | * | * | present but not exact | * | BLOCK |
| MANIFEST_PUBLISHED | exact all | exact all | exact all | valid but candidate bytes mismatch | BLOCK |
| COMMITTED | present | present | present | valid | CLEAN (verify manifest matches marker candidate, then remove marker + staging) |
| COMMITTED | any absent | * | * | * | BLOCK |
| COMMITTED | * | any absent | * | * | BLOCK |
| COMMITTED | * | * | any absent | * | BLOCK |
| COMMITTED | present | present | present | invalid | BLOCK |
| COMMITTED | present | present | present | valid but marker candidate != manifest on disk | BLOCK |
| QUARANTINED | * | * | * | * | BLOCK (report unresolved; do not auto-resolve) |
| corrupt marker | * | * | * | * | QUARANTINE (move marker to .quarantine/) |
| no marker, orphan artifact | present | * | * | * | BLOCK (orphan) |
| no marker, orphan sidecar | * | present | * | * | BLOCK (orphan) |
| no marker, orphan manifest | * | * | present | * | BLOCK (orphan) |
| stale marker temp (*.tmp in marker path) | * | * | * | * | QUARANTINE (move temp to .quarantine/) |
| two markers, same sequence | * | * | * | * | BLOCK (cannot resolve which is canonical) |
| two markers, same transaction_uuid | * | * | * | * | BLOCK (duplicate UUID) |
| manifest without marker | * | * | present | * | BLOCK (orphan manifest) |
| sidecar without artifact | absent | present | * | * | BLOCK (orphan sidecar) |
| sidecar without marker | * | present | * | * | BLOCK (orphan sidecar) |
| candidate bytes hash incorrect (marker) | * | * | * | * | BLOCK |
| candidate dict != candidate bytes (marker) | * | * | * | * | BLOCK |
| unsafe path in marker (contains `..` or absolute) | * | * | * | * | QUARANTINE |
| symlink in marker paths | * | * | * | * | QUARANTINE |
| marker version unknown | * | * | * | * | QUARANTINE |
| marker status unknown | * | * | * | * | QUARANTINE |
| chain previa corrupta | * | * | * | invalid | BLOCK (cannot publish on corrupt chain) |

Actions:
- **CONTINUE**: Resume publication from the effective state (which may be ahead of marker).
- **COMMIT**: Verify all components exact + chain valid + manifest matches marker candidate. Then remove marker + staging.
- **BLOCK**: Preserve all evidence. Do not move or delete. Report as unresolved. New publications refused.
- **QUARANTINE**: Marker is corrupt or evidence is contradictory. Move marker to `.quarantine/`. Report as unresolved. New publications refused.
- **CLEAN**: Only after COMMITTED verification passes. Remove marker and staging file.

---

## A7 — Fault Injection (C8 corrected: five points)

### Fault Points

```
AFTER_STAGED_FSYNC         — After marker STAGED is persisted + fsync'd
AFTER_ARTIFACT_FSYNC       — After artifact hardlink + dir fsync
AFTER_SIDECAR_FSYNC        — After sidecar hardlink + dir fsync
AFTER_MANIFEST_FSYNC       — After manifest O_EXCL write + dir fsync
AFTER_COMMITTED_FSYNC      — After marker COMMITTED + dir fsync
```

### Execution Model (C8)

All execution is via subprocess. The parent test process never calls the publisher directly.

```
Parent test process:
  1. Prepare filesystem (create staging, seal artifact)
  2. Fork subprocess A: publisher with fault_after=<POINT>
     → Subprocess A calls _publish_raw_scan_with_fault_hook()
     → At the fault point: os._exit(99)
     → Parent checks returncode == 99
  3. Fork subprocess B: recovery
     → Subprocess B calls recover_incomplete_transactions()
     → Returns result as JSON on stdout
     → os._exit(0)
  4. Parent reads subprocess B stdout
  5. Parent verifies final state (chain, markers, quarantine, staging)
```

No `SystemExit`. No `except` blocks in the fault path. `os._exit(99)` terminates immediately without cleanup.

---

## A8 — API Without Identity Duplication (C6 corrected: transfer token)

### Canonical API

```python
# Stage events
with RawScanStager(run_id=run_id, scan_id=scan_id, raw_dir=V3_RAW_CHAIN_DIR) as stager:
    for market in markets:
        process_market_v3(..., raw_event_sink=stager)
    sealed = stager.seal()
    transfer = stager.transfer()

# Publish
publish_raw_scan(
    directory=V3_RAW_CHAIN_DIR,
    transfer=transfer,
    policy=RAW_MANIFEST_POLICY,
)
```

### RawArtifactTransfer

```python
@dataclass(frozen=True)
class RawArtifactTransfer:
    sealed: SealedRawArtifact
    ownership_token: str       # UUID4
    staging_path: Path         # Resolved absolute path

    # Lifecycle callback (not called by publisher directly;
    # publisher calls these via the transfer object)
    def mark_transferred(self) -> None: ...
    def mark_published(self) -> None: ...
    def mark_recoverable_error(self, failure_stage: str, failure_message: str) -> None: ...
    def mark_blocked(self, failure_stage: str, failure_message: str) -> None: ...
```

### stager.transfer()

```python
def transfer(self) -> RawArtifactTransfer:
    """Transfer ownership of staging to publisher.

    Must be called after seal(). Sets stager state to TRANSFERRED.
    After this call, stager.__exit__ will NOT delete the staging file.
    """
    if not self._sealed:
        raise RuntimeError("Cannot transfer before seal()")
    self._transferred = True
    return RawArtifactTransfer(
        sealed=self._sealed_descriptor,
        ownership_token=str(uuid.uuid4()),
        staging_path=self._staging_path.resolve(),
    )
```

### publish_raw_scan

```python
def publish_raw_scan(
    directory: Path,
    transfer: RawArtifactTransfer,
    policy: ManifestPolicy,
) -> dict[str, Any]:
    sealed = transfer.sealed
    # Identity comes exclusively from sealed.run_id and sealed.scan_id
    # No identity_fields parameter
    ...
    transfer.mark_transferred()
    try:
        ...
        transfer.mark_published()
    except RecoverableError as e:
        transfer.mark_recoverable_error(e.stage, str(e))
        raise
    except UnrecoverableError as e:
        transfer.mark_blocked(e.stage, str(e))
        raise
```

---

## A9 — Runtime Edge Cases (C10 corrected: fail-closed)

### Publication Failure (C10)

If `publish_raw_scan()` fails:
- `run_scan_v3` catches the error.
- Does NOT continue to snapshot generation.
- Does NOT persist snapshot final.
- Does NOT declare scan complete.
- `scan_status = "BLOCKED_RAW_INTEGRITY"`.
- INV-005 = `FAIL`.
- Marker/staging/evidence preserved.
- Only recovery on next cycle can resolve.

### All Edge Cases (from previous version, confirmed)

| Case | Behavior |
|---|---|
| Zero markets | No stager created. No artifact. INV-005 = NOT_APPLICABLE for this scan. |
| Zero Data API queries | Stager sealed with event_count=0. Empty artifact published. |
| Empty Data API response | Valid event with empty payload. `payload_sha256` computed from `[]`. |
| Partial failures | Events already in staging preserved. Remaining markets continue. Seal with collected events. |
| Exception before first raw event | Stager sealed with event_count=0. Empty artifact. |
| Exception after first raw event | Events preserved. Seal with collected events. |
| Zero raw events total | Empty artifact published. |
| Duplicate condition IDs | Both events stored. `condition_ids` deduplicated in manifest. |
| Publication failure | `scan_status = BLOCKED_RAW_INTEGRITY`. No snapshot. No COMPLETE_VALIDATED. |

---

## A10 — Legacy Strategy (unchanged, confirmed)

```
results/h011_v3/raw/           ← Legacy daily-append (DEPRECATED for V3)
results/h011_v3/raw_chain_v1/  ← New immutable per-scan chain
```

No automatic migration. New chain starts empty. INV-005 checks `raw_chain_v1/`.

---

## A11 — Ownership and States (C6 corrected)

### Stager States

```
OPEN                               — Stager created, staging file open for append
  ↓ seal()
SEALED                             — Staging file closed, read-only, SealedRawArtifact returned
  ↓ transfer()
TRANSFERRED                        — Ownership transferred to publisher via RawArtifactTransfer
  ↓ publish success
PUBLISHED                          — Staging file removed, marker COMMITTED
  ↓ publish failure (recoverable)
RECOVERABLE_ERROR_AFTER_TRANSFER   — Marker at failure_stage, recovery will complete
  ↓ publish failure (unrecoverable)
BLOCKED_AFTER_TRANSFER             — Marker BLOCKED, evidence preserved, manual intervention
```

```
OPEN                               — Stager created
  ↓ exception before seal()
ABORTED_BEFORE_TRANSFER            — Staging file deleted by context manager
```

```
SEALED                             — Sealed but not transferred
  ↓ context manager exit without transfer
ABORTED_BEFORE_TRANSFER            — Staging file deleted (orphan cleanup)
```

### Context Manager Behavior

- `OPEN` + exception → delete staging, state = `ABORTED_BEFORE_TRANSFER`
- `SEALED` + not transferred → delete staging (orphan), state = `ABORTED_BEFORE_TRANSFER`
- `TRANSFERRED` → do nothing (publisher owns lifecycle via marker)
- `PUBLISHED` → do nothing (already cleaned up)
- `RECOVERABLE_ERROR_AFTER_TRANSFER` → do nothing (marker owns recovery)
- `BLOCKED_AFTER_TRANSFER` → do nothing (evidence preserved)

---

## A12 — Concurrency (C13 corrected: no flock contradiction)

### Lock

```python
lock_path = directory / f"{policy.manifest_prefix}.lock"
lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
```

### Properties

- **Multi-process**: `fcntl.flock` advisory but works across processes on same host.
- **Recovery under same lock**: `recover_incomplete_transactions()` called inside lock by `publish_raw_scan()`. No separate lock.
- **No nested locking**: All operations under single lock. No function called from within re-acquires.
- **No timeout**: `flock(LOCK_EX)` blocks indefinitely. Kernel releases on process death.

### Filesystem Without flock (C13)

If `fcntl.flock` raises `OSError` (unsupported):
- Publication refused.
- `scan_status = "BLOCKED_RAW_INTEGRITY"`.
- INV-005 = `FAIL` if a chain exists or an eligible scan has been seen.
- INV-005 = `UNKNOWN` only before any eligible scan (empty chain, no eligibility state).

No contradiction. No fallback. No silent ignore.

---

## A13 — INV-005 Semantics (C11, C12 corrected)

### Separation of Read and Write (C11)

**Write operation (mutating):**
```python
recover_raw_transactions(directory, policy)  # Under lock. Mutates filesystem.
```
Called by:
- Runtime at startup
- `publish_raw_scan()` before publishing
- Never by INV-005

**Read operations (non-mutating):**
```python
inspect_raw_transaction_state(directory, policy)  # Read-only. Returns state.
verify_raw_chain(directory, policy)                # Read-only. Returns chain status.
```
Called by:
- INV-005 evaluator
- Dashboard
- Any read-only inspector

INV-005 does NOT call `recover_raw_transactions()`. It only inspects.

### Persisted Eligibility State (C12)

A small JSON file at `raw_chain_v1/.eligibility_state.json`:

```json
{
  "schema_version": "h011-eligibility-v1",
  "first_eligible_scan_seen": true,
  "first_eligible_scan_id": "2026-07-13T10:00:00Z",
  "first_persistible_data_api_request_at": "2026-07-13T10:00:01Z",
  "state_sha256": "..."
}
```

**Who persists:** `run_scan_v3` after the first market reaches Data API (i.e., the first market that is not rejected before Data API).

**When fsynced:** Immediately after write, with directory fsync.

**Integrity:** `state_sha256` is computed from the canonical JSON of all fields except `state_sha256` itself. Verified on read. If corrupt: treated as `first_eligible_scan_seen=false`.

### INV-005 Decision Table (C12, C13)

```
EMPTY_CHAIN + first_eligible_scan_seen=false:
    UNKNOWN
    (No manifests, no artifacts. No eligible scan has run yet.)

EMPTY_CHAIN + first_eligible_scan_seen=true:
    FAIL
    (An eligible scan ran but produced no artifact. Chain is broken.)

VALID_CHAIN + no unresolved markers + no quarantine + no orphans:
    PASS

VALID_CHAIN + unresolved markers or quarantine or orphans:
    FAIL

BOOTSTRAP_REQUIRED:
    FAIL

INVALID_CHAIN:
    FAIL

flock unsupported + chain exists or first_eligible_scan_seen=true:
    FAIL

flock unsupported + empty chain + first_eligible_scan_seen=false:
    UNKNOWN

Zero markets in current scan + EMPTY_CHAIN + first_eligible_scan_seen=false:
    NOT_APPLICABLE (for this scan; does not alter chain state)
```

---

## C9 — Retries of run_id and scan_id

```
same run_id + same scan_id + same artifact hash (file_sha256):
    IDEMPOTENT_SUCCESS — return existing manifest entry, do not create new sequence.

same run_id + same scan_id + different artifact hash:
    BLOCK — duplicate identity with different content.

run_id repeated + scan_id different:
    BLOCK — run_id must be unique.

scan_id repeated + run_id different:
    BLOCK — scan_id must be unique.
```

No new sequence is created in any of these cases. The existing chain is not modified.

---

## C14 — PR Body

After committing this design doc:

```bash
HEAD_SHA="$(git rev-parse HEAD)"
```

PR body will contain:

```
Current head: <HEAD_SHA EXACTO>
Design base code SHA: 18f8e6dea12c25a4dc338b0a0fdb2bccc417540b
Phase: transaction redesign — architecture correction
Code implementation paused
Tests: 247/247 existing
Production: 2f850353 untouched
PR: Draft
```

---

## Summary: C1–C14 Status

| ID | Topic | Status |
|---|---|---|
| C1 | PR body with real SHA (no invented) | ✅ Resolved |
| C2 | Recovery: marker may be behind filesystem; "exacto" matching; presence of next component is not contradiction | ✅ Resolved |
| C3 | COMMITTED: no wildcards; verify all components present + valid + manifest matches marker candidate | ✅ Resolved |
| C4 | verify_candidate_logical (pre-publish), verify_candidate_physical (post artifact+sidecar, with allowed_candidate_filename), verify_raw_chain (post-manifest, strict, no exceptions) | ✅ Resolved |
| C5 | SealedRawArtifact: device_id, inode, size_bytes mandatory; seal() chmod read-only + fsync; under-lock stat comparison; post-hardlink inode check | ✅ Resolved |
| C6 | RawArtifactTransfer with ownership_token; stager.transfer() returns transfer; publish_raw_scan receives transfer, not sealed directly; no private attribute access | ✅ Resolved |
| C7 | Recovery matrix: exhaustive rows for stale temp, duplicate sequence, duplicate UUID, orphan manifest, orphan sidecar, candidate bytes mismatch, unsafe path, symlink, unknown version, unknown status, corrupt chain, COMMITTED with missing components, QUARANTINED/BLOCKED residual | ✅ Resolved |
| C8 | Fault injection: 5 points (AFTER_STAGED_FSYNC through AFTER_COMMITTED_FSYNC); subprocess + os._exit(99); recovery in separate subprocess | ✅ Resolved |
| C9 | Retries: same identity + same hash = IDEMPOTENT_SUCCESS; same identity + different hash = BLOCK; repeated run_id or scan_id = BLOCK | ✅ Resolved |
| C10 | Publication failure: fail-closed; no snapshot; no COMPLETE_VALIDATED; scan_status=BLOCKED_RAW_INTEGRITY; evidence preserved | ✅ Resolved |
| C11 | INV-005 read-only: does not call recovery; separate recover_raw_transactions (write) from inspect/verify (read) | ✅ Resolved |
| C12 | Persisted eligibility state: .eligibility_state.json with first_eligible_scan_seen; EMPTY_CHAIN + seen=true = FAIL; fsync + integrity hash | ✅ Resolved |
| C13 | Filesystem without flock: publication refused; BLOCKED_RAW_INTEGRITY; FAIL if chain/eligibility exists; UNKNOWN only before first eligible scan | ✅ Resolved |
| C14 | PR body with exact SHA from git rev-parse HEAD | ✅ Resolved |

**Zero open decisions.**
