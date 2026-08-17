# Third independent review — Keel broker t_b3b69de5

## Verdict

**CHANGES REQUIRED — not suitable for bootstrap or a Captain ceremony.**

The repair closes the original complete-valid-tail truncation witness and correctly moves failed preflight before authority consumption. However, three new deterministic P0 probes demonstrate two remaining classes of unsafe behavior:

1. a task/run can become terminal after the final freshness check and durable `mutation_started` append, yet mutation still executes; and
2. a crash/failure after appending `health_passed` or `committed` but before replacing its checkpoint leaves a valid new ledger record plus a stale checkpoint. The exception path cannot append rollback or `recovery_required`, because every subsequent `append_chain()` first rejects the stale checkpoint. Execution escapes without rollback/reconciliation; the persisted state is fail-closed for replay but operationally stranded and cannot establish success or the required recovery action.

No sudo, pkexec, install, approval, service, Ollama, bootstrap, or root mutation occurred. This verdict addresses ceremony suitability only and does not execute or authorize a ceremony.

## Required acceptance checks

| Requirement | Result | Evidence |
|---|---|---|
| Authenticated checkpoint defeats valid-tail truncation | PASS | unchanged `test_complete_tail_truncation_is_detected` passes; checkpoint binds sequence and terminal hash |
| Preflight failure does not consume authority or roll back absent mutation | PASS | unchanged `test_precheck_failure_does_not_spend_authority_or_call_rollback` passes; only `preflight_rejected` is recorded |
| Task/run terminal race prevents mutation | FAIL | `test_terminal_race_after_mutation_started_record_still_mutates` proves terminal transition after the last freshness check still permits `mutate` and `health` before later rollback |
| Every post-health/result crash reconciles without retry or false success | FAIL | health-checkpoint and commit-checkpoint crash probes both escape with `ledger-checkpoint-mismatch`; no rollback or recovery record can be appended |
| Descriptor/package/rollback/uninstall invariants | PARTIAL/GATED | request/key and rollback unlink improved; DB and package walks remain pathname-based, install remains multi-publication, uninstall refuses active effect rather than proving restoration |

## Crash and mutation state analysis

`append_chain()` durably appends a ledger frame, then atomically replaces a separate checkpoint. This is not one atomic commit. If checkpoint replacement fails after the ledger append, `verify_chain()` correctly detects mismatch, but there is no reconciliation routine that can authenticate and advance the checkpoint to the already-authenticated terminal ledger frame. The normal exception handler then calls `append_chain()` for rollback/recovery, which immediately fails on the mismatch. At `health_passed`, this prevents rollback from even being invoked. At `committed`, it prevents the advertised recovery record and leaves success unknowable to the executor despite committed bytes being present.

The authority race remains because `task_active()` is a point-in-time read. The final pre-mutation read is followed by `append_chain(mutation_started)` and then `backend.mutate()` with no lease/token CAS or recheck between record completion and mutation. The deterministic test transitions both task and run to done from the append boundary; mutation still runs. A later pre-commit check triggers rollback, but that does not satisfy “terminal race prevents mutation.”

## Finding matrix

