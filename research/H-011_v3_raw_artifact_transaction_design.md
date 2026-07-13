# H-011 V3 — Raw Artifact Transaction Design

## Status: DESIGN DOCUMENT — Not Implemented

**Date:** 2026-07-13
**Branch:** `feat/h011-v3-control-plane-coverage`
**Head:** `18f8e6de`
**Production:** `2f850353` (untouched)

---

## 1. Problem Statement

The current raw event store uses a mutable daily-append model
(`YYYY-MM-DD.events.jsonl.gz`). This is incompatible with immutable
manifest chains because:

1. Each append modifies the artifact, breaking any previously computed
   SHA-256 stored in a manifest.
2. Multiple scans share the same daily file, making per-scan identity
   (run_id, scan_id) impossible to enforce.
3. The file cannot be sealed or verified as a complete unit.

The manifest writer (`publish_staged_artifact_with_manifest_v2`) exists
but has structural issues:
- Multiple publishers coexist (U1).
- Recovery reconstructs manifests with new timestamps (U2).
- Validation is not repeated under lock (U3).
- Markers lack transaction UUIDs (U4).
- All errors become QUARANTINED (U5).
- Recovery is not path-safe (U6).
- Recovery matrix is incomplete (U7).
- No virtual chain verification before manifest (U8).
- Chain verification doesn't check sidecar or raw content (U9).
- Staging lifecycle is implicit (U10).

This document specifies the complete design to resolve U1-U12.

---

## 2. Architecture Overview

### 2.1 Module Structure

```
control_plane/
  artifact_manifest.py       — Generic types + primitives (ManifestPolicy, hash helpers)
  raw_artifact_transaction.py — Raw-specific transaction, verifier, recovery
  coverage.py                — INV-005/006 evaluators (import from raw_artifact_transaction)

raw_event_store.py           — RawScanStager + SealedRawArtifact + load_raw_events_strict
```

### 2.2 Single Publisher API

**Deprecated (removed from raw flow):**
- `write_manifest_atomic()` — generic, no staging, no transaction
- `publish_artifact_with_manifest()` — generic, no staging
- `publish_staged_artifact_with_manifest()` (v1) — no candidate bytes, no UUID

**Canonical (only API for raw artifacts):**
```python
publish_raw_scan(
    directory: Path,
    sealed: SealedRawArtifact,
    policy: ManifestPolicy,
    identity_fields: dict[str, str],
    extra_manifest_fields: dict[str, Any] | None = None,
) -> dict[str, Any]
```

This is the ONLY function that publishes raw artifacts. It:
1. Validates fields (T2)
2. Acquires lock
3. Recovers incomplete transactions (T5)
4. Validates sealed artifact under lock (T1/U3)
5. Verifies virtual chain (U8)
6. Creates marker with UUID (U4)
7. Publishes artifact via hardlink (no-overwrite)
8. Publishes sidecar via hardlink (durable)
9. Publishes manifest from exact candidate bytes (U2)
10. Strict reverification (U9)
11. Marks COMMITTED, cleans up
12. Releases lock

---

## 3. Data Structures

### 3.1 SealedRawArtifact (frozen dataclass)

```python
@dataclass(frozen=True)
class SealedRawArtifact:
    staging_path: Path          # .pending/raw_scan_<safe_id>_<uuid12>.jsonl.gz.tmp
    final_name: str             # raw_scan_<safe_id>_<scan_id_hash12>.events.jsonl.gz
    run_id: str
    scan_id: str
    event_count: int
    condition_ids: tuple[str, ...]
    file_sha256: str            # SHA-256 of staging file bytes
    canonical_events_sha256: str # SHA-256 of canonical JSON of events
    # Sealed at seal() time; never modified after
```

### 3.2 Transaction Marker

```json
{
  "transaction_version": "h011-artifact-txn-v2",
  "transaction_id": "txn_<sequence:06d>_<uuid>",
  "transaction_uuid": "<uuid>",
  "policy": "raw",
  "status": "STAGED",
  "sequence": 0,
  "run_id": "...",
  "scan_id": "...",
  "staging_path": ".../pending/raw_scan_..._....jsonl.gz.tmp",
  "final_name": "raw_scan_..._....events.jsonl.gz",
  "sidecar_name": "raw_scan_..._....events.jsonl.gz.sha256",
  "manifest_name": "manifest_000000.json",
  "file_sha256": "...",
  "canonical_events_sha256": "...",
  "event_count": 3,
  "condition_ids": ["0xabc", "0xdef"],
  "previous_manifest_hash": null,
  "candidate_manifest": { ... },
  "candidate_manifest_bytes": "...",
  "candidate_manifest_bytes_sha256": "...",
  "manifest_created_at": "2026-07-13T...",
  "failure_stage": null,
  "failure_type": null,
  "failure_message": null,
  "recoverable": true
}
```

