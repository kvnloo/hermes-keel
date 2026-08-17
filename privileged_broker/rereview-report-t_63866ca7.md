# Independent Keel broker re-review — t_63866ca7

## Verdict

**CHANGES REQUIRED — not suitable for bootstrap or for a Captain approval ceremony.**

The repair materially improves fixed-command confinement, checked rollback commands, runtime-locality checks, package hashing, and authenticated append records. It does not close the normalized P0/P1 queue. Four deterministic independent probes demonstrate: a valid ledger tail can be removed undetected; failed preflight still spends authority and invokes rollback; a task/run can become terminal after the only freshness check and mutation still proceeds; and a post-health result-write failure leaves only an undifferentiated consume record. Source inspection also confirms pathname/queue/package TOCTOU, partial installer publication, approval/rollback races, and uninstall persistence.

This is a review verdict only. No sudo, pkexec, installation, approval creation, service/Ollama mutation, bootstrap, or root write occurred.

## Evidence basis

Reviewed cold:

- original adverse review `t_0bb55798` and its F-001..F-005 artifacts;
- repair `t_3b6ac7a1`, complete report/findings, live source, tests, shell policy, build/install/uninstall paths;
- synthesis `t_aa62402d`, including P0/P1/P2 queue, crash state machine, RED→GREEN plan, K-001..K-008 mapping;
- live source hashes listed below.

The entire `privileged_broker/` tree is currently untracked, so there is no committed revision or git diff against a reviewed base to seal. Unrelated untracked `docs/token-master-shadow.md` and `token_master/` were preserved.

## Finding-by-finding result

| ID | Result | Independent finding |
|---|---|---|
| F-001 | PARTIAL / OPEN | Checked rollback command failures and post-state checks are improved. There is no durable phase journal or recovery classification. `execute()` consumes before preflight, calls rollback even when preflight failed before mutation, and can lose the terminal result after mutation/health. `rollback()` checks `is_symlink()` then separately unlinks the path, allowing path replacement between check and unlink. |
| F-002 | OPEN | Effective state is broad but pathname-based: `Path.resolve`, later reopen/hash, `/proc` path reads, `rglob`, and path-based systemd/drop-in/model-store accesses are not descriptor-anchored. It lacks boot ID, process start ticks/cgroup and socket inode binding. Revalidation is not immediately repeated before every side effect. |
| F-003 | PARTIAL / OPEN | Exact binary/version, a single name-matched daemon, loopback listener ownership, CUDA libraries/device FDs, model manifest and deterministic smoke are checked. PID identity is reusable and process discovery is basename-based; sockets are not inode-bound; the four-token rate is not a sustained benchmark; CPU/GPU correlation is not independently rehearsed; 7B/27B gates are absent. Production evidence cannot be inferred from mocks. |
| F-004 | OPEN | The unprivileged package is hashed, but the privileged installer validates and later reopens pathnames. Root ownership/mode does not seal a package whose parent can be renamed. Publication is non-transactional: library and sbin symlink are activated before state/key and sudoers; the cleanup trap removes only staging/policy staging, leaving published artifacts after later failure. No same-filesystem/version-pointer proof or kill-phase fixture exists. |
| F-005 | OPEN | Record edits/reorder/wrong key are detected, but there is no external trusted tip/checkpoint or framed EOF contract. A complete authenticated final record can be deleted and `verify_chain()` accepts the shortened prefix; the independent probe proves this. Approval records are not chained and the same root HMAC key authenticates approvals and execution history. |
| K-001 | OPEN / HIGH | Task/run freshness is checked once before consume. Independent probe transitions task and run to done during `check_pre`; mutation and successful result still occur. No recheck before mutation or commit. |
| K-002 | OPEN / HIGH | Canonical authority depends on a mutable user-owned SQLite DB and comments. `task_active()` uses pathname checks then opens separately, without descriptor identity/owner/mode sealing. Request loading resolves/stats/reads separately; root queue loading is plain `Path.read_bytes()`. |
| K-003 | OPEN / HIGH | Rollback symlink check and unlink are separate pathname operations. The drop-in parent/file identity is not descriptor-sealed across mutation and rollback. |
| K-004 | PARTIAL / OPEN | Approval prints hash, operation, host, risk, rollback and expiry and requires full-hash typing. It omits requester task/run and explicit Captain identity from the actual confirmation display; request opening is TOCTOU-prone. `PKEXEC_UID` is an environment assertion, not an independently sealed operator identity record. |
| K-005 | PARTIAL | Fixed commands and health-output suppression reduce leakage. However exact subprocess stdout/stderr and exception messages are persisted without an explicit field allowlist/redaction contract. No secret-canary mutation suite covers all failure paths. |
| K-006 | OPEN | Duplicate valid approval is deliberately ambiguous rather than idempotent, enabling durable denial. Ledger/model-tree reads are unbounded; no frame/record/store limits exist. Any permitted passwordless executor can spend the sole queue packet. |
| K-007 | OPEN / HIGH | `uninstall.sh` removes broker code/policy but does not inspect or remove/revert the broker-created Ollama drop-in, reload/restart the original service, quarantine queue state, or prove no privileged effect persists. |
| K-008 | OPEN | Host, Captain UID, home/board/request roots, GPU `/dev/nvidia0`, service paths and binary paths are hard-coded. No install-time sealed identity/boot/filesystem/polkit preflight proves those assumptions on the eventual ceremony host. |

