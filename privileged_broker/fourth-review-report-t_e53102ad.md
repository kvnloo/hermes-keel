# Fourth Keel review — t_e53102ad

## Verdict

**CODE READY for the separately authorized Captain ceremony; not ceremony-approved.** No privileged action, approval creation, install, service mutation, Ollama mutation, sudo, or pkexec was performed.

## P0 invariants independently checked

- **Canonical mutation fence: CLOSED / TESTED.** `execute()` acquires SQLite `BEGIN IMMEDIATE` after preflight and before consume, validates task/run and request hash inside that transaction, and holds the transaction through mutation and health. A competing terminal writer is blocked; the injected terminal transition cannot complete and the mutation callback is not invoked. Duplicate, expired, unavailable, and connection-close fence cases fail closed.
- **Atomic authenticated generation: CLOSED / TESTED.** Ledger record plus authenticated snapshot tip are emitted by one temporary-file write, file fsync, rename, and directory fsync. Write/fsync failure leaves the prior complete generation; truncation, corruption, missing tip, and tip rollback fail closed. Health-boundary failure produces `rollback_verified`; commit-publication failure produces `recovery_required`; neither retries mutation or claims success.
- **Replay/chain integrity: CLOSED / TESTED.** Full chain, sequence, previous hash, record MAC, snapshot-tip MAC, generation, terminal hash, request/task/run/nonce binding are verified before execution.

## Verification run

- `python -m pytest -q`: **68 passed**
- `python -m unittest discover -s privileged_broker -p 'test*.py' -q`: **36 passed**
- `python -m py_compile privileged_broker/*.py`: **pass**
- `bash -n privileged_broker/install.sh privileged_broker/uninstall.sh`: **pass**
- `git diff --check`: **pass**
- ShellCheck: not installed; no pass claimed.

The unchanged third-review probes and fourth-repair matrix were exercised. The test suite contains the deterministic race, health/commit crash, write/fsync publication, stale fence, corruption/truncation, and tip-binding witnesses.

## Remaining live ceremony gates

These are intentionally not closed by this review and require a separately authorized Captain ceremony: F-002/K-002 descriptor/owner/mode/inode sealing of canonical DB, package, and runtime identities; F-003/K-005 sustained CUDA 3B/7B/27B and secret-canary evidence; F-004 descriptor-relative package ingestion plus kill-at-every-publication install rehearsal; K-006 approval chaining/idempotency and sealed executor identity; K-007 privileged uninstall/restoration rehearsal; K-008 install-time host/UID/path/device/policy identity manifest.

## Evidence hashes

- core.py: `d8d7ddb7e18e31145f78fa2dfd23458a154609bc9b7717ecbeb5c9d6f5da9b8c`
- third-review probes: `06947443fe0583f35503bd6f767b5f932100c94b4d9ab52596f2fffd8301da84`
- fourth-repair matrix: `70b759d6ab3c0ccb7d11945c7ff29900701c0ad848d361bd4a2962c5cd1b686e`
