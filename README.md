# Hermes Keel

**A self-evolving, performance-based execution kernel for Hermes Agent.**

[Hermes Agent](https://github.com/NousResearch/hermes-agent) can route work across conversations, tools, profiles, and a durable Kanban board. Hermes Keel is the proposed governance layer that makes claims about that work mechanically testable. It defines capability boundaries, evidence requirements, staged promotion, and rollback around Hermes Agent's existing runtime. It does not replace that runtime or its Kanban execution kernel.

This repository is currently a **Level 0 constitutional and bootstrap specification**. It does not contain an installable Keel plugin or a general-purpose execution backend. Its job today is narrower: define the first safety boundary, prove it in the running Hermes system, and stop before adding more machinery.

**Documentation:** [read the published guide](https://kvnloo.github.io/hermes-keel/) or [browse its source](docs/index.md).

## Start here

Read this document from top to bottom before changing a Hermes configuration or dispatching work. The safe first action is inspection, not installation or implementation.

For a Hermes harness, open a session in this checkout with the supported working-directory flag:

```sh
hermes --in /path/to/hermes-keel
```

Then give the harness this instruction:

> Read `README.md`. Treat "Current scope" as the complete authorization boundary. Inspect the live Hermes configuration and runtime evidence before proposing any change. Do not implement Level 1 or later, do not assume a Keel plugin exists, and stop after reporting whether Level 0 is satisfied.

The command only starts Hermes in this repository; it does not install or activate Keel. See the [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs) for Hermes installation and CLI setup.

## North star

Maximize verified useful progress per unit of time, compute, Captain attention, and risk—within hard authority and evidence constraints.

## Boundaries

- **Hermes Agent owns:** messaging, profiles, tools, sessions, Kanban tasks/runs, and worker processes.
- **Keel owns:** role capabilities, execution invariants, evidence chains, adversarial probes, performance policy, governed evolution, and rollback.
- **[Firstmate](https://github.com/kunchenguid/firstmate) may own:** optional subordinate supervision, worker crews, worktrees, validation, and the pull-request lifecycle for an already authorized Hermes task. It is a complementary subordinate executor, not a co-equal source of execution truth.
- **[PM](https://github.com/kvnloo/_pm) may own:** product, portfolio, and project intent, prioritization, acceptance criteria, and company-level semantics. It is a complementary intent and management system, not a co-equal source of execution truth.
- **External dashboards and projections may display state:** they never define execution truth.

## Constitutional rule

Keel may be self-modifiable, but never self-authorizing. A running kernel cannot approve weakened authority boundaries or evidence requirements. Changes require an isolated experiment, frozen evaluator, adversarial evidence, explicit promotion authority, and a rollbackable version.

## Levels

Exactly one invariant is introduced and proven at a time. Advancement requires runtime evidence and explicit Captain approval.

| Level | Invariant |
|---:|---|
| 0 | The Telegram-facing router cannot execute project work directly. |
| 1 | Every execution is a canonical Hermes Kanban task. |
| 2 | Every task has a distinct durable run. |
| 3 | Every successful run has durable evidence. |
| 4 | Every completion durably wakes its owner. |
| 5 | Worker crashes are detected and recoverable. |
| 6 | Review is a separate durable run. |
| 7 | Product-specific persistent profiles may be introduced. |
| 8 | Portfolio replenishment may be introduced. |
| 9 | Firstmate may become an optional subordinate execution backend. |
| 10 | External systems may become projections of execution truth. |

## Current scope

Only **Level 0** is authorized:

1. Provision exactly one disposable `canary-worker` profile without messaging ingress.
2. Remove all project-implementation capabilities from Telegram-facing `default`.
3. Prove the router cannot execute directly.
4. Stop.

A Kanban tracer and product work are not authorized until Level 1.

## Resources

- [Hermes Keel documentation source](docs/index.md)
- [Hermes Keel documentation site](https://kvnloo.github.io/hermes-keel/)
- [Hermes Agent source](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs)
- [Hermes Agent Kanban documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban)
- [Firstmate source](https://github.com/kunchenguid/firstmate)
- [PM public mirror](https://github.com/kvnloo/_pm)