Key decisions:
- **candidate_manifest**: Full manifest entry dict, stored in marker.
- **candidate_manifest_bytes**: Base64-encoded canonical JSON bytes.
- **manifest_created_at**: Frozen at creation time. Recovery uses this
  exact value. No `datetime.now()` during recovery.
- **transaction_uuid**: UUID4, included in marker filename:
  `manifest_txn_<sequence:06d>_<uuid>.marker`

### 3.3 Manifest Entry (raw-specific)

```json
{
  "sequence": 0,
  "filename": "raw_scan_..._....events.jsonl.gz",
  "file_sha256": "...",
  "previous_manifest_hash": null,
  "created_at": "2026-07-13T10:00:00Z",
  "run_id": "...",
  "scan_id": "...",
  "event_count": 3,
  "condition_ids": ["0xabc", "0xdef"],
  "canonical_events_sha256": "...",
  "manifest_hash": "..."
}
```

### 3.4 ManifestPolicy (unchanged)

```python
RAW_MANIFEST_POLICY = ManifestPolicy(
    manifest_prefix="manifest",
    artifact_glob="*.events.jsonl.gz",
    exclude_names=frozenset(),
    identity_fields=("run_id", "scan_id"),
)
```

---

## 4. State Machine

### 4.1 Transaction States

```
STAGED
  ↓ (artifact hardlinked)
ARTIFACT_PUBLISHED
  ↓ (sidecar hardlinked)
SIDECAR_PUBLISHED
  ↓ (manifest published from exact candidate bytes)
MANIFEST_PUBLISHED
  ↓ (strict reverify passed)
COMMITTED
  ↓ (marker + staging removed)
[terminal — no marker exists]

Any state → FAILURE:
  marker.status stays at last successful state
  marker.failure_stage = current stage
  marker.failure_type = error type
  marker.failure_message = error message
  marker.recoverable = true/false
```

### 4.2 Staging Lifecycle

```
OPEN      — stager created, staging file open for append
  ↓ seal()
SEALED    — staging file closed, SealedRawArtifact returned
  ↓ publish_raw_scan() called
TRANSFERRED — ownership transferred to publisher
  ↓ publish success
PUBLISHED — staging file removed, marker COMMITTED
  ↓ publish failure
ABORTED   — staging file preserved for recovery; marker tracks state
```

Context manager behavior:
- `OPEN` + exception → delete staging
- `SEALED` + not transferred → delete staging (orphan cleanup)
- `TRANSFERRED` → publisher owns lifecycle via marker
- `PUBLISHED` → staging already deleted by publisher
- `ABORTED` → staging preserved for recovery

### 4.3 Recovery Decision Matrix

| Marker Status | Artifact | Sidecar | Manifest | Chain Valid | Action |
|---|---|---|---|---|---|
| STAGED | no | no | no | n/a | Continue publication from STAGED |
| STAGED | no | no | no | n/a | If staging valid → continue; else BLOCKED |
| STAGED | yes* | no | no | n/a | Unexpected → BLOCKED (preserve evidence) |
| ARTIFACT_PUBLISHED | yes | no | no | n/a | Validate artifact → publish sidecar → continue |
| ARTIFACT_PUBLISHED | yes | yes* | no | n/a | Unexpected sidecar → BLOCKED |
| ARTIFACT_PUBLISHED | no | no | no | n/a | Missing artifact → BLOCKED |
| SIDECAR_PUBLISHED | yes | yes | no | n/a | Validate both → publish exact candidate manifest → continue |
| SIDECAR_PUBLISHED | yes | yes | yes* | n/a | Unexpected manifest → BLOCKED |
| SIDECAR_PUBLISHED | no | * | no | n/a | Missing artifact → BLOCKED |
| MANIFEST_PUBLISHED | yes | yes | yes | yes | → COMMITTED (clean up) |
| MANIFEST_PUBLISHED | yes | yes | yes | no | → BLOCKED (preserve all evidence) |
| MANIFEST_PUBLISHED | no | * | * | no | → BLOCKED |
| COMMITTED | * | * | * | * | Clean up residual marker/staging |
| QUARANTINED | * | * | * | * | Skip; report as unresolved |
| (corrupt marker) | * | * | * | * | → QUARANTINED |

