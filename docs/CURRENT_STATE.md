# SENEX / SENECIO H-011 V3 — Current State

## Canonical identity

- Product: **SENEX**
- Technical system: **SENECIO H-011 V3**
- Repository: `simonkey888/SeneX-Prophet`
- Purpose: defensive discovery, immutable evidence capture, integrity validation, replay, observability, and paper-only shadow execution for BTC Up/Down five-minute markets.

## Permanent safety flags

```text
paper_only=true
orders_enabled=false
live_capital_locked=true
```

No wallet, private key, real order, real fill, realized PnL, NAV, or real-capital path is authorized or enabled.

## Authoritative branches and pull requests

```text
product/base branch: feat/h011-v3-discovery-refresh
product/base SHA: 2f8503533543832147caf4c8e97a0cc6f5af3cbc
main development branch: feat/h011-v3-control-plane-coverage
PR #5: OPEN / DRAFT / UNMERGED
PR #5 old head before Phase II-C merge: 495265f162fc2fc44bbcfc4707b1c38ecde2fd3a
Phase II-C source branch: feat/h011-v3-runtime-transaction-integration
PR #20 source head: 3ffeddf29ea02ed691dc12f3f979d1be58a486d3
PR #20 merge commit: 4c2a00db86d1740f0a53b6f62a523dabedfae21d
PR #20: CLOSED / MERGED
validated PR #5 head before this continuity-only commit: 17d86f66f22675a7d16bf1e66070a22b909e78d1
```

PR #20 was merged into `feat/h011-v3-control-plane-coverage` using a merge commit. PR #5 remains Draft and was not merged into `feat/h011-v3-discovery-refresh`.

## Production and infrastructure

Known public service:

- Dashboard: `https://h011-web--senecio-h011--wbjggn89fnf8.code.run/`
- Health: `/healthz`
- State: `/api/v3/state`
- Integrity: `/api/v3/integrity`
- Replay: `/api/v3/replay`

Last known production code SHA:

```text
2f8503533543832147caf4c8e97a0cc6f5af3cbc
```

Phase II-C has not been deployed. Northflank services, deployments, variables, secrets, domains, replicas, and volumes were not accessed or modified.

Authoritative delivery architecture remains:

```text
GitHub -> GitHub Actions -> Python 3.11 Docker image
       -> FastAPI/Uvicorn supervised runtime -> Northflank -> code.run
```

Cloudflare is not the authoritative runtime.

## Integrated Phase II-C architecture

The PR #5 branch contains:

1. compatibility normalization for legacy `InvariantResult` values without changing UNKNOWN semantics, severity, or the 31-invariant catalog;
2. startup recovery before scanner and publication enablement;
3. explicit fail-closed runtime states;
4. one hardened stager, publisher, recovery implementation, and authoritative raw chain;
5. transactional publication integrated into `run_scan_v3`;
6. committed manifest-chain reader for state, integrity, and replay;
7. `latest.json` as a regenerable cache bound to the latest committed manifest, never as authority;
8. Python PID-1 supervision with signal forwarding, graceful shutdown, liveness, readiness, and scanner status;
9. manual isolated filesystem capability probe;
10. Linux and Docker same-volume crash/restart validation;
11. exact-head, read-only Phase II-C evidence workflow with pinned action SHAs.

## Storage contract

Authoritative transactional root:

```text
/app/polymarket/results/h011_v3/raw_chain_v1
```

Legacy paths remain non-authoritative and are never automatically migrated or mixed into the committed chain:

```text
/app/polymarket/results/v3/raw
/app/polymarket/results/v3/scans
/app/polymarket/results/v3/state
bundle_*.json
YYYY-MM-DD.events.jsonl.gz
v3_scan_*.jsonl
```

The latest committed scan is selected by contiguous sequence, previous-manifest linkage, canonical manifest hash, artifact SHA-256, sidecar validation, permissions, and residue checks. It is never selected by mtime, filename ordering, or a legacy bundle.

## Runtime states

```text
STARTING
RECOVERING
RUNNING
DEGRADED
BLOCKED_RAW_INTEGRITY
BLOCKED_STORAGE_UNVERIFIED
SCANNER_FAILED
STOPPING
```

Scanner and publication remain disabled during recovery and in blocked states. No silent legacy-writer fallback exists.

## Pre-merge Phase II-C evidence

```text
run_id=29826214658
job_id=88620050451
validated_head=3ffeddf29ea02ed691dc12f3f979d1be58a486d3
conclusion=success
artifact_id=8493410423
artifact_digest=sha256:c01046dd1f81eddbb2315d77afd289722a85b223936c884dc487ed8228bab707
```

## Post-merge exact-head evidence

The integrated PR #5 branch was validated directly at its exact branch head, not at a synthetic merge ref:

```text
run_id=29830860459
job_id=88635003168
validated_head=17d86f66f22675a7d16bf1e66070a22b909e78d1
conclusion=success
artifact_id=8495223681
artifact_digest=sha256:b6fb5198afe35d60f682fc8476577ee407ba5f93b36a2221c95c6687f7300f19
```

Results:

```text
Phase II-C focused suite: 29 passed
transaction/publisher/recovery regression: 268 passed
H-011 complete suite: 534 passed
full global suite: 561 passed, 0 failed
compileall: PASS
host filesystem probe: PASS
Docker build: PASS
Docker module completeness: PASS
container filesystem probe: PASS
controlled container startup: PASS
liveness: PASS
readiness: PASS
/api/v3/state: PASS
/api/v3/integrity: PASS
/api/v3/replay: PASS
SIGTERM graceful shutdown: PASS
crash matrix: 7/7 PASS
restart matrix: 7/7 PASS
unresolved marker/temp residue: 0
```

Runtime evidence:

```text
invariants.total=31
invariants.pass=31
invariants.fail=0
invariants.unknown=0
chain_verified=true
replay_verified=true
legacy_mode=false
raw_store_available=true
paper_only=true
orders_enabled=false
live_capital_locked=true
```

Validated crash/restart points:

```text
PUBLISH_AFTER_STAGED_MARKER
PUBLISH_AFTER_ARTIFACT_MARKER_UPDATE
PUBLISH_AFTER_SIDECAR_MARKER_UPDATE
PUBLISH_AFTER_MANIFEST_MARKER_UPDATE
PUBLISH_AFTER_COMMITTED_MARKER
PUBLISH_AFTER_STAGING_UNLINK
PUBLISH_AFTER_MARKER_UNLINK
```

Each case used an interrupted process/container followed by startup recovery in a second container over the same isolated temporary volume. Final chain verification passed without marker, marker-temp, pending, or unowned transaction residue.

## CI compatibility repair after integration

The inherited PR3 and PR5 smoke workflows assumed a legacy discovery artifact. Phase II-C intentionally removed that path as an authoritative output. The workflows were updated to validate the committed raw chain, exact-head checkout, controlled runtime APIs, pinned actions, security flags, sidecar checksum, and zero marker residue.

Validated workflow-repair head:

```text
head=17d86f66f22675a7d16bf1e66070a22b909e78d1
H011_PR3_DOCKER_SMOKE=PASS
H011_PR5_CONTROL_PLANE_SMOKE=PASS
H011_PR5_PHASE_IIC_EXACT_HEAD=PASS
```

No product transaction-core or recovery contract change was required.

## Historical baseline

```text
run_id=29821019238
H-011=515 passed
global=542 passed, 0 failed
Docker=PASS
safety_flags=PASS
artifact_id=8491371840
artifact_digest=sha256:594ecaa1651be29340d7a74a5955c7b01a6ee6bfef01ba99028689a0f88dd875
```

Phase II-C increased coverage while preserving the hardened transaction and recovery contracts.

## Current milestone

```text
PR20_STATE=CLOSED
PR20_MERGED=YES
PR20_MERGE_COMMIT=4c2a00db86d1740f0a53b6f62a523dabedfae21d
PR5_STATE=OPEN
PR5_DRAFT=YES
PR5_MERGED=NO
INVARIANT_COMPATIBILITY_FIX=PASS
STARTUP_RECOVERY=PASS
TRANSACTIONAL_PUBLISHER_RUNTIME=PASS
COMMITTED_SNAPSHOT_READER=PASS
PYTHON_PID1_RUNTIME=PASS
DOCKER_RUNTIME_INTEGRATION=PASS
CRASH_MATRIX=7/7_PASS
RESTART_MATRIX=7/7_PASS
GLOBAL_TESTS_ZERO_FAILED=YES
LEGACY_AUTHORITATIVE_WRITER=ABSENT
SILENT_LEGACY_FALLBACK=ABSENT
TEMPORARY_MATERIALIZER_FILES=REMOVED
PRODUCTION_CHANGED=NO
NORTHFLANK_CHANGED=NO
DEPLOY_EXECUTED=NO
```

## Open blocker

The sole pre-deploy blocker is direct verification of the real Northflank volume and filesystem:

- exact mount path;
- persistence across restart and deployment;
- `flock`;
- hardlinks;
- `renameat2(RENAME_EXCHANGE)`;
- file and directory `fsync`;
- `O_NOFOLLOW`;
- final `0444` permissions and inode stability;
- ownership and capacity;
- backup and rollback behavior.

The probe exists but must not be run against production without explicit infrastructure authorization.

## Next exact step

Revalidate the branch head containing this canonical continuity commit with all exact-head and smoke gates. Keep PR #5 Draft. The next authorized technical action after that is an isolated Northflank volume/filesystem probe; no deploy decision is valid before that evidence exists.