## Normalized state-machine and crash review

Required state remains:

`REQUESTED → APPROVED → PREFLIGHTED → CONSUMED → MUTATION_STARTED → MUTATION_FINISHED → HEALTH_VERIFIED → COMMITTED`, with explicit rollback phases and `RECOVERY_REQUIRED` for ambiguity.

Current durable execution evidence has only `authorization-consumed` and `operation-result`. It cannot distinguish preflight failure, mutation not started, mutation partial, health complete, rollback started, or result append failure. The deterministic result-append probe performs precheck/mutation/health and leaves only `authorization-consumed`. Replay is blocked, which avoids duplicate mutation, but the exact state and required recovery action are unknowable.

## Approval, queue and operator binding

- `approve()` appends a receipt before publishing/replacing the queue; queue publication failure leaves a valid approval without a queue.
- Repeated identical approval appends a second valid receipt and bricks execution as ambiguous instead of idempotent no-op.
- Queue execution does not open `O_NOFOLLOW`, bind inode/bytes to consume, or move a sole packet atomically to `inflight/<request-hash>`.
- The actual approval display does not show task/run or Captain UID, despite README template prose doing so.
- Authority freshness is not checked at preflight completion, immediately before mutation, or before commit.

## Package/install/uninstall review

Positive: fixed file allowlist, hashes, root owner/mode checks, shell syntax, staged sudoers parsing, fixed absolute commands, and fsync calls.

Blocking:

1. Validation and copying are pathname-based and separable; no descriptor-relative no-follow walk binds verified bytes to installed bytes.
2. `LIB` is published at line 37 and sbin symlink at lines 38–39 before state/key and sudoers publication. Failures at lines 40–44 leave partial privileged installation because cleanup only removes `$STAGE` and `$POLICY_STAGE`.
3. Existing sbin/state/policy collision checks are incomplete and occur after some publication.
4. No kill-at-every-phase, EXDEV, concurrent install/uninstall, hardlink/FIFO/device, parent replacement, or cleanup state-machine fixture exists.
5. Uninstall leaves the operation-created systemd drop-in and possible switched runtime active.

## Ledger/truncation/key review

HMAC chaining authenticates present records but cannot prove historical completeness without an external sealed checkpoint. The probe deletes the complete second record and verification returns a valid one-record chain. The single root key is both approval and ledger MAC authority; compromise or misuse has no independent verifier boundary. JSONL has no bounded frame length or authenticated durable tip. Approval history is individually MACed but not sequenced/chained/revocable.

## Deterministic probes

Added review-only fixture `test_rereview_t_63866ca7.py`:

