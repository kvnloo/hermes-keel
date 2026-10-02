# OSS Level-0 Capability Receipts

**PER-1299 specification:** evidence system for OSS Hermes workers executing Level-0 claims via canonical Hermes mesh dispatch.

## A. Intent — evidence/capability, not a bus

This document specifies a **receipt protocol** for OSS Hermes workers proving they satisfied an authorized Level-0 claim without compromising safety boundaries. It is not a messaging transport, not a general-purpose execution bus, not a Hermes replacement, and not a production system.

The mesh owns dispatch, messaging, and Kanban lifecycle. Keel Level-0 defines **authorize + receipt only**: an OSS worker receives a mesh-dispatched claim (as a Kanban task), performs the authorized action in a located, fail-closed environment, and returns a signed receipt the Captain can verify offline. The receipt proves placement, origin-post gate, fail-closed mode, and HITL binding without giving the worker production authority.

## B. Non-goals — Hermes mesh owns bus; keel Level-0 is authorize+receipt; NO keel.service; NO production flip; NO Level≥1; NO install recipe

**This document explicitly defers and excludes:**

- **NO Hermes mesh replacement.** Canonical dispatch, messaging, session lifecycle, tool resolution, and Kanban execution remain with Hermes Agent.
- **NO keel.service.** No systemd service, no daemons, no long-running Keel process. Keel Level-0 is a verification and receipt library, not a service.
- **NO production_enabled flip.** The receipt system assumes `production_disabled` / `production_enabled: false` fail-closed mode. Flipping to production is forbidden at Level 0.
- **NO Level≥1 capabilities.** No Kanban tracer, no portfolio automation, no Firstmate subordinates, no PM integration, no durable run stores, no crash recovery. Those capabilities require explicit Captain approval and promotion beyond Level 0.
- **NO install recipes or automated deployment.** This is a constitutional spec, not a turnkey installer.

## C. Wire: claim (mesh.poll-shaped) + signed receipt

**Normative requirements:**

- A Level-0 claim MUST identify `intent_id`, `worker_id`, `task_id`, `task_revision`, and a placement locator.
- A Level-0 completion MUST be a signed receipt over a canonical encoding of the receipt body; verifiers MUST reject tampered or incomplete signed records.
- Peers MAY exchange claims using a mesh.poll-shaped envelope; Hermes mesh owns transport, Level-0 owns authorize+evidence semantics.

### Claim structure (mesh → worker, Kanban task-shaped)

When the Hermes mesh dispatcher assigns a task to a Level-0 capable worker, the worker receives:

```json
{
  "intent_id": "i_abc123",
  "task_id": "t_c8dc8afb",
  "task_revision": 1,
  "worker_id": "canary-worker",
  "authorized_action": "nonce-proof",
  "placement": {
    "host_id": "laptop-kvn",
    "workspace_path": "/workspace/zer0/oss/hermes-keel",
    "git_branch": "main"
  }
}
```

The worker MUST NOT execute if `placement` is incomplete. A claim with only `host_id` and no `workspace_path` or `git_branch` is **not located** and MUST be rejected.

### Receipt structure (worker → Captain, signed)

After successful execution, the worker produces a **signed canonical JSON (JCS) receipt**:

```json
{
  "receipt_version": 1,
  "intent_id": "i_abc123",
  "task_id": "t_c8dc8afb",
  "task_revision": 1,
  "worker_id": "canary-worker",
  "outcome": "completed",
  "evidence_digest": "sha256:29bc565c42aeaa8c4701ffba291c30594638cc13f865351037b7cb3ba1660c98",
  "placement": {
    "host_id": "laptop-kvn",
    "workspace_path": "/workspace/zer0/oss/hermes-keel",
    "git_branch": "main",
    "git_commit": "78f74a39480130a22d49c751374f3dcf217be6df"
  },
  "timestamp_utc": "2026-09-10T05:30:00Z",
  "signature": "base64-encoded-ed25519-sig"
}
```

The signature covers the **canonical JSON serialization (RFC 8785 JCS)** of all fields except `signature`. The Captain verifies the signature using the worker's registered public key before accepting the receipt.

## D. Locator + origin-post gate

**Normative requirements:**

- A placement locator MUST include `host_id`, an absolute `workspace_path`, and `git_branch`. A host_id-only placement MUST be treated as not located.
- An origin GitHub write MUST be denied unless the target repository is a `kvnloo/*` private fork AND the claimed branch is present in that repository's fetchable refs.
- Absence of a locator MUST fail closed for any operation that would publish or attach origin work.

### Placement locator (3-tuple requirement)

A **complete placement locator** requires:

1. `host_id` — uniquely identifies the execution host (e.g., hostname, machine-id, or stable node identifier)
2. `workspace_path` — absolute filesystem path to the working directory
3. `git_branch` — the Git branch the worker is on when executing

**Critical rule:** A claim specifying only `host_id` without `workspace_path` and `git_branch` is **not located** and MUST be rejected. The worker cannot prove where the work happened or what source revision was active.

### Origin-post DENY gate

The worker MUST verify **before execution**:

- The Git remote origin is a **private fork under `kvnloo/*`** (e.g., `kvnloo/hermes-keel`).
- The specified `git_branch` is **fetchable from the remote** (i.e., exists and is pushed).

**DENY otherwise.** If the origin is not a `kvnloo/*` private fork, or if the branch is local-only or unpushed, the worker MUST reject the claim and return a `rejected` receipt with reason `origin_post_gate_failed`.

This gate prevents execution of arbitrary local-only code and ensures the Captain can inspect the same source revision the worker used.

## E. Fail-closed production + revision binding

**Normative requirements:**

