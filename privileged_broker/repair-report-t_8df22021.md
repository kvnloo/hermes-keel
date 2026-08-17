# Keel bounded repair report — t_8df22021

## Result

Implementation complete for fourth independent review. No privileged action, approval, install, service, Ollama, sudo, or pkexec operation was performed.

## TR-001 / K-001 — canonical mutation fence

`execute()` now acquires `BEGIN IMMEDIATE` on the canonical Kanban SQLite database after preflight and before authority consumption. The active task/run and request-hash binding are validated inside that transaction. The transaction is held through the first mutation, health verification, and result construction, so canonical terminal transitions are serialized against mutation rather than sampled by polling.

The fence is fail-closed: busy/unavailable canonical DB, terminal state before acquisition, duplicate acquisition, or monotonic lease expiry rejects. The OS/SQLite releases stale fences when a process or connection dies. No broker authority table or parallel ledger was added. Fence validity is checked before consume, before and after `mutation_started`, after mutation, and after health.

The prior deterministic race injection now causes the competing terminal update to fail at the canonical SQLite write fence; the mutation callback is never invoked and `recovery_required` is durably recorded.

## TR-002 / F-001 / F-005 — atomic ledger generations

The split append-plus-checkpoint publication was replaced by a single rename-published snapshot generation. Each generation contains the complete authenticated chain and one authenticated `ledger-snapshot-tip` binding generation, sequence, terminal record hash, request/task/run/nonce and state. `_atomic_write()` writes fully, fsyncs the temporary file, renames once, and fsyncs the directory; temporary files are uniquely named and removed on pre-rename failure.

At every pre-rename failure, the prior generation remains complete and verifiable. At a post-rename/directory-fsync failure, the complete next generation is observable and verifiable, allowing the caller to append rollback or `recovery_required` without replaying mutation. Missing tip, truncation, corruption, wrong key and tip rollback fail closed.

The third-review health boundary now rolls back and seals `rollback_verified`; the commit publication boundary seals `recovery_required` without replaying mutation or claiming success.

## Verification

- Full pytest: 68 passed.
- Full unittest discovery: 61 passed.
- Prior four re-review probes: pass.
- Third-review three P0 probes, preserving race/crash injection intent with safe assertions: pass.
- New fence/generation matrix: 8 passed.
- `py_compile`: pass.
- shell syntax for build/install/uninstall: pass.
- sudoers parse: pass.
- `git diff --check`: pass.
- ShellCheck: unavailable; no pass claimed.

## Finding reconciliation

Code-closable in this bounded repair:

- F-001: P0 crash ambiguity closed by atomic generations and deterministic rollback/recovery publication.
- F-005: split checkpoint and valid-tail concerns closed by authenticated single-file snapshot generations.
- K-001: point-in-time race closed by canonical SQLite write serialization.
- K-003/K-004: prior descriptor-safe rollback and exact Captain prompt fixes preserved.

Still live ceremony/preflight gates, not self-approved here:

- F-002/K-002: broader descriptor/owner/mode/inode sealing of canonical DB, package and runtime identities.
- F-003/K-005: live sustained 3B/7B/27B CUDA and secret-canary evidence.
- F-004: descriptor-relative package ingestion and kill-at-every-publication install matrix.
- K-006: approval chaining/idempotency and fully sealed executor identity.
- K-007: privileged uninstall/restoration rehearsal.
- K-008: sealed install-time host/UID/path/device/policy identity manifest.

Bootstrap and Captain ceremony remain prohibited until the independent reviewer affirms P0 invariants and enumerates exact remaining live checks.

## Hashes

- core.py: d8d7ddb7e18e31145f78fa2dfd23458a154609bc9b7717ecbeb5c9d6f5da9b8c
- broker.py: e544ce5ea328487f1623dca016cd6c5c6ba4a71eff5cfa0f35bd0b3a41b447fc
- install.sh: 31921ed195cc4e622c991dc0622379ce343ef6e9bcec474a498943e6e19924c7
- uninstall.sh: 34246e6dc551522860898832225e279c34c996a97fa0118472d8a3f6d0e77a74
- third-review probes: 06947443fe0583f35503bd6f767b5f932100c94b4d9ab52596f2fffd8301da84
- fourth-repair matrix: 70b759d6ab3c0ccb7d11945c7ff29900701c0ad848d361bd4a2962c5cd1b686e
