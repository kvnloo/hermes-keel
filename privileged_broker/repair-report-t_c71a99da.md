# Keel privileged broker bounded repair — t_c71a99da

## Result

The four deterministic cold-review witnesses now assert fail-closed behavior and pass. This repair adds an authenticated durable ledger checkpoint, bounded/framed ledger parsing, preflight-before-consume ordering, repeated task/run freshness gates, and a durable operation phase journal. It also descriptor-anchors request/key loading and rollback deletion, adds installer cleanup on partial publication, and makes uninstall refuse while a broker drop-in exists and remove reusable authority while retaining ledger/checkpoint audit evidence.

This is an implementation handoff, not approval. No sudo, pkexec, install, approval, service, Ollama, or root mutation occurred. Bootstrap remains fail-closed pending independent child re-review t_b3b69de5.

## State machine

Durable phases are `prepared`, `consumed`, `mutation_started`, `health_passed`, `committed`, `rollback_started`, `rollback_verified`, and `recovery_required`; read-only rejection uses `preflight_rejected`.

`execute()` now:

1. validates request, canonical task/run and sole approval under the executor lock;
2. verifies the ledger and authenticated checkpoint;
3. performs backend read-only preflight before spend;
4. records a non-spending rejection receipt on preflight failure;
5. revalidates task/run, records prepared, revalidates, consumes exact approval/request/pre-state, revalidates again;
6. records mutation-start before invoking mutation;
7. records health-pass, revalidates canonical authority before commit;
8. records rollback/recovery phases on failure and never auto-re-executes a spent request.

A terminal append failure is converted to a durable `recovery_required` record when the journal remains writable. Any ledger/checkpoint mismatch fails closed.

## Ledger checkpoint

`ledger.jsonl.checkpoint` is atomically replaced and directory-fsynced after each ledger record. It is authenticated with an HMAC subkey domain-separated as `keel-ledger-checkpoint-v1` and binds ledger identity, sequence, terminal record hash, request, task, run, nonce, and terminal state. Verification rejects missing/deleted, stale, truncated, partial-frame, oversized, malformed, reordered, wrong-key, or mismatched state. The root-only 32-byte authority key remains inaccessible to unprivileged callers and uninstall removes it to prevent a residual signing oracle.

Bootstrap/rotation/recovery rule: there is no implicit checkpoint bootstrap for a non-empty ledger. A missing or mismatched checkpoint is `recovery_required`; an operator must preserve the immutable ledger/checkpoint pair and perform an independently reviewed rotation/recovery. Automatic mutation replay is forbidden.

## File/symbol mapping

- `core.py:_records`, `_verify_records`, `verify_chain`, `append_chain`: bounded framing, chain validation, authenticated terminal checkpoint.
- `core.py:execute`, `_phase`: preflight-before-spend, repeated freshness checks, durable phase journal and terminal recovery classification.
- `core.py:OllamaBackend.rollback`: descriptor-relative no-follow identity/hash validation and unlink.
- `broker.py:load`, `load_captain_request`, `load_bytes`: descriptor/no-follow bounded request, queue, and key reads; approval display includes task/run/Captain UID.
- `install.sh:cleanup`: prepublication collision checks and cleanup of partially published library/sbin artifacts.
- `uninstall.sh`: refuses unresolved runtime effect; removes policy/code/queue/key; retains ledger/checkpoint evidence.
- `test_rereview_t_63866ca7.py`: four cold-review witnesses converted RED→GREEN without changing security intent.

## Closure status

Closed by deterministic invariant/test: F-001 phase/preflight/rollback classification; F-005 complete-tail checkpoint defect; K-001 freshness race; K-003 rollback pathname race; K-004 prompt/request descriptor gap; K-007 unsafe uninstall behavior.

Partially closed and explicitly gated from bootstrap pending independent review/live rehearsal: F-002 broader process/model/systemd descriptor coverage; F-003 sustained production L3 runtime proof; F-004 fully descriptor-relative package ingestion and kill-at-every-boundary fixture; K-002 canonical SQLite descriptor/owner sealing; K-005 complete secret-canary matrix; K-006 approval-chain/idempotency/rate controls; K-008 install-time portability identity manifest. These gates do not authorize bootstrap and are represented as `partial_gated`, not closed.

## Verification executed

- `python -m pytest -q` → 57 passed.
- `python -m unittest discover -v` → 50 passed.
- `python -m py_compile privileged_broker/*.py` → pass.
- `sh -n privileged_broker/build-package.sh privileged_broker/install.sh privileged_broker/uninstall.sh` → pass.
- `/usr/sbin/visudo -cf privileged_broker/hermes-privileged-broker.sudoers` → parsed OK.
- `git diff --check` → pass.
- Static prohibited-code search found matches only in historical report prose, not executable source.
- ShellCheck is unavailable (`command -v shellcheck` exit 1); it was not installed.

## Constraints

No privileged command or state mutation was performed. The whole `privileged_broker/` tree remains untracked alongside unrelated untracked work, so no coherent owned commit was safe without also adopting pre-existing review artifacts. All unrelated work was preserved.
