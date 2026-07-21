# SENEX / SENECIO H-011 V3 — Current State

## Canonical identity

- Product: **SENEX**
- Technical system: **SENECIO H-011 V3**
- Repository: `simonkey888/SeneX-Prophet`
- Runtime purpose: defensive, read-only market discovery, evidence capture, integrity evaluation, replay, and paper-only shadow execution.

## Permanent safety flags

```text
paper_only=true
orders_enabled=false
live_capital_locked=true
```

No wallets, private keys, real orders, real fills, realized PnL, NAV, or real capital are authorized.

## Authoritative branches and PRs

- Product/base branch: `feat/h011-v3-discovery-refresh`
- Product/base SHA: `2f8503533543832147caf4c8e97a0cc6f5af3cbc`
- Main development branch: `feat/h011-v3-control-plane-coverage`
- PR #5 head at Phase II-C start: `495265f162fc2fc44bbcfc4707b1c38ecde2fd3a`
- Phase II-C branch: `feat/h011-v3-runtime-transaction-integration`
- Phase II-C base: `495265f162fc2fc44bbcfc4707b1c38ecde2fd3a`
- PR #5 remains Draft and must not be merged without explicit authorization.

## Production

Known public service:

- Dashboard: `https://h011-web--senecio-h011--wbjggn89fnf8.code.run/`
- Health: `/healthz`
- State: `/api/v3/state`
- Integrity: `/api/v3/integrity`
- Replay: `/api/v3/replay`

Production was last verified declaring code SHA:

```text
2f8503533543832147caf4c8e97a0cc6f5af3cbc
```

No Phase II-C code has been deployed. Northflank and production are out of scope for mutation.

## Architecture

```text
GitHub
  -> GitHub Actions
  -> Python 3.11 Docker image
  -> FastAPI/Uvicorn runtime
  -> Northflank
  -> code.run public domain
```

Cloudflare is not the authoritative runtime.

## Existing completed work

- BTC Up/Down five-minute discovery and structural identity contract.
- Control plane with 31 invariants.
- Transaction core and hardened `publish_raw_scan()`.
- Crash-safe marker lifecycle and immutable artifact/sidecar/manifest publication.
- Forward-only raw transaction recovery V2.
- Hostile publisher and recovery tests.

## Phase II-C scope

Phase II-C must integrate:

1. compatibility fix for legacy `InvariantResult` summaries;
2. startup recovery before scanner enablement;
3. one authoritative transactional raw chain;
4. publisher integration in the real scan flow;
5. committed manifest-chain reader;
6. Docker process supervision and readiness semantics;
7. hostile crash and same-volume restart tests;
8. exact-head, read-only CI evidence.

## Storage contract

Target transactional root:

```text
/app/polymarket/results/h011_v3/raw_chain_v1
```

Legacy paths remain read-only and are never auto-migrated:

```text
/app/polymarket/results/v3/raw
/app/polymarket/results/v3/scans
/app/polymarket/results/v3/state
bundle_*.json
YYYY-MM-DD.events.jsonl.gz
v3_scan_*.jsonl
```

The production Northflank volume and filesystem capabilities remain unverified. This is a deployment gate, not a code-construction gate. The filesystem probe must not be run against production without explicit authorization.

## Known inherited failure at Phase II-C start

```text
tests/cp/test_control_plane.py::
TestInvariants::
test_unknown_not_collapsed_to_zero
```

Root cause: the legacy shim returned `InvariantResult` objects while re-exporting a summary function that expected mappings. Phase II-C normalizes only at the compatibility boundary and preserves UNKNOWN, severities, and the 31-invariant catalog.

## Historical evidence

- Recovery audit run: `29609269756`
- Recovery artifact: `8418084299`
- Recovery digest: `sha256:f1646f789418f765d05554bb47e6520dabc21be603780006fe89355e223e0067`
- PR #5 control-plane smoke: `29617926232`
- PR #3 Docker smoke: `29617926234`

Historical PR smokes used GitHub's synthetic merge ref and are not sufficient as final Phase II-C exact-head evidence.

## Prohibitions

No merge, deploy, restart, Northflank mutation, volume mutation, secret access, wallet connection, real order, real fill, capital movement, force-push, rebase, or evidence deletion is authorized.

## Current milestone

```text
PHASE_IIC_BRANCH_CREATED=YES
INVARIANT_COMPATIBILITY_FIX=PASS
GLOBAL_BASELINE_08701669=542_PASSED
RUNTIME_TRANSACTION_INTEGRATION=IMPLEMENTED_LOCAL_VALIDATION_IN_PROGRESS
COMMITTED_READER=IMPLEMENTED_LOCAL_VALIDATION_IN_PROGRESS
STARTUP_RECOVERY=IMPLEMENTED_LOCAL_VALIDATION_IN_PROGRESS
PRODUCTION_CHANGED=NO
NORTHFLANK_CHANGED=NO
```

## Phase II-C implementation status

Implemented on the stacked branch worktree:

- legacy invariant compatibility normalization and regression tests;
- transactional `run_scan_v3` with one hardened stager/publisher/recovery path;
- authoritative root `results/h011_v3/raw_chain_v1`;
- committed manifest-chain reader and replay;
- startup recovery and explicit runtime-state store;
- Python PID-1 supervisor with liveness/readiness separation;
- atomic derived snapshot cache publication;
- manual isolated filesystem probe;
- hostile same-volume process/container restart tests;
- committed-reader API and visible dashboard error states.

Exact-head baseline run `29821019238` passed before runtime integration:

```text
H-011: 515 passed
global: 542 passed
Docker build/start: PASS
safety flags: PASS
artifact: 8491371840
digest: sha256:594ecaa1651be29340d7a74a5955c7b01a6ee6bfef01ba99028689a0f88dd875
```

Local focused Phase II-C tests pass. The local sandbox filesystem correctly fails the isolated `RENAME_EXCHANGE` probe, so hostile transaction/restart evidence must be produced by the Ubuntu/Docker CI gate.

## Next exact step

Publish the implementation commits to Draft PR #20, run the final exact-head Linux/Docker gate, correct only demonstrated failures, and preserve Northflank volume verification as the sole pre-deploy blocker.
