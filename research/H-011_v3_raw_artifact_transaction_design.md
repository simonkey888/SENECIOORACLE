# H-011 V3 — Raw Artifact Transaction Design

## Status: DESIGN DOCUMENT — Architecture Finalized (D1–D8)

**Design base code SHA:** `18f8e6dea12c25a4dc338b0a0fdb2bccc417540b`
**Date:** 2026-07-13
**Branch:** `feat/h011-v3-control-plane-coverage`
**Production:** `2f850353` (untouched)
**PR:** #5 Draft

---

## A1 — Verification Functions (D1, D8 corrected)

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

### verify_committing_transaction(directory, marker, candidate_entry, policy)  (D1)

After manifest publication, before cleanup. The marker (`MANIFEST_PUBLISHED`) and staging file still exist.

Checks:
1. `verify_candidate_logical(existing_entries_excluding_current, candidate_entry)` — logical checks against prior entries only.
2. `verify_manifest_entry_physical(directory, candidate_entry, policy)` — physical checks on the now-manifested entry (see below).
3. Marker exists and status == `MANIFEST_PUBLISHED`.
4. Marker's `candidate_manifest_bytes_sha256` == SHA-256 of manifest file on disk.
5. Staging file still exists (hasn't been cleaned up yet).
6. No OTHER markers exist (only the current transaction's marker).
7. No OTHER staging files in `.pending/` (only the current transaction's staging).

Returns `(True, [])` or `(False, [errors])`.

### verify_manifest_entry_physical(directory, entry, policy)  (D8)

For entries that are already manifested (part of the chain). No `allowed_candidate_filename` parameter — strict.

Checks:
1. Artifact `directory / entry["filename"]` exists, is a regular file, not symlink.
2. Sidecar `directory / (filename + ".sha256")` exists, is a regular file.
3. Sidecar content matches `^[0-9a-f]{64}\n$`.
4. Sidecar content (stripped) == `entry["file_sha256"]`.
5. Recompute SHA-256 of artifact file bytes == sidecar content == `entry["file_sha256"]`.
6. `load_raw_events_strict(artifact_path)` succeeds.
7. `len(disk_events) == entry["event_count"]`.
8. `sorted({e["requested_condition_id"] for e in disk_events if e.get("requested_condition_id")})` == `entry["condition_ids"]`.
9. Recompute `canonical_events_sha256` from disk events and compare.
10. For each event: recompute `payload_sha256` and compare.
11. `filename` matches `policy.artifact_glob`.

Returns `(True, [])` or `(False, [errors])`.

### verify_raw_chain(directory, policy) — Steady State Only (D1)

**Only for steady state** (no active transaction). Demands:
1. All `verify_manifest_entry_physical` checks for every entry.
2. `manifest_hash` recalculated correctly for every entry.
3. `previous_manifest_hash` links correct for every entry.
4. `sequence` continuous (0, 1, 2, ...).
5. Zero unregistered artifacts matching `policy.artifact_glob`.
6. Zero orphan sidecars.
7. Zero unresolved markers (`*_txn_*.marker` files in directory).
8. Zero files in `.quarantine/` directory.
9. Zero files in `.pending/` directory (staging files must be cleaned up).

Returns `{"chain_status": ..., "errors": [...], ...}`.

### Publication Sequence (D1)

```
verify_candidate_logical          → in memory, before touching disk
publish artifact                  → hardlink
publish sidecar                   → hardlink
verify_candidate_physical         → read artifact + sidecar from disk (allowed_candidate_filename set)
publish manifest                  → O_CREAT|O_EXCL
persist marker MANIFEST_PUBLISHED → atomic temp + rename + fsync
verify_committing_transaction     → allows current marker + staging; no others
persist marker COMMITTED          → atomic temp + rename + fsync
cleanup marker + staging          → unlink + dir fsync
verify_raw_chain                  → steady-state verification (zero markers, zero pending)
```

If steady-state verification fails after cleanup:
- `BLOCKED_RAW_INTEGRITY`
- Preserve diagnosis (log all errors)
- Do not declare success
- Do not proceed to snapshot

---

## A2 — SealedRawArtifact (D2 corrected: seal order)

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
    device_id: int                        # os.fstat(fd).st_dev
    inode: int                            # os.fstat(fd).st_ino
```

### seal() Definitive Order (D2)

```
1. gzip_handle.flush()
2. gzip_handle.close()                    # writes gzip footer + CRC
3. fd = os.open(staging_path, O_RDONLY)
4. os.fsync(fd)
5. st = os.fstat(fd)                      # capture st_dev, st_ino, st_size
6. os.close(fd)
7. os.chmod(staging_path, 0o444)          # read-only
8. fsync(.pending directory)              # dir_fd = os.open(.pending, O_RDONLY); os.fsync(dir_fd); close
9. strict reread: load_raw_events_strict(staging_path)
10. recalculate event_count, condition_ids, canonical_events_sha256 from disk
11. recalculate file_sha256 from disk bytes
12. build SealedRawArtifact with all fields
13. return SealedRawArtifact
```

If any step fails: state = `ABORTED_BEFORE_TRANSFER`. No transfer. No marker. Staging file is NOT cleaned up by seal() (the context manager will clean it up if not transferred).

### Under-lock Validation (unchanged from C5)

After acquiring lock, before hardlink:
1. `stat(staging_path)` → compare `st_dev`, `st_ino`, `st_size` with sealed values.
2. `stat(target_directory)` → compare `st_dev` with staging `st_dev` (same filesystem for hardlink).
3. Verify staging is not a symlink.
4. Recompute `file_sha256` from staging bytes → compare with sealed.
5. Re-read staging with `load_raw_events_strict()` → compare event_count, condition_ids, canonical_events_sha256.

After hardlink (staging → final):
1. `stat(final_path)` → compare `st_dev`, `st_ino`, `st_size` with staging.
2. `stat(staging_path)` → must still have same `st_dev`, `st_ino` (hardlink = same inode).
3. Recompute `file_sha256` from final → must match.

Any difference: `BLOCK` before manifest publication. Preserve all evidence.

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

Rules: `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, list order preserved, 64-char lowercase hex.

---

## A4 — Hash Differentiation (unchanged, confirmed)

- **manifest_hash_input_bytes**: canonical JSON of entry excluding `manifest_hash` key.
- **manifest_file_bytes**: canonical JSON of entry including `manifest_hash` key.
- **candidate_manifest_bytes_sha256**: SHA-256 of `manifest_file_bytes`. Stored in marker. Recovery verifies manifest file on disk has this exact SHA.

---

## A5 — Sidecar (unchanged, confirmed)

Format: exactly `<64 lowercase hex chars>\n` (65 bytes). Validated with `re.compile(rb'^[0-9a-f]{64}\n$')`.

---

## A6 — Recovery Matrix (unchanged from C7, confirmed)

### Rules (C2)

The marker may be one state behind the filesystem. "Exacto" means names, hashes, inode (when applicable), and candidate bytes all match the marker.

If a component is present but does not match exactly: `BLOCK`.

The presence of the next component is NOT automatically a contradiction — it may indicate the marker wasn't updated before crash.

### Complete Matrix

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
| stale marker temp (*.tmp) | * | * | * | * | QUARANTINE |
| two markers, same sequence | * | * | * | * | BLOCK |
| two markers, same transaction_uuid | * | * | * | * | BLOCK |
| manifest without marker | * | * | present | * | BLOCK (orphan manifest) |
| sidecar without artifact | absent | present | * | * | BLOCK (orphan sidecar) |
| sidecar without marker | * | present | * | * | BLOCK (orphan sidecar) |
| candidate bytes hash incorrect (marker) | * | * | * | * | BLOCK |
| candidate dict != candidate bytes (marker) | * | * | * | * | BLOCK |
| unsafe path in marker | * | * | * | * | QUARANTINE |
| symlink in marker paths | * | * | * | * | QUARANTINE |
| marker version unknown | * | * | * | * | QUARANTINE |
| marker status unknown | * | * | * | * | QUARANTINE |
| chain previa corrupta | * | * | * | invalid | BLOCK |

Actions: CONTINUE, COMMIT, BLOCK, QUARANTINE, CLEAN (defined in previous version, unchanged).

---

## A7 — Fault Injection (unchanged from C8, confirmed)

Five fault points: `AFTER_STAGED_FSYNC`, `AFTER_ARTIFACT_FSYNC`, `AFTER_SIDECAR_FSYNC`, `AFTER_MANIFEST_FSYNC`, `AFTER_COMMITTED_FSYNC`.

All via subprocess + `os._exit(99)`. Recovery in separate subprocess. Parent only prepares filesystem, runs publisher subprocess, checks returncode 99, runs recovery subprocess, inspects result.

---

## A8 — API (D5 corrected: transfer lifecycle)

### Canonical API

```python
# Stage events
with RawScanStager(run_id=run_id, scan_id=scan_id, raw_dir=V3_RAW_CHAIN_DIR) as stager:
    for market in markets:
        process_market_v3(..., raw_event_sink=stager)
    sealed = stager.seal()
    transfer = stager.transfer()

# Publish
result = publish_raw_scan(
    directory=V3_RAW_CHAIN_DIR,
    transfer=transfer,
    policy=RAW_MANIFEST_POLICY,
)
```

### RawArtifactTransfer (D5: immutable, no callbacks)

```python
@dataclass(frozen=True)
class RawArtifactTransfer:
    sealed: SealedRawArtifact
    ownership_token: str       # UUID4
    staging_path: Path         # Resolved absolute path
```

No callbacks. No mutable methods. The transfer is an immutable descriptor.

### stager.transfer() (D5: single transition)

```python
def transfer(self) -> RawArtifactTransfer:
    """Single transition: SEALED → TRANSFERRED.
    After this call, stager.__exit__ will NOT delete the staging file.
    The marker durable is the sole authority for lifecycle after this point.
    """
    if not self._sealed:
        raise RuntimeError("Cannot transfer before seal()")
    self._transferred = True  # Single transition
    return RawArtifactTransfer(
        sealed=self._sealed_descriptor,
        ownership_token=str(uuid.uuid4()),
        staging_path=self._staging_path.resolve(),
    )
```

### publish_raw_scan (D5: no mark_transferred callback)

```python
def publish_raw_scan(
    directory: Path,
    transfer: RawArtifactTransfer,
    policy: ManifestPolicy,
) -> PublishResult:
    sealed = transfer.sealed
    # Identity exclusively from sealed.run_id and sealed.scan_id
    ...
    # After success:
    return PublishResult(status="PUBLISHED", manifest_entry=entry)
    # After recoverable failure:
    return PublishResult(status="RECOVERABLE_ERROR", failure_stage=..., failure_message=...)
    # After blocked failure:
    return PublishResult(status="BLOCKED", failure_stage=..., failure_message=...)
```

```python
@dataclass(frozen=True)
class PublishResult:
    status: str  # "PUBLISHED" | "RECOVERABLE_ERROR" | "BLOCKED"
    manifest_entry: dict | None = None
    failure_stage: str | None = None
    failure_message: str | None = None
```

The marker durable is the sole authority. After crash, recovery reconstructs everything from marker + filesystem. In-memory state is observational only.

---

## A9 — Runtime Edge Cases (D6 corrected: exception classification)

### Exception Hierarchy (D6)

```
RecoverableMarketDataError
  → Register source health (DEGRADED for that source)
  → Continue with other markets
  → Event NOT appended to staging

MarketRejected (identity, temporal, metadata, no trades)
  → Register rejection
  → Continue with other markets
  → Event IS appended to staging (for rejected markets that reached Data API)

RawEventPersistenceError
  → Stop scan immediately
  → scan_status = BLOCKED_RAW_INTEGRITY
  → Do NOT seal/publish partial artifact as valid
  → Do NOT generate snapshot
  → Preserve staging for diagnosis

RawArtifactTransactionError
  → Stop scan immediately
  → scan_status = BLOCKED_RAW_INTEGRITY
  → Do NOT generate snapshot
  → Marker/staging/evidence preserved

IdentityCollisionError
  → Stop scan immediately
  → scan_status = BLOCKED_RAW_INTEGRITY

UnexpectedInternalError (after raw event persisted)
  → Stop scan
  → Preserve staging
  → Do NOT present partial artifact as scan complete
  → scan_status = BLOCKED_RAW_INTEGRITY
```

### Partial Artifact Policy (D6)

A partial artifact (scan that collected some events but crashed before completing all markets) is NOT published as a valid scan. The staging file is preserved for diagnosis but `publish_raw_scan` is NOT called.

Only a complete scan (all markets processed, even if some rejected) proceeds to seal + publish.

### Publication Failure (C10, confirmed)

If `publish_raw_scan()` fails:
- `scan_status = "BLOCKED_RAW_INTEGRITY"`.
- No snapshot generation.
- No `COMPLETE_VALIDATED`.
- INV-005 = `FAIL`.
- Evidence preserved.
- Only recovery on next cycle can resolve.

### All Edge Cases

| Case | Behavior |
|---|---|
| Zero markets | No stager created. No artifact. INV-005 = NOT_APPLICABLE for this scan. |
| Zero Data API queries | Stager sealed with event_count=0. Empty artifact published. |
| Empty Data API response | Valid event with empty payload. `payload_sha256` computed from `[]`. |
| RecoverableMarketDataError | Skip that market. Continue. Event NOT appended. |
| MarketRejected | Continue. Event IS appended (if reached Data API). |
| RawEventPersistenceError | Stop. BLOCKED_RAW_INTEGRITY. No publish. |
| RawArtifactTransactionError | Stop. BLOCKED_RAW_INTEGRITY. No snapshot. |
| IdentityCollisionError | Stop. BLOCKED_RAW_INTEGRITY. |
| UnexpectedInternalError after raw persist | Stop. Preserve staging. No partial publish. |
| Partial scan (crash mid-market) | Staging preserved. NOT published as valid. |
| Publication failure | BLOCKED_RAW_INTEGRITY. No snapshot. Evidence preserved. |

---

## A10 — Legacy Strategy (unchanged, confirmed)

```
results/h011_v3/raw/           ← Legacy daily-append (DEPRECATED for V3)
results/h011_v3/raw_chain_v1/  ← New immutable per-scan chain
```

No automatic migration. New chain starts empty. INV-005 checks `raw_chain_v1/`.

---

## A11 — Ownership and States (D5 corrected)

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

SEALED                             — Sealed but not transferred
  ↓ context manager exit without transfer
ABORTED_BEFORE_TRANSFER            — Staging file deleted (orphan cleanup)
```

Single transition from `SEALED` → `TRANSFERRED` via `stager.transfer()`. No `mark_transferred()` callback in publisher. The marker durable is the sole authority after TRANSFERRED.

### Context Manager Behavior

- `OPEN` + exception → delete staging, state = `ABORTED_BEFORE_TRANSFER`
- `SEALED` + not transferred → delete staging (orphan), state = `ABORTED_BEFORE_TRANSFER`
- `TRANSFERRED` → do nothing (publisher owns lifecycle via marker)
- `PUBLISHED` → do nothing (already cleaned up)
- `RECOVERABLE_ERROR_AFTER_TRANSFER` → do nothing (marker owns recovery)
- `BLOCKED_AFTER_TRANSFER` → do nothing (evidence preserved)

---

## A12 — Concurrency (D4 corrected: locking API)

### Lock

```python
lock_path = directory / f"{policy.manifest_prefix}.lock"
lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
```

### Recovery API (D4)

**Public (acquires lock):**
```python
def recover_raw_transactions(directory: Path, policy: ManifestPolicy) -> list[dict]:
    """Public recovery API. Acquires flock, calls internal, releases flock."""
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _recover_raw_transactions_under_lock(directory, policy)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

**Private (caller already holds lock):**
```python
def _recover_raw_transactions_under_lock(directory: Path, policy: ManifestPolicy) -> list[dict]:
    """Internal recovery. Caller MUST already hold the lock.
    Raises RuntimeError if called without lock (assertion check via thread-local or parameter).
    """
    ...
```

`publish_raw_scan()` uses `_recover_raw_transactions_under_lock()` (it already holds the lock).
Runtime startup uses `recover_raw_transactions()` (public, acquires lock).

**Nested locking prohibited.** If `publish_raw_scan()` calls `recover_raw_transactions()`, it would deadlock (flock is not recursive in the same process for exclusive locks). The private function exists precisely to avoid this.

### Filesystem Without flock (C13, confirmed)

If `fcntl.flock` raises `OSError`:
- Publication refused.
- `scan_status = "BLOCKED_RAW_INTEGRITY"`.
- INV-005 = `FAIL` if chain exists or eligible scan seen.
- INV-005 = `UNKNOWN` only before first eligible scan.

No timeout. No fallback.

---

## A13 — INV-005 Semantics (D3, D4, D11 corrected)

### Separation of Read and Write (D4)

**Write (mutating, under lock):**
```python
recover_raw_transactions(directory, policy)           # Public, acquires lock
_recover_raw_transactions_under_lock(directory, policy)  # Private, caller holds lock
```

**Read (non-mutating):**
```python
inspect_raw_transaction_state(directory, policy)     # Read-only
verify_raw_chain(directory, policy)                  # Read-only (steady state)
```

INV-005 calls only read functions. Never calls recovery.

### Persisted Eligibility State (D3 corrected: fail-closed)

File: `raw_chain_v1/.eligibility_state.json`

```json
{
  "schema_version": "h011-eligibility-v1",
  "first_eligible_scan_seen": true,
  "first_eligible_scan_id": "2026-07-13T10:00:00Z",
  "first_persistible_data_api_request_at": "2026-07-13T10:00:01Z"
}
```

Integrity: `state_sha256` computed from canonical JSON of all fields except `state_sha256`. Stored as additional field.

**Read rules (D3):**
- File absent: `first_eligible_scan_seen = false`
- File valid (hash matches): use persisted value
- File present but corrupt (invalid JSON, hash mismatch, schema invalid): `BLOCKED_RAW_INTEGRITY`, INV-005 = `FAIL`

**Monotonicity:**
- `false → true` permitted
- `true → false` prohibited (runtime must refuse to overwrite `true` with `false`)

**Write (D3):**
```
exclusive temp file (O_CREAT | O_EXCL)
→ canonical bytes (sort_keys, separators, ensure_ascii=False, allow_nan=False)
→ flush
→ fsync
→ atomic replace (os.rename)
→ directory fsync
```

### INV-005 Decision Table

```
EMPTY_CHAIN + first_eligible_scan_seen=false:
    UNKNOWN

EMPTY_CHAIN + first_eligible_scan_seen=true:
    FAIL

EMPTY_CHAIN + eligibility file corrupt:
    FAIL (BLOCKED_RAW_INTEGRITY)

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

## C9 — Retries (unchanged, confirmed)

```
same run_id + same scan_id + same artifact hash:
    IDEMPOTENT_SUCCESS — return existing manifest entry.

same run_id + same scan_id + different artifact hash:
    BLOCK.

run_id repeated + scan_id different:
    BLOCK.

scan_id repeated + run_id different:
    BLOCK.
```

---

## D7 — Transaction Marker Schema (definitive)

### Complete Schema

```json
{
  "transaction_version": "h011-artifact-txn-v2",
  "transaction_uuid": "<uuid4>",
  "ownership_token": "<uuid4 from RawArtifactTransfer>",
  "status": "STAGED",
  "resolution": "ACTIVE",
  "sequence": 0,
  "run_id": "...",
  "scan_id": "...",
  "staging_filename": "...",
  "final_name": "...",
  "sidecar_name": "...",
  "manifest_name": "...",
  "device_id": 0,
  "inode": 0,
  "size_bytes": 0,
  "file_sha256": "...",
  "canonical_events_sha256": "...",
  "event_count": 0,
  "condition_ids": [],
  "previous_manifest_hash": null,
  "candidate_manifest": {},
  "candidate_manifest_bytes_base64": "...",
  "candidate_manifest_bytes_sha256": "...",
  "manifest_created_at": "2026-07-13T10:00:00Z",
  "failure_stage": null,
  "failure_type": null,
  "failure_message": null,
  "recoverable": true
}
```

### Field Rules

**Required fields** (all must be present):
- `transaction_version`: must be `"h011-artifact-txn-v2"`
- `transaction_uuid`: UUID4 string
- `ownership_token`: UUID4 string
- `status`: one of `STAGED`, `ARTIFACT_PUBLISHED`, `SIDECAR_PUBLISHED`, `MANIFEST_PUBLISHED`, `COMMITTED`
- `resolution`: one of `ACTIVE`, `BLOCKED`, `QUARANTINED`
- `sequence`: non-negative int
- `run_id`: non-empty string
- `scan_id`: non-empty string
- `staging_filename`: filename only (no path), ends with `.tmp`
- `final_name`: filename only, matches `policy.artifact_glob`
- `sidecar_name`: filename only, ends with `.sha256`
- `manifest_name`: filename only, matches `{prefix}_{sequence:06d}.json`
- `device_id`: int
- `inode`: int
- `size_bytes`: int ≥ 0
- `file_sha256`: 64-char lowercase hex
- `canonical_events_sha256`: 64-char lowercase hex
- `event_count`: int ≥ 0
- `condition_ids`: list of strings
- `previous_manifest_hash`: 64-char hex or null
- `candidate_manifest`: dict (full manifest entry including `manifest_hash`)
- `candidate_manifest_bytes_base64`: base64-encoded canonical JSON bytes of `candidate_manifest`
- `candidate_manifest_bytes_sha256`: 64-char hex, SHA-256 of decoded `candidate_manifest_bytes_base64`
- `manifest_created_at`: ISO 8601 UTC string, frozen at creation, never changed by recovery

**Optional fields** (may be null):
- `failure_stage`: string or null (set when failure occurs)
- `failure_type`: string or null
- `failure_message`: string or null
- `recoverable`: bool (true if recovery can complete from this state)

### Marker Integrity Hash

`marker_integrity_sha256` = SHA-256 of canonical JSON of all fields except `marker_integrity_sha256` itself. Stored as additional field. Verified on every marker read.

### `status` vs `resolution` (D7)

- `status` = transaction progress: `STAGED` → `ARTIFACT_PUBLISHED` → `SIDECAR_PUBLISHED` → `MANIFEST_PUBLISHED` → `COMMITTED`
- `resolution` = recovery outcome: `ACTIVE` (in progress or not yet recovered), `BLOCKED` (recovery attempted, unresolved), `QUARANTINED` (corrupt/ambiguous)

Normal path: `resolution` stays `ACTIVE` until `COMMITTED`, then marker is removed.

Recovery sets `resolution` to `BLOCKED` or `QUARANTINED` (not `status`). `status` reflects the last successful filesystem operation.

### Marker Filename

```
{policy.manifest_prefix}_txn_{sequence:06d}_{transaction_uuid}.marker
```

Example: `manifest_txn_000003_550e8400-e29b-41d4-a716-446655440000.marker`

### Marker Operations

**Creation (O_EXCL):**
```
temp_name = f"{marker_name}.tmp.{uuid4()}"
fd = os.open(temp_name, O_CREAT | O_EXCL | O_WRONLY, 0o644)
with os.fdopen(fd, 'wb') as f:
    f.write(canonical_bytes)
    f.flush()
    os.fsync(f.fileno())
os.rename(temp_name, marker_name)
dir_fsync(directory)
```

**Update (atomic replace):**
```
temp_name = f"{marker_name}.tmp.{uuid4()}"
# Same as creation — O_EXCL on temp, then rename to marker_name
```

**Validation before any filesystem operation:**
1. Parse JSON. If invalid → QUARANTINE.
2. Verify `transaction_version` == `"h011-artifact-txn-v2"`. If not → QUARANTINE.
3. Verify `marker_integrity_sha256`. If mismatch → QUARANTINE.
4. Verify all required fields present and correct types. If any invalid → QUARANTINE.
5. Validate paths: `staging_filename`, `final_name`, `sidecar_name`, `manifest_name` are bare filenames (no `/`, `\`, `..`). If invalid → QUARANTINE.
6. Verify `candidate_manifest_bytes_sha256` == SHA-256 of decoded `candidate_manifest_bytes_base64`. If mismatch → QUARANTINE.
7. Verify `candidate_manifest["manifest_hash"]` == recomputed from `candidate_manifest`. If mismatch → QUARANTINE.

---

## Summary: D1–D8 Status

| ID | Topic | Status |
|---|---|---|
| D1 | verify_committing_transaction (post-manifest, pre-cleanup) vs verify_raw_chain (steady-state only); steady-state failure → BLOCKED_RAW_INTEGRITY | ✅ Resolved |
| D2 | seal() definitive order: flush → close → fsync → fstat → chmod → dir fsync → strict reread → calculate → return | ✅ Resolved |
| D3 | Eligibility corrupt → BLOCKED_RAW_INTEGRITY + FAIL (not false); monotonic false→true; atomic write with fsync | ✅ Resolved |
| D4 | Recovery API: public (acquires lock) vs private (caller holds lock); no nested locking | ✅ Resolved |
| D5 | RawArtifactTransfer immutable (no callbacks); stager.transfer() single transition; marker is sole authority after TRANSFERRED | ✅ Resolved |
| D6 | Exception classification: RecoverableMarketDataError, MarketRejected, RawEventPersistenceError, RawArtifactTransactionError, IdentityCollisionError, UnexpectedInternalError; partial artifact NOT published | ✅ Resolved |
| D7 | Marker schema v2 with status vs resolution, integrity hash, candidate_manifest_bytes_base64, ownership_token, device_id, inode, size_bytes; creation/update/validation rules | ✅ Resolved |
| D8 | verify_manifest_entry_physical (strict, no exceptions) vs verify_candidate_physical (with allowed_candidate_filename); no ambiguous optional parameters | ✅ Resolved |

**Zero open decisions.**