- F-001: **OPEN P0** — phase records improved, but checkpoint split-brain prevents guaranteed rollback/recovery after post-health persistence failure.
- F-002: **PARTIAL/GATED** — selected descriptor-safe reads/unlink exist; broader systemd/process/model/package identity remains pathname-based.
- F-003: **PARTIAL/GATED** — local/CUDA/mock gates improved; sustained 3B/7B/27B live evidence and stronger socket/process identity remain absent.
- F-004: **OPEN P0** — package verification/copy is pathname-based and installation publishes library, command, state/key, and policy in separate steps. Cleanup is improved but no kill-at-every-boundary proof exists.
- F-005: **PARTIAL** — valid-tail deletion is detected, framing is bounded, and checkpoint is authenticated; append/checkpoint atomicity and recovery are not solved. Approvals remain unchained and share authority material.
- K-001: **OPEN P0** — final freshness-check-to-mutation race is deterministic.
- K-002: **OPEN/GATED** — canonical SQLite path lacks descriptor/owner/mode/inode sealing; queue/request parent identity remains only partially bound.
- K-003: **CLOSED TESTED** — descriptor-relative no-follow rollback deletion binds owner, type, and exact bytes.
- K-004: **CLOSED TESTED** — actual prompt displays task/run/Captain UID and requires full request hash; Captain identity still depends on fixed policy/environment assumptions covered by K-008.
- K-005: **PARTIAL/GATED** — malicious health evidence test exists; complete secret-canary failure matrix does not.
- K-006: **OPEN/GATED** — duplicate approval remains a durable ambiguity/DoS; approvals are not chained/idempotent and executor identity policy is not fully sealed.
- K-007: **PARTIAL/GATED** — uninstall safely refuses while the broker drop-in exists and removes reusable authority, but does not itself reconcile/restore an ambiguous operation; privileged rehearsal is absent by constraint.
- K-008: **OPEN/GATED** — host, UID, paths, device and policy assumptions remain hard-coded without a sealed install-time identity manifest.

## Deterministic probes

Unchanged four cold-review probes: **4 passed**.

New third-review P0 probes: **3 passed as defect witnesses**:

- terminal transition at the mutation-start boundary still permits mutation;
- health-record/checkpoint split escapes without rollback or reconciliation;
- committed-record/checkpoint split cannot persist `recovery_required`.

## Executed verification

- `python -m pytest -q privileged_broker/test_rereview_t_63866ca7.py` → 4 passed.
- `python -m pytest -q privileged_broker/test_third_review_t_b3b69de5.py` → 3 passed.
- pre-probe full `python -m pytest -q` → 57 passed.
- pre-probe `python -m unittest discover -v` → 50 passed.
- `python -m py_compile privileged_broker/*.py` → pass.
- shell syntax for build/install/uninstall → pass.
- `/usr/sbin/visudo -cf privileged_broker/hermes-privileged-broker.sudoers` → parsed OK.
- `git diff --check` → pass.
- ShellCheck unavailable; no ShellCheck pass is claimed.

## Required correction before fourth review

1. Replace ledger-then-checkpoint split with a recoverable transaction protocol. On startup, independently authenticate the complete ledger and checkpoint, distinguish exactly one valid pending successor from truncation/forgery, reconcile it idempotently, and test failures before/after every write/fsync/rename boundary. Never rely on writing a recovery record through a verifier that rejects the current state.
2. Close the task/run mutation race with an authoritative lease/fencing/CAS mechanism whose validity is consumed atomically with mutation authority, or define the board state as advisory and use a separate root-owned non-revocable post-consume authority. Point-in-time repeated reads cannot prove absence of a transition in the following instruction window.
3. Complete descriptor-relative package ingestion and kill-phase install/uninstall matrices, approval idempotency/chaining, DB identity sealing, secret-canary tests, and sealed install-time identity assumptions before ceremony approval.

## Source manifest

- `core.py`: `88d0acd6604592cafb26441ae0b9973e4d678c53c672f930cdfdd2fac5673354`
- `broker.py`: `e544ce5ea328487f1623dca016cd6c5c6ba4a71eff5cfa0f35bd0b3a41b447fc`
- `install.sh`: `31921ed195cc4e622c991dc0622379ce343ef6e9bcec474a498943e6e19924c7`
- `uninstall.sh`: `34246e6dc551522860898832225e279c34c996a97fa0118472d8a3f6d0e77a74`
- unchanged four probes: `2de87e717e48c3649df32f9c5a10e1821630fecfb34b078cf019f1f6381efdc8`
- third-review probes: `d548829af3f26b8176934a495b21e1bcb5804e04838d588d449f8a139d66d604`
