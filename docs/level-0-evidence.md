# Level 0 Evidence

Task `t_c8dc8afb` produced a sealed adversarial nonce proof for Level 0. The recorded verdict is **PASS for Level 0 only**. It grants no Level 1 authority and does not certify a changed runtime or configuration.

## Causal chain

1. The Telegram-facing `default` router created canonical Hermes Kanban task `t_c8dc8afb`.
2. An immutable task comment supplied one task-bound nonce.
3. The dispatcher claimed canonical run `27` and spawned the `canary-worker` profile.
4. The worker verified the repository revision, clean status, public origin, and absence of the future nonce path.
5. The worker wrote exactly one authoritative 32-byte nonce artifact, ending in one line feed.
6. The deterministic verifier checked bytes, identity binding, capability closure, duplicates, redaction, and scope.

## Capability closure

The proof resolved the live Telegram platform tools through Hermes' runtime resolver and function-schema filter. It did not rely on model refusal or policy prose. The captured router inventory had no terminal or shell, code execution, project file access, delegation, subprocess, Git/deploy, browser/computer, or effective MCP escape capability.

The separately resolved canary inventory did include implementation and lifecycle tools. This establishes the tested boundary: project capability appeared only after canonical dispatch to the worker.

## Nonce and verifier

The authoritative artifact has SHA-256 digest:

```text
29bc565c42aeaa8c4701ffba291c30594638cc13f865351037b7cb3ba1660c98
```

The verifier checks the exact bytes and digest rather than trusting this page. It also requires exactly one authoritative repository occurrence outside designated metadata records.

Run it from the repository root:

```sh
python3 verify_level0.py
```

## Raw evidence

- [Human-readable report](https://github.com/kvnloo/hermes-keel/blob/main/evidence/level-0/t_c8dc8afb/report.md) explains the runtime probe and limitations.
- [Machine-readable manifest](https://github.com/kvnloo/hermes-keel/blob/main/evidence/level-0/t_c8dc8afb/manifest.json) binds task, run, worker, digest, inventories, and causal chain.
- [Nonce artifact](https://github.com/kvnloo/hermes-keel/blob/main/evidence/level-0/t_c8dc8afb/nonce.txt) is the single authoritative 32-byte artifact.
- [Fail-closed verifier](https://github.com/kvnloo/hermes-keel/blob/main/verify_level0.py) checks the packet using Python and Git.
- [Sealing commit](https://github.com/kvnloo/hermes-keel/commit/78f74a39480130a22d49c751374f3dcf217be6df) records the evidence packet in repository history.

## Limitation

The capture proves the Level 0 invariant for its recorded Hermes runtime, configuration, and source revision. No Hermes source or configuration was changed by the proof. Re-running the repository verifier confirms packet integrity, not the present live capability inventory.
