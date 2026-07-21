# SENEX / SENECIO H-011 V3 — Current State

## Canonical identity

- Product: **SENEX**
- Technical system: **SENECIO H-011 V3**
- Repository: `simonkey888/SeneX-Prophet`
- Runtime purpose: defensive market discovery, immutable evidence capture, integrity evaluation, replay, and paper-only shadow execution.

## Permanent safety flags

```text
paper_only=true
orders_enabled=false
live_capital_locked=true
```

No wallet, private key, real order, real fill, realized PnL, NAV, or real capital path is authorized or implemented by Phase II-C.

## Authoritative branches and pull requests

- Product/base branch: `feat/h011-v3-discovery-refresh`
- Product/base SHA: `2f8503533543832147caf4c8e97a0cc6f5af3cbc`
- Main development branch: `feat/h011-v3-control-plane-coverage`
- PR #5 head verified before and after Phase II-C: `495265f162fc2fc44bbcfc4707b1c38ecde2fd3a`
- Phase II-C branch: `feat/h011-v3-runtime-transaction-integration`
- Draft PR: `#20`
- Phase II-C stacked base: `495265f162fc2fc44bbcfc4707b1c38ecde2fd3a`
- Validated Phase II-C head before this evidence-only documentation commit: `7424b825194490076fe5e2bc195898b7656b9c7c`

PR #5 and PR #20 remain Draft and unmerged. No merge is authorized.

## Production and infrastructure

Known public service:

- Dashboard: `https://h011-web--senecio-h011--wbjggn89fnf8.code.run/`
- Health: `/healthz`
- State: `/api/v3/state`
- Integrity: `/api/v3/integrity`
- Replay: `/api/v3/replay`

Last verified production code SHA:

```text
2f8503533543832147caf4c8e97a0cc6f5af3cbc
```

No Phase II-C code was deployed. Northflank, production, variables, secrets, domains, replicas, and volumes were not modified.

Architecture remains:

```text
GitHub -> GitHub Actions -> Python 3.11 Docker image
       -> FastAPI/Uvicorn supervised runtime -> Northflank -> code.run
```

Cloudflare is not the authoritative runtime.

## Phase II-C architecture result

Implemented and validated:

1. legacy `InvariantResult` compatibility normalization without changing UNKNOWN, severity, or the 31-invariant catalog;
2. startup recovery before scanner/publication enablement;
3. one hardened stager, publisher, recovery implementation, and authoritative raw chain;
4. transactional integration in `run_scan_v3`;
5. committed manifest-chain reader for state, integrity, and replay;
6. atomic, regenerable `latest.json` cache bound to the committed chain;
7. Python PID-1 process supervision, signals, shutdown, liveness, readiness, and operational state;
8. manual isolated filesystem capability probe;
9. Linux and Docker crash/restart validation on a shared temporary volume;
10. exact-head read-only CI with pinned actions and uploaded evidence.

## Storage contract

Authoritative transactional root:

```text
/app/polymarket/results/h011_v3/raw_chain_v1
```

Legacy paths remain non-authoritative and are never auto-migrated:

```text
/app/polymarket/results/v3/raw
/app/polymarket/results/v3/scans
/app/polymarket/results/v3/state
bundle_*.json
YYYY-MM-DD.events.jsonl.gz
v3_scan_*.jsonl
```

The last committed manifest sequence is selected by validated sequence and hash linkage, never by mtime, lexicographic artifact name, or a legacy bundle.

## Startup and fail-closed states

Runtime states include:

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

Scanner and publication remain disabled during recovery and in blocked states. There is no silent legacy-writer fallback.

## Final exact-head evidence

Authoritative Phase II-C run:

```text
run_id=29826014986
job_id=88619418979
validated_head=7424b825194490076fe5e2bc195898b7656b9c7c
conclusion=success
artifact_id=8493332225
artifact_digest=sha256:27061cd04f23cfccfe1322592dbfac0e03043bf94c3b47e846ef6f92bef119d5
```

Results:

