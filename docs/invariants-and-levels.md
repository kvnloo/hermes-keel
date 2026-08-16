# Invariants and Levels

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

## Current authorization

Only **Level 0** is authorized:

1. Provision exactly one disposable `canary-worker` profile without messaging ingress.
2. Remove all project-implementation capabilities from Telegram-facing `default`.
3. Prove the router cannot execute directly.
4. Stop.

A Kanban tracer and product work are not authorized until Level 1.

## Constitutional constraint

Keel may be self-modifiable, but never self-authorizing. A running kernel cannot approve weakened authority boundaries or evidence requirements. Changes require an isolated experiment, frozen evaluator, adversarial evidence, explicit promotion authority, and a rollbackable version.

The machine-readable authorization record is [`keel-level.json`](https://github.com/kvnloo/hermes-keel/blob/main/keel-level.json). It includes historical local mutation paths because it records the environment in which Level 0 was established; those paths are evidence, not setup instructions.
