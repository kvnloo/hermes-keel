# Getting Started

Hermes Keel is currently a specification and Level 0 evidence repository. It is **not** an installable Hermes plugin, package, or execution backend. Starting Hermes in this checkout supplies project context only; it does not activate Keel.

## Prerequisite

Install and configure [Hermes Agent](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart) using its official documentation.

## Open the repository as harness context

Clone the public repository, then start Hermes with this checkout as its working directory:

```sh
git clone https://github.com/kvnloo/hermes-keel.git
hermes --in hermes-keel
```

Give the harness a bounded inspection request:

> Read `README.md`. Treat "Current scope" as the complete authorization boundary. Inspect the live Hermes configuration and runtime evidence before proposing any change. Do not implement Level 1 or later, do not assume a Keel plugin exists, and stop after reporting whether Level 0 is satisfied.

## Verify the sealed packet

The checked-in verifier uses only the Python standard library and Git:

```sh
python3 verify_level0.py
```

A pass validates the captured packet's exact nonce bytes and digest, task/run/worker binding, forbidden capability closure, effective MCP emptiness, repository occurrence count, redaction check, and Level 0 scope. It does not recertify a changed live Hermes runtime.

## Before proposing changes

1. Read [Invariants and Levels](/invariants-and-levels).
2. Confirm the current authorized level in `keel-level.json`.
3. Separate repository evidence from claims about the current runtime.
4. Stop before Level 1 unless the Captain has explicitly authorized promotion.

For the execution model behind the proof, see [Hermes Kanban](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban).
