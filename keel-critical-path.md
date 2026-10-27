# Keel critical path — t_7074e58e

Status: **fail closed; Level 0 remains the only authorized level.**

## Runtime truth

- Keel revision: `6fe20cbfe5a16c073b8f2a801add00400dbc134b` before this task's uncommitted local K1 patch; branch was seven commits ahead of origin.
- Foreign/unowned paths were preserved: `.worktrees/`, `docs/token-master-shadow.md`, `privileged_broker` Phase-0/preflight artifacts, and `token_master/`.
- Gateway is active/running at PID 1164. The LF006 supervisor is enabled but crash-looping with `226/NAMESPACE`, `MainPID=0`, and observed restart count 4153. A lane report that described these units as inactive/not-found was superseded by this direct runtime observation.
- The exact certified controller was checked out detached at `77a4ea98cc994917c54d7df612ac631e41cbdd50`; its focused suite passed 15/15. Its production-sentinel, receipt replay/expiry/mismatch, manifest path/no-follow, concurrent receipt spend, and DB-swap tests are green.
- The current Keel tree has no broad Pythia fixture pack covering all requested Keel risks. Therefore smoke/lifecycle/adversarial Keel certification is **not claimed**. Missing fixtures are UNKNOWN/open, not silently passed.

## Priority spine

1. **K0 evidence cleanliness.** Level-0 passes from an isolated clean snapshot and the nonce mutation turns RED. It fails in the shared checkout only because `verify_level0.py` recursively traverses the sibling `.worktrees` copy. Do not add foreign paths to the packet.
2. **K1 LF006.** Local reversible repair is applied: manager-owned `RuntimeDirectory=hermes-keel`, mode 0700, no manual runtime-directory creation. 23 targeted tests and the 85-test repository suite pass. Live installation/restart remains gated.
3. **K2 broker.** Code regression suite is green, including nonce spend, replay, crash windows, task binding and publication controls. No live Phase-1 or authoritative runtime acceptance is claimed.
4. **K3 focused policy.** Bootstrap `9ed479168` correctly remains FROZEN/DENY. ACTIVE receipt parsing, key-provider integration and single-boundary dispatcher enforcement are missing and must remain fail closed.
5. **K4 Mesh containment.** No disposable competing-`:8787` fixture exists; transport-only containment is a design requirement, not runtime proof. Continuation `t_29ddc475` is pending.
6. **K5 dispatch/wake.** Require at least 30 sealed synthetic runs, complete causal traces, and zero dangling/orphan/duplicate claims while the production sentinel remains unchanged.
7. **K6 Level-1 candidacy.** Not a candidate until K0–K5 are runtime-proven, review is a separate durable run, and the Captain explicitly promotes the level.

The machine-readable queue is `keel-critical-path.json` and includes rank, evidence, confidence, ownership, dependencies, action type, exact files/units, pre-state hash, tests, rollback, review card, Captain gate, and status.

## Executed local work

Changed only:

- `supervisor/hermes-keel-lf006-supervisor.service.in`
- `supervisor/README.md`
- `supervisor/test_lf006_unit.py`

Verification:

- exact Harness Debug controller: 15 passed
- LF006 targeted: 23 passed
- Keel full pytest: 85 passed, 23 subtests passed
- privileged broker unittest: 51 passed
- docs build: passed
- `git diff --check`: passed

No sudo, production DB write, network route, credential action, daemon reload, service restart, authority activation, commit, or public push occurred.

## Created cards

- `t_1e00e134` — independent review of the K1 source/unit repair.
- `t_f35e5b39` — blocked exact-action LF006 activation ceremony, dependent on that review.
- `t_b31c971f` — K3 disposable ACTIVE-policy Pythia fixtures.
- `t_e032535e` — K4 disposable Mesh containment fixtures.
- `t_3e4e761e` — K5/K6 sealed N>=30 Level-1 measurement.

Existing `t_29ddc475` is the K4 continuation created by the K4 lane. Existing `t_71266e87` independently reviews this synthesis after completion. Stale queue `t_4e959efb` remains superseded and was not revived or deleted.

## Next Captain gate

Approve only `t_f35e5b39` after `t_1e00e134` passes: atomically install the reviewed LF006 unit, daemon-reload, and restart **only** `hermes-keel-lf006-supervisor.service`; verify one process, runtime directory 0700, socket 0600, unchanged gateway PID and unchanged board sentinel; otherwise restore the pre-state unit hash and stop LF006.