- When `production_enabled` is false, intake MUST nack with a production-disabled reason; liveness probes MUST NOT report production as active.
- A claim's `task_id` and `task_revision` MUST match the bound HITL/Captain approval revision; mismatch MUST deny the claim.
- Enabling production or starting a keel service is out of scope for Level-0 library semantics and MUST be a separate, explicitly authorized activation.

### Fail-closed production mode

When `production_enabled` is false, intake MUST nack (reject) the claim with a `production-disabled` reason. The worker checks:

```python
if not config.get("production_enabled", False):
    return reject_receipt(reason="production-disabled")
```

The fail-closed default is DENY. Happy-path claims that need production use an isolated peer with `production_enabled: true`; the live config stays false. This ensures production work is explicitly gated and isolated.

### HITL/Captain binding: task_id + task_revision

The worker MUST verify:

- The `task_id` in the claim matches the Kanban task identifier exactly.
- The `task_revision` in the claim matches the immutable task revision (one leaf) exactly.

**If the revision does not match, reject the claim.** This binds the receipt to a single, immutable HITL/Captain-approved task snapshot. The worker cannot silently upgrade to a later revision or execute a different task.

## F. Non-Hermes workers via adapters (identity only)

OSS workers not running the full Hermes Agent stack (e.g., minimal Python/Rust executors, container sidecars, or embedded devices) MAY participate **via identity adapters**.

An adapter provides:

1. **Worker identity** — a stable `worker_id` and registered Ed25519 keypair for signing receipts.
2. **Claim polling** — fetches pending claims from the mesh (via an adapter shim, not directly from Hermes).
3. **Receipt submission** — signs and returns the receipt to the mesh.

The adapter does NOT provide tool resolution, session management, or messaging ingress. Those remain with Hermes. The adapter is a **read-only identity bridge**, not an execution engine.

**INTERP note:** Hermes-native workers already have identity (profile name) and signing keys. Non-Hermes workers need only the signing protocol, not the full Hermes runtime.

## G. Out of scope / deferred

The following are **explicitly out of scope** for Level-0 receipts and deferred to Level 1 or later:

- **host_power / ASG (Auto-Scaling Groups):** Dynamic host provisioning, power management, and fleet scaling.
- **Role LeaseStore fencing:** Distributed lease coordination and fencing tokens for multi-host workers.
- **Durable PlacementLease / RunBinding / Trace stores:** Persistent state stores for long-running tasks, crash recovery, and audit trails.
- **Linear-inside-keel:** Integrating Linear issue tracking directly into Keel's execution model.
- **systemd service or daemon:** No long-running Keel process. Level-0 is library-only.
- **Taildrop / A2A transport:** Peer-to-peer file/artifact transport between workers.
- **Executors beyond Hermes:** General-purpose executor backends (e.g., Temporal, Celery, AWS Step Functions) are deferred.

## INTERP: Mapping Level-0 concepts to hermes-agent hooks

This table shows how Level-0 receipt concepts **interpret** existing Hermes Agent mechanisms. It is a clarification, not new code.

| Keel Level-0 concept | Hermes Agent hook / mechanism |
|---|---|
| `intent_id` | Captain intent message or instruction identifier (contextual; may be Telegram message ID) |
| `task_id` | Canonical Hermes Kanban task identifier (e.g., `t_c8dc8afb`) |
| `task_revision` | Immutable Kanban task snapshot revision (one leaf, HITL-bound) |
| `worker_id` | Hermes profile name (e.g., `canary-worker`) |
| Placement locator | Worker's runtime environment: `host_id` from hostname/machine-id, `workspace_path` from `--in` flag, `git_branch` from Git state |
| Origin-post gate | Worker pre-execution check: `git remote get-url origin` + `git ls-remote origin <branch>` |
| Fail-closed production | Keel config `production_enabled: false` checked at intake before dispatch |
| HITL/Captain binding | Dispatcher ensures claim carries immutable `task_revision`; worker rejects revision mismatches |
| Signed receipt | Ed25519 signature over JCS-serialized receipt; Captain verifies offline using worker's registered public key |
| Tool permissions | Hermes profile `tools` allowlist (Level-0 router has no shell/file/Git; worker has implementation tools) |
| Gateway approvals | Hermes Telegram gateway forwards instructions but cannot execute (Level-0 boundary) |
| Session ownership | Hermes session belongs to one profile; dispatcher spawns worker session from Kanban task |

## References

### Repository artifacts

- [README.md](https://github.com/kvnloo/hermes-keel/blob/main/README.md) — constitutional scope and Level-0 authorization boundary
- [docs/level-0-evidence.md](https://github.com/kvnloo/hermes-keel/blob/main/docs/level-0-evidence.md) — nonce proof, capability closure, and verifier instructions
- [docs/invariants-and-levels.md](https://github.com/kvnloo/hermes-keel/blob/main/docs/invariants-and-levels.md) — staged promotion ladder and constitutional constraint
- [keel-level.json](https://github.com/kvnloo/hermes-keel/blob/main/keel-level.json) — machine-readable authorization record
- [verify_level0.py](https://github.com/kvnloo/hermes-keel/blob/main/verify_level0.py) — deterministic packet integrity verifier
- [Hermes Keel documentation site](https://kvnloo.github.io/hermes-keel/) — published specification and proof

### Mesh modules (reference, not install)

The hermes-mesh-keel repository (if it exists) contains **slim reference modules** for receipt signing, JCS canonicalization, and claim validation. These are **not installable packages** at Level 0. They are code examples only, illustrating the receipt protocol for implementers.

### Delivery path

This document is the **specification home** for Level-0 capability receipts. After PR merge, a comment-first copy may be posted to [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) discussions or issues as a **proposal for community review**, not as a merge target. The authoritative version remains in [kvnloo/hermes-keel](https://github.com/kvnloo/hermes-keel).