1. `test_complete_tail_truncation_is_not_detected` — GREEN as an exploit witness: shortened valid prefix is accepted.
2. `test_precheck_failure_still_spends_authority_and_calls_rollback` — GREEN as a state-machine witness.
3. `test_task_can_finish_after_precheck_and_mutation_still_runs` — GREEN as an authority-race witness.
4. `test_result_append_crash_leaves_only_consume_without_phase_evidence` — GREEN as a crash-ambiguity witness.

These tests intentionally assert observed unsafe/incomplete semantics. They are not evidence that the defects are fixed.

## Executed verification

- `python -m pytest -q privileged_broker/test_rereview_t_63866ca7.py` → 4 passed.
- `python -m pytest -q` after adding probes → 57 passed.
- `python -m unittest discover -v` after adding probes → 50 passed.
- `python -m py_compile privileged_broker/*.py` → pass.
- `sh -n privileged_broker/build-package.sh privileged_broker/install.sh privileged_broker/uninstall.sh` → pass.
- `/usr/sbin/visudo -cf privileged_broker/hermes-privileged-broker.sudoers` → parsed OK.
- `git diff --check` → pass.
- Static scan for `shell=True`, `subprocess.Popen`, `os.system(`, `NOPASSWD: ALL` → no prohibited match.
- **ShellCheck unavailable** (`command -v shellcheck` failed); no ShellCheck pass is claimed.

## Required corrections before another re-review

P0:

1. Implement descriptor-anchored request/DB/queue/pre-state/package/drop-in handling; bind inode/bytes and packet hash to consume.
2. Perform read-only deterministic preflight before spend, then recheck lease/task/run immediately before consume, mutation and commit; define cancellation after spend as recovery-required.
3. Add durable phase journal and inspect/reconcile fixed operation. Put terminal-result persistence inside the transaction; no success can escape without durable terminal evidence.
4. Replace rollback pathname check/unlink with descriptor-bound ownership and identity checks.
5. Add external authenticated ledger checkpoint/tip, bounded framing, independent key ownership, approval chain/revoke/idempotency, and truncation/torn-write tests.
6. Rebuild installer as descriptor-relative/versioned atomic publication with complete rollback cleanup, destination collision checks before publication, same-filesystem proof, and kill-phase fixtures.
7. Strengthen L3 runtime proof with boot/start/cgroup/socket-inode identity and sustained benchmark/CUDA correlation fixtures.
8. Make uninstall detect and safely revert/quarantine operation state, or refuse with an explicit recovery packet; prove no executable policy or systemd effect remains.

P1:

9. Display and bind exact task/run, operator identity, host, revision/package hash and expiry in the actual approval prompt; authenticate operator through verified policy rather than an environment value alone.
10. Add size/rate bounds, duplicate-approval idempotency, queue/inflight cleanup, secret-canary tests, and sealed install-time identity/host assumptions.

A new broad research card is unnecessary; the synthesis already specifies the correction queue.

## SHA-256 source manifest

- `core.py` `822fa72f5ed6a88129556d68130eec693a93c5a9185fe36995465276c9826d32`
- `broker.py` `2e9a98ed163dc78c29759dab23d419287405b19160a1f48980f124ea48ff1e60`
- `build-package.sh` `e443bfe798eb6af99faceb5ce4a160ccbb6ed1e372b8da0816dbea0fd11ff5b4`
- `install.sh` `2d93710fde9cdd1cbf429aedfa7c6f99087671be845d79bb73de76321f68ee3d`
- `uninstall.sh` `60c87fbc1a9448b5036ce0d354e545f2f15d9339261cbf8a3bb3f1a11f0d371e`
- `hermes-privileged-broker.sudoers` `259551c7e8874ce402e7408ef5b31820a1d940e7916b683d4d695a87a1211f5f`
- `README.md` `065468ca9f768f80953ad1ffe68a3df4aa825e1388a3467cbd4986bc72c70053`
- review probes `9ca608db57c31ce25180ae978692749e2221acd4709d202703abee750515f6bc`