* = unexpected presence

Key rules:
- `BLOCKED` = preserve all evidence, don't move files, don't delete
- `QUARANTINED` = only for corrupt/ambiguous markers
- Recovery never uses `datetime.now()` — uses `marker.manifest_created_at`
- Recovery publishes exact `candidate_manifest_bytes`

### 4.4 Blocking Semantics

When recovery finds unresolved transactions (BLOCKED or QUARANTINED):
- `recover_incomplete_transactions()` returns `{"blocking": true, "unresolved": [...]}`
- `publish_raw_scan()` refuses to start a new publication
- INV-005 cannot be PASS
- `COMPLETE_VALIDATED` is impossible
- Runtime must report the block and halt

---

## 5. Validation

### 5.1 Pre-lock Validation (fail-fast)

Before acquiring lock:
1. `validate_identity_and_extra_fields()` — reserved fields, exact keys
2. Check `final_path` doesn't exist
3. Check `sidecar_path` doesn't exist

### 5.2 Under-lock Validation (U3)

After acquiring lock, before any publication:
1. Re-check `final_path` and `sidecar_path` don't exist (race condition)
2. Recover incomplete transactions
3. Verify existing chain (must be EMPTY or VALID)
4. Validate sealed artifact:
   a. `staging_path` exists, is regular file, not symlink
   b. `staging_path` is inside `directory/.pending/`
   c. `staging_path` name ends with `.tmp`
   d. `final_name` has no `/`, `\`, `..`
   e. `final_name` matches `policy.artifact_glob`
   f. Re-read staging with `load_raw_events_strict()`
   g. Recalculate `file_sha256` from disk
   h. Recalculate `event_count` from disk
   i. Recalculate `condition_ids` from disk
   j. Recalculate `canonical_events_sha256` from disk
   k. Compare all with `SealedRawArtifact` fields
   l. Verify `sealed.run_id == identity_fields["run_id"]`
   m. Verify `sealed.scan_id == identity_fields["scan_id"]`
5. Validate candidate against existing entries (duplicates)

### 5.3 Virtual Chain Verification (U8)

Before publishing manifest:
```python
def verify_candidate_against_chain(
    existing_entries: list[dict],
    candidate_entry: dict,
    directory: Path,
    policy: ManifestPolicy,
) -> tuple[bool, list[str]]:
```

Checks:
- `sequence == len(existing_entries)`
- `previous_manifest_hash == existing_entries[-1].manifest_hash` (or None if empty)
- `manifest_hash` recalculated correctly
- `filename` unique across entries
- `run_id` unique across entries
- `scan_id` unique across entries
- `file_sha256` matches actual artifact on disk
- Sidecar exists and matches
- `event_count` matches actual content
- `condition_ids` match actual content
- `canonical_events_sha256` matches actual content

Returns `(True, [])` if valid, `(False, [errors])` if not.

---

## 6. Publication Protocol

### 6.1 Step-by-step (under lock)

```
1. acquire lock (fcntl.flock)
2. recover_incomplete_transactions_locked()
   → if blocking: release lock, raise RuntimeError
3. verify_manifest_chain() → must be EMPTY or VALID
4. validate sealed artifact under lock (section 5.2)
5. validate candidate against existing entries
6. build candidate_entry (with frozen created_at)
7. verify_candidate_against_chain() (section 5.3)
8. compute candidate_manifest_bytes (canonical JSON)
9. create marker (STAGED) with:
   - transaction_uuid
   - candidate_manifest (full dict)
   - candidate_manifest_bytes (base64)
   - manifest_created_at (frozen)
10. persist marker (atomic temp + rename + fsync)
11. hardlink staging → final artifact
    → check same inode after link
12. _dir_fsync(directory)
13. update marker → ARTIFACT_PUBLISHED
14. create sidecar in .pending (O_CREAT|O_EXCL)
15. hardlink sidecar → final sidecar
16. _dir_fsync(directory)
17. re-read sidecar, validate 64-char hex, compare with file_sha256
18. update marker → SIDECAR_PUBLISHED
19. write manifest from candidate_manifest_bytes (O_CREAT|O_EXCL)
20. _dir_fsync(directory)
21. update marker → MANIFEST_PUBLISHED
22. verify_manifest_chain_strict() (U9 — includes sidecar + raw content)
23. if valid:
      update marker → COMMITTED
      delete staging
      delete marker