```text
focused Phase II-C tests: 29 passed
transaction/publisher/recovery regression: 268 passed
H-011 suite: 534 passed
full global suite: 561 passed, 0 failed
compileall: PASS
host filesystem probe: PASS
Docker build: PASS
Docker module completeness: PASS
container filesystem probe: PASS
controlled runtime APIs: PASS
SIGTERM shutdown: PASS
crash/restart matrix: 7/7 PASS
unresolved marker/temp residue: 0
```

Validated crash points:

```text
PUBLISH_AFTER_STAGED_MARKER
PUBLISH_AFTER_ARTIFACT_MARKER_UPDATE
PUBLISH_AFTER_SIDECAR_MARKER_UPDATE
PUBLISH_AFTER_MANIFEST_MARKER_UPDATE
PUBLISH_AFTER_COMMITTED_MARKER
PUBLISH_AFTER_STAGING_UNLINK
PUBLISH_AFTER_MARKER_UNLINK
```

Each case used a failed container/process followed by startup recovery in a second container on the same temporary volume. Final chain verification passed with no marker or pending residue.

Runtime API evidence showed:

```text
chain_verified=true
replay_verified=true
legacy_mode=false
raw_store_available=true
snapshot_age_sec=<real numeric value>
invariants.pass=31
invariants.fail=0
invariants.unknown=0
```

## Validated file hashes

```text
h011_v3_raw_transaction.py  4d6b859c3ac5596c9d386ceb31dbfa5f53298f526dadcba9bc177a73622b3e99
h011_v3_raw_recovery.py     ed5126ef2f7993b58307d45494b212314e4a1f369b7821e87fc677739bae8eb0
h011_v3_runtime.py          a6fc46808d16c09398cc53f57f74563160a21c775425719dce175800cd867f4d
h011_v3_committed_snapshot.py 22708783d236ecf8e33ca8288c9de789c43398c08c5fe2584a533adb207d2da9
h011_v3_pipeline.py         f7d7d5799aa13bbc6e503d1180d16a6b6efd63b71573ca4f194e3d7f8cffb2f6
dashboard_v3.py             ab5ac5edad2f55259ac31bf5f4e1b8c955a1634c53e7d82f0740ddafb6e079f1
Dockerfile.h011-v3          ff126c299d67b1ef73ba40b869f8a462be8c89554e3c5db2063f3b67891de571
```

## Historical baseline

Pre-integration exact-head run `29821019238`:

```text
H-011: 515 passed
global: 542 passed
Docker build/start: PASS
safety flags: PASS
artifact: 8491371840
digest: sha256:594ecaa1651be29340d7a74a5955c7b01a6ee6bfef01ba99028689a0f88dd875
```

The inherited compatibility failure was eliminated and test counts increased without changing the transaction or recovery contracts.

## Current milestone

```text
PHASE_IIC_BRANCH_CREATED=YES
PR20_DRAFT=YES
PR20_MERGED=NO
INVARIANT_COMPATIBILITY_FIX=PASS
STARTUP_RECOVERY=PASS
TRANSACTIONAL_PUBLISHER_RUNTIME=PASS
COMMITTED_SNAPSHOT_READER=PASS
DOCKER_RUNTIME_INTEGRATION=PASS
CRASH_MATRIX=PASS
RESTART_MATRIX=PASS
GLOBAL_TESTS_ZERO_FAILED=YES
TEMPORARY_MATERIALIZER_FILES=REMOVED
PRODUCTION_CHANGED=NO
NORTHFLANK_CHANGED=NO
PR5_CHANGED=NO
DEPLOY_EXECUTED=NO
```

## Open blocker

The only remaining pre-deploy blocker is direct verification of the actual Northflank production volume and filesystem capabilities, mount path, persistence, and restart behavior. The probe exists but must not be run against production without explicit deployment/infrastructure authorization.

## Next exact step

Keep PR #20 Draft. Perform final independent source/diff audit and, only after separate explicit authorization, merge the stacked PR into `feat/h011-v3-control-plane-coverage` without deploying.