24. if invalid:
      update marker → failure_stage=REVERIFY, recoverable=false
      DO NOT move files (preserve evidence)
      raise RuntimeError
25. release lock
```

### 6.2 Failure Handling (U5)

On failure at any step:
- Marker status stays at last successful state
- `failure_stage`, `failure_type`, `failure_message` set
- `recoverable` = true if recovery can complete from this state
- DO NOT automatically QUARANTINE
- DO NOT move files
- Raise RuntimeError with marker path

Only QUARANTINED when:
- Marker itself is corrupt
- Files exist in contradictory state (e.g., artifact without marker)
- Staging file is corrupt/unreadable

### 6.3 Path Safety (U6)

Marker validation before any file operation:
- `transaction_version` == "h011-artifact-txn-v2"
- All required fields present
- `staging_path` resolves inside `directory/.pending/`
- `final_name` == `Path(final_name).name` (no path components)
- `sidecar_name` == `Path(sidecar_name).name`
- `manifest_name` == `Path(manifest_name).name`
- No `..` in any name
- No absolute paths
- No symlinks in resolved paths
- `sequence` is non-negative int
- `file_sha256` is 64-char hex
- `candidate_manifest_bytes_sha256` matches `candidate_manifest_bytes`

---

## 7. Chain Verification (U9/T7)

### 7.1 Raw-Specific Verifier

```python
def verify_raw_chain(
    directory: Path,
    policy: ManifestPolicy,
) -> dict[str, Any]:
```

For each manifest entry:
1. Artifact file exists
2. Sidecar file exists
3. Sidecar content is 64-char hex
4. Sidecar == manifest `file_sha256`
5. Recalculated file SHA == sidecar
6. Gzip valid (open + read)
7. JSONL valid (strict load)
8. Each payload is dict
9. Required schema fields present
10. `payload_sha256` matches actual payload
11. `event_count` matches actual content
12. `condition_ids` match actual content
13. `canonical_events_sha256` matches actual content
14. `run_id` present and unique
15. `scan_id` present and unique
16. `filename` matches `policy.artifact_glob`
17. `manifest_hash` recalculated correctly
18. `previous_manifest_hash` links correct
19. `sequence` continuous (0, 1, 2, ...)

Additional:
- No unregistered artifacts
- No orphan sidecars
- No unresolved markers

Sidecar absent → `CHAIN_INVALID` (not UNKNOWN)
Sidecar altered → `CHAIN_INVALID`
Event count altered → `CHAIN_INVALID`
Canonical hash altered → `CHAIN_INVALID`

### 7.2 INV-005 Integration

```python
def _eval_raw_events_append_only(ctx):
    result = verify_raw_chain(Path(ctx.raw_dir), RAW_MANIFEST_POLICY)
    if result["chain_status"] == "VALID_CHAIN":
        return PASS
    elif result["chain_status"] in ("EMPTY_CHAIN", "BOOTSTRAP_REQUIRED"):
        return UNKNOWN
    else:  # INVALID_CHAIN
        return FAIL
```

---

## 8. Canonicalization

### 8.1 Events Canonical Form

```python
canonical = json.dumps(
    disk_events,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8")
canonical_events_sha256 = hashlib.sha256(canonical).hexdigest()
```

### 8.2 Manifest Canonical Form

```python
# Exclude manifest_hash from canonical form
manifest_for_hash = {k: v for k, v in entry.items() if k != "manifest_hash"}
manifest_bytes = json.dumps(
    manifest_for_hash,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
entry["manifest_hash"] = hashlib.sha256(manifest_bytes).hexdigest()
```

### 8.3 Fields Excluded from Snapshot Hash

When implementing snapshot two-phase (future FASE D):
- `snapshot_hash` itself
- Any field derived exclusively from verifying the hash
- Timestamps generated after canonical content is frozen

---

## 9. Concurrency

### 9.1 Lock

```python
lock_path = directory / f"{policy.manifest_prefix}.lock"
lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
```

### 9.2 Concurrent Publishers

Two threads, each with their own sealed staging:
1. Both call `publish_raw_scan()` simultaneously
2. Lock serializes them
3. First thread acquires lock, publishes sequence 0, releases lock
4. Second thread acquires lock, recovers (nothing to recover), publishes sequence 1
5. Both succeed
6. No `time.sleep` needed
7. Final chain: VALID, 2 entries, 0 errors, 0 unregistered

### 9.3 Staging Exclusivity

Each stager creates a unique staging file:
```
.pending/raw_scan_<safe_scan_id>_<uuid12>.jsonl.gz.tmp
```
Created with `O_CREAT | O_EXCL`. No collision possible.

---

## 10. Test Plan

### 10.1 Fault Injection Framework

```python
FAULT_HOOKS = {
    "STAGED",               # After marker STAGED, before artifact
    "ARTIFACT_PUBLISHED",   # After artifact, before sidecar
    "SIDECAR_PUBLISHED",    # After sidecar, before manifest
    "MANIFEST_PUBLISHED",   # After manifest, before reverify
}
```

Each hook simulates crash by raising `SystemExit` without executing
the `except` block. The test then:
1. Creates a new publisher instance
2. Calls `recover_incomplete_transactions()`
3. Verifies final state

### 10.2 Required Tests (30+)

**Basic:**
1. seal does not publish
2. UUID staging exclusive
3. staging hash altered after seal → validation fails
4. staging JSON altered (same line count) → validation fails
5. gzip truncated → strict load fails
6. final_name traversal → rejected
7. final_name outside glob → rejected
8. sealed run_id != identity run_id → rejected
9. sealed scan_id != identity scan_id → rejected
10. reserved key in identity_fields → rejected
11. sidecar publication no-overwrite
12. sidecar fsync + relectura validates
13. marker STAGED persisted
14. marker ARTIFACT_PUBLISHED persisted
15. marker SIDECAR_PUBLISHED persisted
16. marker MANIFEST_PUBLISHED persisted

**Recovery:**
17. recovery from ARTIFACT_PUBLISHED → publishes sidecar + manifest
18. recovery from SIDECAR_PUBLISHED → publishes exact candidate manifest
19. recovery from MANIFEST_PUBLISHED + valid chain → COMMITTED
20. recovery from MANIFEST_PUBLISHED + invalid chain → BLOCKED
21. ambiguous state → QUARANTINED
22. candidate created_at exact (recovery uses marker timestamp, not now())
23. stale marker temp → cleaned up
24. marker path traversal → rejected
25. marker staging path external → rejected
26. marker version invalid → QUARANTINED
27. marker hash altered → QUARANTINED

**Chain verification:**
28. sidecar absent → CHAIN_INVALID
29. sidecar altered → CHAIN_INVALID
30. event_count altered → CHAIN_INVALID
31. canonical hash altered → CHAIN_INVALID
32. condition_ids altered → CHAIN_INVALID
33. payload_sha256 altered → CHAIN_INVALID

**Lifecycle:**
34. sealed orphan cleaned up
35. unresolved transaction blocks new publication

**Concurrency:**
36. two publishers concurrent (no sleep) → VALID_CHAIN, 2 entries

**Post-commit:**
37. no markers after commit
38. no staging after commit
39. no quarantine after successful commit

**Fault injection:**
40. crash at STAGED → recovery continues
41. crash at ARTIFACT_PUBLISHED → recovery publishes sidecar + manifest
42. crash at SIDECAR_PUBLISHED → recovery publishes exact manifest
43. crash at MANIFEST_PUBLISHED → recovery commits or blocks

### 10.3 End-to-End Gate

On a clean temporary directory:
1. Run two scans (mock, not full runtime)
2. After first: raw artifacts=1, manifests=1, sidecars=1, chain=VALID, INV-005=PASS
3. After second: raw artifacts=2, manifests=2, sidecars=2, chain=VALID, sequences=[0,1]
4. Tamper first artifact: chain=INVALID, INV-005=FAIL, scan_status=BLOCKED

---

## 11. Runtime Integration Plan (T10 — Future)

### 11.1 Changes to `run_scan_v3`

```python
# BEFORE (deprecated):
date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
raw_path = V3_RAW_DIR / f"{date_str}.events.jsonl.gz"
append_raw_event(raw_path, raw_event)

# AFTER:
with RawScanStager(run_id=run_id, scan_id=scan_id, raw_dir=V3_RAW_DIR) as stager:
    for market in markets:
        record = process_market_v3(
            ...,
            raw_event_sink=stager,  # new parameter
        )
    sealed = stager.seal()
    publish_raw_scan(
        V3_RAW_DIR, sealed, RAW_MANIFEST_POLICY,
        identity_fields={"run_id": run_id, "scan_id": scan_id},
        extra_manifest_fields=sealed.to_manifest_fields(),
    )
```

### 11.2 Changes to `process_market_v3`

```python
# New parameter: raw_event_sink: RawScanStager | None = None

# After Data API response, before transform:
if raw_event_sink is not None:
    raw_event = create_raw_event(...)
    raw_event_sink.append_event(raw_event)
    # flush + fsync already happens inside append_event

# Then proceed with trade_binding, VWAP, etc.
```

### 11.3 INV-025 Verification

Raw event is persisted (flush + fsync) inside `append_event()` before
any transform runs. This preserves INV-025.

### 11.4 Migration

**Do NOT migrate existing daily files automatically.**

Legacy daily files (`YYYY-MM-DD.events.jsonl.gz`) will appear as
unregistered artifacts → `BOOTSTRAP_REQUIRED`.

Options for migration (future, authorized window):
1. Move legacy files to a separate `legacy/` directory
2. Create bootstrap manifests for legacy files
3. Start fresh in a new `raw/` directory

**Recommendation:** Option 3 (fresh start). Legacy files remain in
production for audit but are not part of the manifest chain. The new
chain starts empty.

---

## 12. Snapshot Manifests (Future — FASE D)

Same transaction protocol but with:
- `SNAPSHOT_MANIFEST_POLICY`
- `artifact_glob="snapshot_*.json"`
- `exclude_names={"latest.json", "latest.json.sha256"}`
- Two-phase snapshot: provisional → canonical → hash → publish → reverify

Not implemented in this design doc. Will be specified separately after
raw artifacts are working end-to-end.

---

## 13. Open Decisions

### 13.1 Should `payload_sha256` be verified in chain verification?

**Decision:** Yes. Each raw event has a `payload_sha256` field. The
verifier recalculates it from the stored payload and compares. If they
don't match, the event was tampered with after creation.

### 13.2 Should recovery run automatically on every `publish_raw_scan`?

**Decision:** Yes. Recovery runs under the lock at the start of every
publish. This ensures:
- Previous crashes are resolved before new work
- The chain is in a known state
- No orphan artifacts accumulate

If recovery finds blocking transactions, publish refuses to start.

### 13.3 Should the staging file be opened read-only after seal?

**Decision:** Yes. `seal()` closes the gzip handle and the file is
never reopened for write. The publisher opens it read-only for
hardlink. This is enforced by the staging file extension (`.tmp`)
not matching the artifact glob, so even if someone tries to append,
it won't be confused with a final artifact.

### 13.4 Should marker files be in `.pending/` or in the main directory?

**Decision:** Markers go in the main directory (alongside manifests)
because:
- They need to be visible for recovery
- They don't match the artifact glob
- They have a distinct prefix (`manifest_txn_*`)
- `.pending/` is for staging files only

### 13.5 What happens if the lock file itself is corrupt?

**Decision:** The lock file is created with `O_CREAT | O_RDWR` and
`fcntl.flock` is used. If the lock file is corrupt (unlikely), `flock`
still works because it uses inode-level locking, not file content.
The lock file is never read for content.

---

## 14. Summary

| Component | Status |
|---|---|
| SealedRawArtifact | Implemented (B2) |
| RawScanStager | Implemented (B2, B3) |
| load_raw_events_strict | Implemented (T1) |
| validate_sealed_artifact | Implemented (T1) — needs under-lock repeat (U3) |
| validate_identity_and_extra_fields | Implemented (T2) |
| publish_sidecar_durable | Implemented (T3) |
| Transaction marker | Implemented (T4) — needs UUID (U4) + candidate bytes (U2) |
| Recovery | Partially implemented (T5) — needs exact candidate (U2), matrix (U7), path safety (U6) |
| Virtual chain verification | Not implemented (U8) |
| Raw chain verifier | Not implemented (U9/T7) |
| Staging lifecycle | Partially implemented (T8) — needs explicit states (U10) |
| Fault injection tests | Not implemented (U11) |
| Runtime integration | Not implemented (T10) |

**Next step:** Implement U1-U12 in code, then T10 runtime integration,
then FASES B-F.

---

## 15. PR Body Template

```text
Current head: <SHA>
Tests: <N>/<N>
Transaction system: design doc complete, implementation in progress
PASS 22
FAIL 0
UNKNOWN 4
NOT_APPLICABLE 5
scan_status: COMPLETE_WITH_UNKNOWN_VALIDATION
Production: 2f850353 (untouched)
```
